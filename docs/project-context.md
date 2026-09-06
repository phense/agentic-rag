# Project profiles and selective recall

`rag context --project /path/to/repo` returns the same bounded startup context used
by the hooks. Add `--prompt 'How do we run tests in this project?'` for selective
query context, or `--json` for document IDs, revision, status and omission warnings.
The read-only MCP equivalent is `memory_context(project=..., prompt=...)`.

Startup preserves exact pin bodies and checkpoint restoration first. Remaining
space holds an advisory project profile: up to six stable conventions and six
recent references. Stable entries require a short, directly supported user-stated
claim with a convention cue; generated proposals and incomplete legacy evidence
cannot become stable rules. Entries retain document/source identities, claim kind,
review/provenance status and validity. The view never changes canonical documents.

Profiles store only bounded IDs in PostgreSQL. Reads revalidate source trust, scope
and temporal validity; stale views show their generation date. SessionStart queues
missing/stale profiles through the existing worker, independently of rendering
success. Refresh is an audited atomic gateway operation; failure preserves the
previous cache. `rag profile --refresh --project /path/to/repo` explicitly rebuilds
it using writer authority. CLI context and MCP context always use reader authority.

Ordinary EN/DE project questions and history references use deterministic gates and
local full-text candidates. Unrelated questions with no applicable evidence produce
no memory context. Error-signature recall remains available. No query model, hosted
provider, new scheduler or separate provider-specific store is introduced.

The shared startup cap is at most 10,000 characters (or the configured smaller
limit); profiles occupy at most 2,400 extra characters. Prompt context is at most
4,800 characters. Whole entries, including multiline pins, are selected before
rendering; omitted entries have explicit notices. Content deduplication uses only
complete selected text, so an omitted profile cannot suppress query evidence.

Prompt replay receipts are written only after successful output. Their key includes
host, session, canonical project, real turn ID, configuration, visible memory
revision and emitted text. A later turn always re-reads current data; missing real
turn IDs disable suppression. The bounded local receipt cache expires after one day.
This does not edit earlier host messages or guarantee atomic exactly-once delivery
between concurrent processes. Startup does not use prompt receipts.

The gate is heuristic and the revision aggregates scoped metadata; large projects
may cost more than the small [synthetic measurement](benchmarks/2026-09-06-project-context/README.md).
Profiles are advisory retrieval aids, not newly inferred user instructions.
