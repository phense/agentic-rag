# Pattern suggestion contract v1

Work: RAG-065 / Issue65. Status: settled before implementation (T065-001); any
as-built refinement is recorded at the end of this file.

## Purpose and boundary

A pattern is a derived, explicitly inferred suggestion over several eligible
original memories in one concrete domain and project/global scope. It is stored
as a `dtype=synthesis` document with a `claim_records.kind='inference'` claim,
written only through the audited gateway (`store.save_claim`). It never becomes a
user statement, never counts as support for another pattern and never confirms
itself. Inference confidence, operator review (`review_state`) and current
factual status (`claim_eligible`/`assertion_eligible`) are separate fields.

## Configuration

`[synthesis]` in `config.toml` (all optional):

| Key | Default | Bound | Meaning |
|---|---|---|---|
| `enabled` | `false` | bool | Global safety switch. Off: no scheduling, no provider call, no backfill. |
| `provider` | `""` | `""`, `claude`, `codex`, `openai-compatible` | Empty reuses `[llm] provider`. |
| `model` | `""` | ≤ 200 chars | Empty reuses `[llm] model`. |
| `timeout_seconds` | `30` | 1–300 | One provider call. |
| `max_input_chars` | `12000` | 1000–24000 | Aggregate provider input. |
| `max_output_tokens` | `1024` | 128–4096 | Provider output. |
| `max_runs_per_tick` | `2` | 1–10 | New runs scheduled per worker tick. |

A scoped policy (below) is additionally required. Fresh and upgraded stores
contain no policy.

## Eligible original support

A candidate memory is in the policy's exact domain and `project_scope`; no global
or cross-scope join happens implicitly. Documents are excluded at document level
in this order (first match is the reported reason):

1. `derived` — registered pattern or `dtype=synthesis`;
2. `legacy_unmanaged` — no claim record;
3. `not_stated` — claim kind other than `stated`;
4. `no_qualifying_span` — no span that is complete, `role=user`, from an active
   source and not a manual attestation (namespaces `operator`, `manual`,
   `svc1:*:manual:*`);
5. `not_current` — `status<>'active'` or not `assertion_eligible(id, now())`.

Qualifying spans: complete, user role, active source, not manual, quote ≤ 4000
characters. Per memory at most 8 spans; per batch at most 12 memories.

Independence. Spans form one event when they share a `source_key` or the same
normalized quote (NFKC, casefold, whitespace runs collapsed, stripped). The
stored quote bytes are never changed; normalization is only an independence key.
A set of spans is sufficient when a maximum matching between event groups and
distinct memories has size ≥ 3 (minimum three distinct user events across three
distinct memories). Below the floor, nothing is sent to a provider.

## Tool surface (MCP, REST `POST /v1/tools/<name>`, remote MCP)

| Tool | Level | Arguments | Effect |
|---|---|---|---|
| `memory_pattern_preview` | read | `domain, project=None, scope=None, start=None, end=None` | Provider-free, write-free. Policy state, candidate counts, exclusions, independence, budgets and bounded original references (`document_id, version, reference, source_version, event`). No quotes. |
| `memory_pattern_status` | read | `domain=None, project=None, scope=None, limit=20` | Visible policies, open backfills and newest runs: state, code, counts, provider calls, timings. No prompts, quotes, raw provider errors or namespaces. |
| `memory_patterns` | read | `domain, project=None, scope=None, limit=20, cursor=None` | Current patterns only. Withheld patterns are omitted without a count. |
| `memory_pattern` | read | `id_or_slug` | One current pattern: `label, statement, confidence, review_state, current, parts[]` with exact citations; otherwise `evidence_unavailable`. |
| `memory_pattern_policy` | write | `domain, enabled, reason, project=None, scope=None, interval_seconds=86400` | Create/enable/disable. Enabling from disabled records server time as `forward_from`; disabling keeps accepted output and patterns but withholds the patterns. Re-enabling sets a new `forward_from`; nothing between is processed implicitly. |
| `memory_pattern_backfill` | write | `domain, start, end, reason, project=None, scope=None, max_batches=1` | Explicit finite history window `[start,end)` of document arrival time, `end ≤ forward_from`, ≤ 366 days, `max_batches` 1–10. Requires an enabled policy. |

Read-only principals and `agentic-rag-ro` may call the read tools only. Write
tools require write scope for the policy's domain and project.

CLI (local SQL or, in client mode, the service): `rag pattern preview|status|list|show|enable|disable|backfill`.

Errors: `invalid_arguments` (400), `scope_denied` (403), `evidence_unavailable`
(404, shared for missing, inaccessible and withheld), `synthesis_disabled` (409,
global switch off for write tools), `incompatible_service_schema` (503).

## Pattern inspection (`memory_pattern`)

```text
contract_version: 1
pattern: {id, slug, label, statement, domain, project_scope}
kind: "inference"            # never "stated"
confidence: low|medium|high  # the model's own, not verification
review_state: unreviewed|confirmed|refuted
current: true                # withheld patterns are not returned
verification: {independent: false}
support: {events, memories}
parts: [{text, citations: [{reference, source_version, original: {id, slug, version}}]}]
```

`reference` is `<source_key>#<span_hash>`; drill-down is `memory_evidence(original.id, source_key=…)`
from contract evidence-v1. No namespace, source event ID or transcript path.

## Durable work

- Policy `(domain, project_scope)` unique, `version` increments on every change.
- Scheduling happens only inside the existing singleton worker tick; at most one
  open run per policy, `max_runs_per_tick` per tick, one provider call per run.
- Run states: `pending → accepted → applied`, or `non_conclusion`, `withheld`
  (policy/authority/source changed), `error`.
- The snapshot records sorted `(document_id, ev1, source_key, span_hash, src1)`.
- Accepted provider output is validated and committed before application.
  A retry of an accepted run never calls the provider again.
- Application key: `sha256(["pattern-v1", policy_id, policy_version, domain,
  project_scope, sorted cited (document_id, ev1, source_key, span_hash, src1)])`,
  unique. One pattern document, its dependencies, its claim spans and one
  `synthesis_apply` audit row commit atomically.
- Forward cursor: document arrival `(created_at, id)`; not advanced while the
  pending candidates are below the floor and fewer than a full batch.

## Provider output (strict JSON schema)

```text
{suggestions: [≤3 {label ≤120, statement ≤600, confidence: low|medium|high,
                   parts: [1..6 {text ≤400, citations: [1..8 {id: "C<n>", stance: supports|contradicts}]}]}],
 non_conclusions: [≤3 {reason: insufficient_evidence|conflicting_sources|ambiguous, citations: [≤8 {id, stance}]}]}
```

No additional properties. Validation outcomes per suggestion: `unknown_citation`
(an id not offered), `conflicting_support` (any `contradicts` stance),
`insufficient_independent_support` (cited spans below the floor), more than 8
distinct cited spans (`too_many_citations`). A schema violation rejects the whole
response as `invalid_output`. Provider text never selects scope, domain, kind or
sources.

## Read guard

`claim_eligible(id)` and the history branch of `assertion_eligible` call
`rag_pattern_current(id)` for registered patterns: the policy is enabled, the
pattern document is active, and every dependency is visible, active, currently
`assertion_eligible`, has the recorded `ev1` version, and every cited source
still has the recorded `src1` version and is active. `memory_get`,
`memory_evidence`, `memory_evidence_history`, graph tools and pattern tools apply
the same check. An unreviewed pattern stays out of ordinary retrieval even when
current, as every unreviewed inference does.
