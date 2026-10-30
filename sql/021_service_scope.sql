-- Additive service scope. Legacy role grants/data remain unchanged.
CREATE FUNCTION rag_service_active() RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(current_setting('rag_service.active',true),'')='1'
$$;
CREATE FUNCTION rag_service_allows(p_value text,p_kind text,p_write boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT rag_service_active() OR
 COALESCE((current_setting('rag_service.' || CASE WHEN p_write THEN 'write_' ELSE 'read_' END || p_kind,true)::jsonb ? p_value)
 OR (current_setting('rag_service.' || CASE WHEN p_write THEN 'write_' ELSE 'read_' END || p_kind,true)::jsonb ? '*'),false)
$$;
CREATE FUNCTION rag_service_document(p_domain text,p_scope text,p_write boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT rag_service_allows(p_domain,'domains',p_write) AND rag_service_allows(p_scope,'projects',p_write)
$$;
CREATE FUNCTION rag_service_session(p_session text) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT NOT rag_service_active() OR starts_with(p_session,'svc1:' || current_setting('rag_service.namespace',true) || ':')
$$;
CREATE FUNCTION rag_service_assert_document(p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF public.rag_service_active() AND NOT EXISTS(SELECT 1 FROM public.documents WHERE id=p_id AND public.rag_service_document(domain,project_scope,true)) THEN
  RAISE EXCEPTION 'scope denied' USING ERRCODE='42501';
 END IF;
END $$;
CREATE OR REPLACE FUNCTION replace_chunks(
    p_document_id uuid, p_contents text[], p_embeddings text[]
) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog,public,pg_temp AS $$
DECLARE n int;
BEGIN
    PERFORM public.rag_service_assert_document(p_document_id);
    DELETE FROM public.chunks WHERE document_id = p_document_id;
    INSERT INTO public.chunks(document_id, idx, content, embedding)
    SELECT p_document_id, t.i - 1, t.c,
           CASE WHEN t.e IS NULL THEN NULL ELSE t.e::public.halfvec END
    FROM unnest(p_contents, p_embeddings) WITH ORDINALITY AS t(c, e, i);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;
CREATE OR REPLACE FUNCTION put_chunk_contexts(p_doc uuid,p_ids uuid[],p_contexts text[],p_vectors text[],p_hashes text[],p_digest text)
RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE changed int;
BEGIN
 PERFORM public.rag_service_assert_document(p_doc);
 IF cardinality(p_ids) IS DISTINCT FROM cardinality(p_contexts)
 OR cardinality(p_ids) IS DISTINCT FROM cardinality(p_vectors)
 OR cardinality(p_ids) IS DISTINCT FROM cardinality(p_hashes) THEN
  RAISE EXCEPTION 'context array lengths differ';
 END IF;
 IF EXISTS(SELECT 1 FROM unnest(p_ids,p_hashes) u(id,hash)
  LEFT JOIN public.chunks c ON c.id=u.id LEFT JOIN public.documents d ON d.id=c.document_id
  WHERE d.id IS DISTINCT FROM p_doc OR u.hash IS DISTINCT FROM public.chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)) THEN
  RAISE EXCEPTION 'context source changed; retry';
 END IF;
 INSERT INTO public.chunk_contexts(chunk_id,version,context,representation,source_hash,embedding,model_digest)
 SELECT c.id,1,u.context,u.context || E'\n' || left(c.content,4000),u.hash,u.vector::public.halfvec,p_digest
 FROM unnest(p_ids,p_contexts,p_vectors,p_hashes) u(id,context,vector,hash) JOIN public.chunks c ON c.id=u.id
 ON CONFLICT(chunk_id,version) DO UPDATE SET context=excluded.context,representation=excluded.representation,
 source_hash=excluded.source_hash,indexed_at=now(),
 embedding=CASE WHEN chunk_contexts.source_hash=excluded.source_hash AND chunk_contexts.representation=excluded.representation
  THEN COALESCE(excluded.embedding,chunk_contexts.embedding) ELSE excluded.embedding END,
 model_digest=CASE WHEN excluded.embedding IS NULL AND chunk_contexts.source_hash=excluded.source_hash AND chunk_contexts.representation=excluded.representation
  THEN chunk_contexts.model_digest ELSE excluded.model_digest END;
 GET DIAGNOSTICS changed=ROW_COUNT;
 RETURN changed;
END $$;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_documents ON documents
 USING(rag_service_document(domain,project_scope))
 WITH CHECK(rag_service_document(domain,project_scope,true));
ALTER TABLE domains ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_domains ON domains
 USING(rag_service_allows(name,'domains'))
 WITH CHECK(NOT rag_service_active());
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_chunks ON chunks
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id));
ALTER TABLE chunk_contexts ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_chunk_contexts ON chunk_contexts
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM chunks c WHERE c.id=chunk_id));
-- An unresolved local reference is valid. Once any target exists, it must be
-- visible, even when the gateway could not resolve its ID under RLS.
CREATE FUNCTION rag_service_edge_target(p_id uuid,p_slug text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT NOT public.rag_service_active() OR
 EXISTS(SELECT 1 FROM public.documents d WHERE (d.id=p_id OR (p_id IS NULL AND d.slug=p_slug))
  AND public.rag_service_document(d.domain,d.project_scope)) OR
 (p_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.documents d WHERE d.slug=p_slug))
$$;
ALTER TABLE edges ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_edges ON edges
 USING(NOT rag_service_active() OR
   (EXISTS(SELECT 1 FROM documents d WHERE d.id=src_id) AND
    rag_service_edge_target(dst_id,dst_slug)))
 WITH CHECK(NOT rag_service_active() OR
   (EXISTS(SELECT 1 FROM documents d WHERE d.id=src_id AND rag_service_document(d.domain,d.project_scope,true)) AND
    rag_service_edge_target(dst_id,dst_slug)));
ALTER TABLE pins ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_pins ON pins
 USING(NOT rag_service_active() OR
  ((rag_service_allows(COALESCE(scope_path,scope),'projects') OR
    (rag_service_allows('global','projects') AND rag_service_allows(scope,'domains')))
   AND (document_id IS NULL OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))))
 WITH CHECK(NOT rag_service_active() OR
  ((rag_service_allows(COALESCE(scope_path,scope),'projects',true) OR
    (rag_service_allows('global','projects',true) AND rag_service_allows(scope,'domains',true)))
   AND (document_id IS NULL OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)))));
ALTER TABLE fact_assertions ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_assertions ON fact_assertions
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))
 WITH CHECK(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)));
ALTER TABLE assertion_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_assertion_sources ON assertion_sources
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))
 WITH CHECK(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)));
ALTER TABLE claim_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_claims ON claim_records
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))
 WITH CHECK(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)));
ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_evidence ON claim_evidence
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))
 WITH CHECK(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)));
CREATE FUNCTION rag_service_source_write(p_key text,p_namespace text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT NOT public.rag_service_active() OR (
   NOT EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.documents d ON d.id=e.document_id
    WHERE e.source_key=p_key AND NOT public.rag_service_document(d.domain,d.project_scope,true))
   AND (public.rag_service_session(p_namespace) OR EXISTS(
    SELECT 1 FROM public.claim_evidence e JOIN public.documents d ON d.id=e.document_id
    WHERE e.source_key=p_key AND public.rag_service_document(d.domain,d.project_scope,true))))
$$;
ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_sources ON knowledge_sources
 USING(NOT rag_service_active() OR rag_service_source_write(source_key,namespace) OR EXISTS(
   SELECT 1 FROM claim_evidence e WHERE e.source_key=knowledge_sources.source_key))
 WITH CHECK(rag_service_source_write(source_key,namespace));
ALTER TABLE entity_identities ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_identities ON entity_identities
 USING(rag_service_document(domain,project_scope))
 WITH CHECK(rag_service_document(domain,project_scope,true));
ALTER TABLE assertion_entities ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_assertion_entities ON assertion_entities
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))
 WITH CHECK(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)));
ALTER TABLE entity_aliases ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_aliases ON entity_aliases
 USING(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id))
 WITH CHECK(NOT rag_service_active() OR EXISTS(SELECT 1 FROM documents d WHERE d.id=document_id AND rag_service_document(d.domain,d.project_scope,true)));
ALTER TABLE continuation_checkpoints ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_checkpoints ON continuation_checkpoints
 USING(NOT rag_service_active() OR (rag_service_session(session_id) AND rag_service_allows(COALESCE(project_root,'unknown'),'projects')))
 WITH CHECK(NOT rag_service_active() OR (rag_service_session(session_id) AND rag_service_allows(COALESCE(project_root,'unknown'),'projects',true)));
ALTER TABLE mining_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_batches ON mining_batches
 USING(NOT rag_service_active() OR rag_service_session(session_id))
 WITH CHECK(NOT rag_service_active() OR rag_service_session(session_id));
ALTER TABLE mining_queue ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_queue ON mining_queue
 USING(NOT rag_service_active() OR rag_service_session(session_id) OR
  (kind='embed' AND EXISTS(SELECT 1 FROM documents d WHERE d.id::text=payload->>'document_id')))
 WITH CHECK(NOT rag_service_active() OR rag_service_session(session_id) OR
  (kind='embed' AND EXISTS(SELECT 1 FROM documents d WHERE d.id::text=payload->>'document_id' AND rag_service_document(d.domain,d.project_scope,true))));
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_audit ON audit_log USING(NOT rag_service_active()) WITH CHECK(true);
-- Shared derived caches may contain foreign selection counts; use the engine's
-- existing missing-cache fallback for service readers until scoped caches exist.
ALTER TABLE project_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_profiles ON project_profiles USING(NOT rag_service_active()) WITH CHECK(NOT rag_service_active());
ALTER TABLE thematic_summaries ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_themes ON thematic_summaries USING(NOT rag_service_active()) WITH CHECK(NOT rag_service_active());

-- UPDATE must authorize BOTH the existing row and its proposed replacement.
-- SELECT visibility alone must never allow moving a readable row into a writable scope.
DO $scope_updates$
DECLARE p record;
BEGIN
 FOR p IN SELECT polrelid::regclass AS rel,polname,pg_get_expr(polwithcheck,polrelid) AS check_expr
  FROM pg_policy WHERE polname LIKE 'service_%' AND polwithcheck IS NOT NULL
  AND polrelid IN (SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace)
 LOOP
  EXECUTE format('CREATE POLICY %I ON %s AS RESTRICTIVE FOR UPDATE USING (%s)',
                 p.polname || '_old_write',p.rel,p.check_expr);
 END LOOP;
END $scope_updates$;
REVOKE ALL ON FUNCTION public.rag_service_assert_document(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rag_service_assert_document(uuid) TO rag_writer,rag_admin;
REVOKE ALL ON FUNCTION public.rag_service_source_write(text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rag_service_edge_target(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rag_service_source_write(text,text),public.rag_service_edge_target(uuid,text)
 TO rag_reader,rag_writer,rag_admin;

-- Transport authority owns audit attribution, including nested mining gateways.
-- Preserve legacy origin enums separately from the authenticated audit actor.
CREATE FUNCTION rag_service_audit_actor() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF public.rag_service_active() THEN
  NEW.actor=current_setting('rag_service.actor',true);
  IF NEW.actor IS NULL OR NEW.actor='' THEN RAISE EXCEPTION 'missing service actor'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER service_audit_actor BEFORE INSERT ON audit_log
 FOR EACH ROW EXECUTE FUNCTION rag_service_audit_actor();
