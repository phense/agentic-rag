-- 007_checkpoint_predecessor.sql — retain the enrichment delta start across
-- partial PreCompact delivery (snapshot committed, queue temporarily down).

ALTER TABLE continuation_checkpoints
    ADD COLUMN predecessor_cursor text;
