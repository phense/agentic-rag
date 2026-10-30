---
id: PB061-OPS
title: Change inference providers and embedding indexes
type: task
doc_id: standalone
readers: [installation-operators]
owner: repository-maintainer
class: system
origin: Issue61 AC001-008
status: drafted
version: 0.6.14
last_edited: 2026-10-30
last_reviewed: unreviewed
depends_on: [13-central-service.md]
assets: []
summary: Inspect independent inference slots and explicitly rebuild, select or roll back a model-bound vector space.
---

# Change inference providers and embedding indexes

Use this procedure to change the model used for extraction or semantic search
while preserving the original knowledge. Run the operator commands on the
installation that owns PostgreSQL. Central clients use the server's selected
generation; they do not administer it through the service API.

## Before you start

Install 0.6.14 and apply additive schema027 through the
[verified upgrade procedure](13-central-service.md#upgrade-the-local-store).
Use the existing database owner's local account, its configured database and a
reviewed backup with a successful strict restore. Coordinate any installation
upgrade or service restart separately. This guide does not authorize production
deployment. Rehearse on a synthetic or explicitly approved isolated copy first.

Keep the previous profile and generation available for rollback. The commands
retain up to three generations and never delete one automatically. Each
generation has its own dimension-specific HNSW vector index. Plan storage for
the retained vectors/indexes and the backup. Stop on resource pressure; do not
reduce the installation's free-space guard to get a rebuild through.

Do not change legacy `[embed]`/`[ollama]` settings to migrate existing vectors.
Historical raw vectors have no recorded identity. They stay available in legacy
mode until you explicitly select a managed generation; they are never imported
as verified vectors. Old binaries continue using the legacy index even after a
new binary selects a managed generation. Upgrade readers together if consistent
model selection across clients is required. Old clients' canonical writes remain
visible and become missing managed coverage until the next bounded build.

### Upgrade an existing 0.6.13 installation

For this release, the supported starting point is0.6.13/schema026 and the target
is0.6.14/schema027. The linked central-service procedure is retained at its
original0.6.10 baseline; reuse its writer inventory, backup/strict restore and
post-upgrade checks with the following source version and a new private dump
path. `/owned/source.toml` is the operator-selected existing database config.

1. Run `rag service --config /owned/source.toml inventory --source-version 0.6.13 --identities --output /owned/upgrade/provider-source.json`.
2. Run `rag service --config /owned/source.toml preflight --source-version 0.6.13 --mode local`.
3. After approval for that installation and after stopping its writers, run
   `rag service --config /owned/source.toml upgrade --source-version 0.6.13 --dump /owned/upgrade/provider-027.dump --apply --writers-stopped`.
4. Check `migrations_applied=["027_provider_indexes.sql"]`,
   `restore_verified=true` and `original_rows_unchanged=true`. Run
   `rag service --config /owned/source.toml status` and existing RO/RW client
   smoke checks before resuming writers. Keep the dump and its manifest.

The local/central populated026 rehearsals reuse the existing verified-backup,
strict-restore and original-row verifier unchanged; only the empty additive
generation tables are new. Central target restore uses the same verified
manifest and empty-target/resume rules. No original rows or ACLs are excluded
from comparison. See the verification record for commands and actual results.

## Terms

| Term | Meaning |
|---|---|
| Extraction slot | Provider that turns an explicit input into structured facts; independent of search embeddings. |
| Embedding profile | A named configuration for one provider/model/revision, endpoint, dimensions, normalization, distance metric and representation. |
| Generation | A retained set of vectors tied to an immutable profile identity. |
| Coverage | Current canonical chunks with valid source hashes in that generation, including inactive chunks needed for later applicability changes. |
| Cutover | Atomic change of the selected generation after complete coverage validation. |
| Catch-up | Bounded processing of missing/stale vectors after canonical writes. |
| HNSW | PostgreSQL's approximate vector index, used with bounded candidate work. |
| Egress | Text sent to a provider outside the local loopback endpoint. |

## Choose and inspect the configuration

1. Run `rag providers inspect`. This opens no database, reads no credential value
   and sends no request. Inspect extraction and each profile's destination,
   identity guarantee, dimensions, input bounds and maximum requests.
2. Keep extraction settings in `[llm]` in `~/.agentic-rag/config.toml`, or the file
   named by `AGENTIC_RAG_CONFIG`. Existing Claude/Codex CLI login remains supported:

   ```toml
   [llm]
   provider = "codex"
   model = "YOUR_AVAILABLE_MODEL"
   bin = "codex"
   ```

   Use a model available to your authenticated CLI; the example is a configuration
   shape, not a claim about account access. Extraction changes do not rebuild vectors.
3. Add an embedding profile under `[embedding_profiles.NAME]`. For Ollama, obtain
   the full SHA256 digest from your configured server's `/api/tags` response and
   replace `REPLACE_WITH_FULL_SHA256` before saving this example:

   ```toml
   [embedding_profiles.local]
   provider = "ollama"
   model = "bge-m3"
   revision = "REPLACE_WITH_FULL_SHA256"
   url = "http://127.0.0.1:11434"
   dimensions = 1024
   normalization = "none"
   metric = "cosine"
   representation = "raw-v1"
   max_batch = 8
   max_input_chars = 4000
   timeout = 30
   ```
4. Run `rag providers inspect` again. Resolve configuration errors before probing.
   Model/revision/endpoint/dimensions/normalization/metric/representation define
   identity. Credential rotation, batch size and timeout changes preserve it.

You should see the independent extraction slot and named profile with finite
bounds. No profile edit changes the selected database generation.

### Optional compatible HTTP provider

The initial managed embedding providers are Ollama and `openai-compatible`.
Extraction supports Claude/Codex CLI and compatible HTTP structured chat. Neural
reranking retains its independent local [reranker contract](retrieval-quality.md).

For HTTP embeddings, set `provider="openai-compatible"`, an HTTPS origin or `/v1`
URL, and `model` equal to `revision`. The endpoint must list that exact logical
model in `/v1/models`, return the same model ID in inference responses and produce
the requested dimension. There is no arbitrary revision-label override. This
checks the server's logical model assertion; it cannot attest remote weights.
Ollama instead checks the tag's SHA256 before and after inference. Neither
contract establishes that a hostile provider tells the truth.

Set one `credential_env="VARIABLE_NAME"` or `credential_file="/absolute/token/path"`.
The file must be a regular file owned by the running account, mode0600, at most
8192 bytes and not a symlink. Keep actual credentials out of TOML, shell history,
issues and logs. URL credentials/query strings, redirects, environment proxies
and retained response cookies are refused. Hosted HTTP requires HTTPS.

Compatible HTTP extraction uses `[llm]` keys `provider`, `model`, `revision`, `url`,
`credential_env` or `credential_file`, `max_input_chars` and `max_output_tokens`.
It requires `/v1/chat/completions` with strict inline JSON schema, `max_tokens`,
an exact model ID and a complete schema-valid JSON object. Endpoints missing
these capabilities are rejected; no alternate model is selected.

## Probe before sending stored knowledge

1. Run `rag providers probe local` for the example loopback embedding profile.
   This sends one fixed synthetic string and checks the identity around inference.
2. For a non-loopback profile, inspect its destination first, then explicitly run
   `rag providers probe NAME --allow-egress`. No stored content is used.
3. To test extraction explicitly, run
   `rag providers probe-extraction --allow-egress` for a hosted/CLI provider.
   It asks only for a fixed synthetic JSON result.

Successful probes report their identity and dimensions/capability. They do not
modify canonical knowledge or certify corpus quality. Stop on authentication,
identity or capability errors and correct that profile; retrying does not switch
providers. A successful inspection alone is not a connectivity test.

## Build and select a generation

The generation name `next-space` and profile name `local` below are operator
inputs. Use a new generation name for a changed identity. Canonical documents,
IDs, assertions, evidence and pin text remain unchanged throughout.

1. Run `rag index status` to record the selected generation and current coverage.
2. Run `rag index create next-space --profile local` to verify the identity and
   create a separate generation. For an external profile, add `--allow-egress`.
   Repeating the same name/identity is idempotent; a changed identity is refused.
3. Run `rag index build next-space --batch-size 8 --allow-corpus`. For an external
   profile, also add `--allow-egress`. This explicitly permits only the bounded
   batch of stored, sanitized chunk text to reach that destination.
4. Repeat the bounded build until `rag index status next-space` reports no missing
   chunks. After interruption, use the same generation; valid vectors are reused.
5. Run `rag index activate next-space`. Add `--allow-egress` for an external
   identity/capability check. Activation sends one fixed synthetic input, up to
   four HTTP requests, even for an empty store. It refuses incomplete coverage,
   a changed model or an unsupported/wrong-dimension embedding response.

The previous index remains selected until step5 succeeds. Cutover excludes
canonical writes briefly and checks coverage while holding that exclusion;
timeout or an incomplete generation leaves selection unchanged. Concurrent
builders may duplicate inference; effective writes serialize under source locks.
Inference happens before canonical source locks; source
changes invalidate the affected results instead of overwriting new content.

## Check search and keep rollback usable

1. Run a representative `rag search "KNOWN QUERY" --json` with the normal domain
   and project selectors. Check expected document IDs, original citations and
   any warnings against your reference results.
2. Run `rag index status` after new saves. New or changed chunks stay searchable
   through lexical evidence until bounded catch-up adds their current vectors.
3. Run bounded builds for both the selected and retained generation as needed.
   Keep each profile configured under its original identity. Post-cutover writes
   do not disappear when you switch back.
4. To return to a retained generation, run `rag index rollback OLD_NAME` after its
   coverage is complete. Add `--allow-egress` if its fixed synthetic
   identity/capability check is external (one input, up to four HTTP requests).

Rollback refuses stale coverage and changes only selection. It preserves new
canonical writes. A missing model/profile yields a classified warning and lexical
retrieval; another embedding provider never receives the query automatically.
Managed retrieval never merges vectors from legacy raw/context indexes. The
initial managed representation is raw-v1. Contextual full-text candidates remain
available to managed retrieval through source-checked lexical reads; contextual
vectors remain limited to legacy operation and rollback to an old binary.

## Limits, failures and evidence

| Boundary | Behavior |
|---|---|
| Embedding batch | 1–32 inputs, at most4000 characters each; per-profile limits may be smaller. Oversized input is refused, never silently truncated. |
| Managed embedding network usage | At most3 requests per batch/probe: discovery, one inference, discovery. Identity-only checks use1 request; activation/rollback use up to4 requests and one synthetic input. No automatic HTTP retries or fallback. |
| Compatible HTTP adapter response/time/concurrency | At most4MiB per response; at most120seconds per HTTP operation, lower configured limit honored; two inference operations per process. These limits do not bound a Claude/Codex CLI's own internal HTTP requests. |
| Central background builds | Shared model admission yields to foreground work; per-operation timeout capped at10seconds. This does not change standalone profile limits. |
| Vector format | halfvec,1–4000 dimensions, finite/nonzero values, cosine; normalization `none` or `l2`; raw-v1 only. |
| HTTP extraction | Default24000input characters and2048output tokens; hard limits64000/8192. Inline bounded JSON schema only. |
| Durable HTTP jobs | Finite configured worker attempt budget, including transient failures and rate limits; no per-request retries. Existing CLI outage scheduling remains compatible. |
| Monetary cost | Input/request/output bounds limit usage, not a currency total. Configure account-side spend limits and check provider pricing before corpus processing. Failed requests may also be billed. |

On a missing model, auth error or changed identity, inspect the configured profile
and restore access to the pinned model, or create a new generation deliberately.
On a coverage refusal, run status and resume the bounded build. On lock/resource
pressure, stop the operator action and retry after the competing write/build or
capacity problem is resolved. For a central background timeout, reduce the next
explicit batch size; completed batches persist and are not repeated. Preserve generation names, safe error codes,
coverage counts, source/target versions and backup manifests for the maintainer;
omit corpus text and credentials.

Completion requires current complete coverage, expected scoped/cited results and
a rehearsed catch-up rollback. Repeat this review/rehearsal after changes to
schema, providers, identity guarantees, source hashing, authority, cutover locking
or storage limits. See the [verification record](verification/issue61-providers.md)
for measured synthetic results and the separate limits on production claims.
