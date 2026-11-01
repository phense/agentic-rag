# Extraction-policy measurement (RAG-067)

This measurement checks what the versioned extraction policy does to mined
output on seven frozen synthetic English and German cases. Each case runs
through actual mining: a transcript file, `read_window`, the real prompt, a mock
provider, the unchanged grounding, the policy filter and the audited gateways,
in owned PostgreSQL databases that the script creates and drops. The mock
provider returns each case's hand-written output and sometimes ignores the
guidance on purpose. So the figures show deterministic enforcement, retry and
replay. They say nothing about how well a real model follows guidance.

- Source: `048a9f8` (clean product tree), package 0.6.20, migration032.
- Baseline: the same cases without a policy file, which is the unchanged 0.6.19
  behavior (same prompt and schema, see `test_without_a_policy_file_payload_and_prompt_are_unchanged`).
- Environment: Python 3.13.13, PostgreSQL 17.10 with pgvector, one shared host,
  local test server on port 55460.
- Repetitions: 3, each in a new database. Every deterministic outcome was
  identical in all repetitions (`deterministic_outcomes_identical: true`) and
  matched the frozen labels (`all_labels_matched: true`).
- Raw output: [results.json](results.json). Script: [measure.py](measure.py).
  Frozen inputs and labels: [fixtures/](fixtures/README.md), committed at
  `ad256e7` before any product change and checked by SHA-256 on every load.

## Before and after

Items kept in the accepted batch, per category (same provider output):

| Case | Without policy (0.6.19 behavior) | With policy | Dropped by the policy | Provider calls |
|---|---|---|---|---|
| R1 decision plus abandoned experiment and error signature (EN) | 1 memory, 1 lesson, 1 signal | 1 memory | lesson and signal: `category_disabled` | 1 |
| D1 project rule (DE) | 2 memories, 1 lesson, 1 pin suggestion, 1 domain proposal | 1 memory, 1 pin suggestion | memory: `item_limit`; lesson (451 characters): `body_limit`; domain proposal: `category_disabled` | 1 |
| L1 abandoned experiment labelled as a memory (EN) | 1 memory | 1 memory | nothing | 1 |
| S1 exact quote and invented claim with a credential (EN) | 2 memories | 2 memories | nothing | 1 |

L1 is the known limit: the guidance asks to skip abandoned experiments, the
provider ignores it and labels the experiment as an allowed memory, and the
filter cannot tell. In S1 the quoted memory keeps its exact source quote and
stays a user statement (`stated`); the invented one loses its evidence link
(`inference`, 0 links) and its credential never reaches storage (redacted). These are
the unchanged grounding and redaction rules, now running after the policy.

## Retry, replay and the empty policy

| Check (per repetition) | Result |
|---|---|
| P1: provider outage, then the file is replaced by B (lessons off) and by a malformed file | The retry used the admitted policy A (same `xb1:` digest), read no file and kept the lesson |
| P1: provider calls until acceptance / on replay | 2 / 0 |
| P1: new admission after the replacement | new digest, lesson dropped (`category_disabled`) |
| P1: admission with the malformed file | refused, 0 queue rows added |
| Z1: every category disabled | 0 provider calls, empty batch accepted, cursor advanced, `skipped: extraction disabled by policy` |
| V1: malformed file | `reserved_setting` at `rules[1].write_domains`, `duplicate_selector` at `rules[1]` |
| Foreign writes (other project or domain) | 0 in every case |
| Bindings / binding audit rows per repetition | 11 / 11 |

## Latency

Wall time of one worker job (`process_job` plus completion) in milliseconds,
three repetitions, mock provider (no network, no model):

| Case | Values | Note |
|---|---|---|
| R1 | 325.43, 126.24, 116.14 | first job of each database includes warm-up |
| D1 | 81.82, 77.51, 78.20 | |
| L1 | min 79.20, max 81.93 | |
| S1 | min 115.69, max 130.09 | |
| P1 failed attempt (binding committed, provider raised) | min 20.81, max 21.87 | |
| P1 retry (bound policy, accepted and applied) | min 74.83, max 79.14 | |
| P1 replay (accepted result, no provider call) | min 4.00, max 4.43 | |
| Z1 all disabled (no provider call) | min 20.62, max 22.51 | |

These times measure the local pipeline around a provider that answers
instantly. A real provider call adds its own latency; the policy adds no call.

## Limits

- Mock provider only: no statement about real-model extraction quality or
  about whether a model follows guidance.
- Seven small synthetic cases on one host; timings vary with load.
- Embeddings were disabled (no Ollama), so near-duplicate linking did not run.

## Recheck after the policy-binding corrections

At clean product revision `e88717f`, the same seven frozen cases were measured
again in three owned databases: all labels matched and all deterministic
outcomes were identical. [results-final.json](results-final.json) preserves the
new observations separately from the original results above. Providers remained
scripted, embeddings disabled; these figures do not measure model quality.
The CM1 domain-add/revocation regressions are separate from these frozen cases:
41 affected tests passed, and the coordinator re-executed the prior independent
correction script with37/37 assertions passing. That replay is coordinator
verification, not a new independent review. Independent correction acceptance
and the root full-suite result remain separate gates.
