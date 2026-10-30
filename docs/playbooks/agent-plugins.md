---
title: Install or recover a native agentic-rag client
type: playbook
audience: administrators
version: 0.6.11
---

# PB06801: Install or recover a native agentic-rag client

## Identity and scope

- Class: system.
- Origin: Issue #68, FR01–09 in [the specification](../specs/6-10-agent-plugins/spec.md).
- Owner/audience: deployment administrator; agent user for status/cancel recovery.
- Target: 0.6.11/schema024; owned plugin directories and an explicitly enrolled client.
- Readiness deadline: before activating a new client or upgrading a central server.
- Last edited: 2026-10-30.
- Evidence: [review and rehearsal record](evidence/agent-plugins.md).

## When to use / when not to use

Use for packaging an existing Python installation, staged client/server updates,
or a tool that reports a waiting handle. Do not use it to import independent
stores, merge department permissions or cut over production writers. Those actions
retain the [6.0 deployment/upgrade gates](../verification/issue58-service.md).
An unavailable native model login blocks claims about that host's interactive UI;
it does not justify copying another department's credentials.

## Before starting

1. Choose an existing Python environment with agentic-rag0.6.11 and run
   `rag --help` and `rag plugin --help` in it.
2. Check the enrolled token's private permissions and intended domains/projects/
   teams with the administrator; do not print the token. Use the existing
   `rag service client-config` command for a remote or loopback server.
3. Choose a new owned package directory, host (`claude`, `codex`, `gemini`) and
   explicit absolute client config path. Keep config, credentials and spool
   outside the generated package.

Intentional parameters in examples: `/opt/rag-client/bin/python`,
`/home/agent/.agentic-rag/client.toml`, `/home/agent/plugins/agentic-rag`. Replace
them with this client's inspected paths. Authority covers only the chosen
package and explicitly selected host installation; existing foreign settings
and pending evidence remain outside that boundary.

## Decision paths and actions

| Step | Actor/target and action | Expected evidence | Failure/next step |
|---|---|---|---|
| P01 | Administrator previews package with the command below | `preview:true`, host and exact file paths; no files created | Resolve wrong paths/host before applying |
| P02 | Administrator repeats with `--apply` | Native manifest/hooks/MCP plus `.rag-package.json` ownership record | A foreign or modified file is a conflict: stop, inspect it, do not overwrite |
| P03 | Administrator runs `rag plugin doctor --host claude --destination /home/agent/plugins/agentic-rag` | `status:ok`; owned file hashes match | Stop activation on any conflict or missing file |
| P04 | Administrator activates the owned package through the host's native mechanism below | Host lists/discovers agentic-rag; fresh session reports authorized context or explicit waiting/offline state | Keep old integration until new one is verified; avoid enabling both capture paths |
| P05 | Agent invokes a read tool, then native manual compression or a controlled automatic boundary | Durable original source/checkpoint, correct continuation, source extraction status distinct from current knowledge | Retain original transcript and local spool on any missing capture/ACK; use recovery below |
| P06 | Administrator tests scoped main/read-only and foreign-department denial | Main tools behave within scope; RO has no mutation/cancel/capture; foreign data denied | Disable new integration and inspect policy; never broaden it to make a test pass |

Preview:

```sh
rag plugin install --host claude \
  --destination /home/agent/plugins/agentic-rag \
  --python /opt/rag-client/bin/python \
  --config /home/agent/.agentic-rag/client.toml
```

Use `--read-only` when packaging a read-only agent. Update with the same arguments
and `plugin update`; omitted wiring options retain the recorded paths and RO
choice. `plugin uninstall ... --apply` removes only unchanged owned package
files and retains the bounded previous generation in `.rag-package.json`.
Disable the package in the host before uninstalling its generated files. The
record is recovery evidence, not a copy of native user settings or source data.

Native activation:

- Claude: validate with `claude plugin validate /home/agent/plugins/agentic-rag`,
  then use `claude --plugin-dir /home/agent/plugins/agentic-rag` in an owned test
  workspace, or publish the package through the team's native marketplace.
- Codex: place the package in a local marketplace, add that marketplace with
  `codex plugin marketplace add /path/to/marketplace`, then
  `codex plugin add agentic-rag@marketplace-name`. Validate the actual installed
  CLI's `plugin --help`; keep the existing Codex installer as a fallback.
- Gemini: use `gemini extensions install /home/agent/plugins/agentic-rag`, review
  the host's trust prompt, then restart and inspect `gemini extensions list`.
  Do not enable automatic extension updates until the matching Python engine has
  passed the staged upgrade. agy uses `rag install --agy`, not this command.

## Interruption, recovery and rollback

| Observation | Safe action and result |
|---|---|
| `waiting:true,durable:true` | Retain `request_id`; call `memory_request_status`. Completed returns the original result; pending/running means keep waiting within a finite tool deadline. Do not submit a new envelope. |
| `local.<uuid>,durable:false` or lost ACK | Keep the local outbox. The same status tool reconciles its unchanged envelope; cancellation first reconciles whether the server accepted it. |
|429/507 before acceptance | Preserve input, retry with bounded backoff after pressure clears. Poll no faster than once per second per waiting tool; share the uploader's12/s allowance across sessions. |
| Cancel/expiry | Cancel an owned handle once; repeating it does not append audit rows. `completed` means effects already committed. `expired`/`result_expired` means the finite result window ended; inspect canonical state before intentionally issuing a new mutation. |
| Credential rotation/logout/scope change | Old authority cannot execute or release results. Retain the old partition as recovery evidence; enroll a fresh profile explicitly. Never retimestamp/rekey an ambiguous mutation automatically. |
| Full local spool or malformed/rewritten recording | Retain host recording and pending spool. Drain existing source work with `rag service spool --flush`; repair or recover source input explicitly. Removing the plugin does not make that evidence safe to delete. |
| Interrupted package update | Keep `.rag-package.json` and its bounded recovery generation. Preview `rag plugin recover --host claude --destination /home/agent/plugins/agentic-rag`, then repeat with `--apply` to restore the recorded owned generation. A mismatch is a stop condition, not permission to overwrite foreign content. |

Before a server upgrade, take `rag service verified-backup` with the inspected
source version and perform the existing verified upgrade/strict restore rehearsal
on an owned copy. Schema023→024 is additive. Stop writers only within the
explicitly approved deployment window. Upgrade server first, verify synchronous
compatibility/queue capabilities, then update clients and native packages.
For code rollback leave024 installed, disable new client queue use by returning
to the prior connector/package, and retain pending handles until reconciled.
Do not drop tables or replay unconfirmed mutations during rollback.

## Escalation and preserved evidence

Escalate unknown native event formats, failed original-row/ACL comparisons,
request effects without a completed receipt, foreign data visibility or a
package ownership conflict to the maintainer. Preserve version, event names,
request/source IDs, stable error codes, timing, file hashes and owned test logs.
Keep prompts, recordings, tokens and unrestricted results out of public issues.

## Completion and maintenance

The operation completes when the host discovers the package, current knowledge
and compaction continuation work within its authenticated scope, accepted input
survives restart/replay and the applicable native observation is recorded.
Disable the owned test installation after rehearsal. Retain knowledge, pending
sources/requests and recovery records. Reassess this playbook when host events,
plugin schema, request limits, authentication or spool ownership changes.

Sources: [runtime/limits/matrix](../14-agent-plugins.md),
[request engine](../../agentic_rag/service/requests.py),
[package operator](../../agentic_rag/plugins/package.py).
