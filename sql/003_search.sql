-- 003_search.sql — deterministic hybrid search: RRF(vector, fts-en, fts-de), k=60.
CREATE OR REPLACE FUNCTION hybrid_search(
    query_text text,
    query_vec  halfvec(1024) DEFAULT NULL,
    p_domain   text DEFAULT NULL,
    k          int  DEFAULT 8
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
          AND d.status = 'active'
          AND (p_domain IS NULL OR d.domain = p_domain)
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
        WHERE d.status = 'active'
          AND (p_domain IS NULL OR d.domain = p_domain)
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
        WHERE d.status = 'active'
          AND (p_domain IS NULL OR d.domain = p_domain)
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
