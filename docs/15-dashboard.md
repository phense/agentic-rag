---
id: C-059
title: Set up and operate the dashboard
type: task
doc_id: dashboard-operations
readers: [operator]
status: reviewed
version: 0.6.12
depends_on: [C-058]
assets: [A05901]
last_reviewed: 2026-10-30
summary: Bootstrap access, resume setup and manage file-owned client permissions safely.
---

# Set up and operate the dashboard

Use the dashboard to inspect your service, enroll clients and browse permitted
knowledge. It runs in the existing Python API. Browser clients need no database,
embedding model or agent CLI. Local CLI/stdio operation remains available without
a dashboard account.

PB-059-01 and PB-059-02 below are system playbooks for the Linux operator, owned
by the repository maintainer. Origin:[Issue59](https://github.com/phense/agentic-rag/issues/59),
requirements AC001–009. Last edited 2026-10-30. Target 0.6.12/schema 025.
Content review and rehearsals are recorded separately in the
[verification record](verification/issue59-dashboard.md).

## Before starting

Use Python 3.13+, PostgreSQL 17 with pgvector, current 0.6.12 code and an initialized
schema 025 store. For an existing installation, take a verified backup and use
[PB-058-01](13-central-service.md#pb-058-01-install-upgrade-and-enroll) to upgrade
before starting the new API. Supported source prefixes 018–024 remain additive;
025 adds dashboard control tables. An older-schema API refuses to start.

The browser assistant starts after database prerequisites. For a new empty local
installation, finish the repository's `rag init` procedure first. For a populated
store, use verified upgrade tooling; never reinitialize it to obtain a web page.
The assistant validates and records setup progress. Migration, restore, data
movement and service restarts remain explicit operator actions.

Choose an actual private configuration file, owner-only policy path, one-time
credential file and HTTPS service origin. The examples use `/owned/` as an
intentional operator-chosen directory, not an existing deployment. Run the API
as the policy's file owner. Keep its directory private; applying policy changes
requires permission to atomically replace the file in that directory. Configure
only the intended hosts with `--allowed-host`. Use private HTTPS for network
access, such as your Tailscale-served origin; HTTP is accepted only from a real
loopback peer.

## Restore-verification privileges

Verified upgrades restore a backup into a randomly named disposable database
before touching the source schema. The operator needs permission to create that
database and restore every original owner and privilege. The API service account
does not need those administrative permissions during normal operation.

A restricted database owner can use an explicitly prepared, empty template that
already contains the same `vector` extension version in `public`:

```sh
rag service --config /owned/server.toml upgrade --source-version 0.6.11 \
  --dump /owned/before-dashboard.dump --apply --writers-stopped \
  --verification-template operator_prepared_vector_template
```

Have the database administrator prepare and own-review that template first. It
must contain no application tables. The command copies it into its own disposable
database, validates the extension version, and restores all application objects,
rows and privileges. It leaves the template unchanged. Only the already installed
`vector` extension declaration/comment is omitted from the restore list.

A template does not authorize restoration of another role's historical default
privileges. For those populated stores, use the authorized database administrator
for the verified upgrade. Review ownership of newly created control tables before
starting the API as its normal owner. Preserve original object ownership and
permissions. Do not grant superuser to the runtime service or remove privilege
entries from the backup to make verification pass. A failed restore leaves the
source schema untouched; inspect the error and use a new dump path for retry.

## PB-059-01: Bootstrap and resume setup

Use this playbook for a new policy with no users or machines. Existing policies
use their configured administrator login; a bootstrap token cannot bypass them.
Bootstrap grants administrative control with no automatic knowledge scope.

### Arm first access

1. Generate a private token file and an empty policy, only if that policy is absent:

   ```sh
   rag service bootstrap --auth-file /owned/principals.toml \
     --output /owned/first-admin.key
   ```
2. Start the API with the current server configuration:

   ```sh
   rag service --config /owned/server.toml serve \
     --auth-file /owned/principals.toml --allowed-host rag.example.internal
   ```
3. Open your configured private origin at `/dashboard/`.
4. Enter the token from the private file in **One-time bootstrap token**.
5. Create the first administrator with a new username and a password of at least 12 characters.

Expected: **Administrator created. Sign in to continue.** Subsequent first-admin
claims are rejected. The CLI prints file paths, never the token. A concurrent
claim returns a conflict; inspect the policy and sign in with the successfully
created administrator. A failed/interrupted arming never overwrites an existing
token/marker file; its owner must inspect those private artifacts before retry.

### Validate the chosen installation

1. Sign in with the administrator you created or an existing configured administrator.
2. Open **Setup assistant** in the sidebar.
3. Select **New local installation**, **Upgrade an existing local store**,
   **Central server setup**, or **Connect a client**.
4. Configure an operator-owned `service.url` and protected `service.token_file` for the compatibility target in the server configuration. For server/local validation, point them at this private API and use an explicitly enrolled read-only credential. For client validation, use the actual intended server and client credential. Restart the owned API after configuration changes.
5. Run each check under **Validate this configuration**.
6. Select **Export setup plan** to review the operator instructions and placeholders.

Expected: database discovery identifies existing knowledge; **New local
installation** is disabled for populated stores. Checks retain safe result codes
across a service restart. **Embedding access** makes one synthetic local call;
**Provider access** makes one synthetic provider call using the service account.
They yield to foreground work and may return busy. No stored knowledge is sent
by these checks. Provider checks allow20 seconds per process; Codex may use a login preflight and a call, up to40 seconds total. Compatibility makes a real authenticated2-second discovery request; without a reachable configured target and valid credential it cannot turn green. Browser input cannot select arbitrary URLs or supply probe secrets. Treat unavailable or stale checks as incomplete.

### Finish and verify

1. Apply any required file or verified migration changes through the existing operator workflow.
2. Re-run checks invalidated by configuration changes.
3. Select **Complete setup** when every required check is verified.
4. Reload the page and reopen **Setup assistant**.

Expected: **Setup complete** persists. Repeating completion is idempotent.
Completion does not deploy clients, restart services or migrate data. An
interrupted setup resumes from its saved mode/checks. Client setup exports a
protocol1/queued-tools plan with placeholders; provision its private credential
through PB-059-02 and the existing client installer.

## PB-059-02: Enroll and change client access

Use this playbook for a human administrator with a writable owner-only policy.
The policy file is the sole access authority; runtime/model settings remain
read-only in the dashboard. An external file edit invalidates an older preview.
Preserve a private current policy backup before consequential scope changes.
An old key cannot be recovered after rotation; recovery uses a new key.

### Enroll a client

1. Open **Clients & access** and add a service owner with **Add user**, if needed.
2. Select **Enroll a VM** and enter its stable ID, owner user and explicit readable/writable domains and projects.
3. Select **Preview change** and inspect the exact scope values.
4. Select **Apply policy change**, then return to the client and select **Manage**.
5. Enter a unique **New key ID** and select **Generate credential**.

Expected: the enrolled VM appears with its label and permissions. A VM's effective
rights are the intersection of its scopes and its owner's scopes. A user without
a password can own machines without gaining browser login. Administrator status
does not grant cross-department knowledge rights. Shared session-log teams widen
read visibility without merging uploader cursors or write/cancellation authority.

### Store and verify the credential

1. Preview the credential generation and select **Apply policy change**.
2. Save the displayed credential immediately in the client's private token file.
3. Select **I saved it** to clear the credential from the page.
4. Connect the client through the existing [client setup](13-central-service.md).
5. Check its domain/project access and the separate RO/RW interfaces.

Expected: the raw credential appears once; later pages show safe key IDs/prefixes.
A lost response requires another rotation. Never put a credential in a URL,
shared screenshot, source-controlled file or browser persistent storage.

### Rotate, revoke or recover

1. Open the named client's **Manage** page and select **Rotate** or **Revoke** for the exact key ID.
2. Review the affected ID and apply the policy change explicitly.
3. Verify that the old credential is rejected and, for rotation, install the newly shown credential on its client.
4. Inspect **Recent administrative changes** for the recorded actor, subject and outcome.

Expected: new requests and queued work recheck the original credential revision.
Rotating one key leaves other IDs enabled. Disabling the last password-capable
administrator is refused. **Freshness** records last authenticated activity;
**stale** clients remain enabled until an administrator changes access.

External file editors must take the same `<policy-file>.dashboard.lock` lock or pause the dashboard writer before changing the policy. Revision checks detect completed intervening edits; they cannot serialize an editor that ignores the ownership lock.

If an apply response is lost, reload the policy instead of blindly replaying it.
The audit is prepared before atomic file replacement. A later apply reconciles
an interrupted change against its known old/new file digest. Unknown external
drift returns `policy_recovery_required`: stop dashboard changes, preserve the
private policy and its prepared audit row, and ask the file/database owner to
reconcile which revision was applied. Do not delete the journal or reset the
store. If credentials were affected, issue a fresh rotation after recovery.

## Check that it worked

Sign in as a restricted knowledge user. **Knowledge** shows only their allowed
domains/projects, including counts and previews. Open a memory to inspect
**Original sources & review**. A read-only account has no review mutation controls
or administrative navigation. Sign-out/expiry returns to the login form.

For the full contract, limits and error meanings, use the
[dashboard reference](dashboard-reference.md). Production readiness requires the
named deployment's own TLS, account, backup and access verification after code
review and copy rehearsal; a merged PR alone does not perform that rollout.

## Request tracing after0.6.12

In0.6.13, select **Request tracing** in the sidebar to inspect authorized request
metadata and current job outcomes. Follow [the tracing operations guide](16-request-tracing.md)
for its schema026 upgrade, permissions, bounded exports and retention.
