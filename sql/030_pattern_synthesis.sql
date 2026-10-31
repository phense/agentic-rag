-- RAG-065: opt-in, scoped, source-linked pattern suggestions (contract pattern-v1).
-- Additive only: no original row, field, grant, audit or history record is
-- rewritten, no policy is created and nothing is scheduled by this migration.
-- Patterns are ordinary audited documents (dtype=synthesis, claim kind
-- inference); these tables only hold scoped policies, bounded durable work and
-- the immutable dependency registry that decides whether a pattern is current.

-- Durable runs ride the existing singleton worker queue as their own job kind.
ALTER TABLE public.mining_queue DROP CONSTRAINT mining_queue_kind_check;
ALTER TABLE public.mining_queue ADD CONSTRAINT mining_queue_kind_check
 CHECK(kind IN ('mine','embed','curate','backup','checkpoint_enrich','profile_refresh','source_window','synthesis'));

CREATE TABLE public.synthesis_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain text NOT NULL REFERENCES public.domains(name) ON DELETE CASCADE,
    project_scope text NOT NULL CHECK (project_scope <> 'unknown' AND length(project_scope) BETWEEN 1 AND 1000),
    enabled boolean NOT NULL DEFAULT false,
    version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    forward_from timestamptz,
    interval_seconds integer NOT NULL DEFAULT 86400 CHECK (interval_seconds BETWEEN 60 AND 2592000),
    next_due_at timestamptz,
    cursor_at timestamptz,
    cursor_id uuid,
    owner jsonb,
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domain, project_scope),
    CHECK (NOT enabled OR forward_from IS NOT NULL),
    CHECK ((cursor_at IS NULL) = (cursor_id IS NULL)),
    CHECK (owner IS NULL OR octet_length(owner::text) <= 4096)
);

CREATE TABLE public.synthesis_backfills (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id uuid NOT NULL REFERENCES public.synthesis_policies(id) ON DELETE CASCADE,
    domain text NOT NULL,
    project_scope text NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    max_batches integer NOT NULL CHECK (max_batches BETWEEN 1 AND 10),
    batches integer NOT NULL DEFAULT 0 CHECK (batches >= 0),
    cursor_at timestamptz,
    cursor_id uuid,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','done','cancelled')),
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    owner jsonb,
    requested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CHECK (window_start < window_end AND window_end - window_start <= interval '366 days'),
    CHECK ((cursor_at IS NULL) = (cursor_id IS NULL)),
    CHECK (owner IS NULL OR octet_length(owner::text) <= 4096)
);

CREATE TABLE public.synthesis_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id uuid NOT NULL REFERENCES public.synthesis_policies(id) ON DELETE CASCADE,
    policy_version bigint NOT NULL,
    backfill_id uuid REFERENCES public.synthesis_backfills(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('forward','backfill')),
    domain text NOT NULL,
    project_scope text NOT NULL,
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','accepted','applied','non_conclusion','withheld','error')),
    code text CHECK (code IS NULL OR length(code) <= 80),
    candidates integer NOT NULL CHECK (candidates BETWEEN 0 AND 12),
    snapshot jsonb NOT NULL,
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    end_cursor_at timestamptz,
    end_cursor_id uuid,
    accepted jsonb,
    accepted_at timestamptz,
    provider jsonb,
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    result jsonb,
    owner jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'backfill') = (backfill_id IS NOT NULL)),
    CHECK (octet_length(snapshot::text) <= 262144),
    CHECK (accepted IS NULL OR octet_length(accepted::text) <= 65536),
    CHECK (result IS NULL OR octet_length(result::text) <= 65536),
    CHECK (octet_length(usage::text) <= 4096),
    CHECK (owner IS NULL OR octet_length(owner::text) <= 4096),
    CHECK (state <> 'accepted' OR accepted IS NOT NULL)
);
-- At most one open run per policy; concurrent schedulers cannot double-book.
CREATE UNIQUE INDEX synthesis_runs_open ON public.synthesis_runs(policy_id) WHERE state IN ('pending','accepted');
CREATE INDEX synthesis_runs_recent ON public.synthesis_runs(created_at DESC, id);

CREATE TABLE public.synthesis_patterns (
    document_id uuid PRIMARY KEY REFERENCES public.documents(id) ON DELETE CASCADE,
    application_key text NOT NULL UNIQUE CHECK (application_key ~ '^[0-9a-f]{64}$'),
    policy_id uuid NOT NULL REFERENCES public.synthesis_policies(id) ON DELETE CASCADE,
    run_id uuid NOT NULL REFERENCES public.synthesis_runs(id) ON DELETE CASCADE,
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
    statement text NOT NULL CHECK (length(statement) BETWEEN 1 AND 600),
    confidence text NOT NULL CHECK (confidence IN ('low','medium','high')),
    parts jsonb NOT NULL CHECK (octet_length(parts::text) <= 65536),
    dependency_count integer NOT NULL CHECK (dependency_count BETWEEN 3 AND 8),
    events integer NOT NULL CHECK (events >= 3),
    memories integer NOT NULL CHECK (memories >= 3),
    applied_by text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- One row per cited exact original span. Only originals may be dependencies, so
-- a pattern can never support another pattern (no dependency cycle).
CREATE TABLE public.synthesis_dependencies (
    document_id uuid NOT NULL REFERENCES public.synthesis_patterns(document_id) ON DELETE CASCADE,
    original_id uuid NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    original_version text NOT NULL CHECK (original_version ~ '^ev1:[0-9a-f]{64}$'),
    source_key text NOT NULL,
    span_hash text NOT NULL,
    source_version text NOT NULL CHECK (source_version ~ '^src1:[0-9a-f]{64}$'),
    PRIMARY KEY (document_id, original_id, source_key, span_hash),
    CHECK (document_id <> original_id)
);
CREATE INDEX synthesis_dependencies_original ON public.synthesis_dependencies(original_id);

-- Structural anti-recursion. Definer so the check cannot be narrowed by the
-- caller's row visibility; it reads only identifiers and returns no data.
CREATE FUNCTION public.rag_synthesis_dependency_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_TABLE_NAME = 'synthesis_dependencies' THEN
        IF EXISTS (SELECT 1 FROM public.synthesis_patterns p WHERE p.document_id = NEW.original_id)
           OR EXISTS (SELECT 1 FROM public.documents d WHERE d.id = NEW.original_id AND d.dtype = 'synthesis') THEN
            RAISE EXCEPTION 'pattern_dependency_must_be_original' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF EXISTS (SELECT 1 FROM public.synthesis_dependencies x WHERE x.original_id = NEW.document_id)
           OR NOT EXISTS (SELECT 1 FROM public.documents d WHERE d.id = NEW.document_id AND d.dtype = 'synthesis') THEN
            RAISE EXCEPTION 'pattern_must_be_new_synthesis_document' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER synthesis_dependency_guard BEFORE INSERT ON public.synthesis_dependencies
    FOR EACH ROW EXECUTE FUNCTION public.rag_synthesis_dependency_guard();
CREATE TRIGGER synthesis_pattern_guard BEFORE INSERT ON public.synthesis_patterns
    FOR EACH ROW EXECUTE FUNCTION public.rag_synthesis_dependency_guard();
REVOKE ALL ON FUNCTION public.rag_synthesis_dependency_guard() FROM PUBLIC;

-- Same persisted inputs and encoding as evidence_contract.DOCUMENT_VERSION_SQL
-- (ev1). Invoker rights: only rows visible to the caller participate.
CREATE FUNCTION public.rag_document_version(p_id uuid) RETURNS text
LANGUAGE sql STABLE AS $$
SELECT 'ev1:'||encode(sha256(convert_to(jsonb_build_array(
    d.id::text,d.domain,d.project_scope,d.status,extract(epoch FROM d.refuted_at),
    c.kind,c.review_state,c.content_hash,COALESCE(cr.revision,1),
    (SELECT COALESCE(jsonb_agg(jsonb_build_array(e.source_key,e.span_hash,
            encode(sha256(convert_to(e.quote,'UTF8')),'hex'),e.complete,e.reviewed,
            s.state,s.role,extract(epoch FROM s.source_at),COALESCE(sr.revision,1))
            ORDER BY e.source_key,e.span_hash),'[]'::jsonb)
       FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
       LEFT JOIN public.source_revisions sr USING(source_key) WHERE e.document_id=d.id),
    (SELECT jsonb_build_array(a.disposition,extract(epoch FROM a.event_at),extract(epoch FROM a.expires_at),a.relation)
       FROM public.fact_assertions a WHERE a.document_id=d.id)
  )::text,'UTF8')),'hex')
  FROM public.documents d LEFT JOIN public.claim_records c ON c.document_id=d.id
  LEFT JOIN public.claim_revisions cr ON cr.document_id=d.id WHERE d.id=p_id
$$;

-- A registered pattern is current only while its policy is enabled, it is active,
-- and every recorded original and cited source is visible, current and unchanged.
-- Invoker rights: an invisible dependency makes the pattern unavailable.
CREATE FUNCTION public.rag_pattern_current(p_id uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE
    pattern record;
    dependency record;
    seen integer := 0;
BEGIN
    SELECT p.policy_id,p.dependency_count INTO pattern FROM public.synthesis_patterns p WHERE p.document_id=p_id;
    IF NOT FOUND THEN RETURN false; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.synthesis_policies sp WHERE sp.id=pattern.policy_id AND sp.enabled) THEN
        RETURN false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.documents d WHERE d.id=p_id AND d.status='active') THEN
        RETURN false;
    END IF;
    FOR dependency IN
        SELECT x.original_id,x.original_version,x.source_key,x.span_hash,x.source_version
          FROM public.synthesis_dependencies x WHERE x.document_id=p_id
    LOOP
        seen := seen + 1;
        IF NOT EXISTS (SELECT 1 FROM public.documents d WHERE d.id=dependency.original_id AND d.status='active')
           OR NOT public.assertion_eligible(dependency.original_id, now(), false)
           OR public.rag_document_version(dependency.original_id) IS DISTINCT FROM dependency.original_version
           OR NOT EXISTS (SELECT 1 FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
                          LEFT JOIN public.source_revisions sr USING(source_key)
                          WHERE e.document_id=dependency.original_id AND e.source_key=dependency.source_key
                            AND e.span_hash=dependency.span_hash AND s.state='active'
                            AND 'src1:'||encode(sha256(convert_to(jsonb_build_array(s.source_key,COALESCE(sr.revision,1),
                                s.state,s.role,extract(epoch FROM s.source_at))::text,'UTF8')),'hex') = dependency.source_version) THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN seen = pattern.dependency_count;
END $$;

-- Preserve migration023's keyed invoker lookups and every existing outcome for
-- non-pattern documents. Only a registered pattern adds its dependency guard, so
-- a later confirmation can never expose a stale or unauthorized pattern.
CREATE OR REPLACE FUNCTION public.claim_eligible(p_id uuid) RETURNS boolean
LANGUAGE plpgsql STABLE COST 100 AS $$
DECLARE
    claim_kind text;
    claim_review text;
    evidence record;
    source_state text;
    source_role text;
BEGIN
    SELECT c.kind,c.review_state INTO claim_kind,claim_review
      FROM public.claim_records c WHERE c.document_id=p_id;
    IF NOT FOUND THEN RETURN true; END IF;
    IF claim_review='refuted' OR (claim_review<>'confirmed' AND claim_kind<>'stated') THEN
        RETURN false;
    END IF;
    IF claim_kind='inference' AND EXISTS (SELECT 1 FROM public.synthesis_patterns p WHERE p.document_id=p_id)
       AND NOT public.rag_pattern_current(p_id) THEN
        RETURN false;
    END IF;
    FOR evidence IN
        SELECT e.source_key,e.complete,e.reviewed FROM public.claim_evidence e
          WHERE e.document_id=p_id
    LOOP
        IF (claim_review='confirmed' AND evidence.reviewed)
           OR (claim_kind='stated' AND evidence.complete) THEN
            SELECT s.state,s.role INTO source_state,source_role
              FROM public.knowledge_sources s WHERE s.source_key=evidence.source_key;
            IF FOUND AND source_state='active' AND (
                (claim_review='confirmed' AND evidence.reviewed)
                OR (claim_kind='stated' AND source_role='user' AND evidence.complete)
            ) THEN RETURN true; END IF;
        END IF;
    END LOOP;
    RETURN false;
END $$;

-- Migration020 predicate plus one change: the history shortcut no longer admits
-- a registered pattern; it must pass the full claim predicate (and its guard).
CREATE OR REPLACE FUNCTION assertion_eligible(p_id uuid, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT (p_history AND NOT EXISTS (SELECT 1 FROM synthesis_patterns sp WHERE sp.document_id=p_id))
OR (claim_eligible(p_id) AND NOT EXISTS (
    SELECT 1 FROM fact_assertions a JOIN documents d ON d.id=a.document_id
    WHERE a.document_id=p_id AND (
        a.disposition <> 'accepted' OR a.event_at IS NULL OR a.event_at > p_at
        OR (a.expires_at IS NOT NULL AND a.expires_at <= p_at)
        OR EXISTS (
            SELECT 1 FROM fact_assertions newer JOIN documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute
              AND nd.project_scope=d.project_scope AND nd.domain=d.domain
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at > a.event_at AND newer.event_at <= p_at
        )
    )
))
$$;

-- Strip inherited default privileges from only these relations, then grant.
DO $synthesis_acl$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.oid::regclass relation,a.grantee,r.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
  LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND c.relname IN ('synthesis_policies','synthesis_backfills','synthesis_runs',
        'synthesis_patterns','synthesis_dependencies') AND a.grantee<>c.relowner LOOP
  EXECUTE format('REVOKE ALL ON TABLE %s FROM %s CASCADE',item.relation,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
END $synthesis_acl$;
GRANT SELECT ON public.synthesis_policies, public.synthesis_backfills, public.synthesis_runs,
    public.synthesis_patterns, public.synthesis_dependencies TO rag_reader;
GRANT SELECT, INSERT, UPDATE ON public.synthesis_policies, public.synthesis_backfills, public.synthesis_runs TO rag_writer;
GRANT SELECT, INSERT ON public.synthesis_patterns, public.synthesis_dependencies TO rag_writer;
GRANT ALL ON public.synthesis_policies, public.synthesis_backfills, public.synthesis_runs,
    public.synthesis_patterns, public.synthesis_dependencies TO rag_admin;
REVOKE ALL ON FUNCTION public.rag_document_version(uuid), public.rag_pattern_current(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rag_document_version(uuid), public.rag_pattern_current(uuid)
    TO rag_reader, rag_writer, rag_admin;

-- Service scope: policies and work follow their concrete domain/project; the
-- registry follows the pattern document and, for dependencies, the original too.
ALTER TABLE public.synthesis_policies ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_synthesis_policies ON public.synthesis_policies
    USING (public.rag_service_document(domain, project_scope))
    WITH CHECK (public.rag_service_document(domain, project_scope, true));
CREATE POLICY service_synthesis_policies_old_write ON public.synthesis_policies AS RESTRICTIVE FOR UPDATE
    USING (public.rag_service_document(domain, project_scope, true));
ALTER TABLE public.synthesis_backfills ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_synthesis_backfills ON public.synthesis_backfills
    USING (public.rag_service_document(domain, project_scope))
    WITH CHECK (public.rag_service_document(domain, project_scope, true));
CREATE POLICY service_synthesis_backfills_old_write ON public.synthesis_backfills AS RESTRICTIVE FOR UPDATE
    USING (public.rag_service_document(domain, project_scope, true));
ALTER TABLE public.synthesis_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_synthesis_runs ON public.synthesis_runs
    USING (public.rag_service_document(domain, project_scope))
    WITH CHECK (public.rag_service_document(domain, project_scope, true));
CREATE POLICY service_synthesis_runs_old_write ON public.synthesis_runs AS RESTRICTIVE FOR UPDATE
    USING (public.rag_service_document(domain, project_scope, true));
ALTER TABLE public.synthesis_patterns ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_synthesis_patterns ON public.synthesis_patterns
    USING (NOT public.rag_service_active() OR EXISTS (SELECT 1 FROM public.documents d WHERE d.id=document_id))
    WITH CHECK (NOT public.rag_service_active() OR EXISTS (SELECT 1 FROM public.documents d
        WHERE d.id=document_id AND public.rag_service_document(d.domain, d.project_scope, true)));
ALTER TABLE public.synthesis_dependencies ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_synthesis_dependencies ON public.synthesis_dependencies
    USING (NOT public.rag_service_active() OR (
        EXISTS (SELECT 1 FROM public.documents d WHERE d.id=document_id)
        AND EXISTS (SELECT 1 FROM public.documents o WHERE o.id=original_id)))
    WITH CHECK (NOT public.rag_service_active() OR (
        EXISTS (SELECT 1 FROM public.documents d WHERE d.id=document_id
                AND public.rag_service_document(d.domain, d.project_scope, true))
        AND EXISTS (SELECT 1 FROM public.documents o WHERE o.id=original_id)));
