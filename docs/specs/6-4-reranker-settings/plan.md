# Plan: Dashboard reranker selection

Status: approved for the requested end-to-end implementation; extends RAG-062.
Baseline a8441eb, source main7a61955/0.6.14/schema027; target0.6.15/schema028.

## Evidence and architecture

Dashboard currently only edits auth policy, through dashboard_policy._store:
owner-only file lock -> prepared journal -> session-row fence -> atomic file
replace -> applied journal. Reuse this authority for an additive [reranker]
profile field in the same policy file. No new SQL table is needed. Migration028 widens only the existing audit kind constraint.
Only Settings may mutate that field. Existing user/machine policy edits preserve
it; old binaries ignore unknown top-level tables. Config remains immutable.

A packaged preset catalogue holds exactly three model aliases, upstream pinned
revisions, model/tokenizer SHA256 and pad-token identity. Model selection maps to
alias+artifact SHA+focused-v1. Defaults change to mMARCO; explicit model/revision
TOML keeps the historical budget when policy is omitted. A new optional
[rerank] profile shortcut sets the same validated tuple. Mixing profile with
model/revision is rejected rather than silently ignoring manual values.

neural_rerank.order snapshots the effective selection once, reading the protected
server auth file when configured. Each search is internally consistent; later
requests see the latest selection even from queued REST/remote MCP calls. No
mutable per-process configuration pointer or model-switch restart is required.
Preset discovery requires the matching alias and artifact SHA before query data.
Existing custom runtimes retain the previous alias-based contract.

New module reranker_runtime provides explicit prepare/serve commands. prepare
fetches only pinned public artifacts into staged files and checks every hash;
serve verifies local files, loads all installed presets before advertising them,
uses optional ONNX CPU+tokenizers+numpy,512 token pair truncation, sigmoid logits,
one shared inference slot/no queue, bounded body/time/field validation and literal
127.0.0.1 binding. The installed Host guard rejects IPv6; do not offer an
unusable native bind. Legacy custom IPv6 adapters remain supported. No remote code, request logs or search-time network download.
The administrator must prepare/start this optional service separately.

Settings state/preview/apply routes reuse browser session+CSRF, current policy
revision, UUID operation replay guard and existing journal. Read state exposes
only preset metadata and available identities. Preview/apply test discovery and
one fixed public EN/DE synthetic probe for the requested model; unavailable
models cannot replace the selection. Apply checks fresh authority again after
probing. Unknown runtime never receives a real query. Availability after commit
can change, so search retains deterministic fallback.

## Ownership and integration order

Coordinator owns all edits: catalogue/config/neural adapter -> runtime -> policy
and settings API -> UI -> tests/docs. Independent reviewer owns only its report.
Serialize this coupled interface; no parallel implementation writers.

## Verification and upgrade

Test first against missing settings/default contract; then test admin/CSRF/races,
restart persistence, recovery after replace, custom config preservation, local
runtime body/identity/hash validation, timeout/no-score behavior and payloads.
Native smoke the three presets using owned offline model files. Rehearse real
archived0.6.14 and new code on a populated isolated multi-domain store, compare
all canonical row hashes, retain credential bytes and perform old/new protocol1
REST+MCP calls. Browser desktop/mobile and full Python/Node/wheel checks follow.
No canonical-production writes, service restarts or embedding provider calls.

## Playbook inventory

PB062-SETTINGS: docs/reranker-settings.md, system operator, AC006/007; document
prepare/start, default transition, restart/retry, custom preservation and rollback.
Independent content review and populated rehearsal required before PR handoff.
No destructive development procedure: existing private PG runner and isolated
model service suffice; keep owned data and source evidence after stopping them.

## Risks and limits

mMARCO concurrency on the reference CPU can exceed1.5s; one shared slot rejects
pressure promptly. A client timeout cannot cancel a native kernel, but the slot
remains occupied until it completes. Quantized Jina tiny ONNX differs from old
GGUF; only fresh native smoke/compatibility is claimed here. No generic speedup
or German tiny support is inferred. No GPU/TLS/deployed-host acceptance claimed.
