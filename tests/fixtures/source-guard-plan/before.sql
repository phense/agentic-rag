CREATE FUNCTION rag_service_source_write(p_key text,p_namespace text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT NOT public.rag_service_active() OR (
   NOT EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.documents d ON d.id=e.document_id
    WHERE e.source_key=p_key AND NOT public.rag_service_document(d.domain,d.project_scope,true))
   AND (public.rag_service_session(p_namespace) OR EXISTS(
    SELECT 1 FROM public.claim_evidence e JOIN public.documents d ON d.id=e.document_id
    WHERE e.source_key=p_key AND public.rag_service_document(d.domain,d.project_scope,true))))
$$;
