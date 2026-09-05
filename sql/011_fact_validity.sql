-- Atomic facts reuse document chunks and typed edges; source documents are untouched.
CREATE TABLE fact_assertions (
    document_id uuid PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    entity text NOT NULL,
    attribute text NOT NULL,
    value text NOT NULL,
    event_at timestamptz,
    expires_at timestamptz,
    relation text NOT NULL CHECK (relation IN ('assertion','extension','replacement')),
    disposition text NOT NULL CHECK (disposition IN ('accepted','review')),
    review_reason text,
    evidence jsonb NOT NULL,
    CHECK (expires_at IS NULL OR (event_at IS NOT NULL AND expires_at > event_at))
);
CREATE INDEX fact_assertions_key ON fact_assertions(entity,attribute,event_at);
GRANT SELECT ON fact_assertions TO rag_reader;
GRANT SELECT,INSERT ON fact_assertions TO rag_writer;
GRANT ALL ON fact_assertions TO rag_admin;

CREATE TABLE assertion_sources (
    document_id uuid NOT NULL REFERENCES fact_assertions(document_id) ON DELETE CASCADE,
    source_hash text NOT NULL,
    evidence jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(document_id,source_hash)
);
GRANT SELECT ON assertion_sources TO rag_reader;
GRANT SELECT,INSERT ON assertion_sources TO rag_writer;
GRANT ALL ON assertion_sources TO rag_admin;

CREATE FUNCTION assertion_eligible(p_id uuid, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT p_history OR NOT EXISTS (
    SELECT 1 FROM fact_assertions a JOIN documents d ON d.id=a.document_id
    WHERE a.document_id=p_id AND (
        a.disposition <> 'accepted' OR a.event_at IS NULL OR a.event_at > p_at
        OR (a.expires_at IS NOT NULL AND a.expires_at <= p_at)
        OR EXISTS (
            SELECT 1 FROM fact_assertions newer JOIN documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute
              AND nd.project_scope=d.project_scope
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at > a.event_at AND newer.event_at <= p_at
        )
    )
)
$$;

CREATE OR REPLACE FUNCTION hybrid_search_temporal(
    query_text text,
    query_vec  halfvec(1024) DEFAULT NULL,
    p_domain   text DEFAULT NULL,
    k          int  DEFAULT 8,
    p_scopes text[] DEFAULT NULL, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false
) RETURNS TABLE (
    document_id uuid, chunk_id uuid, title text, slug text,
    domain text, dtype text, snippet text, score double precision,
    verified_at timestamptz, provenance jsonb
) LANGUAGE sql STABLE AS $$
WITH vec AS (
    SELECT s.chunk_id, row_number() OVER (ORDER BY s.dist) AS rank
    FROM (
        SELECT c.id AS chunk_id, c.embedding <=> query_vec AS dist
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE query_vec IS NOT NULL AND c.embedding IS NOT NULL
          AND d.status = 'active' AND assertion_eligible(d.id,p_at,p_history)
          AND (p_domain IS NULL OR d.domain = p_domain)
          AND (p_scopes IS NULL OR d.project_scope = ANY(p_scopes))
        ORDER BY c.embedding <=> query_vec
        LIMIT 50
    ) s
),
ts_en AS (
    SELECT s.chunk_id, row_number() OVER (ORDER BY s.r DESC) AS rank
    FROM (
        SELECT c.id AS chunk_id,
               ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) AS r
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'active' AND assertion_eligible(d.id,p_at,p_history)
          AND (p_domain IS NULL OR d.domain = p_domain)
          AND (p_scopes IS NULL OR d.project_scope = ANY(p_scopes))
          AND c.tsv_en @@ websearch_to_tsquery('english', query_text)
        ORDER BY r DESC
        LIMIT 50
    ) s
),
ts_de AS (
    SELECT s.chunk_id, row_number() OVER (ORDER BY s.r DESC) AS rank
    FROM (
        SELECT c.id AS chunk_id,
               ts_rank_cd(c.tsv_de, websearch_to_tsquery('german', query_text)) AS r
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'active' AND assertion_eligible(d.id,p_at,p_history)
          AND (p_domain IS NULL OR d.domain = p_domain)
          AND (p_scopes IS NULL OR d.project_scope = ANY(p_scopes))
          AND c.tsv_de @@ websearch_to_tsquery('german', query_text)
        ORDER BY r DESC
        LIMIT 50
    ) s
),
fused AS (
    SELECT u.chunk_id, (sum(1.0 / (60 + u.rank)))::double precision AS score
    FROM (
        SELECT * FROM vec
        UNION ALL SELECT * FROM ts_en
        UNION ALL SELECT * FROM ts_de
    ) u
    GROUP BY u.chunk_id
)
SELECT d.id, c.id, d.title, d.slug, d.domain, d.dtype,
       left(c.content, 400), f.score, d.verified_at, d.provenance
FROM fused f
JOIN chunks c ON c.id = f.chunk_id
JOIN documents d ON d.id = c.document_id
ORDER BY f.score DESC, d.slug
LIMIT k
$$;

CREATE OR REPLACE FUNCTION recall_signals_scoped(q_or text, k int DEFAULT 3, p_scopes text[] DEFAULT NULL)
RETURNS TABLE (slug text, title text, verified_at timestamptz,
               created_at timestamptz, score real)
LANGUAGE sql STABLE AS $$
SELECT d.slug, d.title, d.verified_at, d.created_at,
       max(ts_rank_cd(c.tsv_en, to_tsquery('english', q_or))) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'active' AND assertion_eligible(d.id) AND d.dtype = 'signal'
  AND (p_scopes IS NULL OR d.project_scope = ANY(p_scopes))
  AND c.tsv_en @@ to_tsquery('english', q_or)
GROUP BY d.slug, d.title, d.verified_at, d.created_at
ORDER BY score DESC, d.slug
LIMIT k
$$;

-- 004_graph.sql — real traversal over the edges table (recursive CTEs).

-- Undirected breadth exploration up to p_depth hops, cycle-safe per branch.
CREATE OR REPLACE FUNCTION graph_neighbors_temporal(
    p_id uuid, p_depth int DEFAULT 1, p_predicates text[] DEFAULT NULL, p_scopes text[] DEFAULT NULL, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false
) RETURNS TABLE (
    edge_id uuid, src_id uuid, dst_id uuid, predicate text,
    evidence text, confidence text, depth int
) LANGUAGE sql STABLE AS $$
WITH RECURSIVE hops(edge_id, src_id, dst_id, predicate, evidence, confidence,
                    depth, frontier, visited) AS (
    SELECT e.id, e.src_id, e.dst_id, e.predicate, e.evidence, e.confidence, 1,
           CASE WHEN e.src_id = p_id THEN e.dst_id ELSE e.src_id END,
           ARRAY[p_id, CASE WHEN e.src_id = p_id THEN e.dst_id ELSE e.src_id END]
    FROM edges e
    WHERE (e.src_id = p_id OR e.dst_id = p_id) AND e.dst_id IS NOT NULL AND assertion_eligible(e.src_id,p_at,p_history) AND assertion_eligible(e.dst_id,p_at,p_history) AND (p_history OR (e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at)))
      AND (p_predicates IS NULL OR e.predicate = ANY (p_predicates)) AND (p_scopes IS NULL OR (EXISTS (SELECT 1 FROM documents ds WHERE ds.id=e.src_id AND ds.project_scope=ANY(p_scopes)) AND EXISTS (SELECT 1 FROM documents dd WHERE dd.id=e.dst_id AND dd.project_scope=ANY(p_scopes))))
  UNION ALL
    SELECT e.id, e.src_id, e.dst_id, e.predicate, e.evidence, e.confidence,
           h.depth + 1,
           CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END,
           h.visited || CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END
    FROM hops h
    JOIN edges e ON (e.src_id = h.frontier OR e.dst_id = h.frontier)
    WHERE h.depth < p_depth AND e.dst_id IS NOT NULL AND assertion_eligible(e.src_id,p_at,p_history) AND assertion_eligible(e.dst_id,p_at,p_history) AND (p_history OR (e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at)))
      AND (p_predicates IS NULL OR e.predicate = ANY (p_predicates)) AND (p_scopes IS NULL OR (EXISTS (SELECT 1 FROM documents ds WHERE ds.id=e.src_id AND ds.project_scope=ANY(p_scopes)) AND EXISTS (SELECT 1 FROM documents dd WHERE dd.id=e.dst_id AND dd.project_scope=ANY(p_scopes))))
      AND NOT (CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END
               = ANY (h.visited))
)
SELECT DISTINCT ON (edge_id) edge_id, src_id, dst_id, predicate,
       evidence, confidence, depth
FROM hops
ORDER BY edge_id, depth
$$;

-- Shortest path (BFS by construction: shorter paths generated first).
CREATE OR REPLACE FUNCTION graph_path_temporal(
    p_from uuid, p_to uuid, p_max_depth int DEFAULT 4, p_scopes text[] DEFAULT NULL, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false
) RETURNS TABLE (step int, doc_id uuid, via_predicate text)
LANGUAGE sql STABLE AS $$
WITH RECURSIVE walk(path, preds) AS (
    SELECT ARRAY[p_from], ARRAY[]::text[] WHERE assertion_eligible(p_from,p_at,p_history) AND (p_scopes IS NULL OR EXISTS (SELECT 1 FROM documents d WHERE d.id=p_from AND d.project_scope=ANY(p_scopes)))
  UNION ALL
    SELECT w.path || n.next_id, w.preds || e.predicate
    FROM walk w
    JOIN edges e ON (e.src_id = w.path[array_length(w.path, 1)]
                  OR e.dst_id = w.path[array_length(w.path, 1)])
    CROSS JOIN LATERAL (
        SELECT CASE WHEN e.src_id = w.path[array_length(w.path, 1)]
                    THEN e.dst_id ELSE e.src_id END AS next_id
    ) n
    WHERE e.dst_id IS NOT NULL AND assertion_eligible(e.src_id,p_at,p_history) AND assertion_eligible(e.dst_id,p_at,p_history) AND (p_history OR (e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at))) AND (p_scopes IS NULL OR (EXISTS (SELECT 1 FROM documents ds WHERE ds.id=e.src_id AND ds.project_scope=ANY(p_scopes)) AND EXISTS (SELECT 1 FROM documents dd WHERE dd.id=e.dst_id AND dd.project_scope=ANY(p_scopes))))
      AND n.next_id IS NOT NULL
      AND NOT n.next_id = ANY (w.path)
      AND w.path[array_length(w.path, 1)] <> p_to
      AND array_length(w.path, 1) <= p_max_depth
),
found AS (
    SELECT path, preds
    FROM walk
    WHERE path[array_length(path, 1)] = p_to
    ORDER BY array_length(path, 1)
    LIMIT 1
)
SELECT i AS step, f.path[i] AS doc_id,
       CASE WHEN i = 1 THEN NULL ELSE f.preds[i - 1] END AS via_predicate
FROM found f, generate_subscripts(f.path, 1) AS i
ORDER BY i
$$;



CREATE OR REPLACE FUNCTION hybrid_search_scoped(query_text text, query_vec halfvec(1024) DEFAULT NULL, p_domain text DEFAULT NULL, k int DEFAULT 8, p_scopes text[] DEFAULT NULL) RETURNS TABLE (document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,snippet text,score double precision,verified_at timestamptz,provenance jsonb) LANGUAGE sql STABLE AS $$ SELECT * FROM hybrid_search_temporal(query_text,query_vec,p_domain,k,p_scopes) $$;

CREATE OR REPLACE FUNCTION hybrid_search(query_text text, query_vec halfvec(1024) DEFAULT NULL, p_domain text DEFAULT NULL, k int DEFAULT 8) RETURNS TABLE (document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,snippet text,score double precision,verified_at timestamptz,provenance jsonb) LANGUAGE sql STABLE AS $$ SELECT * FROM hybrid_search_temporal(query_text,query_vec,p_domain,k,NULL) $$;

-- Explicit legacy reactivation starts a new evidence epoch.
ALTER TABLE documents ADD COLUMN reactivated_at timestamptz;
CREATE FUNCTION stamp_reactivation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'active' AND NEW.status = 'active' THEN
        NEW.reactivated_at = clock_timestamp();
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER documents_reactivated BEFORE UPDATE ON documents
FOR EACH ROW EXECUTE FUNCTION stamp_reactivation();
