# Codex Memory Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable native Codex memories and preserve auditable, resumable execution state across compactions and session boundaries through agentic-rag.

**Architecture:** A PostgreSQL checkpoint gateway records fast deterministic snapshots and later semantic enrichment. Codex lifecycle adapters remain thin and fail-open; `SessionStart(source="compact")` is the only model-context restoration point. A Codex installer losslessly merges global TOML and hook JSON and atomically installs the versioned compact prompt.

**Tech Stack:** Python 3.13+, PostgreSQL 17, psycopg 3, pytest, tomlkit, Codex lifecycle hooks, Codex CLI with ChatGPT authentication

**Spec:** `docs/superpowers/specs/2026-09-03-codex-memory-continuity-design.md`

## Global Constraints

- `agentic-rag` remains the canonical, audited memory and continuation store; native Codex memories are complementary.
- The active context uses `model_context_window = 600000`; automatic compaction uses `model_auto_compact_token_limit = 500000` and `model_auto_compact_token_limit_scope = "total"`, leaving a 100000-token reserve.
- Checkpoint capture and every lifecycle hook fail open; compaction, continuation, and shutdown never wait for an LLM or login.
- Every database mutation passes through a focused gateway and writes `audit_log` in the same transaction.
- Preserve foreign Codex/Claude settings, hooks, MCP registrations, and unknown configuration keys.
- Never store full diffs, transcript bodies, secrets, or unverifiable claims that a process remains active.
- Restoration is same-session first, same-canonical-project second, and never crosses projects.
- `PostCompact` performs bookkeeping/UI warnings only; only `SessionStart` emits restored `additionalContext`.
- Use the existing provider adapter, health artifact, circuit breaker, single-writer queue, and transcript cursor machinery.
- Keep `Stop`; add `SessionEnd` for the final delta and deduplicate both through the same enqueue path.
- Installation is active after verification, idempotent, backed up, and recoverable; changed hooks still require `/hooks` trust review.
- Keep root `BACKLOG.md` complete and blocker-first and create/update root `FEATURES.md` with shipped/planned discoverability.

---

## File Map

- `sql/006_continuity.sql` — checkpoint table, queue kind constraint changes, indexes, role grants.
- `agentic_rag/continuity/model.py` — immutable checkpoint input/output types and validation.
- `agentic_rag/continuity/store.py` — audited checkpoint create/upsert, enrichment, boundary marking, and selection.
- `agentic_rag/continuity/capture.py` — bounded Git/worktree/artifact snapshot and transcript cursor capture.
- `agentic_rag/continuity/render.py` — strict-budget continuation rendering and stale-state labels.
- `agentic_rag/continuity/enrich.py` — structured-output prompt/schema and enrichment application.
- `agentic_rag/integrations/codex/config.py` — comment-preserving Codex TOML merge.
- `agentic_rag/integrations/codex/hooks.py` — owned-hook definitions and lossless JSON merge.
- `agentic_rag/integrations/codex/install.py` — backups, atomic writes, prompt asset install, validation report.
- `agentic_rag/hooks/pre_compact.py` — synchronous snapshot plus priority enqueue.
- `agentic_rag/hooks/post_compact.py` — compaction-boundary bookkeeping without context injection.
- `agentic_rag/hooks/session_end.py` — final import-light mining enqueue.
- `agentic_rag/hooks/session_start.py` — restoration composed with existing pins/knowledge/health.
- `agentic_rag/jobs.py`, `agentic_rag/worker.py` — checkpoint-enrichment queue plumbing.
- `agentic_rag/status.py`, `agentic_rag/cli.py` — checkpoint freshness and pending-enrichment visibility.
- `agentic_rag/install.py` — orchestration of existing Claude and new Codex installers.
- `assets/codex/compact_prompt.md` — canonical global compaction prompt.
- `tests/test_continuity_*.py`, `tests/test_hook_*.py`, `tests/test_codex_install.py` — focused TDD coverage.
- README, handbook chapters, `CHANGELOG.md`, `BACKLOG.md`, `FEATURES.md` — user-facing behavior and operations.

---

### Task 1: Checkpoint schema and audited gateway

**Files:**
- Create: `sql/006_continuity.sql`
- Create: `agentic_rag/continuity/__init__.py`
- Create: `agentic_rag/continuity/model.py`
- Create: `agentic_rag/continuity/store.py`
- Create: `tests/test_continuity_store.py`
- Modify: `tests/test_db_init.py`
- Modify: `tests/test_roles.py`

**Interfaces:**
- Produces: `CheckpointSnapshot`, `Checkpoint`, `upsert_snapshot(conn, snapshot) -> Checkpoint`, `apply_enrichment(conn, checkpoint_id, enrichment) -> Checkpoint`, `mark_compacted(conn, session_id, cursor) -> bool`, `latest_for_session(conn, session_id) -> Checkpoint | None`, `latest_for_project(conn, project_root) -> Checkpoint | None`.
- Consumes: existing `audit_log`, `rag_writer`, `rag_reader`, and migration runner.

- [ ] **Step 1: Write failing migration and store tests**

```python
def test_checkpoint_upsert_is_idempotent_and_audited(conn):
    snap = CheckpointSnapshot(session_id="s1", turn_id="t1", cursor="u7",
                              source="PreCompact", trigger="auto",
                              cwd="/work/p", project_root="/work/p")
    first = store.upsert_snapshot(conn, snap)
    second = store.upsert_snapshot(conn, snap)
    assert second.id == first.id
    assert conn.execute("SELECT count(*) AS n FROM continuation_checkpoints").fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE op='checkpoint_snapshot'").fetchone()["n"] == 1

def test_new_cursor_supersedes_without_deleting(conn):
    old = store.upsert_snapshot(conn, snapshot(cursor="u7"))
    new = store.upsert_snapshot(conn, snapshot(cursor="u8"))
    assert store.get(conn, old.id).state == "superseded"
    assert store.get(conn, new.id).state == "open"
```

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run: `uv run pytest tests/test_db_init.py tests/test_roles.py tests/test_continuity_store.py -v`

Expected: FAIL because migration `006_continuity.sql` and the continuity package do not exist.

- [ ] **Step 3: Add the migration and typed model**

Create `continuation_checkpoints` with UUID primary key, session/turn/cursor identity, transcript fingerprint, CWD/project/Git fields, JSONB snapshot/enrichment/references/warnings, state and quality checks, `compacted_at`, and timestamps. Add `UNIQUE(session_id, cursor)`, same-session and `(project_root, state, updated_at)` indexes, writer mutation grants, reader SELECT grants, and an allowed `checkpoint_enrich` queue kind.

```python
@dataclass(frozen=True)
class CheckpointSnapshot:
    session_id: str
    turn_id: str | None
    cursor: str
    source: str
    trigger: str | None
    cwd: str | None
    project_root: str | None
    transcript_fingerprint: str | None = None
    git: Mapping[str, object] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
```

- [ ] **Step 4: Implement the transactional gateway**

Use `INSERT ... ON CONFLICT (session_id, cursor) DO UPDATE`, lock the current open session rows, supersede older cursors, and insert an `audit_log` row before one commit. Reject blank session/cursor values and unknown state/quality values before SQL.

- [ ] **Step 5: Run focused and migration tests**

Run: `uv run pytest tests/test_continuity_store.py tests/test_db_init.py tests/test_roles.py -v`

Expected: PASS, including writer/reader privilege checks and migration idempotency.

- [ ] **Step 6: Commit**

```bash
git add sql/006_continuity.sql agentic_rag/continuity tests/test_continuity_store.py tests/test_db_init.py tests/test_roles.py
git commit -m "feat: add audited continuation checkpoints"
```

---

### Task 2: Deterministic capture and bounded rendering

**Files:**
- Create: `agentic_rag/continuity/capture.py`
- Create: `agentic_rag/continuity/render.py`
- Create: `tests/test_continuity_capture.py`
- Create: `tests/test_continuity_render.py`
- Modify: `agentic_rag/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `CheckpointSnapshot`, stored `Checkpoint`, existing tolerant `build_digest()` cursor behavior.
- Produces: `capture_snapshot(payload, *, run=subprocess.run) -> CheckpointSnapshot`, `render_checkpoint(checkpoint, *, max_chars: int) -> str`.

- [ ] **Step 1: Add failing capture/config tests**

```python
def test_capture_records_bounded_git_state(tmp_path, fake_git):
    cp = capture.capture_snapshot(payload(tmp_path), run=fake_git)
    assert cp.project_root == str(tmp_path.resolve())
    assert cp.git["branch"] == "feat/x"
    assert cp.git["head"] == "abc123"
    assert len(cp.git["status"]) <= 4000

def test_capture_non_git_and_missing_transcript_still_has_cursor(tmp_path):
    cp = capture.capture_snapshot({"session_id": "s", "cwd": str(tmp_path),
                                   "transcript_path": None}, run=not_a_repo)
    assert cp.project_root is None
    assert cp.cursor.startswith("event:")
```

Add config defaults `checkpoint_status_max_chars=4000`, `checkpoint_render_max_chars=8000`, and `checkpoint_artifact_max=16` under `[continuity]`.

- [ ] **Step 2: Run and confirm failures**

Run: `uv run pytest tests/test_continuity_capture.py tests/test_continuity_render.py tests/test_config.py -v`

Expected: FAIL on missing capture/render modules and continuity config fields.

- [ ] **Step 3: Implement deterministic capture**

Invoke Git without a shell and with timeouts, passing the payload's `cwd` value
as the argument after `git -C`: run `rev-parse --show-toplevel`,
`rev-parse --git-dir`, `rev-parse --git-common-dir`,
`branch --show-current`, `rev-parse HEAD`, and `status --short`. Resolve paths
canonically, label detached HEAD, cap output, scan only named authoritative
artifacts (`AGENTS.md`, `CLAUDE.md`, `BACKLOG.md`, `FEATURES.md`, and
`docs/superpowers/{specs,plans}`), and hash transcript path/size/mtime without
storing transcript content.

- [ ] **Step 4: Add failing renderer tests**

```python
def test_renderer_is_bounded_and_reference_oriented(checkpoint):
    text = render_checkpoint(checkpoint, max_chars=500)
    assert len(text) <= 500
    assert "Next exact action" in text
    assert "[[relevant-slug]]" in text
    assert checkpoint.large_spec_body not in text

def test_renderer_labels_snapshot_and_stale_processes(checkpoint):
    text = render_checkpoint(replace(checkpoint, quality="snapshot"), max_chars=2000)
    assert "semantic enrichment pending" in text
    assert "revalidate" in text.lower()
```

- [ ] **Step 5: Implement ordered, truncation-safe rendering**

Render identity/quality, goal, remaining criteria, repository status, verified tests, blockers, next action, artifacts/slugs, and warnings in that priority order. Drop low-priority sections before truncating a line; always retain checkpoint id, blocker, and next action.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest tests/test_continuity_capture.py tests/test_continuity_render.py tests/test_config.py -v`

Expected: PASS.

```bash
git add agentic_rag/continuity/capture.py agentic_rag/continuity/render.py agentic_rag/config.py tests/test_continuity_capture.py tests/test_continuity_render.py tests/test_config.py
git commit -m "feat: capture and render continuation state"
```

---

### Task 3: Asynchronous semantic checkpoint enrichment

**Files:**
- Create: `agentic_rag/continuity/enrich.py`
- Create: `tests/test_continuity_enrich.py`
- Modify: `agentic_rag/jobs.py`
- Modify: `agentic_rag/worker.py`
- Modify: `tests/test_jobs.py`
- Modify: `tests/test_worker.py`

**Interfaces:**
- Consumes: `llm.run_structured(...)`, `build_digest(...)`, `apply_enrichment(...)`, existing `LLMUnavailableError` handling.
- Produces: `enqueue_checkpoint_enrichment(conn, *, checkpoint_id, session_id, transcript_path, after_cursor) -> bool`, `enrich_checkpoint(conn, cfg, job, runner) -> str | None`.

- [ ] **Step 1: Write failing enqueue and worker dispatch tests**

```python
def test_enrichment_enqueue_deduplicates_checkpoint(conn):
    assert enqueue_checkpoint_enrichment(conn, checkpoint_id=CP, session_id="s",
                                         transcript_path="/t", after_cursor="u1")
    assert not enqueue_checkpoint_enrichment(conn, checkpoint_id=CP, session_id="s",
                                             transcript_path="/t", after_cursor="u1")

def test_worker_dispatches_checkpoint_enrich(conn, cfg, monkeypatch):
    seen = {}
    monkeypatch.setattr(worker.enrich, "enrich_checkpoint",
                        lambda *a, **k: seen.setdefault("called", True))
    worker.process_job(conn, cfg, checkpoint_job())
    assert seen["called"] is True
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run pytest tests/test_jobs.py tests/test_worker.py tests/test_continuity_enrich.py -v`

Expected: FAIL because the new queue API and processor are absent.

- [ ] **Step 3: Implement the schema-constrained enrichment contract**

Define exact JSON fields: `goal`, `success_criteria`, `instructions`, `approvals`, `decisions`, `rejected_alternatives`, `completed_steps`, `remaining_steps`, `files`, `tests`, `processes`, `external_states`, `blockers`, `risks`, `next_action`, and `rag_slugs`. Strip secrets before the call, cap the digest using existing config, accept only JSON objects matching the schema, and never infer test success or process liveness.

- [ ] **Step 4: Integrate priority enqueue and provider recovery**

Order due jobs by an explicit priority expression so `checkpoint_enrich` precedes ordinary mining but does not starve backup/curation indefinitely. Route `LLMUnavailableError` through the unchanged lossless attempt restoration and provider-health artifact. Return the new digest cursor only after enrichment commits.

- [ ] **Step 5: Verify invalid output and auth recovery**

Run: `uv run pytest tests/test_continuity_enrich.py tests/test_jobs.py tests/test_worker.py tests/test_provider_health.py -v`

Expected: PASS for valid enrichment, malformed output retry, provider outage preserving attempts, and later recovery enriching the same checkpoint.

- [ ] **Step 6: Commit**

```bash
git add agentic_rag/continuity/enrich.py agentic_rag/jobs.py agentic_rag/worker.py tests/test_continuity_enrich.py tests/test_jobs.py tests/test_worker.py
git commit -m "feat: enrich continuation checkpoints asynchronously"
```

---

### Task 4: Codex lifecycle hooks and restoration

**Files:**
- Create: `agentic_rag/hooks/pre_compact.py`
- Create: `agentic_rag/hooks/post_compact.py`
- Create: `agentic_rag/hooks/session_end.py`
- Create: `tests/test_hook_pre_compact.py`
- Create: `tests/test_hook_post_compact.py`
- Create: `tests/test_hook_session_end.py`
- Modify: `agentic_rag/hooks/common.py`
- Modify: `agentic_rag/hooks/session_start.py`
- Modify: `tests/test_hook_session_start.py`
- Modify: `tests/test_hooks_common.py`

**Interfaces:**
- Consumes: capture/store/render/enqueue APIs from Tasks 1–3.
- Produces: command hook entry points whose `main() -> int` always returns zero; `build_context(..., session_id=None, source=None)` composes checkpoint restoration with existing memory context.

- [ ] **Step 1: Add failing `PreCompact` tests**

```python
def test_pre_compact_snapshots_and_enqueues(conn, hook_env, payload, monkeypatch):
    pre_compact.run(payload)
    cp = store.latest_for_session(conn, payload["session_id"])
    assert cp.trigger == "auto"
    assert queue_count(conn, "checkpoint_enrich") == 1

def test_pre_compact_db_down_exits_zero(hook_env, capsys):
    assert pre_compact.main() == 0
    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: Implement `PreCompact` with a strict timeout contract**

Validate payload, capture/upsert/enqueue, spawn the worker, log sanitized errors, and emit no stdout. The installed handler timeout is 3 seconds; subprocess capture operations use shorter internal timeouts.

- [ ] **Step 3: Add and implement `PostCompact` bookkeeping tests**

```python
def test_post_compact_marks_boundary_without_additional_context(conn, payload, capsys):
    post_compact.run(payload, sys.stdout)
    assert store.latest_for_session(conn, payload["session_id"]).compacted_at
    assert "additionalContext" not in capsys.readouterr().out
```

On failure, optionally emit only `{"systemMessage": "checkpoint bookkeeping delayed"}`; never call `emit_context`.

- [ ] **Step 4: Add and implement `SessionEnd` final-delta tests**

```python
def test_session_end_reuses_mine_dedup(conn, hook_env, payload):
    stop_enqueue.run(payload)
    session_end.run({**payload, "reason": "other"})
    assert open_mine_jobs(conn, payload["session_id"]) == 1
```

Factor the shared import-light enqueue into `common.enqueue_transcript_delta(payload)` or a focused helper so `Stop` and `SessionEnd` cannot drift. Do not spawn inline mining.

- [ ] **Step 5: Restore only through `SessionStart`**

Extend `build_context` to accept `session_id` and `source`. Select same-session first; on startup/resume only, fall back to same canonical project. Append the bounded renderer output after operational warnings and pins. Preserve the existing visible failure banner and maintenance behavior.

- [ ] **Step 6: Run all hook tests and commit**

Run: `uv run pytest tests/test_hook_pre_compact.py tests/test_hook_post_compact.py tests/test_hook_session_end.py tests/test_hook_session_start.py tests/test_hook_stop.py tests/test_hooks_common.py -v`

Expected: PASS with no model context emitted by `PreCompact`, `PostCompact`, or `SessionEnd`.

```bash
git add agentic_rag/hooks tests/test_hook_pre_compact.py tests/test_hook_post_compact.py tests/test_hook_session_end.py tests/test_hook_session_start.py tests/test_hook_stop.py tests/test_hooks_common.py
git commit -m "feat: preserve continuity across Codex lifecycle events"
```

---

### Task 5: Versioned compact prompt

**Files:**
- Create: `assets/codex/compact_prompt.md`
- Create: `tests/test_compact_prompt.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: packaged `assets/codex/compact_prompt.md` retrievable by the Codex installer.
- Consumes: checkpoint terminology and priorities from the approved spec.

- [ ] **Step 1: Write a failing prompt contract test**

```python
@pytest.mark.parametrize("phrase", [
    "objective", "success criteria", "user instructions", "decisions",
    "worktree", "uncommitted", "test results", "active processes",
    "blockers", "next exact action", "agentic-rag slugs", "revalidate",
])
def test_compact_prompt_contains_continuity_contract(phrase):
    assert phrase.lower() in compact_prompt_text().lower()
```

- [ ] **Step 2: Run and confirm the missing asset failure**

Run: `uv run pytest tests/test_compact_prompt.py -v`

Expected: FAIL because the packaged prompt is absent.

- [ ] **Step 3: Write the prompt and package it**

Require evidence-backed state, explicit unverified labels, user-owned dirty-file preservation, artifact paths/slugs instead of bodies, and continuation without asking Peter to repeat known context. Add the asset to Hatch wheel/sdist configuration and test retrieval from `importlib.resources`.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/test_compact_prompt.py -v`

Expected: PASS.

```bash
git add assets/codex/compact_prompt.md tests/test_compact_prompt.py pyproject.toml
git commit -m "feat: add Codex continuity compact prompt"
```

---

### Task 6: Lossless Codex config and hook installation

**Files:**
- Create: `agentic_rag/integrations/__init__.py`
- Create: `agentic_rag/integrations/codex/__init__.py`
- Create: `agentic_rag/integrations/codex/config.py`
- Create: `agentic_rag/integrations/codex/hooks.py`
- Create: `agentic_rag/integrations/codex/install.py`
- Create: `tests/test_codex_install.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `merge_config(text: str, *, home: Path) -> str`, `merge_hooks(data: dict, python: str) -> dict`, `install_codex(paths, *, check=False, run=subprocess.run) -> CodexInstallReport`.
- Consumes: packaged prompt asset and Python interpreter path.

- [ ] **Step 1: Add `tomlkit` and write failing preservation tests**

```python
def test_merge_config_preserves_comments_unknown_keys_and_sets_values():
    merged = merge_config('# mine\ncustom = "keep"\n[features]\nhooks = true\n', home=HOME)
    assert "# mine" in merged and 'custom = "keep"' in merged
    parsed = tomllib.loads(merged)
    assert parsed["model_context_window"] == 600000
    assert parsed["model_auto_compact_token_limit"] == 500000
    assert parsed["features"]["memories"] is True
    assert parsed["memories"]["extract_model"] == "gpt-5.6-luna"
    assert merge_config(merged, home=HOME) == merged
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run pytest tests/test_codex_install.py -v`

Expected: FAIL because the Codex integration package is absent.

- [ ] **Step 3: Implement comment-preserving TOML merge**

Use `tomlkit.parse`/`dumps`; set exactly the approved root, `[features]`, and `[memories]` keys. Expand the supplied home path deterministically in tests. Abort on invalid TOML without modifying the source file.

- [ ] **Step 4: Implement owned hook definitions and merge**

Install exactly one owned entry for `SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact`, `PostCompact`, and `SessionEnd`. Match `manual|auto` for compact hooks and `startup|resume|clear|compact` for SessionStart. Replace stale commands containing `agentic_rag.hooks.` while preserving foreign handlers, matchers, top-level metadata, and the unrelated duplicate `herdr-agent-state.sh` entries; report those duplicates without removing them.

- [ ] **Step 5: Implement recoverable atomic installation**

Back up each existing file once per install transaction, stage config/hooks/prompt to sibling temp files, parse staged TOML/JSON, then `os.replace`. If any staging/validation step fails, leave all live files unchanged. `check=True` returns intended changes without writing. Run `codex --version` plus a non-mutating config-loading probe supported by the installed CLI; if no validator exists, parse locally and report that runtime validation remains a rollout step rather than inventing a flag.

- [ ] **Step 6: Verify preservation, rollback fixtures, and commit**

Run: `uv run pytest tests/test_codex_install.py tests/test_compact_prompt.py -v`

Expected: PASS for empty files, existing comments, unknown keys, invalid inputs, foreign hooks, stale owned paths, repeat install, partial failure, check mode, and restoration from backups.

```bash
git add agentic_rag/integrations pyproject.toml tests/test_codex_install.py
git commit -m "feat: install Codex memory continuity safely"
```

---

### Task 7: Installer CLI and status discoverability

**Files:**
- Modify: `agentic_rag/install.py`
- Modify: `agentic_rag/cli.py`
- Modify: `agentic_rag/status.py`
- Modify: `tests/test_install.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_status.py`

**Interfaces:**
- Consumes: `install_codex(...)`, checkpoint selection/count queries.
- Produces: `rag install --codex`, `rag install --check`, expanded `InstallReport`, and checkpoint health fields in `StatusReport`.

- [ ] **Step 1: Write failing CLI/status tests**

```python
def test_install_codex_flag_reports_changed_paths(cli, monkeypatch):
    result = cli.invoke(["install", "--codex", "--check"])
    assert result.exit_code == 0
    assert ".codex/config.toml" in result.output
    assert "no files written" in result.output.lower()

def test_status_reports_checkpoint_freshness(conn, cfg):
    store.upsert_snapshot(conn, snapshot(session_id="s", cursor="u1"))
    rep = status.gather_status(conn, cfg)
    assert rep.open_checkpoints == 1
    assert rep.pending_checkpoint_enrichments == 1
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run pytest tests/test_install.py tests/test_cli.py tests/test_status.py -v`

Expected: FAIL on absent CLI options/report fields.

- [ ] **Step 3: Compose installers without changing legacy defaults**

Keep existing Claude MCP/hook installation behavior intact. Add explicit Codex targeting and check mode, print backups/changed paths/hook trust instructions, and never register another scheduler. Ensure repeated install replaces owned paths after virtualenv movement.

- [ ] **Step 4: Add checkpoint status and SessionStart health warning**

Report open checkpoint count, newest checkpoint timestamp/quality/project, oldest pending enrichment age, and provider health. Warn only for stale/pending conditions defined in config; do not warn merely because no checkpoint exists.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/test_install.py tests/test_cli.py tests/test_status.py tests/test_hook_session_start.py -v`

Expected: PASS.

```bash
git add agentic_rag/install.py agentic_rag/cli.py agentic_rag/status.py tests/test_install.py tests/test_cli.py tests/test_status.py tests/test_hook_session_start.py
git commit -m "feat: expose Codex continuity installation and health"
```

---

### Task 8: Documentation, backlog, and feature registry

**Files:**
- Create: `FEATURES.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `BACKLOG.md`
- Modify: `docs/01-what-is-agentic-rag.md`
- Modify: `docs/02-mental-model.md`
- Modify: `docs/03-quick-start.md`
- Modify: `docs/05-session-mining-and-curation.md`
- Modify: `docs/06-configuration-reference.md`
- Modify: `docs/07-privacy-and-cost.md`
- Modify: `docs/10-architecture.md`
- Modify: `docs/11-reference-cli-and-mcp.md`
- Modify: `docs/12-contributing.md`
- Modify: `docs/README.md`
- Create: `tests/test_docs_continuity.py`

**Interfaces:**
- Consumes: final CLI names, config values, hook behavior, and rollback paths from Tasks 1–7.
- Produces: complete provider-neutral documentation and discoverability points.

- [ ] **Step 1: Write failing documentation contract tests**

```python
def test_docs_explain_memory_ownership_and_compaction_limit():
    corpus = docs_text()
    assert "600000" in corpus and "500000" in corpus
    assert "native Codex memories" in corpus
    assert "agentic-rag" in corpus and "canonical" in corpus
    assert "SessionStart" in corpus and "PostCompact" in corpus

def test_feature_registry_and_numbered_backlog_exist():
    assert Path("FEATURES.md").is_file()
    assert "Codex continuity" in Path("FEATURES.md").read_text()
    assert re.search(r"^- [⬜🔵✅🔒⏸] \*\*\d+\.\d+", Path("BACKLOG.md").read_text(), re.M)
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run pytest tests/test_docs_continuity.py -v`

Expected: FAIL because `FEATURES.md` and continuity documentation are absent.

- [ ] **Step 3: Update positioning and operating documentation**

Describe agentic-rag as provider-neutral memory plus continuity; document native-memory complementarity, `/memories`, privacy implications of `disable_on_external_context=false`, the 600K context window, 500K compaction threshold, 100K reserve, the documented higher-pricing boundary above 272K input, hook trust, lifecycle data flow, status output, installation, verification, rollback, and auth-circuit recovery. Explicitly state that `PostCompact` cannot inject context and `SessionStart(source="compact")` restores it.

- [ ] **Step 4: Update feature/backlog/change records**

Add every implementation/rollout remainder to the root blocker-first numbered backlog with status, why-not-done, trigger, dependency, and effort. Mark only genuinely shipped behavior as shipped in `FEATURES.md` and `CHANGELOG.md`; leave operational rollout open until Task 10 succeeds.

- [ ] **Step 5: Run documentation and full tests, then commit**

Run: `uv run pytest tests/test_docs_continuity.py -v`

Run: `uv run pytest`

Expected: PASS with 0 failures.

```bash
git add README.md CHANGELOG.md BACKLOG.md FEATURES.md docs tests/test_docs_continuity.py
git commit -m "docs: document Codex memory continuity"
```

---

### Task 9: Pre-install review and full verification

**Files:**
- Modify only files required by evidence-backed review fixes.

**Interfaces:**
- Consumes: all implementation tasks and approved spec.
- Produces: a clean, review-ready branch and a check-mode install report.

- [ ] **Step 1: Review the complete diff against the spec**

Run: `git diff 33245fa...HEAD --stat && git diff 33245fa...HEAD --check`

Expected: all specified components present and no whitespace errors.

- [ ] **Step 2: Run focused security/preservation checks**

Run: `uv run pytest tests/test_secrets.py tests/test_roles.py tests/test_codex_install.py tests/test_provider_health.py -v`

Expected: PASS; no tests access Peter's real home configuration or database.

- [ ] **Step 3: Run the complete suite fresh**

Run: `uv run pytest`

Expected: PASS with 0 failures.

- [ ] **Step 4: Run check-mode against explicit temporary fixtures**

Run: `fixture_path="$(mktemp -d /private/tmp/agentic-rag-codex.XXXXXX)"`

Run: `uv run rag install --codex --check --codex-home "$fixture_path"`

Expected: report contains config, hooks, prompt, 600000/500000, Luna models, and “no files written”; fixture hashes remain unchanged.

- [ ] **Step 5: Run a code review and fix only verified findings**

Review schema transactions, selection isolation, hook output contracts, timeouts, transcript/secret boundaries, TOML/JSON preservation, rollback, and concurrency. For each accepted finding, add a failing regression test, implement the minimum correction, rerun its focused tests, then rerun the full suite.

- [ ] **Step 6: Commit review fixes if any**

```bash
git diff --name-only -z | xargs -0 git add --
git commit -m "fix: address Codex continuity review findings"
```

If no files changed, do not create an empty commit.

---

### Task 10: Global installation and operational smoke tests

**Files:**
- Modify through installer: `~/.codex/config.toml`
- Modify through installer: `~/.codex/hooks.json`
- Create through installer: `~/.codex/compact_prompt.md`
- Modify after verified rollout: `BACKLOG.md`, `FEATURES.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: verified `rag install --codex`, backups, Codex `/hooks`, live PostgreSQL/Ollama/Codex login.
- Produces: active global configuration, trusted lifecycle hooks, verified manual/automatic continuity, recorded rollout evidence.

- [ ] **Step 1: Capture read-only pre-install evidence**

Run: `codex --version`, `codex login status`, `uv run rag status`, and `uv run rag install --codex --check`.

Expected: Codex login valid, services healthy or explicitly diagnosed, check report limited to the three owned global artifacts plus owned hook entries.

- [ ] **Step 2: Install with recoverable backups**

Run: `uv run rag install --codex`

Expected: installer reports backups and changed paths; config contains context window `600000`, compaction threshold `500000`, memories enabled, Luna extraction/consolidation, and the installed prompt path.

- [ ] **Step 3: Validate and trust hooks**

Start Codex, run `/hooks`, inspect all new hashes/commands, and trust only the six agentic-rag lifecycle handlers. Record the unrelated duplicated/broken `herdr-agent-state.sh` diagnostic without changing it in this scope.

- [ ] **Step 4: Exercise manual compaction**

In a disposable session, establish a goal, dirty test fixture, observed passing/failing command, blocker, next action, and one RAG slug; run manual compact. Verify one checkpoint row, `compacted_at`, no duplicate enrichment job, and immediate `SessionStart(source="compact")` context containing the bounded evidence.

- [ ] **Step 5: Exercise automatic compaction safely**

Back up config, temporarily lower only the threshold in an isolated disposable session, trigger automatic compaction, verify the same lifecycle path, then atomically restore `model_context_window = 600000` and `model_auto_compact_token_limit = 500000` and validate config again.

- [ ] **Step 6: Exercise provider outage and recovery**

Using test configuration that does not alter Peter's real credential, force the provider preflight to report unavailable. Verify compaction continues, snapshot remains usable, enrichment stays pending without attempt loss, and SessionStart warns. Restore normal provider configuration and verify the same job enriches and health clears.

- [ ] **Step 7: Exercise SessionEnd tail capture**

Close/archive a disposable main thread after a final unmatched delta. Verify `SessionEnd` queues it once, the worker mines it, and no duplicate durable document is created by the preceding `Stop` hook.

- [ ] **Step 8: Record live evidence and close rollout backlog items**

Update `FEATURES.md`, `CHANGELOG.md`, and `BACKLOG.md` with actual Codex version, test results, hook trust state, checkpoint ids/counts without content, provider recovery result, backup locations, and rollback command. Do not record secrets or transcript paths containing private names.

- [ ] **Step 9: Run final verification and commit rollout records**

Run: `uv run pytest`

Run: `uv run rag status`

Run: `git diff --check && git status --short`

Expected: 0 test failures; no unexplained queue errors/processing rows; global context/threshold restored to 600000/500000; only intended documentation records uncommitted.

```bash
git add BACKLOG.md FEATURES.md CHANGELOG.md
git commit -m "chore: record Codex continuity rollout"
```

---

## Completion Gate

Before declaring the feature complete:

- Run the full suite fresh and quote its exact pass count.
- Confirm `git status --short` is empty in the feature worktree.
- Confirm live `~/.codex/config.toml` parses and contains the intended 600K context, 500K compaction, and memory values.
- Confirm `/hooks` shows the owned handlers trusted and no foreign handlers removed.
- Confirm one manual and one automatic compaction restored the correct checkpoint before continuation.
- Confirm an auth/provider outage did not block compaction or consume enrichment attempts.
- Confirm SessionEnd captured the final delta once.
- Confirm `rag status` has no unexplained errors and exposes checkpoint freshness.
- Confirm rollback backups exist and the documented restoration procedure matches their paths.
