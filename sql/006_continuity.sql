-- 006_continuity.sql — durable, audited state at a compaction boundary.
-- Checkpoints are operational state, not general RAG documents: they have a
-- separate lifecycle and retain superseded history without a delete path.

CREATE TABLE continuation_checkpoints (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id             text NOT NULL CHECK (btrim(session_id) <> ''),
    turn_id                text,
    cursor                 text NOT NULL CHECK (btrim(cursor) <> ''),
    transcript_fingerprint text,
    source                 text NOT NULL,
    trigger                text,
    cwd                    text,
    project_root           text,
    git                    jsonb NOT NULL DEFAULT '{}',
    snapshot               jsonb NOT NULL DEFAULT '{}',
    enrichment             jsonb NOT NULL DEFAULT '{}',
    "references"           jsonb NOT NULL DEFAULT '[]',
    warnings               jsonb NOT NULL DEFAULT '[]',
    state                  text NOT NULL DEFAULT 'open'
                           CHECK (state IN ('open', 'superseded', 'completed')),
    quality                text NOT NULL DEFAULT 'snapshot'
                           CHECK (quality IN ('snapshot', 'enriched')),
    compacted_at           timestamptz,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, cursor),
    CHECK (jsonb_typeof(git) = 'object'),
    CHECK (jsonb_typeof(snapshot) = 'object'),
    CHECK (jsonb_typeof(enrichment) = 'object'),
    CHECK (jsonb_typeof("references") = 'array'),
    CHECK (jsonb_typeof(warnings) = 'array')
);

CREATE INDEX idx_continuation_checkpoints_session_open
    ON continuation_checkpoints(session_id, state, updated_at DESC);
CREATE INDEX idx_continuation_checkpoints_project_open
    ON continuation_checkpoints(project_root, state, updated_at DESC)
    WHERE project_root IS NOT NULL;

-- Extend the existing constrained queue vocabulary without granting the writer
-- any new broad queue capability.
ALTER TABLE mining_queue DROP CONSTRAINT mining_queue_kind_check;
ALTER TABLE mining_queue ADD CONSTRAINT mining_queue_kind_check
    CHECK (kind IN ('mine', 'curate', 'backup', 'embed', 'checkpoint_enrich'));

-- Checkpoint gateway audit events intentionally leave document_id NULL: the
-- checkpoint UUID is present in the human/audit-readable summary.
GRANT SELECT, INSERT, UPDATE ON continuation_checkpoints TO rag_writer;
GRANT SELECT ON continuation_checkpoints TO rag_reader;
