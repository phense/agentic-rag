# Provider indexes delta

## Added: Explicit task-bound inputs

An explicitly configured retrieval profile SHALL bind document and query prefixes
to its immutable generation identity. Documents SHALL receive only the document
prefix and queries only the query prefix. Empty-prefix profiles SHALL preserve
their prior descriptor, identity and input bytes.

Raw input bounds SHALL be checked before prefixing. No input SHALL be silently
truncated. Inspection SHALL report the additional wire characters and role probes.
Selection SHALL verify both roles before changing the active pointer. A failure
SHALL preserve the previously selected generation and canonical knowledge.

Existing installations SHALL need no migration or model change. Config rollback
SHALL restore the prior profile file before launching a binary without these keys.
