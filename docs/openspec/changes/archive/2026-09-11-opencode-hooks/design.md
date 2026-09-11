# Design
Official OpenCode 1.18.30 plugin, SDK and session/compaction sources inspected 2026-09-11:
https://github.com/anomalyco/opencode/blob/v1.18.30/packages/plugin/src/index.ts
https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/session/compaction.ts
https://opencode.ai/docs/plugins/

A native JS plugin invokes a bounded Python dispatcher over stdin, without a shell. It reads only the active session through the supplied SDK client, checks parentID, and serializes work per session. chat.message invalidates prompt context; experimental.chat.system.transform injects transient context, including resumed sessions. Successful summary parentID binds PostCompact to its actual request. system.transform reconciles summaries synchronously, avoiding asynchronous bus ordering assumptions. session.compacted invalidates context; session.idle exports completed prose and queues existing mining.

SDK reads use 200 recent messages and request timeouts. A private secret-stripped JSONL projection merges stable message identities, capped at 8 MiB with explicit omission. Existing transcript/capture/mining code consumes the format unchanged. Exclude synthetic/ignored parts, reasoning, tool arguments/results and children. No reliable SessionEnd exists: abrupt termination may need resume for tail pickup.

The installer owns only plugins/agentic-rag.js; packaged JS binds the existing virtualenv Python. A config hook adds read-only MCP only if absent. No provider settings or credentials are opened or rewritten. Foreign loader bytes and symlinks are refused. Source and virtualenv must remain available.

Reuse context, prompt_recall, continuity.capture/store and jobs. Strip secrets before model-bound context. Hooks do not call an LLM; the current worker provider remains unchanged. Test DB agentic_rag_test only, native probes in synthetic fixtures. Existing main/read-only MCP privilege separation is preserved.
