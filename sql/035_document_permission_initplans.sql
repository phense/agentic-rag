-- Same service_documents authorization, statement-local permission inputs.
-- Keep this helper pure and inlinable: no SET, STRICT, definer, subquery or
-- parallel-safety override. Parameters occur once. Bind the operator explicitly
-- without adding a search_path SET that would prevent SQL-function inlining.
CREATE FUNCTION public.rag_service_permission(p_value text,p_permissions jsonb)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT COALESCE(p_permissions OPERATOR(pg_catalog.?|) ARRAY[p_value,'*'],false)
$$;
-- Like the original argument-only permission helpers, this grants no data
-- access. Include admin and additional deployment roles that encounter RLS.
GRANT EXECUTE ON FUNCTION public.rag_service_permission(text,jsonb) TO PUBLIC;

-- ALTER preserves the policy identity, roles, command and permissiveness.
-- Uncorrelated InitPlans are evaluated lazily on each statement execution,
-- including EXECUTE of a reused generic plan. Inactive/legacy callers bypass
-- JSON parsing exactly as in 021. Never move a SubLink into the SQL helper.
ALTER POLICY service_documents ON public.documents
 USING (NOT public.rag_service_active() OR (
   public.rag_service_permission(domain,
     (SELECT current_setting('rag_service.read_domains',true)::jsonb))
   AND public.rag_service_permission(project_scope,
     (SELECT current_setting('rag_service.read_projects',true)::jsonb))))
 WITH CHECK (NOT public.rag_service_active() OR (
   public.rag_service_permission(domain,
     (SELECT current_setting('rag_service.write_domains',true)::jsonb))
   AND public.rag_service_permission(project_scope,
     (SELECT current_setting('rag_service.write_projects',true)::jsonb))));
