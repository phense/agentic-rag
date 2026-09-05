# Claim evidence and source trust

Ordinary mined memories, lessons and signals now carry one independently assessable
claim per item, a kind, and bounded references to consumed sanitized source events.
Kinds are `stated`, `proposal`, `hypothetical` and `inference`. Source role and optional
time come from the transcript. Event identity is namespaced by session. Neither raw
transcripts nor arbitrary tool outputs are copied into the evidence registry.

A source ID must exist in the consumed window and its quote must occur in that span.
This proves membership, not truth or semantic entailment. Paraphrases/translations,
questions, hypothetical language, partial source fragments and unquoted signal additions
are conservatively kept for review. Only a complete, directly quoted user statement
can enter ordinary current retrieval without explicit operator review, and it is still
labeled `unreviewed`, never a verified fact. Assistant repetition adds no independent
user source count. Distinct events prove distinct records, not independent authors or
independent real-world observation.

Search/CLI/MCP expose compact `evidence` kind/review/completeness/count metadata.
SessionStart and prompt recall include the same labels. `memory_get`/`rag get --json`
return `claim_evidence` plus the full sanitized `claim_sources` with stable source keys.
Get/history/review preserve unsupported claims. Legacy documents remain accessible,
explicitly provenance-incomplete; old `verified_at` does not prove claim-level support.

Within a known project, exact same-body/kind/domain/type reuse appends source spans
without regenerating content. Same event counts once even with several spans. Managed
claims are immutable: corrections create another claim, and source trust can change
without deleting prior evidence. Ordinary curation excludes managed claims. Existing
accepted batches lacking evidence are retained as incomplete review claims, so replay
remains lossless without silently promoting old model output.

```bash
rag get CLAIM --json
rag evidence source-state SOURCE_KEY --state refuted --reason 'Source corrected'
rag evidence source-state SOURCE_KEY --state removed --reason 'Source withdrawn'
rag evidence source-state SOURCE_KEY --state active --reason 'Source revalidated'
rag evidence review CLAIM --state confirmed --reason 'Meaning and source support checked'
rag evidence review CLAIM --state unreviewed --reason 'Needs another review'
```

MCP writers expose `memory_source_state` and `memory_review_claim`; read-only MCP does
not register them. These are explicit operator decisions, not extra autonomous model
calls. Refuted/removed are retained trust states, not hard deletion. Confirmation binds
to the active source spans inspected at that time. A later attached source does not
inherit confirmation. Source loss makes current eligibility depend on remaining
reviewed support (or directly stated complete user support); all evidence remains in
history. Source-state change and audit commit atomically. Attaching a withdrawn source
cannot reactivate it. Exact duplicate confirmations retain source identity.

Source trust composes with project scope and valid-time selection before candidate
limits and every selected graph hop. New atomic temporal sources participate in this
registry. Old temporal evidence remains inspectable but has incomplete lifecycle
coverage until attached through the new gateway. Refuting a newer temporal source does
not resurrect a superseded old value. As-of queries use current source trust plus
known validity at the requested time, not a reconstruction of old trust decisions.

Migration012 adds tables and a shared predicate without rewriting legacy knowledge,
provenance, timestamps or pins. Back up first, hold the worker lock, migrate and activate
the matching code, verify unchanged legacy/pin fingerprints and migration idempotence.
Restart long-lived MCP processes for new tools. Old workers cannot enforce source trust;
use a forward fix or controlled restore of the verified predeployment backup.

The [synthetic semantic check](benchmarks/2026-09-06-claim-evidence/README.md) separates
semantic support from structural membership and retains its classification discrepancy.
It is not a production promotion model or a general accuracy claim.
