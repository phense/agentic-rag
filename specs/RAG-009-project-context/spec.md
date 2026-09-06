# Feature Specification: Bounded project context

## Stable work ID

Feature RAG-009; GitHub #9; accepted under the user's next-issue implementation request.

## User scenarios

- US-001(P1): At startup, see bounded advisory project conventions and recent focus,
  with inspectable sources, beside exact pins and continuity restoration.
- US-002(P1): Normal project questions and explicit history references retrieve useful
  context; unrelated prompts avoid memory noise and model/provider calls.
- US-003(P1): Corrections, withdrawn sources and expiry stop stale context. A failed
  refresh retains a dated, revalidated view or the established startup path.

## Acceptance criteria

- AC-001: Stable and recent sections have separate limits, source document/event IDs,
  validity and kind labels. Unsupported proposals cannot become stable instructions.
- AC-002: EN/DE project/history questions without error signatures can recall applicable
  evidence; unrelated questions do not acquire project memories. Errors retain old recall.
- AC-003: Pins remain byte-faithful; checkpoint restoration and host caps remain intact;
  omitted sections/items have explicit warnings. Profiles never mutate source records.
- AC-004: Deduplicate only against actually emitted complete evidence. A hidden profile
  item cannot suppress query evidence. Repeated text on later turns queries current data.
- AC-005: Same real turn replay may suppress identical already delivered context; keys
  include host/session/project/turn/config and relevant memory revision. No prompt-text
  identity guess when the host supplies no trustworthy turn identifier.
- AC-006: Rebuild failure preserves prior cache atomically and exposes its date; every
  cached reference is revalidated for scope, current trust and validity at read time.
- AC-007: Reader CLI/MCP cannot rebuild/write canonical data. Refresh runs asynchronously
  through the existing queue/worker and audited gateway; no new hosted provider.
- AC-008: Publish baseline/after useful-context rate, redundant characters/tokens,
  recall firing precision and hook p95 on labeled synthetic positive/negative prompts.

## Functional requirements

FR-001: One local context service powers CLI/MCP and both shared hook clients.
FR-002: A rebuildable profile stores bounded references, not a second canonical narrative.
FR-003: Deterministic gates, strict applicability, bounded rendering and transparent failure.

## Compatibility boundaries

One PostgreSQL store, audited/redacted writes, immutable claims, exact pins, existing
checkpoint policy, host output schemas and provider neutrality remain. Additive profile
storage only; no corpus rewrite/backfill or extra scheduler. Legacy incomplete sources
remain recent advisory references, never automatically stable preferences.

## Interface contracts

| ID | Boundary | Inputs / outputs | Failure invariant |
|---|---|---|---|
| IC-001 | profile gateway | project -> dated bounded IDs | atomic refresh; sources untouched |
| IC-002 | local context | project, mode, prompt/session -> text + metadata | cap, scope and provenance |
| IC-003 | hook replay | real turn + current revision -> emitted receipt | no cross-turn prompt cache |

## Edge cases and assumptions

No cwd selects explicit global context only. Missing trustworthy turn ID disables replay
suppression. A CLI hook cannot edit old conversation messages; no such claim is made.
Stable conventions use directly supported stated claims with preference/convention cues;
all labels remain advisory. Recent views may contain clearly labeled legacy references.

## Success measures

All acceptance regressions pass; synthetic unrelated injection rate0, positive useful
context improves over error-only baseline, all payloads within existing host limits.
Target synthetic hook p95<=500ms without a hosted query model; report scale limitations.
