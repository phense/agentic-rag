# Codex compact continuation prompt — bounded handoff

Version: 2.0

Generate a bounded handoff summary from the active conversation history.
Do not continue the task, call tools, or invent missing state. Preserve only
evidence-backed information needed for another model invocation to continue
without asking for context that is already known.

Include, in this order:

1. Current objective and explicit success criteria.
2. Still-active user instructions, approvals, constraints, and prohibitions.
3. Decisions made, rejected alternatives, and the evidence or reason for each.
4. Current repository, canonical project root, CWD, branch/worktree, HEAD, and
   user-owned or uncommitted changes. Label repository facts as current only
   when recently verified; otherwise label them historical/unverified.
5. Completed and remaining plan steps, including exact artifact paths rather
   than copied file bodies.
6. Test results: commands and their actual outcomes, each with an observation timestamp
   or an explicit historical/unverified label.
7. Active processes and external states only when observed, with timestamp and
   a mandatory instruction to revalidate them.
8. Blockers, risks, and the next exact action.
9. Relevant agentic-rag slugs only as canonical `[[slug]]` references. Do not
   copy any memory body or document body.

Keep the handoff bounded and concise: prefer identifiers, paths, hashes,
timestamps, outcomes, and canonical slugs over prose. Distinguish current,
historical, stale, and unverified facts explicitly. Preserve security-sensitive
boundaries while omitting credentials, secrets, raw transcripts, diffs, logs,
and large artifact bodies.
