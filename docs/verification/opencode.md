# RAG-OC-001 OpenCode verification

Date: 2026-09-11. Base: fb2242f. Scope: existing RAG services adapted to OpenCode
1.18.30, with DeepSeek Flash for native model calls. No DB schema or worker
provider change.

## Evidence

- Baseline: 791 Python tests passed.
- Red phase: new Python modules and JS import failed before implementation.
- Nine focused Python tests pass, including actual test-database checkpoint and
  handoff persistence, foreign-boundary rejection, debounced queue and private
  projection/installer behavior.
- Six initial Node tests pass: transient context, selective prompt propagation,
  projection filtering, child exclusion, compaction ordering, SDK failure and
  serialized idle handling.
- Independent review found an unresolvable predecessor cursor. The two-compaction
  regression failed, then passed after adding a matching empty boundary record.
  Reviewer independently checked successive and no-new-prose compactions and
  returned Ready with no unresolved Important/Critical findings.
- Native local OpenCode REST server + deepseek/deepseek-flash: an unpredictable
  marker from a synthetic scoped pin was returned on the first model invocation.
  The actual summarize endpoint completed; PostgreSQL recorded the matching
  compacted checkpoint and nonempty handoff. The next model response returned the
  marker and exact checkpoint ID from restored context. One debounced mine job
  existed for that session.
- Native test used agentic_rag_test, private fixture transcripts and a test-only
  Python sitecustomize that suppresses worker spawning and redirects local hook
  paths. It did not change production data or copy credentials. This proves queue
  handoff, not a new live worker-provider evaluation.

## Completion checks

Full regression suite: 800 passed in 33.11 seconds. Final Node suite: 7 passed,
including real child-process failure and existing read-only MCP preservation.
The built wheel contains all four adapter resources; an isolated virtualenv
installed that wheel and its OpenCode check mode succeeded without creating
the target directory. Production loader installation is recorded at handoff. Raw synthetic API transcripts remain temporary local
evidence and are not distributed.

## Limits

Native manual compaction was exercised. Automatic compaction shares the same
observed callback path and has contract coverage; sustained real auto-compaction
and crash-before-idle recovery remain operational limits. OpenCode hooks are
experimental. Capture is bounded to recent messages and excludes reasoning/tool
results. Existing canonical context and worker services retain their own prior
acceptance boundaries. No automatic Flash/Pro routing is included.
