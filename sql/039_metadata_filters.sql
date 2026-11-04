-- Additive typed metadata-v1. No policies or truth predicates are changed.
-- Pure helpers consume only their arguments. Document lookup is invoker-only.
CREATE FUNCTION public.rag_metadata_valid(v jsonb,t text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE item jsonb; stamp timestamptz; day date;
BEGIN
 IF v IS NULL OR v='null'::jsonb THEN RETURN false; END IF;
 IF right(t,2)='[]' THEN
  IF jsonb_typeof(v)<>'array' OR jsonb_array_length(v)>32 THEN RETURN false; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(v) LOOP
   IF NOT public.rag_metadata_valid(item,left(t,length(t)-2)) THEN RETURN false; END IF;
  END LOOP;
  RETURN true;
 END IF;
 CASE t
 WHEN 'string' THEN RETURN jsonb_typeof(v)='string' AND octet_length(v#>>'{}')<=1024;
 WHEN 'number' THEN RETURN jsonb_typeof(v)='number';
 WHEN 'boolean' THEN RETURN jsonb_typeof(v)='boolean';
 WHEN 'date' THEN
  IF jsonb_typeof(v)<>'string' OR (v#>>'{}') !~ '^\d{4}-\d{2}-\d{2}$' THEN RETURN false; END IF;
  day:=(v#>>'{}')::date; RETURN to_char(day,'YYYY-MM-DD')=v#>>'{}';
 WHEN 'timestamp' THEN
  IF jsonb_typeof(v)<>'string' OR (v#>>'{}') !~ '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}(:?\d{2})?)$' THEN RETURN false; END IF;
  stamp:=(v#>>'{}')::timestamptz; RETURN isfinite(stamp);
 ELSE RETURN false;
 END CASE;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_text_representation THEN RETURN false;
END $$;

CREATE FUNCTION public.rag_metadata_comparable(v jsonb,t text) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN t='timestamp' THEN to_jsonb(extract(epoch FROM (v#>>'{}')::timestamptz)) ELSE v END
$$;

CREATE FUNCTION public.rag_metadata_node(fields jsonb,node jsonb,level integer DEFAULT 1) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE child jsonb; present boolean; v jsonb; wanted jsonb; comparable jsonb;
 field_name text; op text; typ text; matches boolean;
BEGIN
 IF level>6 OR octet_length(node::text)>16384 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='invalid_filter';
 END IF;
 IF node ? 'and' THEN
  FOR child IN SELECT value FROM jsonb_array_elements(node->'and') LOOP
   IF NOT public.rag_metadata_node(fields,child,level+1) THEN RETURN false; END IF;
  END LOOP; RETURN true;
 ELSIF node ? 'or' THEN
  FOR child IN SELECT value FROM jsonb_array_elements(node->'or') LOOP
   IF public.rag_metadata_node(fields,child,level+1) THEN RETURN true; END IF;
  END LOOP; RETURN false;
 ELSIF node ? 'not' THEN RETURN NOT public.rag_metadata_node(fields,node->'not',level+1);
 END IF;
 field_name:=node->>'field';op:=node->>'op';typ:=node->>'type';wanted:=node->'value';
 present:=COALESCE(fields ? field_name,false);v:=fields->field_name;
 IF op='exists' THEN RETURN present=(wanted='true'::jsonb); END IF;
 IF op='is_null' THEN RETURN present AND ((v='null'::jsonb)=(wanted='true'::jsonb)); END IF;
 IF NOT present OR NOT public.rag_metadata_valid(v,typ) THEN RETURN false; END IF;
 comparable:=public.rag_metadata_comparable(v,typ);
 IF op IN ('in','nin') THEN
  matches:=false;
  FOR child IN SELECT value FROM jsonb_array_elements(wanted) LOOP
   IF comparable=public.rag_metadata_comparable(child,typ) THEN matches:=true;EXIT; END IF;
  END LOOP;
  RETURN CASE WHEN op='nin' THEN NOT matches ELSE matches END;
 ELSIF op IN ('has_any','has_all') THEN
  matches:=(op='has_all');
  FOR child IN SELECT value FROM jsonb_array_elements(wanted) LOOP
   IF op='has_all' AND NOT v @> jsonb_build_array(child) THEN RETURN false; END IF;
   IF op='has_any' AND v @> jsonb_build_array(child) THEN RETURN true; END IF;
  END LOOP;RETURN matches;
 ELSIF op='prefix' THEN RETURN left(v#>>'{}',length(wanted#>>'{}')) COLLATE "C" = (wanted#>>'{}') COLLATE "C";
 ELSIF op='contains' THEN RETURN strpos(v#>>'{}',wanted#>>'{}')>0;
 END IF;
 wanted:=public.rag_metadata_comparable(wanted,typ);
 RETURN COALESCE(CASE op WHEN 'eq' THEN comparable=wanted WHEN 'ne' THEN comparable<>wanted
  WHEN 'gt' THEN comparable>wanted WHEN 'gte' THEN comparable>=wanted
  WHEN 'lt' THEN comparable<wanted WHEN 'lte' THEN comparable<=wanted ELSE false END,false);
END $$;

CREATE FUNCTION public.rag_metadata_guard(node jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE item record; total integer:=0; leaves integer:=0; keys text[];typ text;op text; child jsonb;
BEGIN
 IF octet_length(node::text)>16384 THEN RETURN false; END IF;
 FOR item IN
  WITH RECURSIVE nodes(value,level) AS (
   SELECT node,1 UNION ALL
   SELECT child.value,n.level+1 FROM nodes n CROSS JOIN LATERAL (
    SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.value->'and')='array' THEN n.value->'and' ELSE '[]'::jsonb END)
    UNION ALL SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.value->'or')='array' THEN n.value->'or' ELSE '[]'::jsonb END)
    UNION ALL SELECT n.value->'not' WHERE n.value ? 'not'
   ) child WHERE n.level<=6
  ) SELECT value,level FROM nodes LIMIT 65
 LOOP
  total:=total+1;
  IF total>64 OR item.level>6 OR jsonb_typeof(item.value)<>'object' THEN RETURN false; END IF;
  SELECT array_agg(key ORDER BY key) INTO keys FROM jsonb_object_keys(item.value) key;
  IF keys=ARRAY['and'] OR keys=ARRAY['or'] THEN
   IF jsonb_typeof(item.value->keys[1])<>'array' OR jsonb_array_length(item.value->keys[1]) NOT BETWEEN 1 AND 32 THEN RETURN false; END IF;
  ELSIF keys=ARRAY['not'] THEN NULL;
  ELSIF keys=ARRAY['field','op','type','value'] THEN
   leaves:=leaves+1;typ:=item.value->>'type';op:=item.value->>'op';
   IF leaves>32 OR typ NOT IN ('string','number','boolean','date','timestamp','string[]','number[]','boolean[]')
     OR (item.value->>'field') !~ '^(dtype|status|slug|created_at|updated_at|verified_at|review_state|app\.[A-Za-z_][A-Za-z0-9_]{0,63})$'
     OR op NOT IN ('eq','ne','in','nin','gt','gte','lt','lte','prefix','contains','has_any','has_all','exists','is_null') THEN RETURN false; END IF;
   IF ((item.value->>'field') IN ('dtype','status','slug','review_state') AND typ<>'string')
     OR ((item.value->>'field') IN ('created_at','updated_at','verified_at') AND typ<>'timestamp')
     OR (op IN ('gt','gte','lt','lte') AND typ NOT IN ('number','date','timestamp'))
     OR (op IN ('prefix','contains') AND (typ<>'string' OR octet_length(item.value->>'value')>256))
     OR (op IN ('in','nin') AND right(typ,2)='[]')
     OR (op IN ('has_any','has_all') AND right(typ,2)<>'[]') THEN RETURN false; END IF;
   IF op IN ('exists','is_null') THEN
    IF jsonb_typeof(item.value->'value')<>'boolean' THEN RETURN false; END IF;
   ELSIF op IN ('in','nin','has_any','has_all') THEN
    IF jsonb_typeof(item.value->'value')<>'array' OR jsonb_array_length(item.value->'value') NOT BETWEEN 1 AND 32 THEN RETURN false; END IF;
    FOR child IN SELECT value FROM jsonb_array_elements(item.value->'value') LOOP
     IF NOT public.rag_metadata_valid(child,CASE WHEN right(typ,2)='[]' THEN left(typ,length(typ)-2) ELSE typ END) THEN RETURN false; END IF;
    END LOOP;
   ELSIF NOT public.rag_metadata_valid(item.value->'value',typ) THEN RETURN false;
   END IF;
  ELSE RETURN false;
  END IF;
 END LOOP;
 RETURN COALESCE(total>0,false);
END $$;

CREATE FUNCTION public.rag_metadata_match(fields jsonb,node jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
 IF NOT public.rag_metadata_guard(node) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='invalid_filter';
 END IF;
 RETURN public.rag_metadata_node(fields,node);
END $$;

CREATE FUNCTION public.rag_metadata_filter_node(p_filter jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE keys text[];
BEGIN
 IF jsonb_typeof(p_filter) IS DISTINCT FROM 'object' OR octet_length(p_filter::text)>16384 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='invalid_filter';
 END IF;
 SELECT array_agg(key ORDER BY key) INTO keys FROM jsonb_object_keys(p_filter) key;
 IF keys IS DISTINCT FROM ARRAY['version','where'] OR (p_filter->>'version') IS DISTINCT FROM '1'
   OR jsonb_typeof(p_filter->'version') IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='invalid_filter';
 END IF;
 RETURN p_filter->'where';
END $$;

CREATE FUNCTION public.rag_metadata_document(p_id uuid,p_filter jsonb) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT p_filter IS NULL OR COALESCE((SELECT public.rag_metadata_match(
   jsonb_build_object('dtype',d.dtype,'status',d.status,'slug',d.slug,
     'created_at',d.created_at,'updated_at',d.updated_at,'verified_at',d.verified_at)
   || CASE WHEN r.document_id IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('review_state',r.review_state) END
   || COALESCE((SELECT jsonb_object_agg('app.'||key,value) FROM jsonb_each(
      CASE WHEN d.meta->'application'->'version'='1'::jsonb
        AND jsonb_typeof(d.meta->'application'->'values')='object'
      THEN d.meta->'application'->'values' ELSE '{}'::jsonb END)), '{}'::jsonb),public.rag_metadata_filter_node(p_filter))
   FROM public.documents d LEFT JOIN public.claim_records r ON r.document_id=d.id WHERE d.id=p_id),false)
$$;

CREATE FUNCTION hybrid_search_candidates_metadata(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_filter jsonb DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE SET hnsw.ef_search = 256 SET jit=off AS $$
WITH matches_en AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.tsv_en FROM chunks c
 WHERE c.tsv_en @@ (SELECT websearch_to_tsquery('english',query_text))
),
matches_de AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.tsv_de FROM chunks c
 WHERE c.tsv_de @@ (SELECT websearch_to_tsquery('german',query_text))
),
eligible_documents AS MATERIALIZED (
 SELECT d.* FROM (
   SELECT document_id FROM matches_en UNION SELECT document_id FROM matches_de
 ) m JOIN LATERAL (
   SELECT d.id,d.slug FROM documents d
   WHERE d.id=m.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter)
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
     WHERE d.id=c.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
     OFFSET 0
   ) d ON true
   WHERE (SELECT current_setting('hnsw.iterative_scan',true)='strict_order'
     AND EXISTS(SELECT 1 FROM pg_catalog.pg_extension WHERE extname='vector'
       AND (split_part(extversion,'.',1)::int>0 OR split_part(extversion,'.',2)::int>=8))) AND query_vec IS NOT NULL AND c.embedding IS NOT NULL
   ORDER BY c.embedding <=> query_vec LIMIT 256
 ), exact_pool AS MATERIALIZED (
   -- A capped or unsupported ANN scan must not turn eligible results into gaps.
   -- Distance+0 deliberately selects exact sorting for this recovery branch.
   SELECT c.id,d.id AS document_id,d.slug,c.idx,c.embedding <=> query_vec AS metric
   FROM chunks c JOIN LATERAL (
     SELECT d.id,d.slug FROM documents d
     WHERE d.id=c.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
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
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) DESC,c.idx,c.id) AS within_document
     FROM matches_en c JOIN eligible_documents d ON d.id=c.document_id
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
ts_de AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) DESC,c.idx,c.id) AS within_document
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

CREATE FUNCTION contextual_search_candidates_metadata(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL,p_filter jsonb DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE SET hnsw.ef_search = 256 SET jit=off AS $$
WITH matches_en AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.content,x.source_hash,x.tsv_en
 FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id
 WHERE x.version=1 AND x.tsv_en @@ (SELECT websearch_to_tsquery('english',query_text))
),
matches_de AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.content,x.source_hash,x.tsv_de
 FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id
 WHERE x.version=1 AND x.tsv_de @@ (SELECT websearch_to_tsquery('german',query_text))
),
eligible_documents AS MATERIALIZED (
 SELECT d.* FROM (
   SELECT document_id FROM matches_en UNION SELECT document_id FROM matches_de
 ) m JOIN LATERAL (
   SELECT d.id,d.slug,d.title,d.body,d.project_scope FROM documents d
   WHERE d.id=m.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter)
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
     WHERE d.id=c.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
       AND (p_domain IS NULL OR d.domain=p_domain)
       AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
       -- Keep hash selectivity inside this gate so generic plans retain HNSW.
       AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
     OFFSET 0
   ) d ON true
   WHERE (SELECT current_setting('hnsw.iterative_scan',true)='strict_order'
     AND EXISTS(SELECT 1 FROM pg_catalog.pg_extension WHERE extname='vector'
       AND (split_part(extversion,'.',1)::int>0 OR split_part(extversion,'.',2)::int>=8))) AND query_vec IS NOT NULL AND x.version=1 AND x.embedding IS NOT NULL AND x.model_digest=p_model
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
     WHERE d.id=c.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
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
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) DESC,c.idx,c.id) AS within_document
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
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) DESC,c.idx,c.id) AS within_document
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

CREATE FUNCTION filtered_vector_candidates_metadata(
 p_vector halfvec(1024),p_domain text DEFAULT NULL,p_scopes text[] DEFAULT NULL,
 p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL,
 p_context boolean DEFAULT false,p_exact_limit integer DEFAULT 4096,p_pool_limit integer DEFAULT 4096,p_filter jsonb DEFAULT NULL
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
    AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes)) LIMIT p_exact_limit+1
  ), exact_pool AS (
   SELECT e.id,e.doc_id,e.slug,e.idx,e.embedding <=> p_vector metric FROM eligible e
   WHERE (SELECT count(*) FROM eligible)<=p_exact_limit
  ), ann_pool AS MATERIALIZED (
   SELECT c.id,d.id doc_id,d.slug,c.idx,x.embedding <=> p_vector metric
   FROM chunks c JOIN documents d ON d.id=c.document_id JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1
   WHERE (SELECT count(*) FROM eligible)>p_exact_limit AND x.embedding IS NOT NULL AND l2_norm(x.embedding)>0 AND x.model_digest=p_model AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)
    AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
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
    AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes)) LIMIT p_exact_limit+1
  ), exact_pool AS (
   SELECT e.id,e.doc_id,e.slug,e.idx,e.embedding <=> p_vector metric FROM eligible e
   WHERE (SELECT count(*) FROM eligible)<=p_exact_limit
  ), ann_pool AS MATERIALIZED (
   SELECT c.id,d.id doc_id,d.slug,c.idx,c.embedding <=> p_vector metric
   FROM chunks c JOIN documents d ON d.id=c.document_id
   WHERE (SELECT count(*) FROM eligible)>p_exact_limit AND c.embedding IS NOT NULL AND l2_norm(c.embedding)>0
    AND d.status='active' AND public.rag_metadata_document(d.id,p_filter) AND assertion_eligible(d.id,p_at,p_history)
    AND (p_domain IS NULL OR d.domain=p_domain) AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   ORDER BY c.embedding <=> p_vector LIMIT p_pool_limit
  ), selected AS (SELECT * FROM exact_pool UNION ALL SELECT * FROM ann_pool),
  diverse AS (SELECT t.*,row_number() OVER(PARTITION BY doc_id ORDER BY metric,idx,id) within_document FROM selected t),
  bounded AS (SELECT * FROM diverse WHERE within_document<=2 ORDER BY metric,slug,idx,id LIMIT 50)
  SELECT b.id,row_number() OVER(ORDER BY metric,slug,idx,id) FROM bounded b;
 END IF;
END $$;

CREATE FUNCTION hybrid_search_candidates_planned_metadata(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_filter jsonb DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
-- Keep the small SQL branches cached rather than repeatedly inlining their full plans.
-- This matches013/015 ef_search and is restored by PostgreSQL at function return.
LANGUAGE sql STABLE SET hnsw.ef_search=256 SET jit=off AS $$
WITH matches_en AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.tsv_en FROM chunks c
 WHERE c.tsv_en @@ (SELECT websearch_to_tsquery('english',query_text))
),
matches_de AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.tsv_de FROM chunks c
 WHERE c.tsv_de @@ (SELECT websearch_to_tsquery('german',query_text))
),
eligible_documents AS MATERIALIZED (
 SELECT d.* FROM (
   SELECT document_id FROM matches_en UNION SELECT document_id FROM matches_de
 ) m JOIN LATERAL (
   SELECT d.id,d.slug FROM documents d
   WHERE d.id=m.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter)
     AND assertion_eligible(d.id,p_at,p_history)
     AND (p_domain IS NULL OR d.domain=p_domain)
     AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   OFFSET 0
 ) d ON true
),
vec AS (
 SELECT * FROM filtered_vector_candidates_metadata(query_vec,p_domain,p_scopes,p_at,p_history,NULL,false,4096,4096,p_filter)
),
ts_en AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) DESC,c.idx,c.id) AS within_document
     FROM matches_en c JOIN eligible_documents d ON d.id=c.document_id
   ) eligible WHERE within_document<=2
   ORDER BY metric DESC,slug,idx,id LIMIT 50
 ) bounded
),
ts_de AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) DESC,c.idx,c.id) AS within_document
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

CREATE FUNCTION contextual_search_candidates_planned_metadata(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL,p_filter jsonb DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
-- Keep the small SQL branches cached rather than repeatedly inlining their full plans.
-- This matches013/015 ef_search and is restored by PostgreSQL at function return.
LANGUAGE sql STABLE SET hnsw.ef_search=256 SET jit=off AS $$
WITH matches_en AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.content,x.source_hash,x.tsv_en
 FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id
 WHERE x.version=1 AND x.tsv_en @@ (SELECT websearch_to_tsquery('english',query_text))
),
matches_de AS MATERIALIZED (
 SELECT c.id,c.document_id,c.idx,c.content,x.source_hash,x.tsv_de
 FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id
 WHERE x.version=1 AND x.tsv_de @@ (SELECT websearch_to_tsquery('german',query_text))
),
eligible_documents AS MATERIALIZED (
 SELECT d.* FROM (
   SELECT document_id FROM matches_en UNION SELECT document_id FROM matches_de
 ) m JOIN LATERAL (
   SELECT d.id,d.slug,d.title,d.body,d.project_scope FROM documents d
   WHERE d.id=m.document_id AND d.status='active' AND public.rag_metadata_document(d.id,p_filter)
     AND assertion_eligible(d.id,p_at,p_history)
     AND (p_domain IS NULL OR d.domain=p_domain)
     AND (p_scopes IS NULL OR d.project_scope=ANY(p_scopes))
   OFFSET 0
 ) d ON true
),
vec AS (
 SELECT * FROM filtered_vector_candidates_metadata(query_vec,p_domain,p_scopes,p_at,p_history,p_model,true,4096,4096,p_filter)
),
ts_en AS (
 SELECT id AS chunk_id,row_number() OVER(ORDER BY metric DESC,slug,idx,id) AS rank
 FROM (
   SELECT * FROM (
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_en, (SELECT websearch_to_tsquery('english', query_text))) DESC,c.idx,c.id) AS within_document
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
     SELECT c.id,d.slug,c.idx,ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) AS metric,
       row_number() OVER(PARTITION BY d.id ORDER BY ts_rank_cd(c.tsv_de, (SELECT websearch_to_tsquery('german', query_text))) DESC,c.idx,c.id) AS within_document
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

CREATE FUNCTION hybrid_search_contextual_metadata(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL,p_filter jsonb DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE AS $$
 WITH combined AS (
 SELECT * FROM hybrid_search_candidates_metadata(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history,p_filter)
 UNION ALL
 SELECT * FROM contextual_search_candidates_metadata(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history,p_model,p_filter)
 ), fused AS (SELECT chunk_id,sum(score) AS score FROM combined GROUP BY chunk_id)
 SELECT d.id,c.id,d.title,d.slug,d.domain,d.dtype,left(c.content,4000),f.score,d.verified_at,d.provenance
 FROM fused f JOIN chunks c ON c.id=f.chunk_id JOIN documents d ON d.id=c.document_id
 ORDER BY f.score DESC,d.slug,c.idx,c.id LIMIT least(greatest(k,0),150)
$$;

CREATE FUNCTION hybrid_search_contextual_planned_metadata(
 query_text text,query_vec halfvec(1024) DEFAULT NULL,p_domain text DEFAULT NULL,
 k int DEFAULT 150,p_scopes text[] DEFAULT NULL,p_at timestamptz DEFAULT now(),p_history boolean DEFAULT false,p_model text DEFAULT NULL,p_filter jsonb DEFAULT NULL
) RETURNS TABLE(document_id uuid,chunk_id uuid,title text,slug text,domain text,dtype text,
 snippet text,score double precision,verified_at timestamptz,provenance jsonb)
LANGUAGE sql STABLE AS $$
 WITH combined AS (
 SELECT * FROM hybrid_search_candidates_planned_metadata(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history,p_filter)
 UNION ALL
 SELECT * FROM contextual_search_candidates_planned_metadata(query_text,query_vec,p_domain,150,p_scopes,p_at,p_history,p_model,p_filter)
 ), fused AS (SELECT chunk_id,sum(score) AS score FROM combined GROUP BY chunk_id)
 SELECT d.id,c.id,d.title,d.slug,d.domain,d.dtype,left(c.content,4000),f.score,d.verified_at,d.provenance
 FROM fused f JOIN chunks c ON c.id=f.chunk_id JOIN documents d ON d.id=c.document_id
 ORDER BY f.score DESC,d.slug,c.idx,c.id LIMIT least(greatest(k,0),150)
$$;

DO $capability$
BEGIN
 PERFORM '[1]'::halfvec;
 IF EXISTS(SELECT 1 FROM pg_catalog.pg_settings WHERE name='hnsw.iterative_scan') THEN
  ALTER FUNCTION public.hybrid_search_candidates_metadata(text,halfvec,text,integer,text[],timestamptz,boolean,jsonb) SET hnsw.iterative_scan='strict_order';
  ALTER FUNCTION public.contextual_search_candidates_metadata(text,halfvec,text,integer,text[],timestamptz,boolean,text,jsonb) SET hnsw.iterative_scan='strict_order';
 END IF;
END $capability$;

CREATE FUNCTION graph_neighbors_temporal_metadata(
    p_id uuid, p_depth int DEFAULT 1, p_predicates text[] DEFAULT NULL, p_scopes text[] DEFAULT NULL, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false,p_filter jsonb DEFAULT NULL
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
    WHERE (e.src_id = p_id OR e.dst_id = p_id) AND e.dst_id IS NOT NULL AND assertion_eligible(e.src_id,p_at,p_history) AND public.rag_metadata_document(e.src_id,p_filter) AND public.rag_metadata_document(e.dst_id,p_filter) AND assertion_eligible(e.dst_id,p_at,p_history) AND (p_history OR (e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at)))
      AND (p_predicates IS NULL OR e.predicate = ANY (p_predicates)) AND (p_scopes IS NULL OR (EXISTS (SELECT 1 FROM documents ds WHERE ds.id=e.src_id AND ds.project_scope=ANY(p_scopes)) AND EXISTS (SELECT 1 FROM documents dd WHERE dd.id=e.dst_id AND dd.project_scope=ANY(p_scopes))))
  UNION ALL
    SELECT e.id, e.src_id, e.dst_id, e.predicate, e.evidence, e.confidence,
           h.depth + 1,
           CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END,
           h.visited || CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END
    FROM hops h
    JOIN edges e ON (e.src_id = h.frontier OR e.dst_id = h.frontier)
    WHERE h.depth < p_depth AND e.dst_id IS NOT NULL AND assertion_eligible(e.src_id,p_at,p_history) AND public.rag_metadata_document(e.src_id,p_filter) AND public.rag_metadata_document(e.dst_id,p_filter) AND assertion_eligible(e.dst_id,p_at,p_history) AND (p_history OR (e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at)))
      AND (p_predicates IS NULL OR e.predicate = ANY (p_predicates)) AND (p_scopes IS NULL OR (EXISTS (SELECT 1 FROM documents ds WHERE ds.id=e.src_id AND ds.project_scope=ANY(p_scopes)) AND EXISTS (SELECT 1 FROM documents dd WHERE dd.id=e.dst_id AND dd.project_scope=ANY(p_scopes))))
      AND NOT (CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END
               = ANY (h.visited))
)
SELECT DISTINCT ON (edge_id) edge_id, src_id, dst_id, predicate,
       evidence, confidence, depth
FROM hops
ORDER BY edge_id, depth
$$;

CREATE FUNCTION graph_path_temporal_metadata(
    p_from uuid, p_to uuid, p_max_depth int DEFAULT 4, p_scopes text[] DEFAULT NULL, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false,p_filter jsonb DEFAULT NULL
) RETURNS TABLE (step int, doc_id uuid, via_predicate text)
LANGUAGE sql STABLE AS $$
WITH RECURSIVE walk(path, preds) AS (
    SELECT ARRAY[p_from], ARRAY[]::text[] WHERE public.rag_metadata_document(p_from,p_filter) AND assertion_eligible(p_from,p_at,p_history) AND (p_scopes IS NULL OR EXISTS (SELECT 1 FROM documents d WHERE d.id=p_from AND d.project_scope=ANY(p_scopes)))
  UNION ALL
    SELECT w.path || n.next_id, w.preds || e.predicate
    FROM walk w
    JOIN edges e ON (e.src_id = w.path[array_length(w.path, 1)]
                  OR e.dst_id = w.path[array_length(w.path, 1)])
    CROSS JOIN LATERAL (
        SELECT CASE WHEN e.src_id = w.path[array_length(w.path, 1)]
                    THEN e.dst_id ELSE e.src_id END AS next_id
    ) n
    WHERE e.dst_id IS NOT NULL AND assertion_eligible(e.src_id,p_at,p_history) AND public.rag_metadata_document(e.src_id,p_filter) AND public.rag_metadata_document(e.dst_id,p_filter) AND assertion_eligible(e.dst_id,p_at,p_history) AND (p_history OR (e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at))) AND (p_scopes IS NULL OR (EXISTS (SELECT 1 FROM documents ds WHERE ds.id=e.src_id AND ds.project_scope=ANY(p_scopes)) AND EXISTS (SELECT 1 FROM documents dd WHERE dd.id=e.dst_id AND dd.project_scope=ANY(p_scopes))))
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
