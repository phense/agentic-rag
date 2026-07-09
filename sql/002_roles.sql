-- 002_roles.sql — three-role destruction protection (spec §8). Idempotent.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_reader') THEN
        CREATE ROLE rag_reader LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_writer') THEN
        CREATE ROLE rag_writer LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_admin') THEN
        CREATE ROLE rag_admin LOGIN;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO rag_reader, rag_writer, rag_admin',
                   current_database());
END $$;

GRANT USAGE ON SCHEMA public TO rag_reader, rag_writer, rag_admin;

-- reader: read everything, change nothing
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rag_reader;

-- writer: no DELETE/TRUNCATE/DROP anywhere (spec §8 matrix, verbatim).
-- Chunk regeneration happens ONLY through replace_chunks() below,
-- scoped to one document per call.
GRANT SELECT, INSERT, UPDATE ON domains, documents, edges, pins, mining_queue
    TO rag_writer;
GRANT SELECT ON chunks TO rag_writer;
GRANT SELECT, INSERT ON audit_log TO rag_writer;          -- append-only
GRANT SELECT ON schema_migrations TO rag_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO rag_writer;

-- admin: everything (used only by rag migrate / purge / restore)
GRANT ALL ON ALL TABLES IN SCHEMA public TO rag_admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO rag_admin;

-- Chunk replacement without any table-wide DELETE privilege (spec §8):
-- SECURITY DEFINER runs as the owner; the writer can only swap the chunks
-- of the ONE document it names, never empty the table.
CREATE OR REPLACE FUNCTION replace_chunks(
    p_document_id uuid, p_contents text[], p_embeddings text[]
) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE n int;
BEGIN
    DELETE FROM chunks WHERE document_id = p_document_id;
    INSERT INTO chunks(document_id, idx, content, embedding)
    SELECT p_document_id, t.i - 1, t.c,
           CASE WHEN t.e IS NULL THEN NULL ELSE t.e::halfvec END
    FROM unnest(p_contents, p_embeddings) WITH ORDINALITY AS t(c, e, i);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;
REVOKE ALL ON FUNCTION replace_chunks(uuid, text[], text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION replace_chunks(uuid, text[], text[])
    TO rag_writer, rag_admin;
