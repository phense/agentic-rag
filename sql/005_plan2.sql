-- 005_plan2.sql — Plan 2: queue backoff/debounce, DB-enforced refute
-- justification (the trigger promised in 001), default privileges for
-- future tables (Plan-1 review gate), deterministic signal recall.

ALTER TABLE mining_queue
    ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX idx_queue_due ON mining_queue(status, next_attempt_at);

-- audit lookups used by the refute trigger and rag review / last-curation
CREATE INDEX idx_audit_doc ON audit_log(document_id);
CREATE INDEX idx_audit_op_at ON audit_log(op, at DESC);

-- spec §7: refuting a document requires reason+evidence+timestamp (001 CHECK)
-- AND a supersedes/contradicts edge AND an audit row — enforced at COMMIT,
-- so the refuting transaction can write all three in any order.
CREATE FUNCTION enforce_refute_justification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'refuted' THEN
        IF NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE (e.src_id = NEW.id OR e.dst_id = NEW.id)
              AND e.predicate IN ('supersedes', 'contradicts')
        ) THEN
            RAISE 'refuted document % lacks a supersedes/contradicts edge',
                NEW.slug;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM audit_log a
            WHERE a.document_id = NEW.id AND a.op = 'refute'
        ) THEN
            RAISE 'refuted document % lacks a refute audit row', NEW.slug;
        END IF;
    END IF;
    RETURN NULL;  -- AFTER trigger: return value ignored
END $$;

CREATE CONSTRAINT TRIGGER documents_refute_justified
    AFTER INSERT OR UPDATE OF status ON documents
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION enforce_refute_justification();

-- Tables added by LATER migrations (Plan-1 final-review gate): reader and
-- admin rights are uniform and inherit automatically. WRITER rights are
-- deliberately PER-TABLE (the §8 matrix: documents S/I/U, chunks
-- SELECT-only, audit_log append-only), so there must be NO blanket writer
-- default: pg_restore --clean recreates every table, default privileges
-- fire at CREATE and are ADDITIVE on top of the dump's ACLs — a writer
-- default would silently re-grant UPDATE on audit_log and INSERT on
-- chunks at every restore (observed live during Task 4). Every migration
-- that adds a table MUST grant rag_writer explicitly (grants template).
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO rag_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO rag_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO rag_writer, rag_admin;

-- Deterministic signal recall for the UserPromptSubmit hook: the caller
-- passes a sanitized OR-tsquery string ('tok1 | tok2 | ...'); only active
-- dtype='signal' documents match. English config: error signatures are
-- ASCII/English by construction.
CREATE OR REPLACE FUNCTION recall_signals(q_or text, k int DEFAULT 3)
RETURNS TABLE (slug text, title text, verified_at timestamptz,
               created_at timestamptz, score real)
LANGUAGE sql STABLE AS $$
SELECT d.slug, d.title, d.verified_at, d.created_at,
       max(ts_rank_cd(c.tsv_en, to_tsquery('english', q_or))) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'active' AND d.dtype = 'signal'
  AND c.tsv_en @@ to_tsquery('english', q_or)
GROUP BY d.slug, d.title, d.verified_at, d.created_at
ORDER BY score DESC, d.slug
LIMIT k
$$;
