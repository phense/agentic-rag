# Antigravity compact continuation instructions — bounded handoff

Version: 1.0

You are compacting an agentic-rag-backed Antigravity CLI session. Produce a
bounded handoff so the next model request can continue the same task without
asking the user to repeat known context. Do not continue the task, call tools,
or invent state. Preserve only evidence-backed facts.

agentic-rag has already stored a deterministic continuation checkpoint for
this compaction and will re-inject the pinned rules, the knowledge-domain map,
and that checkpoint into later requests. Reference that material instead of
repeating it.

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
