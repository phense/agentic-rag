# Delta: Retrieval ordering

## ADDED Requirements

### Requirement: Bounded local multilingual inference

Ordinary ambiguous auto searches SHALL use an available verified local trained
reranker within twelve candidates, 1200 characters per passage,512 query
characters, two concurrent requests and a total1500ms inference deadline.
Unavailable or invalid inference SHALL preserve the complete original ordering.
The application SHALL neither download models during search nor send passages
to remote hosts, proxies or redirects. Over-budget queries SHALL bypass inference.

Scenario: An eligible ambiguous query reaches a matching local model.
The validated model-index permutation changes order; original content, identity,
score, scope, provenance, evidence and source offsets SHALL remain authoritative.

Scenario: Discovery fails or inference times out/returns invalid indices or scores.
Return original eligible ordering; a failure after model discovery SHALL emit the
existing generic fallback warning. Busy clients SHALL not queue local inference.

### Requirement: Existing clients and stored knowledge

Exact selectors/symbol queries, explicit hybrid/lexical, baseline and rerank=off
SHALL preserve previous stages. Existing TOML and omitted optional CLI/MCP mode
SHALL work without model deployment. Existing callback behavior SHALL remain
available. SQL eligibility SHALL run on every search. Old/new readers and rollback
SHALL preserve all public database rows and leave production runtime unchanged.
