-- Accept model output durably, then apply all bounded batch effects atomically.
CREATE TABLE mining_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id text NOT NULL,
    input_cursor text NOT NULL DEFAULT '',
    output_cursor text NOT NULL,
    extraction jsonb NOT NULL,
    domains jsonb NOT NULL,
    project text,
    has_more boolean NOT NULL DEFAULT false,
    warnings jsonb NOT NULL DEFAULT '[]',
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz,
    UNIQUE (session_id, input_cursor),
    CHECK ((applied_at IS NULL) = (result IS NULL))
);
GRANT SELECT ON mining_batches TO rag_reader;
GRANT SELECT, INSERT, UPDATE ON mining_batches TO rag_writer;
GRANT ALL ON mining_batches TO rag_admin;
