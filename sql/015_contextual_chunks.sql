-- Additive derived representations. Raw chunks, vectors and old functions stay intact.
CREATE FUNCTION chunk_context_source_hash(p_title text,p_body text,p_scope text,p_content text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to(jsonb_build_array(p_title,p_body,p_scope,p_content)::text,'UTF8')),'hex')
$$;

CREATE TABLE chunk_contexts (
 chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
 version int NOT NULL CHECK(version=1),
 context text NOT NULL CHECK(char_length(context)<=768),
 representation text NOT NULL,
 source_hash text NOT NULL,
 embedding halfvec(1024),
 model_digest text,
 indexed_at timestamptz NOT NULL DEFAULT now(),
 tsv_en tsvector GENERATED ALWAYS AS (to_tsvector('english',representation)) STORED,
 tsv_de tsvector GENERATED ALWAYS AS (to_tsvector('german',representation)) STORED,
 PRIMARY KEY(chunk_id,version),
 CHECK(embedding IS NULL OR (model_digest IS NOT NULL AND model_digest ~ '^[0-9a-f]{64}$'))
);
CREATE INDEX chunk_contexts_vec ON chunk_contexts USING hnsw(embedding halfvec_cosine_ops) WHERE embedding IS NOT NULL;
CREATE INDEX chunk_contexts_en ON chunk_contexts USING gin(tsv_en);
CREATE INDEX chunk_contexts_de ON chunk_contexts USING gin(tsv_de);
GRANT SELECT ON chunk_contexts TO rag_reader,rag_writer;
GRANT ALL ON chunk_contexts TO rag_admin;

CREATE FUNCTION put_chunk_contexts(p_doc uuid,p_ids uuid[],p_contexts text[],p_vectors text[],p_hashes text[],p_digest text)
RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE changed int;
BEGIN
 IF cardinality(p_ids) IS DISTINCT FROM cardinality(p_contexts)
 OR cardinality(p_ids) IS DISTINCT FROM cardinality(p_vectors)
 OR cardinality(p_ids) IS DISTINCT FROM cardinality(p_hashes) THEN
  RAISE EXCEPTION 'context array lengths differ';
 END IF;
 IF EXISTS(SELECT 1 FROM unnest(p_ids,p_hashes) u(id,hash)
  LEFT JOIN chunks c ON c.id=u.id LEFT JOIN documents d ON d.id=c.document_id
  WHERE d.id IS DISTINCT FROM p_doc OR u.hash IS DISTINCT FROM chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)) THEN
  RAISE EXCEPTION 'context source changed; retry';
 END IF;
 INSERT INTO chunk_contexts(chunk_id,version,context,representation,source_hash,embedding,model_digest)
 SELECT c.id,1,u.context,u.context || E'\n' || left(c.content,4000),u.hash,u.vector::halfvec,p_digest
 FROM unnest(p_ids,p_contexts,p_vectors,p_hashes) u(id,context,vector,hash) JOIN chunks c ON c.id=u.id
 ON CONFLICT(chunk_id,version) DO UPDATE SET context=excluded.context,representation=excluded.representation,
 source_hash=excluded.source_hash,indexed_at=now(),
 embedding=CASE WHEN chunk_contexts.source_hash=excluded.source_hash AND chunk_contexts.representation=excluded.representation
  THEN COALESCE(excluded.embedding,chunk_contexts.embedding) ELSE excluded.embedding END,
 model_digest=CASE WHEN excluded.embedding IS NULL AND chunk_contexts.source_hash=excluded.source_hash AND chunk_contexts.representation=excluded.representation
  THEN chunk_contexts.model_digest ELSE excluded.model_digest END;
 GET DIAGNOSTICS changed=ROW_COUNT;
 RETURN changed;
END $$;
REVOKE ALL ON FUNCTION put_chunk_contexts(uuid,uuid[],text[],text[],text[],text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION put_chunk_contexts(uuid,uuid[],text[],text[],text[],text) TO rag_writer,rag_admin;

CREATE FUNCTION contextual_search_candidates(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE SET hnsw.ef_search = 256 AS $$
WITH vec AS (
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

CREATE FUNCTION hybrid_search_contextual(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE AS $$
 WITH combined AS (
 SELECT * FROM hybrid_search_candidates(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history)
 UNION ALL
 SELECT * FROM contextual_search_candidates(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history,p_model)
 ), fused AS (SELECT chunk_id,sum(score) AS score FROM combined GROUP BY chunk_id)
 SELECT d.id,c.id,d.title,d.slug,d.domain,d.dtype,left(c.content,4000),f.score,d.verified_at,d.provenance
 FROM fused f JOIN chunks c ON c.id=f.chunk_id JOIN documents d ON d.id=c.document_id
 ORDER BY f.score DESC,d.slug,c.idx,c.id LIMIT least(greatest(k,0),150)
$$;
