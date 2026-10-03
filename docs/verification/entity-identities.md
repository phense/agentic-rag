# Feature8 / PB-5.8 verification and independent review evidence

## Scope and supported installation

- Work: RAG-5.8, feature8/10, [Issue33](https://github.com/phense/agentic-rag/issues/33), [AC-001–008](../specs/RAG-5.8-entity-identities/spec.md).
- Supported source: adopted `2a29c50a2fa435d2caeb3354da9dbce92e85e6bb`, package0.5.0, schema001–017. Source tree was clean; origin/main matched at preflight.
- Measured candidate: `c757fbfcfea5e9cc7655bb50a553c2dd3d4a2181`, isolated `feature/entity-identities` worktree. Application/main-driver/source-dependency bytes match the final PR. [Measured fingerprints and raw samples](../benchmarks/2026-10-04-entity-identities/results.json).
- Activation candidate: `ac2532f2189c82bdf132765b0c52fd6696bbd323`. Its only later code change corrects the rehearsal's original-grant filter; the measured API is unchanged. [Separate activation report](../benchmarks/2026-10-04-entity-identities/activation-results.json).
- Procedure: [PB-5.8](../playbooks/entity-identities.md), system deliverable, authorized operators/maintainer. Repository `.engineering-method` and local project-state script are absent; Git/Issue/spec artifacts provide continuity, no framework ledger claimed.

The live read-only preflight identified one PostgreSQL/pgvector store, login-enabled
non-superuser admin/reader/writer roles, seven domains,22 pins, existing queue,
checkpoints and audit history. No new config, provider/model, dependency, hook,
scheduler or job kind is needed. Existing exact-text assertion/mining/validity/search
implementations remain byte-identical. The additive index is persisted only through
explicit gateway backfill; unindexed old/new writes remain readable with stable IDs.
No union/embedding inference, new user ACL or provider-specific store is introduced.

## Fresh verification commands and results

From the candidate root:

```bash
/Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q
node --test tests/test_opencode_plugin.mjs
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_entity_identities.py --repeats 20 --trading \
  --private-recovery-dump /private/operator-selected/source017.dump \
  --private-recovery-report /private/operator-selected/source017-report.json \
  --output /private/operator-selected/entity-results.json
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_entity_activation.py /private/operator-selected/activation-results.json
```

Full Python suite: **1137 passed in151.54s**. Node integration: **7 passed in82.996375ms**.
The source baseline passed1076 Python tests in147.80s and7 Node tests. The61 new
entity cases passed separately in5.20s. They cover confirmed/revoked aliases,
history/current/as-of and expiry, no stale resurrection, conflicting values,
exact project/domain/global boundaries, unknowns, current source withdrawal and
bound-span confirmation, malformed/oversized inputs, bounded output/timeouts,
reader/writer column grants, transaction rollback, stale domain-index repair,
concurrent confirmations, unchanged batch/mining writers, admin purge, CLI/MCP
contracts and populated017 fallback/upgrade. Existing research/theme/tool/migration
expectations were extended only for018 and the additive tools.

Two accidentally overlapping earlier pytest processes shared the test database;
those results were discarded. The reported targeted and full runs executed
sequentially after both processes exited. Production was not their target. Affected
pre-final suites also passed167 tests; no completion claim relies on invalid runs.
No application/test changes followed the reported full suite. Later docs and
operational-driver fixes were checked by their actual isolated rehearsal.

## Independent complete code reviews

The independent core reviewer `/root/review_entity_core` inspected the complete
bounded application/schema/test diff, both drivers and consumed playbook snippets;
it did not implement, run tests, touch databases or read private contents. Final
core verdict: **Ready**, no unresolved Critical/High/Medium/Low. Inspected regression
findings were reproduced and corrected:

| Confirmed finding | Severity | Resolution and real regression |
| --- | --- | --- |
| Duplicate/domain source locks could deadlock | Medium | Source017 assertion writer restored unchanged; explicit indexing only. `test_cross_domain_legacy_duplicate_saves_do_not_deadlock`, `test_assertion_alias_shared_source_has_consistent_lock_order` |
| Caller-owned multi-assertion batch could deadlock on second key | Medium | No identity locks/effects added to old writer. `test_caller_owned_assertion_batch_and_concurrent_second_key_complete`; actual DeadlockDetected red before fix |
| Unindexed facts lost stable UUID | Medium | Deterministic read-derived ID equals persisted ID after backfill. `test_old_client_unindexed_facts_have_same_stable_id_after_backfill` |
| Alias cap left names unbounded | Medium |33 names maximum with full count and fail-closed incomplete context. `test_alias_limit_also_bounds_names_and_reports_total` |
| New relation FKs blocked authorized admin purge | Medium | Existing claim/evidence deletion cascades retained. `test_admin_document_purge_retains_legacy_delete_contract`; actual FK violation red before fix |

Reviewed core fingerprints include entities.py
`b155b08dee2e29c6eb29557d9e477fa6535929d86c60dddc0a16941ccec9876f`,
sql018 `906c1ddb3f5091b9e139122cf7ab360ffbd5eafee9600088c6d551c0fec5668b`,
and test_entities.py `558657e6b1b0dea1a2bf1bb4781861743f95f7915ef1dd1111e74783e51f2b75`.
The complete per-file hashes are in the raw measured report.

The independent design/integration reviewer `/root/review_entity_design` checked
requirements, architecture, current domain/trust predicates and the complete
measurement driver. Six driver issues were fixed before measurement: identical
as-of, exhaustive literal scope/assertion oracle, full measurement-byte freeze,
actual overlapping client processes, API timing outside verification, and actual
candidate-on017 legacy reads/writes/fallback. Final main-driver verdict **Ready**,
SHA256 `97211724b2f8a4c561fef6dcdf58ec90e62d556c5426ed53861879eae0b44613`.
Domain-aware raw retained facts and binding confirmation to the original source
key/span address design findings without changing legacy exact-key contracts.

Final artifact audit corrected a Low plan wording error: backfill takes both its
dedicated run lock and attachment scope/domain locks. Existing assertion/mining
transactions acquire no new locks. UML requirement coverage was corrected to
AC-001–008. No residual Low is deferred or hidden.

## Executed populated upgrade and recovery

- Candidate on017: existing CLI reads/writes pass, optional entity API returns unavailable without aborting caller work; actual candidate MCP checks both privilege levels and strict malformed booleans.
- Strict source017/target018 restore: consistent exported snapshot, single transaction, exit-on-error, every public table fingerprint and application-role grant equal in owned empty targets; cleanup verified.
- Additive018: original rows and grants retained; interrupted DDL rolls back; apply/retry becomes no-op. New tables enforce reader SELECT and bounded writer column updates; no deletion or arbitrary identity rewiring for writer.
- Backfill: interrupted two-row caller transaction leaves no attachments; four resumed batches map7 known facts while one unknown remains unlinked. No-change retry writes no audit. Actual failure tests roll back identity/attachment/audit together.
- Active clients: original/source/new/source CLI citations equal; fresh MCP9/15→10/18→9/15. Old-client writes after018 resolve without indexing; audited backfill persists the identical UUID. Three actual source assertion/new alias subprocess pairs overlap, share source evidence, complete and recover the fact.
- Private representative installation: SHA-verified source017 dump strictly restored,18 public-table fingerprints match. All10571 original documents/11961 chunks/607 assertions, seven domains,22 pins,26 checkpoints,1406 queue entries,1016 accepted batches and37689 historical audits survive. Seven audited batches map607 facts; remaining0, no inferred aliases and no-change audit count retained. Original grants preserved, owned copy deleted. Public output contains only counts.
- Exact operational order: literal PB snippets on an owned source017 Git/database/lock fixture apply018, bounded backfill, fast-forward to exact candidate, retry with018 already committed, then detach back to source while retaining018. Original rows/grants/citations and branch tip survive; lock release/reacquisition and resource cleanup pass.
- Guard rejection: unsupported source, abbreviated target, wrong/dirty candidate, wrong imported modules/SQL directory, canonical drift before/after lock, and busy upgrade/recovery lock stop without data/code changes. The tested target is an exact committed candidate, not a fabricated fixture commit.

The first activation run uncovered a **verification-driver** grant comparison
error: the final filter omitted original schema-migration/ownership grants on one
side only. It failed after successful isolated activation/retry/recovery. The
reviewer verified the correction to exclude only the three new tables; literal
rehearsal then passed. Final driver SHA256:
`7c60f2d4fe2abf4664721923c0010ee1fe1938ae10a51ed4fc8479c1c411a8ed`.
This later driver differs from the broad scripts inventory in the measurement
report; it is not used for any timed retrieval. All timed application/main-driver
bytes are unchanged. No unreviewed production migration was attempted.

## PB-5.8 content review and rehearsal status

PB was drafted, independently reviewed, then separately executed. Content reviewer
`/root/review_entity_design` returned **Ready** with no C/H/M/L after these fixes:

| Finding | Severity | Disposition |
| --- | --- | --- |
| PB-5.8-R01: unapproved candidate could migrate/backfill | High | Exact supported source/approved clean candidate, module/SQL/ancestry guards; recheck under worker lock and before activation |
| PB-5.8-R02: arbitrary recovery source or post-lock drift | Medium | Full supported-source/target/clean-HEAD guards before and inside lock; executed reject cases |
| PB-5.8-R03: CLI cannot reuse dated registered source metadata | Medium | Untimed CLI attestation separated from MCP reuse; original source_at copied to evidence.timestamp, no invented source ID bypass |
| PB-5.8-R04: report understated candidate dirty marker | Low | Temporary owned marker explicitly disclosed; fixed, no residual Low issue |

Reviewed and executed PB SHA256:
`8d70378c049be440c4eb212c811a7a2bb3b3ab48342bdcb01d0444d61360737e`.
The exact snippets passed at `ac2532f`; strict backups, MCP and private restore are
separate main-driver evidence, not inferred from content review. PB operational
readiness applies only to the tested source/isolated scope; production execution
still requires explicit authorization and fresh preflight/backup.

## Practical results, architecture and limits

The [three measured examples](../benchmarks/2026-10-04-entity-identities/README.md)
recover1/2→2/2,0/1→1/1 and0/2→2/2 correct original facts for20 warm observations
each. The old-name status case eliminates one stale current fact. Every candidate
observation has zero foreign/stale/unexpected assertion/citation errors. Context
budget4800, first/warm/API-format distinctions, raw times and quality denominators
are disclosed. No general speedup or production answer-quality gain is claimed.
Live Trading controls are read-only,20 repetitions over three ordinary queries,
eight valid original citations each,0 writes/0 providers; no production aliases.

[As-built sequence and integration checks](../uml/entity-identities.md) reconcile
stable IDs, scope/trust snapshot, reversible star relations, compatibility and
recovery with AC-001–008. Current qualified history preserves expired/superseded
facts but does not reconstruct former trust or arbitrary source edits. Shared
roles/domains are not a new user ACL. Existing domain-agnostic exact-key saves can
already omit a retained independent-domain assertion; this feature cannot recover
that lost evidence and preserves the original writer contract. Same-name entity
generations within one boundary require explicit operator qualification. Large
corpus entity-read latency and already-running client reconnect remain unmeasured.
Full restore can discard post-snapshot writes and is separately authorized.

## Production boundary and Feature7 reconciliation

Post-implementation live **read-only** verification: canonical checkout clean at
`2a29c50`, schema17 with all three entity tables absent; original three login-enabled
non-superuser roles retained. Codex config, Claude settings and RAG config hashes
match preflight. Whole `.claude.json` drift was independently compared against its
matching before-hash backup: only runtime experiment/usage cache keys changed;
MCP definitions and per-project MCP/tool settings match. No client settings were
edited. Normal concurrent production sessions increased queue/checkpoint/audit
counts; protected-state preservation is verified against consistent owned snapshot
copies, not by freezing the running store. No production gateway/index/alias write,
migration, configuration edit, reinstall or service interruption was invoked.

Feature7 stale pre-adoption statements in BACKLOG/FEATURES/its verification report
are reconciled with [Issue32's canonical adoption record](https://github.com/phense/agentic-rag/issues/32#issuecomment-5974266962)
and private rollout reports. Feature7 is adopted at source2a29c50/schema017 with
1076 Python/7 Node checks; Issue32 is closed. No features1–7 were reimplemented.

## Acceptance and next action

Implementation and populated compatibility/recovery are complete. Both independent
reviewers audited the complete bounded diff and final artifacts, recomputed the raw
metrics/checked hashes and links, and returned Ready with no C/H/M/L. The final Low
lock-model/requirement-label corrections were rechecked. Read-only convergence
against AC-001–008, the plan, as-built model and EI-S01–04/EI-R01–03 found no missing
implementation or evidence task; no convergence work was appended. [PR46](https://github.com/phense/agentic-rag/pull/46) is published and registered
with the T3 thread; Issue33 records implementation evidence. T010 is complete.
Issue33 remains open for applicable merge and separately authorized adoption.
Request approval of the specific Feature8 PR only after verified publication;
merge approval alone does not authorize deployment, migration or interruption.
