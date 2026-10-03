# agentic-rag — feature registry

This registry separates behavior present in the repository from operational
deployment. A feature is not called live merely because its implementation and
tests exist.

**Status:** ✅ shipped in code · 🔵 in progress · ⬜ planned · 🔒 blocked by a
precondition · ⏸ paused. The numbered source of truth for unfinished work is
[`BACKLOG.md`](BACKLOG.md).

## Memory platform

- ✅ **Explicit project scope (issue #5).** Canonical project/global/unknown
  applicability across search, recall, startup assembly and optional graph traversal;
  same-known-scope curation, audited legacy repair and synthetic scope fixtures.
  See [scope policy and rollout](docs/project-scope.md).

- ✅ **Synthetic memory benchmark (issue #3).** Versioned 60-query EN/DE corpus,
  real gateway/mining and retrieval modes in an owned temporary database,
  source-recall/answer metrics, failure denominators, context budgets, latency,
  machine-readable reports and offline CI contracts are implemented. Local FTS/hybrid
  baselines and an authorized eight-query real-model smoke are measured; all eight
  answers/judgements were inspected. This is not a general-quality claim.
  See [usage and limits](docs/benchmarks/memory-quality.md).

- ✅ **Durable local store.** PostgreSQL + pgvector documents, structural
  chunks, fixed document/predicate vocabularies, dangling-safe typed graph
  edges, and archive/refute history are shipped.
- ✅ **Hybrid retrieval and graph navigation.** HNSW vector search, bilingual
  English/German full-text, deterministic rank fusion, full document lookup,
  neighbors, shortest paths, and timelines are shipped. Retrieval degrades to
  full-text with a warning if Ollama is unavailable.
- ✅ **Canonical audited writes.** CLI, MCP, mining, and migration writes share
  the secret-stripping `save_document()` gateway and least-privilege database
  roles.
- ✅ **Domains and explicit memory tools.** Dynamic domains, save/get/search,
  scoped user-owned pins, read-write MCP tools, and an independently enforced
  read-only MCP surface are shipped.
- ✅ **Provider-neutral session mining.** Schema-constrained Codex and Claude
  CLI adapters, bounded delta-only transcript digests, single-writer background
  jobs, secret-stripped provider-bound matching pin bodies without mutating
  stored pin text, near-duplicate detection, and lossless outage recovery are
  shipped. Claude remains the configuration-only provider rollback.
- ✅ **Resumable source-window ingestion (issue #4).** Versioned source-bound
  cursors, durable normalized extraction batches, atomic application through the
  gateway, stable item provenance, automatic pending remainder and status reporting
  are implemented. Dedicated migration/privilege and real process-death tests cover
  new input; historical backfill is separate. See the
  [deployment and recovery procedure](docs/implementation/issue-4-recovery.md).
- ✅ **Curation and human review.** Bounded dangling-edge resolution,
  exact-duplicate merging, contradiction review, inert suggestions,
  refute-as-archive, confirmed admin-only purge, and `rag review` are shipped.
- ✅ **Migration.** Dry-run, backup-gated import of an existing llm-wiki store,
  domain classification/application, and acceptance reports are shipped.
- ✅ **Operations and recovery.** Provider/queue/checkpoint/status reporting,
  local plus opt-in synced backups, retention, deliberate database restore,
  log rotation, scheduled maintenance, and report-only restore-testing are
  shipped.
- ✅ **Claude Code integration.** The default no-option installer registers
  read-write/read-only MCP servers and merges six Claude hooks plus the managed
  `autoCompactWindow` without replacing foreign settings; `rag install --check`
  previews the merge and writes nothing.

## Codex continuity

- ✅ **Provider-neutral checkpoints.** Audited, non-deleting checkpoint
  persistence; deterministic Git/transcript-cursor capture; bounded rendering;
  and asynchronous schema-constrained enrichment are shipped in code.
  Enrichment output is screened value by value (issue #2): an unstorable or
  ungrounded value is dropped and named in the checkpoint's `Warnings:`
  line instead of voiding the other fields; a credential still fails the
  job, and the word guard exempts paths and identifiers.
- ✅ **Six lifecycle handlers.** `SessionStart`, `UserPromptSubmit`, `Stop`,
  `PreCompact`, `PostCompact`, and `SessionEnd` handlers are shipped. Only
  `SessionStart(source="compact")` can restore checkpoint context after
  compaction; `PostCompact` records the boundary and never injects context.
- ✅ **Compact prompt and policy installer.** The versioned prompt and the
  lossless `rag install --codex` transaction are shipped. The managed policy is
  a 350000-token context window, a 250000-token total-scope compaction limit
  (100K reserve; nominally 22K below the higher-pricing boundary), enabled
  hooks/native Codex memories, and Luna extraction and consolidation.
- ✅ **Safe preview, rollback, and health reporting.** Non-writing check mode,
  unique backups, a mode-0600 rollback record, conflict-safe restoration, hook
  trust instructions, and checkpoint/provider fields in `rag status` are
  shipped in code.
- ✅ **Pre-install review.** Whole-branch review, focused security/preservation
  tests, the full suite, isolated wheel installation, and an immutable
  temporary-home check-mode exercise are complete.
- 🔵 **Global Codex rollout.** A reference macOS deployment has the database
  migrations, native memories, the 350000/250000 context policy, compact prompt,
  and six merged lifecycle handlers installed. The idempotent installer probe,
  handler trust, `rag status`, host-side `codex doctor`, and a fresh connected
  session passed. Live verification remains pending under backlog 0.2 for
  manual/automatic compaction, provider outage/recovery, and SessionEnd tail
  capture. Continuity is therefore installed but not yet claimed operationally
  proven across every end-to-end boundary. The Codex sources confirm that
  `PostCompact` completes before `SessionStart(source="compact")` runs, and
  that handlers are discovered once per session (a session opened before the
  install never runs them).

Native Codex memories are complementary: they may adapt Codex from prior work
and remain inspectable with `/memories`. agentic-rag is the canonical store for
durable, searchable, auditable knowledge and explicit continuation state.

## Claude continuity

- ✅ **Six Claude handlers.** `SessionStart`, `UserPromptSubmit`, `Stop`,
  `PreCompact`, `PostCompact`, and `SessionEnd` share the Codex modules;
  `hooks.common.client_kind()` selects the Claude branch from argv and the
  payload, and every existing Codex test stays green.
- ✅ **Compact prompt channel.** `PreCompact` prints the versioned
  `assets/claude/compact_prompt.md` (≤ 4,000 chars, `Version: 1.0`) plus the
  checkpoint id on stdout, which Claude appends to its compaction prompt; the
  prompt is printed even when persistence fails and the hook never exits 2.
- ✅ **Handoff.** `PostCompact` matches the newest same-session/same-trigger
  `PreCompact` checkpoint without a `turn_id` (compacted or not — the newest
  compaction wins), marks the boundary, and stores Claude's
  `compact_summary` as a bounded (`handoff_max_chars`, default 8,000),
  secret-stripped, audited handoff (migration 008: `handoff`, `handoff_at`).
  Only the `<summary>` block of Claude's raw output is kept; the `<analysis>`
  scratch block is discarded, and block boundaries are tags on lines of
  their own (tags quoted inline in the prose are content). Over the bound,
  the middle is cut out so the head and the tail (pending work, current
  state, next step) survive around a `…[truncated]` marker. Replays are
  idempotent; a newer summary replaces the older one.
- ✅ **Context cap.** `SessionStart` renders the handoff with a
  `CURRENT`/`HISTORICAL` age label (shortened into the remaining render
  budget, head and tail kept, rather than dropped, so a full-length handoff
  still surfaces) and caps its
  whole output at
  `context_max_chars` (default 9,500; hard maximum 10,000, Claude's per-hook
  limit). The checkpoint is elastic: it is shortened into the remaining budget
  before knowledge, domains, checkpoint, or pins are trimmed, and the visible
  warning names what was shortened, dropped, or cut. `SessionEnd` enqueues
  the final delta for every Claude reason within a 1 s timeout (measured
  about 0.12 s).
- ✅ **Managed 1M/500K policy.** The installer sets `autoCompactWindow =
  500000` only; it reports a `model` without the `[1m]` suffix,
  `autoCompactEnabled=false`, and overriding `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
  / `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` / `DISABLE_AUTO_COMPACT` /
  `DISABLE_COMPACT` without rewriting anything.
- ✅ **Check and restore.** `rag install --check` previews the merge and
  writes nothing; a changing install stages, backs up to a unique
  `settings.json.bak.<id>`, publishes atomically, records a mode-0600
  rollback record, and prints the exact `rag install --restore <record>`
  command, which is target-aware for Claude and Codex records. `rag status`
  shows `checkpoint handoff:` freshness.
- 🔵 **Live rollout.** `rag install` ran on the maintainer machine on
  2026-09-04 and a manual `/compact` proved the PreCompact → PostCompact →
  SessionStart chain (checkpoint, 7,999-char handoff, `rag status` freshness
  line, no hook errors). That smoke exposed and fixed two defects (raw
  `<analysis>` block stored as handoff; whole-section trimming evicting the
  checkpoint). A second manual `/compact` the same day, after the 0.4.0
  release, found the summary extraction cutting at tags quoted inline in
  the prose and the head-only bound dropping the summary's pending-work and
  next-step sections — both fixed (line-anchored tag boundaries; head-and-tail
  truncation). Still open: `/hooks` review, `/autocompact` confirmation, an
  automatic compaction, a SessionEnd tail capture. See backlog 0.3.

Claude auto-memory is the Claude analogue of native Codex memories: a
complementary local layer that this feature neither installs nor changes.
agentic-rag remains canonical.

## Antigravity continuity

- ✅ **Antigravity CLI adapter.** `rag install --agy` merges one named hook
  (`SessionStart` 10 s, `PreInvocation` 5 s, `Stop` 10 s) into
  `~/.gemini/config/hooks.json` losslessly, with check mode, unique
  `hooks.json.bak.<id>` backup, atomic publish, mode-0600 rollback record, and
  a target-aware `rag install --agy --restore <record>`.
- ✅ **Derived compaction events.** `PreInvocation` reads the transcript tail:
  a `/compact` request is PreCompact (cursor `agy-step-<idx>`, enrichment,
  versioned `assets/agy/compact_prompt.md` injected with the checkpoint id);
  `Stop` is PostCompact (the model's summary becomes the bounded handoff);
  an automatic-compaction marker is both at once plus an immediate checkpoint
  re-injection. Error-signature recall runs on every new prompt.
- ✅ **Transcript support.** Antigravity steps flow through the shared
  digest (`build_digest`), mining window (`read_window`), and checkpoint
  cursor capture (`agy-step-<n>`), with the same redaction and
  tool-names-only rules.
- 🔵 **Live rollout.** Installed on the maintainer machine on 2026-09-06;
  `/hooks` lists the hook and a headless `/compact` smoke produced the
  checkpoint, prompt-shaped summary, handoff, enrichment, and mining job with
  no hook error. One observed automatic compaction is still pending
  (BACKLOG 0.4); that marker shape is inferred from the binary, not observed.

## Planned hardening

- ⬜ Broaden prompt-recall evaluation beyond the measured synthetic project corpus.
- ⬜ Correct curation cadence/audit growth and cap-aware mining cursors.
- ⬜ Define the intended refute-trigger recency semantics, then decide whether
  a recency check is warranted ([BACKLOG 2.2](BACKLOG.md#2--housekeeping--test-coverage)).
- ⬜ Improve worker-death idempotency and complete the listed coverage gaps.
- ⬜ Validate duplicate review under sustained load, normalize interactive save
  confidence, preserve built SessionStart context on maintenance failure, and
  re-resolve installed scheduler paths after environment moves.

The details, dependencies, reasons, and resumption triggers for every planned
item remain in [`BACKLOG.md`](BACKLOG.md).

## Atomic fact validity (issue #6)

Evidence-backed immutable assertions support explicit replacement, extension, expiry
and as-of/history retrieval across one shared store. Mining retains source event
identity, role, quote and completeness; uncertain assertions stay reviewable.
Ordinary documents and pins are preserved. See [policy](docs/fact-validity.md) and
[synthetic comparison](docs/benchmarks/2026-09-06-fact-validity/README.md).

## Claim evidence and inference status (issue #7)

Ordinary mined claims retain bounded source spans, event identity, speaker and kind.
Distinct event counts exclude assistant corroboration; source withdrawal and explicit
span-bound review compose with scope/time selection. Both automatic hooks and manual
retrieval expose evidence status. [Policy](docs/claim-evidence.md).

## Retrieval evidence quality (issue #8)

Diverse bounded hybrid candidates, query-centered contiguous spans and chunk citations;
exact-symbol preservation, optional two-hop evidence-bearing graph expansion and a
validated local reranker seam. Bilingual FTS remains available during embedding outages.
See [policy and limitations](docs/retrieval-quality.md). Migration013 activated; installed reader and citation checks passed.

## Adaptive retrieval (issue #26)

Merged in PR #36 as `f27acd9`; adopted locally on 2026-10-03. Eligible exact
UUID/slug and standalone error-symbol queries skip local query inference; ordinary questions
and misses keep hybrid retrieval. Optional CLI/MCP strategies preserve forced hybrid and
explicit lexical behavior. No schema/configuration/data migration. In 20 paired Trading
measurements per case, median exact lookup fell from about 1,040–1,064 ms to 16.5–17.0 ms;
the ordinary-question control retained identical citations and about 1,050 ms latency.
[Evidence and limits](docs/benchmarks/2026-10-03-adaptive-search/README.md).

## Query inference reuse (issue #27)

Merged in PR #38 as`342bccf`; adopted locally on 2026-10-03. Long-lived MCP
sessions reuse bounded context/model-scoped query vectors with fresh SQL authority and
local model-digest checks. HTTP transport reuse preserves one-shot process cleanup and
fork isolation. Paired Trading warm medians fell 1,045→811 ms and 422→185 ms for repeated
question/context examples; citations remain identical 20/20. Twenty synthetic correction
pairs preserve immediate source withdrawal with half the inference calls.
[Evidence and limits](docs/benchmarks/2026-10-03-query-cache/README.md).

## Bounded project context (issue #9)

Source-backed stable/recent profile references, asynchronous audited refresh, scoped
EN/DE selective recall and real-turn post-output receipts. Shared reader CLI/MCP and
hook context preserve exact pins, checkpoint priority and explicit cap omissions.
[Policy](docs/project-context.md); [measurements](docs/benchmarks/2026-09-06-project-context/README.md).
Migration014 activated; installed reader and audited profile refresh verified with unchanged
documents/pins. Published implementation2c46e02; CI34024173116 passed.

## OpenCode (RAG-OC-001)

- ✅ Native adapter code: transient context/recall, matched checkpoint and handoff, sanitized stable transcript projection, debounced idle queue, child exclusion and guarded loader installation.
- ✅ Local rollout: installed from retained checkout; canonical startup context and read-only MCP healthy. Real DeepSeek startup/manual-compaction/restore passed with synthetic test-database data. A production T3 thread on the Mac also verified canonical context delivery and a completed read-only RAG search with DeepSeek Flash. Sustained automatic compaction is not claimed. See [evidence](docs/verification/opencode.md).

## Selective local neural reranking (issue #28)

Merged in PR #39 as`ae4a102` and adopted locally on 2026-10-03 with930 Python/7 Node tests. The pinned native model is supervised on loopback; old MCP sessions adopt the code on reconnect. See [rollout evidence](docs/verification/three-feature-production-adoption.md).
A verified local Qwen3-Reranker-0.6B Q8_0 runtime can reorder up to12 ambiguous
auto candidates within1500ms. Original payloads, SQL eligibility and citations remain
authoritative. Exact identifiers/symbols and explicit hybrid/lexical/baseline routes
retain previous behavior; an absent runtime needs no config or data migration.
The three Trading development examples improve expected-source coverage in a
three-hit context, at roughly one extra second per query. No general speedup or
answer-accuracy gain is claimed. [Evidence and limits](docs/benchmarks/2026-10-03-neural-rerank/README.md).

## Contextual chunk indexing (issue #29)

Merged in PR42 at99514fe and adopted locally on2026-10-03. The full audited backfill indexed10432 documents/11822 chunks with0 retries or warnings; protected knowledge/history and strict015 backup restoration were verified. [Production adoption](docs/verification/contextual-indexing.md#production-adoption).

Feature 4 adds bounded source excerpts and document/section/project metadata
to a versioned side index; original chunks, vectors and citations remain intact.
Normal audited saves create lexical context; bounded `rag save --index-context`
adds local contextual vectors. Current-source/model checks and original eligibility
apply before contextual selection. Explicit context-off and old clients retain
baseline behavior. Additive015 and populated014 upgrade/recovery are rehearsed.

Three synthetic practical examples improve original-fact coverage from0/20 to20/20
within the same three-hit/1200-character source budget, with extra retrieval and
indexing cost. This is limited development evidence, not a production-scale gain.
The initial Trading014 controls preceded adoption. Post-adoption controls showed36.9% overhead for one question (449.353→615.142ms), with original citations retained; no production quality or speed gain is claimed. [Measurements](docs/benchmarks/2026-10-03-contextual-indexing/README.md),
[upgrade procedure](docs/contextual-indexing.md).


## Filter-aware vector retrieval (issue #30)

Feature5, adopted locally at `19ed09c` with schema016, adds read-only016 functions for default semantic context-auto searches. A single eligible probe chooses complete exact ordering for at most4096 matching nonzero chunks; larger sets use a bounded4096 ANN pool with installed iterative capabilities, original eligibility/citations and per-document diversity. Savepoints preserve caller settings/writes and propagate cancellation. Exact selectors, explicit context-off/hybrid/baseline and code before016 retain existing behavior.

Controlled crowded-source tests recover missing documents with additional SQL cost. Three20-pair Trading snapshot-copy controls retain100% raw/context vector recall and20/20 original citation-list parity, with roughly8–16ms median extra end-to-end cost. No general speedup or production answer-quality improvement is claimed. Actual015→016 upgrade/retry/code rollback, strict restore and all row/grant fingerprints pass.987 Python/7 Node checks pass. Approved merge and local adoption are recorded on [Issue30](https://github.com/phense/agentic-rag/issues/30#issuecomment-5973029391). [Measurements](docs/benchmarks/2026-10-03-filter-aware-search/README.md), [operator procedure](docs/filter-aware-search.md).

## Bounded research retrieval (issue #31)

Feature6 adds `rag research` and read-only `memory_research` on both
MCP privilege levels. Compound questions share step/call/time/context budgets;
related graph documents contribute relevant original passages. Exact quoted
support requires distinct qualified upstream sources. Disagreement, missing
evidence and abstention remain explicit. Default processing stays local;
configured-provider assessment requires an explicit request.

Three paired synthetic examples measure source coverage and literal fact
coverage, with additional worker/retrieval latency. They do not establish
production answer accuracy. Local mode always abstains semantic completion.
Schema016, ordinary search, client settings, hooks and jobs remain unchanged;
actual populated old/new/rollback clients and a strict restore are exercised.
See [measurements](docs/benchmarks/2026-10-03-bounded-research/README.md),
[operation](docs/bounded-research.md) and [verification](docs/verification/bounded-research.md).
PR44 was merged with specific approval and adopted locally at `bd01d97`,
schema016, with1039 Python/7 Node checks and fresh8/14-tool MCP clients.
All12 protected production tables,37147 historical audits and existing checkpoint/
queue/batch IDs were retained; strict restore compared17 public tables and grants.
No migration, reinstall, configuration edit or service interruption was required.
[Adoption record](https://github.com/phense/agentic-rag/issues/31#issuecomment-5973683496).

## Incremental thematic profiles (issue #32)

Feature7 candidate adds local extractive summaries to bounded profiles, with
`rag summary` and reader-only `memory_summary`. Audited refresh reuses unchanged
excerpts; each entry preserves original citations and source/version references.
Correction, expiry, source trust and scope changes withhold stale excerpts.
Historical architecture entries remain explicitly superseded, never new canonical
truth. Existing pins, checkpoints, knowledge and client settings remain intact.

The additive017 cache is compatible with016 fallback and old/new clients.
Three paired original-snapshot examples fit more eligible documents using9.89–45.77%
less context, with higher query latency; synthetic controls separately test exact
fact coverage and one-entry rebuild/seven-entry reuse. These are structural
retrieval measurements, not production semantic accuracy. See
[measurements](docs/benchmarks/2026-10-03-thematic-summaries/README.md),
[reference](docs/thematic-summaries.md), [PB-5.7](docs/playbooks/thematic-summaries.md)
and [verification](docs/verification/thematic-summaries.md). Merge approval and
production017 rollout are pending separate authority.
