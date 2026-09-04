# What’s New in 0.4.0

agentic-rag 0.4.0 brings compaction continuity to Claude Code, bound to
Claude's own hook contract. The provider-neutral checkpoint store from 0.3.0
is reused; a thin Claude adapter replaces the three-hook legacy install.

## Claude compaction continuity

The default `rag install` now wires six lifecycle hooks into
`~/.claude/settings.json`:

- `PreCompact` (`manual|auto`, 3 s) persists the deterministic checkpoint,
  queues enrichment, and then prints the versioned compact instructions.
  Claude appends a PreCompact hook's stdout to its compaction prompt, so every
  compaction — automatic or manual — is guided without `/compact <text>`.
- `PostCompact` (`manual|auto`, 3 s) marks the boundary and stores the
  `<summary>` block of Claude's own `compact_summary` (its `<analysis>`
  scratch block is discarded) as a bounded, secret-stripped **handoff** on
  the checkpoint (default 8,000 characters; over the bound the middle is cut
  out so the objective and the next step both survive). It never injects
  context.
- `SessionStart` restores the checkpoint; on the next `startup`/`resume` it
  includes the handoff with a CURRENT/HISTORICAL age label. (Right after a
  compaction Claude Code runs `SessionStart` and `PostCompact` concurrently,
  so that first injection usually predates the handoff — Claude's own summary
  is still in context then.) The whole injected context is capped at 9,500
  characters by default (Claude drops anything over 10,000 per hook); the
  checkpoint is shortened into the remaining budget before any section is
  dropped, and every cut is announced.
- `SessionEnd` (1 s) queues the final transcript delta for every Claude
  reason (`clear`, `resume`, `logout`, `prompt_input_exit`, `other`). Claude
  allows 1.5 s for all SessionEnd hooks together; `Stop` remains the
  guaranteed enqueue path.

## Managed 1M/500K policy

The installer sets `autoCompactWindow = 500000` — a token count, capped by
the model's window. With a `[1m]` model such as `claude-fable-5-1[1m]` that
means a 1M context with automatic compaction at 500K, the same reserve logic
as the Codex 600K/500K policy. `model` is never rewritten; the installer warns
when the suffix is missing, when `autoCompactEnabled` is false, or when
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` /
`DISABLE_AUTO_COMPACT` / `DISABLE_COMPACT` override it. Verify with
`/autocompact`.

Claude auto-memory stays a complementary local layer, exactly like native
Codex memories. agentic-rag remains the canonical, auditable store.

## Safe installation

```bash
uv run rag init-db                 # migration 008 adds the handoff columns
uv run rag install --check         # preview; writes nothing
uv run rag install                 # unique backup + printed rollback command
```

Hooks are live-reloaded by Claude Code; review them with `/hooks`. Undo with
the printed `rag install --restore <record>` command, which is now
target-aware for Claude and Codex records.

## Upgrade notes

1. Pull, run `uv sync`, then `uv run rag init-db`.
2. `uv run rag install --check`, then `uv run rag install`.
3. In Claude Code: `/hooks` to review, `/autocompact` to confirm 500000 tokens
   from settings, then one manual `/compact` and `uv run rag status` to see
   `checkpoint handoff:`.
