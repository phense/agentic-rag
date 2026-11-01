# Contract lifecycle-v1 (RAG-066, schema031)

Status: correction reconciliation after review of `1fc0628` (2026-11-01);
independent correction review and final verification pending. Rationale and
diagrams: `../../../uml/memory-lifecycle-66.md`. Findings: AF-066-001..010. Why a separate
contract: implementation, transports, upgrade and tests need one place for the exact
budgets, codes and predicates. The spec deliberately leaves these to design.

## Operations and proof classes

| Operation | Hides member in `current` | Proof | Preconditions (all fail closed) |
|---|---|---|---|
| `exact_duplicate` | yes, while the target is base-eligible at the selected time | structural proof | identical `title` and `dtype`, identical non-empty body bytes (sha256), and, if claim-managed, identical `kind` and `content_hash`. Direction is fixed: canonical = older `(created_at, id)`, as in legacy curation |
| `semantic_duplicate` | same as exact | operator judgement, explicitly labelled "not proven" | reason required |
| `extension` | same as exact (the richer target represents the member) | operator judgement | reason required |
| `replacement` | yes, for `at >= effective_at` until audited correction, even if the target is missing, stale or ineligible | event order proven; content is judgement | both event bases known and `member < target <= now()`. Basis = earliest qualifying active source `source_at`, as in `search._TEMPORAL_SQL`. Equal, unknown or future basis returns `event_order_unproven` |
| `contradiction` | never | operator record | recorded as `contested`; listed in `review_report` and detail; neither side is hidden |

Common anchor rules: two distinct documents. Same `domain` and `project_scope`, with the
scope not `unknown`. Both `status='active'` and base-eligible now. Neither is a synthesis
document or pattern, and neither has a `fact_assertions` or `entity_aliases` row
(`assertion_managed`/`not_original`). Flat invariant: the target is not a member of any
active hiding decision, and the member is not the target of one (`chain_conflict`). One
active hiding decision per member (`already_active`).

Automatic policy: none is added. `curation.run_pass` stays the only automatic exact path,
conservatively tightened to identical title/body/dtype and existing scope/claim restrictions. No migration, worker or model ever creates a lifecycle decision.

## Versions and identities

- `lv1(doc)` = `'lv1:' || sha256(JSONB[base_snapshot(doc), anchor_revision(doc)])`.
  `base_snapshot` is the SQL `ls1` digest described below. `anchor_revision` is
  the count of append-only `lifecycle_events` touching the document, detecting
  apply/correct ABA without staling the base snapshot. The snapshot binds content
  ABA through `updated_at`, and source ABA through ev1's source revisions.
  `rag_document_version` (ev1) and `src1` are **not** changed.
- `action_key` = sha256 of canonical JSON `[operation, member_id, target_id, lv1_member,
  lv1_target, reason]`, which is unique. An optional client `request_key` (≤128 chars,
  unique within `(domain, project_scope)` when present) is stored on the event. A replay that produces the same
  `action_key` returns the existing decision and writes nothing. A known `request_key`
  that arrives with a different `action_key` fails with `replay_mismatch`. The transport
  request ID plays no part.
- Correction key = sha256 `[decision_id, decision_revision, reason]`. Decision revision =
  count of the decision's events.
- Separate `base_snapshot(doc)` binds the same content/evidence/state/scope fields but
  excludes lifecycle event counts. Store it on application and compare it for hiding
  duplicate/extension links. Using an action's pre-insert `lv1` as this snapshot would
  stale the new relationship immediately; using only `updated_at` would miss source ABA.
  Applying/correcting overlay state changes `lv1`, not the base snapshot or ev1/src1.
- Scope lifecycle token for `profiles.revision()` = `count(*)` and `max(at)` of
  `lifecycle_events` in the selected scopes.

## Storage (migration031, additive, starts empty)

- `lifecycle_decisions`: `id uuid`, `action_key` unique, `operation`, `member_id`,
  `target_id` (uuid, **no FK**, so `purge` keeps working and history survives),
  `domain`, `project_scope`, `proof`, `reason` (1..1000 chars), `member_lv1`,
  `target_lv1`, `member_snapshot`, `target_snapshot`, `effective_at` (replacement
  only), `state` (`active`|`contested`|`corrected`), `created_by`, `created_at`.
  Partial unique index `(member_id) WHERE state='active'`. Index on `(target_id) WHERE
  state='active'`.
- `lifecycle_events`: UUID `id` primary key for stable `(at,id)` paging, append-only (`rag_history_append_only`), with `decision_id`,
  `event` (`applied`|`recorded`|`corrected`), `actor`, `reason`, `request_key`, `at`,
  and `action_key`, `member_id`, `target_id`, `domain`/`project_scope` copied
  from the decision (the action key belongs to the individual operation).
- `rag_lifecycle_guard` (SECURITY DEFINER, `search_path` pinned) on INSERT and UPDATE of
  decisions. It enforces the anchor rules and the flat invariant. Identity columns are
  immutable; the only allowed transition is `active|contested → corrected`. It raises
  fixed SQLSTATE `23514` messages and reads identifiers only.
- RLS on both tables reads only the original decision scope; `WITH CHECK` uses
  that scope's write flag. Restrictive UPDATE also requires that flag. A member
  moving to another scope grants no access to the old decision or events.
  `rag_lifecycle_hidden` is a STABLE SECURITY DEFINER function with a fixed
  `search_path`, no PUBLIC rights, and grants to the existing reader/writer/admin
  roles. It returns only a Boolean, and only when the caller can read the current
  member. This preserves replacement suppression across a scope move without
  exposing decision IDs, target IDs, scope, actor, reason or request keys.
  Inaccessible and nonexistent member IDs both return false. Detail and explicit
  get use a `suppressed` / `decision_unavailable` placeholder when the original
  decision is inaccessible. Grants: reader SELECT; writer SELECT, INSERT, plus
  UPDATE(state) on decisions; admin ALL. Both tables join `SCOPED_TABLES` and
  the restore allowlist.
- `rag_assertion_eligible_base` = exact 030 body. `assertion_eligible` keeps its signature
  and adds the view-aware hidden check. `rag_lifecycle_hidden(id, at)` evaluates D7.
  `rag_pattern_current` is redefined with an explicit hidden check that ignores the view
  setting. 001..030 stay unedited.

## Budgets

| Budget | Value |
|---|---|
| Preview anchors / output source refs | exactly 2 / ≤8 per anchor plus `omitted` count |
| Apply/correct lock and statement timeout | `lock_timeout` 2000 ms, `statement_timeout` 10000 ms (never raises a stricter caller value) → `busy` (retryable, nothing written) |
| Canonical resolution | exactly 1 hop (flat invariant) |
| Active members per canonical | ≤500, otherwise `budget_exceeded` |
| Canonical members / history events page | default 20, max 100, opaque timestamp/id cursor, `more` flag; `history=true` applies the cursor to events, otherwise to canonical members |
| Detail as-member relationships | at most 20, `as_member_more` signals older relationships; older events remain accessible through history |
| Search candidates and graph nodes | unchanged: 150 and 20 |

## Views and wire

`view ∈ {current, latest, include_merged, historical}`. `latest` is an alias of `current`.
The field is added to `memory_search`, `memory_research`, `memory_get`,
`memory_neighbors` and `memory_path`. It is listed in `ADDITIVE_ARGUMENTS`, so clients omit
it when unset and older servers keep working. The REST and CLI options use the same
name. When omitted, payload shape/omitted-field encoding stays byte-identical to 0.6.18; an explicit applied decision intentionally changes current result membership. With an empty overlay, result membership is also identical. Lifecycle labels
(`evidence.lifecycle`) appear only when a view is given. Invalid combinations return
`invalid_view`. Profile, thematic, entity and context tools stay `current`-only.

## Tools and errors

READ: `memory_lifecycle_preview(member, target, operation=None)` and `memory_lifecycle(id_or_slug,
history=False, cursor=None, limit=20)`. WRITE: `memory_lifecycle_apply(...)` and
`memory_lifecycle_correct(...)`. CLI: `rag lifecycle preview|apply|correct|show|history`.
`include_merged` bypasses hiding only for exact/semantic duplicates and extensions;
replacement remains suppressed, including explicit `get`. Explicit `historical` includes qualified accepted
past records (including superseded/expired), excludes future/refuted/withdrawn or
unqualified truth, and preserves pattern withholding. Unset legacy `history` retains
its prior contract. Invalid view/history/as_of combinations fail before DB mutation.
View scope opens a transaction where needed (including autocommit), uses SET LOCAL,
and explicitly restores its prior value even across nested calls/savepoints. Derived
readers always force current semantics; request view cannot widen their dependencies.

Codes: `not_found` (missing, foreign and invisible all look alike, with no counts),
`scope_mismatch` (both visible), `unknown_scope`, `not_original`, `assertion_managed`,
`stale_version`, `replay_mismatch`, `already_active`, `chain_conflict`,
`event_order_unproven`, `budget_exceeded`, `busy`, `invalid_view`,
`proof_failed`, `review_required`, `not_current`, `invalid_arguments`,
`scope_denied` (including the existing 42501 mapping). Anchor/scope checks precede
version checks; version checks precede proof checks, so a stale request returns
`stale_version` even if a fresh proof would also fail. This avoids evaluating an
operation against a snapshot the operator did not inspect.

## Responsibilities

- SQL: the hidden predicate, the guard, uniqueness, RLS, append-only history. This is the
  authority for every reader, including 0.6.18 code.
- `lifecycle.py`: preview and classification (read-only), lv1 and action-key
  computation, view helper, detail/history pagination.
- `store.py`: the only write path. It locks anchors `ORDER BY id`, then the decision,
  inserts the decision and event, writes `audit_log`, calls `check_commit_authority`,
  commits, and rolls back everything on any error.
- `profiles.revision()`: lifecycle token. `service.upgrade`: `SUPPORTED_VERSIONS` includes
  0.6.18, plus the new allowlist and schema checks.

## Coordinator clarification (2026-10-31)

This contract incorporates accepted AF-066-001 limitations and corrections to D2/D5/D7.
Overlay assertions and aliases are excluded, but detail explains their existing
assertion/legacy relations. Legacy archived duplicates remain archived. New exact
and existing automatic exact paths require identical title/body/dtype. Duplicate/
extension stale or unavailable targets release a member only through its own truth
gates. Replacement remains suppressive after effective_at until correction regardless
of target disappearance or changes. Detail reports `canonical_unavailable` without
returning foreign/missing target identifiers. No operation revives refuted, expired,
withdrawn or independently superseded truth. Active/contested/corrected state and
permanent source/history retention are distinct from whether a member is currently
hidden. The implementation must guard lost-source/source-ABA and mixed-old-client
cases with real tests; design analysis alone is not compatibility evidence.

Old automatic-curation workers/hook launchers must be upgraded and restarted.
For a supported0.6.18 code fallback, set `curation_budget=0` before starting an old
worker and prove the policy does not archive different-title pairs. Old reader/
ordinary-writer support does not imply old automatic-policy support.

Preview classifies the requested operation when supplied; without one it can prove
an exact duplicate or report semantic review needed. It does not infer equivalence,
extension, contradiction or replacement semantics from a model or text similarity.
Manual semantic/extension/replacement apply requires `reviewed=True` plus the bounded
reason and inspected lv1 pair; this records operator judgement, not semantic proof.
The server derives action_key from the immutable request, including its reason.
A repeated original request can return its existing decision even though its own
apply advanced lv1; it must never reactivate a corrected/stale decision. Current
read/write authority is checked again before any idempotent result is disclosed.

## As-built implementation seams (2026-11-01)

At `82c031f`, store functions are thin entry points; transaction, lock, decision,
event, audit and current-authority commit code lives in `lifecycle.py`. Snapshot
SQL is defined once in the invoker-rights `rag_lifecycle_snapshots` view; a cached
PL/pgSQL merge-holds helper avoids nested per-candidate SQL re-planning. This is
a performance implementation of the same ls1 semantics, not an ev1 change.

Detail includes a bounded member list and an optional history page. Public history
cursor behavior, cross-scope request-key collision responses and raw decision-row
identifiers remain explicit independent-review questions. No acceptance criterion
is waived by documenting these questions. Omitted get remains raw inspection;
explicit get checks view eligibility and active status before exposing an original.
