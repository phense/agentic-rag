# Design: Query inference reuse

The cache stores immutable successful vectors, never retrieval results. The normal SQL
query, assertion_eligible predicate and evidence presentation run on every search.
This makes expiry and source revocation independent of cache invalidation timing.
Canonical knowledge and audited writer behavior remain unchanged.

HTTPX pools at most eight connections/keep-alive connections per process; requests
keep existing timeouts. Cookies are rejected. Client leases do not close a shared
transport between requests; process exit closes it and child processes start fresh.

MCP owns a lazy bounded query cache. Python/CLI callers keep uncached inference by
default. The cache hashes query/context and keys by the current Ollama model digest,
read from /api/tags for each attempted reuse. It coalesces identical concurrent misses,
stores at most256 entries for300 seconds, copies returned vectors and caches no failures.
Model metadata failure falls back to the original uncached embedding path. Identity
shortcuts and legacy benchmark baseline bypass the cache. Database connections remain
short-lived to preserve roles, transaction lifetimes and process compatibility.

Primary API references: https://docs.ollama.com/api/tags and
https://www.python-httpx.org/advanced/clients/.
