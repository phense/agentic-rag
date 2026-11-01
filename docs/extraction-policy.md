---
id: C-067
title: Extraction policy
type: reference
doc_id: standalone
readers: [operators who configure session mining, maintainers of a central service]
status: verified
version: 0.6.20 (schema032)
depends_on: [05-session-mining-and-curation.md, 06-configuration-reference.md, 13-central-service.md]
assets: []
last_reviewed: 2026-11-01
summary: How an operator chooses which mined knowledge is kept with one versioned policy file, how its settings combine, what it can and cannot change, and how admitted work keeps its policy across retries.
---

# Extraction policy

Reader: someone who runs agentic-rag and wants session mining to keep, for
example, confirmed decisions and solutions but no error signatures, without
editing code. Upgrading an existing store and activating a policy safely is
described in [PB-067-OPS](playbooks/system/rag-067-extraction-policy.md).

Session mining asks the configured provider to extract durable knowledge from a
session and saves what passes the evidence checks. The **extraction policy** is
an optional TOML file that acts like a sieve after that step: it decides which
output categories are kept, how many items per category and how long an item
text may be. It can also hand the provider short **guidance** and examples.
Without a file nothing changes: the prompt, the schema and the retained output
are exactly those of 0.6.19.

## What a policy can and cannot do

| A policy can | A policy cannot |
|---|---|
| Keep only some output categories, per domain or project | Grant or widen any write authority, domain or project |
| Lower the per-category item limit below the built-in cap | Raise a built-in cap, the provider budget, timeout or input size |
| Drop items whose text is longer than a limit | Shorten or skip any part of the session source |
| Give the provider advisory guidance and examples | Change evidence grounding, claim qualification, pins, validity or auditing |
| Disable every category on purpose | Make the provider honest: guidance is advice, not a check |

The category and limit filter is deterministic code that runs on the provider's
output; it is the guard. Guidance is only text in the prompt. An exact quote
proves that the words occur in the session, not that a statement is true, still
valid, or that an experiment was really abandoned. The frozen benchmark records
this limit as case L1.

## File format

Set the path in the configuration:

```toml
[mining]
policy_file = "/etc/agentic-rag/extraction-policy.toml"
```

The file:

```toml
version = 1

[global]
guidance = "Keep confirmed solutions and decisions. Skip abandoned experiments."
examples = [
  { kind = "positive", text = "Decision: the store uses HNSW indexes with m = 16." },
  { kind = "negative", text = "We tried IVFFlat for an hour and dropped it." },
]
categories = ["memories", "lessons", "assertions", "contradictions", "pin_suggestions"]
max_items_per_category = 4
max_body_chars = 1200

[[rules]]
domain = "programming"
categories = ["memories", "assertions"]

[[rules]]
project = "/srv/repos/team-b"
max_items_per_category = 1

[[rules]]
domain = "operations"
project = "/srv/repos/team-b"
guidance = "Behalte bestätigte Betriebsentscheidungen."
```

| Key | Where | Value | Bounds |
|---|---|---|---|
| `version` | top level | must be `1` | required |
| `[global]` | top level | a policy fragment for everything | optional |
| `[[rules]]` | top level | fragments with a selector | at most 64 |
| `domain` | rule | domain name | letters, digits, `.`, `_`, `-`; up to 128 |
| `project` | rule | absolute normalized path, `global` or `unknown` | the project scope mining writes to (the Git top level of a local checkout, the logical project of a central client) |
| `guidance` | fragment | advisory text | 1–2000 characters after whitespace is collapsed |
| `examples` | fragment | list of `{kind, text}` with `kind` `positive` or `negative` | at most 8, each up to 500 characters |
| `categories` | fragment | output categories kept | any subset of the eight below, empty allowed |
| `max_items_per_category` | fragment | per-category limit | 0–8, never above a built-in cap |
| `max_body_chars` | fragment | longest kept item text | 1–8000 |

The whole file is at most 64 KiB. A rule needs a `domain`, a `project` or both,
and at least one fragment key. Two rules with the same selector are an error.

### Output categories

| Category | Built-in cap | Text measured by `max_body_chars` | Policy used |
|---|---|---|---|
| `memories`, `lessons`, `signals` | 8 each | `body` | the item's domain |
| `assertions` | 8 | `value` | the item's domain |
| `contradictions` | 5 | `statement` | the item's domain |
| `pin_suggestions` | 3 | `body` | domainless |
| `contradictions_with_pins` | 5 | `statement` | domainless |
| `domain_proposals` | 3 | `description` | domainless |

## How settings combine

For an item of domain *D* in project *P*, mining starts from the built-in
defaults and lets each matching layer override **field by field**:

1. built-in defaults (all categories, built-in caps, no guidance);
2. `[global]`;
3. the rule with `domain = D` and no project;
4. the rule with `project = P` and no domain;
5. the rule with both `domain = D` and `project = P`.

A list (`categories`, `examples`) replaces the earlier list; it is never merged.
Domainless categories use only layers 1, 2 and 4, so a domain rule never decides
about pin suggestions or domain proposals.

`rag extraction inspect --project P` prints, per domain, the applied layers in
this order (`scopes`), the resulting values and their digest.

## Durable work keeps its policy

The file is read once when work is **admitted**: when a local hook queues a
mining job, or when the central service accepts a source window. The resulting
normalized snapshot, for only the domains the caller may write at that moment,
travels with the job. Before its first provider call, mining binds the input
position of the session to that snapshot, together with an audit row
(`extraction_policy_bind`, policy digest only).

- A provider failure, crash or retry reuses the bound policy. A changed or even
  invalid file is not read again.
- An already accepted result is applied without another provider call and is
  never filtered again by a newer policy.
- A debounced local job that continues (`has_more`, or more turns while it waits)
  keeps its snapshot; the next newly admitted job takes the current file.
- Work admitted without a policy (queued before the upgrade, or while no file was
  configured) always uses the built-in rules.
- Current authority is checked again on every attempt. Mining writes only domains
  that are both in the snapshot and writable now; the digest is no credential.
- If every category is disabled, mining accepts an empty result without calling
  the provider and moves on.

Identities: `xf1:` names a normalized file, `xp1:` one effective policy, `xb1:`
the snapshot bound to work. Formatting, comments and key order never change an
identity; a file with only `version = 1` equals the built-in snapshot.

Accepted batches record the digest and how many items each category dropped and
why (`category_disabled`, `item_limit`, `body_limit`, `domain_not_bound`), never
the dropped text. Saved memories name the digest in their provenance.

## Commands

| Command | Provider | Writes | Purpose |
|---|---|---|---|
| `rag extraction validate [--file F]` | no | no | Strict check, identity, file hash and caps |
| `rag extraction inspect --project P [--domain D]... [--file F]` | no | no | Effective policy per domain and for domainless output |
| `rag extraction inspect --queued` | no | no | Which policy each pending job or window will use |
| `rag extraction dry-run --project P --sample S [--file F]` | no | no | Rendered preferences and plan for a redacted sample |
| `rag extraction dry-run ... --evaluate` | one call | no | Runs the configured provider on the sample, shows kept and dropped items |

All commands print JSON. In `[service] mode = "client"` the service owns the
policy: `validate --file` and `inspect --file --domain` check a local draft, the
other forms are refused with `unsupported_in_client_mode`. There is no remote
policy endpoint and no dashboard editor yet; a future editor uses the same
validator (`extraction_policy.validate_source`).

## Error codes

Validation reports every error as a code and a location such as
`rules[1].write_domains`, never the offending value.

| Code | Meaning |
|---|---|
| `unsupported_version` | `version` missing or not `1` |
| `unknown_key` | a key the format does not know |
| `reserved_setting` | a key that names a capability a policy may not touch (for example `write_domains`, `provider`, `schema`) |
| `invalid_type`, `invalid_value`, `empty_value`, `missing_key` | wrong kind of value, empty text or incomplete example |
| `too_long`, `out_of_range`, `too_many_examples`, `too_many_rules`, `file_too_large` | a bound in the table above |
| `unknown_category`, `duplicate_category` | not one of the eight categories, or listed twice |
| `duplicate_example`, `conflicting_examples` | the same text twice, or once as positive and once as negative |
| `empty_selector`, `invalid_selector`, `duplicate_selector`, `empty_rule` | rule without selector, malformed selector, same selector twice, rule without settings |
| `secret_in_policy` | guidance or an example looks like a credential |
| `invalid_toml`, `invalid_encoding`, `file_unreadable` | the file cannot be read as UTF-8 TOML |
| `bundle_too_large`, `preferences_too_long` | the snapshot exceeds 64 KiB or the rendered guidance 8000 characters |

A central service answers new windows with `extraction_policy_invalid` (HTTP
503) while its file is invalid; clients keep the windows and retry. A local hook
logs the error and admits nothing. No cursor is consumed in either case.

## Limits

- Guidance is advisory; nothing checks whether the provider followed it.
- A process running 0.6.19 ignores policies. Activate a file only after every
  mining process runs 0.6.20 ([PB-067-OPS](playbooks/system/rag-067-extraction-policy.md), part B).
- Policy changes never re-mine or rewrite stored knowledge.
- The measured examples use a mock provider; they show enforcement and replay,
  not extraction quality ([benchmark](benchmarks/2026-11-01-extraction-policy/README.md)).

Sample evaluation preserves line breaks and spacing for exact-quote grounding.
Source identifiers must be bounded, secret-free strings, and timestamps must be
valid optional ISO times. Invalid metadata is refused without echoing its value;
recognized credentials in prose are redacted. Validation error locations are
redacted and bounded too, including unknown quoted TOML keys.
