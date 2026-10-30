# Agent plugin operations documentation

Depth: large set, three focused artifacts. Reader: administrator installing an
existing Python engine and an AI agent user recovering a waiting handle.
Version 0.6.11/schema024. Owner: coordinator; Issue #68/S06803. Apply authoring,
human-prose-drafting, terminology-guard and playbook authoring/review.

| Artifact | Type | Purpose | State |
|---|---|---|---|
| docs/14-agent-plugins.md | reference | Host/event/observation matrix, queue contract, resource limits | reviewed |
| docs/playbooks/agent-plugins.md | system playbook | PB06801 install/update/recovery, compatibility and rollout | reviewed |
| docs/playbooks/evidence/agent-plugins.md | evidence | Exact observations, tests and unproved rollout gates | reviewed; measured boundaries retained |

Terms: foreground request = current tool invocation; source window = original
redacted transcript evidence; receipt = source acceptance; request handle =
foreground status/result ID; handoff = advisory continuation checkpoint;
owner = authenticated uploader; team = explicit shared history policy.

Assets: one Mermaid sequence in docs/uml/agent-plugins.md; no screenshots needed
for the CLI operation. Review source/command/link accuracy and claim strength.

Set review: [review.md](review.md). Native authenticated UI/production readiness
remains separate from documentation acceptance.
