# Codex continuity: digest repair and remaining live evidence

This report covers the code repair for [Issue #12](https://github.com/phense/agentic-rag/issues/12).
It does not complete the Issue's sustained-session acceptance criteria or authorize
production adoption. Measurements were taken locally on 2026-10-05; public evidence
contains aggregates and synthetic fixtures only.

## Supported source and observed failure

The running package is 0.6.2 at `8af011ec31761e4d1cbb6fe389b967c1e141103b`, with 19
applied migrations. The PR base is 0.6.5 at
`046bf2ed8814c51e9a8752cfabb45ca9581fbb6d`; its continuity digest has the same defect.
Codex CLI is 0.160.0. Its configured context window is 350000 and total compaction
threshold 250000; hooks are enabled. Both MCP privilege levels use the retained
production environment. Six RAG event handlers are installed. Eight stored hook
trust hashes exist; their presence does not establish current interactive trust.

The installed `python3 -m agentic_rag.cli install --codex --check` reported all
managed files up to date, validated the generated configuration in an ephemeral
Codex home and changed no target files. Calling through the `python` alias instead
would replace the six owned command paths; that is an invocation mismatch, not
configuration drift. The duplicate foreign herdr handler was reported and preserved.

A `rag_reader` transaction explicitly set `READ ONLY` found 33 Codex-field
`PreCompact` checkpoints, all automatic, compacted and snapshot-only, across 16
available native rollout files. All 33 associated enrichment jobs were `done` with
one attempt and no queue error. Their digests were empty because the continuity
reader expected top-level Claude messages, while Codex writes `response_item.payload`.
No provider was called by these measurements and no production row was changed.

## Practical before/after results

The same 16 local files were read with the source 0.6.2 function and candidate code.
They contained 776–4833 parsed records each. Private bodies, paths and IDs were not
published or sent to a provider.

| Scenario | Source behavior | Candidate behavior | Limit |
| --- | --- | --- | --- |
| Enrichment input from 16 native files | 0/16 nonempty digests | 16/16 nonempty; 2591–12000 characters | Local parsing only; no real enrichment call |
| Continuity cursor from 16 native files | 0/16 cursors | 16/16 opaque cursors; 16/16 agree with bounded capture | Sampled native files, not all future rollout formats |
| Resume after the current boundary | No native cursor to resume from | 16/16 yield an empty digest after that cursor | Synthetic append regression also verifies a new tail is read |

One sequential pass per file measured median elapsed time 28.901 ms before and
42.197 ms after. This is a format-correctness repair with extra parsing cost;
the sample does not establish provider quality, general latency or recall gains.

## Compatibility and verification

Twelve new parser regressions failed on the source behavior before implementation.
The initial affected suite passed 74 tests. Two populated, owned source installations
(018 and 019) then exercised strict source backup/restore, exact all-table row and
application table-privilege comparison, a pending legacy-cursor job, gateway enrichment
with a synthetic runner, reader restoration of goal/next action/pins/domains, a new
cursor superseding the old checkpoint without deleting its enrichment, and unchanged
knowledge/pins/sources/migrations. No schema migration or provider call was used by
the repair rehearsal. The pending queue row itself remained unchanged by the direct
gateway exercise. Existing lossless mining and Claude/agy cursor readers are covered
by their original regressions.

Commands (candidate checkout, database suites run sequentially):

```bash
uv run pytest -q tests/test_transcript_codex.py
uv run pytest -q tests/test_transcript_codex.py tests/test_transcript.py tests/test_transcript_agy.py tests/test_continuity_capture.py tests/test_continuity_enrich.py tests/test_mining_window.py
uv run pytest -q tests/test_codex_continuity_compatibility.py
```

Final candidate results: `uv run pytest -q` passed 1331 tests in 187.32 s;
`node --test tests/test_opencode_plugin.mjs` passed 7 tests. `uv lock --check`
and `git diff --check` passed. All 101 relative links in changed documents resolve.
The wheel and source distribution build successfully; the wheel contains the exact
new parser bytes and the stack's 020 migration. The source distribution also includes
the parser. The target patch bump is 0.6.5→0.6.6. Independent review of the complete
bounded diff found no actionable Critical, High, Medium or Low bug.

## Remaining live acceptance gates

Issue #12 stays open. A fresh session on the adopted code must record manual and
automatic compaction, actual checkpoint enrichment and subsequent context containing
the expected goal, pending work, pins and domains. Current `/hooks` review must verify
the installed handler hashes. Provider outage/recovery must demonstrate preserved
source spans and retry budgets. A real SessionEnd must be correlated with its final
tail and audited mining result; ordinary completed mining jobs cannot establish
which lifecycle hook enqueued them. Native Codex memory and stored snapshots are
complementary evidence, not substitutes for those scenarios.

Production adoption, live outage injection, replay of completed jobs and private
transcript transfer to a new provider were not performed. Follow the
[code recovery procedure](../05-session-mining-and-curation.md#codex-response-item-digest-repair-and-code-recovery)
when adopting the repair.
