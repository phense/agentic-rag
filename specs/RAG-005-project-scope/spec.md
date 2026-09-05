# Feature Specification: Consistent project scope

## Stable work ID
- Feature ID: RAG-005
- Source request: implement next open issue, GitHub #5 / BACKLOG 4.3.
- Status: accepted for implementation under the user's end-to-end instruction.

## User scenarios
- US-001 (P1): Search within one project without receiving conflicting project B facts.
- US-002 (P1): Automatic recall and startup context include only applicable project/parent pins and permitted global knowledge.
- US-003 (P1): Curation cannot collapse or refute facts across project boundaries.
- US-004 (P1): Operators retain deliberate cross-project browsing and can inspect ambiguous legacy scope.

## Acceptance criteria
- AC-001: Identical error signatures in A/B and explicit global facts: project A search and recall return only A/global before rank/candidate limits, independently of domain.
- AC-002: B pins never inject into A; parent path and global pins apply to nested directories, symlinks and Git worktrees of A.
- AC-003: Exact/near duplicates and contradiction review require equal known scope; unknown facts are not automatically merged/refuted. Scoped graph traversal cannot transit through B to reach A.
- AC-004: Explicit global-only/all searches work; omitted project on existing manual APIs preserves unscoped browsing. Automatic hooks never treat missing provenance as global.
- AC-005: Migration retains source metadata and pin scopes, reports ambiguous/missing labels, and never invents global applicability. New writes share the audited gateway.
- AC-006: Synthetic scope fixtures, real SQL/role tests, CLI/MCP contracts and pre-limit adversarial candidates establish behavior without paid model calls.

## Functional requirements
- FR-001: Keep topic domains separate from canonical project identity and global/unknown applicability.
- FR-002: Resolve existing symlinks, normalize absolute paths and identify linked Git worktrees with their primary project. Paths outside Git are directory anchors; relocation/unknown remote filesystem identities require explicit repair.
- FR-003: Use the same policy for search, signal recall, startup document assembly and optional graph expansion. Existing explicit get/path/timeline browsing remains available; no tenant authorization claim.
- FR-004: Global applicability must be explicit. Ambiguous legacy rows remain unknown and inspectable.

## Interface contracts
| Contract | Inputs | Output/invariant |
|---|---|---|
| Selection | optional project, scope=project/global/all | known projects plus global, global only, or unrestricted; invalid combinations reject |
| Write | optional project/scope, legacy provenance.project | canonical scope independent of domain; update without scope preserves prior scope |
| Pins | user-owned global/domain/absolute-path scope | original scope/body retained; normalized applicability used for matching |
| Review | existing review report | unknown/ambiguous scope inventory, no automatic global promotion |

## Compatibility boundaries and assumptions
- Existing unscoped explicit manual search/get/graph calls stay cross-project; supplying project opts into isolation. Hooks always choose a scoped selection.
- Preserve one canonical database, writer/reader privilege boundary, original provenance, pin ownership, audit gateway and both providers.
- Profiles do not exist yet: startup project assembly is covered; future profile code must use this selector.
- Additive migration; backup before live application. Older code rollback cannot preserve isolation guarantees and must not run curation after rollback.
- No historical extraction backfill or paid evaluation is part of this issue.

## Success measures
All six acceptance criteria pass observable regressions; existing non-scope contracts remain valid; no unresolved material policy decision.
