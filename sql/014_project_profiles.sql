-- Disposable references only; source text remains in canonical documents/evidence.
CREATE TABLE project_profiles (
    project_key text PRIMARY KEY,
    config_key text NOT NULL,
    revision text NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    stable_ids uuid[] NOT NULL DEFAULT '{}',
    recent_ids uuid[] NOT NULL DEFAULT '{}',
    CHECK (cardinality(stable_ids) <= 6 AND cardinality(recent_ids) <= 6),
    CHECK (array_position(stable_ids,NULL) IS NULL AND array_position(recent_ids,NULL) IS NULL)
);
GRANT SELECT ON project_profiles TO rag_reader;
GRANT SELECT,INSERT,UPDATE ON project_profiles TO rag_writer;
GRANT ALL ON project_profiles TO rag_admin;
ALTER TABLE mining_queue DROP CONSTRAINT mining_queue_kind_check;
ALTER TABLE mining_queue ADD CONSTRAINT mining_queue_kind_check
    CHECK (kind IN ('mine','embed','curate','backup','checkpoint_enrich','profile_refresh'));
