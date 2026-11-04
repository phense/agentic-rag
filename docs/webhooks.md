---
id: PB07201
title: Operate scoped signed webhooks
type: task
doc_id: webhooks
readers: [installation-operator, authorized-writer]
status: draft
version: 0.6.29
depends_on: [central-service]
assets: []
summary: Deliver minimal committed change notices to an explicitly configured receiver and recover failed deliveries.
---

# PB07201: Operate scoped signed webhooks

## Identity and applicability

- Class: system playbook; owner: the selected installation's operator.
- Origin: [Issue 72](https://github.com/phense/agentic-rag/issues/72),
  [RAG-072 AC-001–008](specs/RAG-072-signed-webhooks/spec.md).
- Target: 0.6.29/schema038, upgraded from 0.6.28/schema037.
- Readiness deadline: before first capture enablement or receiver configuration.
- Last edited: 2026-11-04. This draft awaits the implemented command contracts,
  independent review and isolated receiver/upgrade rehearsal.

Use this procedure when an approved service needs notice of a committed change
without repeatedly searching the store. The sender posts a small signed event
after the database transaction commits. It does not send the memory body,
quotes, prompts or the audit summary. An authorized consumer uses the ordinary
read API if it needs the current content.

Capture starts disabled. Installing or upgrading this release does not create
a subscription, start a sender or contact an external receiver. Choose and
authorize the destination separately before enabling the feature.

## Terms

| Term | Meaning here |
|---|---|
| Event | An immutable notice of a committed resource change, identified by a UUID. |
| Subscription | An authorized destination and a filter for one exact scope and event kinds. |
| Delivery | One event's progress toward one subscription, including attempts. |
| Resource order | A numeric value used to reject older notices for the same resource. |
| Evidence fingerprint | An optional opaque version hash; it is not sortable. |
| Key generation | A subscription's signing-key revision; consumers coordinate rotation. |
| Dead letter | A delivery that exhausted its finite retry budget and needs an explicit decision. |
| Capture switch | The operator's persisted opt-in that controls new capture and sender attempts. |

Knowledge subscriptions select an exact domain and project. Job subscriptions
select an owned namespace and project with no domain; they accept only terminal
job kinds. A recoverable blocked job is not a failed ingestion. A source or
lifecycle notice does not expose another scope's dependent memories.

The sender may retry after the receiver accepted a request but before its
acknowledgement was recorded. Consumers must deduplicate event UUIDs and compare
resource order for the same resource. Delivery is at least once; there is no
global commit order or exactly-once guarantee for the consumer's own work.
Multiple notices from one transaction can share a correlation ID. A notice's
optional fingerprint describes its capture point, not later statements in that
transaction.

## Before starting

Use the intended installed executable and an existing local operator
configuration. Keep database credentials and signing files on that host. A
remote client configuration can manage only the subscriptions its authenticated
writer owns; it cannot enable capture or export signing material.

Define absolute installation paths in Bash:

```sh
RAG=/absolute/path/to/0.6.29/.venv/bin/rag
CFG=/absolute/path/to/server.toml
DIR=/absolute/private/webhook-upgrade
export AGENTIC_RAG_CONFIG="$CFG"
umask 077
```

Before maintenance, record every writer's exact stop/start procedure and prior
running state, including API workers, hooks, local MCP processes and scheduled
work. Use the installation's approved maintenance window and the
[central-service upgrade procedure](13-central-service.md#upgrade-the-local-store).
An unavailable receiver is handled by delivery retries; it is not a reason to
restore or overwrite canonical knowledge.

## A: Upgrade the selected store

1. With the new executable, inspect the source installation:

   ```sh
   "$RAG" service --config "$CFG" preflight --source-version 0.6.28
   ```

   Require `ready: true` and the intended database identity. Stop on a schema,
   privilege or identity mismatch. Do not enable capture during the upgrade.

2. Pause the recorded writers and apply the additive migration with a new dump:

   ```sh
   mkdir -p "$DIR"
   "$RAG" service --config "$CFG" upgrade --source-version 0.6.28 \
     --dump "$DIR/pre-webhooks.dump" --apply --writers-stopped
   ```

   Require a verified independent restore and unchanged original data. An
   existing dump is not overwritten; keep it and choose a new filename. An
   atomically failed migration leaves the source schema and data intact. Keep
   writers paused while diagnosing the reported failure; do not delete a schema
   marker to force a retry.

3. Inspect the target and make a separately verified target backup:

   ```sh
   "$RAG" service --config "$CFG" inventory --source-version 0.6.29 \
     --output "$DIR/post-webhooks-inventory.json"
   "$RAG" service --config "$CFG" verified-backup --source-version 0.6.29 \
     --output "$DIR/with-webhooks.dump"
   ```

   Require schema038, unchanged original rows/ACLs/owners/sequences and
   `restore_verified: true`. If either check fails, keep writers paused and
   preserve both outputs and backups. Restore only into a separate verification
   target; a production cutover needs its own explicit decision.

For a deployment owner without extension-creation rights, prepare the empty
verification template from
[restore-verification privileges](15-dashboard.md#restore-verification-privileges)
before A2. Add `--verification-template TEMPLATE` to A2's upgrade and A3's
`verified-backup`. The template requires `vector` in `public` and the documented
preload. Do not add that option to `inventory`.

Resume the recorded writers only after the target checks succeed. Keep capture
disabled until receiver configuration, signing and the remaining procedure have
been reviewed and rehearsed. Keep pre-upgrade code and both backup manifests.

## B: Configure and prove one destination

1. As the sender's service account, create a private directory outside every
   Git checkout and generate its root signing key:

   ```sh
   KEYDIR=/absolute/private/webhook-signing
   mkdir -m 700 "$KEYDIR"
   "$RAG" webhooks key-init --output "$KEYDIR/root.key"
   ```

   Require `created: true`. The file is 32 random bytes, mode 0600, and is never
   overwritten. Back it up through the installation's private secret-backup
   procedure. Losing it prevents verification of subsequent attempts; replacing
   it changes every subscription's key identity.

2. Add the following to the selected server/operator configuration:

   ```toml
   [webhooks]
   key_file = "/absolute/private/webhook-signing/root.key"
   ```

   Public receivers require HTTPS with a valid certificate. A private HTTPS
   receiver additionally requires an exact normalized origin and its approved
   address range, for example:

   ```toml
   private_origins = { "https://receiver.example:8443" = ["10.20.30.40/32"] }
   ```

   Replace these declared inputs with the approved receiver's actual values.
   The operator authorizes this exception, not the subscribing client. Redirects,
   URL credentials, query strings and metadata/link-local addresses are rejected.
   Every resolved address must pass the policy; the socket uses the validated
   address while TLS authenticates the original hostname. HTTP is available only
   for an explicitly allowlisted loopback rehearsal with `test_http = true`.

3. Using the owning writer's local or client configuration, subscribe to one
   exact knowledge scope:

   ```sh
   "$RAG" webhooks subscribe --endpoint https://receiver.example:8443/events \
     --project global --domain general --kind memory.created \
     --kind claim.reviewed --idempotency-key APPROVED_UUID
   ```

   Generate and retain one UUID before this command; replace `APPROVED_UUID` with
   it. Repeating the same request and UUID returns the same subscription; changing
   that request requires a new UUID. Record the returned `id`, `revision` and
   `generation` without signing material. For owned ingestion jobs, replace
   `--domain general` with `--jobs` and select only `job.applied`, `job.error` or
   `job.cancelled`. Use the actual absolute project path instead of `global` when
   appropriate. Wildcard scopes are unavailable. An authorization error requires
   correcting that writer's enrollment, not switching to an unrestricted account.

4. With the local operator configuration, export this subscription's key:

   ```sh
   SUB=RETURNED_SUBSCRIPTION_UUID
   "$RAG" webhooks key-export "$SUB" --output "$KEYDIR/receiver-generation-1.json"
   ```

   Require `created: true` and deliver this file to the intended receiver through
   an approved private channel. Never paste `key_hex` into logs, an issue or a
   command line. The receiver must select the exported `key_id`, authenticate
   the exact received bytes and reject stale timestamps before doing any work.

5. After configuring that receiver, enable capture with the local operator
   configuration:

   ```sh
   "$RAG" webhooks capture on
   ```

   Require `capture_enabled: true`. This is one database-wide switch: it affects
   all subscriptions. No sender starts automatically. Changes made while it was
   off have no event and cannot be recreated through delivery replay.

6. With the owning writer configuration, queue a minimal test notice using the
   latest returned revision, then run one attempt with the operator configuration:

   ```sh
   "$RAG" webhooks test "$SUB" --expected-revision 1
   "$RAG" webhooks sender --limit 1
   "$RAG" webhooks status "$SUB"
   ```

   Require `outcome: acknowledged`, `completed: true` and an acknowledged delivery
   in status. Also require the receiver's signature check, stable event UUID and
   expected exact scope. These commands use whichever configuration
   `AGENTIC_RAG_CONFIG` names: switch it explicitly between writer and operator
   when they differ. A pending handle is not a successful delivery. Keep the
   switch off and stop this procedure if the receiver, authority or identity is
   wrong; retain the sanitized status and deployment revision for diagnosis.

## C: Verify and consume notices

For a runnable local rehearsal, use the installed Python and this checkout's
[`scripts/examples/webhook_receiver.py`](../scripts/examples/webhook_receiver.py):

```sh
/absolute/path/to/0.6.29/.venv/bin/python scripts/examples/webhook_receiver.py \
  --key-file "$KEYDIR/receiver-generation-1.json" \
  --database "$KEYDIR/receiver.sqlite" --port 18080
```

It listens only on `127.0.0.1:18080/events`. For this isolated rehearsal, subscribe
to that HTTP URL and configure `test_http = true` plus
`private_origins = { "http://127.0.0.1:18080" = ["127.0.0.1/32"] }`.
The private SQLite file records only IDs, body hashes and resource order; duplicates
are acknowledged without processing again, and older versions are retained as
seen without replacing the latest version. Restart it with the same database to
retain that history. Repeated `--key-file` options support a rotation overlap.
Stop it with Ctrl-C. This example has no downstream side effects or automatic
retention; production consumers must bound their own durable deduplication store.

The headers are `X-RAG-Timestamp`, `X-RAG-Key-Id` and
`X-RAG-Signature: v1=HEX`. The HMAC-SHA256 input is the timestamp's ASCII bytes,
a literal period and the **unmodified HTTP body**. A retry keeps the event UUID
and body but gets a fresh timestamp and may use the current key generation.

The receiver can use the installed verifier as follows. Supply `raw_body` and
`headers` from its HTTP framework, without decoding and re-encoding the body:

```python
import json
from pathlib import Path
from agentic_rag.webhook_delivery import verify_signature

secret = json.loads(Path("/private/receiver-generation-1.json").read_text())
valid = headers.get("X-RAG-Key-Id") == secret["key_id"] and verify_signature(
    bytes.fromhex(secret["key_hex"]), raw_body, headers, window=300,
)
if not valid:
    raise ValueError("invalid webhook signature or timestamp")
event = json.loads(raw_body)
```

Keep the receiver clock synchronized. Persist its accepted event IDs and local
work atomically before returning 2xx. A valid signature alone does not make a
duplicate safe to execute twice. Treat lower resource versions as older notices,
not a request to revert state. Fetch current knowledge through that consumer's
ordinary authorized read connection; a notice is not a new permission grant.

Knowledge kinds are `memory.created`, `memory.changed`, `memory.archived`,
`claim.reviewed`, `source.changed`, `lifecycle.applied`, `lifecycle.recorded`,
`lifecycle.corrected`, `edge.supersedes` and `edge.duplicate`. Job kinds are listed
in B3. `test` is created only by the explicit test operation. Event version 1
contains IDs, kind, resource order, timestamp, exact scope, correlation ID and
bounded state; it excludes canonical text and credentials.

## D: Retry, rotate and stop

1. Run the explicit sender on the installation's approved schedule:

   ```sh
   "$RAG" webhooks sender --limit 100
   ```

   Each invocation attempts at most the requested number, 1–100, and stops when
   no delivery is due. A network attempt has a 10-second deadline. An attempt is
   charged before opening a socket, so a crashed process cannot retry forever.
   A 30-second lease fences its completion. There are six attempts, with waits
   of 5, 30, 120, 600 and 1800 seconds before attempts 2–6. Non-2xx, redirects,
   timeouts and destination-policy failures never count as acknowledgements.

2. For an outage, inspect `webhooks status "$SUB"`. Correct the receiver or
   approved configuration, then allow due retries. For a dead or otherwise
   terminal delivery, explicitly replay its retained ID with the latest
   subscription revision:

   ```sh
   "$RAG" webhooks replay "$SUB" --expected-revision CURRENT_REVISION \
     --delivery-id RETAINED_DELIVERY_UUID
   ```

   Replay keeps the event identity and resets its attempt budget. It is bounded
   to eight explicit replays per delivery and rechecks current authority before
   sending. A revoked credential is not repaired by replay: enroll an authorized
   consumer through the ordinary credential process. Do not change database rows
   to bypass revocation. Never restore canonical knowledge to fix an endpoint.

3. For key rotation, pause the external sender schedule, run
   `webhooks rotate "$SUB" --expected-revision CURRENT_REVISION`, then export the
   new generation to a **new** private filename with `key-export`. Configure the
   receiver to accept that new `key_id` before resuming the sender. Keep its old
   key for the bounded in-flight overlap, then retire it through the receiver's
   secret policy. Check the returned revision after every mutation; a conflict
   requires fetching status, not guessing a revision. There are at most 32 key
   generations and 1024 subscription revisions.

4. To stop one destination, run
   `webhooks disable "$SUB" --expected-revision CURRENT_REVISION`. Pending,
   retrying and leased deliveries become disabled. To stop all new capture and
   future sender attempts, run `webhooks capture off` as operator. A request
   already handed to the network cannot be recalled. Retained deliveries remain
   available; re-enabling capture is an explicit operator action.

5. At `webhook_capacity`, turn capture off to restore ordinary writes, pause
   the sender schedule and preserve `webhooks status "$SUB"` output. Storage is
   finite: 32 subscriptions per namespace, 10000 retained subscriptions/events/
   deliveries and 32 MiB of serialized bodies. The originating write rolls back
   when it cannot retain its notice; confirm that write's outcome before retry.
   Inspect each retained delivery and decide which terminal notices may be
   abandoned. Never reactivate a revoked credential to free capacity.

6. For each explicitly selected terminal delivery, run this **local operator**
   command, replacing the ID and observed state:

   ```sh
   "$RAG" webhooks cancel RETAINED_DELIVERY_UUID --expected-state revoked
   "$RAG" webhooks status "$SUB"
   ```

   Accepted prior states are `dead`, `revoked` or `disabled`. For live work,
   first disable its subscription through D4; do not cancel a pending, retrying
   or leased delivery directly. Expect `cancelled` in status and a committed
   `webhook.cancel` audit entry. A wrong state or ID must fail without changing
   other deliveries. Preserve that failure and fetch status again; do not guess
   IDs. Repeating the same cancellation must not restart retention. Knowledge
   and the original credential binding stay unchanged.

7. Wait seven full days after cancellation, then preserve the required evidence
   and run `webhooks prune` as operator. Prune permanently deletes eligible
   acknowledged/cancelled delivery metadata and unreferenced old events. Check
   its reported delivery/event counts against the selected retained records;
   cancellation alone does not immediately free capacity. Pending, retrying,
   leased and unselected dead letters remain. If capacity is still occupied,
   keep capture off and inspect the remaining records; do not edit private
   tables or reduce retention. Disabling does not release subscription quota.
   Once capacity is available, explicitly enable capture and run B6's test plus
   the sender. Require an acknowledged notice before resuming its schedule.
   If that check fails, turn capture off and follow the reported failure branch.

## E: Runtime rollback

Turn capture off, stop the external sender schedule and verify no sender remains
before restoring the previously verified 0.6.28 runtime. Retain schema038,
subscriptions and delivery history; do not drop the new tables, delete a migration
marker or regenerate a signing root. The old runtime does not manage these
tables, but the installed capture triggers remain disabled. Check ordinary
scoped reads and writes through the restored runtime before resuming its recorded
writers. If those checks fail, keep writers paused, retain both backup manifests
and restore into a separate verification target for an explicit cutover decision.
This runtime rollback does not undo knowledge written after the upgrade.
