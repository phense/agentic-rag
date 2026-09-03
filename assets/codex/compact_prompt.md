# Codex compact continuation prompt

Version: 1.0

Use this bounded prompt when restoring a Codex session from an agentic-rag
checkpoint. Continue the work from the recorded state; do not ask Peter to
repeat known context. Ask a question only when a genuinely missing decision
or authorization prevents safe progress.

## Continuity contract

Treat the checkpoint as evidence, not as a claim that the world is unchanged.
Preserve these fields and their distinctions:

- Objective: the concrete goal being pursued.
- Success criteria: the observable conditions that define completion.
- User instructions: constraints and approvals that remain authoritative.
- Decisions: accepted choices and rejected alternatives; do not silently
  reverse them.
- Worktree: current project root, branch, HEAD, and repository status.
- Uncommitted: user-owned dirty files and changes. Preserve user-owned dirty
  files: never reset, clean, checkout, overwrite, or discard them without
  explicit authorization.
- Test results: only report tests as verified when the checkpoint records a
  direct result; otherwise label them unverified.
- Active processes: process observations are historical and must be labeled
  stale or unverified unless rechecked now.
- Blockers: known impediments, including their evidence and owner if recorded.
- Next exact action: the smallest safe action to perform next.

## Evidence and freshness

Label every important state as verified, stale, or unverified. A snapshot is
deterministic state with semantic enrichment pending; it is not proof that
tests passed, a process is still active, or an external service is healthy.
Enriched claims remain evidence-backed observations. Revalidate volatile state
before relying on active processes, external states, branch/status, test
results, or blockers that may have changed. If revalidation contradicts a
checkpoint, prefer the fresh observation and record the discrepancy.

## References and bounded context

Use artifact paths and agentic-rag slugs as pointers to source material. Open
the relevant artifact only when needed; do not embed an artifact body,
transcript bodies, diffs, or large documents in this compact prompt. Preserve the
recorded `[[slug]]` references and cite the path or slug when using them.

## Continuation procedure

1. Read the objective, success criteria, user instructions, decisions,
   blockers, and next exact action.
2. Inspect the current worktree and uncommitted files before editing. Preserve
   all user-owned dirty files and account for any drift from the checkpoint.
3. Revalidate stale or unverified state that affects the next action, then run
   the smallest relevant test or inspection.
4. Continue with the next exact action, updating the plan when evidence changes
   it. Do not restart completed work or re-ask known context.
