-- RAG-067 (0.6.20): durable extraction-policy bindings. Additive and empty after
-- migration; no existing row, batch, queue payload, window, function body of
-- 001..031 or evidence version (ev1/src1) changes. Work without a binding or
-- without policy metadata keeps the builtin (legacy) interpretation.
-- Contract: docs/specs/6-9-extraction-instructions/spec.md, AC-005/006/009.

-- One immutable normalized policy snapshot per mining input cursor, committed
-- with its audit row before the first provider call. Not an authorization
-- credential: current authority is always checked again.
CREATE TABLE public.extraction_policy_bindings (
    session_id text NOT NULL,
    input_cursor text NOT NULL DEFAULT '',
    digest text NOT NULL CHECK (digest ~ '^xb1:[0-9a-f]{64}$'),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object' AND octet_length(snapshot::text) <= 65536),
    origin text NOT NULL CHECK (origin IN ('legacy', 'queue', 'window', 'direct')),
    created_by text NOT NULL DEFAULT current_user,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, input_cursor)
);

CREATE FUNCTION public.rag_policy_binding_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'extraction policy bindings are immutable' USING ERRCODE = '42501';
END $$;
CREATE TRIGGER extraction_policy_binding_immutable BEFORE UPDATE OR DELETE ON public.extraction_policy_bindings
    FOR EACH ROW EXECUTE FUNCTION public.rag_policy_binding_immutable();
REVOKE ALL ON FUNCTION public.rag_policy_binding_immutable() FROM PUBLIC;

-- Strip inherited default privileges from only this relation, then grant.
DO $policy_acl$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.oid::regclass relation,a.grantee,r.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
  LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND c.relname='extraction_policy_bindings' AND a.grantee<>c.relowner LOOP
  EXECUTE format('REVOKE ALL ON TABLE %s FROM %s CASCADE',item.relation,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
END $policy_acl$;
GRANT SELECT ON public.extraction_policy_bindings TO rag_reader;
GRANT SELECT, INSERT ON public.extraction_policy_bindings TO rag_writer;
GRANT ALL ON public.extraction_policy_bindings TO rag_admin;

-- Same session isolation as mining_batches; the restrictive guard keeps any
-- future UPDATE grant from moving a foreign row into the caller's session.
ALTER TABLE public.extraction_policy_bindings ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_policy_bindings ON public.extraction_policy_bindings
    USING (NOT public.rag_service_active() OR public.rag_service_session(session_id))
    WITH CHECK (NOT public.rag_service_active() OR public.rag_service_session(session_id));
CREATE POLICY service_policy_bindings_old_write ON public.extraction_policy_bindings AS RESTRICTIVE FOR UPDATE
    USING (NOT public.rag_service_active() OR public.rag_service_session(session_id));
