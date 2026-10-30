# Dashboard HTTP contract (0.6.12)

All paths below have prefix `/dashboard/api/`. GET responses are private/no-store.
Authentication is a human service session in `__Host-rag_dashboard` on HTTPS,
HttpOnly/Secure/SameSiteStrict/Path=/. Loopback HTTP uses a different cookie.
Bearer headers never log into this API; these cookies never authenticate `/v1/`
or MCP. Every POST requires exact same-origin `Origin`, `x-rag-browser:1`, JSON,
and an authenticated session's `x-rag-csrf` except login/bootstrap.

| Route | Method | Authorization | Input / result |
|---|---|---|---|
| bootstrap | GET | Public | Availability boolean only |
| bootstrap | POST | Operator's private one-time token, empty policy | token,username,password → one admin;409 race/already initialized |
| login | POST | Password | username,password → protected cookie,expiry; no token body |
| me | GET | Session | Current user,admin,readonly,permissions,CSRF |
| logout | POST | Session+CSRF | Revoke exact session, clear cookie |
| overview | GET | Session | RLS memories/pending reviews/domains |
| memories | GET | Session | domain/project/pending,limit1–50,offset0–10000 → bounded previews+scoped total |
| tools | POST | Session+CSRF | memory_get/search/review_claim plus existing queue envelope → request handle |
| requests/{id} | GET | Exact session authority | Existing queue status/result; no foreign handles |
| requests/{id}/cancel | POST | Exact session authority+CSRF | Existing bounded cancellation |
| admin | GET | Human admin | File-owned principals, bounded last-seen/version/capability metadata, operational aggregate health and recent admin changes |
| policy | GET | Human admin | Safe IDs/prefixes/scopes, exact revision; no verifiers |
| policy/preview | POST | Human admin+CSRF | revision,change → validated summary, no file write |
| policy/apply | POST | Human admin+CSRF | revision,change,operation_id(UUID) → new revision, raw generated secret once |
| setup | GET/POST | Human admin(+CSRF) | Persisted mode/checks/discovery; POST selects one of four explicit paths |
| setup/check | POST | Human admin+CSRF | check database/permissions/compatibility/embedding/provider → saved safe state/code/time/configuration fingerprint |
| setup/complete | POST | Human admin+CSRF | All current checks verified; idempotent completion |
| setup/export | GET | Human admin | Reviewed instruction plan/template, no credentials or automatic apply |

Policy change `kind=user|machine` uses stable `id`, validated `fields`, optional
human password or machine owner `user`. Allowed fields:label,enabled,read_domains,
write_domains,read_projects,write_projects,session_teams; user alsoadmin. `rotate`
and`revoke` use machine`id` and`key_id`. Rotation replaces only that credential ID;
other keys persist. Prevent removing the last enabled password-capable admin.
Preserve unknown/commented file-owned configuration through TOML round-trip.

First apply persists a nonsecret prepared audit (actor,kind,subject,old/new digests),
atomically replaces/fsyncs the0600 policy, then marks it applied. Before another
apply, prepared rows reconcile only against known old/new file digests; unknown
operator drift returns503/policy_recovery_required. An operation ID replay never
returns its old secret. Audit capacity10000 rows blocks further administrative
writes until an operator reviews archival; no silent audit eviction.

Browser body64KiB/5s, four independent active slots, five login/bootstrap attempts
per minute/transport peer with1024 bounded buckets. Knowledge listing projects
previews in SQL before transfer. Other tools reuse two foreground consumers,
128 active queue slots, TTL and result limits from0.6.11. One low-priority explicit
model check at a time: embedding timeout10s, provider timeout20s per process (Codex preflight+call up to40s). Compatibility discovery uses the configured service URL/private token,2s HTTP bound, no spool, actual authenticated protocol1/queued_tools1 response. Checks bind target and credential revision; no configured target remains incomplete. Existing agent
work can defer probes with429. Heartbeats are per principal, throttled60s, bounded
configured IDs; online means activity within300s and does not mean a live socket.

Errors contain stable codes only.401 expiry/revocation,403 scope/origin/CSRF,
409 stale revision/setup/conflict,413 input/result limit,429 bounded admission,
507 storage/audit limit,503 failed schema/recovery/availability. No CORS sharing,
iframe embedding, browser-persisted tokens or secrets in administrative audit.
