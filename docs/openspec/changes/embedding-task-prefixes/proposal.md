# Change Proposal: Explicit embedding task prefixes

Issue: [#83](https://github.com/phense/agentic-rag/issues/83). Approved within the
maintainer's request to complete the existing model comparison and safe substitution.

The shipped profile API sends documents and queries identically. Jina retrieval
requires `Document: ` and `Query: ` respectively. Add optional immutable prefixes
to the existing profile; do not introduce another provider or model store.

Acceptance: default identities and wire inputs stay byte-identical; prefixed
profiles bind both strings into generation identity, route each role correctly,
probe both roles before activation, and reject malformed configuration before IO.
Keep the raw 4000-character input bound; prefixes add at most 64 characters.

No schema, access-control, default model or production configuration changes.
Old readers retain their previous configuration and legacy index. Rollback restores
the prior config as well as the binary; old binaries cannot parse the new fields.
Existing PB061-OPS gains the configuration, probe and rollback instructions.
The existing real-model benchmark remains frozen independently of this delta.

Escalation: no new subsystem, privilege boundary, risky migration or architectural
uncertainty. Reuse the profile/generation identity and audited lifecycle APIs.
