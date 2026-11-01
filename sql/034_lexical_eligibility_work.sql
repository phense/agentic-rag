-- RAG-092: perform lexical matching before expensive truth/lifecycle checks.
-- All published migrations001..033 remain unchanged. Preserve SQL signatures,
-- invoker rights, RLS, eligibility, source hashes, diversity, scores and limits.
-- Matching CTEs can use GIN where the caller's RLS permits it. No operator is
-- marked leakproof and no security barrier is bypassed to force an index.
-- Match chunks first, then check each distinct matching document once in a
-- materialized CTE. OFFSET0 prevents a documents-first predicate scan; the
-- document bound does not depend on planner Memoize or chunks per document.
-- Vector branches keep correlated truth/source gates before the ANN limit.
-- Function-local jit=off avoids disproportionate compilation in scoped plans;
-- PostgreSQL restores the caller settings on both return and cancellation.


CREATE OR REPLACE FUNCTION hybrid_search_candidates(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE SET hnsw.ef_search = 256 SET jit=off AS $$
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
 WITH ann_pool AS MATERIALIZED (
   SELECT c.id,d.id AS document_id,d.slug,c.idx,c.embedding <=> query_vec AS metric
   FROM chunks c JOIN LATERAL (
     SELECT d.id,d.slug FROM documents d
     WHERE d.id=c.document_id AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
     OFFSET 0
   ) d ON true
   WHERE current_setting('rag.iterative_vectors',true)='on' AND query_vec IS NOT NULL AND c.embedding IS NOT NULL
   ORDER BY c.embedding <=> query_vec LIMIT 256
 ), exact_pool AS MATERIALIZED (
   -- A capped or unsupported ANN scan must not turn eligible results into gaps.
   -- Distance+0 deliberately selects exact sorting for this recovery branch.
   SELECT c.id,d.id AS document_id,d.slug,c.idx,c.embedding <=> query_vec AS metric
   FROM chunks c JOIN LATERAL (
     SELECT d.id,d.slug FROM documents d
     WHERE d.id=c.document_id AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
     OFFSET 0
   ) d ON true
   WHERE (SELECT count(*) FROM ann_pool)<256 AND query_vec IS NOT NULL AND c.embedding IS NOT NULL
   ORDER BY (c.embedding <=> query_vec)+0 LIMIT 256
 ), pool AS (
   SELECT * FROM ann_pool WHERE (SELECT count(*) FROM ann_pool)>=256
   UNION ALL SELECT * FROM exact_pool
 )
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric ASC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT pool.*,row_number() OVER(PARTITION BY document_id ORDER BY metric ASC,idx,id) AS within_document
     FROM pool
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
LANGUAGE sql STABLE SET hnsw.ef_search = 256 SET jit=off AS $$
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
 WITH ann_pool AS MATERIALIZED (
   SELECT c.id,d.id AS document_id,d.slug,c.idx,x.embedding <=> query_vec AS metric
   FROM chunk_contexts x JOIN LATERAL (
     SELECT c.id,c.document_id,c.idx,c.content FROM chunks c
     WHERE c.id=x.chunk_id OFFSET 0
   ) c ON true JOIN LATERAL (
     SELECT d.id,d.slug,d.title,d.body,d.project_scope FROM documents d
     WHERE d.id=c.document_id AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
       -- Keep hash selectivity inside this gate so generic plans retain HNSW.
       AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
     OFFSET 0
   ) d ON true
   WHERE current_setting('rag.iterative_vectors',true)='on' AND query_vec IS NOT NULL AND x.version=1 AND x.embedding IS NOT NULL AND x.model_digest=p_model
   ORDER BY x.embedding <=> query_vec LIMIT 256
 ), exact_pool AS MATERIALIZED (
   -- A capped or unsupported ANN scan must not turn eligible results into gaps.
   -- Distance+0 deliberately selects exact sorting for this recovery branch.
   SELECT c.id,d.id AS document_id,d.slug,c.idx,x.embedding <=> query_vec AS metric
   FROM chunk_contexts x JOIN LATERAL (
     SELECT c.id,c.document_id,c.idx,c.content FROM chunks c
     WHERE c.id=x.chunk_id OFFSET 0
   ) c ON true JOIN LATERAL (
     SELECT d.id,d.slug,d.title,d.body,d.project_scope FROM documents d
     WHERE d.id=c.document_id AND d.status='active' AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
       -- Keep hash selectivity inside this gate so generic plans retain HNSW.
       AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
     OFFSET 0
   ) d ON true
   WHERE (SELECT count(*) FROM ann_pool)<256 AND query_vec IS NOT NULL AND x.version=1 AND x.embedding IS NOT NULL AND x.model_digest=p_model
   ORDER BY (x.embedding <=> query_vec)+0 LIMIT 256
 ), pool AS (
   SELECT * FROM ann_pool WHERE (SELECT count(*) FROM ann_pool)>=256
   UNION ALL SELECT * FROM exact_pool
 )
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric ASC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT pool.*,row_number() OVER(PARTITION BY document_id ORDER BY metric ASC,idx,id) AS within_document
     FROM pool
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

CREATE OR REPLACE FUNCTION hybrid_search_candidates_planned(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
-- Keep the small SQL branches cached rather than repeatedly inlining their full plans.
-- This matches013/015 ef_search and is restored by PostgreSQL at function return.
LANGUAGE sql STABLE SET hnsw.ef_search=256 SET jit=off AS $$
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
 SELECT * FROM filtered_vector_candidates(query_vec,p_domain,p_scopes,p_at,p_history,NULL,false)
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

CREATE OR REPLACE FUNCTION contextual_search_candidates_planned(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
-- Keep the small SQL branches cached rather than repeatedly inlining their full plans.
-- This matches013/015 ef_search and is restored by PostgreSQL at function return.
LANGUAGE sql STABLE SET hnsw.ef_search=256 SET jit=off AS $$
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
 SELECT * FROM filtered_vector_candidates(query_vec,p_domain,p_scopes,p_at,p_history,p_model,true)
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


-- pgvector0.8+ can continue HNSW past filtered neighbours. Keep this local to
-- each retrieval function; caller scan/memory caps remain in force. Older
-- supported0.7 installations use exact scans instead of silently losing recall.
DO $capability$
DECLARE can_iterate boolean; signature text;
BEGIN
 PERFORM '[1]'::halfvec;
 SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_settings WHERE name='hnsw.iterative_scan')
   AND EXISTS(SELECT 1 FROM pg_catalog.pg_extension WHERE extname='vector'
     AND (split_part(extversion,'.',1)::int>0 OR split_part(extversion,'.',2)::int>=8))
 INTO can_iterate;
 FOREACH signature IN ARRAY ARRAY[
   'public.hybrid_search_candidates(text,halfvec,text,integer,text[],timestamptz,boolean)',
   'public.contextual_search_candidates(text,halfvec,text,integer,text[],timestamptz,boolean,text)'
 ] LOOP
   IF can_iterate THEN
     EXECUTE format('ALTER FUNCTION %s SET rag.iterative_vectors TO on',signature);
     EXECUTE format('ALTER FUNCTION %s SET hnsw.iterative_scan TO %L',signature,'strict_order');
   ELSE
     -- Disable only the ANN branch, retaining B-tree/GIN for exact scoped work.
     EXECUTE format('ALTER FUNCTION %s SET rag.iterative_vectors TO off',signature);
   END IF;
 END LOOP;
END $capability$;
