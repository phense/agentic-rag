# RAG-009 verification and convergence

2026-09-06; implementation base87077ce, isolated feature worktree.

## Acceptance evidence

| Intent | Current evidence |
|---|---|
| AC001 / FR002 / IC001 | tests/test_profiles.py: bounded stable/recent sources, late support, incomplete provenance, whole short statements, cache constraints |
| AC002 / FR003 | test_context_gate.py and test_query_context_without_error_and_negative_gate; real-hook synthetic replay |
| AC003 | startup pin/checkpoint and tight-budget tests, whole multiline pin fitting, omission regressions |
| AC004 | hidden profile/query dedup regression; later identical text test |
| AC005 / IC003 | real turn revision/config receipts, successful emission only, expired receipt renewal and bounded storage |
| AC006 | profile atomic rollback, source loss, expiry and correction tests; real worker failure/retry recovery |
| AC007 / FR001 / IC002 | reader CLI/MCP tests; queue/worker/gateway integration; canonical row preservation; renderer-failure scheduling regression |
| AC008 | checked-in cases/evaluator/results and benchmark README, 12 fictional prompts with dev/test aggregates |

## Fresh checks

- `/Users/peter/Agents/agentic-rag/.venv/bin/python /private/tmp/rag9-isolated-tests.py -q`
  completed: **757 passed in 29.14s**. Runner copies tests to a temporary overlay and
  replaces all shared test database literals with `agentic_rag_test_issue9`; production
  modules are symlinked to this worktree. This avoids interference with another agent's
  concurrent shared-test-database work. Ordinary CI can use its own dedicated default DB.
- Same runner, `tests/test_project_context.py -q`: **10 passed in 2.52s**.
  Includes both independently architect-derived collaborating success/recovery flows.
- `PYTHONPATH=. .../.venv/bin/python docs/benchmarks/2026-09-06-project-context/evaluate.py`:
  successful; isolated database cleanup verified, zero hosted calls. Source hash matches
  current application/SQL. Useful 1/6 ->6/6; unrelated0/6; p95after51.65ms.
- `uv build --wheel --out-dir /private/tmp/rag-issue9-wheel`: successful.
  ZIP read-back verifies exact context/profile/receipt modules and migration014.
- `git diff --check`: passed.

Independent producer and final integration review: **Ready**, no unresolved actionable
findings. Fixed evidence-resolution bounds/provenance, recent updated legacy selection,
and startup profile scheduling after rendering failure. The last finding was reproduced
as a failing regression before the fix. Independent architect inspected both real
integration fixtures and the corrected startup/prompt sequence; database execution was
coordinator-owned. AF009A/B/C are resolved in the as-built diagram/findings.

SpecKit convergence: every accepted requirement and plan boundary has current evidence;
no implementation gap or additional convergence task. Existing T008 release work remains
separate: canonical migration, installed checks, publication and issue close are pending.
The synthetic benchmark is not evidence of broad production semantic accuracy.

Continuity recovery tool cannot derive a project key from this repository's legacy
numeric backlog. Git, task artifacts, issue identity and host agent status were reconciled
manually; existing run preserved, no unrelated backlog migration or agent redispatch.
