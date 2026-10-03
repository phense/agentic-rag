---
id: RAG-5.8-reference
title: Entity identities and scoped aliases
type: reference
doc_id: standalone
readers: [operators, client-developers]
status: drafted
version: source017 to candidate018
depends_on: []
assets: []
last_reviewed: unreviewed
summary: Exact scoped entity evidence, confirmed aliases and reversible relation review.
---

# Entity identities and scoped aliases

## Overview

`rag entity resolve` and `memory_entity` read original assertions under an exact
name and its confirmed direct aliases. Each fact keeps its document/chunk citation,
original entity/attribute/value, event time and source version. Existing search,
assertion writes, mining, graph and historical keys retain their contracts.
[PB-5.8](playbooks/entity-identities.md) describes operator review and upgrade/recovery.

## Terms

| Term | Meaning |
| --- | --- |
| Exact identity | Deterministic UUID for one exact project scope, topic domain and name. Case and spelling remain significant. |
| Alias | Alternate exact name explicitly linked to an anchor by an operator using original source evidence. |
| Anchor | One identity with zero or more direct aliases. Aliases cannot simultaneously be anchors or point at competing anchors. |
| Attachment | Audited derived index mapping an original assertion to its current exact identity. Explicit backfill persists it. |
| Confirmed span | The exact original source key and quote hash inspected for this relation. A later attached source cannot inherit confirmation. |
| Project scope | Applicability selection, separate from PostgreSQL privileges. Entity reads select exactly one known scope. |
| Domain | Topic partition. A domain and an actor name do not implement per-user access control. |

## CLI contracts

Every entity command emits JSON. The canonical environment can execute a candidate
with `PYTHONPATH` selecting that checkout, from its directory, using the canonical
`.venv/bin/python -m agentic_rag.cli`. Do not redirect the installed editable package.

| Command | Required inputs | Optional inputs / effect |
| --- | --- | --- |
| `rag entity resolve NAME` | `--domain`, `--project` or explicit `--scope global` | `--attribute`, `--as-of`, `--history`, `--context-chars`; reader-only, no provider |
| `rag entity alias` | `--alias`, `--target`, `--domain`, known scope, `--namespace`, `--source-id`, `--quote`, `--effective-at` | `--role user\|assistant\|unknown`, `--complete`, `--confirm`; default review suggestion |
| `rag entity review DOCUMENT_UUID` | `--state accepted\|revoked`, `--reason` | Audited, reversible review; rechecks support, boundary and competing anchors |
| `rag entity backfill` | None | `--limit 1–500`, default100; one atomic batch, repeat until `remaining=0` |

For an existing assertion source, use its actual namespace, source ID and original
quote. Manual input is an operator attestation. The system checks membership fields
and current source trust; it cannot prove that an attested quote is true.

## MCP contracts

| Tool | Privilege | Contract |
| --- | --- | --- |
| `memory_entity` | Main and read-only | Same selector/output as resolve; strict boolean history and integer budget |
| `memory_entity_alias` | Authorized main only | Required evidence dict: namespace, source_id, role, quote, complete; explicit `confirm=true` |
| `memory_entity_alias_review` | Authorized main only | Relation evidence document UUID, accepted/revoked, reason |

Fresh candidate servers expose10 read tools and18 total tools. The eight main-only
writes include the six existing tools and the two alias tools. Source017 remains
9/15; long-lived processes keep loaded code until reconnect. No settings rewrite,
provider switch or scheduler change is part of this feature.

## Selection and trust

| Condition | Observable result |
| --- | --- |
| Known project | Exact canonical project only; global facts and ancestor scopes are not folded into an entity identity |
| Explicit global | Global identity only; no project alias bridge |
| Unknown/missing applicability | Alias/read selector rejected; backfill reports unresolved assertions |
| Different domain/project | Separate identity UUIDs and relation sets, including identical names |
| Unconfirmed, incomplete, assistant or unsupported relation | Review suggestion; no expansion |
| Original span removed/refuted/unreviewed or evidence-document boundary changed | Expansion withheld immediately; relation/source history retained |
| Competing anchor, cycle or transitive chain | Review-only; revoke the mistaken relation before repairing the star |
| Same request repeated | Reuse its relation document and IDs; accepted no-change retry adds no audit |
| Explicit revocation | Separate names on the next read; original assertions and audit remain |

Alias effective time is inclusive and must have a timezone. `as_of` applies the
same valid time to relation and fact selection. History uses currently active,
reviewed alias support and includes trusted accepted fact events up to now;
expired and superseded facts carry explicit labels. It does not reconstruct
previous trust or arbitrary document edits. Future facts/relations stay out.

Current selection combines accepted assertions across the confirmed star. An
explicit later replacement suppresses earlier values of that attribute, including
when the replacement expires or its source is withdrawn; the earlier value does
not revive. Extensions coexist. Distinct current values without a decisive
replacement are exposed as ambiguous facts and withheld from answer context.
Source trust is evaluated independently of legacy cross-domain suppression.

## Output and limits

| Field / limit | Meaning |
| --- | --- |
| `identity_id`, per-fact `identity_id` | Stable exact UUID; the top ID is the anchor when confirmed expansion applies |
| `identity_persisted` | Whether the identity row already exists; unindexed old/new facts derive the same UUID without a write |
| `names`, `name_count` | At most33 serialized names and full distinct-name count |
| `links`, `suggestions` | At most32 accepted/support-qualified links and32 review relations; omitted review relations disclosed |
| `facts` | At most100 original assertion excerpts with document/chunk IDs, exact spans, temporal/conflict labels and tuple versions |
| `context` | Whole fact entries only; default4800 characters, allowed1000–12000 |
| `status` | resolved, ambiguous, limited or unavailable; warnings disclose why context is withheld |
| Bounds exceeded | No incomplete current answer; facts/context withheld when link/fact enumeration exceeds its bound |
| Optional SQL failure/missing018 | Rollback-safe unavailable result; exact-name search/get remain available |
| SQL budget | Preserves shorter caller settings, caps statement waits at5s and lock waits at2s; scan cost still depends on corpus size |

Attachments never override current original scope/domain/name. Domain repair can
make an attachment stale; reads use raw originals and explicit backfill repairs only
the derived index. No read side effect or background identity inference occurs.

Legacy exact-key assertion saves can reuse an existing fact across domains, and the
legacy validity predicate can suppress it across domains. These existing contracts
are unchanged. The entity API isolates retained raw facts by domain; it cannot
recover a source assertion that an earlier client already deduplicated into another
domain. Same-name generations within one exact boundary also need explicit operator
repair or distinct qualified names; no embedding-based merge is performed.
