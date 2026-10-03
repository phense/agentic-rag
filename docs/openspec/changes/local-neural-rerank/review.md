# Review and verification: Local neural reranking

Base:342bccf6fce51213b7bac1560e41e7554b2e989c. Complete bounded diff on
feature/local-rerank, including code, tests, measurement/rehearsal tools and docs.

## Independent review

Reviewer: review_neural, independent read-only review under repository AGENTS.md.
Initial pass inspected all tracked and untracked files: no Critical/High/Medium
implementation findings. One Low origin-validation bug accepted empty trailing
query/fragment delimiters. Fixed by rejecting delimiters; two regression cases
verify no discovery or private passage transfer. No Low Issue needed for a fixed bug.
Final full-diff/evidence review: **Ready**, no unresolved Critical/High/Medium/Low.
The second Low finding, an unqualified default RAM-footprint claim in README,
was corrected to account for the optional native model process. Both Low findings
are fixed; no deferred bug Issue is required. The final CLI auto/off JSON contract
test was also independently reviewed. Independent checks:53 DB-free Python tests
and7 Node tests, all source hashes and raw metric arrays verified.

The reviewer's `uv run` created an ignored worktree-local Python3.14 environment
while attempting a read-only probe. The isolated environment was removed after
verifying its provenance; the existing production Python3.13 environment and
all tracked/DB state were unaffected. Remaining review uses the existing interpreter.

## Fresh verification

- `/Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q`:
 930 passed in35.87s. Includes65 neural tests and the legacy benchmark isolation test.
- `node --test tests/test_opencode_plugin.mjs`:7 passed.
- Meaningful observed reds: existing eligible ordering failed to promote original
 evidence; same-source chunks incorrectly triggered inference; offline benchmark
 implicitly invoked installed neural inference; arbitrary baseline module was
 accepted as a supported previous revision. All corresponding tests are green.
- Candidate origin query/fragment regression: previous implementation accepted
 empty delimiters; patched code rejects them before any request.
- All five measured candidate runtime file hashes verified; baseline hash checked
 against the actual342bccf git blob. Private queries/labels remain outside git.
- Three Trading cases:20 paired repetitions plus first call per route;180 original
 spans validated per route. Expected-source hits80/160→160/160, without an answer
 correctness claim. Median latency increases by approximately one second.
- Actual prior-revision concurrent reader, populated outage/retry and code rollback:
 all17 public tables' complete JSON row snapshots unchanged; pin, checkpoint,
 queued work and audit state retained; random owned synthetic DB cleanup verified.
- Two isolated model process starts and40 warm synthetic pair requests: positive
 above negative before/after restart; subprocesses stopped. No disk-cache flush.

See docs/benchmarks/2026-10-03-neural-rerank/ and docs/local-reranker.md for
raw arrays, model/runtime pins, resource observations, limits and reproduction.
No production rollout, data/config migration, service interruption or client
configuration modification was performed. Existing dependency alerts remain #37.
