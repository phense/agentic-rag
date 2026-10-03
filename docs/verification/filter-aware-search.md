# PB-5.5: Review and rehearsal evidence

## Scope

- Playbook: [filter-aware-search.md](../filter-aware-search.md),2026-10-03.
- System: source99514fe012666e67dff02ae2419e05a6c876d1f9/schema015, candidate016 in isolated `feature/filter-aware-search` checkout; PostgreSQL17.10, installed pgvector0.8.4, Python3.13.
- Owner: maintainer Peter; RAG-5.5 T005/AC-005–008. Readiness deadline: before feature PR/merge readiness; production adoption is a separately approved gate.
- Validation: actual populated migration, interruption/retry, read/write old-client coexistence, savepoint/cancellation recovery, strict shared-snapshot restore and every public-table fingerprint/role-table privilege.
- [Numerical evidence](../benchmarks/2026-10-03-filter-aware-search/README.md) and [rehearsal script](../../scripts/verify_filter_aware_search.py).

## Content review

Independent reviewer `/root/review_filter_plan` inspected the complete bounded base995 diff and PB-5.5; no shared DB tests or live mutations by the reviewer. Content-review verdict **Ready**,2026-10-03. Initial findings were verified against source and fixed, then independently re-reviewed.

| Finding | Severity | Verified correction | Evidence |
| --- | --- | --- | --- |
| New function discovery outside planner savepoint | Medium | Protect `available()` too; retain audited pending write after real40ms discovery timeout | `test_discovery_timeout_preserves_pending_audited_caller_write` |
| Vector-only Trading diagnostics lose production settings | Medium | `planned_vectors()` runs under actual `_planned_settings`, then restores | script source; actual-copy oracle comparisons |
| Rollback procedure not executable | Medium | Clean-check, detached SOURCE_REV/DEPLOYED_REV, exact import/HEAD checks and client reconnection | PB-5.5 rollback steps; actual old-code readers after016 |

No unresolved Critical, High, Medium or Low finding in the inspected source. Final numerical identity checks match application bytes exactly and reconstruct the tested SQL hash through the recorded four-line trailing-whitespace-only correction; all SQL tokens/statements remain identical. Synthetic script hash matches current bytes; Trading retains its tested script hash plus a reconstructable one-line unused synthetic metadata correction. No measured samples were edited. Final independent artifact acceptance: Ready,2026-10-03; reviewer reconstructed both nonbehavioral deltas and checked all published numerical claims.

## Rehearsal

Coordinator executed audited gateway fixtures in randomly named ownership-checked databases; mutations,016 and recovery never targeted production. The production measurement source was a read-only exported snapshot, restored strictly into empty owned targets. Private dumps remain outside Git. Every public table, including derived contexts, is inventoried; only the expected migration row changes during016. Existing table grants remain identical.

Observed synthetic acceptance: actual995 store/search modules and001–015 schema; new-code015 citation parity; actual016 DDL rollback before commit, retry via migration runner, repeat no-op; original rows/contexts, pins, claim/evidence/source/assertion history, checkpoints, queue and audit rows unchanged; concurrent old/new readers; actual source-version writer correction after016; actual old search code rollback; reader write denial; strict exported-snapshot source015 backup restored and checked; ownership cleanup. Subsequent read-only measurements also retain all row fingerprints.

Tests demonstrate caller/autocommit transactions, success/restoration, isolated neighboring connections, tighter40ms/1s/1min/unlimited budgets, actual40ms statement timeout, real external cancellation, pending audited caller writes retained with no unexpected commit, and usable subsequent searches. Exact4096-chunk ordering matches the exhaustive oracle including ties; one audited added chunk exercises4097 and a real HNSW index access diagnostic. Current pgvector0.8.4 executes all SQL; unsupported0.7.4/unknown/absent optional-GUC policies are simulated at capability discovery, not claimed as installed-extension downgrade tests.

Fresh final checks:

```sh
PYTHONPATH=/Users/peter/Agents/agentic-rag/.worktrees/adaptive-search /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q
node --test tests/test_opencode_plugin.mjs
```

**987 Python tests passed in127.36s;7 Node tests passed in78.60ms.** Both4096 and4097 boundaries now share one large fixture rather than duplicate its expensive audited creation; assertion coverage is retained. No dependency sync or installer touched the production environment.

Two early Trading-copy attempts reached the candidate2s timeout. The first exposed duplicated exact-probe/source-hash work; the helper now reuses one materialized probe. The second exposed missing planner statistics on the restored copy; the rehearsal now executes ANALYZE only on the owned copy before both source/candidate routes. A subsequent20-pair/three-case run passed with exact recall and original-citation parity. The final regeneration reflects retained013/015-style function-local ef_search caching; no budget was increased or caller cancellation swallowed. Failed owned targets were cleaned up.

Source-hash validation can be expensive for long documents. Candidate/pool limits cap returned representations, not all scans or hash work. ANN scan limits are approximate;2s applies to the candidate SQL statement, not embedding, reranking or whole-search latency. Broad slow queries can still reach a real cancellation. No universal speedup, production answer-quality gain, cold-cache claim or sustained concurrency capacity is established.

## Acceptance and freshness

PB-5.5 drafted, independently content-reviewed Ready; populated synthetic upgrade/recovery and representative Trading-copy measurements are rehearsed. Final byte-aligned numerical verification passed; final independent artifact acceptance is Ready with no open finding. At this pre-merge evidence checkpoint root production is99514fe/schema015;016 is not deployed. Subsequent live adoption is tracked in canonical Issue30. Issue30 remains open until its specific merge and applicable rollout acceptance.

Bundled continuity CLI cannot derive a project key from this repository's legacy numbered BACKLOG. No saved run exists; current Git/worktree/Issue/reviewer/artifacts were revalidated manually. No successful CLI initialization, recovery, event or checkpoint is claimed.

## Architecture and requirement mapping

- AC-001: installed capability discovery plus unsupported/missing-GUC policy tests.
- AC-002/004, AF-5.5-02: independent exact oracles, raw/context source/model/domain/project/status/time guards, document diversity and original spans/citations;4096/4097 and large pool comparisons.
- AC-003/005, AF-5.5-01: bounded statement/scan/memory settings, successful restoration, real timeout/external cancellation, caller/autocommit/neighbour ownership.
- AC-006: actual015 new-code fallback; additive/interrupted/repeated016; all canonical/derived rows and grants retained; actual old clients/code rollback; strict source snapshot restore.
- AC-007: three practical controlled examples and three representative private Trading-copy controls,20 alternating pairs per route, first calls separate, raw timings and honest unchanged/extra-cost cases.
- AC-008:987 Python/7 Node fresh, independently reviewed complete bounded diff with verified/re-reviewed fixes; numerical identity checks passed; final artifact review recorded below.

The [as-built transaction sequence](../uml/filter-aware-search.md) matches protected discovery, nested savepoint/owned idle transaction, one materialized probe, exact/ANN route and original-source results. Cross-component success and failure flows above were derived from the architectural review, then exercised with real gateway and SQL calls.

Reviewed PB-5.5 SHA256: `851c5c8c6a411cdc726ba9f5ec5aaa86722e4eff4b0a23ae5f8550de20639cb8`.


Final artifact review by `/root/review_filter_plan`: **Ready**, no unresolved Critical/High/Medium/Low. Published counts/timings,20 paired observations and60 citations per Trading route were independently checked; rounding raw published samples can differ by0.001ms from medians computed before sample rounding. PB-5.5 hash matches. Fresh current-format SQL checks:44 passed,1 already-covered heavy boundary deselected,9.23s. The full987 suite had covered both heavy boundaries; whitespace-only SQL formatting leaves all tokens identical. No Low bug was deferred. Requirement, as-built integration, review and verification inventories converge without an actionable implementation gap; T009 records publication separately.
