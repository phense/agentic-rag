# Antigravity CLI (agy) compaction continuity

**Date:** 2026-09-06
**Status:** Implemented on `feat/agy-continuity`; live rollout pending
**Owner:** Project maintainer
**Scope:** Antigravity CLI lifecycle hooks, a `hooks.json` installer, a
versioned compact prompt, Antigravity transcript support in mining and
enrichment, documentation, and operational rollout

## 1. Problem

agentic-rag 0.3/0.4 preserve execution state across Codex and Claude Code
compaction. The maintainer now also runs Google's Antigravity CLI (`agy`,
Gemini 3.8 Flash / 3.1 Pro). Its sessions compact too, but agentic-rag had no
adapter: no context injection, no checkpoint at the compaction boundary, no
mining of its transcripts.

## 2. Facts established before design (2026-09-06)

All from the `agy` 1.1.27 binary (embedded hook documentation and protobuf
descriptors) and live probes with a temporary dumping `hooks.json`.

| Fact | Evidence |
|---|---|
| Gemini 3.8 Flash and 3.1 Pro: 1,048,576 input / 65,536 output tokens. | Google AI model page; OpenRouter; Artificial Analysis. |
| `/compact` exists ("Compact the conversation now (summarize history to free up the context window)") and works headless via `--input-format stream-json`. | Binary string; three-turn probe (codeword survived compaction). |
| Automatic compaction is server-side context summarization; result is inserted as `<CONTEXT_SUMMARY>…</CONTEXT_SUMMARY>` ("The following is a summary of the conversation history that has been truncated to fit within the context window"); step type `CHECKPOINT`; no user-settable threshold (`cascade_config.checkpoint_config.max_token_limit` is provider-controlled). | Binary strings; `/config` list has no compaction setting. |
| Hook events: `PreToolUse`, `PostToolUse` (matcher groups), `PreInvocation`, `PostInvocation`, `Stop` (flat lists), plus undocumented `SessionStart` (proto `SessionStartHookArgs`, `CallSessionStartHook`). No PreCompact/PostCompact/SessionEnd/UserPromptSubmit. | Embedded `hooks.json` doc; proto descriptor; live probe: SessionStart fired once per new conversation, not on `-c`. |
| `hooks.json` locations: `~/.gemini/config/hooks.json` (shared CLI/IDE/app) and `<workspace>/.agents/hooks.json` (trusted workspaces only). Format: `{ "<name>": { "enabled"?, "<Event>": [...] } }`; handler `{type:"command", command, timeout(30)}`; cwd = directory of `hooks.json`; env carries `ANTIGRAVITY_CONVERSATION_ID`. | Embedded doc; probe (`loaded 1 named hooks from 1 hooks.json file(s)`). |
| Common payload (camelCase): `conversationId`, `workspacePaths` (empty unless the workspace is trusted / `--add-dir`), `transcriptPath` = `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript_full.jsonl`, `artifactDirectoryPath`, `modelName`. PreInvocation/PostInvocation add `invocationNum`, `initialNumSteps`; Stop adds `executionNum`, `terminationReason`, `error`, `fullyIdle`. `modelOutput`/`lastUserInput` exist in the proto but were not delivered. | Probe dumps. |
| `{"injectSteps":[{"ephemeralMessage":"…"}]}` from SessionStart and PreInvocation reaches the model. | Probe: model answered `fruit=MANGO animal=OTTER` from two injected facts. |
| A `/compact` turn is an ordinary turn: PreInvocation(invocationNum 0) → PostInvocation → Stop; the transcript shows `USER_INPUT` `/compact` followed by a `PLANNER_RESPONSE` whose content is the summary. | Probe transcript. |
| Transcript: JSONL steps `{step_index, source, type, status, created_at, content | tool_calls}`; user prompts wrapped in `<USER_REQUEST>` with `<ADDITIONAL_METADATA>`/`<USER_SETTINGS_CHANGE>` blocks. | Embedded format doc; probe transcripts. |

## 3. Goals and non-goals

### Goals

- Inject pins, domains, project knowledge, and the checkpoint at conversation
  start; recall error signatures per prompt.
- Persist a checkpoint and guide the summary on every manual `/compact`;
  retain the model's summary as the bounded handoff.
- Detect an automatic compaction after the fact, record the boundary with the
  summary as handoff, and restore the checkpoint into the next request
  (there is no SessionStart after automatic compaction).
- Mine Antigravity transcripts with the existing pipeline.
- Keep the install additive, previewable, backed up, and restorable like the
  Claude and Codex targets.

### Non-goals

- No Antigravity compaction policy (none exists to manage).
- No PostInvocation hook (nothing to gain; `Stop` reads the transcript).
- No Gemini mining provider (`[llm]` stays Codex/Claude; `agy -p` could be
  added later, BACKLOG).
- No SessionEnd equivalent; `Stop` is the enqueue path.

## 4. Architecture

```text
agentic_rag/
  transcript_agy.py            step parsing, prose digest, compaction detection
  transcript.py                + agy steps in build_digest (enrichment)
  mining_window.py             + agy steps in read_window (mining)
  continuity/capture.py        + agy-step-<n> cursor from the transcript tail
  hooks/agy.py                 dispatcher: session-start | pre-invocation | stop
  hooks/prompt_recall.py       recall_context() shared with the dispatcher
  integrations/agy/
    hooks.py                   owned named hook + lossless merge
    install.py                 check / unique backup / atomic publish / restore
    prompt.py                  versioned compact prompt loader
  install.py                   --agy target, target-aware rollback records
  cli.py                       --agy, --agy-home; install output
assets/agy/compact_prompt.md   Version: 1.0
```

### 4.1 Event mapping

| Antigravity | agentic-rag behaviour |
|---|---|
| `SessionStart` | `session_start.build_context(cwd=workspacePaths[0], session_id=conversationId, source="startup")` → one `ephemeralMessage`; maintenance trigger; DB failure → visible `⚠️ agentic-rag unavailable`. |
| `PreInvocation`, `invocationNum == 0` | Read transcript tail (256 KB). Trailing `/compact` request → PreCompact (cursor `agy-step-<idx>`, trigger `manual`, enrichment queued) and inject compact prompt + checkpoint line. Otherwise newest auto marker (`type ∈ {CHECKPOINT, CONTEXT_SUMMARY}` or `SYSTEM` step containing `<CONTEXT_SUMMARY>`) not yet in the store → PreCompact (trigger `auto`) + mark compacted + handoff + inject `build_context(source="compact")`. Otherwise error-signature recall on the last user request. |
| `PreInvocation`, `invocationNum > 0` | `{}` (no database access). |
| `Stop` | If the last user request is `/compact` and the newest manual PreCompact checkpoint has that cursor: mark compacted, attach the following `PLANNER_RESPONSE` content as handoff. Always enqueue the transcript delta (`transcript_delta.enqueue_transcript_delta`). |

Idempotence: `upsert_snapshot(update_existing=False)` keyed on
`(conversationId, agy-step-<idx>)`; a replayed PreInvocation re-injects the
same prompt; a replayed auto marker is a no-op because `compacted_at` is set.

### 4.2 Install

`rag install --agy` merges `{"agentic-rag": {enabled, SessionStart,
PreInvocation, Stop}}` into `~/.gemini/config/hooks.json`, removing only
handlers whose command contains `agentic_rag.hooks.` from foreign names.
Check mode writes nothing; a change backs up to `hooks.json.bak.<32 hex>`,
publishes atomically, records `~/.agentic-rag/state/agy-rollback-<id>.json`
(mode 0600, `target: "agy"`, `hooks_path`), and prints
`rollback: rag install --agy --restore <record>`. Restore refuses drift.

### 4.3 Hook contract

Every dispatcher path prints a JSON object and exits 0; all errors go to
`~/.agentic-rag/log/hooks.log` under `agy.<event>`; `AGENTIC_RAG_HOOKS_DISABLE`
silences everything. Timeouts: SessionStart 10 s, PreInvocation 5 s, Stop 10 s.

## 5. Open risks

- The automatic-compaction marker shape is inferred from binary strings, not
  observed. The detector accepts two signals and logs when it fires; BACKLOG
  0.4 tracks the live observation.
- `workspacePaths` is empty in untrusted workspaces and in print mode without
  `--add-dir`; then no project scoping and no repository state are captured.
- The transcript is rewritten during compaction ("Fixed corruption of the
  saved transcript when a background message appended to it while context
  compaction was rewriting it"); tail reads tolerate partial lines.
