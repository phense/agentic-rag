-- Additive read-only retrieval. Existing013/015 functions and indices stay intact.
CREATE FUNCTION filtered_vector_candidates(
 p_vector halfvec(1024),p_domain text DEFAULT NULL,p_scopes text[] DEFAULT NULL,
 p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL,
 p_context boolean DEFAULT false,p_exact_limit integer DEFAULT 4096,p_pool_limit integer DEFAULT 4096
) RETURNS TABLE(chunk_id uuid,rank bigint)
LANGUAGE plpgsql STABLE AS $$
BEGIN
 IF p_exact_limit IS NULL OR p_pool_limit IS NULL OR p_exact_limit NOT BETWEEN 1 AND 4096
 OR p_pool_limit NOT BETWEEN 256 AND 4096 OR p_context IS NULL THEN
  RAISE EXCEPTION 'invalid vector planning bounds';
 END IF;
 IF p_vector IS NULL OR l2_norm(p_vector)=0 OR (p_context AND p_model IS NULL) THEN RETURN; END IF;
 IF p_context THEN
  RETURN QUERY WITH eligible AS MATERIALIZED (
   -- If this bounded probe has <=exact_limit rows, it contains the complete set.
   -- Reuse it for exact distances: do not repeat source hashes or eligibility.
   SELECT c.id,d.id doc_id,d.slug,c.idx,x.embedding embedding
   FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1
   WHERE x.embedding IS NOT NULL AND l2_norm(x.embedding)>0 AND x.model_digest=p_model AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
    AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes)) LIMIT p_exact_limit+1
  ), exact_pool AS (
   SELECT e.id,e.doc_id,e.slug,e.idx,e.embedding <=> p_vector metric FROM eligible e
   WHERE (SELECT count(*) FROM eligible)<=p_exact_limit
  ), ann_pool AS MATERIALIZED (
   SELECT c.id,d.id doc_id,d.slug,c.idx,x.embedding <=> p_vector metric
   FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1
   WHERE (SELECT count(*) FROM eligible)>p_exact_limit AND x.embedding IS NOT NULL AND l2_norm(x.embedding)>0 AND x.model_digest=p_model AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
    AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   ORDER BY x.embedding <=> p_vector LIMIT p_pool_limit
  ), selected AS (SELECT * FROM exact_pool UNION ALL SELECT * FROM ann_pool),
  diverse AS (SELECT t.*,row_number() OVER(PARTITION BY doc_id ORDER BY metric,idx,id) within_document FROM selected t),
  bounded AS (SELECT * FROM diverse WHERE within_document<=2 ORDER BY metric,slug,idx,id LIMIT 50)
  SELECT b.id,row_number() OVER(ORDER BY metric,slug,idx,id) FROM bounded b;
 ELSE
  RETURN QUERY WITH eligible AS MATERIALIZED (
   -- If this bounded probe has <=exact_limit rows, it contains the complete set.
   -- Reuse it for exact distances: do not repeat source hashes or eligibility.
   SELECT c.id,d.id doc_id,d.slug,c.idx,c.embedding embedding
   FROM chunks c JOIN documents d ON d.id=c.document_id
   WHERE c.embedding IS NOT NULL AND l2_norm(c.embedding)>0
    AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes)) LIMIT p_exact_limit+1
  ), exact_pool AS (
   SELECT e.id,e.doc_id,e.slug,e.idx,e.embedding <=> p_vector metric FROM eligible e
   WHERE (SELECT count(*) FROM eligible)<=p_exact_limit
  ), ann_pool AS MATERIALIZED (
   SELECT c.id,d.id doc_id,d.slug,c.idx,c.embedding <=> p_vector metric
   FROM chunks c JOIN documents d ON d.id=c.document_id
   WHERE (SELECT count(*) FROM eligible)>p_exact_limit AND c.embedding IS NOT NULL AND l2_norm(c.embedding)>0
    AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   ORDER BY c.embedding <=> p_vector LIMIT p_pool_limit
  ), selected AS (SELECT * FROM exact_pool UNION ALL SELECT * FROM ann_pool),
  diverse AS (SELECT t.*,row_number() OVER(PARTITION BY doc_id ORDER BY metric,idx,id) within_document FROM selected t),
  bounded AS (SELECT * FROM diverse WHERE within_document<=2 ORDER BY metric,slug,idx,id LIMIT 50)
  SELECT b.id,row_number() OVER(ORDER BY metric,slug,idx,id) FROM bounded b;
 END IF;
END $$;

CREATE FUNCTION hybrid_search_candidates_planned(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
-- Keep the small SQL branches cached rather than repeatedly inlining their full plans.
-- This matches013/015 ef_search and is restored by PostgreSQL at function return.
LANGUAGE sql STABLE SET hnsw.ef_search=256 AS $$
WITH vec AS (
 SELECT * FROM filtered_vector_candidates(query_vec,p_domain,p_scopes,p_at,p_history,NULL,false)
),
ts_en AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, websearch_to_tsquery('english', query_text)) DESC,c.idx,c.id) AS within_document
     FROM chunks c JOIN documents d ON d.id=c.document_id
     WHERE c.tsv_en @@ websearch_to_tsquery('english',query_text) AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
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
     FROM chunks c JOIN documents d ON d.id=c.document_id
     WHERE c.tsv_de @@ websearch_to_tsquery('german',query_text) AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
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

CREATE FUNCTION contextual_search_candidates_planned(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
-- Keep the small SQL branches cached rather than repeatedly inlining their full plans.
-- This matches013/015 ef_search and is restored by PostgreSQL at function return.
LANGUAGE sql STABLE SET hnsw.ef_search=256 AS $$
WITH vec AS (
 SELECT * FROM filtered_vector_candidates(query_vec,p_domain,p_scopes,p_at,p_history,p_model,true)
),
ts_en AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(x.tsv_en, websearch_to_tsquery('english', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(x.tsv_en, websearch_to_tsquery('english', query_text)) DESC,c.idx,c.id) AS within_document
     FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1 AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
     WHERE x.tsv_en @@ websearch_to_tsquery('english',query_text) AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
ts_de AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(x.tsv_de, websearch_to_tsquery('german', query_text)) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(x.tsv_de, websearch_to_tsquery('german', query_text)) DESC,c.idx,c.id) AS within_document
     FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1 AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
     WHERE x.tsv_de @@ websearch_to_tsquery('german',query_text) AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
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

CREATE FUNCTION hybrid_search_contextual_planned(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE AS $$
 WITH combined AS (
 SELECT * FROM hybrid_search_candidates_planned(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history)
 UNION ALL
 SELECT * FROM contextual_search_candidates_planned(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history,p_model)
 ), fused AS (SELECT chunk_id,sum(score) AS score FROM combined GROUP BY chunk_id)
 SELECT d.id,c.id,d.title,d.slug,d.domain,d.dtype,left(c.content,4000),f.score,d.verified_at,d.provenance
 FROM fused f JOIN chunks c ON c.id=f.chunk_id JOIN documents d ON d.id=c.document_id
 ORDER BY f.score DESC,d.slug,c.idx,c.id LIMIT least(greatest(k,0),150)
$$;
