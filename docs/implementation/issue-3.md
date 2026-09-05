# Issue #3 — reproducible memory quality benchmark

User-authorized sequence: issue #4 implemented, reviewed (643 tests), committed as
6958c4b and integrated locally. Migration 009 was applied after a verified backup;
second init-db applied nothing and installed interpreter/status read-back passed.
Now implement issue #3 without changing production retrieval ranking.

## Contract and design

- Ship a versioned wholly synthetic EN/DE corpus with at least 50 labeled queries,
  explicit evidence IDs, expected answer alternatives, negative cases, categories,
  and fixed development/held-out partitions. Validate every label before DB writes.
- Separate real gateway document ingestion from real mining of synthetic sessions.
  Run the existing search path with FTS-only and hybrid baselines at equal context
  limits. No production database target argument is accepted.
- Create a random disposable local PostgreSQL database; record an ownership marker
  and verify it before cleanup. Refuse canonical/non-benchmark names. Use existing
  migrations and writer/reader privileges. All documents are synthetic.
- Report Recall@5/10, MRR, answer accuracy/abstention and stale answers when an answer
  stage ran; exact context characters and separately labeled estimated tokens;
  indexing failures, warnings, stage timings and p50/p95 retrieval latency. Do not
  invent provider billing/usage unavailable from the existing CLI seam.
- Optional model extraction/answer/judge calls use the existing configured provider
  through run_structured; no private transcript is loaded or new provider introduced.
  Model responses cannot alter ground truth. Preserve failed questions in denominators.
- JSON and Markdown reports include revision, corpus hash, model/prompt identities,
  environment and configuration (explicit non-secret allowlist), split and category
  metrics. Support saved raw per-query evidence for replay/inspection and strict
  same-corpus/split/budget report comparison. No tuning on held-out results.
- Small deterministic offline metrics/corpus subset runs in CI without PostgreSQL,
  Ollama, credentials or provider calls. Integration tests cover database lifecycle,
  real save/search, mining with only the model boundary doubled, report artifacts,
  and safe cleanup. Run a full local retrieval baseline. Paid model evaluations
  require separate explicit authorization (operator preference); do not equate the
  deterministic mining integration test with measured model quality.

## Plan

1. Red-green corpus validation, metrics and safe cleanup tests.
2. Implement isolated runner and CLI; seed versioned corpus and offline CI.
3. Verify real FTS/hybrid baseline and deterministic model boundary; report limitations.
4. Independent review, full suite, docs/backlog/feature updates and integration.

No new reranker/profile/temporal implementation belongs to this issue; their future
changes must be compared against this baseline at equal budgets.

## Verification and review

- First full local retrieval runs: 60 questions, all 26 sources indexed; FTS
  Recall@5 0.1875, hybrid Recall@5 1.0. Source identity is not answer accuracy.
- Independent review found corpus-ID file traversal and inherited libpq routing;
  generated source filenames and an explicit local connection target plus environment
  rejection address both. Marker-initialization cleanup and human-report denominators
  were also hardened. Focused regression suite: 18 passed.
- Real paid extraction/answer/judge quality is unmeasured. The optional pipeline is
  implemented; no paid evaluation matrix was started. No production retrieval tuning.

Final verification: `python -m pytest -q -p no:cacheprovider` — **665 passed**
(11.23 s). The offline subset also ran successfully with an intentionally invalid
PGHOST; the wheel was inspected for the 60-query corpus and migration 009. All
Important review findings were resolved and covered by focused regressions; no
additional paid review/evaluation loop was used.
