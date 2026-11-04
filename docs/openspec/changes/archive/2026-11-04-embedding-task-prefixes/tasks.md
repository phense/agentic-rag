# Tasks: Explicit embedding task prefixes

- [x] Freeze and run failing boundary tests before runtime changes.
- [x] Add immutable prefix options, role routing and honest inspection bounds.
- [x] Prove build/query routing and failed-role activation leaves selection intact.
- [x] Update PB061-OPS configuration and config-aware rollback instructions.
- [x] Run affected provider and existing-installation checks; independently review.

Verification: 168 focused provider/benchmark/release tests passed, including
populated local/central upgrades. Full suite: 2926 passed, 12 skipped, one known
warning. Independent bounded reviews: no Critical, High or Medium findings;
non-blocking follow-ups are tracked in Issue #75 (LOW116, LOW117 and LOW118).
The populated BGE/Nano exact-vector rehearsal preserves 326 original rows across
55 tables and exercises interrupted builds, activation failure and rollback.
It does not establish live Jina endpoint parity or production adoption.
