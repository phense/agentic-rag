---
id: RAG-062-SETTINGS-EVIDENCE
title: Dashboard reranker settings verification
type: reference
doc_id: standalone
readers: [maintainer, operator]
status: verified
version: 0.6.15 / schema028
last_edited: 2026-10-31
summary: Settings authority, pinned native runtime, populated upgrade and old-code rollback evidence.
---

# Dashboard reranker settings verification

This record covers the Settings extension to [Issue62](https://github.com/phense/agentic-rag/issues/62)
in [PR82](https://github.com/phense/agentic-rag/pull/82), roadmap step4/15.
The starting head is `a8441eb6a4c48c7204f21bfcfad449021e2a9077`;
the upgrade source is main `7a61955446119df522a34967273d8dacae56108b`,
0.6.14/schema027. Target is0.6.15/schema028. Earlier benchmark reports retain
their original measured identities and failed-protocol boundaries.

## Behavior and scope

Administrators can preview and apply MiniLM L6 EN/DE, mMARCO DE/EN or Jina tiny
(English only). mMARCO is the new default. Settings uses the existing protected
policy authority and prepared/applied administrative journal. It affects the
server's next eligible search; an in-flight search retains one model snapshot.
Explicit legacy/custom identities remain supported. No source or embedding
rebuild occurs. Migration028 only widens the existing audit-kind constraint.

The new optional ONNX daemon verifies pinned model and tokenizer hashes,
advertises alias plus artifact SHA, accepts literal-loopback traffic and admits
one native inference at a time. Explicit preparation is the only download path.
Tiny ONNX is distinct from the earlier GGUF artifact; no old timings or language
quality figures are attributed to it.

## Verification boundary

Accepted Settings/upgrade rehearsals and the final full-suite invocation use
coordinator-owned PostgreSQL17 on port55460, synthetic fixtures and disposable
databases. An initial affected-test attempt and an excluded reviewer command
omitted the PG override and targeted the default-socket fixture database
`agentic_rag_test`; their partial/failed output is not accepted private-cluster
evidence. Neither command targeted the canonical `agentic_rag` database. Existing production,
provider, embedding and deployed model settings are unchanged. Native smoke uses
retained public artifacts on the reference CPU, affinity0–3, without a GPU.
This is functional evidence, not a new representative throughput benchmark or
production capacity acceptance. mMARCO's earlier concurrency limitations remain.

The required final gates are the entire Python suite, Node adapter tests,
installed-wheel imports outside the checkout, native smoke, desktop/mobile
browser flow, independently derived success/recovery paths, independent bounded
code review and content review of [PB062-SETTINGS](../reranker-settings.md).
Final commands, exit artifacts and review disposition are recorded below only
when complete; a running process does not satisfy a gate.

## Independent findings and regression proof

The initial architecture/full-extension review found two Medium defects:

- A reserved preset alias with an incorrect configured SHA was treated as a
  custom model, bypassing managed identity verification. Config now rejects the
  inconsistent tuple before any source transfer.
- Cancelling a request while its worker was queued could strand the single
  native slot. The submitted executor worker is shielded from caller
  cancellation and owns slot release through completion.

Both regressions were observed RED, then the affected46 tests passed in1.45s.
The initial report deliberately retains its inspected-tree findings; an
independent recheck must establish their final disposition.

## Rehearsed operator paths

PB062-SETTINGS requires populated027-to028 upgrade with verified backup restore,
unchanged original rows, an empty second migration run, interrupted transaction
retry and code-only rollback using actual archived0.6.14. Old local, REST and
remote MCP searches must retain nonempty authorized results with foreign rows
excluded. The old daemon's neural ranking is not claimed while disabled.

IT062-SUCCESS connects admin selection to REST/MCP search, changing a preset
while an earlier search is paused at inference. IT062-RECOVERY connects an
interrupted settings write, application restart, journal reconciliation,
wrong-SHA fallback without passage POST, upgrade preservation and old-code reads.
Tests retain original retrieval payloads and scores; operational/session/audit
changes are enumerated separately from canonical rows.

## Recorded checks

- Combined Settings/upgrade command: `PGPORT=55460 .venv/bin/python -m pytest
  tests/service/test_reranker_upgrade.py tests/service/test_reranker_settings.py
  -q --tb=short` with PGHOST/PGHOSTADDR/PGSERVICE/PGSERVICEFILE unset and owned
  TMPDIR/evidence paths. Exit0: eight passed, one upstream warning,32.15s.
  [Targeted record](issue62-settings/targeted-exit.json) is explicitly a
  coordinator transcription; [preservation summary](issue62-settings/upgrade-summary.json)
  is generated by the successful test assertions. The full-suite record supplies
  a separately captured machine exit for these tests as part of the whole run.
- Independent recheck:28 database-free regression tests passed in1.00s. A
  separate active-cancellation probe observed429 while native work continued,
  then200 after drain. Both initial Medium findings are independently resolved.
  [Initial review](issue62-settings/settings-architecture-review.txt) and
  [complete bounded recheck/content review](issue62-settings/settings-final-review.txt)
  retain their distinct inspected boundaries. Code and playbook content are
  Ready with zero open C/H/M/actionable Low; final execution acceptance was
  deliberately pending at review time.
- Final wheel build: `uv build --wheel --offline`, installed without dependencies
  outside the checkout. Python3.13.13 imports the three-preset catalogue, new
  default and all28 SQL files; module help exits0. All169 packaged product/SQL
  files match the current tree, and package metadata contains the current README.
  [Wheel record](issue62-settings/wheel-ipv4-final.json) identifies SHA256
  `e8d6d489eea467e8566b1ac910c969aa422f35e70e1221afc928409ca93bd647`.
  This final build incorporates the independently rechecked IPv4-only binding
  and the current README metadata; all product/SQL bytes match the final tree.
- Installed-wheel native smoke: three exact alias/SHA identities, five successful
  positive-over-negative probes, EN/DE for L6 and mMARCO, EN for tiny. These are
  n=1 functional probes per listed model/language, not statistical quality or
  latency acceptance. [Actual responses and cleanup](issue62-settings/native-ipv4-final-smoke.json)
  and [executed runner](issue62-settings/native-ipv4-smoke-runner.py.txt) retain the
  evidence. The runner deliberately stopped its daemon (exit-15); subsequent
  connection failed with111. No model listener remains on its owned port8783.
- A further [real product-adapter/native check](issue62-settings/native-adapter-final-smoke.json)
  uses the installed final wheel, actual discovery/SHA validation and unchanged
  1500ms budget. Five eligible three-source calls (EN/DE for L6 and mMARCO, EN for
  tiny) all report `ranked`: the synthetic Berlin source moves from third to
  first, retaining every original object, citation field and retrieval score.
  Each listed model/language has n=1; these are integration controls, not an
  accuracy estimate. [Executed adapter runner](issue62-settings/native-adapter-runner.py.txt)
  retains the assertions and owned daemon cleanup.
- Browser Settings case passed in9.75s at1440px and390px, with preview/reload,
  apply/reload persistence, language warning, no horizontal overflow and no JS
  errors. [Desktop](issue62-settings/reranker-settings-desktop.png) and
  [mobile](issue62-settings/reranker-settings-mobile.png) show the deliberately
  saved L6 test choice; the initial mMARCO default is asserted before that change.
- `node --test tests/test_opencode_plugin.mjs`: seven passed, zero failed,
  332.84ms. `node --check agentic_rag/service/dashboard_assets/app.js` exits0.
  `uv lock --check --offline`:55 packages, exit0. Documentation continuity:
 17 tests pass in0.83s. Local Markdown links resolve.

The [initial reviewed-source manifest](issue62-settings/reviewed-source-manifest.json)
freezes30 code/catalogue/SQL/dependency/script/test files at digest
`60a572d1933152936e7f10c2e0bc7be07c2350b9c4d3c7628b57b9f01834043d`.
The [playbook binding](issue62-settings/playbook-review-binding.json) records its
frontmatter-only status change after content approval; the procedure body is
byte-identical. The [publication normalization](issue62-settings/publication-normalization.json)
records host PCI-identifier redaction in benign ONNX warnings. Locally retained
raw logs and failed pad-token/Python-ABI attempts remain failures; none is counted
as a successful native run.

## Final native-bind correction

A later direct ASGI probe found that the installed framework accepts127.0.0.1
but rejects the offered IPv6 Host with400. The new daemon now offers only its
documented127.0.0.1 binding and rejects unsupported hosts at argument parsing
before model load. The legacy adapter can still use separately supplied IPv6
loopback runtimes. The regression was observed RED, then47 affected tests passed
in0.94s. [The complete bounded bind recheck](issue62-settings/settings-bind-final-review.txt)
independently verifies this final code against the accepted extension; no Settings, auth, migration or stored-data
behavior changed.

[The final manifest](issue62-settings/final-source-manifest.json) identifies
exactly the two changed files and current30-file digest
`e947260f13ef15bd1f6fd9e0010ea2ff206a786da6712ac791b3d359b10ff73e`.
The previous whole-suite attempt was deliberately interrupted for this fix:
[actual exit/timing](issue62-settings/interrupted-settings-full-final-timing.json)
is2, with1,352 passed, one skipped and one warning before SIGINT. Its source
digests were equal. It is not a successful full-suite gate; the new final
invocation uses `ISSUE60_TEST_RUN=settings-full-ipv4-final`.

## Final evidence

The complete Python suite exits0: **1,756 passed, 1 skipped, 1 upstream warning**, in1498.32s. The captured
[machine exit, timing and source digests](issue62-settings/full-suite-exit.json)
[executed runner](issue62-settings/full-suite-runner.py.txt) and
[complete output](issue62-settings/full-suite.log) belong to
`settings-full-ipv4-final`, after the last product/test correction. The runner's
before/after source digests are identical; the final30-file reviewed manifest
also matches. The skip is macOS-only and the warning is the upstream Starlette
TestClient deprecation. Browser and populated-upgrade tests run within this suite.

All AC001–008 and FR001–004 have current implementation, integration and review
evidence. As-built architecture, independent success/recovery paths and the
unchanged reviewed procedure body agree. There are zero remaining actionable
convergence findings. [Acceptance record](issue62-settings/acceptance.json)
binds the evidence. No merge or production rollout has occurred. The maintainer's
next approval is required for PR merge.


Final delivery checks: [17 documentation tests, seven Node tests, lock/syntax and
local-link checks](issue62-settings/delivery-checks.json) pass after the evidence
update. The owned PostgreSQL55460 instance was identity-checked and stopped;
[cleanup record](issue62-settings/postgres-cleanup.json) proves process exit,
closed listener and retained data. No production service was changed.
