# RAG-5.10 verification record

Implemented and measured; merge and production adoption remain pending. Feature9 is
PR47, source `d5e2ce49a4a48554b5d9de58c3beb3b5a4d43d9d`/schema019. Measured
Feature10 code is `5b390692e32e07c8816e98091dfa66e15e0c2cb3`; both compared retrieval
profiles use that revision. Canonical live code remains
`1294d6c44fd02b66715692f12791bfa2fd4c8856`/schema018. Feature10 adds no SQL,
provider/client configuration, hooks, jobs or MCP tools. Existing source018 fallback
and source019 clients remain supported; combined adoption needs Feature9's019 migration
and separate production authority.

## Tests and independent reviews

`PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q`:
**1274 passed in167.83s**. `node --test tests/test_opencode_plugin.mjs`:
**7 passed in78.251334ms**. Full suites ran at the measured5b39069 source; later
handoff changes are documentation/public evidence/CI only. Offline CI commands also
ran locally:39 pure contracts passed,16 private safety/attribution contracts passed,
and36 pure optimizer checks passed. Database-requiring tests are included in the full
local suite; no hosted CI database/provider credentials are required.

Test-first phases observed missing modules/interfaces, absent prompt/CLI seams and
immutable model identity. Independent findings had meaningful regressions before fixes:
whole entity/alias history splits, private tamper/permissions/safety selection, source
revision drift, foreign CLI working directory, wider-visible unequal source pools and
schema-time checkout drift. A real owned rehearsal exposed invalid fixture graph actors;
an added old→new replacement plus alias integration failed with five query observations,
then passed through the supported CLI executor. Public source labels remain metadata,
not per-user ACLs. A workload-bound test reduced scope resolutions from19944 to below1000.

Two independent reviewers (`review_failures_quality`, `review_failures_operational`)
reviewed the complete source9→5b39069 bounded diff and draft PB-5.10, including the
actual operator helper, fixtures, CLI/CI, correction and recovery drivers. Each reports
zero Critical/High/Medium/Low findings. Neither accessed private state/configuration,
canonical databases or providers. Final public evidence/handoff review and hosted CI
are recorded with the PR before merge approval is requested.

| Finding | Verified disposition |
| --- | --- |
| Candidate mining hash-map mismatch | Exact producer metadata accepted; held-out fields remain rejected. |
| Mixed embedding/source/prompt identity | Known local identity and source/prompt bytes frozen and guarded; drift invalidates output. |
| Private candidate rewrite or unsafe dev choice | Exact0600/0700 sealed bytes/readback before held-out and final publication; safety-first selection. |
| Private/foreign-CLI attribution | Frozen full application source/revision reused in private candidate/report; native revision bound to package repository. |
| Cross-attribute/alias split leakage | Scoped identity union joins alias endpoints and every attribute/query before split binding. |
| Global/ancestor eligibility mismatch | Unsupported mixed visible corpus rejected before services; separate exact-boundary queries supported. Production selection unchanged. |
| Source019 operator path only embedded in test | Reusable `activate_failure_evaluation.py` exercised by the driver and exact PB commands. |
| Schema-time switch drift | Clean checkout rechecked under worker lock immediately after schema verification and before Git. |
| Fixture actors invalid for historical graph edges | Supported audited CLI executor, original actor labels preserved in evidence/provenance/review audit. |

## Actual public measurements

Unified command:

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python scripts/verify_failure_evaluation.py \
  --output docs/benchmarks/2026-10-04-failure-evaluation \
  --private-dir /absolute/private/new-directory --repeats 20 \
  --mine-model --production-copy --trading
```

Exit0; all125 measured application/SQL/script/fixture hashes remain unchanged.
[Results](../benchmarks/2026-10-04-failure-evaluation/results.json) SHA256:
`bd06fa88245eb562a1315fa2d164898da521281ee6533584b01c947b4e28e6a8`.
[Examples and raw links](../benchmarks/2026-10-04-failure-evaluation/README.md)
contain complete source revisions, labels, source citations, raw timings, costs and limits.

Public retrieval:204/204 indexed originals/chunks/non-null vectors;0 index/query errors.
48 held-out queries, six independent synthetic source/alias/history families,
20 alternating pairs/query and960 latency observations/route. Supported extractive
correctness30/48→48/48; positive evidence recall24/36→36/36; false abstentions18/36→0/36;
unanswerable irrelevant exposure12/12→0/12 while correct abstention stays12/12.
Current corrections6/18→18/18; independent project/domain answers6/12→12/12;
historical originals6/6 on both. Wrong-scope/stale output0 on both routes.
p50/p95:223.982/246.363→44.0895/53.179ms; mean context2764.375→102.750 characters.
Index times21.450/21.517s for separate102-source splits; profiles share each index.

Actual native mining:8 configured Codex/gpt-6.1-sol calls on public fixtures. Dev source
accepts1/2 corrections versus0/2 for the extra prefix; three reviewed/withheld outputs
remain misses. Better dev recall selects the unchanged source prompt. Held-out source
and selected prompt each accept2/2 independent user corrections, no unsafe suggestions,
one complete resulting chunk/vector per case; all8 extraction results replay identically
without another provider call or duplicate application. Two-family/native backend limits
prevent a prompt-gain claim; billing/token cost is unavailable. No private content is sent.

## Executed existing-installation and recovery evidence

Combined source018→019 runs strict consistent source/target backup restore, populated
multi-domain old/new writes on018/019, interrupted DDL rollback/retry/no-op, retained
rows/grants/pins/checkpoints/queue/audit and fresh10-reader/18-main MCP contracts. Actual
owned Git activation, schema-committed retry and detached source recovery retain019 and
branch refs; eight unsafe activation/recovery cases reject. Source/candidate writers
both hold persistent uncommitted audited transactions before either commits at each schema.

Source019 code-only adoption/retry/recovery executes the reusable PB helper on an owned
clone, with strict fresh019 backup/restore/checksum/cluster identity and unchanged19-file
SQL ledger. It proves unavailable→available→unavailable new CLI discovery, retained
original rows/grants and later overlapping writes, old/new CLI/MCP contracts, branch refs
and reacquired worker lock. Dirty checkout, busy lock and schema-time drift actually reject.
Code recovery detaches source9 and retains019; it restores no database and loses no later
rows. Active clients must reconnect for new commands; no service interruption/reinstall
or adapter configuration change is required by this additive code-only feature.

A fresh canonical018 consistent backup was strictly restored to an owned representative
copy;019 DDL interruption/retry/no-op there preserved all21 original public tables/grants.
At that snapshot:10614 documents,12004 chunks,7 domains,22 pins,34 checkpoints,
1416 queued rows,1025 batches and39019 audits. Counts can change with normal live work.
Canonical application writes and private provider calls are0; destructive work/restore
stays owned. Private backup/report/labels are outside Git with restrictive permissions.

Controlled private-format export/evaluation retains8/8 confirmed corrections across four
alias identity families. Three assistant/unreviewed/incomplete negatives produce0 labels
(two accepted negative roots are withheld; assistant remains review disposition). Three
families are dev, one held-out; FTS/entity dev scores tie6/6, stable choiceFTS scores2/2
held-out. Entity baseline also8/8. Candidate readback/seal/modes, full original inventories
and118 audit rows remain unchanged. Inference attempts/writes/vectors generated are0;
owned cleanup verified. This is a controlled public fixture through the private contract,
not a production correction-availability estimate; one held-out family has null uncertainty.

Trading on live018:3 public lexical queries, separately recorded first call plus20 repeats
each;480 repeated citations verified against original eligible chunks. Source control
p50/p95ms:portfolio66.257/84.751, earnings77.831/82.585, regime159.869/163.765.
No private excerpts/provider/application writes; no live Feature10 policy gain measured.

## Limits and remaining authority

Candidate routing chooses existing tools with explicit literal selectors, not automatic
entity extraction or general language-model answers. Synthetic structural families yield
degenerate bootstrap intervals and no real-traffic assurance. Query caches are retained,
first calls included; model-identity checks are outside query timers. Native prompt outputs
vary; reviewed misses remain visible. Final raw JSON privacy inspection found only known
metadata false positives (`token_estimation` description and public `secrets.py` source
hash), no credential/private-content values. No partial failed report is promoted.

The new corpus confirms a pre-existing domain-free temporal comparison/supersession
problem, tracked separately in [Issue48](https://github.com/phense/agentic-rag/issues/48).
Exact entity routing recovers this fixture's original; no historical gateway/SQL repair
or private impact estimate is included. All review findings in the bounded implementation
are resolved. Feature9/10 Issues remain open pending applicable approved merges/adoption.
Merge approval does not authorize production migration, rollout or interruption.
