# Technical Plan: RAG-5.9

## Baseline and affected contracts

Clean isolated branchfeature/incremental-ingestion starts at1294d6c, schema018.
The local source baseline passed1137 Python and7 Node tests after Feature8 adoption.
Affected paths: store.save_document/reembed_document, contextual.refresh, accepted
mining application. Retain source locks, immutable assertions and original write gateways.
Queue claim/apply/complete contracts, provider calls and client configuration remain intact.

## Design and architecture gate

Migration019 introduces embedding_reuse_cache keyed by model identity hash,
representation and exact input hash, with halfvec1024 and FIFO capacity8192.
One SECURITY DEFINER function validates bounded input, tries one global advisory
transaction lock, inserts immutable entries, evicts and appends aggregate audit metadata.
Writer direct cache DML is denied. Optional cache discovery/lookup/persistence uses
savepoints, so failures cannot poison accepted mining transactions.

embedding_reuse.py performs bounded read/compute/persist work. HTTP inference alone
uses two threads; pending batches are bounded. A context-local prepared map groups
final sanitized mining document inputs before sequential application. Cache/prepared
vectors are validated and model identity is checked before and after inference/hits.
Large document pages retain order and complete original content. Unknown identity or
missing019 uses the exact old loader contract. Reembed and contextual stale-source
checks remain authoritative. No queue lookahead or speculative job claims are needed.

Independent source-only architecture review identified input/model drift, optional SQL
transaction poisoning, dedup/chunk representation confusion, premature batch commits,
queue priority and evidence truncation as explicit gate requirements. All are covered
by AC-001–006 and integration checks below.

## Derived integration checks

II-S01: Small edit and context change reuse/invalidate exact inputs.
II-S02: Endpoint/tag/digest/version changes and unknown/drifting identity disable reuse.
II-R01: Contention/SQL failure preserve prior uncommitted writes and outer rollback.
II-S03: Independent writers cannot introduce cache lock inversion.
II-S04: Reembedding/context refresh reject stale sources; queue order remains unchanged.
II-S05: More than256 chunks preserve complete ordered content.
II-R02: Accepted application crash/retry uses retained extraction exactly once.
II-R03: Populated018→019 DDL interruption, retry, strict restore and code recovery.

## Verification and evidence

Behavioral red tests first; implement; targeted checks; controlled local-Ollama paired
measurements; isolated populated operational rehearsal; independent complete diff review;
full Python/Node suites. No production writes/migration for this candidate.
