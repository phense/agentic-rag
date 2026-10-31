-- RAG-063: portable evidence revisions and append-only, scoped decision history.
-- Additive only: no original row, field, grant or audit record is rewritten.
-- A missing revision row means the storage-contract baseline revision 1; it
-- does not claim to know the historical content revision before this upgrade.
-- Revisions are persisted counters, never xmin/ctid, so they survive dump and
-- restore. A withdrawal followed by reinstatement advances twice (no ABA).
CREATE TABLE public.source_revisions (
    source_key text PRIMARY KEY,
    revision bigint NOT NULL CHECK (revision >= 2),
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.claim_revisions (
    document_id uuid PRIMARY KEY,
    revision bigint NOT NULL CHECK (revision >= 2),
    changed_at timestamptz NOT NULL DEFAULT now()
);
-- Source history is source-scoped and never records a document identifier.
CREATE TABLE public.source_history (
    source_key text NOT NULL,
    revision bigint NOT NULL,
    operation text NOT NULL CHECK (operation IN ('source_state')),
    state text,
    reason text,
    actor text NOT NULL,
    concurrency text NOT NULL CHECK (concurrency IN ('strict','legacy','direct')),
    inspected_version text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_key, revision),
    CHECK (concurrency = 'strict' OR inspected_version IS NULL)
);
-- Claim history is document-scoped; its source references are the document's own.
CREATE TABLE public.claim_history (
    document_id uuid NOT NULL,
    revision bigint NOT NULL,
    operation text NOT NULL CHECK (operation IN ('attach','review','span_review')),
    state text,
    reason text,
    source_key text,
    span_hash text,
    actor text NOT NULL,
    concurrency text NOT NULL CHECK (concurrency IN ('strict','legacy','direct')),
    inspected_version text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, revision),
    CHECK (concurrency = 'strict' OR inspected_version IS NULL)
);

-- Strict claim review needs a shared source lock even when another dependent
-- is outside the caller's write scope. PostgreSQL applies UPDATE RLS to direct
-- SELECT FOR SHARE, which would reject that otherwise authorized review.
-- This helper returns no data and locks only a source attached to an explicitly
-- readable AND writable anchor. It never grants source mutation authority.
CREATE FUNCTION public.rag_lock_claim_source(p_document uuid, p_source text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.documents d JOIN public.claim_evidence e ON e.document_id=d.id
        WHERE d.id=p_document AND e.source_key=p_source
          AND public.rag_service_document(d.domain,d.project_scope)
          AND public.rag_service_document(d.domain,d.project_scope,true)
    ) THEN
        RAISE EXCEPTION 'evidence_unavailable' USING ERRCODE='42501';
    END IF;
    PERFORM source_key FROM public.knowledge_sources WHERE source_key=p_source FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'evidence_unavailable' USING ERRCODE='42501';
    END IF;
END $$;
REVOKE ALL ON FUNCTION public.rag_lock_claim_source(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rag_lock_claim_source(uuid,text) TO rag_writer,rag_admin;

-- The audited gateway sets a transaction-local context. Without it, a change
-- is recorded truthfully as a direct change with no inspected version. The
-- service actor always comes from the authenticated transport, never input.
CREATE FUNCTION public.rag_evidence_context(OUT mode text, OUT actor text, OUT inspected text, OUT operation text)
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE raw text := NULLIF(current_setting('rag_evidence.context', true), ''); j jsonb;
BEGIN
    mode := 'direct'; actor := session_user; inspected := NULL; operation := NULL;
    IF raw IS NOT NULL THEN
        j := raw::jsonb;
        IF j->>'mode' IN ('strict','legacy') THEN mode := j->>'mode'; END IF;
        actor := COALESCE(NULLIF(left(j->>'actor', 200), ''), actor);
        operation := j->>'operation';
        IF mode = 'strict' THEN inspected := left(j->>'inspected', 200); END IF;
    END IF;
    IF public.rag_service_active() THEN
        actor := current_setting('rag_service.actor', true);
        IF actor IS NULL OR actor = '' THEN RAISE EXCEPTION 'missing service actor'; END IF;
    END IF;
END $$;

CREATE FUNCTION public.rag_source_revision_trigger() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE ctx record; rev bigint;
BEGIN
    SELECT * INTO ctx FROM public.rag_evidence_context();
    INSERT INTO public.source_revisions(source_key, revision) VALUES (NEW.source_key, 2)
    ON CONFLICT (source_key) DO UPDATE SET revision = public.source_revisions.revision + 1, changed_at = now()
    RETURNING revision INTO rev;
    INSERT INTO public.source_history(source_key, revision, operation, state, reason, actor, concurrency, inspected_version)
    VALUES (NEW.source_key, rev, 'source_state', NEW.state, NEW.reason, ctx.actor, ctx.mode, ctx.inspected);
    RETURN NULL;
END $$;

CREATE FUNCTION public.rag_claim_revision_bump(p_document uuid) RETURNS bigint
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    INSERT INTO public.claim_revisions(document_id, revision) VALUES (p_document, 2)
    ON CONFLICT (document_id) DO UPDATE SET revision = public.claim_revisions.revision + 1, changed_at = now()
    RETURNING revision
$$;

CREATE FUNCTION public.rag_claim_revision_trigger() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE ctx record; rev bigint;
BEGIN
    SELECT * INTO ctx FROM public.rag_evidence_context();
    rev := public.rag_claim_revision_bump(NEW.document_id);
    IF TG_TABLE_NAME = 'claim_records' THEN
        INSERT INTO public.claim_history(document_id, revision, operation, state, reason, actor, concurrency, inspected_version)
        VALUES (NEW.document_id, rev, 'review', NEW.review_state, NEW.reason, ctx.actor, ctx.mode, ctx.inspected);
    ELSIF TG_OP = 'INSERT' THEN
        INSERT INTO public.claim_history(document_id, revision, operation, state, source_key, span_hash, actor, concurrency, inspected_version)
        VALUES (NEW.document_id, rev, 'attach', CASE WHEN NEW.complete THEN 'complete' ELSE 'partial' END,
                NEW.source_key, NEW.span_hash, ctx.actor, ctx.mode, ctx.inspected);
    ELSIF ctx.operation IS DISTINCT FROM 'claim_review' THEN
        -- A claim review records one decision event on claim_records; other
        -- span-flag changes (for example alias acceptance) are recorded here.
        INSERT INTO public.claim_history(document_id, revision, operation, state, source_key, span_hash, actor, concurrency, inspected_version)
        VALUES (NEW.document_id, rev, 'span_review', CASE WHEN NEW.reviewed THEN 'reviewed' ELSE 'unreviewed' END,
                NEW.source_key, NEW.span_hash, ctx.actor, ctx.mode, ctx.inspected);
    END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION public.rag_history_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'evidence history is append-only' USING ERRCODE = '42501';
END $$;

CREATE TRIGGER source_revision AFTER UPDATE ON public.knowledge_sources
    FOR EACH ROW EXECUTE FUNCTION public.rag_source_revision_trigger();
CREATE TRIGGER claim_record_revision AFTER UPDATE ON public.claim_records
    FOR EACH ROW EXECUTE FUNCTION public.rag_claim_revision_trigger();
CREATE TRIGGER claim_evidence_revision AFTER INSERT OR UPDATE ON public.claim_evidence
    FOR EACH ROW EXECUTE FUNCTION public.rag_claim_revision_trigger();
CREATE TRIGGER source_history_append_only BEFORE UPDATE OR DELETE ON public.source_history
    FOR EACH ROW EXECUTE FUNCTION public.rag_history_append_only();
CREATE TRIGGER claim_history_append_only BEFORE UPDATE OR DELETE ON public.claim_history
    FOR EACH ROW EXECUTE FUNCTION public.rag_history_append_only();

REVOKE ALL ON FUNCTION public.rag_source_revision_trigger(), public.rag_claim_revision_trigger(),
    public.rag_claim_revision_bump(uuid), public.rag_history_append_only() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rag_evidence_context() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rag_evidence_context() TO rag_reader, rag_writer, rag_admin;

-- Strip inherited ALTER DEFAULT PRIVILEGES from only these new relations, then
-- grant read access. Only the definer triggers above may write; a limited role
-- able to reset a revision could recreate an inspected version (ABA).
DO $evidence_acl$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.oid::regclass relation,a.grantee,r.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
  LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND c.relname IN ('source_revisions','claim_revisions','source_history','claim_history')
   AND a.grantee<>c.relowner LOOP
  EXECUTE format('REVOKE ALL ON TABLE %s FROM %s CASCADE',item.relation,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
END $evidence_acl$;
GRANT SELECT ON public.source_revisions, public.claim_revisions, public.source_history, public.claim_history
    TO rag_reader, rag_writer, rag_admin;

-- Service scope follows the parent rows: no global audit-table shortcut and no
-- security-definer read path. Source rows are visible only through a visible
-- source; claim rows only through a visible document.
ALTER TABLE public.source_revisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_source_revisions ON public.source_revisions FOR SELECT
    USING (NOT public.rag_service_active() OR EXISTS (
        SELECT 1 FROM public.knowledge_sources s WHERE s.source_key = source_revisions.source_key));
ALTER TABLE public.source_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_source_history ON public.source_history FOR SELECT
    USING (NOT public.rag_service_active() OR EXISTS (
        SELECT 1 FROM public.knowledge_sources s WHERE s.source_key = source_history.source_key));
ALTER TABLE public.claim_revisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_claim_revisions ON public.claim_revisions FOR SELECT
    USING (NOT public.rag_service_active() OR EXISTS (
        SELECT 1 FROM public.documents d WHERE d.id = claim_revisions.document_id));
ALTER TABLE public.claim_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_claim_history ON public.claim_history FOR SELECT
    USING (NOT public.rag_service_active() OR EXISTS (
        SELECT 1 FROM public.documents d WHERE d.id = claim_history.document_id));
