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

## Inspect evidence and decide on what you saw (0.6.16)

Think of a review like signing a document: the signature should cover the page
you read, not whatever the page says later. Version 0.6.16 gives every memory an
inspectable evidence view and a version that a decision can cite.

```bash
rag evidence show CLAIM                 # readable; add --json for the full contract
rag evidence show CLAIM --cursor NEXT   # next page; at most 20 spans per page
rag evidence history CLAIM              # decisions since the 0.6.16 upgrade
rag evidence history CLAIM --source SOURCE_KEY
rag evidence review CLAIM --state confirmed --reason 'Both quotes checked' \
  --expected-version ev1:...
rag evidence source-state SOURCE_KEY --state removed --reason 'Withdrawn' \
  --document CLAIM --expected-version src1:...
```

The same contract (version 1) is returned by `memory_evidence` and
`memory_evidence_history` on both MCP levels, by `POST /v1/tools/...` on the
central service, and by the dashboard memory page. It keeps five things apart:

| Field | Meaning | Not to be read as |
|---|---|---|
| `trust` per source | Operator decision about a source: `active`, `refuted` or `removed` | A statement about the claim |
| `claim.review_state` | Operator decision about the claim | Independent verification |
| `lifecycle` | Document status and, for facts, `current`, `future`, `expired`, `superseded`, `not_accepted` or `no_event_time` | Source quality |
| `completeness` and `origin` | Whether the stored quote is complete, and whether it came from a user event, an assistant statement, an operator attestation or an unknown speaker | Proof of independent authors |
| `verification` | Always `independent: false`; `origin` is `operator_review` only after a confirmation | External verification, which this system never performs |

`eligibility.current` comes from the existing `assertion_eligible` predicate and
the document status. `reasons` only explain that result; they are not a second
rule set. Quotes are the exact stored text, at most 4000 characters. Sources are
identified by an opaque `source_key` and `span_hash`; the recorded session
namespace and event ID are not returned, because they can name host paths.

### Versions and conflicts

`version` (`ev1:…`) covers the whole evidence set of the memory, not just the
visible page: claim revision and review, every span, every linked source's
revision and trust, document status and the fact's stored time fields.
`source_version` (`src1:…`) covers one source. Both use persisted revision
counters, so a verified dump restored elsewhere yields the same versions. A
withdrawal followed by reinstatement advances the revision twice and never
recreates an earlier version.

A strict decision locks the writable document, the claim, then its sources in
key order before comparing the cited version. Shared source row locks also
serialize changes made by a 0.6.15 client that has no advisory-lock support. If anything changed, it fails with
`evidence_conflict` (HTTP 409) and writes nothing: no state, history or audit
row. Reload and decide again. A source-trust change locks only the source and
never waits for dependent claims. Shared sources still need write access to
every memory that cites them on the central service; otherwise it fails as
`evidence_unavailable`, the same answer as for an unknown or unlinked source.
The dashboard always sends the inspected version.

### History and compatibility

History rows record actor, time, operation, resulting state, reason, revision
and the concurrency mode: `strict` (with the inspected version), `legacy`
(gateway call without a version) or `direct` (a change outside the gateway,
for example by a 0.6.15 process still running after the upgrade). Source
history lists no document identifiers. Events before migration029 are not
converted; `pre_upgrade_history: not_captured` says so, and the original audit
log remains unchanged. Existing claims start at the storage baseline revision 1,
which says nothing about their earlier history.

Existing calls keep working: `memory_review_claim` and `memory_source_state`
without `expected_version`, `rag evidence review|source-state` without the new
options, and `memory_get` with its unchanged `claim_sources` and `provenance`
fields. Those legacy fields still contain the recorded namespace, source event
ID and provenance metadata for readers of that memory. Treat them as recorded
text, not as links; new clients should use the evidence contract. Project paths
in `project_scope` are authorization keys and stay unchanged, and paths that
appear inside quoted knowledge are original content.

Limits: pages hold at most 20 spans and 64 KiB of JSON-encoded quotes, with
an additional 80 KiB budget for complete source items. Source and claim reasons
are shown up to 1000 characters with truncation flags; stored originals remain
unchanged. History pages hold at most 20 events; a strict review accepts at most 128 linked sources. Fact supersession
by another memory is evaluated live, not frozen into the version. Migration029
is additive; a schema downgrade is not supported. Follow
[PB-063-UPGRADE](playbooks/system/rag-063-source-evidence-upgrade.md) and see the
[measured before/after examples](benchmarks/2026-10-31-source-evidence/results.json).

The [synthetic semantic check](benchmarks/2026-09-06-claim-evidence/README.md) separates
semantic support from structural membership and retains its classification discrepancy.
It is not a production promotion model or a general accuracy claim.


Manual attestations keep `origin: manual_attestation` and, without other complete
user support or an operator review, `claim.support_basis: manual_attestation`.
`provenance.independent_user_events` counts distinct active user source events,
including partial events, and excludes manual attestations even when their
stored role is `user`. The legacy `get`/summary fields retain their existing
shape and counting semantics; canonical eligibility is unchanged.
