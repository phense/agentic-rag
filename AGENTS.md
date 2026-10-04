# Shared knowledge engine

This repository is the canonical memory and knowledge engine shared by Claude Code and Codex.
Read `README.md` and the relevant document under `docs/` before changing behavior.

## Invariants

- Preserve one PostgreSQL + pgvector store for all clients. Never fork data by agent provider.
- All writes pass through the audited gateway (`rag save` or `memory_save`); never hand-write rows,
  embeddings, deduplication state, or audit records.
- Keep both MCP privilege levels: `agentic-rag` for an authorized main session and
  `agentic-rag-ro` for read-only/subagent use.
- Claude and Codex adapters must remain additive and idempotent. Do not remove or overwrite another
  client's settings, hooks, or MCP configuration.
- Never expose database credentials or other secret values in logs, tests, documentation, or commits.

## Production compatibility and upgrades

agentic-rag is an actively used production system with multiple users and knowledge domains.
Every change must remain compatible with the running installation or provide a real, tested
upgrade path from that installation. A fresh-install test alone is insufficient.

- Before changing behavior, identify the supported source version and affected schema, stored
  data, configuration, CLI/MCP contracts, hooks, jobs, and client integrations. Preserve existing
  users, domains, access boundaries, pins, knowledge, checkpoints, and audit history.
- Prefer additive, backward-compatible changes. Account for active sessions, concurrent clients,
  queued work, and old/new client versions during an upgrade; document any required restart or
  maintenance window. Never silently reset, reinitialize, or discard production state.
- If compatibility cannot be preserved, deliver the upgrade path with the change: supported
  source/target versions, preflight checks, verified backup, exact migration and deployment order,
  safe retry/resume after interruption, post-upgrade checks, and rollback or tested recovery with
  explicit limits on downgrade and data loss. Preserve the audited write boundary.
- Verify affected existing-installation workflows. Rehearse migrations and recovery on an isolated
  representative multi-user, multi-domain installation before production rollout. Record commands,
  results, and remaining risks in the PR; a written plan without verification is insufficient.
- Do not merge a change that lacks compatibility evidence or its required verified upgrade path.
  Merge approval does not itself authorize production deployment, migration, or service interruption.

## GitHub Issues and pull requests

- GitHub Issues are the canonical source for open work. Keep the stable numbered IDs and Issue
  links in `BACKLOG.md` as a local index; maintain priorities, dependencies, blockers, and remaining
  acceptance criteria in the Issues. Check existing open and closed Issues before creating one.
- The maintainer authorizes agents to create Issues and pull requests autonomously and to push
  the branches needed for those PRs. Use English for repository artifacts and GitHub content.
- Keep the maintainer informed about scope, created Issue/PR links, verification, and material
  risks. Link implementation PRs to their Issues and distinguish code completion from live rollout.
- Before merging any PR, briefly ask the maintainer for approval of that specific PR and wait for
  an explicit answer. Do not merge or enable automatic merge based on Issue/PR creation permission,
  silence, or a general authorization. Reconfirm if the approved scope materially changes.
- Satisfy compatibility, upgrade, review, and verification requirements before requesting merge
  approval. Keep unresolved work open until its acceptance criteria and required rollout evidence
  are met; do not bypass the PR workflow with direct pushes to the default branch.

## Mandatory version bump and documentation for every PR

- Starting after the already prepared 0.6.0 release PR, every PR must increase the
  patch version by exactly `0.0.1` relative to its target branch at merge time.
  This applies to feature, fix, documentation-only and maintenance PRs. The next
  version after 0.6.0 is 0.6.1.
- Increase the minor or major version only on an explicit manual instruction from
  the maintainer. That instruction replaces the normal patch bump for the affected PR;
  never infer a minor or major bump from feature size or change type.
- Update `pyproject.toml`, the project's version in `uv.lock`, the README version
  badge and `CHANGELOG.md` together in that same PR. Keep current-version
  references consistent; preserve historical release and measurement versions.
- Include the relevant documentation update in every PR. Document the changed
  behavior, workflow or maintenance outcome, and any affected upgrade/recovery
  steps. A version-only change does not satisfy the documentation requirement.
- Before requesting merge approval, verify the version against the current target
  branch and check documentation consistency. Stacked PRs use consecutive patch
  versions; refresh the bump and documentation when their base changes.

## Code review and feature evidence

- Every code change requires an independent review of its complete bounded diff.
  Verify and fix findings, then repeat review until no Critical, High, or Medium bug
  remains. Bundle non-blocking Low bugs into a separate linked Issue; do not hide them.
- Implement numbered feature requests sequentially. After each feature, report two
  or three practical before/after examples with measured numerical evidence, source
  revisions, test commands, sample sizes, and remaining limits. Never invent gains.
- Trading is an authorized read-only measurement workload. Keep destructive tests,
  migrations, interruption and restore rehearsals on isolated representative copies.
  Keep private content and credentials out of public evidence and new provider calls.
