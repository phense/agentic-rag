# Feature Specification: Dashboard reranker selection

## Stable work ID

- Feature ID: RAG-062 (Issue62, roadmap6.4, step4/15), settings extension.
- Status: Accepted for implementation by the maintainer request.
- Source request: expose MiniLM L6 EN/DE, mMARCO DE/EN and Jina tiny EN in Settings;
  adopt mMARCO by default in PR82 and provide a tested existing-installation upgrade.

## User scenarios

### US-001: Choose a local reranker (P1)

An authenticated administrator sees the three language-labelled options, the
current selection, runtime availability and an explicit preview/apply action.
Members cannot administer settings. A stale page cannot overwrite another change.

### US-002: Upgrade without changing knowledge (P1)

An existing multi-user/multi-domain installation adopts the new default or keeps
its explicit custom configuration. All canonical data, original citations, ACLs,
credentials, jobs, pins, checkpoints and audit history survive code rollback.

## Acceptance criteria

- AC001: Exactly three supported selectable presets appear; mMARCO is the fresh
  default. Jina tiny is explicitly labelled English only, with no DE guarantee.
- AC002: Selection survives process restart and affects subsequent local-runtime
  search calls from REST and remote MCP, including old protocol1 clients. An
  in-flight search uses one immutable effective configuration.
- AC003: Non-admin, missing CSRF, revoked session, malformed choice, stale revision,
  duplicate operation and unavailable/mismatched runtime cannot change selection.
- AC004: Every applied selection has a durable nonsecret administrative audit.
  Crash-after-file-replace recovery uses the existing prepared journal. Runtime
  changes after validation preserve deterministic fallback within 1500ms.
- AC005: Preserve eligibility, scopes, payload identity, score validation, timeout
  and bypasses. Presets use the measured focused6x600 budget; sigmoid transports
  native logits without treating them as confidence. No search-time downloads.
- AC006: Ship an offline local runtime and explicit preparation command for the
  three presets, with pinned model/tokenizer hashes, bounded input and concurrency,
  no request logging or remote inference. Activation remains operator-owned.
- AC007: Rehearse upgrade from0.6.14/schema027 and rollback using a populated
  isolated store, persisted settings, existing clients and unchanged row hashes.
  Only the additive audit-kind constraint migration028 is permitted; no embedding rebuild or knowledge mutation.
- AC008: Browser desktop/mobile, native inference smoke checks, focused tests,
  complete suite and independent full bounded diff review pass before handoff.

## Functional requirements

FR001: Only reranker presets become editable; other model/provider configuration
stays file-owned/read-only. FR002: Explicit existing custom model/revision/budget
remain supported. FR003: Show unavailable separately from configured selection.
FR004: Persist only a preset ID; never credentials, request content or model scores.

## Compatibility boundaries

Source0.6.14/schema027 -> target0.6.15/schema028 within the same unmerged PR82.
Missing reranker configuration intentionally now means mMARCO/focused-v1. Explicit
legacy Qwen/JinaGGUF aliases and timeouts remain usable. Existing binaries ignore
an additive [reranker] policy table; code rollback removes its effect without
rewriting the policy or database. Selecting a model changes ordering only, not
stored embeddings. mMARCO can time out under concurrent CPU load; fallback stays.

## Interface contracts

| ID | Boundary | Contract |
|---|---|---|
| IC001 | Browser settings | GET state; POST preview/apply with policy revision, preset, operation UUID |
| IC002 | Policy authority | Existing owner-only policy file, lock, session fence and prepared audit |
| IC003 | Search/runtime | Loopback discovery must match preset alias and SHA256 before sending sources |
| IC004 | Runtime weights | Explicit public download, immutable pinned artifacts; startup verifies hashes |

## Edge cases

Absent runtime retains deterministic ordering. Invalid policy selection fails
closed. Existing explicit custom model is shown as custom until a preset is
chosen. English-only is a language support disclosure, not automatic detection.
The service administrator controls a server-wide setting, not per-user knowledge.

## Assumptions and unresolved decisions

No production rollout/restart was requested. Install and switch only on owned
isolated rehearsal resources. Tiny ONNX is a separately identified artifact from
previous GGUF measurements; do not transfer benchmark numbers between them.
No unresolved scope/security decision remains.

## Success measures

SC001: Three presets selectable with durable preview/apply and real native rank.
SC002: Zero changes to canonical row hashes or users/scopes on upgrade/rollback.
SC003: Zero open C/H/M findings before updated PR handoff; deferred Low in Issue75.

## Playbook obligations

PB062-SETTINGS: maintainer/operator preparation, adoption, interruption recovery
and code rollback under docs/reranker-settings.md. Must be independently reviewed
and rehearsed before handoff; production execution requires separate approval.
