---
title: PB06801 review and rehearsal evidence
type: reference
audience: administrators
version: 0.6.11
---

# PB06801 review and rehearsal evidence

Version0.6.11/schema024; updated2026-10-30. This is an owned-copy development
rehearsal, not production cutover or a maximum-capacity guarantee.

## Verification and review

- The final isolated Hetzner Python run passed **1,520 tests, 2 skipped**,
  one upstream Starlette warning, 327.19s, exit 0. Skips are macOS launchd and
  absent real Claude transcripts. Applicable OpenCode Node checks: **7 passed**.
- Independent complete-range Sol/high review1 found2High/5Medium/1Low. All were
  reproduced and corrected; the Low diagnostic mismatch is LOW-011 in Issue75.
  Review2 found1High/2Medium around ambiguous Gemini authorship, header-only
  recording and a background dependency cycle. Five red regressions reproduced
  them; 19 focused checks passed. Review 3 examined all 62 files of tree
  `6368f674c5db79bd3ea35697d9734e93e4848bef` against base `07f989f` and found
  no remaining defects; its independent selections passed 78 Python and 7 Node
  checks. This is the third and final independent review, not a native UI proof.
- A subsequent real-cloud repetition found one transient result-publication
  lock collision: 119 of 120 requests completed, one failed with
  `result_capacity_exceeded`; all 20 source windows applied. Three new tests
  reproduced this. The small correction waits at most one second, then keeps
  the same accepted input pending while rolling back uncommitted effects.
  All 22 affected tests passed, followed by the full run above. This correction
  was coordinator-checked after review 3; its corrected cloud repetition is
  reported separately below, without hiding the failed run.
- One later non-blocking status detail is open as
  [LOW-012](https://github.com/phense/agentic-rag/issues/75#issuecomment-6513105016):
  successful completion can retain its former transient deferral code. A real
  HTTP/SQL probe confirmed the successful result and exactly one document/audit;
  the connector follows terminal state and consumes that result correctly.
- Built wheel `agentic_rag-0.6.11-py3-none-any.whl` includes schema024 and plugin
  code. A fresh environment installed it outside the checkout; install and
  doctor passed for all three native packages (6 operations). Offline dependency
  installation initially lacked cached wheels; normal dependency installation
  succeeded. `uv lock --check --offline` passes with 42 packages.
- Synthetic populated023→024 migration, current024 versioned backup/strict
  restore and retry passed. The real populated reference copy began at022;
  its verified upgrade applied023/024 and preserved299256 original rows across
 26tables, including compatible embeddings, history, ACLs and pending jobs.
  Only afterward were copied legacy jobs frozen to prevent original private
  transcripts reaching the rehearsal model. Twenty new synthetic windows were
  extracted using the authorized provider; all20 reached applied.

## Native observations and practical continuity traces

Claude native manifest validation passed; Codex CLI0.165.0 installed the owned
package through an isolated marketplace; Gemini CLI0.66.0 installed the extension
after its explicit trust prompt in a private test home. No credentials were
copied to the isolated Gemini home. Validation/install do not prove interactive
hook delivery or model-authenticated manual/automatic compression. Issues12–14
remain open for those actual native scenarios.

1. Claude/Codex manual and automatic payload fixtures run the real pre-compaction
   adapter, retain source/checkpoint, then remove the host transcript. The private
   spool still contains original source and the matching trigger. Child/fork/
   maintenance callbacks do not enter the capture engine.
2. Gemini fixtures cover a fresh header-only recording, patches, manual/automatic
   PreCompress and next-BeforeAgent handoff restoration. Installed-host source
   replay demonstrates that BeforeAgent also receives hook-generated continuation
   reasons. Both recording-user and hook-input prose therefore remain advisory;
   no synthetic approval acquires original user support. A history parse failure
   retains the separately observed input before reporting the failure.
3. Real HTTP/SQL connector tests cover durable ACK loss/replay, read/write/result
   consumption, owner-only extraction status and foreign denial. A subprocess is
   killed inside queued-save embedding; restart applies exactly one document and
   one save audit record. Cancel, scope/credential change and oversized result
   roll back canonical effects. Accepted source-backlog pressure yields to the
   source worker and then completes the waiting mutation without cancellation.

These are controlled adapter/HTTP/process traces, not authenticated native UI
observations. PB06801 package preview/apply/doctor/update/uninstall/recover was
rehearsed on owned directories; partial update/uninstall recovery preserves the
reviewed generation and refuses foreign edits. Native memories and pending input
remain outside package ownership.

## Reference-host 40-client measurements

CX33, 4 vCPU/7757 MiB, no swap; separate code/database copy and loopback API.
Each phase offered 40 simultaneous mixed requests from 4 uploader identities in
2 teams: 14 metadata, 13 context, 13 populated hybrid searches, reranking disabled.
After the publication correction, all 120 requests received durable handles and
completed. Gateway throttling was retried with the same envelope: 96/91/82
transport retries across the phases. Before the third burst, the sampler observed
an actual active background inference child. These are finite workloads, not a
maximum-throughput ceiling or an agreed response-time guarantee.

| Phase | Metadata p50/p95 | Context p50/p95 | Search p50/p95 | Total |
|---|---:|---:|---:|---:|
| Idle extraction | 22.43/50.44s | 34.02/40.21s | 38.55/65.30s | 71.74s |
| 20 queued source windows | 27.63/53.46s | 40.64/59.54s | 38.14/64.15s | 69.56s |
| Active background inference | 35.05/63.34s | 48.49/51.59s | 35.36/62.45s | 67.98s |

These latencies include queue wait and polling. Fixed foreground consumers limit
concurrency; the mixed queue can delay small metadata/context calls behind search.
Context p95 rose in the growing-backlog sample, while search p95 fell slightly.
The samples do not isolate causation or establish a numerical latency guarantee.
A short hook returns a waiting handle or labeled retained context while accepted
work finishes. Operator acceptance of a latency budget remains a rollout decision.

The corrected 1-second sampler collected 299 points over 336.51s, including the
subsequent background drain. PSS apportions shared pages; summed RSS can count
the same PostgreSQL pages repeatedly.

| Process group | Peak PSS | Peak RSS | CPU-time increase |
|---|---:|---:|---:|
| API | 71.16 MiB | 85.18 MiB | 22.89s |
| One worker and its CLI helpers | 320.64 MiB | 339.36 MiB | 24.50s |
| Shared PostgreSQL instance | 588.74 MiB | 1600.32 MiB | 333.66s |
| Shared Ollama service | 840.14 MiB | 846.10 MiB | 234.05s |

There was one API application process and one serial extraction worker. The
worker's group contained at most 4 processes including transient CLI helpers,
not one inference session per client. Maximum connections to the rehearsal
database: 10. One embedding model remained resident, with at most 695845517
reported model bytes. Shared PostgreSQL/Ollama CPU includes other instance work;
it is not attributed exclusively to the test.

Database size grew 656463539 to 656799411 bytes (335872 bytes). This measures
logical database files, not whole-host WAL, backup or snapshot growth. After the
rehearsal, host SSD usage was 18 percent with about 59 GiB free. All 20 new
synthetic source windows applied after interactive demand subsided; the owned
API/worker were stopped before the separate sustained run. The earlier sampler
with the wrong Ollama unit and the later 119/120 failing run are retained as
private diagnostic evidence, not substituted for this corrected result.

## Sustained workload

Forty concurrent logical clients continued submitting work for 300 seconds through
a bounded shared HTTP pool. Outstanding work finished after 370.65 seconds:
203 offered, 203 durably accepted, 203 completed; 135 transport retries, no failed
or expired accepted requests. Each client completed at least 4 turns. Another
20 synthetic source windows waited behind this foreground demand.

| Tool | Completed | End-to-end p50/p95 |
|---|---:|---:|
| Metadata | 73 | 71.03/83.05s |
| Context | 66 | 70.58/84.03s |
| Populated hybrid search | 64 | 73.37/83.04s |

The active phase supplied 323 resource samples over 371.55 seconds. API peak
PSS/RSS was 69.44/86.68 MiB; median PSS of its first/last 10 samples was
65.55/69.44 MiB. The paused single worker stayed at 53.28/53.29 MiB median PSS,
peak 53.29 MiB. Shared PostgreSQL peaked at PSS 685.15 MiB (RSS 3060.38 MiB);
Ollama peaked at PSS 841.88 MiB (RSS 847.86 MiB), with one resident model.
Maximum rehearsal-database connections: 12. API/worker/PostgreSQL/Ollama CPU time
increased 55.44/1.35/683.23/351.22 seconds. Database files grew 311296 bytes.
The worker did not start a model child during the sustained interactive phase;
its retained sources resumed afterward. Warm-up growth and these finite samples
do not establish zero leakage or an indefinitely sustainable arrival rate.
All 20 reached `applied` after the foreground run; the owned API and worker
stopped successfully. This gives 40 applied synthetic windows across the two
final corrected rehearsals.

The installed-copy smoke also started the actual plugin stdio server and called
it through an MCP client, then through the queued HTTP connector into the copied
store. RW exposed 20 tools, RO exposed 11; save/get returned the synthetic body
and RO rejected mutation. This is an actual process/transport observation, not a
claim of authenticated Claude/Codex/Gemini UI compression.

## Evidence identity and rollout boundaries

The final full Python command ran as the owned PostgreSQL test operator with
`PGPORT=55458`, private test HOME and `PYTHONDONTWRITEBYTECODE=1`:

```sh
/opt/agentic-rag-68/.venv/bin/python -m pytest -q -rs -p no:cacheprovider
node --test tests/test_opencode_plugin.mjs
```

Python log SHA-256:
`5e0febd1233b403dba44b6bc39afa27a73b2a39d9da7b54c6e94c2987c1ccae4`.
Tested code/test snapshot manifest SHA-256:
`1913ab0e9abee36293b5cb99ceef04d266144fe4c275672a61072354a485745d`.
Final documentation/evidence edits follow that snapshot and receive their own
render/link and 15-test documentation check; application code remains identical.

Complete private logs, distribution/source manifests and aggregate JSON remain
outside the repository. Public evidence contains no original private corpus,
prompts or tokens. Native authenticated manual/automatic compression, abrupt
terminal exit and resume scenarios remain open under Issues12–14. Production
writer cutover and independent-store consolidation remain separate operations;
the canonical worker's boot guard stays inactive. A day-long leak test, sustained
40-client model inference and acceptance of a numerical interactive latency
budget remain unproved. Finite storage/retention guards and short workload
measurements are the evidence supplied by this PR.
