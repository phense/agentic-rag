# Codex-Backed Session Mining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the active Claude-backed session-mining transform with GPT-5.6 Luna/high through Codex, while making provider-auth outages lossless, bounded, self-recovering, and loudly observable.

**Architecture:** Keep `agentic_rag.llm.run_structured` as the only LLM seam and route it through explicit Codex and Claude adapters. A typed provider-unavailable exception opens a worker circuit that restores the claimed job without consuming its attempt budget, writes an atomic health artifact, and stops further LLM claims; SessionStart and Trading's existing ops-health sentinel expose sustained outages. The existing queue, worker lock, scheduler, transcript digest, schema validation, and audited write gateway remain single-instance and unchanged in authority.

**Tech Stack:** Python 3.13, pytest, psycopg/PostgreSQL 17, `codex exec`, TOML configuration, launchd, Trading ops-health sentinel.

**Spec:** `docs/superpowers/specs/2026-09-02-codex-session-mining-design.md`

## Global Constraints

- The reference deployment provider is `codex`; model is exactly `gpt-5.6-luna`; reasoning effort is exactly `high`. Public package defaults remain Claude/Haiku for backward compatibility.
- Use the operator's ChatGPT-authenticated Codex CLI; do not add an OpenAI API key or direct Responses API integration.
- Do not automate `codex login`, browser/device authentication, or credential refresh.
- Do not add a queue, database, scheduler, parallel miner, or automatic provider fallback.
- Codex runs ephemeral, read-only, bounded by the existing 300-second timeout, and returns schema-constrained JSON.
- Preserve the Claude adapter as an explicit configuration rollback path.
- Preserve transcript digesting, secret stripping, deduplication, routing, and the audited `save_document` gateway.
- Provider unavailability must preserve the job's ordinary attempt budget and stop the current drain after one provider failure.
- Reuse `com.agentic-rag.maintenance` and Trading's existing ops-health email route; create no Codex schedule or mail transport.
- Preserve the untracked `agentic-rag/AGENTS.md` and Trading's uncommitted Alpha Picks/Trading 212 state files.
- Use `apply_patch` for edits. Commit each task separately. Push and PR remain opt-in.
- Before changing Trading `ops/`, wrappers, or unattended paths, execute in an isolated worktree created with `superpowers:using-git-worktrees`.

---

## File Map

### agentic-rag repository

- Modify `agentic_rag/config.py`: provider, reasoning-effort, provider-backoff, and absolute CLI configuration.
- Modify `agentic_rag/llm.py`: provider-neutral entry point, Codex/Claude adapters, typed errors, Codex login preflight, structured-output file handling.
- Create `agentic_rag/provider_health.py`: atomic, sanitized provider-health artifact reads/writes; no queue policy.
- Modify `agentic_rag/worker.py`: provider-unavailable queue transition, drain circuit break, health success/failure calls.
- Modify `agentic_rag/status.py`: provider health and oldest pending/error age in the status snapshot.
- Modify `agentic_rag/hooks/session_start.py`: concise provider-unavailable remediation warning.
- Modify `agentic_rag/cli.py`: render the additional status fields.
- Modify `tests/test_config.py`, `tests/test_llm.py`, `tests/test_worker.py`, `tests/test_status.py`, `tests/test_hook_session_start.py`: TDD coverage.
- Modify `README.md`, `docs/03-quick-start.md`, `docs/05-session-mining-and-curation.md`, `docs/06-configuration-reference.md`, `docs/10-architecture.md`, `docs/12-contributing.md`, `docs/99-design-notes.md`, `CHANGELOG.md`, `BACKLOG.md`: describe deployed behavior and close/add exact backlog state.
- Modify `~/.agentic-rag/config.toml` only after code verification: select Codex/Luna/high with an absolute binary path.

### Trading repository

- Modify `scripts/ops_health_sentinel.py`: read-only provider-health/queue status policy feeding the existing ISSUE digest.
- Modify the existing ops-health test module identified by `rg -l "ops_health_sentinel" tests scripts/tests`: benign, sustained-outage, recovery, and malformed-artifact coverage.
- Modify `CLAUDE.md`, `docs/FEATURES.md`, `BACKLOG.md` only where the shared engine/provider or monitoring state is named.
- Modify `.claude/skills/cron-hardening/Learnings.md` and `.claude/skills/retiring-automation/Learnings.md`: durable incident/migration lessons.

---

### Task 1: Provider Configuration and Codex Structured-Output Adapter

**Files:**
- Modify: `agentic_rag/config.py`
- Modify: `agentic_rag/llm.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_llm.py`

**Interfaces:**
- Consumes: existing `run_structured(prompt, schema, cfg, system=None, timeout=None, runner=subprocess.run, env=None) -> dict` used by mining, curation, and migration.
- Produces: `Config.llm_provider: str`, `Config.llm_reasoning_effort: str`, `Config.provider_backoff_seconds: int`; `LLMJobError`, `LLMUnavailableError`; `check_provider(cfg, *, runner, env) -> None`; provider-neutral `run_structured(...) -> dict` with its existing call signature.

- [ ] **Step 1: Add failing configuration tests**

```python
def test_llm_codex_configuration(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''[llm]\nprovider="codex"\nbin="/x/codex"\nmodel="gpt-5.6-luna"\nreasoning_effort="high"\nprovider_backoff_seconds=3600\n''')
    cfg = load_config(p)
    assert (cfg.llm_provider, cfg.llm_bin, cfg.llm_model) == (
        "codex", "/x/codex", "gpt-5.6-luna")
    assert cfg.llm_reasoning_effort == "high"
    assert cfg.provider_backoff_seconds == 3600

def test_public_defaults_remain_backward_compatible():
    cfg = Config()
    assert (cfg.llm_provider, cfg.llm_model,
            cfg.llm_reasoning_effort) == ("claude", "haiku", "high")
```

- [ ] **Step 2: Run the configuration tests and confirm RED**

Run: `uv run pytest tests/test_config.py -q`

Expected: failures because the provider/reasoning/backoff fields do not exist.

- [ ] **Step 3: Add failing Codex adapter tests**

Add tests using a fake runner that writes to the paths following `--output-schema` and `--output-last-message`:

```python
def test_codex_command_is_ephemeral_read_only_luna_high(tmp_path):
    seen = {}
    def runner(cmd, **kw):
        seen["cmd"] = cmd
        if cmd[1:3] == ["login", "status"]:
            return FakeProc(stdout="Logged in using ChatGPT")
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text('{"ok":true}')
        return FakeProc()
    cfg = Config(llm_provider="codex", llm_bin="/x/codex")
    assert llm.run_structured("mine", SCHEMA, cfg, runner=runner) == {"ok": True}
    cmd = seen["cmd"]
    assert cmd[:2] == ["/x/codex", "exec"]
    assert ["--model", "gpt-5.6-luna"] == cmd[cmd.index("--model"):cmd.index("--model") + 2]
    assert 'model_reasoning_effort="high"' in cmd
    assert "--ephemeral" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in cmd and "--ignore-rules" in cmd
    assert Path(seen["cwd"]).parent == tmp_path
```

Also add explicit tests for:

- `codex login status` non-zero -> `LLMUnavailableError`;
- missing binary, timeout, and empty exit-1 -> `LLMUnavailableError`;
- successful exit with missing/empty/non-JSON/non-object last message -> `LLMJobError`;
- prompt contains both `SYSTEM INSTRUCTIONS` and `TASK` blocks without shell interpolation;
- subprocess runs in an empty temporary directory and ignores user/project config and rules while retaining `CODEX_HOME` authentication;
- schema and output temp files are removed on success, non-zero exit, and timeout;
- provider `claude` preserves the old command shape and hook-disable environment;
- unknown provider raises `ValueError` before subprocess execution.

- [ ] **Step 4: Run focused adapter tests and confirm RED**

Run: `uv run pytest tests/test_llm.py tests/test_config.py -q`

Expected: new Codex tests fail while existing Claude tests remain green.

- [ ] **Step 5: Implement the minimal provider-neutral adapter**

Implement these exact public types in `llm.py`:

```python
class LLMError(RuntimeError): pass
class LLMJobError(LLMError): pass
class LLMUnavailableError(LLMError): pass

def check_provider(cfg: Config, *, runner=subprocess.run,
                   env: dict | None = None) -> None: ...

def run_structured(prompt: str, schema: dict, cfg: Config, *,
                   system: str | None = None, timeout: int | None = None,
                   runner=subprocess.run, env: dict | None = None) -> dict: ...
```

Keep provider-specific helpers private: `_run_codex_structured`, `_run_claude_structured`, `_codex_command`, `_classify_codex_failure`. Use `tempfile.TemporaryDirectory()` for an empty working directory plus schema/output files; pass `cwd=` to the subprocess and add `--ignore-user-config --ignore-rules`. Authentication still comes from `CODEX_HOME`. Pass the prompt as a direct argv element or stdin, never through a shell. Redact diagnostic text with the project's existing secret stripper before raising.

- [ ] **Step 6: Run adapter and all direct consumers**

Run: `uv run pytest tests/test_llm.py tests/test_config.py tests/test_mining.py tests/test_curation.py tests/test_migration.py -q`

Expected: PASS; no real provider subprocess is spawned.

- [ ] **Step 7: Commit Task 1**

```bash
git add agentic_rag/config.py agentic_rag/llm.py tests/test_config.py tests/test_llm.py
git commit -m "feat: add Codex structured-output provider"
```

---

### Task 2: Atomic Provider Health and Lossless Worker Circuit Breaker

**Files:**
- Create: `agentic_rag/provider_health.py`
- Modify: `agentic_rag/worker.py`
- Create: `tests/test_provider_health.py`
- Modify: `tests/test_worker.py`

**Interfaces:**
- Consumes: `llm.LLMUnavailableError`, `Config.provider_backoff_seconds`, existing `claim_next` transaction semantics.
- Produces: `ProviderHealth` dataclass; `read_health(path=HEALTH_PATH) -> ProviderHealth | None`; `record_failure(provider, reason, *, path=HEALTH_PATH, now=None) -> ProviderHealth`; `record_success(provider, *, path=HEALTH_PATH, now=None) -> ProviderHealth`; worker `_provider_unavailable(conn, cfg, job, error) -> None`; `drain(...) -> {done, failed, provider_unavailable}`.

- [ ] **Step 1: Write failing atomic-health tests**

```python
def test_failure_health_preserves_first_failure_and_sanitizes(tmp_path):
    path = tmp_path / "provider-health.json"
    first = record_failure("codex", "token sk-secret failed", path=path,
                           now=FIXED_NOW)
    second = record_failure("codex", "still unavailable", path=path,
                            now=FIXED_NOW + timedelta(hours=1))
    assert second.first_failure_at == first.first_failure_at
    assert second.last_failure_at > first.last_failure_at
    assert "sk-secret" not in path.read_text()

def test_success_closes_circuit_atomically(tmp_path):
    path = tmp_path / "provider-health.json"
    record_failure("codex", "login required", path=path, now=FIXED_NOW)
    state = record_success("codex", path=path, now=FIXED_NOW + timedelta(hours=2))
    assert state.available is True and state.last_success_at is not None
    assert not list(tmp_path.glob("*.tmp"))
```

Also test absent file, malformed JSON (returns an unavailable/diagnostic state rather than raising into SessionStart), file mode where supported, and notification timestamp round-trip.

- [ ] **Step 2: Run health tests and confirm RED**

Run: `uv run pytest tests/test_provider_health.py -q`

Expected: import failure because `provider_health.py` does not exist.

- [ ] **Step 3: Implement atomic provider-health storage**

Write to a sibling temporary file, `flush` + `os.fsync`, then `os.replace`. Store only provider, availability, first/last failure, last success, sanitized reason, and notification timestamps. Do not place queue policy or credentials in this module.

- [ ] **Step 4: Add failing worker circuit tests**

```python
def test_provider_outage_preserves_attempt_and_stops_drain(conn, cfg, monkeypatch):
    _job(conn, "mine", session_id="s1", transcript_path="/a")
    _job(conn, "mine", session_id="s2", transcript_path="/b")
    monkeypatch.setattr(worker.mining, "mine_session",
                        lambda *a, **k: (_ for _ in ()).throw(
                            LLMUnavailableError("codex login required")))
    rep = worker.drain(conn, cfg)
    rows = conn.execute("SELECT status, attempts FROM mining_queue ORDER BY id").fetchall()
    assert rep == {"done": 0, "failed": 0, "provider_unavailable": 1}
    assert [(r["status"], r["attempts"]) for r in rows] == [
        ("pending", 0), ("pending", 0)]
```

Add tests that `next_attempt_at` is approximately `cfg.provider_backoff_seconds` ahead, ordinary `LLMJobError` retains exponential retries, deterministic embed/backup jobs are not mislabeled, a later successful invocation calls `record_success`, and diagnostics are truncated/redacted.

- [ ] **Step 5: Run worker tests and confirm RED**

Run: `uv run pytest tests/test_worker.py -q`

Expected: the first job consumes an attempt and the drain continues or returns the old two-key report.

- [ ] **Step 6: Implement the minimal circuit transition**

Catch `LLMUnavailableError` before the broad exception. In one transaction set `status='pending'`, `attempts=GREATEST(attempts - 1, 0)`, `finished_at=NULL`, sanitized `last_error`, and the provider backoff. Record failure, increment `provider_unavailable`, and `break`. Preserve `_fail` unchanged for job-specific failures.

- [ ] **Step 7: Run health, worker, mining, and curation tests**

Run: `uv run pytest tests/test_provider_health.py tests/test_worker.py tests/test_mining.py tests/test_curation.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add agentic_rag/provider_health.py agentic_rag/worker.py tests/test_provider_health.py tests/test_worker.py
git commit -m "fix: preserve mining jobs during provider outages"
```

---

### Task 3: Status and SessionStart Visibility

**Files:**
- Modify: `agentic_rag/status.py`
- Modify: `agentic_rag/hooks/session_start.py`
- Modify: `agentic_rag/cli.py`
- Modify: `tests/test_status.py`
- Modify: `tests/test_hook_session_start.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `provider_health.read_health()` and current `mining_queue` timestamps.
- Produces: `StatusReport.provider_health`, `StatusReport.oldest_open_mine_at`; rendered warning `⚠️ session mining provider codex unavailable since ... — run codex login`.

- [ ] **Step 1: Add failing status and context tests**

```python
def test_context_surfaces_provider_remediation(conn, cfg, tmp_path, monkeypatch):
    health = tmp_path / "provider-health.json"
    provider_health.record_failure("codex", "login required", path=health,
                                   now=FIXED_NOW)
    monkeypatch.setattr(session_start.provider_health, "HEALTH_PATH", health)
    text = session_start.build_context(conn, cfg, "/project")
    assert "session mining provider codex unavailable" in text
    assert "codex login" in text
```

Add a recovery-state test with no warning, a malformed-health warning, oldest-pending timestamp coverage, and CLI rendering without leaking raw secrets.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run pytest tests/test_status.py tests/test_hook_session_start.py tests/test_cli.py -q`

Expected: status fields and provider warning are absent.

- [ ] **Step 3: Implement status aggregation and rendering**

Keep filesystem parsing in `provider_health`; status only composes its result with one SQL query:

```sql
SELECT min(enqueued_at) AS at
FROM mining_queue
WHERE kind = 'mine' AND status IN ('pending', 'processing', 'error')
```

SessionStart must remain fail-closed-visible if health parsing fails. The warning is one concise line and points to `rag status` plus `codex login`.

- [ ] **Step 4: Run status/hook/CLI tests**

Run: `uv run pytest tests/test_status.py tests/test_hook_session_start.py tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add agentic_rag/status.py agentic_rag/hooks/session_start.py agentic_rag/cli.py tests/test_status.py tests/test_hook_session_start.py tests/test_cli.py
git commit -m "feat: surface session-mining provider health"
```

---

### Task 4: Trading Ops-Health Integration

**Files:**
- Modify: `/Users/example/Agents/Trading/scripts/ops_health_sentinel.py`
- Modify: the existing test file returned by `rg -l "ops_health_sentinel" /Users/example/Agents/Trading/tests /Users/example/Agents/Trading/scripts/tests`

**Interfaces:**
- Consumes: read-only `~/.agentic-rag/state/provider-health.json`; optionally `rag status --json` only if the current CLI already exposes a stable JSON contract.
- Produces: `check_agentic_rag_mining_health(...) -> list[str]` feeding the sentinel's existing issue list; no new mail sender.

- [ ] **Step 1: Create an isolated Trading worktree**

Invoke `superpowers:using-git-worktrees`. Confirm the main Trading checkout remains on `main` and its uncommitted Alpha Picks/Trading 212 files remain untouched. Use a branch such as `codex-session-mining-health`.

- [ ] **Step 2: Add failing benign/outage tests**

```python
def test_agentic_rag_mining_health_is_quiet_when_healthy(tmp_path):
    path = tmp_path / "provider-health.json"
    path.write_text(json.dumps({"provider":"codex", "available":True,
                                "last_success_at":"2026-09-02T12:00:00+00:00"}))
    assert check_agentic_rag_mining_health(path=path, now=NOW) == []

def test_agentic_rag_mining_health_alerts_after_grace(tmp_path):
    path = tmp_path / "provider-health.json"
    path.write_text(json.dumps({"provider":"codex", "available":False,
                                "first_failure_at":"2026-09-02T08:00:00+00:00",
                                "reason":"login required"}))
    issues = check_agentic_rag_mining_health(path=path, now=NOW,
                                             grace=timedelta(hours=2))
    assert len(issues) == 1 and "codex login" in issues[0]
```

Add quiet tests for absent artifact/no historical outage and transient outage inside grace; loud tests for malformed artifact and stale/unrecovered outage. Exercise the existing email composition with a fake sender only; never send real mail from tests.

- [ ] **Step 3: Run the focused Trading test and confirm RED**

Run the exact discovered test path with `uv run pytest <path> -q`.

Expected: missing health-check function or missing integration.

- [ ] **Step 4: Implement the read-only sentinel check**

Parse the artifact defensively, compare timezone-aware timestamps, return issue strings, and append them through the existing collector. Do not modify or acknowledge the artifact from the sentinel; deduplication remains the existing only-issues digest behavior plus provider-health timestamps.

- [ ] **Step 5: Run benign and pipeline suites**

Run: focused sentinel test, then `uv run python scripts/test_suites.py pipelines`.

Expected: PASS and zero real messages sent.

- [ ] **Step 6: Commit Task 4 in the Trading worktree**

```bash
git add scripts/ops_health_sentinel.py <discovered-test-file>
git commit -m "feat: monitor agentic-rag mining health"
```

Do not merge the worktree branch into the live Trading checkout yet; integration is an explicit checkpoint after the shared engine is verified.

---

### Task 5: Documentation, Backlog, and Retirement Sweep

**Files:**
- Modify: `README.md`
- Modify: `docs/03-quick-start.md`
- Modify: `docs/05-session-mining-and-curation.md`
- Modify: `docs/06-configuration-reference.md`
- Modify: `docs/10-architecture.md`
- Modify: `docs/12-contributing.md`
- Modify: `docs/99-design-notes.md`
- Modify: `CHANGELOG.md`
- Modify: `BACKLOG.md`
- Modify in Trading worktree: `CLAUDE.md`, `docs/FEATURES.md`, `BACKLOG.md`, `.claude/skills/cron-hardening/Learnings.md`, `.claude/skills/retiring-automation/Learnings.md`

**Interfaces:**
- Consumes: verified behavior and exact config names from Tasks 1–4.
- Produces: one consistent operator contract, explicit rollback, complete retiring-automation checklist.

- [ ] **Step 1: Run the retirement sweep as an evidence checklist**

Record `DONE`/`N/A`/`BLOCKED` for scheduler, watchdogs, writers/consumers, test collection, ops-health coverage, docs/knowledge, rollback. Use:

```bash
rg -n "claude -p|llm_provider|llm_bin|haiku|Claude session|Anthropic" agentic_rag tests README.md docs
rg -n "agentic-rag|session mining|Claude OAuth" /Users/example/Agents/Trading/CLAUDE.md /Users/example/Agents/Trading/docs/FEATURES.md /Users/example/Agents/Trading/BACKLOG.md /Users/example/Agents/Trading/scripts
```

Production LLM calls must all pass through `run_structured`; historical text may remain only when clearly labeled as prior behavior or Claude rollback.

- [ ] **Step 2: Update docs with exact deployed commands and failure semantics**

Document:

```toml
[llm]
provider = "codex"
bin = "/Users/example/.local/bin/codex"
model = "gpt-5.6-luna"
reasoning_effort = "high"
provider_backoff_seconds = 3600
```

State that `codex login` is the human remediation, the job remains pending without attempt consumption, one failure stops the drain, and Claude is config-only rollback. Remove claims that every mining call necessarily uses Claude/Anthropic.

- [ ] **Step 3: Update backlog and shared learnings**

Add/close a numbered blocker-first backlog item for provider-auth circuit breaking. Append the durable lessons: launchd PATH and OAuth are distinct failure layers; provider-wide outages must circuit-break before per-job retry; an always-exit-0 worker requires an independently watched health artifact.

- [ ] **Step 4: Run documentation consistency checks**

Run:

```bash
rg -n "default model `haiku`|every `claude -p`|your Anthropic account" README.md docs agentic_rag
git diff --check
```

Expected: remaining matches are explicitly historical/rollback; no whitespace errors.

- [ ] **Step 5: Commit agentic-rag documentation**

```bash
git add README.md docs/03-quick-start.md docs/05-session-mining-and-curation.md docs/06-configuration-reference.md docs/10-architecture.md docs/12-contributing.md docs/99-design-notes.md CHANGELOG.md BACKLOG.md
git commit -m "docs: document Codex mining and auth recovery"
```

- [ ] **Step 6: Commit Trading documentation in its worktree**

```bash
git add CLAUDE.md docs/FEATURES.md BACKLOG.md .claude/skills/cron-hardening/Learnings.md .claude/skills/retiring-automation/Learnings.md
git commit -m "docs: record Codex mining health migration"
```

---

### Task 6: Full Verification and Safe Deployment

**Files:**
- Modify after verification: `~/.agentic-rag/config.toml`
- Regenerate/verify after code deployment: `~/Library/LaunchAgents/com.agentic-rag.maintenance.plist`
- Read/operate: PostgreSQL `mining_queue` through audited application/CLI commands only.

**Interfaces:**
- Consumes: all prior commits, current ChatGPT login, known 60 provider-failure jobs.
- Produces: deployed Codex configuration, verified launchd execution, recovered queue, rollback commit/config pointer.

- [ ] **Step 1: Invoke verification-before-completion and run the full agentic-rag suite**

Run: `uv run pytest`

Expected: all tests pass with no real Codex/Claude calls and no writes under the real `~/.agentic-rag` test guard.

- [ ] **Step 2: Verify Trading branch suites before integration**

In the Trading worktree run the focused ops-health test and `uv run python scripts/test_suites.py pipelines`. Then run the full Trading root suite required by `retiring-automation`: `uv run pytest`.

Expected: all collected tests pass; no real mail; no Alpha Picks/Trading 212 file mutations.

- [ ] **Step 3: Run one harmless real Codex smoke probe**

First run `codex login status`. Then invoke a repository-provided smoke entry point or a minimal `run_structured` call with schema `{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":false}` and prompt `Return {"ok":true}. Do not use tools.` Verify its child cwd is temporary and neither repository instructions nor installed plugins/hooks load.

Expected: `{"ok": true}`, Luna/high command visible in debug/test capture, no repository diff, no new Codex session file because `--ephemeral` is set.

- [ ] **Step 4: Configure the live engine through apply_patch**

Update `~/.agentic-rag/config.toml` with the exact `[llm]` block from Task 5 while preserving `[backup] cloud_dir`. Do not rewrite the file wholesale.

- [ ] **Step 5: Verify launchd's minimal environment**

Ensure the generated plist uses the absolute agentic-rag executable and configuration uses the absolute Codex executable. Run the maintenance command once with `PATH=/usr/bin:/bin:/usr/sbin:/sbin` and a bounded timeout.

Expected: provider binary is found; worker result is audited; no `binary not found`; a healthy empty/no-due queue is benign.

- [ ] **Step 6: Simulate and verify auth outage without touching real credentials**

Run the worker test/integration fixture with a fake Codex runner returning login failure. Inspect the fixture row and health artifact.

Expected: pending, attempts unchanged, next retry bounded, one health artifact, no second job claim.

- [ ] **Step 7: Merge the verified Trading health branch into main**

Before merge, re-read the main checkout status and confirm protected uncommitted files are unchanged. Merge only the verified commits; merging deploys the ops-health change. Remove the worktree after successful merge using the worktree skill's safe cleanup.

- [ ] **Step 8: Requeue only legacy provider-failure jobs**

Add/use a CLI operation that updates only `kind='mine' AND status='error'` rows whose sanitized `last_error` matches the known Claude missing-binary/exit-1 provider signatures. Preserve id, session_id, transcript_path, payload, and last_uuid; set status pending, attempts 0, next_attempt_at now, finished_at null, and retain a migration note in `last_error`. Print the candidate count and require an explicit confirmation before mutation.

Expected candidate count before mutation: 60. If it differs, stop and inspect; never broaden the predicate.

- [ ] **Step 9: Drain in bounded batches and inspect contracts**

Run the existing worker once (50-job cap), then `rag status`; inspect saved/duplicate/skipped counts and provider health. Run once more for the remainder.

Expected: all legacy provider failures complete or leave a distinct, evidence-backed job error; no provider-failure error rows, no processing orphans, health available.

- [ ] **Step 10: Update active-crons and durable migration knowledge through `rag save`**

Use `rag get active-crons`, update it via `rag save --slug active-crons`, and save one migration memory naming the Codex/Luna/high cutover, circuit-break semantics, deployed commits, and rollback configuration. Never write store rows directly.

- [ ] **Step 11: Run final status and repository checks**

Run:

```bash
rag status
git status --short --branch
```

Also check the Trading main status, launchd last exit, provider-health JSON, and newest worker/maintenance log lines. Expected: queue healthy, launchd exit 0, provider available, only pre-existing protected uncommitted files remain.

- [ ] **Step 12: Commit any deployment-generated tracked change separately**

Do not commit home-directory config, logs, state artifacts, or database contents. If launchd installation changes a tracked template, commit only that template with `chore: deploy Codex session mining`.

---

## Plan Self-Review

- Spec coverage: provider adapter (Task 1), auth classification and circuit breaker (Task 2), visibility (Tasks 3–4), output/data safety (Tasks 1–2), retirement/docs (Task 5), real deployment and 60-job recovery (Task 6).
- Bounds: existing single-worker lock, 50-job cap, 300-second subprocess timeout, one-hour provider backoff, no parallel schedule, no automatic fallback.
- Benign alert states: absent/healthy/transient/recovery/malformed artifact tests are explicit in Tasks 3–4.
- Type consistency: `LLMUnavailableError`, `check_provider`, `ProviderHealth`, `read_health`, `record_failure`, `record_success`, and the three-key drain report use the same names throughout.
- Destructive scope: no deletion; the legacy requeue predicate is exact, count-gated at 60, preserves cursors/payloads, and stops on mismatch.
- Placeholder scan: no TBD/TODO/“implement later” instructions; every implementation step names exact behavior, test, and verification.
