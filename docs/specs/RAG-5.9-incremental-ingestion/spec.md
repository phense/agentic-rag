# Feature Specification: Incremental embedding reuse and bounded preprocessing

## Stable work ID

RAG-5.9, feature9/10, [Issue34](https://github.com/phense/agentic-rag/issues/34).
Implementation is authorized. Merge approval will be requested together with Feature10.
Production deployment, migration and service interruption remain separate authority gates.

## User scenarios

1. A small edit to a large document embeds only changed sanitized inputs. Original
   content remains complete; a save still regenerates chunk IDs under the existing contract.
2. An interrupted accepted mining batch resumes its retained extraction exactly once.
   Uncommitted cache entries disappear with the application; committed entries survive
   process restart. Reuse is an optimization, never a replacement for batch idempotency.
3. A backlog of independent mining items benefits from bounded parallel embedding
   preprocessing while one writer applies deduplication, evidence and cursor completion.

## Acceptance criteria

- AC-001: Reuse requires exact sanitized input, endpoint, normalized model tag, observed
  model digest, dimension and representation version. Unknown or changing identity cannot
  authorize reuse. Raw and contextual inputs have distinct representations; context edits invalidate them.
- AC-002: Keep all original evidence, scopes, pins, checkpoints, queue and audit history.
  No legacy untagged vector is adopted. No model or provider change is implied.
- AC-003: Only pure HTTP embedding work is parallel. Bound each prepared group to16
  documents,256 chunks and1MiB input; at most2 preprocessing embedding requests are in
  flight per process, with16 inputs per known-identity request. Legacy fallback retains
  its original request payload. Page large documents or use the existing ordered fallback; never
  truncate evidence. Dedup decisions and source-window completion remain sequential.
- AC-004: Cache writes and eviction use one nonblocking transaction lock and the audited
  gateway transaction. Readers cannot write; writers have no direct cache DML. Optional
  SQL failures use savepoints and never commit or roll back caller-owned work.
- AC-005: Retain accepted mining/application atomicity, source comparisons, contextual
  source-hash checks, queue priority and per-job acknowledgement. No speculative queue claims.
- AC-006: Execute populated018→019 interruption/retry, strict verified backup/restore,
  old/new clients and code recovery with concurrent clients on owned copies. Preserve
  configurations, grants, existing rows and audit history; fresh-install testing is insufficient.
- AC-007: Publish three paired examples with source/candidate revisions, sample sizes,
  embedding input counts, throughput, peak memory, queue delay, raw times and limits.
  Trading is read-only; no private corpus reaches public artifacts or new providers.
- AC-008: Full Python/Node suites and independent complete diff reviews leave no Critical,
  High or Medium bugs. Record remaining Low findings in a linked Issue.

## Compatibility boundaries

Source1294d6c44fd02b66715692f12791bfa2fd4c8856, schema001–018,
package0.5.0. Additive019 contains disposable hash/vector cache state only. Existing
CLI/MCP shapes, both privilege levels, configuration, hooks, scheduler and dependencies
remain supported. Candidate code on018 uses the original inference path. Old code on019
ignores the cache. Code recovery retains019; strict restore loses writes after the backup
and needs separate authorization. Production adoption is outside this implementation.

## Edge cases and limits

Half-vector entries contain no original text or endpoint. Matching vectors across domains
never changes document selection or access boundaries. This shared-role installation does
not provide per-user row ACLs. Cache pressure and contention may duplicate inference.
Model identity checks cannot prevent an adversarial server changing twice between checks.
The8192-entry FIFO cache is disposable; repeated identical saves are not canonical no-ops.

## Playbook obligations

PB-5.9 `docs/playbooks/incremental-ingestion.md`: supported additive upgrade,
interruption/resume, strict restore and code recovery, independently reviewed and rehearsed.
