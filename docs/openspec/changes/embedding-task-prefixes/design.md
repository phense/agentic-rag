# Design: Explicit embedding task prefixes

`EmbeddingProfile` adds `document_prefix` and `query_prefix`, defaulting to empty.
Both must be strings of at most 64 printable characters and either both empty or
both nonempty. When empty, omit both descriptor keys to preserve saved identities.
Otherwise include both verbatim; editing either requires a different generation.

`embed_profile(..., purpose='document')` checks raw inputs before adding the role's
prefix. Only `document` and `query` are accepted. Input strings are never truncated.
Both Ollama and compatible HTTP receive the same prepared input contract.
`indexes.query_vector` chooses query; bounded builds choose document. Default
profiles keep the old two-argument adapter call for compatibility.

Prefixed capability probes and generation activation infer the fixed synthetic
string once per role. The activation pointer changes only after both succeed.
Inspection reports source/wire bounds and six probe / seven selection requests;
unprefixed profiles retain three / four. Each inference retains its existing
timeout, identity checks, process admission and service model lock.

Tests use literal HTTP inputs, old descriptor bytes, changed identities, invalid
configuration, raw limits, real generation lifecycle and failed query-role probe.
No new dependencies or SQL. Existing release/upgrade and provider tests supply
backward compatibility; actual model measurements stay separate from mock tests.
