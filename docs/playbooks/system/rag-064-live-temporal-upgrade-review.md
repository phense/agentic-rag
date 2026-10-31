# PB-064-LIVE: Review and execution evidence

## Scope

- Playbook: [rag-064-live-temporal-upgrade.md](rag-064-live-temporal-upgrade.md), SHA256 `91545f142f022b42b8819fd21c9b230516711e9e1ad1f436c5a2f7c2be93a4e3`.
- DBA driver: [live-upgrade.py.txt](../../verification/issue64/live-upgrade.py.txt), SHA256 `8f1a200cb01a4dba331d2f7b1ef247a3e6ced3bb53e3d57ae2e38b5302eb9a63`.
- Application: PR87 `e51003a`;0.6.17/schema029. Source VM:0.6.15/schema028, two existing stores and their historical owners.
- Owning request: maintainer-authorized pre-merge Hetzner activation, T064-009/AC-007. Independent review and full-copy restore/migration/old-code recovery before live DDL; scoped HTTPS/service and backup verification before merge.

## Content review

- Independent reviewer: claude-opus-5-5/high, two bounded read-only reviews on2026-10-31. Reports: [initial](../../verification/issue64/live-upgrade-initial-review.txt), [correction review](../../verification/issue64/live-upgrade-fix-review.txt).
- Coordinator: inspected both reports against actual files/interfaces and live peer rules; implemented and checked their focused corrections. The final small L10 correction reuses the existing reviewed publisher without changing its implementation. Its real ownership/mode enforcement was first exercised using a synthetic producer/mocked validator (no database-restore claim), then verified again on the actual restore-verified0.6.17 package. The first actual run exposed a root0700 intermediate parent that blocked the postgres dump producer. Matching the existing backup layout (root:postgres0710 intermediate parent, root:root0700 final package and0600 files) corrected that safe abort.
- Content verdict after those corrections: Ready,0open Critical/High/Medium/Important. The independent correction review approves the unchanged driver; the coordinator separately reviewed the final L10 range and observed root0700/0600 enforcement.

| Finding | Severity | Evidence and correction | Disposition |
|---|---|---|---|
| LIVE-H1 | High | Reader login under OS postgres fails peer authentication; both old/new readers now connect as DBA and drop to rag_reader within the session | Independently resolved; real SET ROLE probe passes |
| LIVE-H2 | High | Literal spaced TOML replacement cannot match the actual TOML; original config is now unchanged and a validated owned clone name is passed via argv before connecting | Independently resolved |
| LIVE-M1 | Medium | Direct produce bypassed private root ownership and modes; final L10 uses umask0077, the existing locked publish() and explicit stat assertions | Coordinator recheck, real permission enforcement and actual restore-verified new backup pass |
| LIVE-L1 | Low | Conservative source/post-traffic comparisons can reject legitimate concurrent operational writes | Fail-closed behavior retained; documented and tracked as [LOW-037](https://github.com/phense/agentic-rag/issues/75#issuecomment-6543637328) |
| LIVE-L10 | Low | Fresh-package production could overlap the daily timer | Corrected by the same job lock and restarting the timer after completion |

## Rehearsal

- Status: passed for both complete populated-copy rehearsals and the authorized live operation.
- Last validated:2026-10-31, both rehearsal and live apply exits0, external TLS/REST/MCP/browser and new verified-backup checks passed.
- Owner/method: coordinator, existing verified_backup and fenced DBA migration driver; actual archived0.6.15 reads and new0.6.17 reads against restored copies. The user explicitly authorized this maintenance and activation.
- Snapshot backups: both independently restored and verified before copy migration;35tables each,299,517 canonical and300,955 dashboard rows. Counts include the snapshot's operational rows and may differ from final stopped-writer backups.
- Canonical copy:029 applied once, original rows/grants/owners/history preserved, empty retry; actual0.6.15 before/after and0.6.17 legacy reads equal,3hits; owned clone removed.
- Dashboard copy: same preservation/029/empty-retry/actual-old-and-new-read checks pass,3hits; owned clone removed. Canonical95.59s, dashboard96.95s.
- Untested: cross-host disaster recovery, live database restore/discard of post-backup writes, actual process-kill/fence retention and canonical worker activation. These are not claimed by copy restores or code-read rollback evidence.

## Acceptance and freshness

- Draft complete and independently reviewed with disclosed coordinator resolution of the final small correction.
- Both required copy rehearsals and live gates passed. Both APIs run0.6.17/schema029 with auto enabled/`Europe/Berlin`; service startup took300.92s from the maintenance start. Original35-table preservation passes in both stores at migration commit; post-traffic27original core tables and original owners/grants/history remain unchanged.
- Actual fresh package:39tables/299,538rows,1,100,256,758sealed bytes, restore verified, all published members root0600 and package root0700. The same-day0.6.15 daily package is retained separately; the existing daily service revalidated it and the timer is active/enabled.
- [Sanitized live results](../../verification/issue64/live-upgrade-result.json), [HTTPS](../../verification/issue64/live-http.json), [browser](../../verification/issue64/live-dashboard.json) and [first backup abort](../../verification/issue64/live-backup-first-failed.json) retain actual outcomes. No failed attempt is represented as a successful backup.
- The original two reports preserve their earlier blocked verdicts; the disposition table records later fixes without rewriting those reports.
- Next action: commit these observed results to PR87, synchronize its documentation to the VM and merge after checking the final branch/checks. Canonical worker adoption remains outside this operation.
