-- 008_checkpoint_handoff.sql — retain the client's own bounded, secret-stripped
-- compact summary next to the deterministic checkpoint.  Claude Code delivers
-- it in PostCompact; Codex does not.  The existing UPDATE grant covers the new
-- columns; there is still no delete path.

ALTER TABLE continuation_checkpoints
    ADD COLUMN handoff    text,
    ADD COLUMN handoff_at timestamptz;
