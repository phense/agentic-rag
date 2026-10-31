# RAG-005 architecture findings

## RAG-061 provider indexes (as-built reconciliation, 2026-10-30)

- AF061-001 (resolved; AC003/005, IC003): How can equal-size model changes avoid
  mixing raw/context/dedup vectors? `provider-indexes.md`, search.py:56,
  mining.py:_near_duplicate and SQL016's unconditional raw union show the gap.
  Category: interface consistency. Build sidecar generations from source and
  route all managed semantic reads through one descriptor; never import untagged
  historical vectors. Resolve in T003/T006; legacy mode documented separately.
- AF061-002 (resolved; AC004–006, IC004): How does coverage survive an edit during
  inference or activation? Sequence/state views in `provider-indexes.md` and
  contextual.refresh source recheck show the required order. Category: race.
  Hash source metadata/content, recheck under locks, validate completeness while
  excluding canonical writes for atomic pointer change; rollback catches up
  post-cutover writes. Resolve in T005/T007.
- AF061-003 (resolved; AC004/008): Who may inspect/write global generations?
  SQL021 service RLS and scoped definer gateways are authority boundaries.
  Category: security. Local-owner lifecycle only, invoker scoped retrieval,
  audited scope/source-checked derivative writes. Resolve in T005/T007.
- AF061-004 (resolved; AC002/003/007): What does provider identity actually prove?
  Query cache model_digest checks an Ollama SHA but historical raw vectors have
  no identity. Category: trust boundary. Explicit profile revision guarantees,
  bounded opt-in probes, no plaintext credentials or response diagnostics, no
  fallback. Resolve in T002/T003; do not claim remote weight attestation.

As-built RAG-061: AF061-001–004 resolved by the implementation and independent
complete bounded review (base8e521a7, runtime5c4abce, measurement supplemente6cf92b).
Source contracts, authority, locking, index representation and recovery topology
reconciled against providers.py/indexes.py/SQL027/search.py/mining.py/store.py
and actual green bounded test exits on2026-10-30. See provider-indexes.md.

- AF061-005 (resolved; AC007/US003): Do classified HTTP extraction failures remain
  visible through source receipt and tracing? Independent architect found
  ingest.receipt_status's static allowlist dropping rate_limit/transient and
  service.worker replacing permanent failures with processing_failed.
  Category: integration mismatch; Medium. Fixed with bounded provider_status codes
  at worker and receipt projection. Real HTTP submit→process_source→receipt/trace
  regression observed RED3, then24 related tests passed (31.35s, exit0).
- AF061-006 (resolved contract clarification; AC005/SC002): The no-mixing guarantee
  applies to managed reads in the new binary. Historical untagged legacy reads
  and old binaries remain explicitly unverified; a managed rebuild is required
  for verified identity. No historical identity is inferred from a current tag.
- AF061-007 (resolved; AC003): Empty stores made coverage
  vacuously complete without proving embedding capability/dimensions. RED2
  actual-adapter tests reproduced acceptance of wrong-dimension/unsupported
  providers. Selection now runs one fixed synthetic input before canonical locks;
  94 provider/index/search/CLI tests passed (61.92s, exit0).

Independent review also read the actual derived success and persisted CLI
recovery tests and verified the synthetic measurement counters/manifests.
LOW-018 documentation inconsistencies are corrected and retained in Issue75.
- AF061-008 (resolved; AC002): Current introductions still
  claimed universal local embeddings/CLI-only calls, and default research was
  called local although selected managed embeddings can be external. Focused
  independent review classifies these as Medium disclosure contradictions.
  Current prose now distinguishes structured assessment from selected embedding
  retrieval, discloses semantic duplicate candidate inputs and documents lexical
  research without model calls. The corresponding docs regression was RED before
  correction; actual search/research characterization passed7 tests (3.31s).
  Independent focused recheck through078ad29 confirms the corrected contract,
  actual17-test documentation module and unchanged153 runtime/SQL/script hashes.
  LOW-019 retains the obsolete selector correction in Issue75.

The first full suite exited1 solely on the obsolete privacy paragraph selector:
1696 passed,1 failed,1 expected skip,1 warning,1415.15s. Its runtime/test hashes
stayed unchanged. The selector and new disclosure guards are repaired. Fresh
complete verification on078ad29 passes1700 tests with1 expected skip and1 upstream
warning in1245.42s, exit0;304 runtime/test/SQL/dependency hashes stay unchanged.
Independent full review plus the focused disclosure recheck leave no open C/H/M
findings. Final convergence reconciles AC001–009, as-built locking/authority,
actual success/recovery and operator rehearsal, measured-source identity and
the unchanged-source complete-suite exit. No additional task is required;
PR publication and maintainer merge remain separate workflow actions.

- AF-001 (implemented; AC-001/003): Post-filtering loses eligible candidates and recursive
  traversal can bridge through B. Evidence: 003_search.sql LIMIT50, 004_graph.sql
  recursive walk; project-scope.md. Require scope in each candidate and hop (T003).
- AF-002 (implemented; AC-003/005): Unknown provenance cannot imply global or shared
  dedup identity. Evidence: curation.py domain/body join. Require explicit unknown
  state, equal-known curation and audited repair (T002/T004).
- AF-003 (implemented; AC-002): Repository-level collapse would broaden subdirectory pins.
  Evidence: pins.py prefix policy. Keep mapped directory anchor separately from
  project root; no LIKE wildcards (T002/T004).

2026-09-05: design evaluated against current code. Next: implement referenced tasks,
reconcile as-built, then independent architecture-derived success/recovery checks.

As-built reconciliation: scope.py owns root vs pin-anchor normalization, including
separate nested Git repos. Migration010 carries before-limit candidate and every-hop
filters. search/graph/CLI/MCP/hooks all pass selection; curation uses equal known
project_scope. store.set_project_scope and scope.backfill are atomic/audited and
preserve original provenance/content freshness. tests/test_scope.py covers bridge,
limit, hook, curation, path and retry flows. No diagram topology drift.

Independent architecture/code review (read-only reviewer): every candidate branch
and graph hop matches the model. Derived success flow maps to
`test_prompt_recall_and_startup_share_project_policy`; recovery maps to
`test_audited_legacy_mapping_and_rollback` plus pin-phase rollback. Added explicit
CLI/MCP roundtrip coverage. Four Important findings were dispositioned:

- Update replay of old provenance must not undo explicit repair: restrict automatic
  provenance inference to creates; regression reproduced before fix.
- Curation scope can change during model work: acquire ordered endpoint row locks
  and revalidate expected known scope immediately before writes; count/audit applied
  results only. Separate-connection scope-change regression covers the race.
- Git timeout is unknown, not proven non-Git: no ancestor document selection on
  failed detection; environment cannot redirect Git identity.
- Scope ground truth is not representable by current mining corpus overrides:
  reject scoped E2E benchmark mode before DB/provider work; existing unscoped E2E
  remains supported. Scope fixtures run through real retrieval mode.

As-built addendum: explicit scope decisions (including unknown) are protected from
legacy backfill by scope_explicit. Applicability-only changes retain updated_at.
All fixes stay within the defined data/applicability boundary; no extra reviewer or
paid model matrix was used.

## RAG-006 fact validity (design-time, 2026-09-05)

- **AF-006 — Resolved; authority boundary (AC-002/005).** Mining windows currently
  flatten role/time/identity. `fact-validity.md` requires evidence matched against
  the consumed source fragment before acceptance. Task T002 must preserve this
  metadata and reject invented evidence; full #7 is not assumed implemented.
- **AF-007 — Resolved; concurrency/order (AC-001/006).** Read-then-write replacement
  races and arrival-time ordering can reverse truth. Task T001 must serialize a
  canonical assertion key, use event time, and keep all effects in the batch txn.
- **AF-008 — Resolved; shared eligibility (AC-004).** Search-only post-filtering leaves
  hooks/graph bypasses and exhausted candidate budgets. Task T003 must enforce one
  SQL predicate before limits and at every selected graph hop.
- **AF-009 — Resolved; lifecycle ownership (AC-003/007).** Whole-document curation
  could archive an assertion independently of valid time. Task T004 must exclude
  atomic assertions, reject in-place edits and establish explicit reactivation epochs.

Verification 2026-09-06: mapped changes implemented, as-built view reconciled,
independent review clean after source-authority/completeness, evidence retention
and reactivation fixes. Derived success/recovery tests pass in the full 703-test
suite. Next action: backup-gated rollout.

## RAG-007 evidence lifecycle (design-time, 2026-09-06)

- **AF-010 — Resolved; source authority (AC001/002/003).** Existing event IDs lack
  explicit session namespace at the attachment boundary. Task T001 namespaces
  identity and derives role/time from source; T002 grounds before batch acceptance.
- **AF-011 — Resolved; concurrency (AC003/004/007).** Attach and source withdrawal
  must not overwrite each other. Task T001 uses deterministic source locks and
  immutable append semantics; T004 proves replay and concurrent trust changes.
- **AF-012 — Resolved; eligibility (AC004/005).** Source trust must compose with
  temporal validity at every pre-limit/hop predicate, without reviving superseded
  values. Task T003 replaces the common predicate and proves composition.
- **AF-013 — Resolved; content ownership (AC006/007).** Ordinary updates/curation can
  invalidate attached evidence. Task T002 protects managed claims from in-place
  mutation and curation; legacy documents remain labeled incomplete.

RAG-007 reconciliation: AF010–013 implemented and covered by source lifecycle and
mining integration tests. Independent review findings on signal authority, confirmation
inheritance, malformed timestamps, completeness and prompt labels corrected with
regressions. Final independent fix review is clean; full verification passed (718 tests).

## RAG-009 design findings (2026-09-06)

- AF-009A(resolved;AC-004/005/006): visible revision + per-read eligibility and real-turn
  identity prevent stale corrections/replays. See rag009-context.md; tasksT001/T003.
- AF-009B(resolved;AC-003/004): budget/dedup ordering and whole multiline pins must remain
  faithful. See rag009-context.md; taskT005.
- AF-009C(resolved;AC-006/007): writer-only atomic refresh, dated fallback and source-backed
  stable classification. See rag009-context.md; tasksT001/T006.

RAG-009: independent final review Ready; real queue/worker/reader success and failed
refresh recovery pass. Full isolated suite:757 passed29.14s. See rag009-context.md.


## RAG-5.4 architecture findings

RAG-5.4 design/as-built reconciliation,2026-10-03. Evidence: [consistency sequence](contextual-indexing.md), [plan](../specs/RAG-5.4-contextual-indexing/plan.md), tests/test_contextual_indexing.py and the populated [rehearsal](../benchmarks/2026-10-03-contextual-indexing/results.json).

| ID | Question/risk | Requirement | Required task | State |
| --- | --- | --- | --- | --- |
| AF-5.4-001 | source edit/model switch during inference | AC-004 | fingerprint/lock, query and index digest races, scope/time/source eligibility tests | resolved; regression tests and old-writer recovery |
| AF-5.4-002 | index-only rebuild loses baseline/citations | AC-002/003 | side table + all15 canonical table fingerprints, historical audit subset, original spans | resolved; migration/index/recovery snapshots |
| AF-5.4-003 | old worker cannot process new jobs | AC-004/006 | unchanged queue vocabulary/scheduler; actual old save/read after015; queued reembed lexical context | resolved; coexistence and retry tests |

## RAG-5.5 design findings (2026-10-03)

Evidence: [transaction sequence](filter-aware-search.md), [plan](../specs/RAG-5.5-filter-aware-search/plan.md),013/015 candidate functions and psycopg transaction ownership.

| ID | Question/risk | Requirement | Required response | State |
| --- | --- | --- | --- | --- |
| AF-5.5-01 | budget/scan settings leak into caller or neighboring client | AC-001/003/005 | savepoint-local settings outside candidate statement; successful explicit restoration and real timeout/cancel recovery tests | resolved; actual success/timeout/cancel/discovery ownership tests and full987 suite pass |
| AF-5.5-02 | long-document chunks crowd out other eligible sources | AC-002/004 | exact eligibility materialization and per-document diversity before final limit; bounded ANN pool and separate oracle recall measurements | resolved; complete small-set oracle/ties4096/4097 and measured pool/source diversity; Trading exact-oracle/citation parity |

## RAG-5.8 entity identities (2026-10-04)

Named question: How can an operator reverse identity links without rewriting facts
or permitting scope/trust bridges? [Model](entity-identities.md),
[plan](../specs/RAG-5.8-entity-identities/plan.md), AC-001–008.

- AF-5.8-001: Preserve exact assertion keys and original validity functions; cross-name
  validity belongs only to the new explicit read. Required T002/T004; design addressed.
- AF-5.8-002: Relations bind one known scope/domain, complete active user evidence and
  explicit confirmation. A star has one anchor and no transitive chains. Required
  T003/T004; design addressed.
- AF-5.8-003: Old writes lack mapping; resolve exact rows directly and report missing
  indexing, backfill through gateway. Required T002/T006; design addressed.
- AF-5.8-004: Support and relation state must share the read snapshot; competing
  confirmations require ordered scope locks. Required T003/T004/T006; design addressed.
- AF-5.8-005: Code rollback retains018, source rows and old-client behavior. Backfill
  is bounded/replay-safe; strict backup restore precedes migration. Required T006;
  executed populated017→018/strict restore/code recovery evidence passes.


As-built RAG-5.8 reconciliation: [EI-S01–04 and EI-R01–03](entity-identities.md)
pass against current schema/CLI/MCP/source transaction contracts. Stable unindexed
IDs, complete original-span support, exact project/domain selection, bounded output
and retained018 rollback are evidenced. Initial automatic indexing design was
revised to explicit audited backfill after real source/batch deadlock regressions;
existing assertion/mining code is byte-identical to source. No open architecture
finding; production rollout remains separately authorized.

## RAG-5.9 incremental ingestion

The independent source gate identified model/input drift, optional SQL transaction
poisoning, chunk/dedup representation confusion, premature mining commits, queue
priority and evidence truncation risks. The [as-built model](incremental-ingestion.md)
keeps one audited writer and parallelizes pure bounded inference only. Shared
nonblocking cache mutation, explicit savepoints and exact prepared inputs address
these integration risks. Operational reviews added backup actual-server identity,
pre-switch drift checks, child ownership/configuration and measurable content/vector
oracles. Final source and recovery verification remains in the feature record.


## Issue58 service architecture findings

### AF-058-001 — Scope must survive transaction commits (design response required)

FR-004; `central-service.md`, `db.py`, gateways that commit internally. Per-transaction settings would reset halfway through an existing tool. Apply service authorization settings for the lifetime of each fresh non-pooled role-limited connection and close it after the call. Test a read following a gateway commit and definer writes to guessed IDs. Owner: coordinator; status: implemented and independently verified in S1, task T058-02.

### AF-058-002 — Machine-local locks are insufficient (design response required)

FR-008; `central-service.md`, `worker.py:acquire_lock/requeue_orphans`. Hold a database session advisory lock across all worker commits and orphan recovery. Keep old binaries fenced during cutover. Test concurrent worker contenders and crash/retry. Owner: coordinator; status: implemented with keeper checks plus per-connection execution pins; keeper/main loss and accepted-batch replay regressions pass, confirmed in independent S2 review3, task T058-06.

### AF-058-003 — Accepted input and applied knowledge are different states

FR-006/007; durable-ACK sequence and `mining.py:mine_session`. Commit source+queue before ACK; persist accepted normalized batches before applying. Never remove a local submission after a timeout without an exact receipt replay. Owner: coordinator; status: implemented, replay/ownership/crash tests pass; confirmed in independent S2 review3, task T058-05.

### AF-058-004 — Migration cannot infer remote-readable transcript paths

FR-009/010; legacy `jobs.py` local-path payloads. Inventory blocking source dependencies, credentials, versions and independent stores before an opt-in remote move. Refuse unresolved path/mapping/collision state; do not fabricate evidence or claim a lossless move based on an old dump alone. Owner: coordinator; status: implemented with strict inventory/restore and source fence; final independent review pending, task T058-08.

### AF-058-005 — Team reading must not collapse uploader authority

FR-003A/AC-002B, maintainer clarification during final review. IT colleagues need
shared knowledge/logs, while agent cursors and job authority remain distinct.
Record immutable publication teams separately from principal/session IDs; use
current team/project grants for SELECT only. Preserve original-row write guards
and explicit receipt-owner checks. Do not infer permissions from Herdr labels
or disappear team history when its author leaves. Owner: coordinator; implemented
with real SQL/HTTP regressions, complete-feature re-review pending, T058-07C.

## AF-059-01 — Policy/audit cross-resource recovery (resolved, RAG-059)

Question and source: dashboard sequence, IC-059-02, service/auth.py's file authority. Category: failure ordering. Required response T059-02: serialized prepared journal, old/new digest reconciliation, atomic file replace and lost-secret response behavior. Validate crash/drift probes before delivery.

## AF-059-02 — Browser authority isolation (resolved, RAG-059)

Question and source: dashboard sequence, IC-059-01, existing Bearer Gateway. Category: trust boundary. T059-01 must keep cookies isolated, enforce same-origin/session CSRF, bounded bodies/concurrency/rate and safe cache/CSP headers. Test expired/revoked session and hostile origins.

## AF-059-03 — Administration versus knowledge scope (resolved, RAG-059)

Question and source: dashboard sequence, IC-059-03, scope RLS and service/read_limits.py. Category: ownership/resource boundaries. T059-03 must project scoped bounded knowledge and never treat admin as knowledge superuser; heartbeat fields are informational. Test same-project foreign department and large legacy fields.


As-built disposition for AF-059-01..03, 2026-10-30: the current
[sequence](dashboard.md) matches filesystem `flock`, durable prepared audit,
exact-session row locking through replacement/commit and final clock-expiry
validation. Crash exit73 and known/unknown-digest recovery pass; replay never
reveals an old secret. Cookie/Origin/CSRF and Bearer isolation, body/rate/concurrency
budgets and expiry/revocation regressions pass. Scoped browse/count/source/review
uses existing RLS/engine/queue; the bootstrap admin sees0 documents while its
authorized reader sees2 and the original quote. All three whole-feature reviews
completed; round3 reports0 C/H/M/feature Low and158 passing checks. T059-01..05
supply the implementation and integration evidence. No unresolved architecture
difference remains; final full-suite and delivery evidence is tracked separately
in the [verification record](../verification/issue59-dashboard.md).

## RAG-060 design-time gate — 2026-10-30

Question: how can cross-request/job diagnostics remain bounded without leaking broader source authority or changing durable outcomes? Sequence: `issue60-tracing.mmd` (Mermaid sequence notation; source semantics inspected, no renderer claimed). Sources: `service/api.py` Gateway, `dashboard.py`, `ingest.py:accept`, `requests.py:submit`, specification IC-001..003.

- AF-060-01 (resolved, trust boundary): owner-only metadata has no automatic RLS; T002/T004 apply current read-envelope and identity predicates before every count/page/detail/export. Restricted administrators cannot see global anonymous failures. Real two-department, policy-realm, empty-scope and revocation probes pass.
- AF-060-02 (resolved, recovery): trace retention must not erase accepted-job provenance. T002/T003 persist nullable origin IDs transactionally on each queue source, preserve on replay/retry, and avoid trace foreign keys. Prune/replay regressions and independent HTTP→source→worker success/recovery probes pass with exactly one acceptance.
- AF-060-03 (resolved, resource/failure): logging after canonical commit must not rewrite HTTP outcomes or create unbounded tasks. T003/T005 bound metadata/concurrency/storage/SQL time and expose fixed degraded diagnostics. Real storage reserve, lock/outage, scheduler error and cancellation probes preserve audited outcomes and admission ownership.

As-built reconciliation2026-10-30: the sequence matches Gateway/Dashboard context,
transactional queue origins, bounded best-effort recorder and live authorized job
projection. Independent complete-diff review and architecture-derived success/
recovery probes pass after cursor-type and CLI-import corrections. No architecture
difference remains. Final whole-project convergence and actual exit are recorded
in [Issue60 verification](../verification/issue60-tracing.md); deployment is separate.

## RAG-062 settings (as-built, 2026-10-30)

- AF062-S1 (tasked T002/T003, AC002–004): File ownership/session races must
  reuse the prepared policy journal and exact live-session fence; no second store.
- AF062-S2 (tasked T001/T002, AC005/006): Alias alone is insufficient for new
  presets. Require advertised artifact SHA before sources; startup hashes all files.
- AF062-S3 (tasked T004, AC007): Migration028 widens only the audit-kind constraint; default
  ordering changes. Prove explicit-config preservation and actual old-binary rollback.

As-built: all three findings map to the existing authority/journal and pinned
runtime boundaries in [reranker-settings.md](reranker-settings.md). Reserved
alias/SHA mismatch fails during Config construction. Shielded submitted workers
release the native slot after drain even when the caller cancels before start.
IT062-SUCCESS/RECOVERY connect selection, scoped search, restart and actual old
code rollback; final review and complete-suite gates are recorded in
[Settings verification](../verification/issue62-settings.md).


## RAG-063 design-time gate — 2026-10-31

Source model: [source-evidence-63.md](source-evidence-63.md). Spec/plan: `docs/specs/6-5-source-evidence/`. Existing semantics were independently inventoried; 38 baseline tests passed at5390a6f. No implementation evidence claimed yet.

- **AF-063-001 (open, concurrency/data integrity)**: current evidence gateways lack CAS and use no portable revision. AC-003/004, evidence.py:attach/source_state/review. T063-001..003 must persist revisions, bind review to the complete inspected set, avoid ABA and match claim→source locking without a source→claim cycle. Verify concurrent attach/withdraw/review and audit failure.
- **AF-063-002 (open, trust boundary/resources)**: raw source metadata and no scoped history transport. AC-005/006, service scope021/read_limits, dashboard source renderer. T063-002/004..006 must anchor reads to visible documents, enforce existing all-dependent write scope, hide technical host locators, bound quote/history pages and use non-oracular errors. No security-definer history shortcut or audit-table grant.
- **AF-063-003 (open, lifecycle/invalidation)**: source trust, claim review and fact-time disposition are different gates; derived paths must remain live-qualified. AC-001/002/007, SQL020/023, profiles.py/thematic.py/generated patterns. T063-002/007 must derive explanations from canonical semantics and test withdrawal, correction, expiry, supersession, scope revocation and no resurrection.
- **AF-063-004 (open, migration/recovery)**: existing populated schema028 data must retain its original fields and unknown provenance. AC-008/009, service/upgrade.py and schema framework. T063-001/008/009 must prove additive029 migration, source0.6.15 support, restored originals/ACLs, portable tokens, retry and old-client reads; PB-063-UPGRADE reviewed/rehearsed before delivery.

Next: tasks before application changes; reconcile this exact sequence and all four findings as-built, then independent strong architect derives success/recovery integration tests. No design waiver.


RAG-063 as-built reconciliation, 2026-10-31: AF-063-001..004 have implemented
responses in migration029, evidence_contract.py/evidence.py, all four client
surfaces, scoped history and populated upgrade tests. The source locking gap was
reproduced against old-style SQL and corrected with a no-data anchored SHARE-lock
helper; the document lifecycle race and oversized legacy reasons have regression
tests. Details and rationale are in [source-evidence-63.md](source-evidence-63.md).
These findings are resolved at the implementation/model boundary. Independent
architecture-derived success26/26 and recovery10/10 checks passed. The complete
review and correction re-review through `2c92d4d` resolved Medium RV063-M1 and
Important PB063-R1, with zero open Critical/High/Medium/Important findings. The
accepted playbook has a populated public-command restoration rehearsal. Final
whole-suite evidence at that source revision is1,819passed/1skipped/1warning,
exit0; see [verification](../verification/issue63-source-evidence.md). Low findings
and their explicit deferrals remain in Issue75; production rollout is separate.


## RAG-064 design-time gate — 2026-10-31

Question/model: [temporal-query-64.md](temporal-query-64.md), source8772fbd; requirements and plan under docs/specs/6-6-temporal-query/. Source semantics reviewed, no rendered validation claimed.

- **AF-064-001 (open, interface/time semantics):** AC-001/002/006, validity.py:selection and search.py:search. Calendar parsing must capture reference once, use explicit zone/DST calendar boundaries, avoid date guessing and never replace as_of/history. Owner S1/T064-001/002; prove parser boundaries, no-intent/off parity and future eligibility. Next: implementation.
- **AF-064-002 (open, trust/data semantics):** AC-003/005, evidence.py and SQL020/023. Late import/update time and nonqualifying source time must not masquerade as event truth; RLS and current claim/validity gates remain authoritative. Owner S1/T064-002/003; batch finite metadata for visible candidates, explicit unknown/manual basis, no-resurrection and two-domain tests. Next: implementation.
- **AF-064-003 (open, bounds/recovery/compatibility):** AC-004/006/007/008, search.py:diverse/_expand and MCP/CLI envelopes. Graph promotion cannot undo filtering/preference; candidate caps must be explicit, hard failures never return unfiltered output, off/no-intent preserve legacy transport and no SQL failure leaves a swallowed aborted transaction. Owner S1/T064-002..005; bounded graph/filter tests, real transport parity, populated old-code rollback and held-out measurements. Next: implementation then S2 independent success/recovery gate.


RAG-064 as-built reconciliation, 2026-10-31: AF-064-001..003 have implemented
responses in temporal.py/search.py/config.py and local/remote transports. The
model records actual library/client opt-in defaults, canonical qualifying event
time, savepoint recovery, bounded candidate recall, no-migration0.6.16 operator
support and old-code rollback. Coordinator regressions reproduced and corrected
k=3 graph eviction and fresh source-withdrawal retention. See
[temporal-query-64.md](temporal-query-64.md). Findings are resolved at the
implementation/model boundary; independent architecture success/recovery,
complete bounded review and fresh full suite remain pending.


RAG-064 independent integration gate,2026-10-31: complete bounded review
8772fbd→517263c covers32/32files and reports0Critical/High/Medium. Architecture
probes derive29success and12failure/recovery checks through authenticated
REST/serverMCP→engine/RLS→canonical PostgreSQL, all41pass exit0 with36data-table
hashes unchanged. The original failed probe is retained as a probe-design failure,
not hidden or counted as acceptance. Low findings RV064-L1..5 are deferred to
Issue75/LOW-031..035 under the maintainer's policy; L6 documentation/evidence
corrections are completed during delivery. Runtime/tests remain byte-identical
to reviewed6291685; the full suite subsequently passed1,896tests/1skip/1known warning,exit0,
and the wheel has181entries with176matching source/SQL/assets files. Final
convergence checks and PR handoff remain separate gates. Public evidence: docs/verification/issue64/.


## RAG-065 design-time findings and as-built reconciliation (2026-10-31)

- **AF-065-001 — Open, evidence identity and anti-recursion.** Question: what counts as independent original support, and can later-confirmed generated content bypass it? AC-002/003/004/006; sequence `pattern-synthesis-65.md`; evidence `evidence_contract.py`, `evidence.py`, `thematic.py`, `sql/012_claim_evidence.sql`. Impact: assistant/manual/duplicate/derived evidence can manufacture certainty or stale disclosure. Required response: T065-001/003/004 original-event/content deduplication, ev1/src1 identity, exact part citations and complete current dependency/read guard; independently verify later confirmation and graph/direct reads.
- **AF-065-002 — Open, acceptance/application ordering.** Question: how does a crash after a paid inference avoid repeated output or half-application? AC-005/007; same sequence; evidence `worker.py`, `jobs.py`, `store.save_claim(commit=False)`, `service/fence.py`. Impact: duplicate provider calls/documents and partial audits. Required response: T065-002/003 persistent accepted results and unique application identity under existing worker authority, atomic gateway/dependency/audit; test post-accept failure and retry.
- **AF-065-003 — Open, deferred authority and scope.** Question: who may enable, backfill, read and commit after credentials/policy change? AC-001/006/008/009; same sequence; evidence `service/context.py`, `service/worker.py`, `service/schema.py`, migration021/029. Impact: cross-scope joins, stale accepted work and implicit historical processing. Required response: T065-002/004/005 concrete scoped policy, forward boundary, RLS/commit revalidation and schema/startup/old-client upgrade evidence.

All three are analyzed, task-mapped design obligations, not unresolved product ambiguities. Coordinator will reconcile as-built before independent success/recovery integration gate T065-009. Mermaid source semantically inspected; no render claimed.

As-built disposition at `a44c0a1` (runtime `8f0911a`), superseding the design-time
Open statuses above: **implementation reconciled; independent acceptance pending**.
AF-065-001 maps to the exact-span/version gate, dependency trigger and SQL/Python
read guards, with a disclosed semantic limit (a model can lie about a citation's
meaning). AF-065-002 maps to accepted-before-apply persistence, unique semantic
application identity, scoped queue recovery corrected in `85af27d`, and atomic
inference/dependency/audit/processed-member writes. AF-065-003 maps to scoped
RLS/commit checks and the corrected all-reader upgrade gate: old direct readers
are unsupported after a pattern exists; disabling on new code is not an old-code
rollback. Exact source/test pointers are in `pattern-synthesis-65.md` and the
R65-01..06 correction evidence in `docs/verification/issue65-pattern-synthesis.md`.

- **AF-065-004 — Implementation reconciled; integration acceptance pending,
  lossless bounded selection.** AC-001/007, US-002, R65-02/03/06; question: can a
  finite scan and prompt budget silently lose late commits or cross-run support?
  Evidence: `synthesis._pending/_plan/_context/_finish`, migration030
  `synthesis_processed`, and `tests/test_synthesis_forward.py`. The rotating scan
  position is only an examination cursor; epoch membership records actual
  consumption. Pending originals must fit before a run is created; oversized
  support stays visible, and recent processed originals can supply bounded
  context without causing context-only paid work. T065-012 implements the
  correction; T065-009 must independently probe late commits, budget continuation,
  cross-run recurrence and failure/accepted-recovery atomicity.

The corrected architecture requires fresh success and recovery probes, independent
SQL/authorization/playbook review and the final full suite. The earlier review's
probe exit0 means execution completed and includes a failed product recovery gate;
it is not acceptance evidence for the corrected source. No gate is waived here.


RAG-065 independent final acceptance at `73ddd02`: AF-065-001..004 are resolved
at the implementation/model/integration boundary. The final 60-file manifest
matched exactly; 34 fresh assertions passed, with four owned databases removed.
N1 backfill waiting/no-consumption/recovery and PB065-R07's hardlink gate are
resolved. Earlier source/policy/credential, atomic apply and accepted recovery
probes are reused only for byte-identical code, as documented in the review.
No Critical/High/Medium or Important finding remains. LOW-038..044 are deferred
in Issue75; the companion Minor C1/C9 wording finding is corrected by the
coordinator without changing executable steps. Full-suite and convergence
acceptance are still pending.

Final Issue65 coordinator evidence: `ea6697b` full pytest 1974 passed/1 skip/1 known warning,
exit 0, 355 source hashes unchanged; restore correction 119 targeted + 28/28 probe
assertions. AF-065-001..004 remain resolved; LOW038..044 remain in75.
No additional architecture change or live rollout occurred.


## RAG-066 design-time findings (2026-10-31)

Gate: `memory-lifecycle-66.md` (design decisions D1..D8, three Mermaid views, semantic
source review, no render claimed) and contract
`../specs/6-8-memory-lifecycle/contracts/lifecycle-v1.md`. Base `d4d2372`, branch head
`af7c9d8`. No product code or test was changed or run for this gate. Every entry stays
Open until as-built reconciliation. ACF-066-S/R are the derived post-implementation
acceptance flows.

- **AF-066-001 — Open, operation semantics and automatic policy (requires coordinator
  acknowledgement of two scope clarifications).** Question: which of the five operations
  may hide, which is proof versus judgement, and may anything apply automatically?
  US-001, AC-001/002/010, IC-001, FR-001/003. Evidence: `curation._merge_exact_duplicates`
  excludes fact and claim documents and archives the newer copy; `validity.save` already
  owns assertion replacement/extension and exact assertion dedup; `entity_aliases`
  references `claim_records`. Impact: a second supersession engine over assertions or
  aliases would contradict FR-001, and 0.6.18 `entities.py:312` would then show merged
  facts. Decisions D4/D5: anchors exclude synthesis, assertion and alias documents; no new
  automatic applier; legacy curation stays byte-identical. Contradiction is recorded and
  never hides. Replacement requires a proven strictly increasing event basis.
  Clarifications for the coordinator: (a) assertion/alias anchors return
  `assertion_managed`, which directs callers to `memory_assert`; (b) `include_merged` does
  not return legacy archived `duplicate_of` copies, which stay reachable through original
  get/detail as `legacy_duplicate`. Required response: preview/classifier task with frozen
  fixtures for all five classes, cross-entity, cross-scope, unknown-scope and
  equal/unknown/future event order; zero writes and zero provider calls asserted;
  documentation of both clarifications. Next: coordinator accepts or rejects (a)/(b)
  before speckit-tasks.
- **AF-066-002 — Open, versions, ABA and ev1 preservation.** Question: how do applies bind
  content, evidence, scope and decision state without invalidating untouched ev1 values
  and 6.7 patterns? AC-003/006/009, IC-002. Evidence: `rag_document_version` omits body
  and `updated_at`; legacy bodies are mutable through `store._save_txn`; the
  `updated_at` trigger comes from migration001; ev1 feeds `rag_pattern_current`. Impact:
  extending ev1 would invalidate every existing pattern and evidence reference, while
  using ev1 alone misses legacy body edits and apply/correct ABA. Decision: separate `lv1`
  (ev1 + content hash + status/scope + `updated_at` + append-only anchor event count), and
  overlay rows never touch `documents`. Required response: tests that ev1/src1 of every
  document stay byte-identical across migration031, apply and correct; lv1 detects body
  edits, scope/domain moves, status changes, source revision and apply→correct ABA.
  Next: tasks.
- **AF-066-003 — Open, cycles, locking, replay and correction.** Question: can concurrent
  writers, replays with new transport IDs, or corrections create duplicate active
  decisions, chains or cycles, possibly hidden by RLS? AC-005/006/008, US-003, IC-002.
  Evidence: `curation._lock_scope_pair` (ordered row locks); the
  `rag_synthesis_dependency_guard` definer pattern; `validity.save` advisory and
  savepoint retry; `ServiceConnection.check_commit_authority`. Impact: two-sided
  opposing merges, a lost correction, or a partial audit. Decision D3: flat invariant
  (chain length 1), so cycles are structurally impossible. A definer guard and a partial
  unique active-member index enforce it. Locks: anchors `ORDER BY id`, then the decision;
  `lock_timeout` 2000 ms. Semantic `action_key` and `request_key` handle replay. The only
  transition is `active|contested → corrected`. Required response: PostgreSQL tests for
  A→B‖B→A, A→B‖B→C, replay with a new request ID, replay mismatch, lock timeout, injected
  audit failure and revocation before commit (all-or-nothing), and correcting an earlier
  decision after a later one. Next: tasks.
- **AF-066-004 — Open, selection before LIMIT across all readers.** Question: how do raw,
  contextual, managed, identity, graph and research candidates apply
  current/include-merged/historical selection before their limits, without changing
  omitted defaults? AC-004/005/008, US-002, IC-003. Evidence: every family filters through
  `assertion_eligible` (sql/013/015/016, `indexes.py:218/273`, `search.py:383/413`,
  `research.py:295/350`); graph keeps an omitted-history default (`graph.py:45`); and
  `SET LOCAL` survives a released savepoint (`indexes._bounded` restores explicitly).
  Impact: post-filtering starves results, and a leaked view setting would widen later
  statements. Decisions D2/D6: same-signature redefinition over
  `rag_assertion_eligible_base`, a view in a transaction-local setting set and restored by
  one helper, and labels only when a view is given. Required response: k=1 starvation
  tests per candidate family; byte-identical omitted-view payloads; an `invalid_view`
  matrix; a setting-leak test across savepoints and an autocommit connection; `memory_get`
  canonical resolution with requested/canonical identities; and the documented
  legacy-duplicate limit (AF-066-001b). Next: tasks.
- **AF-066-005 — Open, derived-output invalidation.** Question: do profiles, thematic
  summaries, aliases, existing 6.7 patterns and caches stop presenting merged members as
  current, without rewriting evidence? AC-007, US-003. Evidence: `profiles.revision`
  fingerprints row xmins only and runs no eligibility function; `profiles.read` and
  `thematic._state` revalidate through `assertion_eligible`; `rag_pattern_current` calls
  `assertion_eligible` on dependencies; the query cache holds vectors only. Impact: the
  profile can say `fresh` after a decision; under `include_merged` a withheld pattern could
  reappear if the pattern check honored the view setting. Required response: a scope
  lifecycle token in `profiles.revision()`; redefine `rag_pattern_current` with an
  explicit hidden check that ignores the view; tests show profile/thematic `stale`,
  pattern withheld after apply and restored after correction with unchanged ev1, and no
  pattern re-exposure under `include_merged`. Entity/alias paths stay untouched by D4.
  Next: tasks.
- **AF-066-006 — Open, stale relationships and canonical failure (spec clarification;
  coordinator acknowledgement required).** Question: what does `current` show when an
  anchor is edited, moved, refuted, expired or purged after apply? AC-006, spec edge cases
  (target edit/withdrawal/expiry/scope move, source deletion). Evidence: migration020
  supersession ignores the newer row's later state; `curation.purge` hard-deletes refuted
  documents; `documents.updated_at` changes on every gateway update. Impact: either
  silent knowledge loss (member stays hidden behind an unavailable canonical) or revival
  of a superseded value. Decision D7: duplicate/extension hide only while both anchors
  are unchanged and the target is base-eligible at the selected time. Replacement hides
  from `effective_at` while the target row exists. Anchors have no FKs, so purge works and
  history remains. Stale or unavailable relationships appear in detail/history and
  `review_report`. Required response: tests for each transition, in both directions where
  reversible. Next: coordinator accepts D7 as the spec clarification before tasks.
- **AF-066-007 — Open, populated upgrade and 0.6.18 code boundary.** Question: which
  0.6.18 operations remain valid before and after first use, and what does rollback mean?
  US-004, AC-009, IC-004, FR-005, PB-066-OPS. Evidence: `service.upgrade.SUPPORTED_VERSIONS
  = range(18)` excludes 0.6.18; restore allowlist line 370 and `schema.SCOPED_TABLES`
  lack the new tables; the schema check accepts a superset of migrations; the old-code
  harness exists in `tests/service/test_synthesis_upgrade.py` (`SOURCE='81beaf6'`). The
  plan's citation of a root-level `test_synthesis_upgrade.py` is a path slip. Decision D8:
  no activation fence. Old readers honor decisions through SQL, with no labels or views,
  and the profile status may read `fresh` until a refresh. Old writers only make
  relationships stale. Old restore tooling refuses through `target_drift`. Dropping 031
  is unsupported, and backup restore loses later writes. Required response: add 0.6.18 to
  the supported versions; extend the allowlist, scoped-table and RLS checks; add a new
  upgrade test pinned to `d4d2372` with populated multi-user/multi-domain data. It
  exercises old search/get/graph/profile/curation/save before and after the first
  decision, original-row/grant/owner hashes, interrupted and empty retry, and verified
  backup restore with stated post-backup loss. PB-066-OPS records these limits and the
  restart guidance. Next: tasks.
- **AF-066-008 — Open, authorization and disclosure.** Question: do preview, detail,
  errors and counts stay inside reader/writer and principal/domain/project authority over
  local and central transports? AC-008, IC-001..003. Evidence: `READ_TOOLS`/`WRITE_TOOLS`
  registration; `rag_service_document`; the synthesis RLS pattern; definer guard design.
  Impact: preview or the guard reveals foreign IDs or counts, or an RO server gains a
  write. Decision: preview/detail are read tools; apply/correct are write tools only. The
  uniform `not_found` carries no counts. The same-scope invariant keeps guard messages
  non-disclosing. Members per canonical are capped at 500 with pagination. Required
  response: RO tool-list tests; foreign/invisible/missing parity over MCP, REST and CLI,
  local and central; a revoked writer before commit; and an RLS test where a reader sees
  the member iff it sees the decision. Next: tasks.

Proportionality: no new worker, queue kind, event-delivery service, model call or
dependency. The overlay is two tables, one guard, three SQL functions and one helper
module. Blocking for task generation: the coordinator must accept or reject
AF-066-001(a)/(b) and AF-066-006/D7. Everything else is a task-mapped design obligation.

### RAG-066 coordinator design dispositions (2026-10-31)

AF-066-001(a)/(b) accepted with explicit spec boundaries: overlay anchors exclude
assertions/aliases/synthesis; detail still explains existing assertion relations and
legacy archived duplicates. AF-066-006/D7 corrected: duplicate/extension may release
members under their own truth gates, but replacement remains suppressive until
correction even when the target disappears. AF-066-004 explicit include-merged
bypasses only merged duplicate/extension links; explicit historical uses qualified
past records while omitted legacy history keeps its old behavior. These dispositions
supersede conflicting recommendations above and must be implemented/tested.

- **AF-066-009 — Open, conservative exact automatic proof.** AC-002/010, IC-001/002.
  Existing curation only matches same-domain/project body, even when titles identify
  different entities. Require identical title/body/dtype for automatic archival and
  new exact classification. Preserve existing archival/edge/audit semantics; reject
  different-title pairs and measure legitimate differently titled non-merges. Meaningful
  red/green and unchanged cross-scope/evidence immutability checks required.
- **AF-066-010 — Open, immutable anchor snapshot versus action ABA.** AC-005/006/007,
  IC-002/003. A lifecycle event count inside lv1 protects optimistic concurrency but
  must not be used as the active-link base snapshot: insert would stale itself and
  later group actions would stale siblings. Use a separate content/evidence/state/
  scope snapshot excluding lifecycle event counts. Compare full snapshots, including
  source revisions, to detect source ABA that updated_at misses. ev1/src1 remain
  unchanged by overlay operations. Add tests for immediate effect, multiple members,
  apply/correct ABA, source withdrawal/reinstatement and old writer edits.

AF-066-007/009 compatibility refinement: new exact-title policy lives in Python,
so old0.6.18 automatic workers cannot enforce it. Upgrade/restart all workers and
hook launchers in PB-066-OPS; an old-code fallback must disable curation with
curation_budget=0 and prove that behavior. Ordinary old reader/writer support is
separate and must be measured.
