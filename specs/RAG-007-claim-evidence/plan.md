# Implementation Plan: RAG-007 claim evidence

Specification: spec.md. Base c81aec2; Python/psycopg/PostgreSQL/pgvector.

## Approach and ownership

Coordinator serially implements `evidence.py` behind store gateway wrappers,
migration012, mining normalization, shared eligibility and CLI/MCP presentation.
`knowledge_sources` stores identity, source-derived role/time and active/refuted/removed
state. `claim_records` identifies immutable statement documents and their kind/review
state. `claim_evidence` stores bounded quote links; uniqueness is source+span, while
independent count is DISTINCT active user source identity. A source event key includes
session namespace. Source-state locks serialize attach/withdraw without lost trust.

Ordinary extraction gains claim_kind and evidence refs. Before durable acceptance,
normalize them against consumed window events. Conservative classification demotes
summaries, suggestions/hypotheticals and partial contexts. No additional production
model call. Store unsupported legacy-format batches as incomplete managed claims.
Known-scope exact claim reuse appends evidence under a key lock; kind is part of the
key. Preserve original chunks/source history, never semantic auto-merge.

Eligibility uses one SQL evidence predicate combined with existing assertion_eligible,
so every temporal search branch, hook and selected graph hop inherits source trust.
A complete stated claim with active user evidence may be retrieved as an unverified
user statement; unreviewed inference/proposal/hypothetical needs explicit history.
Operator confirmation permits retrieval while preserving kind/source labels. Source
withdrawal overrides confirmation if no active supporting evidence remains.

New temporal assertion source writes also register in this evidence lifecycle. Existing
assertions without registry entries preserve prior behavior and surface incomplete
lifecycle coverage. Source refutation never resurrects a superseded old fact: current
trust is an additional exclusion, not reversal of the temporal event chain.

## Project gates and migration

AGENTS.md shared store, gateway-only writes, reader/writer separation, secret stripping
and additive adapters preserved. Migration012 creates structures/functions only;
legacy content/timestamps/provenance and pins unchanged. Explicit grants, no reader
writes. Forward fix after activation; old workers cannot enforce new evidence policy.
Backup/archive/cloud checks and worker lock precede activation.

## Interfaces

IC001: MinedItem gains normalized kind/evidence, preserving old batch parsing.
IC002: store.save_claim and source attachment participate in caller transaction.
IC003: SearchHit gains defaulted evidence summary; get returns full bounded sources;
legacy summary is incomplete/unreviewed regardless of old verified_at.
IC004: CLI evidence source-state/review plus write MCP equivalents require reasons.

## Verification

Tests first: classification/grounding/redaction, exact reuse and source count,
source withdrawal and surviving support, immutable records, reader privileges,
source/mining rollback/replay, pre-limit and graph eligibility, CLI/MCP contract.
Full regression suite and wheel. Synthetic semantic fixture distinguishes quote
membership from entailment; inspect results, no private data or superiority claim.
Independent review derives real success/recovery integration checks.

## Architecture findings

AF-010 identity/role authority; AF-011 source-state concurrency; AF-012 shared
eligibility and temporal composition; AF-013 immutable evidence vs legacy updates.
See docs/uml/claim-evidence.md and findings.md before implementation tasks.
