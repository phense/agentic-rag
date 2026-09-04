# Claude Compaction Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Claude Code sessions the same durable, auditable continuity across compaction that 0.3.0 gave Codex, bound to Claude's hook contract (PreCompact stdout = compact instructions, PostCompact `compact_summary`, 10,000-char context limit, 1.5 s SessionEnd budget) and a managed 500,000-token auto-compact window inside the 1M context.

**Architecture:** The provider-neutral checkpoint core (`agentic_rag/continuity/`) is reused unchanged in contract and extended with a bounded `handoff` column. The six shared hook modules gain three explicit client branches (PreCompact prints the prompt, PostCompact matches without `turn_id` and stores the summary, SessionEnd enqueues for every Claude reason) selected by `hooks.common.client_kind()`. A thin `integrations/claude/` adapter merges six hooks plus `autoCompactWindow=500000` into `~/.claude/settings.json` with check mode, unique backups, and a target-aware rollback record.

**Tech Stack:** Python 3.13+, PostgreSQL 17, psycopg 3, pytest, Claude Code 2.1.259 lifecycle hooks, `uv`

**Spec:** `docs/superpowers/specs/2026-09-03-claude-compaction-continuity-design.md`

## Global Constraints

- The checkpoint core must not depend on client hook names; Codex behavior and every existing Codex test stay green.
- Every hook fails open: no hook may block compaction (`PreCompact` never exits 2), prompt submission, or shutdown; every error is logged via `common.log_hook_error` and the hook exits 0.
- `SessionStart` is the only restoration point; `PostCompact` never emits `additionalContext`.
- The rendered `SessionStart` context never exceeds Claude's 10,000-character per-hook limit silently: cap at `context_max_chars` (default 9,500; hard max 10,000; min 1,000) with a visible warning.
- The handoff is a bounded, secret-stripped summary (`checkpoint_handoff_max_chars`, default 8,000, minimum 400), never a transcript, diff, or file body.
- Managed Claude setting: `autoCompactWindow = 500000` only. `model` is reported, never rewritten.
- Hook timeouts in seconds: `SessionStart 10`, `UserPromptSubmit 5`, `Stop 10`, `PreCompact 3`, `PostCompact 3`, `SessionEnd 1`.
- Installation is additive, idempotent, previewable (`--check`), backed up with a unique sibling `settings.json.bak.<32 hex>`, and recoverable with `rag install --restore <record>`.
- Every database mutation goes through `continuity/store.py` and writes `audit_log` in the same transaction; no delete path.
- Never expose secrets in logs, tests, docs, or commits. Use `agentic_rag.secrets.strip_secrets`.
- Run the suite with `uv run pytest` (needs local PostgreSQL; the fixture creates `agentic_rag_test`).
- Commit after each task with a conventional message; keep `BACKLOG.md` and `FEATURES.md` current.

---

## File Map

- `sql/008_checkpoint_handoff.sql` — `handoff text`, `handoff_at timestamptz` on `continuation_checkpoints`.
- `agentic_rag/config.py` — `checkpoint_handoff_max_chars`, `context_max_chars` with validation.
- `agentic_rag/continuity/model.py` — `Checkpoint.handoff/handoff_at`, `bound_handoff()`.
- `agentic_rag/continuity/store.py` — `attach_handoff()`, `latest_pre_compact()`, row mapping.
- `agentic_rag/continuity/render.py` — handoff section with age/applicability label; `stale_days` parameter.
- `agentic_rag/hooks/common.py` — `client_kind()`.
- `agentic_rag/hooks/pre_compact.py` — Claude prompt on stdout.
- `agentic_rag/hooks/post_compact.py` — Claude matching + handoff.
- `agentic_rag/hooks/session_end.py` — Claude reason set.
- `agentic_rag/hooks/session_start.py` — handoff rendering, total-output cap.
- `agentic_rag/status.py`, `agentic_rag/cli.py` — handoff visibility; install output; CLI flag rules.
- `agentic_rag/integrations/claude/__init__.py`, `prompt.py`, `settings.py`, `install.py` — Claude adapter.
- `agentic_rag/integrations/codex/install.py` — `_snapshot(label=...)` wording only.
- `agentic_rag/install.py` — Claude transaction orchestration, rollback records, target-aware restore.
- `assets/claude/compact_prompt.md` — versioned compact instructions; `pyproject.toml` force-include.
- `tests/test_continuity_store.py`, `tests/test_continuity_render.py`, `tests/test_config.py`, `tests/test_hooks_common.py`, `tests/test_hook_pre_compact.py`, `tests/test_hook_post_compact.py`, `tests/test_hook_session_end.py`, `tests/test_hook_session_start.py`, `tests/test_status.py`, `tests/test_claude_prompt.py`, `tests/test_claude_settings.py`, `tests/test_claude_install.py`, `tests/test_install.py`, `tests/test_cli.py`, `tests/test_docs_continuity.py`.
- `docs/00-whats-new-in-0.4.md`, `docs/README.md`, `docs/03-quick-start.md`, `docs/05-session-mining-and-curation.md`, `docs/06-configuration-reference.md`, `docs/07-privacy-and-cost.md`, `docs/10-architecture.md`, `docs/11-reference-cli-and-mcp.md`, `README.md`, `CHANGELOG.md`, `FEATURES.md`, `BACKLOG.md`.

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b feat/claude-compaction-continuity
```

---

### Task 1: Handoff column, model, store, and configuration

**Files:**
- Create: `sql/008_checkpoint_handoff.sql`
- Modify: `agentic_rag/config.py`
- Modify: `agentic_rag/continuity/model.py`
- Modify: `agentic_rag/continuity/store.py`
- Test: `tests/test_continuity_store.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `model.bound_handoff(text: object, *, max_chars: int) -> str`, `model.MIN_HANDOFF_CHARS = 400`, `model.HANDOFF_TRUNCATION_MARKER = "…[truncated]"`, `Checkpoint.handoff: str | None`, `Checkpoint.handoff_at: datetime | None`.
- Produces: `store.attach_handoff(conn, checkpoint_id: str, handoff: str, *, max_chars: int) -> Checkpoint`, `store.latest_pre_compact(conn, session_id: str, trigger: str) -> Checkpoint | None`.
- Produces: `Config.checkpoint_handoff_max_chars: int = 8000`, `Config.context_max_chars: int = 9500`, `config.MAX_CONTEXT_CHARS = 10_000`, `config.MIN_CONTEXT_CHARS = 1_000`.

- [ ] **Step 1: Write the failing store tests**

Append to `tests/test_continuity_store.py`:

```python
def _pre_compact(conn, *, session_id="session-1", cursor="event-1", trigger="auto",
                 turn_id=None):
    from agentic_rag.continuity.model import CheckpointSnapshot
    return store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id=session_id, turn_id=turn_id, cursor=cursor,
        source="PreCompact", trigger=trigger, cwd="/work/project",
        project_root="/work/project",
    ))


def test_attach_handoff_bounds_strips_and_audits(conn):
    checkpoint = _pre_compact(conn)
    summary = "Goal: ship\nAPI key sk-ant-api03-" + "a" * 40 + "\n" + "x" * 9000

    saved = store.attach_handoff(conn, checkpoint.id, summary, max_chars=800)

    assert saved.handoff is not None
    assert len(saved.handoff) <= 800
    assert saved.handoff.endswith("…[truncated]")
    assert "sk-ant-api03-" not in saved.handoff
    assert saved.handoff_at is not None
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_handoff'"
    ).fetchone()["n"] == 1


def test_attach_handoff_identical_replay_is_noop_and_change_replaces(conn):
    checkpoint = _pre_compact(conn)
    store.attach_handoff(conn, checkpoint.id, "first summary", max_chars=400)

    again = store.attach_handoff(conn, checkpoint.id, "first summary", max_chars=400)
    replaced = store.attach_handoff(conn, checkpoint.id, "second summary", max_chars=400)

    assert again.handoff == "first summary"
    assert replaced.handoff == "second summary"
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_handoff'"
    ).fetchone()["n"] == 2


def test_attach_handoff_rejects_blank_and_small_budget(conn):
    import pytest
    checkpoint = _pre_compact(conn)
    with pytest.raises(ValueError, match="non-blank"):
        store.attach_handoff(conn, checkpoint.id, "   ", max_chars=400)
    with pytest.raises(ValueError, match="at least 400"):
        store.attach_handoff(conn, checkpoint.id, "summary", max_chars=399)
    with pytest.raises(ValueError, match="no such checkpoint"):
        store.attach_handoff(
            conn, "00000000-0000-0000-0000-000000000000", "summary",
            max_chars=400)


def test_latest_pre_compact_ignores_turn_and_prefers_newest_same_trigger(conn):
    older = _pre_compact(conn, cursor="event-a", trigger="auto")
    manual = _pre_compact(conn, cursor="event-b", trigger="manual")
    newest = _pre_compact(conn, cursor="event-c", trigger="auto")

    assert store.latest_pre_compact(conn, "session-1", "auto").id == newest.id
    assert store.latest_pre_compact(conn, "session-1", "manual").id == manual.id
    assert store.latest_pre_compact(conn, "session-1", "unknown") is None
    assert store.latest_pre_compact(conn, "other", "auto") is None
    assert store.get(conn, older.id).state == "superseded"   # retained, never deleted
```

Append to `tests/test_config.py`:

```python
def test_continuity_handoff_and_context_bounds(tmp_path):
    import pytest
    from agentic_rag.config import Config, load_config

    assert Config().checkpoint_handoff_max_chars == 8000
    assert Config().context_max_chars == 9500
    path = tmp_path / "config.toml"
    path.write_text(
        "[continuity]\nhandoff_max_chars = 1200\ncontext_max_chars = 4000\n")
    cfg = load_config(path)
    assert cfg.checkpoint_handoff_max_chars == 1200
    assert cfg.context_max_chars == 4000
    with pytest.raises(ValueError, match="handoff_max_chars"):
        Config(checkpoint_handoff_max_chars=399)
    with pytest.raises(ValueError, match="context_max_chars"):
        Config(context_max_chars=10001)
    with pytest.raises(ValueError, match="context_max_chars"):
        Config(context_max_chars=999)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_continuity_store.py tests/test_config.py -q`
Expected: FAIL — `AttributeError: module 'agentic_rag.continuity.store' has no attribute 'attach_handoff'`, `TypeError: Config.__init__() got an unexpected keyword argument 'checkpoint_handoff_max_chars'`.

- [ ] **Step 3: Add the migration**

Create `sql/008_checkpoint_handoff.sql`:

```sql
-- 008_checkpoint_handoff.sql — retain the client's own bounded, secret-stripped
-- compact summary next to the deterministic checkpoint.  Claude Code delivers
-- it in PostCompact; Codex does not.  The existing UPDATE grant covers the new
-- columns; there is still no delete path.

ALTER TABLE continuation_checkpoints
    ADD COLUMN handoff    text,
    ADD COLUMN handoff_at timestamptz;
```

- [ ] **Step 4: Extend configuration**

In `agentic_rag/config.py` add after `MIN_DIGEST_CHARS = 128`:

```python
MIN_HANDOFF_CHARS = 400
MIN_CONTEXT_CHARS = 1_000
MAX_CONTEXT_CHARS = 10_000   # Claude Code's per-hook additionalContext limit
```

Add fields to `Config` after `checkpoint_artifact_max`:

```python
    checkpoint_handoff_max_chars: int = 8000
    context_max_chars: int = 9500
```

Extend `__post_init__`:

```python
        if (
            not isinstance(self.checkpoint_handoff_max_chars, int)
            or isinstance(self.checkpoint_handoff_max_chars, bool)
            or self.checkpoint_handoff_max_chars < MIN_HANDOFF_CHARS
        ):
            raise ValueError(
                "continuity handoff_max_chars must be an integer of at least "
                f"{MIN_HANDOFF_CHARS}"
            )
        if (
            not isinstance(self.context_max_chars, int)
            or isinstance(self.context_max_chars, bool)
            or not MIN_CONTEXT_CHARS <= self.context_max_chars <= MAX_CONTEXT_CHARS
        ):
            raise ValueError(
                "continuity context_max_chars must be an integer between "
                f"{MIN_CONTEXT_CHARS} and {MAX_CONTEXT_CHARS}"
            )
```

(`[continuity] handoff_max_chars` maps through the `checkpoint` prefix; `context_max_chars` matches the bare field name — both are already handled by `load_config`.)

- [ ] **Step 5: Extend the model**

In `agentic_rag/continuity/model.py` add constants after `MAX_ENRICHMENT_BYTES`:

```python
MIN_HANDOFF_CHARS = 400
HANDOFF_TRUNCATION_MARKER = "…[truncated]"
_HORIZONTAL_SPACE = re.compile(r"[ \t]+")
_BLANK_RUN = re.compile(r"\n{3,}")
```

Add the function before `class CheckpointSnapshot`:

```python
def bound_handoff(text: object, *, max_chars: int) -> str:
    """Normalize, secret-strip, and truncate a client compact summary.

    The handoff keeps its line structure (it is prose the client wrote for
    its own continuation) but never grows past ``max_chars`` and never
    carries a secret-shaped value into the store.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("handoff must be a non-blank string")
    if (
        not isinstance(max_chars, int)
        or isinstance(max_chars, bool)
        or max_chars < MIN_HANDOFF_CHARS
    ):
        raise ValueError(
            f"max_chars must be an integer of at least {MIN_HANDOFF_CHARS}"
        )
    normalized = _HORIZONTAL_SPACE.sub(" ", text.replace("\r\n", "\n")).strip()
    normalized = _BLANK_RUN.sub("\n\n", normalized)
    stripped, _ = strip_secrets(normalized)
    if len(stripped) > max_chars:
        cut = max_chars - len(HANDOFF_TRUNCATION_MARKER)
        stripped = stripped[:cut].rstrip() + HANDOFF_TRUNCATION_MARKER
    return stripped
```

Add two fields at the end of `Checkpoint` (after `predecessor_cursor`):

```python
    handoff: str | None = None
    handoff_at: datetime | None = None
```

- [ ] **Step 6: Extend the store**

In `agentic_rag/continuity/store.py` import `bound_handoff` from `.model`, add `handoff=row["handoff"], handoff_at=row["handoff_at"]` to `_checkpoint()`, and append:

```python
def attach_handoff(
    conn, checkpoint_id: str, handoff: str, *, max_chars: int
) -> Checkpoint:
    """Attach the client's bounded compact summary; identical replays are no-ops."""
    bounded = bound_handoff(handoff, max_chars=max_chars)
    try:
        current = conn.execute(
            "SELECT handoff FROM continuation_checkpoints WHERE id = %s FOR UPDATE",
            (checkpoint_id,),
        ).fetchone()
        if current is None:
            raise ValueError(f"no such checkpoint: {checkpoint_id}")
        if current["handoff"] == bounded:
            conn.rollback()
            return get(conn, checkpoint_id)  # type: ignore[return-value]
        row = conn.execute(
            "UPDATE continuation_checkpoints SET handoff = %s, handoff_at = now(), "
            "updated_at = now() WHERE id = %s RETURNING *",
            (bounded, checkpoint_id),
        ).fetchone()
        conn.execute(
            "INSERT INTO audit_log(actor, op, summary) VALUES (%s, %s, %s)",
            ("continuity", "checkpoint_handoff",
             _checkpoint_summary(str(row["id"]), "handoff attached")),
        )
        conn.commit()
        return _checkpoint(row)
    except Exception:
        conn.rollback()
        raise


def latest_pre_compact(conn, session_id: str, trigger: str) -> Checkpoint | None:
    """Newest PreCompact row for clients whose PostCompact carries no turn_id."""
    row = conn.execute(
        "SELECT * FROM continuation_checkpoints "
        "WHERE session_id = %s AND trigger = %s AND source = 'PreCompact' "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (session_id, trigger),
    ).fetchone()
    return _checkpoint(row) if row is not None else None
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_continuity_store.py tests/test_config.py tests/test_continuity_render.py tests/test_hook_session_start.py -q`
Expected: PASS (the fixture drops and re-applies all migrations, so 008 is applied automatically).

- [ ] **Step 8: Commit**

```bash
git add sql/008_checkpoint_handoff.sql agentic_rag/config.py agentic_rag/continuity/model.py agentic_rag/continuity/store.py tests/test_continuity_store.py tests/test_config.py
git commit -m "feat: add bounded checkpoint handoff column and gateway"
```

---

### Task 2: Client detection in the shared hook plumbing

**Files:**
- Modify: `agentic_rag/hooks/common.py`
- Test: `tests/test_hooks_common.py`

**Interfaces:**
- Produces: `common.client_kind(payload: dict, argv: list[str] | None = None) -> str` returning `"claude"` or `"codex"`; `common.CLIENT_KINDS = ("claude", "codex")`.
- Precedence: explicit `--client X` / `--client=X` in argv, then a non-blank `turn_id` in the payload (Codex), else `"claude"`. The environment is deliberately not consulted: `CLAUDECODE=1` is inherited by every child of a Claude session, including `pytest` and a Codex started from a Claude Bash tool, so payload evidence is stronger.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_common.py`:

```python
def test_client_kind_prefers_explicit_argv():
    assert common.client_kind({"turn_id": "t1"}, ["--client", "claude"]) == "claude"
    assert common.client_kind({}, ["--client=codex"]) == "codex"
    assert common.client_kind({"turn_id": "t1"}, ["--client", "bogus"]) == "codex"


def test_client_kind_uses_turn_id_for_codex_and_defaults_to_claude(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert common.client_kind({"turn_id": "turn-7"}, []) == "codex"
    assert common.client_kind({"turn_id": "  "}, []) == "claude"
    assert common.client_kind({"session_id": "s"}, []) == "claude"


def test_client_kind_reads_sys_argv_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["hook", "--client", "codex"])
    assert common.client_kind({}) == "codex"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_hooks_common.py -q`
Expected: FAIL — `AttributeError: module 'agentic_rag.hooks.common' has no attribute 'client_kind'`.

- [ ] **Step 3: Implement**

Add to `agentic_rag/hooks/common.py` after `INTERACTIVE_SOURCES`:

```python
CLIENT_KINDS = ("claude", "codex")


def client_kind(payload: dict, argv: list[str] | None = None) -> str:
    """Which client delivered this hook event: ``claude`` or ``codex``.

    An explicit ``--client`` argument wins (tests, diagnostics).  Otherwise a
    non-blank ``turn_id`` is Codex's documented stable field; Claude Code
    never sends one.  Environment variables are ignored on purpose: a Claude
    session exports CLAUDECODE=1 to every child, including test runs.
    """
    args = sys.argv[1:] if argv is None else argv
    for index, arg in enumerate(args):
        if arg == "--client" and index + 1 < len(args):
            if args[index + 1] in CLIENT_KINDS:
                return args[index + 1]
        elif arg.startswith("--client=") and arg[len("--client="):] in CLIENT_KINDS:
            return arg[len("--client="):]
    turn_id = payload.get("turn_id")
    if isinstance(turn_id, str) and turn_id.strip():
        return "codex"
    return "claude"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_hooks_common.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentic_rag/hooks/common.py tests/test_hooks_common.py
git commit -m "feat: detect the hook client from argv and payload"
```

---

### Task 3: Claude compact prompt asset and PreCompact stdout

**Files:**
- Create: `assets/claude/compact_prompt.md`
- Create: `agentic_rag/integrations/claude/__init__.py`, `agentic_rag/integrations/claude/prompt.py`
- Modify: `pyproject.toml`, `agentic_rag/hooks/pre_compact.py`
- Test: `tests/test_claude_prompt.py`, `tests/test_hook_pre_compact.py`

**Interfaces:**
- Produces: `integrations.claude.prompt.compact_prompt_text() -> str`, `MAX_PROMPT_CHARS = 4000`, `CHECKPOINT_LINE_PREFIX = "agentic-rag checkpoint: "`.
- Changes: `pre_compact.run(payload: dict, stdout=None) -> None` (stdout optional; Claude writes the prompt to it).

- [ ] **Step 1: Write the failing prompt tests**

Create `tests/test_claude_prompt.py`:

```python
from agentic_rag.integrations.claude import prompt


def test_claude_compact_prompt_is_versioned_bounded_and_reference_oriented():
    text = prompt.compact_prompt_text()

    assert text.startswith("# Claude compact continuation instructions")
    assert "Version: 1.0" in text
    assert len(text) <= prompt.MAX_PROMPT_CHARS
    assert "agentic-rag checkpoint:" in text
    assert "[[slug]]" in text
    assert "SessionStart" in text
    for forbidden in ("transcript", "diff", "credential"):
        assert forbidden in text  # named only as things to omit
    assert "Do not copy" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_claude_prompt.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_rag.integrations.claude'`.

- [ ] **Step 3: Write the asset**

Create `assets/claude/compact_prompt.md`:

```markdown
# Claude compact continuation instructions — bounded handoff

Version: 1.0

You are compacting an agentic-rag-backed Claude Code session. Produce a
bounded handoff so the next model request can continue the same task without
asking the user to repeat known context. Do not continue the task, call tools,
or invent state. Preserve only evidence-backed facts.

After this compaction the agentic-rag `SessionStart` hook injects the pinned
rules, the knowledge-domain map, and the continuation checkpoint for this
session. Reference that material instead of repeating it.

Include, in this order:

1. Current objective and the explicit success criteria still open.
2. User instructions, approvals, constraints, and prohibitions still in force.
3. Decisions made, rejected alternatives, and the reason or evidence for each.
4. Repository facts: canonical project root, CWD, branch or worktree, HEAD, and
   user-owned or uncommitted changes. Label facts as current only when
   recently verified; otherwise label them historical/unverified.
5. Completed and remaining plan steps with exact artifact paths (specs, plans,
   `BACKLOG.md`, `FEATURES.md`) rather than copied file bodies.
6. Commands and tests with their actual observed outcomes and when they were
   observed; never report inferred success.
7. Background processes, subagents, and external states only when observed,
   with identifiers, plus an instruction to revalidate them.
8. Blockers, risks, unresolved questions, and the next exact action.
9. Relevant agentic-rag memory as canonical `[[slug]]` references only.
10. The line `agentic-rag checkpoint: <id>` if one appears below, verbatim.

Keep the handoff concise: prefer identifiers, paths, hashes, timestamps,
outcomes, and slugs over prose. Distinguish current, historical, stale, and
unverified facts. Do not copy transcript passages, diffs, logs, memory bodies,
document bodies, or any credential or secret-shaped value.
```

Register the asset in `pyproject.toml` in both force-include tables:

```toml
[tool.hatch.build.targets.wheel.force-include]
"assets/codex/compact_prompt.md" = "assets/codex/compact_prompt.md"
"assets/claude/compact_prompt.md" = "assets/claude/compact_prompt.md"
"sql" = "sql"

[tool.hatch.build.targets.sdist.force-include]
"assets/codex/compact_prompt.md" = "assets/codex/compact_prompt.md"
"assets/claude/compact_prompt.md" = "assets/claude/compact_prompt.md"
```

- [ ] **Step 4: Write the loader**

Create `agentic_rag/integrations/claude/__init__.py`:

```python
"""Claude Code adapter: hook wiring, compaction policy, and compact prompt."""
```

Create `agentic_rag/integrations/claude/prompt.py`:

```python
"""Versioned compact instructions delivered through PreCompact stdout."""
from __future__ import annotations

from importlib import resources

MAX_PROMPT_CHARS = 4000
CHECKPOINT_LINE_PREFIX = "agentic-rag checkpoint: "


def compact_prompt_text() -> str:
    text = resources.files("assets").joinpath(
        "claude", "compact_prompt.md"
    ).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Claude compact prompt asset is empty")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"Claude compact prompt asset exceeds {MAX_PROMPT_CHARS} characters"
        )
    return text
```

- [ ] **Step 5: Run the prompt test**

Run: `uv run pytest tests/test_claude_prompt.py -q`
Expected: PASS

- [ ] **Step 6: Write the failing PreCompact tests**

Append to `tests/test_hook_pre_compact.py`:

```python
def _claude_payload(tmp_path, **over):
    payload = _payload(tmp_path)
    del payload["turn_id"]
    payload["permission_mode"] = "default"
    payload["custom_instructions"] = None
    payload.update(over)
    return payload


def test_pre_compact_claude_prints_prompt_and_checkpoint_line(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    stdout = io.StringIO()
    payload = _claude_payload(tmp_path)

    pre_compact.run(payload, stdout)

    checkpoint = store.latest_for_session(conn, payload["session_id"])
    out = stdout.getvalue()
    assert out.startswith("# Claude compact continuation instructions")
    assert out.rstrip().endswith(f"agentic-rag checkpoint: {checkpoint.id}")
    assert _queue_count(conn, "checkpoint_enrich") == 1


def test_pre_compact_claude_prints_prompt_without_line_when_db_down(
        hook_env, tmp_path, monkeypatch):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    stdout = io.StringIO()

    pre_compact.run(_claude_payload(tmp_path), stdout)

    out = stdout.getvalue()
    assert out.startswith("# Claude compact continuation instructions")
    assert "agentic-rag checkpoint:" not in out
    assert "no_such_database_xyz" not in out


def test_pre_compact_codex_stays_silent_on_stdout(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    stdout = io.StringIO()

    pre_compact.run(_payload(tmp_path), stdout)

    assert stdout.getvalue() == ""


def test_pre_compact_kill_switch_silences_claude_prompt(
        hook_env, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_RAG_HOOKS_DISABLE", "1")
    stdout = io.StringIO()

    pre_compact.run(_claude_payload(tmp_path), stdout)

    assert stdout.getvalue() == ""
```

- [ ] **Step 7: Run to verify they fail**

Run: `uv run pytest tests/test_hook_pre_compact.py -q`
Expected: FAIL — `TypeError: run() takes 1 positional argument but 2 were given`.

- [ ] **Step 8: Implement the Claude branch**

Replace the body of `agentic_rag/hooks/pre_compact.py` from the module docstring down with:

```python
"""PreCompact hook: persist fast deterministic continuation state.

Semantic enrichment is queued for the singleton worker; this hook never calls
an LLM or waits for mining.  Codex output stays silent.  Claude Code appends a
PreCompact hook's stdout to its compaction instructions, so for Claude the hook
prints the versioned compact prompt (plus the checkpoint id when one exists)
after persistence — even when persistence failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import db, jobs
from ..config import load_config
from ..continuity import capture, store
from ..integrations.claude.prompt import CHECKPOINT_LINE_PREFIX, compact_prompt_text
from . import common

_TRIGGERS = frozenset({"manual", "auto"})


def _validate(payload: dict) -> tuple[str, str | None]:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("PreCompact requires a session_id")
    trigger = payload.get("trigger")
    if trigger not in _TRIGGERS:
        raise ValueError("PreCompact trigger must be manual or auto")
    transcript = payload.get("transcript_path")
    if transcript is not None and not isinstance(transcript, str):
        raise ValueError("PreCompact transcript_path must be a string or null")
    return session_id, transcript


def _persist(payload: dict) -> str | None:
    """Snapshot, enrich-enqueue, and return the checkpoint id (or None)."""
    session_id, transcript = _validate(payload)
    cfg = load_config()
    snapshot = capture.capture_snapshot_seed(payload)
    conn = db.connect(cfg, role="writer")
    try:
        checkpoint = store.upsert_snapshot(
            conn, snapshot, update_existing=False)
        try:
            repository_snapshot = capture.capture_repository_state(
                snapshot, cwd=payload.get("cwd"))
            checkpoint = store.upsert_snapshot(conn, repository_snapshot)
        except Exception as exc:  # noqa: BLE001 — seed is already durable
            common.log_hook_error("pre_compact", repr(exc))
        if transcript and Path(transcript).is_file():
            jobs.enqueue_checkpoint_enrichment(
                conn,
                checkpoint_id=checkpoint.id,
                session_id=session_id,
                transcript_path=transcript,
                after_cursor=checkpoint.predecessor_cursor,
            )
            common.spawn_worker()
        return checkpoint.id
    finally:
        conn.close()


def _emit_compact_instructions(stdout, checkpoint_id: str | None) -> None:
    try:
        text = compact_prompt_text()
    except Exception as exc:  # noqa: BLE001 — a missing asset must not block
        common.log_hook_error("pre_compact.prompt", repr(exc))
        return
    stdout.write(text.rstrip("\n") + "\n")
    if checkpoint_id:
        stdout.write(f"{CHECKPOINT_LINE_PREFIX}{checkpoint_id}\n")
    stdout.flush()


def run(payload: dict, stdout=None) -> None:
    if not common.is_interactive(payload):
        return
    checkpoint_id = None
    try:
        checkpoint_id = _persist(payload)
    except Exception as exc:  # noqa: BLE001 — compaction must never block
        common.log_hook_error("pre_compact", repr(exc))
    if stdout is not None and common.client_kind(payload) == "claude":
        _emit_compact_instructions(stdout, checkpoint_id)


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tests/test_hook_pre_compact.py tests/test_claude_prompt.py tests/test_compact_prompt.py -q`
Expected: PASS (existing tests call `run(payload)` without stdout and keep working; `test_pre_compact_rejects_invalid_trigger_without_stdout` uses a Codex payload and stays silent).

- [ ] **Step 10: Commit**

```bash
git add assets/claude/compact_prompt.md agentic_rag/integrations/claude pyproject.toml agentic_rag/hooks/pre_compact.py tests/test_claude_prompt.py tests/test_hook_pre_compact.py
git commit -m "feat: deliver the Claude compact prompt through PreCompact stdout"
```

---

### Task 4: PostCompact for Claude — turn-less matching and handoff capture

**Files:**
- Modify: `agentic_rag/hooks/post_compact.py`
- Test: `tests/test_hook_post_compact.py`

**Interfaces:**
- Consumes: `store.latest_pre_compact`, `store.mark_compacted`, `store.attach_handoff`, `common.client_kind`, `Config.checkpoint_handoff_max_chars`.
- Behavior: Claude payload (`session_id`, `trigger`, optional `compact_summary`, no `turn_id`) marks the newest same-trigger PreCompact checkpoint compacted and attaches the bounded summary. Still no `additionalContext`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hook_post_compact.py`:

```python
def _claude_payload(**over):
    payload = _payload(compact_summary="Goal: finish the adapter.\nNext: run tests.")
    del payload["turn_id"]
    payload["permission_mode"] = "default"
    payload.update(over)
    return payload


def _seed_claude(conn, *, cursor="event-9", trigger="auto"):
    return store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id="session-1", turn_id=None, cursor=cursor,
        source="PreCompact", trigger=trigger, cwd="/work/project",
        project_root="/work/project",
    ))


def test_post_compact_claude_marks_newest_same_trigger_and_stores_handoff(
        conn, hook_env):
    older = _seed_claude(conn, cursor="event-a")
    manual = _seed_claude(conn, cursor="event-b", trigger="manual")
    newest = _seed_claude(conn, cursor="event-c")
    stdout = io.StringIO()

    post_compact.run(_claude_payload(), stdout)

    saved = store.get(conn, newest.id)
    assert saved.compacted_at is not None
    assert saved.handoff == "Goal: finish the adapter.\nNext: run tests."
    assert saved.handoff_at is not None
    assert store.get(conn, older.id).compacted_at is None
    assert store.get(conn, manual.id).compacted_at is None
    assert stdout.getvalue() == ""


def test_post_compact_claude_replay_is_idempotent_and_change_replaces(
        conn, hook_env):
    checkpoint = _seed_claude(conn)

    post_compact.run(_claude_payload(), io.StringIO())
    post_compact.run(_claude_payload(), io.StringIO())
    post_compact.run(_claude_payload(compact_summary="revised summary"),
                     io.StringIO())

    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_compacted'"
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_handoff'"
    ).fetchone()["n"] == 2
    assert store.get(conn, checkpoint.id).handoff == "revised summary"


def test_post_compact_claude_bounds_and_strips_handoff(conn, hook_env):
    checkpoint = _seed_claude(conn)
    hook_env.write_text(
        hook_env.read_text() + "\n[continuity]\nhandoff_max_chars = 500\n")
    secret = "sk-ant-api03-" + "b" * 40
    summary = f"token {secret}\n" + "z" * 2000

    post_compact.run(_claude_payload(compact_summary=summary), io.StringIO())

    saved = store.get(conn, checkpoint.id)
    assert len(saved.handoff) <= 500
    assert saved.handoff.endswith("…[truncated]")
    assert secret not in saved.handoff


def test_post_compact_claude_without_checkpoint_or_summary_is_silent(
        conn, hook_env):
    stdout = io.StringIO()
    post_compact.run(_claude_payload(), stdout)          # no checkpoint
    assert stdout.getvalue() == ""

    checkpoint = _seed_claude(conn)
    post_compact.run(_claude_payload(compact_summary=None), stdout)

    saved = store.get(conn, checkpoint.id)
    assert saved.compacted_at is not None
    assert saved.handoff is None
    assert stdout.getvalue() == ""


def test_post_compact_claude_handoff_failure_keeps_boundary(
        conn, hook_env, monkeypatch, tmp_path):
    checkpoint = _seed_claude(conn)
    monkeypatch.setattr(post_compact.common, "HOOK_LOG", tmp_path / "hooks.log")

    def boom(*args, **kwargs):
        raise RuntimeError("handoff store down sk-ant-api03-" + "c" * 40)
    monkeypatch.setattr(post_compact.store, "attach_handoff", boom)
    stdout = io.StringIO()

    post_compact.run(_claude_payload(), stdout)

    assert store.get(conn, checkpoint.id).compacted_at is not None
    assert stdout.getvalue() == ""
    log = (tmp_path / "hooks.log").read_text()
    assert "post_compact.handoff" in log
    assert "sk-ant-api03-" not in log
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_hook_post_compact.py -q`
Expected: FAIL — the Claude payload has no `turn_id`, so `_identity` returns `None` and nothing is marked (`assert saved.compacted_at is not None` fails).

- [ ] **Step 3: Implement**

Replace `agentic_rag/hooks/post_compact.py` with:

```python
"""PostCompact hook: record the boundary without restoring model context.

Codex delivers session/turn/trigger and nothing else.  Claude Code delivers
no turn id but includes ``compact_summary``; that summary is retained as a
bounded, secret-stripped handoff on the matching checkpoint.  Neither client
receives ``additionalContext`` from this hook — SessionStart restores.
"""
from __future__ import annotations

import json
import sys

from .. import db
from ..config import Config, load_config
from ..continuity import store
from . import common

_TRIGGERS = frozenset({"manual", "auto"})


def _session_and_trigger(payload: dict) -> tuple[str, str] | None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    trigger = payload.get("trigger")
    if trigger not in _TRIGGERS:
        return None
    return session_id, trigger


def _identity(payload: dict) -> tuple[str, str, str] | None:
    base = _session_and_trigger(payload)
    turn_id = payload.get("turn_id")
    if base is None or not isinstance(turn_id, str) or not turn_id.strip():
        return None
    session_id, trigger = base
    return session_id, turn_id, trigger


def _record_codex_boundary(conn, session_id: str, turn_id: str, trigger: str) -> None:
    checkpoint = store.matching_compaction(conn, session_id, turn_id, trigger)
    if checkpoint is not None:
        store.mark_compacted(conn, session_id, checkpoint.cursor)


def _record_claude_boundary(
    conn, cfg: Config, payload: dict, session_id: str, trigger: str
) -> None:
    checkpoint = store.latest_pre_compact(conn, session_id, trigger)
    if checkpoint is None:
        return
    store.mark_compacted(conn, session_id, checkpoint.cursor)
    summary = payload.get("compact_summary")
    if not isinstance(summary, str) or not summary.strip():
        return
    try:
        store.attach_handoff(
            conn, checkpoint.id, summary,
            max_chars=cfg.checkpoint_handoff_max_chars,
        )
    except Exception as exc:  # noqa: BLE001 — the boundary is already marked
        common.log_hook_error("post_compact.handoff", repr(exc))


def run(payload: dict, stdout) -> None:
    if not common.is_interactive(payload):
        return
    client = common.client_kind(payload)
    if client == "claude":
        identity = _session_and_trigger(payload)
    else:
        identity = _identity(payload)
    if identity is None:
        return
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            if client == "claude":
                _record_claude_boundary(conn, cfg, payload, *identity)
            else:
                _record_codex_boundary(conn, *identity)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — compaction already succeeded
        common.log_hook_error("post_compact", repr(exc))
        json.dump({"systemMessage": "checkpoint bookkeeping delayed"}, stdout)


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_hook_post_compact.py -q`
Expected: PASS, including the five pre-existing Codex tests.

- [ ] **Step 5: Commit**

```bash
git add agentic_rag/hooks/post_compact.py tests/test_hook_post_compact.py
git commit -m "feat: record Claude compaction boundaries with a bounded handoff"
```

---

### Task 5: SessionEnd for Claude — every reason, measured budget

**Files:**
- Modify: `agentic_rag/hooks/session_end.py`
- Test: `tests/test_hook_session_end.py`

**Interfaces:**
- Consumes: `common.client_kind`, `transcript_delta.enqueue_transcript_delta`.
- Produces: `session_end.CLAUDE_REASONS`, `session_end.CODEX_REASONS` frozensets.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hook_session_end.py`:

```python
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize(
    "reason", ["clear", "resume", "logout", "prompt_input_exit", "other"])
def test_session_end_claude_enqueues_for_every_reason(
        conn, hook_env, tmp_path, monkeypatch, reason):
    monkeypatch.setattr(session_end.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path, reason=reason)

    session_end.run(payload)

    assert _open_mine_jobs(conn, payload["session_id"]) == 1


def test_session_end_codex_keeps_other_only(conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_end.common, "spawn_worker", lambda: None)

    session_end.run(_payload(tmp_path, turn_id="turn-1", reason="clear"))
    assert _open_mine_jobs(conn, "session-1") == 0

    session_end.run(_payload(tmp_path, turn_id="turn-1", reason="other"))
    assert _open_mine_jobs(conn, "session-1") == 1


def test_session_end_wall_time_fits_claude_budget(
        conn, hook_env, tmp_path, monkeypatch):
    """Claude gives all SessionEnd hooks 1.5 s in total.  Interpreter start
    plus import (subprocess) and the enqueue itself (in-process, worker spawn
    stubbed) must stay well below that.  The printed figure is recorded in
    BACKLOG.md during rollout."""
    monkeypatch.setattr(session_end.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path)

    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-c", "import agentic_rag.hooks.session_end"],
        check=True, capture_output=True,
    )
    session_end.run(payload)
    elapsed = time.perf_counter() - start

    print(f"\nsession_end wall time (startup+import+enqueue): {elapsed:.3f}s")
    assert _open_mine_jobs(conn, payload["session_id"]) == 1
    assert elapsed < 1.5
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_hook_session_end.py -q`
Expected: FAIL — the `clear`/`resume`/`logout`/`prompt_input_exit` cases enqueue nothing.

- [ ] **Step 3: Implement**

Replace `agentic_rag/hooks/session_end.py` with:

```python
"""SessionEnd hook: enqueue the main thread's final transcript delta.

Codex fires ``reason="other"`` when the main thread really ends.  Claude Code
ends the transcript on every reason it reports (``clear``, ``resume``,
``logout``, ``prompt_input_exit``, ``other``) and gives all SessionEnd hooks
1.5 seconds in total, so this module stays import-light and the ``Stop`` hook
remains the guaranteed enqueue path.
"""
from __future__ import annotations

import sys

from . import common, transcript_delta

CODEX_REASONS = frozenset({"other"})
CLAUDE_REASONS = frozenset(
    {"clear", "resume", "logout", "prompt_input_exit", "other"})


def run(payload: dict) -> None:
    reasons = (
        CLAUDE_REASONS if common.client_kind(payload) == "claude"
        else CODEX_REASONS
    )
    if payload.get("reason") not in reasons:
        return
    transcript_delta.enqueue_transcript_delta(payload, hook="session_end")


def main() -> int:
    run(common.read_payload(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and note the timing**

Run: `uv run pytest tests/test_hook_session_end.py -q -s`
Expected: PASS; copy the printed `session_end wall time` figure into the Task 11 BACKLOG entry.

- [ ] **Step 5: Commit**

```bash
git add agentic_rag/hooks/session_end.py tests/test_hook_session_end.py
git commit -m "feat: enqueue the final delta on every Claude session end"
```

---

### Task 6: Handoff rendering and the SessionStart total-output cap

**Files:**
- Modify: `agentic_rag/continuity/render.py`
- Modify: `agentic_rag/hooks/session_start.py`
- Test: `tests/test_continuity_render.py`, `tests/test_hook_session_start.py`

**Interfaces:**
- Changes: `render_checkpoint(checkpoint, *, max_chars, current_cwd=None, current_project_root=None, now=None, stale_days: int = 30)`.
- Produces: `session_start.fit_context(parts: list[tuple[str, str]], warnings: list[str], max_chars: int) -> str` with section names `"header"`, `"pins"`, `"domains"`, `"knowledge"`, `"checkpoint"` and trim order `knowledge → domains → checkpoint → pins`.

- [ ] **Step 1: Write the failing render tests**

Append to `tests/test_continuity_render.py`:

```python
def test_renderer_includes_labelled_handoff_and_drops_it_before_mandatory():
    from datetime import timedelta
    saved = replace(checkpoint(), handoff="Goal: finish\nNext: run the suite",
                    handoff_at=datetime.now(UTC))

    text = render_checkpoint(saved, max_chars=2000,
                             current_project_root="/work/project")
    assert "Handoff (Claude compact summary, CURRENT" in text
    assert "Goal: finish\nNext: run the suite" in text

    old = replace(saved, handoff_at=datetime.now(UTC) - timedelta(days=45))
    text = render_checkpoint(old, max_chars=2000, stale_days=30)
    assert "Handoff (Claude compact summary, HISTORICAL" in text

    tiny = render_checkpoint(saved, max_chars=MIN_RENDER_CHARS)
    assert "Handoff" not in tiny
    assert "Next exact action" in tiny and "Blockers:" in tiny


def test_renderer_handoff_is_dropped_before_goal_and_after_references():
    saved = replace(checkpoint(), handoff="H" * 600, handoff_at=datetime.now(UTC))

    text = render_checkpoint(saved, max_chars=900)

    assert "Goal:" in text
    assert "Handoff" not in text or "H" * 600 not in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_continuity_render.py -q`
Expected: FAIL — `TypeError: render_checkpoint() got an unexpected keyword argument 'stale_days'` / missing `Handoff` label.

- [ ] **Step 3: Implement the handoff section**

In `agentic_rag/continuity/render.py` add after `_repository_context`:

```python
def _handoff_label(checkpoint: Checkpoint, now: datetime, stale_days: int) -> str:
    attached = checkpoint.handoff_at or checkpoint.updated_at
    if attached.tzinfo is None:
        attached = attached.replace(tzinfo=UTC)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    age_hours = max(0, int((current - attached).total_seconds() // 3600))
    state = "HISTORICAL" if age_hours > stale_days * 24 else "CURRENT"
    return f"Handoff (Claude compact summary, {state}, age={age_hours}h): "


def _handoff_value(checkpoint: Checkpoint) -> str:
    if not isinstance(checkpoint.handoff, str):
        return ""
    cleaned, _ = strip_secrets(checkpoint.handoff.strip())
    return cleaned
```

Change the signature of `render_checkpoint` to add `stale_days: int = 30` after `now`, and add before the `references` block:

```python
    if handoff := _handoff_value(checkpoint):
        optional.append(_Section(
            85, 85, _handoff_label(checkpoint, now or datetime.now(UTC), stale_days),
            handoff,
        ))
```

(Drop order 85 sits below references (90), warnings (100), and volatile (110), so those go first; goal (40), criteria (50), repository (60), and tests (70) survive longer.)

- [ ] **Step 4: Run the render tests**

Run: `uv run pytest tests/test_continuity_render.py -q`
Expected: PASS

- [ ] **Step 5: Write the failing SessionStart tests**

Append to `tests/test_hook_session_start.py`:

```python
def test_compact_restores_handoff_within_budget(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    checkpoint = _checkpoint(
        conn, session_id="s1", project_root="/Users/example/proj",
        cursor="c1", goal="ship handoff")
    store.attach_handoff(conn, checkpoint.id, "Goal: ship handoff\nNext: docs",
                         max_chars=400)

    ctx = _run(_payload(source="compact"))

    assert "Handoff (Claude compact summary, CURRENT" in ctx
    assert "Next: docs" in ctx


def test_fit_context_trims_in_order_and_warns_visibly():
    parts = [
        ("header", "# agentic-rag memory"),
        ("pins", "## Pinned rules\n" + "\n".join(
            f"- pin {i} " + "p" * 80 for i in range(40))),
        ("domains", "## Knowledge domains\n" + "d" * 1500),
        ("knowledge", "## Recent knowledge\n" + "k" * 1500),
        ("checkpoint", "## Continuation checkpoint\n" + "c" * 1500),
    ]

    fitted = session_start.fit_context(parts, [], 6000)

    assert len(fitted) <= 6000
    assert "## Recent knowledge" not in fitted
    assert "## Knowledge domains" not in fitted
    assert "## Continuation checkpoint" in fitted
    assert "pin 0 " in fitted
    assert "⚠️ context truncated" in fitted
    assert "knowledge" in fitted and "domains" in fitted

    tighter = session_start.fit_context(parts, ["⚠️ existing warning"], 1500)

    assert len(tighter) <= 1500
    assert "⚠️ existing warning" in tighter
    assert "## Continuation checkpoint" not in tighter
    assert "pins cut" in tighter
    assert "pin 0 " in tighter


def test_fit_context_never_exceeds_hard_limit_even_with_one_huge_pin():
    parts = [("header", "# agentic-rag memory"),
             ("pins", "## Pinned rules\n- " + "x" * 20000)]

    fitted = session_start.fit_context(parts, [], 1000)

    assert len(fitted) <= 1000
    assert "⚠️ context truncated" in fitted


def test_session_start_caps_total_output_from_config(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    hook_env.write_text(
        hook_env.read_text() + "\n[continuity]\ncontext_max_chars = 1000\n")
    for i in range(30):
        pins.add_pin(conn, body=f"Rule {i}: " + "r" * 100)

    ctx = _run(_payload())

    assert len(ctx) <= 1000
    assert "⚠️ context truncated" in ctx
    assert "Rule 0:" in ctx
```

- [ ] **Step 6: Run to verify they fail**

Run: `uv run pytest tests/test_hook_session_start.py -q`
Expected: FAIL — `AttributeError: module 'agentic_rag.hooks.session_start' has no attribute 'fit_context'`.

- [ ] **Step 7: Implement the cap**

In `agentic_rag/hooks/session_start.py`:

1. Add `from ..config import MAX_CONTEXT_CHARS` to the config import line.
2. Add after `CURATION_MAX_AGE_H = 24`:

```python
_TRIM_ORDER = ("knowledge", "domains", "checkpoint")
_TRUNCATED = "⚠️ context truncated to fit the {limit}-char Claude hook limit: {detail}"


def _join(parts: list[tuple[str, str]], warnings: list[str]) -> str:
    body = [text for _, text in parts]
    if warnings:
        body.insert(1, "\n".join(warnings))
    return "\n\n".join(body)


def fit_context(
    parts: list[tuple[str, str]], warnings: list[str], max_chars: int
) -> str:
    """Trim named sections (knowledge, domains, checkpoint, then pins) until
    the joined context fits ``max_chars``; every cut is announced up front."""
    kept = list(parts)
    notes = list(warnings)
    text = _join(kept, notes)
    if len(text) <= max_chars:
        return text
    dropped: list[str] = []
    for name in _TRIM_ORDER:
        if not any(part_name == name for part_name, _ in kept):
            continue
        kept = [part for part in kept if part[0] != name]
        dropped.append(name)
        text = _join(kept, notes + [_TRUNCATED.format(
            limit=max_chars, detail="dropped " + ", ".join(dropped))])
        if len(text) <= max_chars:
            return text
    # Pins are law: cut whole trailing pin lines, say how many, keep the rest.
    pin_index = next(
        (i for i, (name, _) in enumerate(kept) if name == "pins"), None)
    if pin_index is not None:
        heading, _, body = kept[pin_index][1].partition("\n")
        lines = body.split("\n")
        total = len(lines)
        while lines:
            lines.pop()
            detail = (
                f"{total - len(lines)} of {total} pins cut"
                + (f"; dropped {', '.join(dropped)}" if dropped else "")
                + " — curate pins (rag pin list)"
            )
            trial = kept[:pin_index] + [
                ("pins", heading + "\n" + "\n".join(lines))
            ] + kept[pin_index + 1:]
            text = _join(trial, notes + [
                _TRUNCATED.format(limit=max_chars, detail=detail)])
            if len(text) <= max_chars:
                return text
    detail = "hard cut" + (f"; dropped {', '.join(dropped)}" if dropped else "")
    warning = _TRUNCATED.format(limit=max_chars, detail=detail)
    text = _join(kept, notes + [warning])
    return text[:max_chars]
```

3. Rework `build_context` to collect named parts instead of a flat list. Change `parts: list[str] = ["# agentic-rag memory"]` to `parts: list[tuple[str, str]] = [("header", "# agentic-rag memory")]` and every `parts.append("…")` to append a `(name, text)` tuple: pins → `("pins", …)`, domains → `("domains", …)`, project knowledge → `("knowledge", …)`, checkpoint → `("checkpoint", …)`. Pass `stale_days=cfg.stale_days` to `render_checkpoint`. Replace the final three lines

```python
    if warnings:
        parts.insert(1, "\n".join(warnings))
    return "\n\n".join(parts)
```

with

```python
    return fit_context(
        parts, warnings, min(cfg.context_max_chars, MAX_CONTEXT_CHARS))
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_hook_session_start.py tests/test_continuity_render.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add agentic_rag/continuity/render.py agentic_rag/hooks/session_start.py tests/test_continuity_render.py tests/test_hook_session_start.py
git commit -m "feat: render the handoff and cap SessionStart context at Claude's limit"
```

---

### Task 7: Status visibility for the handoff

**Files:**
- Modify: `agentic_rag/status.py`, `agentic_rag/cli.py`
- Test: `tests/test_status.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `StatusReport.newest_checkpoint_handoff_at: datetime | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_status.py`:

```python
def test_gather_status_reports_handoff_age(conn, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")
    checkpoint = store.upsert_snapshot(conn, _snapshot())
    assert status.gather_status(conn, cfg).newest_checkpoint_handoff_at is None

    store.attach_handoff(conn, checkpoint.id, "summary text", max_chars=400)

    rep = status.gather_status(conn, cfg)
    assert rep.newest_checkpoint_handoff_at is not None
```

Append to `tests/test_cli.py` (the module's `cli_env` fixture points the CLI at the test database and yields its connection; `continuity_store` and `CheckpointSnapshot` are already imported there):

```python
def test_status_prints_handoff_line(cli_env, capsys):
    # cli_env yields the test-database connection (see the fixture above)
    checkpoint = continuity_store.upsert_snapshot(cli_env, CheckpointSnapshot(
        session_id="s", turn_id=None, cursor="c", source="PreCompact",
        trigger="auto", cwd="/p", project_root="/p"))
    continuity_store.attach_handoff(cli_env, checkpoint.id, "summary",
                                    max_chars=400)

    assert cli._main(["status"]) == 0

    out = capsys.readouterr().out
    assert "checkpoint handoff:" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_status.py tests/test_cli.py -q -k "handoff"`
Expected: FAIL — `AttributeError: 'StatusReport' object has no attribute 'newest_checkpoint_handoff_at'`.

- [ ] **Step 3: Implement**

In `agentic_rag/status.py` add the field after `newest_checkpoint_project`:

```python
    newest_checkpoint_handoff_at: datetime | None = None
```

In `_checkpoint_health`, select `handoff_at` in the `newest` query (`"SELECT updated_at, quality, project_root, handoff_at "`) and add to the returned dict:

```python
        "newest_checkpoint_handoff_at": newest["handoff_at"] if newest else None,
```

In `agentic_rag/cli.py`, inside the `status` printing block right after the `newest checkpoint` line (around line 470), add:

```python
                handoff_at = rep.newest_checkpoint_handoff_at
                if handoff_at is not None:
                    age = datetime.now(timezone.utc) - handoff_at
                    print(f"checkpoint handoff: {handoff_at:%Y-%m-%d %H:%M} "
                          f"({_format_age(age)} ago)")
                else:
                    print("checkpoint handoff: none")
```

(Import `datetime, timezone` from `datetime` at the top of `cli.py` if not already imported.)

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_status.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentic_rag/status.py agentic_rag/cli.py tests/test_status.py tests/test_cli.py
git commit -m "feat: show checkpoint handoff freshness in rag status"
```

---

### Task 8: Claude settings merge and policy warnings

**Files:**
- Create: `agentic_rag/integrations/claude/settings.py`
- Modify: `agentic_rag/install.py` (delegate `hook_entries`/`merge_hooks`), `tests/test_install.py` (retire the three-hook tests)
- Test: `tests/test_claude_settings.py`

**Interfaces:**
- Produces: `settings.HOOK_MARKER = "agentic_rag.hooks."`, `settings.MANAGED_VALUES = {"autoCompactWindow": 500000}`, `settings.OVERRIDING_ENV`, `settings.owned_hook_entries(python: str) -> dict[str, list[dict]]`, `settings.merge_settings(data: dict, python: str) -> dict`, `settings.policy_warnings(data: dict, environ: Mapping[str, str]) -> tuple[str, ...]`, `settings.managed_settings() -> tuple[tuple[str, object], ...]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_claude_settings.py`:

```python
import shlex

from agentic_rag.integrations.claude import settings

PY = "/venv with space/bin/python"


def test_owned_entries_cover_six_events_with_matchers_and_timeouts():
    entries = settings.owned_hook_entries(PY)

    assert set(entries) == {
        "SessionStart", "UserPromptSubmit", "Stop",
        "PreCompact", "PostCompact", "SessionEnd",
    }
    assert entries["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    assert entries["PreCompact"][0]["matcher"] == "manual|auto"
    assert entries["PostCompact"][0]["matcher"] == "manual|auto"
    assert "matcher" not in entries["SessionEnd"][0]
    timeouts = {event: entry[0]["hooks"][0]["timeout"]
                for event, entry in entries.items()}
    assert timeouts == {"SessionStart": 10, "UserPromptSubmit": 5, "Stop": 10,
                        "PreCompact": 3, "PostCompact": 3, "SessionEnd": 1}
    command = entries["PreCompact"][0]["hooks"][0]["command"]
    assert command == f"{shlex.quote(PY)} -m agentic_rag.hooks.pre_compact"
    assert all("additionalContextLimit" not in e[0]["hooks"][0]
               for e in entries.values())


def test_merge_settings_is_idempotent_replaces_stale_and_preserves_foreign():
    original = {
        "model": "claude-fable-5-1[1m]",
        "permissions": {"defaultMode": "auto"},
        "hooks": {
            "SessionStart": [
                {"matcher": "*", "hooks": [
                    {"type": "command", "command": "bash herdr.sh session",
                     "timeout": 10}]},
                {"matcher": "startup|resume|clear|compact", "hooks": [
                    {"type": "command",
                     "command": "/old/python -m agentic_rag.hooks.session_start",
                     "timeout": 10}]},
            ],
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "guard.sh"}]}],
        },
    }

    once = settings.merge_settings(original, PY)
    twice = settings.merge_settings(once, PY)

    assert twice == once
    assert original["hooks"]["SessionStart"][1]["hooks"][0]["command"].startswith(
        "/old/python")                       # input untouched
    assert once["model"] == "claude-fable-5-1[1m]"
    assert once["permissions"] == {"defaultMode": "auto"}
    assert once["autoCompactWindow"] == 500000
    ss = once["hooks"]["SessionStart"]
    assert ss[0]["hooks"][0]["command"] == "bash herdr.sh session"
    owned = [h["command"] for e in ss for h in e["hooks"]
             if "agentic_rag.hooks." in h["command"]]
    assert len(owned) == 1 and owned[0].startswith(shlex.quote(PY))
    assert once["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    assert set(once["hooks"]) >= {"PreCompact", "PostCompact", "SessionEnd"}


def test_merge_settings_rejects_non_object_hooks():
    import pytest
    with pytest.raises(ValueError, match="hooks"):
        settings.merge_settings({"hooks": []}, PY)
    with pytest.raises(ValueError, match="SessionStart"):
        settings.merge_settings({"hooks": {"SessionStart": {}}}, PY)


def test_policy_warnings_cover_model_toggle_and_overrides():
    data = {"model": "claude-opus-5", "autoCompactEnabled": False,
            "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"}}
    environ = {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "40"}

    warnings = settings.policy_warnings(data, environ)

    assert any("[1m]" in w and "claude-opus-5" in w for w in warnings)
    assert any("autoCompactEnabled" in w for w in warnings)
    assert any("settings env CLAUDE_CODE_AUTO_COMPACT_WINDOW" in w for w in warnings)
    assert any("environment variable CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" in w
               for w in warnings)
    assert settings.policy_warnings(
        {"model": "claude-fable-5-1[1m]"}, {}) == ()
    assert any("no model" in w for w in settings.policy_warnings({}, {}))


def test_managed_settings_is_the_single_policy_source():
    assert settings.managed_settings() == (("autoCompactWindow", 500000),)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_claude_settings.py -q`
Expected: FAIL — `ImportError: cannot import name 'settings'`.

- [ ] **Step 3: Implement**

Create `agentic_rag/integrations/claude/settings.py`:

```python
"""Lossless merge of owned hooks and the compaction policy into
``~/.claude/settings.json``.

Only handler commands carrying ``agentic_rag.hooks.`` are ever replaced; every
foreign entry, key, and ordering survives.  The managed policy is one value:
``autoCompactWindow = 500000`` (a token count, capped by the model's window).
"""
from __future__ import annotations

import shlex
from collections.abc import Mapping
from copy import deepcopy

HOOK_MARKER = "agentic_rag.hooks."
MANAGED_VALUES: dict[str, object] = {"autoCompactWindow": 500000}
OVERRIDING_ENV = (
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
    "DISABLE_AUTO_COMPACT",
    "DISABLE_COMPACT",
)
ONE_MILLION_SUFFIX = "[1m]"

# event -> (module, timeout seconds, matcher)
_HOOK_MODULES = {
    "SessionStart": ("session_start", 10, "startup|resume|clear|compact"),
    "UserPromptSubmit": ("prompt_recall", 5, None),
    "Stop": ("stop_enqueue", 10, None),
    "PreCompact": ("pre_compact", 3, "manual|auto"),
    "PostCompact": ("post_compact", 3, "manual|auto"),
    "SessionEnd": ("session_end", 1, None),
}


def managed_settings() -> tuple[tuple[str, object], ...]:
    return tuple(MANAGED_VALUES.items())


def owned_hook_entries(python: str) -> dict[str, list[dict]]:
    quoted = shlex.quote(python)
    result: dict[str, list[dict]] = {}
    for event, (module, timeout, matcher) in _HOOK_MODULES.items():
        entry: dict = {
            "hooks": [{
                "type": "command",
                "command": f"{quoted} -m agentic_rag.hooks.{module}",
                "timeout": timeout,
            }]
        }
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
        result[event] = [entry]
    return result


def _without_owned(entry: object) -> object | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
        return entry
    kept = [
        handler for handler in entry["hooks"]
        if not (isinstance(handler, dict)
                and HOOK_MARKER in str(handler.get("command", "")))
    ]
    if not kept:
        return None
    entry["hooks"] = kept
    return entry


def merge_settings(data: dict, python: str) -> dict:
    """Return a new settings object with owned hooks and policy applied."""
    result = deepcopy(data)
    hooks = result.get("hooks")
    if hooks is None:
        hooks = {}
        result["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("Claude settings 'hooks' value must be an object")
    for event, current in list(hooks.items()):
        if not isinstance(current, list):
            raise ValueError(f"Claude settings hooks {event!r} must be an array")
        hooks[event] = [
            kept for original in current
            if (kept := _without_owned(original)) is not None
        ]
    for event, entries in owned_hook_entries(python).items():
        hooks[event] = hooks.get(event, []) + entries
    for key, value in MANAGED_VALUES.items():
        result[key] = value
    return result


def policy_warnings(data: dict, environ: Mapping[str, str]) -> tuple[str, ...]:
    """Report, never fix, conditions under which the managed window is moot."""
    warnings: list[str] = []
    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        warnings.append(
            "no model configured in settings; autoCompactWindow=500000 is "
            "capped to the default model's context window"
        )
    elif not model.endswith(ONE_MILLION_SUFFIX):
        warnings.append(
            f"model {model!r} has no {ONE_MILLION_SUFFIX} suffix; "
            "autoCompactWindow=500000 is capped to that model's window"
        )
    if data.get("autoCompactEnabled") is False:
        warnings.append(
            "autoCompactEnabled is false; automatic compaction and continuity "
            "checkpoints stay idle until it is re-enabled"
        )
    env_block = data.get("env")
    if isinstance(env_block, dict):
        for key in OVERRIDING_ENV:
            if key in env_block:
                warnings.append(
                    f"settings env {key} overrides the managed autoCompactWindow")
    for key in OVERRIDING_ENV:
        if key in environ:
            warnings.append(
                f"environment variable {key} overrides the managed "
                "autoCompactWindow"
            )
    return tuple(warnings)
```

- [ ] **Step 4: Delegate the legacy helpers**

In `agentic_rag/install.py`, add `from .integrations.claude import settings as claude_settings` and replace the bodies of `hook_entries`, `_is_ours`, and `merge_hooks` with delegations:

```python
def hook_entries(python: str) -> dict:
    """Owned Claude hook entries (six lifecycle events)."""
    return claude_settings.owned_hook_entries(python)


def merge_hooks(settings: dict, python: str) -> dict:
    """Lossless merge of owned hooks plus the managed compaction policy."""
    return claude_settings.merge_settings(settings, python)
```

Delete `_is_ours`. In `tests/test_install.py` delete `test_hook_entries_reference_all_three_hooks`, `test_merge_hooks_into_empty_settings`, `test_merge_hooks_is_idempotent_and_replaces_stale_paths`, and `test_merge_hooks_preserves_foreign_hooks_and_keys` (Task 8's new module tests cover them) and add:

```python
def test_legacy_helpers_delegate_to_claude_settings():
    assert set(install.hook_entries(PY)) == {
        "SessionStart", "UserPromptSubmit", "Stop",
        "PreCompact", "PostCompact", "SessionEnd",
    }
    merged = install.merge_hooks({"model": "opus"}, PY)
    assert merged["model"] == "opus"
    assert merged["autoCompactWindow"] == 500000
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_claude_settings.py tests/test_install.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agentic_rag/integrations/claude/settings.py agentic_rag/install.py tests/test_claude_settings.py tests/test_install.py
git commit -m "feat: merge six Claude hooks and the 500K auto-compact window"
```

---

### Task 9: Claude install transaction, check mode, rollback record, target-aware restore

**Files:**
- Create: `agentic_rag/integrations/claude/install.py`
- Modify: `agentic_rag/integrations/codex/install.py` (`_snapshot(label=...)`), `agentic_rag/install.py`, `agentic_rag/cli.py`
- Test: `tests/test_claude_install.py`, `tests/test_install.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `claude_install.ClaudeInstallReport(settings_path: Path, check: bool, changed: bool, backup: BackupRecord | None, installed: InstalledFile | None, warnings: tuple[str, ...], managed: tuple[tuple[str, object], ...])`.
- Produces: `claude_install.install_claude(settings_path: Path, *, python: str, check: bool = False, environ: Mapping[str, str] | None = None) -> ClaudeInstallReport`.
- Produces: `claude_install.restore_claude(settings_path: Path, backup: BackupRecord | None, installed: InstalledFile) -> tuple[Path, ...]`.
- Produces in `agentic_rag/install.py`: `CLAUDE_ROLLBACK_VERSION = 1`, `record_claude_rollback(report, *, state_dir: Path | None = None) -> Path`, `restore_claude_rollback(record_path: Path) -> tuple[Path, ...]`, `restore_rollback(record_path: Path, *, codex_flag: bool) -> tuple[Path, ...]`, `InstallReport.claude_report: ClaudeInstallReport | None`.
- Changes: `install(cfg, *, settings_path=None, run=subprocess.run, with_launchd=True, codex=False, check=False, codex_home=None, restore_path=None, state_dir=None)` — `check` and `restore_path` no longer require `codex`.

- [ ] **Step 1: Write the failing adapter tests**

Create `tests/test_claude_install.py`:

```python
import json
import os
import re
from pathlib import Path

import pytest

from agentic_rag.integrations.claude import install as claude_install

PY = "/venv/bin/python"


def test_check_mode_reports_without_writing(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "claude-opus-5"}')
    before = settings.read_text()

    report = claude_install.install_claude(
        settings, python=PY, check=True, environ={})

    assert report.check is True
    assert report.changed is True
    assert report.backup is None and report.installed is None
    assert report.managed == (("autoCompactWindow", 500000),)
    assert any("[1m]" in w for w in report.warnings)
    assert settings.read_text() == before
    assert list(tmp_path.iterdir()) == [settings]


def test_install_backs_up_uniquely_writes_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "claude-fable-5-1[1m]", "env": {"X": "1"}}')
    settings.chmod(0o600)

    first = claude_install.install_claude(settings, python=PY, environ={})

    assert first.changed is True
    assert first.backup is not None
    assert re.fullmatch(r"settings\.json\.bak\.[0-9a-f]{32}",
                        first.backup.backup_path.name)
    assert first.backup.backup_path.read_text() == (
        '{"model": "claude-fable-5-1[1m]", "env": {"X": "1"}}')
    assert (first.backup.backup_path.stat().st_mode & 0o777) == 0o600
    assert (settings.stat().st_mode & 0o777) == 0o600
    data = json.loads(settings.read_text())
    assert data["env"] == {"X": "1"}
    assert data["autoCompactWindow"] == 500000
    assert set(data["hooks"]) >= {"PreCompact", "PostCompact", "SessionEnd"}
    assert first.installed is not None
    assert first.warnings == ()

    second = claude_install.install_claude(settings, python=PY, environ={})

    assert second.changed is False
    assert second.backup is None
    assert len([p for p in tmp_path.iterdir() if ".bak." in p.name]) == 1


def test_install_creates_missing_settings_without_backup(tmp_path):
    settings = tmp_path / "nested" / "settings.json"

    report = claude_install.install_claude(settings, python=PY, environ={})

    assert report.changed is True
    assert report.backup is None
    assert json.loads(settings.read_text())["autoCompactWindow"] == 500000


def test_install_rejects_corrupt_json_and_leaves_it(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus", TRAILING GARBAGE')

    with pytest.raises(RuntimeError, match="not valid JSON"):
        claude_install.install_claude(settings, python=PY, environ={})

    assert "TRAILING GARBAGE" in settings.read_text()
    assert list(tmp_path.iterdir()) == [settings]


def test_install_refuses_concurrent_edit_between_snapshot_and_publish(
        tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "m"}')
    original_stage = claude_install._stage_text

    def edit_then_stage(path, text):
        path.write_text('{"model": "edited concurrently"}')
        return original_stage(path, text)
    monkeypatch.setattr(claude_install, "_stage_text", edit_then_stage)

    with pytest.raises(RuntimeError, match="changed concurrently"):
        claude_install.install_claude(settings, python=PY, environ={})

    assert json.loads(settings.read_text()) == {"model": "edited concurrently"}
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".settings")]


def test_restore_puts_backup_back_and_refuses_drift(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "before"}')
    report = claude_install.install_claude(settings, python=PY, environ={})

    restored = claude_install.restore_claude(
        settings, report.backup, report.installed)

    assert restored == (settings,)
    assert settings.read_text() == '{"model": "before"}'

    again = claude_install.install_claude(settings, python=PY, environ={})
    settings.write_text(settings.read_text() + "\n")
    with pytest.raises(RuntimeError, match="changed since installation"):
        claude_install.restore_claude(settings, again.backup, again.installed)


def test_restore_removes_a_file_the_install_created(tmp_path):
    settings = tmp_path / "settings.json"
    report = claude_install.install_claude(settings, python=PY, environ={})

    restored = claude_install.restore_claude(settings, None, report.installed)

    assert restored == (settings,)
    assert not settings.exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_claude_install.py -q`
Expected: FAIL — `ImportError: cannot import name 'install'`.

- [ ] **Step 3: Parametrize the Codex snapshot wording**

In `agentic_rag/integrations/codex/install.py` change `_snapshot` to accept a label:

```python
def _snapshot(path: Path, *, label: str = "Codex") -> FileSnapshot:
    """Read a stable regular-file snapshot without following a leaf symlink."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return FileSnapshot(FileIdentity(False), b"")
    if stat.S_ISLNK(before.st_mode):
        raise RuntimeError(f"refusing {label} leaf symbolic link: {path}")
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"refusing non-regular {label} file: {path}")
    content = path.read_bytes()
    try:
        after = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} file changed concurrently: {path}") from exc
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise RuntimeError(f"{label} file changed concurrently: {path}")
    ...  # unchanged remainder
```

- [ ] **Step 4: Implement the adapter**

Create `agentic_rag/integrations/claude/install.py`:

```python
"""Recoverable installation of the Claude hook set and compaction policy.

One target file (``~/.claude/settings.json``), staged in place, published
atomically, backed up uniquely, and identity-bound for restore.  The Codex
installer's snapshot/stage/backup primitives are reused so both targets share
one notion of "changed concurrently".
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..codex.install import (
    BackupRecord,
    FileSnapshot,
    InstalledFile,
    _backup_changed,
    _snapshot,
    _stage_text,
)
from .settings import managed_settings, merge_settings, policy_warnings

LABEL = "Claude settings"


@dataclass(frozen=True)
class ClaudeInstallReport:
    settings_path: Path
    check: bool
    changed: bool
    backup: BackupRecord | None
    installed: InstalledFile | None
    warnings: tuple[str, ...]
    managed: tuple[tuple[str, object], ...]


def _load(snapshot: FileSnapshot, path: Path) -> dict:
    if not snapshot.identity.exists or not snapshot.content.strip():
        return {}
    try:
        data = json.loads(snapshot.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{path} is not valid JSON ({exc}) — fix it or move it aside, "
            "then re-run rag install"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not valid JSON: root must be an object")
    return data


def _render(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def install_claude(
    settings_path: Path,
    *,
    python: str,
    check: bool = False,
    environ: Mapping[str, str] | None = None,
) -> ClaudeInstallReport:
    settings_path = Path(os.path.abspath(Path(settings_path).expanduser()))
    env = os.environ if environ is None else environ
    snapshot = _snapshot(settings_path, label=LABEL)
    current = _load(snapshot, settings_path)
    merged = merge_settings(current, python)
    desired = _render(merged)
    changed = not snapshot.identity.exists or desired != snapshot.content.decode(
        "utf-8", errors="replace")
    warnings = policy_warnings(merged, env)
    if check or not changed:
        return ClaudeInstallReport(
            settings_path, check, changed, None, None, warnings, managed_settings())

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    backups = _backup_changed((settings_path,), {settings_path: snapshot})
    backup = backups[0] if backups else None
    staged = _stage_text(settings_path, desired)
    try:
        if _snapshot(settings_path, label=LABEL).identity != snapshot.identity:
            raise RuntimeError(f"{LABEL} file changed concurrently: {settings_path}")
        os.replace(staged, settings_path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    installed = InstalledFile(
        settings_path, _snapshot(settings_path, label=LABEL).identity)
    return ClaudeInstallReport(
        settings_path, False, True, backup, installed, warnings, managed_settings())


def restore_claude(
    settings_path: Path,
    backup: BackupRecord | None,
    installed: InstalledFile,
) -> tuple[Path, ...]:
    """Put the recorded backup back only if nothing drifted since install."""
    settings_path = Path(settings_path)
    live = _snapshot(settings_path, label=LABEL)
    if live.identity != installed.identity:
        raise RuntimeError(
            f"{settings_path} changed since installation; refusing to overwrite "
            "— compare it with the backup and restore by hand"
        )
    if backup is None:
        settings_path.unlink()
        return (settings_path,)
    saved = _snapshot(backup.backup_path, label=LABEL)
    if backup.identity is None or saved.identity != backup.identity:
        raise RuntimeError(
            f"backup changed since installation: {backup.backup_path}")
    staged = _stage_text(settings_path, saved.content.decode("utf-8"))
    try:
        if _snapshot(settings_path, label=LABEL).identity != installed.identity:
            raise RuntimeError(f"{LABEL} file changed concurrently: {settings_path}")
        os.replace(staged, settings_path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return (settings_path,)
```

- [ ] **Step 5: Run the adapter tests**

Run: `uv run pytest tests/test_claude_install.py tests/test_codex_install.py -q`
Expected: PASS (the concurrent-edit test passes because `_stage_text` is looked up on the module at call time).

- [ ] **Step 6: Write the failing orchestration tests**

Replace `test_install_writes_settings_and_reresolves_launchd` in `tests/test_install.py` and add the new orchestration tests:

```python
@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_install_writes_settings_records_rollback_and_reresolves_launchd(
        tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus"}')
    monkeypatch.setattr(install, "register_mcp", lambda python, run: None)
    seen = {}

    def fake_launchd(cfg, rag_bin):
        seen["rag_bin"] = rag_bin
        return tmp_path / "plist"
    monkeypatch.setattr(install.backup, "install_launchd", fake_launchd)

    rep = install.install(Config(), settings_path=settings,
                          state_dir=tmp_path / "state")

    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert set(data["hooks"]) >= {"SessionStart", "PreCompact", "SessionEnd"}
    assert data["autoCompactWindow"] == 500000
    assert rep.claude_report is not None and rep.claude_report.changed
    assert rep.rollback_path is not None
    assert rep.rollback_path.parent == tmp_path / "state"
    assert (rep.rollback_path.stat().st_mode & 0o777) == 0o600
    assert json.loads(rep.rollback_path.read_text())["target"] == "claude"
    assert str(seen["rag_bin"]).endswith("/rag")
    assert rep.plist_path == tmp_path / "plist"


def test_install_check_for_claude_registers_nothing_and_writes_nothing(
        tmp_path, monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("check mode must not register MCP or launchd")
    monkeypatch.setattr(install, "register_mcp", must_not_run)
    monkeypatch.setattr(install.backup, "install_launchd", must_not_run)
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "claude-fable-5-1[1m]"}')

    rep = install.install(Config(), settings_path=settings, check=True,
                          state_dir=tmp_path / "state")

    assert rep.claude_report is not None
    assert rep.claude_report.check is True
    assert rep.mcp_registered is False
    assert rep.rollback_path is None
    assert json.loads(settings.read_text()) == {"model": "claude-fable-5-1[1m]"}
    assert not (tmp_path / "state").exists()


def test_restore_dispatches_on_record_target(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "register_mcp", lambda python, run: None)
    monkeypatch.setattr(install.sys, "platform", "linux")
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "before"}')
    rep = install.install(Config(), settings_path=settings,
                          state_dir=tmp_path / "state")

    with pytest.raises(ValueError, match="targets Claude"):
        install.install(Config(), codex=True, restore_path=rep.rollback_path)

    restored = install.install(Config(), restore_path=rep.rollback_path)

    assert restored.restored_paths == (settings,)
    assert settings.read_text() == '{"model": "before"}'


def test_restore_rejects_check_combination(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        install.install(Config(), check=True, restore_path=tmp_path / "r.json")
```

Delete `test_restore_requires_codex_and_cannot_be_combined_with_check` (its first assertion no longer holds). Keep `test_install_aborts_on_corrupt_settings` unchanged. In `test_install_skips_launchd_off_darwin` pass `state_dir=tmp_path / "state"` to `install.install(...)` so the rollback record never lands in the real `~/.agentic-rag/state`.

In `tests/test_cli.py` delete `test_install_check_requires_explicit_codex_target` (`--check` is now valid for the Claude target) and add:

```python
def test_cli_install_flags_allow_claude_check_and_restore(monkeypatch, capsys):
    calls = []

    def fake_install(cfg, **kwargs):
        calls.append(kwargs)
        return cli.install_mod.InstallReport(None, None, False)
    monkeypatch.setattr(cli.install_mod, "install", fake_install)

    assert cli._main(["install", "--check"]) == 0
    assert calls[-1]["check"] is True and calls[-1]["codex"] is False
    with pytest.raises(SystemExit):
        cli._main(["install", "--check", "--restore", "/x.json"])
    with pytest.raises(SystemExit):
        cli._main(["install", "--codex-home", "/h"])
```

- [ ] **Step 7: Run to verify they fail**

Run: `uv run pytest tests/test_install.py tests/test_cli.py -q`
Expected: FAIL — `TypeError: install() got an unexpected keyword argument 'state_dir'`, `AttributeError: 'InstallReport' object has no attribute 'claude_report'`.

- [ ] **Step 8: Implement orchestration**

In `agentic_rag/install.py`:

1. Import the adapter: `from .integrations.claude import install as claude_install`. Add `CLAUDE_ROLLBACK_VERSION = 1` next to `CODEX_ROLLBACK_VERSION`.
2. Extend `InstallReport`:

```python
@dataclass(frozen=True)
class InstallReport:
    settings_path: Path | None
    plist_path: Path | None
    mcp_registered: bool
    codex_report: codex_install.CodexInstallReport | None = None
    rollback_path: Path | None = None
    restored_paths: tuple[Path, ...] = ()
    claude_report: claude_install.ClaudeInstallReport | None = None
```

3. Extract the atomic record writer from `record_codex_rollback` and reuse it:

```python
def _write_rollback_record(state_dir: Path, name: str, data: dict) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    record_path = state_dir / name
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{name}.", suffix=".tmp", dir=state_dir)
    staged = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        staged.chmod(0o600)
        os.link(staged, record_path, follow_symlinks=False)
    finally:
        staged.unlink(missing_ok=True)
    return record_path


def record_codex_rollback(report: codex_install.CodexInstallReport) -> Path:
    """Atomically persist the identities needed by ``restore_codex``."""
    data = _record_data(report)
    state_dir = report.paths.home / ".agentic-rag" / "state"
    return _write_rollback_record(
        state_dir, f"codex-rollback-{uuid.uuid4().hex}.json", data)


def record_claude_rollback(
    report: claude_install.ClaudeInstallReport, *, state_dir: Path | None = None
) -> Path:
    if report.check or not report.changed or report.installed is None:
        raise RuntimeError("Claude install did not produce a restorable report")
    backup = None
    if report.backup is not None:
        current = codex_install._snapshot(
            report.backup.backup_path, label="Claude settings")
        if report.backup.identity is None or current.identity != report.backup.identity:
            raise RuntimeError(
                f"valid rollback backup is unavailable: {report.backup.backup_path}")
        backup = {
            "backup_path": str(report.backup.backup_path),
            "identity": _identity_data(report.backup.identity),
        }
    data = {
        "version": CLAUDE_ROLLBACK_VERSION,
        "target": "claude",
        "settings_path": str(report.settings_path),
        "backup": backup,
        "installed": {"identity": _identity_data(report.installed.identity)},
    }
    directory = state_dir or (Path.home() / ".agentic-rag" / "state")
    return _write_rollback_record(
        directory, f"claude-rollback-{uuid.uuid4().hex}.json", data)


def _load_claude_rollback(record_path: Path) -> tuple[
    Path, codex_install.BackupRecord | None, codex_install.InstalledFile
]:
    record_path = _absolute(record_path)
    snapshot = codex_install._snapshot(record_path, label="rollback record")
    if not snapshot.identity.exists:
        raise RuntimeError(f"invalid Claude rollback record: {record_path}")
    try:
        data = json.loads(snapshot.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid Claude rollback record: {record_path}") from exc
    expected = {"version", "target", "settings_path", "backup", "installed"}
    if (
        not isinstance(data, dict)
        or set(data) != expected
        or data["version"] != CLAUDE_ROLLBACK_VERSION
        or data["target"] != "claude"
    ):
        raise RuntimeError(f"invalid Claude rollback record: {record_path}")
    try:
        settings_path = _record_path(data["settings_path"], label="settings path")
        backup = None
        if data["backup"] is not None:
            backup_path = _record_path(
                data["backup"]["backup_path"], label="backup path")
            if (
                backup_path.parent != settings_path.parent
                or re.fullmatch(
                    r"[0-9a-f]{32}",
                    backup_path.name.removeprefix(settings_path.name + ".bak."),
                ) is None
            ):
                raise RuntimeError(f"invalid Claude rollback record: {record_path}")
            backup = codex_install.BackupRecord(
                settings_path, backup_path,
                _identity_from_data(data["backup"]["identity"], label="backup"))
        installed = codex_install.InstalledFile(
            settings_path,
            _identity_from_data(data["installed"]["identity"], label="installed"))
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"invalid Claude rollback record: {record_path}") from exc
    return settings_path, backup, installed


def restore_claude_rollback(record_path: Path) -> tuple[Path, ...]:
    settings_path, backup, installed = _load_claude_rollback(record_path)
    return claude_install.restore_claude(settings_path, backup, installed)


def _record_target(record_path: Path) -> str:
    try:
        data = json.loads(Path(record_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid rollback record: {record_path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid rollback record: {record_path}")
    return "claude" if data.get("target") == "claude" else "codex"


def restore_rollback(record_path: Path, *, codex_flag: bool) -> tuple[Path, ...]:
    """Dispatch on the record's target; Codex records carry no target key."""
    target = _record_target(record_path)
    if target == "claude" and codex_flag:
        raise ValueError(
            "rollback record targets Claude settings; run rag install "
            "--restore without --codex")
    if target == "claude":
        return restore_claude_rollback(record_path)
    return restore_codex_rollback(record_path)
```

(`_identity_from_data` currently says "invalid Codex rollback …" in its error; leave the wording, it is only reached on corrupt records.)

4. Rewrite `install()`:

```python
def install(cfg: Config, *, settings_path: Path | None = None,
            run=subprocess.run, with_launchd: bool = True,
            codex: bool = False, check: bool = False,
            codex_home: Path | None = None,
            restore_path: Path | None = None,
            state_dir: Path | None = None) -> InstallReport:
    if restore_path is not None and check:
        raise ValueError("restore and check are mutually exclusive")
    if restore_path is not None:
        restored = restore_rollback(restore_path, codex_flag=codex)
        return InstallReport(None, None, False, restored_paths=restored)
    if codex:
        paths = codex_install.CodexPaths.for_home(
            _absolute(Path.home() if codex_home is None else codex_home)
        )
        report = codex_install.install_codex(paths, check=check, run=run)
        rollback_path = None
        if not report.check and report.changed_paths:
            try:
                rollback_path = record_codex_rollback(report)
            except BaseException as record_failure:
                try:
                    codex_install.restore_codex(report)
                except BaseException as restore_failure:
                    backups = ", ".join(
                        str(item.backup_path) for item in report.backups
                    )
                    raise RuntimeError(
                        "Codex installation could not record rollback and "
                        "automatic restoration failed; manual recovery "
                        f"required from [{backups}]"
                    ) from restore_failure
                raise RuntimeError(
                    "Codex installation was restored because its rollback "
                    "record could not be written"
                ) from record_failure
        return InstallReport(
            None, None, False, report, rollback_path=rollback_path
        )

    python = sys.executable
    settings_path = settings_path or SETTINGS_PATH
    report = claude_install.install_claude(
        settings_path, python=python, check=check)
    if check:
        return InstallReport(settings_path, None, False, claude_report=report)

    rollback_path = None
    if report.changed:
        try:
            rollback_path = record_claude_rollback(report, state_dir=state_dir)
        except BaseException as record_failure:
            claude_install.restore_claude(
                settings_path, report.backup, report.installed)
            raise RuntimeError(
                "Claude installation was restored because its rollback "
                "record could not be written"
            ) from record_failure

    register_mcp(python, run=run)
    plist = None
    if with_launchd and sys.platform == "darwin":
        rag_bin = Path(python).with_name("rag")
        plist = backup.install_launchd(cfg, rag_bin)
    return InstallReport(
        settings_path, plist, True, rollback_path=rollback_path,
        claude_report=report,
    )
```

(`report.installed` is non-None whenever `report.changed` is true; the `restore_claude` signature accepts it directly.)

5. In `agentic_rag/cli.py`: change the `--check` help to `"show the changes without writing files"`, `--restore` help to `"restore a recorded Claude or Codex installation"`; delete the two `p.error` lines `--check requires --codex` and `--restore requires --codex`; keep the other three checks. In the `install` command branch pass `check=args.check` and `restore_path=args.restore` on the Claude call too:

```python
        else:
            rep = install_mod.install(
                cfg, with_launchd=not args.no_launchd,
                check=args.check, restore_path=args.restore,
            )
```

Replace the trailing Claude print block with:

```python
        claude_rep = rep.claude_report
        if claude_rep is not None:
            for key, value in claude_rep.managed:
                print(f"managed: {key}={json.dumps(value)}")
            if claude_rep.changed:
                action = "would change" if claude_rep.check else "changed"
                print(f"{action}: {_safe(claude_rep.settings_path)}")
            else:
                print("Claude settings: already up to date")
            if claude_rep.backup is not None:
                print(f"backup: {_safe(claude_rep.backup.target_path)} <- "
                      f"{_safe(claude_rep.backup.backup_path)}")
            for warning in claude_rep.warnings:
                print(f"warning: {_safe(warning)}")
            if claude_rep.check:
                print("hooks: review changed handlers with `/hooks` after installing")
                print("check complete: no files written; MCP and launchd untouched")
                return 0
        print(f"mcp:      registered '{install_mod.MCP_NAME}' and"
              f" '{install_mod.MCP_NAME_RO}' (user scope)")
        print("          (restrict subagents by allowlisting only"
              " mcp__agentic-rag-ro__* tools in their definitions)")
        print(f"hooks:    {rep.settings_path} — review changed handlers with `/hooks`")
        print("autocompact: verify with `/autocompact` (expect 500000 tokens from settings)")
        print(f"launchd:  {rep.plist_path or 'skipped'}")
        if rep.rollback_path is not None:
            record = shlex.quote(_safe(rep.rollback_path))
            print(f"rollback: rag install --restore {record}")
        return 0
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tests/test_install.py tests/test_cli.py tests/test_claude_install.py tests/test_codex_install.py -q`
Expected: PASS

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all modules). Fix any Codex test that compared the exact `record_codex_rollback` staging prefix (the new helper uses `.{name}.` as prefix; adjust the test expectation only if one asserts on the temporary name).

- [ ] **Step 11: Commit**

```bash
git add agentic_rag/integrations/claude/install.py agentic_rag/integrations/codex/install.py agentic_rag/install.py agentic_rag/cli.py tests/test_claude_install.py tests/test_install.py tests/test_cli.py
git commit -m "feat: previewable, recoverable Claude install with target-aware restore"
```

---

### Task 10: Documentation, changelog, feature registry, backlog

**Files:**
- Create: `docs/00-whats-new-in-0.4.md`
- Modify: `docs/README.md`, `docs/03-quick-start.md`, `docs/05-session-mining-and-curation.md`, `docs/06-configuration-reference.md`, `docs/07-privacy-and-cost.md`, `docs/10-architecture.md`, `docs/11-reference-cli-and-mcp.md`, `README.md`, `CHANGELOG.md`, `FEATURES.md`, `BACKLOG.md`
- Test: `tests/test_docs_continuity.py`

- [ ] **Step 1: Write the failing docs test**

Append to `tests/test_docs_continuity.py`, and add `Path("docs/00-whats-new-in-0.4.md")` to `DOC_PATHS`:

```python
def test_docs_explain_claude_continuity_contract():
    corpus = docs_text()
    assert "autoCompactWindow" in corpus and "500000" in corpus
    assert "[1m]" in corpus
    assert "compact_summary" in corpus
    assert "stdout" in corpus and "PreCompact" in corpus
    assert "10,000" in corpus or "10000" in corpus
    assert "1.5" in corpus and "SessionEnd" in corpus
    assert "handoff" in corpus
    assert "rag install --check" in corpus
    assert "rag install --restore" in corpus
    assert "Claude auto-memory" in corpus or "auto-memory" in corpus
    assert "00-whats-new-in-0.4.md" in Path("docs/README.md").read_text()
    assert "## [Unreleased]" in Path("CHANGELOG.md").read_text()
    assert "Claude continuity" in Path("FEATURES.md").read_text()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_docs_continuity.py -q`
Expected: FAIL — missing file / missing strings.

- [ ] **Step 3: Write the What's New page**

Create `docs/00-whats-new-in-0.4.md`:

```markdown
# What’s New in 0.4.0 (unreleased)

agentic-rag 0.4.0 brings compaction continuity to Claude Code, bound to
Claude's own hook contract. The provider-neutral checkpoint store from 0.3.0
is reused; a thin Claude adapter replaces the three-hook legacy install.

## Claude compaction continuity

The default `rag install` now wires six lifecycle hooks into
`~/.claude/settings.json`:

- `PreCompact` (`manual|auto`, 3 s) persists the deterministic checkpoint,
  queues enrichment, and then prints the versioned compact instructions.
  Claude appends a PreCompact hook's stdout to its compaction prompt, so every
  compaction — automatic or manual — is guided without `/compact <text>`.
- `PostCompact` (`manual|auto`, 3 s) marks the boundary and stores Claude's
  own `compact_summary` as a bounded, secret-stripped **handoff** on the
  checkpoint (default 8,000 characters). It never injects context.
- `SessionStart(source="compact")` restores the checkpoint, including the
  handoff with a CURRENT/HISTORICAL age label. The whole injected context is
  capped at 9,500 characters by default (Claude drops anything over 10,000
  per hook) and announces every cut.
- `SessionEnd` (1 s) queues the final transcript delta for every Claude
  reason (`clear`, `resume`, `logout`, `prompt_input_exit`, `other`). Claude
  allows 1.5 s for all SessionEnd hooks together; `Stop` remains the
  guaranteed enqueue path.

## Managed 1M/500K policy

The installer sets `autoCompactWindow = 500000` — a token count, capped by
the model's window. With a `[1m]` model such as `claude-fable-5-1[1m]` that
means a 1M context with automatic compaction at 500K, the same reserve logic
as the Codex 600K/500K policy. `model` is never rewritten; the installer warns
when the suffix is missing, when `autoCompactEnabled` is false, or when
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` /
`DISABLE_AUTO_COMPACT` / `DISABLE_COMPACT` override it. Verify with
`/autocompact`.

Claude auto-memory stays a complementary local layer, exactly like native
Codex memories. agentic-rag remains the canonical, auditable store.

## Safe installation

```bash
uv run rag init-db                 # migration 008 adds the handoff columns
uv run rag install --check         # preview; writes nothing
uv run rag install                 # unique backup + printed rollback command
```

Hooks are live-reloaded by Claude Code; review them with `/hooks`. Undo with
the printed `rag install --restore <record>` command, which is now
target-aware for Claude and Codex records.

## Upgrade notes

1. Pull, run `uv sync`, then `uv run rag init-db`.
2. `uv run rag install --check`, then `uv run rag install`.
3. In Claude Code: `/hooks` to review, `/autocompact` to confirm 500000 tokens
   from settings, then one manual `/compact` and `uv run rag status` to see
   `checkpoint handoff:`.
```

- [ ] **Step 4: Update the remaining documents**

Make these edits (keep every existing Codex statement intact):

- `docs/README.md`: add under "Start here": `- [What’s New in 0.4.0 (unreleased)](00-whats-new-in-0.4.md) — Claude compaction continuity, the managed 1M/500K policy, handoff capture, check/restore for the Claude install.` Update the chapter blurbs for 03, 05, 06, 10, 11 to mention Claude alongside Codex.
- `docs/03-quick-start.md`: in the Claude install section replace the three-hook sentence with the six-hook list, add `uv run rag install --check` before `uv run rag install`, describe the unique `settings.json.bak.<id>` backup and the printed `rag install --restore` command, add "review with `/hooks`, confirm `/autocompact` shows 500000 tokens from settings", and note that no restart is needed for hooks (MCP registration still needs a new session).
- `docs/05-session-mining-and-curation.md`: add a subsection "Claude continuity around compaction" after the Codex one with the five-step flow (PreCompact snapshot + stdout prompt; PostCompact `compact_summary` → handoff; SessionStart restore with handoff label and 10,000-char cap; SessionEnd every reason within 1.5 s; Stop as guaranteed path) and the sentence "Claude auto-memory is complementary; agentic-rag stays canonical."
- `docs/06-configuration-reference.md`: add rows to `[continuity]` for `handoff_max_chars` (`checkpoint_handoff_max_chars`, `8000`, minimum 400) and `context_max_chars` (`context_max_chars`, `9500`, 1000–10000, "Claude drops per-hook context above 10,000 characters; agentic-rag trims knowledge, domains, checkpoint, then pins, and says so"). Add a "Managed Claude configuration" section with the `autoCompactWindow = 500000` block, the `[1m]` note, the overriding env vars, and "verify with `/autocompact`".
- `docs/07-privacy-and-cost.md`: add that PostCompact's `compact_summary` is stored bounded and secret-stripped on the checkpoint (what it may contain, how to inspect: `SELECT handoff FROM continuation_checkpoints`), that a 1M window costs more per request above 200K input tokens on API billing and consumes subscription usage faster, and that the effect must be measured, not assumed neutral.
- `docs/10-architecture.md`: replace "wires three hooks" with "wires six hooks"; extend the Claude hook table with `PreCompact`, `PostCompact`, `SessionEnd` rows (stdout prompt / handoff / every reason); add migration 008 to the schema list; add `handoff`, `handoff_at` to the `continuation_checkpoints` row; add a "Claude continuity path" diagram:

```text
PreCompact ──► snapshot + enqueue ──► stdout: compact instructions (+ checkpoint id)
Claude compacts (custom instructions appended)
PostCompact ──► latest_pre_compact() → mark_compacted() → attach_handoff(compact_summary)
SessionStart(source="compact")
   └─ latest_for_session() → render_checkpoint(+handoff) → fit_context(≤ context_max_chars)
```

- `docs/11-reference-cli-and-mcp.md`: update the `rag install` row: `--check` previews either target and writes nothing; `--restore` accepts a Claude or Codex record and dispatches on it (`--codex --restore` still works for Codex records; a Claude record with `--codex` is refused). Add a "Claude install, check, and restore" block mirroring the Codex one. Document the Claude hook contracts (PreCompact stdout, PostCompact `compact_summary`, SessionEnd reasons, 10,000-char context limit).
- `README.md`: in the positioning paragraph and install snippet mention Claude compaction continuity and `rag install --check`; link `docs/00-whats-new-in-0.4.md`.
- `CHANGELOG.md` under `## [Unreleased]`:

```markdown
### Added
- **Claude compaction continuity.** The default `rag install` now wires six
  Claude lifecycle hooks. `PreCompact` prints the versioned compact
  instructions (Claude appends hook stdout to its compaction prompt),
  `PostCompact` stores Claude's `compact_summary` as a bounded, secret-stripped
  handoff on the checkpoint, `SessionStart` restores it with an age label and
  caps its whole output at Claude's 10,000-character hook limit, and
  `SessionEnd` queues the final delta for every Claude reason within a 1 s
  timeout. Client detection is payload-driven; Codex behavior is unchanged.
- **Managed 1M/500K Claude policy.** The installer sets
  `autoCompactWindow = 500000`, reports (never rewrites) a model without the
  `[1m]` suffix, and warns about `autoCompactEnabled=false` and overriding
  environment variables.
- **Previewable, recoverable Claude install.** `rag install --check` previews
  the settings merge; a changing install writes a unique `settings.json.bak.<id>`
  backup and a mode-0600 rollback record; `rag install --restore <record>` is
  target-aware for Claude and Codex records.
- **Migration 008** adds `handoff`/`handoff_at` to `continuation_checkpoints`;
  `rag status` shows `checkpoint handoff:` freshness.
```

- `FEATURES.md`: add a "## Claude continuity" section after "Codex continuity" with ✅ entries for the six handlers, the compact prompt channel, the handoff, the context cap, the managed policy, check/restore, and a 🔵 "Live rollout" entry pointing to backlog 0.3. Change the "Claude Code integration" bullet under Memory platform to say six hooks and `--check`.
- `BACKLOG.md` §0: add

```markdown
- 🔵 **0.3** _(chore)_ **Prove Claude continuity end to end.** Code, tests, and
  docs landed on 2026-09-03 (branch `feat/claude-compaction-continuity`).
  Measured `SessionEnd` wall time in the suite: <fill from Task 5>.
  → *Why not done:* the maintainer machine has not yet run `rag install`,
  reviewed `/hooks`, confirmed `/autocompact` = 500000, exercised a manual
  `/compact` (checkpoint + handoff + restored context), an automatic
  compaction, and a `SessionEnd` tail capture. → *Trigger:* Task 11 smoke
  run; record each outcome here. *(M)*
```

- [ ] **Step 5: Run the docs test and the whole suite**

Run: `uv run pytest tests/test_docs_continuity.py -q && uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs README.md CHANGELOG.md FEATURES.md BACKLOG.md tests/test_docs_continuity.py
git commit -m "docs: document Claude compaction continuity and the 1M/500K policy"
```

---

### Task 11: Rollout smoke test on the maintainer machine

**Files:**
- Modify: `BACKLOG.md` (outcomes), `FEATURES.md` (status)

This task runs against the live `~/.claude/settings.json` and the live
database. Each step records its actual output; nothing here is assumed.

- [ ] **Step 1: Apply the migration and preview**

```bash
uv run rag init-db
uv run rag install --check
```

Expected: `applied: 008_checkpoint_handoff.sql`; `managed: autoCompactWindow=500000`; `would change: /Users/<you>/.claude/settings.json`; no `warning:` line for the `[1m]` model; `check complete: no files written`.

- [ ] **Step 2: Install**

```bash
uv run rag install
```

Expected: `changed:` + `backup:` lines, `rollback: rag install --restore …`, MCP and launchd lines. Keep the printed rollback command.

- [ ] **Step 3: Verify inside Claude Code**

In a fresh Claude Code session: `/hooks` shows the six `python -m agentic_rag.hooks.…` handlers with `PreCompact`, `PostCompact`, `SessionEnd`; `/autocompact` shows `500000 tokens (from settings)` (or `capped to … by model` if the model is not `[1m]`).

- [ ] **Step 4: Manual compaction**

Work a few turns, then run `/compact`. Afterwards:

```bash
uv run rag status
psql agentic_rag -c "SELECT id, trigger, compacted_at IS NOT NULL AS compacted, length(handoff) AS handoff_chars, handoff_at FROM continuation_checkpoints ORDER BY created_at DESC LIMIT 3;"
tail -n 20 ~/.agentic-rag/log/hooks.log
```

Expected: newest row `trigger=manual`, `compacted=true`, `handoff_chars` > 0; the restored context in the session shows `## Continuation checkpoint` with a `Handoff (Claude compact summary, CURRENT …)` line; `rag status` shows `checkpoint handoff:` with an age; no new `pre_compact`/`post_compact` errors in `hooks.log`.

- [ ] **Step 5: Automatic compaction and SessionEnd**

During normal long-session use, wait for one automatic compaction (`trigger=auto` row) and end one session with `/clear` or exit; confirm a `mine` job for that session was enqueued (`rag status` queue counts or `SELECT … FROM mining_queue WHERE session_id = …`).

- [ ] **Step 6: Record outcomes and commit**

Update `BACKLOG.md` 0.3 with the measured outcomes (and mark ✅ if every scenario passed) and `FEATURES.md` "Live rollout" status accordingly.

```bash
git add BACKLOG.md FEATURES.md
git commit -m "docs: record Claude continuity rollout outcomes"
```

---

## Self-review against the spec

- §5.2 client detection → Task 2 (argv, `turn_id`, default; environment deliberately excluded — a documented deviation from the spec's second bullet, with the reason in the docstring).
- §5.3 PreCompact stdout, prompt even on DB failure, checkpoint line → Task 3.
- §5.4 PostCompact turn-less match, mark, bounded handoff, audit, replay/replace semantics, no additionalContext → Tasks 1 and 4. Deviation: `store.latest_pre_compact()` carries no `compacted_at IS NULL` predicate — the newest same-trigger PreCompact row wins, compacted or not. The spec's own "different summary replaces" rule depends on this (with the filter, a PostCompact after a failed PreCompact would find no row and drop the newer summary); §5.4 and the docs were amended and the behavior is pinned by `test_post_compact_claude_rematches_newest_checkpoint_even_when_compacted`.
- §5.5 SessionEnd all reasons, `timeout: 1`, measured wall time → Tasks 5 and 8.
- §5.6 handoff section with labels and drop order; total cap with ordered trimming and pin count → Task 6. Deviation (final review): the handoff is truncated to the remaining render budget with the `…[truncated]` marker before any section is dropped, and dropped whole only when fewer than 200 characters would survive — at the shipped 8,000/8,000 defaults a bounded handoff was otherwise never rendered and evicted the reference lists first (`test_renderer_truncates_full_length_handoff_instead_of_dropping_it`).
- §5.7 prompt asset ≤ 4,000 chars, versioned, references SessionStart → Task 3.
- §5.8 managed `autoCompactWindow`, warnings for model/toggle/env → Task 8.
- §5.9 `--check`, unique backup, rollback record, target-aware `--restore`, corrupt JSON abort, `/hooks` and `/autocompact` guidance → Task 9.
- §5.10 migration 008, `Checkpoint` fields, config keys, `rag status` → Tasks 1 and 7.
- §7 testing items 1–13 → Tasks 1–10; item 14 → Task 11.
- §8 documentation → Task 10.
