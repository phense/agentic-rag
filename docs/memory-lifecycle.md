---
id: C-066
title: Memory lifecycle
type: reference
doc_id: standalone
readers: [operators who consolidate memories, agent users who read search results]
status: draft
version: 0.6.19 (schema031)
depends_on: [claim-evidence.md, fact-validity.md, 05-session-mining-and-curation.md]
assets: []
last_reviewed: 2026-11-01
summary: How to mark one memory as a duplicate, extension, replaced version or contradiction of another without changing either, what search and get show afterwards, and how to undo a decision.
---

# Memory lifecycle

Reader: someone who stores memories with agentic-rag and wants fewer repeated or
outdated answers, without losing any original. Upgrading an existing store is
described in [PB-066-OPS](playbooks/system/rag-066-memory-lifecycle.md).

Over time a store collects the same note twice, a short note next to a fuller
one, or an old setting next to its replacement. Deleting the extra copy loses its
history and its evidence. A **lifecycle decision** works like a sticky note on a
filing cabinet instead: "use the other folder". The folder stays where it was;
anyone can still open it, and removing the note restores the old view.

Technically, a decision is a separate audited record that names a **member** (the
memory to step back) and a **target** (the memory that answers instead). It never
edits, archives or deletes either memory, its chunks, claims, evidence, sources,
links or pins. The document version `ev1:…` and the source version `src1:…` stay
the same.

## The five operations

| Operation | Use it when | Proof | Effect in the current view |
|---|---|---|---|
| `exact_duplicate` | Both memories have the same title, body, type and claim identity | Structural, checked by preview | Member hidden |
| `semantic_duplicate` | Same knowledge in other words | Your judgement (`reviewed`) | Member hidden |
| `extension` | The target says everything the member says, and more | Your judgement (`reviewed`) | Member hidden |
| `replacement` | The target is a newer version of the same fact | Source event order: the target's qualifying source must be later than the member's; plus `reviewed` | Member hidden from the target's event time on |
| `contradiction` | The two disagree and you cannot say which is right | Your record | Nothing hidden; both appear in `rag review` |

Both memories must be active originals of the same domain and the same known
project (or both global). Fact assertions follow their own replacement rules
through `memory_assert` and are refused here (`assertion_managed`), as are
refuted, withdrawn or unqualified memories (`not_current`).

Decisions stay one step deep: a member cannot also be a target, and a target
cannot be a member somewhere else (`chain_conflict`). A target collects at most
500 members. Each member has at most one active decision (`already_active`).

## Decide in three steps

1. Preview the pair. Preview reads only; it never writes and never calls a model.

   ```bash
   rag lifecycle preview MEMBER TARGET                         # exact copies
   rag lifecycle preview MEMBER TARGET --operation extension   # anything else
   ```

   The output names the classification, the proof, the reason any operation is
   not allowed, and the version `lv1:…` of both memories.
2. Read both texts yourself, then apply with the versions from step 1:

   ```bash
   rag lifecycle apply MEMBER TARGET --operation extension --reviewed \
     --member-version lv1:… --target-version lv1:… --reason "rich note covers the short one"
   ```

   `--reviewed` states that you checked a judgement the tool cannot prove; it is
   required for `semantic_duplicate`, `extension` and `replacement`. If either
   memory, its evidence or its decisions changed since the preview, the apply
   stops with `stale_version` and writes nothing.
3. Check the result:

   ```bash
   rag lifecycle show MEMBER           # relationship: hiding, replaced or contested
   rag search "query" --view current   # the member is gone
   ```

Agents and central clients use the same steps through `memory_lifecycle_preview`,
`memory_lifecycle_apply` and `memory_lifecycle` ([reference](11-reference-cli-and-mcp.md#lifecycle-tools)).
A retry with the same inspected versions and reason returns the existing decision
and writes nothing. An optional request key makes that explicit; reusing it for a
different request fails with `replay_mismatch`.

## What readers see

Search, research, get, neighbors and path accept a **view**:

| View | Shows |
|---|---|
| omitted or `current` (`latest` is the same) | Hides members of active duplicate, extension and replacement decisions |
| `include_merged` | Shows merged duplicates and extensions again; replaced memories stay hidden |
| `historical` | Qualified past versions, including replaced and merged ones; refuted, withdrawn and future memories stay excluded |

The selection happens inside the database before the result limit, so asking for
one hit (`k=1`) still returns the target, never an empty answer. An agent that
asks without a view gets the current view in search. `rag get MEMBER` without a
view still shows the member itself; `rag get MEMBER --view current` answers with
the target and reports `resolution: canonical`.

Derived results follow the current view too: profiles, thematic summaries,
entity views and session context no longer use a hidden member, and a
synthesized pattern that cites one is withheld.

## When the memories change later

A duplicate or extension holds only while both memories stay as they were when
you decided, and while the target is still current. Edit either memory, change
or withdraw a source, or refute the target, and the member answers again by
itself. `rag lifecycle show` then lists the relationship as `stale`, and
`rag review` lists the decision under *lifecycle review*. To merge again, correct
the stale decision and decide anew.

A replacement is different. Once its event time has passed it keeps the old
version out of the current view, even if the target is later refuted or deleted;
`show` then reports `canonical_unavailable` and never reveals the deleted target.
Correct the decision if the old memory should answer again.

## Undo a decision

```bash
rag lifecycle correct DECISION --revision 1 --reason "kept both on purpose"
rag lifecycle history MEMBER
```

The decision becomes `corrected`; history keeps both events and the audit log has
one row per event. With `--json --limit 20`, history returns `items`, `more` and
a continuation `cursor`; pass that cursor to `rag lifecycle history MEMBER
--cursor CURSOR --json` for the next page. The `memory_lifecycle` tool pages
history when `history=true`, and canonical members otherwise. Detail returns at
most 20 `as_member` relationships and sets `as_member_more` when older ones exist;
use history to inspect the older events.

Correcting restores visibility only: a memory that was refuted
or whose source was withdrawn in the meantime stays excluded.

## Automatic curation

The automatic curation pass archives an exact copy and keeps the older memory.
Since 0.6.19 it treats two memories as copies only when title, type and body are
all equal within one domain and known project. Version 0.6.18 also archived
memories whose titles differed, such as "Build server alpha port" and "Build
server beta port" with the same sentence. While any process still runs 0.6.18,
give it `[curation] budget = 0` ([configuration](06-configuration-reference.md#curation)).
Automatic curation never creates lifecycle decisions.

## Limits

- No decision is made automatically. Preview proves only identical copies and the
  order of source events; whether two texts mean the same is your judgement.
- The published measurement in
  [docs/benchmarks/2026-10-31-memory-lifecycle](benchmarks/2026-10-31-memory-lifecycle/README.md)
  uses a small hand-labelled synthetic corpus. It checks the deterministic rules,
  not the quality of any model.
- Every search hit that is a member of a duplicate or extension decision costs an
  extra check. In the synthetic worst case, where all 300 matches of a broad query
  were merged members, that query took about 0.65 s instead of 0.27 s.
- A database client that reads the tables directly with SQL sees the target id
  of a decision it may see through the member. The tools never return a target
  the caller cannot read.
- Restoring a backup made before the upgrade loses every later write, decisions
  included.

## Terms

| Term | Meaning |
|---|---|
| member | The memory that steps back in the current view |
| target, canonical | The memory that answers instead |
| `lv1:` version | The version of a memory including its lifecycle decisions; apply and correct are bound to it |
| relationship | How a decision acts now: `hiding`, `replaced`, `contested`, `stale` or `canonical_unavailable` |
| view | Which memories a read considers: `current`, `include_merged` or `historical` |
