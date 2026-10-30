-- Additive opt-in spaces: historical untagged vectors remain untouched.
CREATE TABLE embedding_generations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text UNIQUE NOT NULL CHECK(name ~ '^[a-z][a-z0-9-]{0,47}$'),
 profile_name text NOT NULL,
 identity text NOT NULL CHECK(identity ~ '^[0-9a-f]{64}$'),
 descriptor jsonb NOT NULL,
 dimensions integer NOT NULL CHECK(dimensions BETWEEN 1 AND 4000),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(descriptor->>'representation'='raw-v1' AND descriptor->>'metric'='cosine'),
 CHECK((descriptor->>'dimensions')::integer=dimensions)
);
CREATE TABLE embedding_selection (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 generation_id uuid REFERENCES embedding_generations(id)
);
CREATE TABLE embedding_vectors (
 generation_id uuid NOT NULL REFERENCES embedding_generations(id),
 chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
 source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
 embedding halfvec NOT NULL CHECK(vector_dims(embedding) BETWEEN 1 AND 4000 AND l2_norm(embedding)>0),
 indexed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(generation_id,chunk_id)
);
ALTER TABLE embedding_vectors ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_embedding_vectors ON embedding_vectors
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM chunks c WHERE c.id=chunk_id));
GRANT SELECT ON embedding_generations,embedding_selection,embedding_vectors TO rag_reader,rag_writer,rag_admin;

-- raw-v1 embeds c.content exactly. Title/scope edits invalidate applicability;
-- unlike contextual-v1 this deliberately does not hash the full body per chunk.
CREATE FUNCTION embedding_source_hash(p_title text,p_scope text,p_content text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT encode(sha256(convert_to(jsonb_build_array(p_title,p_scope,p_content)::text,'UTF8')),'hex')
$$;

CREATE FUNCTION embedding_lifecycle_owner() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF public.rag_service_active() OR current_user IS DISTINCT FROM
  (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='public.embedding_generations'::regclass) THEN
  RAISE EXCEPTION 'local database owner required' USING ERRCODE='42501';
 END IF;
 PERFORM pg_advisory_xact_lock(610027);
END $$;
REVOKE ALL ON FUNCTION embedding_lifecycle_owner() FROM PUBLIC;

CREATE FUNCTION create_embedding_generation(p_name text,p_profile text,p_identity text,p_descriptor jsonb)
RETURNS uuid LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE existing public.embedding_generations; chosen uuid; dim integer;
BEGIN
 PERFORM public.embedding_lifecycle_owner();
 SELECT * INTO existing FROM public.embedding_generations WHERE name=p_name;
 IF FOUND THEN
  IF existing.identity<>p_identity OR existing.descriptor<>p_descriptor THEN RAISE EXCEPTION 'generation identity mismatch'; END IF;
  RETURN existing.id;
 END IF;
 IF (SELECT count(*) FROM public.embedding_generations)>=3 THEN RAISE EXCEPTION 'three retained generations maximum'; END IF;
 dim:=(p_descriptor->>'dimensions')::integer;
 INSERT INTO public.embedding_generations(name,profile_name,identity,descriptor,dimensions)
 VALUES(p_name,p_profile,p_identity,p_descriptor,dim) RETURNING id INTO chosen;
 -- Each immutable space gets an empty, bounded dimensions-specific ANN index.
 EXECUTE format('CREATE INDEX %I ON public.embedding_vectors USING hnsw ((embedding::public.halfvec(%s)) public.halfvec_cosine_ops) WITH (m=8,ef_construction=32) WHERE generation_id=%L::uuid',
  'embedding_vec_'||replace(chosen::text,'-',''),dim,chosen);
 INSERT INTO public.audit_log(actor,op,summary) VALUES('cli','index_create','created managed generation '||p_name);
 RETURN chosen;
END $$;
REVOKE ALL ON FUNCTION create_embedding_generation(text,text,text,jsonb) FROM PUBLIC;

CREATE FUNCTION put_embedding_vectors(p_generation uuid,p_ids uuid[],p_hashes text[],p_vectors text[],p_actor text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dim integer; n integer; resource record;
BEGIN
 IF p_ids IS NULL OR cardinality(p_ids) NOT BETWEEN 1 AND 32 OR cardinality(p_ids) IS DISTINCT FROM cardinality(p_hashes)
 OR cardinality(p_ids) IS DISTINCT FROM cardinality(p_vectors)
 OR (SELECT count(DISTINCT x) FROM unnest(p_ids) x)<>cardinality(p_ids) THEN RAISE EXCEPTION 'invalid managed vector batch'; END IF;
 SELECT dimensions INTO STRICT dim FROM public.embedding_generations WHERE id=p_generation;
 -- Same lock order as canonical save: documents, then chunks. Recheck after inference.
 FOR resource IN SELECT DISTINCT d.id FROM public.documents d JOIN public.chunks c ON c.document_id=d.id
   WHERE c.id=ANY(p_ids) ORDER BY d.id LOOP
  PERFORM 1 FROM public.documents WHERE id=resource.id FOR UPDATE;
  PERFORM public.rag_service_assert_document(resource.id);
 END LOOP;
 PERFORM 1 FROM public.chunks WHERE id=ANY(p_ids) ORDER BY id FOR SHARE;
 IF EXISTS(SELECT 1 FROM unnest(p_ids,p_hashes,p_vectors) u(id,hash,vector)
  LEFT JOIN public.chunks c ON c.id=u.id LEFT JOIN public.documents d ON d.id=c.document_id
  WHERE c.id IS NULL OR u.hash IS DISTINCT FROM public.embedding_source_hash(d.title,d.project_scope,c.content)
   OR u.vector IS NULL OR public.vector_dims(u.vector::public.halfvec)<>dim OR public.l2_norm(u.vector::public.halfvec)=0)
 THEN RAISE EXCEPTION 'managed source or vector changed; retry'; END IF;
 INSERT INTO public.embedding_vectors(generation_id,chunk_id,source_hash,embedding)
 SELECT p_generation,u.id,u.hash,u.vector::public.halfvec FROM unnest(p_ids,p_hashes,p_vectors) u(id,hash,vector)
 ON CONFLICT(generation_id,chunk_id) DO UPDATE SET source_hash=excluded.source_hash,embedding=excluded.embedding,indexed_at=now()
 WHERE embedding_vectors.source_hash<>excluded.source_hash;
 GET DIAGNOSTICS n=ROW_COUNT;
 IF n>0 THEN INSERT INTO public.audit_log(actor,op,summary) VALUES(p_actor,'index_build',format('managed generation %s vectors=%s',p_generation,n)); END IF;
 RETURN n;
END $$;
REVOKE ALL ON FUNCTION put_embedding_vectors(uuid,uuid[],text[],text[],text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION put_embedding_vectors(uuid,uuid[],text[],text[],text) TO rag_writer,rag_admin;

CREATE FUNCTION select_embedding_generation(p_generation uuid,p_expected uuid,p_operation text)
RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE previous uuid;
BEGIN
 PERFORM public.embedding_lifecycle_owner();
 IF p_operation NOT IN ('activate','rollback') THEN RAISE EXCEPTION 'invalid lifecycle operation'; END IF;
 PERFORM 1 FROM public.embedding_generations WHERE id=p_generation;
 IF NOT FOUND THEN RAISE EXCEPTION 'unknown generation'; END IF;
 -- Table locks also fence old binaries and metadata-only scope repairs.
 LOCK TABLE public.documents,public.chunks IN SHARE MODE;
 SELECT generation_id INTO previous FROM public.embedding_selection WHERE singleton FOR UPDATE;
 IF previous IS DISTINCT FROM p_expected THEN RAISE EXCEPTION 'active selection changed; retry'; END IF;
 IF EXISTS(SELECT 1 FROM public.chunks c JOIN public.documents d ON d.id=c.document_id
   LEFT JOIN public.embedding_vectors v ON v.chunk_id=c.id AND v.generation_id=p_generation
   WHERE v.source_hash IS DISTINCT FROM public.embedding_source_hash(d.title,d.project_scope,c.content))
 THEN RAISE EXCEPTION 'generation coverage incomplete; build before selection'; END IF;
 INSERT INTO public.embedding_selection(singleton,generation_id) VALUES(true,p_generation)
 ON CONFLICT(singleton) DO UPDATE SET generation_id=excluded.generation_id;
 INSERT INTO public.audit_log(actor,op,summary) VALUES('cli','index_'||p_operation,format('selected managed generation %s previous=%s',p_generation,previous));
END $$;
REVOKE ALL ON FUNCTION select_embedding_generation(uuid,uuid,text) FROM PUBLIC;

-- Strip inherited ALTER DEFAULT PRIVILEGES from only these additive objects.
-- Runtime authority must flow through the source-checked gateway, never through
-- an arbitrary default-granted group. Existing tables/functions remain intact.
DO $managed_acl$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.oid::regclass relation,a.grantee,r.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
  LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND c.relname IN ('embedding_generations','embedding_selection','embedding_vectors')
   AND a.grantee<>c.relowner LOOP
  EXECUTE format('REVOKE ALL ON TABLE %s FROM %s CASCADE',item.relation,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
 FOR item IN SELECT c.oid::regclass relation,att.attname,a.grantee,r.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  JOIN pg_attribute att ON att.attrelid=c.oid AND att.attnum>0
  CROSS JOIN LATERAL aclexplode(att.attacl) a LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND c.relname IN ('embedding_generations','embedding_selection','embedding_vectors')
   AND a.grantee<>c.relowner LOOP
  EXECUTE format('REVOKE ALL (%I) ON TABLE %s FROM %s CASCADE',item.attname,item.relation,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
 FOR item IN SELECT p.oid::regprocedure routine,a.grantee,r.rolname
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
  LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND p.proname IN ('embedding_source_hash','embedding_lifecycle_owner',
   'create_embedding_generation','put_embedding_vectors','select_embedding_generation')
   AND a.grantee<>p.proowner LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %s CASCADE',item.routine,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
END
$managed_acl$;
GRANT SELECT ON embedding_generations,embedding_selection,embedding_vectors TO rag_reader,rag_writer,rag_admin;
GRANT EXECUTE ON FUNCTION embedding_source_hash(text,text,text) TO rag_reader,rag_writer,rag_admin;
GRANT EXECUTE ON FUNCTION put_embedding_vectors(uuid,uuid[],text[],text[],text) TO rag_writer,rag_admin;
