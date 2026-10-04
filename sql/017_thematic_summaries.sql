-- Rebuildable views only. No canonical document, source, pin or queue rewrite.
CREATE TABLE thematic_summaries (
    selection_key text PRIMARY KEY,
    config_key text NOT NULL,
    revision text NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    entries jsonb NOT NULL DEFAULT '[]',
    CHECK (jsonb_typeof(entries) = 'array' AND jsonb_array_length(entries) <= 24),
    CHECK (octet_length(entries::text) <= 262144)
);
GRANT SELECT ON thematic_summaries TO rag_reader;
GRANT SELECT,INSERT,UPDATE ON thematic_summaries TO rag_writer;
GRANT ALL ON thematic_summaries TO rag_admin;
