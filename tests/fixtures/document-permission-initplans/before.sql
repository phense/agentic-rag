ALTER POLICY service_documents ON public.documents
 USING(rag_service_document(domain,project_scope))
 WITH CHECK(rag_service_document(domain,project_scope,true));
