CREATE OR REPLACE FUNCTION hybrid_search_candidates(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE SET hnsw.ef_search = 256 AS $$
WITH matches_en AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.tsv_en FROM chunks c
 WHERE c.tsv_en @@ websearch_to_tsquery('english',query_text)
),
matches_de AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.tsv_de FROM chunks c
 WHERE c.tsv_de @@ websearch_to_tsquery('german',query_text)
),
eligible_documents AS MATERIALIZED (
 SELECT d.* FROM (
   SELECT document_id FROM matches_en UNION SELECT document_id FROM matches_de
 ) m JOIN LATERAL (
   SELECT d.id,d.slug FROM documents d
   WHERE d.id=m.document_id AND d.status='active'
     AND assertion_eligible(d.id,p_at,p_history)
     AND (p_domain IS NULL OR d.domain=p_domain)
     AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   OFFSET 0
 ) d ON true
),
vec AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric ASC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT pool.*,row_number() OVER(PARTITION BY document_id ORDER BY metric ASC,idx,id) AS within_document
     FROM (
       -- Distance-only ORDER BY retains the HNSW access path. Diversity is bounded
       -- by this ANN pool; deterministic tie keys apply after approximate selection.
       SELECT c.id,d.id AS document_id,d.slug,c.idx,c.embedding <=> query_vec AS metric
       FROM chunks c JOIN documents d ON d.id=c.document_id
       WHERE query_vec IS NOT NULL AND c.embedding IS NOT NULL AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
         AND (p_domain IS NULL OR d.domain=p_domain)
         AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
       ORDER BY c.embedding <=> query_vec LIMIT 256
     ) pool
   ) eligible WHERE within_document<=2
   ORDER BY metric ASC,slug,idx,id LIMIT 50
 ) bounded
),
ts_en AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) DESC,c.idx,c.id) AS within_document
     FROM matches_en c JOIN eligible_documents d ON d.id=c.document_id
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
ts_de AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_de, websearch_to_tsquery('german', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_de, websearch_to_tsquery('german', query_text)) DESC,c.idx,c.id) AS within_document
     FROM matches_de c JOIN eligible_documents d ON d.id=c.document_id
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
fused AS (
 SELECT chunk_id,sum(1.0/(60+rank))::double precision AS score
 FROM (SELECT * FROM vec UNION ALL SELECT * FROM ts_en UNION ALL SELECT * FROM ts_de) u
 GROUP BY chunk_id
)
SELECT d.id,c.id,d.title,d.slug,d.domain,d.dtype,left(c.content,4000),f.score,d.verified_at,d.provenance
FROM fused f JOIN chunks c ON c.id=f.chunk_id JOIN documents d ON d.id=c.document_id
ORDER BY f.score DESC,d.slug,c.idx,c.id LIMIT least(greatest(k,0),150)
$$;

CREATE OR REPLACE FUNCTION contextual_search_candidates(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE SET hnsw.ef_search = 256 AS $$
WITH matches_en AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.content,x.source_hash,x.tsv_en
 FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id
 WHERE x.version=1 AND x.tsv_en @@ websearch_to_tsquery('english',query_text)
),
matches_de AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.content,x.source_hash,x.tsv_de
 FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id
 WHERE x.version=1 AND x.tsv_de @@ websearch_to_tsquery('german',query_text)
),
eligible_documents AS MATERIALIZED (
 SELECT d.* FROM (
   SELECT document_id FROM matches_en UNION SELECT document_id FROM matches_de
 ) m JOIN LATERAL (
   SELECT d.id,d.slug,d.title,d.body,d.project_scope FROM documents d
   WHERE d.id=m.document_id AND d.status='active'
     AND assertion_eligible(d.id,p_at,p_history)
     AND (p_domain IS NULL OR d.domain=p_domain)
     AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   OFFSET 0
 ) d ON true
),
vec AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric ASC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT pool.*,row_number() OVER(PARTITION BY document_id ORDER BY metric ASC,idx,id) AS within_document
     FROM (
       -- Distance-only ORDER BY retains the HNSW access path. Diversity is bounded
       -- by this ANN pool; deterministic tie keys apply after approximate selection.
       SELECT c.id,d.id AS document_id,d.slug,c.idx,x.embedding <=> query_vec AS metric
       FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1 AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
       WHERE query_vec IS NOT NULL AND x.embedding IS NOT NULL AND x.model_digest=p_model AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
         AND (p_domain IS NULL OR d.domain=p_domain)
         AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
       ORDER BY x.embedding <=> query_vec LIMIT 256
     ) pool
   ) eligible WHERE within_document<=2
   ORDER BY metric ASC,slug,idx,id LIMIT 50
 ) bounded
),
ts_en AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) DESC,c.idx,c.id) AS within_document
     FROM matches_en c JOIN eligible_documents d ON d.id=c.document_id
     WHERE c.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
ts_de AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_de, websearch_to_tsquery('german', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_de, websearch_to_tsquery('german', query_text)) DESC,c.idx,c.id) AS within_document
     FROM matches_de c JOIN eligible_documents d ON d.id=c.document_id
     WHERE c.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
fused AS (
 SELECT chunk_id,sum(1.0/(60+rank))::double precision AS score
 FROM (SELECT * FROM vec UNION ALL SELECT * FROM ts_en UNION ALL SELECT * FROM ts_de) u
 GROUP BY chunk_id
)
SELECT d.id,c.id,d.title,d.slug,d.domain,d.dtype,left(c.content,4000),f.score,d.verified_at,d.provenance
FROM fused f JOIN chunks c ON c.id=f.chunk_id JOIN documents d ON d.id=c.document_id
ORDER BY f.score DESC,d.slug,c.idx,c.id LIMIT least(greatest(k,0),150)
$$;
