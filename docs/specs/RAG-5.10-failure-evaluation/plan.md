# Technical Plan: RAG-5.10

## Baseline and affected contracts

Isolated feature/failure-evaluation starts at reviewed Feature9476e42b, schema019.
Main1294d6c/schema018 remains live. Original benchmark runner/corpus contracts remain
unchanged; new optimization module reuses owned databases, audited store/mining/search
and original entities.read. No SQL change or live strategy loader is needed.

## Design and architecture gate

Strict failure corpus adds explicit document/query source families, split, actor, domain,
project and authored assertion fixtures. Validate all labels, whole-family separation and
copied title/body fingerprints before database/provider access. Bounded static profile grid
combines ordinary search versus exact caller-provided entity/attribute routing, optional
local lexical ranking weights, and two reviewed answer/mining prompt variants. Profiles
never bypass scope/domain/temporal/claim eligibility. Candidate selection uses dev labels
only; held-out labels are evaluated only after candidate serialization/hash sealing.

Extractive results quote exact trusted facts or exact eligible source text. Answer metrics
compare independent authored values plus original citation support. Free-form model quality
remains null without an actual stage. Preserve every miss, indexing failure and exception.
Family bootstrap never treats repeated timings/translations as independent truth cases.
Actual existing-provider public mining prompt measurements are a separate bounded stage;
accepted batches are isolated per candidate so stored replay cannot contaminate comparison.

Correction exporter runs fresh reader REPEATABLE READ/READ ONLY. It classifies complete
families before limits; trusted label requires original retained reviewed complete active
user support, stated/confirmed accepted replacement and current time. Newer unsupported or
expired replacements do not revive old values. Bind exact domain/scope and original source
span, not any later attachment. Hash original content/version, retain history as reference.
Secret-check all output strings and create new0600 files outside all Git/worktree roots.
Private evaluation is a separate local network-free format/path, never synthetic/provider.

## Independent design findings and integration checks

Read-only independent investigations identified current query-family-only split guards,
runner hardcoded general domain, overly broad confirmation of assistant spans, and local
research abstention's lack of semantic assessment. Derived gates:
II-01 source/query/copied-evidence split isolation and holdout label independence.
II-02 explicit selector/domain/time identity and exact original citations survive all profiles.
II-03 confirmed correction export requires original user support, no stale revival/secrets.
II-04 private evaluator never calls providers/embeddings/rerankers;0600/no overwrite.
II-05 mining prefix/default and accepted extraction/retry/grounding unchanged.
II-06 source018/019 old/new CLI/MCP and populated state/grants retained; combined019 recovery.

## Ownership and integration order

Root owns CLI, public fixture corpus, mining prompt seam, docs and operational/measurement
driver. Independent core worker owns corrections.py and its tests. Independent evaluation
worker owns optimization.py and its tests. Stable contracts are in spec IC-001–004 and
slice briefs. Workers may run pure no-service tests only; root serializes DB tests and
integrates exporter then optimizer then CLI/driver. Disjoint files and isolated worktree
prevent shared writes; no concurrent test database reset. Independent reviews after
integration cover the complete bounded diff, not just each worker's own implementation.

## Verification and operations

Behavioral red tests; module integration; controlled real local embeddings; actual bounded
public native mining prompt comparison; full suites; populated existing-installation
rehearsal and read-only Trading; independent complete reviews and final public artifact
reconciliation; stacked PR on Feature9. Code-only retry/recovery retains all database state,
and combined018→019 migration uses PB-5.9. No development operation outside owned copies.
