# What’s New in 0.5.0

agentic-rag 0.5.0 adds a third coding agent: Google's **Antigravity CLI**
(`agy`, the Gemini-backed terminal agent). The provider-neutral checkpoint
store, the mining pipeline, and the recall hooks are reused unchanged; a thin
`agy` adapter maps Antigravity's own hook contract onto them.

## What Antigravity offers, and what it does not

The facts below were read from the `agy` 1.1.27 binary and verified with
live hook probes on 2026-09-06.

- **Context window.** Gemini 3.8 Flash and Gemini 3.1 Pro both accept
  1,048,576 input tokens and emit up to 65,536 output tokens.
- **Compaction.** `/compact` exists and works headless; automatic context
  summarization also exists, but it runs server-side, has **no configurable
  threshold**, and inserts its result as a `<CONTEXT_SUMMARY>` block.
- **Hooks.** One `hooks.json` (user-level `~/.gemini/config/hooks.json` or
  `<workspace>/.agents/hooks.json`) keyed by hook *name*. Events:
  `PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, `Stop`, and
  the undocumented but working `SessionStart` (fires for new conversations
  only, not for `-c`/`/resume`). Payloads are camelCase
  (`conversationId`, `workspacePaths`, `transcriptPath`, `modelName`).
  Context is injected with `{"injectSteps": [{"ephemeralMessage": "…"}]}`.
- **No PreCompact/PostCompact/SessionEnd/UserPromptSubmit.** A `/compact`
  turn is an ordinary turn in the hook stream; the summary lands in the
  transcript as a normal model step.
- **Transcripts.** `…/brain/<conversation>/.system_generated/logs/transcript_full.jsonl`
  holds one step per line (`step_index`, `type` = `USER_INPUT` /
  `PLANNER_RESPONSE`, `content`, `tool_calls`).

## Antigravity compaction continuity

`rag install --agy` merges one named hook, `agentic-rag`, into
`~/.gemini/config/hooks.json`:

- `SessionStart` (10 s) injects pins, the domain map, project knowledge, and
  the continuation checkpoint as one ephemeral message — fail-closed-visible,
  exactly like the Claude hook.
- `PreInvocation` (5 s) works only on the first model call of a turn. It
  reads the transcript tail and
  - treats a trailing `/compact` request as **PreCompact**: persists the
    checkpoint, queues enrichment, and injects the versioned
    `assets/agy/compact_prompt.md` plus `agentic-rag checkpoint: <id>` so the
    summary follows the same handoff contract as Claude and Codex;
  - treats a new automatic-compaction marker (`CHECKPOINT` step or
    `<CONTEXT_SUMMARY>` block) as PreCompact **and** PostCompact in one step,
    stores the summary as the handoff, and re-injects the checkpoint, because
    no `SessionStart` follows an automatic compaction;
  - injects error-signature recall for the new prompt (the `UserPromptSubmit`
    equivalent).
- `Stop` (10 s) attaches the model's `/compact` summary as the bounded,
  secret-stripped handoff (**PostCompact**) and queues the transcript delta
  for mining.

Mining, checkpoint enrichment, and `rag status` understand the Antigravity
step format; cursors are `agy-step-<index>`.

## Safe installation

```bash
uv run rag install --agy --check   # preview; writes nothing
uv run rag install --agy           # unique backup + printed rollback command
```

Antigravity loads `hooks.json` at startup: start a new `agy` conversation
after installing and review the `agentic-rag` hook with `/hooks`. Undo with
the printed `rag install --agy --restore <record>` command; restore is
target-aware for Claude, Codex, and Antigravity records.

## Upgrade notes

1. Pull, run `uv sync`. No new migration is required.
2. `uv run rag install --agy --check`, then `uv run rag install --agy`.
3. Start a new `agy` conversation in a trusted workspace, run `/hooks`, then
   one manual `/compact` and `uv run rag status` to see `checkpoint handoff:`.
4. Automatic compaction has not been observed live yet; the detector logs
   `agy.auto_compaction` to `~/.agentic-rag/log/hooks.log` when it fires.
   See BACKLOG 0.4.
