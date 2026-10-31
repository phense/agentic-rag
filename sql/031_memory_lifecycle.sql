-- RAG-066 (0.6.19): source-preserving lifecycle overlay. Additive and empty after
-- migration; no existing row, function body of 001..030 or evidence version (ev1/src1)
-- changes. Decisions never rewrite documents, chunks, claims, evidence, edges or pins.
-- Contract: docs/specs/6-8-memory-lifecycle/contracts/lifecycle-v1.md.

-- Immutable decision identity plus one mutable state column. Anchors carry no
-- foreign key, so a purge of a refuted document keeps working and history survives.
CREATE TABLE public.lifecycle_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_key text NOT NULL UNIQUE CHECK (action_key ~ '^[0-9a-f]{64}$'),
    operation text NOT NULL CHECK (operation IN
        ('exact_duplicate','semantic_duplicate','extension','replacement','contradiction')),
    member_id uuid NOT NULL,
    target_id uuid NOT NULL,
    domain text NOT NULL,
    project_scope text NOT NULL CHECK (project_scope <> 'unknown'),
    proof text NOT NULL CHECK (proof IN ('exact','judgement','event_order')),
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    member_lv1 text NOT NULL CHECK (member_lv1 ~ '^lv1:[0-9a-f]{64}$'),
    target_lv1 text NOT NULL CHECK (target_lv1 ~ '^lv1:[0-9a-f]{64}$'),
    member_snapshot text NOT NULL CHECK (member_snapshot ~ '^ls1:[0-9a-f]{64}$'),
    target_snapshot text NOT NULL CHECK (target_snapshot ~ '^ls1:[0-9a-f]{64}$'),
    effective_at timestamptz,
    state text NOT NULL CHECK (state IN ('active','contested','corrected')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (member_id <> target_id),
    CHECK ((operation = 'replacement') = (effective_at IS NOT NULL)),
    CHECK (operation <> 'contradiction' OR state IN ('contested','corrected')),
    CHECK (operation = 'contradiction' OR state IN ('active','corrected'))
);
-- One active hiding decision per member; canonical lookups for the flat invariant.
CREATE UNIQUE INDEX lifecycle_decisions_active_member ON public.lifecycle_decisions(member_id) WHERE state = 'active';
CREATE INDEX lifecycle_decisions_active_target ON public.lifecycle_decisions(target_id) WHERE state = 'active';
CREATE INDEX lifecycle_decisions_member ON public.lifecycle_decisions(member_id, created_at, id);
CREATE INDEX lifecycle_decisions_target ON public.lifecycle_decisions(target_id, created_at, id);

-- Append-only history. Anchors and scope are copied from the decision by the guard.
CREATE TABLE public.lifecycle_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id uuid NOT NULL REFERENCES public.lifecycle_decisions(id),
    event text NOT NULL CHECK (event IN ('applied','recorded','corrected')),
    action_key text NOT NULL UNIQUE CHECK (action_key ~ '^[0-9a-f]{64}$'),
    request_key text UNIQUE CHECK (request_key IS NULL OR length(request_key) BETWEEN 1 AND 128),
    actor text NOT NULL,
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    member_id uuid NOT NULL,
    target_id uuid NOT NULL,
    domain text NOT NULL,
    project_scope text NOT NULL,
    at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lifecycle_events_decision ON public.lifecycle_events(decision_id, at, id);
CREATE INDEX lifecycle_events_member ON public.lifecycle_events(member_id);
CREATE INDEX lifecycle_events_target ON public.lifecycle_events(target_id);
CREATE INDEX lifecycle_events_scope ON public.lifecycle_events(project_scope, at);

-- The base predicate is migration030's assertion_eligible body, unchanged.
CREATE FUNCTION public.rag_assertion_eligible_base(p_id uuid, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false)
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

-- Immutable base snapshot: ev1 (claim/evidence/source revisions/state/scope/assertion)
-- plus title/body, dtype, status, domain, scope and updated_at. No lifecycle counts,
-- so applying or correcting never stales a relationship. One definition as an
-- invoker-rights view, because PostgreSQL 17 re-plans an SQL function nested in a
-- non-inlined one on every call: the per-row hidden check joins this view instead
-- of calling rag_document_version. Its ev1 column repeats migration030 exactly.
CREATE VIEW public.rag_lifecycle_snapshots WITH (security_invoker = true) AS
SELECT v.id, v.ev1, 'ls1:'||encode(sha256(convert_to(jsonb_build_array(
    v.ev1, encode(sha256(convert_to(jsonb_build_array(v.title,v.body)::text,'UTF8')),'hex'),
    v.dtype,v.status,v.domain,v.project_scope,extract(epoch FROM v.updated_at)
  )::text,'UTF8')),'hex') AS snapshot
  FROM (SELECT d.id,d.title,d.body,d.dtype,d.status,d.domain,d.project_scope,d.updated_at,
    'ev1:'||encode(sha256(convert_to(jsonb_build_array(
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
    )::text,'UTF8')),'hex') AS ev1
    FROM public.documents d LEFT JOIN public.claim_records c ON c.document_id=d.id
    LEFT JOIN public.claim_revisions cr ON cr.document_id=d.id) v;

CREATE FUNCTION public.rag_lifecycle_snapshot(p_id uuid) RETURNS text
LANGUAGE sql STABLE AS $$
SELECT s.snapshot FROM public.rag_lifecycle_snapshots s WHERE s.id=p_id
$$;

-- Optimistic action version: the base snapshot plus the monotonic count of
-- append-only lifecycle events touching the document (apply/correct ABA).
CREATE FUNCTION public.rag_lifecycle_version(p_id uuid) RETURNS text
LANGUAGE sql STABLE AS $$
SELECT 'lv1:'||encode(sha256(convert_to(jsonb_build_array(s.snapshot,
    (SELECT count(*) FROM public.lifecycle_events e WHERE e.member_id=p_id OR e.target_id=p_id)
  )::text,'UTF8')),'hex')
  FROM (SELECT public.rag_lifecycle_snapshot(p_id) snapshot) s WHERE s.snapshot IS NOT NULL
$$;

-- Event basis of an original: earliest qualifying active source time, as in
-- search._TEMPORAL_SQL. NULL when unknown. Never ingestion or update time.
CREATE FUNCTION public.rag_lifecycle_event_basis(p_id uuid) RETURNS timestamptz
LANGUAGE sql STABLE AS $$
SELECT min(k.source_at) FROM public.claim_records c
  JOIN public.claim_evidence e ON e.document_id=c.document_id
  JOIN public.knowledge_sources k ON k.source_key=e.source_key
 WHERE c.document_id=p_id AND c.review_state<>'refuted' AND k.state='active'
   AND NOT EXISTS (SELECT 1 FROM public.fact_assertions a WHERE a.document_id=p_id)
   AND ((c.review_state='confirmed' AND e.reviewed) OR (c.kind='stated' AND k.role='user' AND e.complete))
$$;

-- Whether a duplicate/extension still hides its member: both base snapshots are
-- unchanged and the target is base-eligible at the selected time. PL/pgSQL so the
-- snapshot plans are cached per session and the base check per transaction; it
-- runs only for members of an active duplicate/extension decision.
CREATE FUNCTION public.rag_lifecycle_merge_holds(p_member uuid, p_target uuid, p_member_snapshot text,
    p_target_snapshot text, p_at timestamptz) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF (SELECT s.snapshot FROM public.rag_lifecycle_snapshots s WHERE s.id=p_member) IS DISTINCT FROM p_member_snapshot
     OR (SELECT s.snapshot FROM public.rag_lifecycle_snapshots s WHERE s.id=p_target) IS DISTINCT FROM p_target_snapshot THEN
    RETURN false;
  END IF;
  RETURN public.rag_assertion_eligible_base(p_target, p_at, false);
END $$;

-- D7: replacement hides from its effective event until correction, whatever
-- happens to the target. Duplicate/extension hide only while rag_lifecycle_merge_holds;
-- otherwise the member answers through its own truth gates. p_merged_visible
-- bypasses only duplicate/extension hiding (include_merged), never replacement.
-- Documents that are no member of an active decision pay one index probe.
CREATE FUNCTION public.rag_lifecycle_hidden(p_id uuid, p_at timestamptz DEFAULT now(), p_merged_visible boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT EXISTS (SELECT 1 FROM public.lifecycle_decisions ld
  WHERE ld.member_id=p_id AND ld.state='active' AND (
    (ld.operation='replacement' AND ld.effective_at <= p_at)
    OR (ld.operation<>'replacement' AND NOT p_merged_visible
        AND public.rag_lifecycle_merge_holds(ld.member_id, ld.target_id, ld.member_snapshot, ld.target_snapshot, p_at))))
$$;

-- Explicit historical view: qualified accepted past observations, including
-- superseded, expired or lifecycle-hidden ones. Current source trust still applies
-- (claim_eligible, pattern guard); future, refuted, withdrawn or unqualified truth
-- stays excluded. Omitted legacy history keeps migration030 behavior.
CREATE FUNCTION public.rag_lifecycle_historical(p_id uuid, p_at timestamptz DEFAULT now())
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT public.claim_eligible(p_id)
   AND NOT EXISTS (SELECT 1 FROM public.fact_assertions a WHERE a.document_id=p_id
                   AND (a.disposition <> 'accepted' OR a.event_at IS NULL OR a.event_at > p_at))
   AND COALESCE(public.rag_lifecycle_event_basis(p_id) <= p_at, true)
$$;

-- Same signature as before (no overload). The view travels in the transaction-local
-- setting rag_lifecycle.view; unset/empty/current/latest mean current. Every
-- candidate family already filters with this predicate before its LIMIT.
CREATE OR REPLACE FUNCTION assertion_eligible(p_id uuid, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT CASE COALESCE(current_setting('rag_lifecycle.view', true), '')
  WHEN 'historical' THEN public.rag_lifecycle_historical(p_id, p_at)
  ELSE public.rag_assertion_eligible_base(p_id, p_at, p_history)
       AND (p_history OR NOT public.rag_lifecycle_hidden(p_id, p_at,
            COALESCE(current_setting('rag_lifecycle.view', true), '') = 'include_merged'))
END
$$;

-- migration030 pattern guard with one change: a dependency hidden by a lifecycle
-- decision withholds the pattern regardless of the request's view setting.
CREATE OR REPLACE FUNCTION public.rag_pattern_current(p_id uuid) RETURNS boolean
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
           OR NOT public.rag_assertion_eligible_base(dependency.original_id, now(), false)
           OR public.rag_lifecycle_hidden(dependency.original_id, now(), false)
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

-- Structural guard (definer, pinned search_path). Locks both anchors in id order,
-- then enforces anchor class/scope and the flat one-hop invariant, so concurrent or
-- direct writers cannot create chains or cycles. Reads identifiers only and raises
-- fixed messages without values. Identity columns are immutable; the only
-- transition is active|contested -> corrected.
CREATE FUNCTION public.rag_lifecycle_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE anchor record; found_anchors integer := 0;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.id, NEW.action_key, NEW.operation, NEW.member_id, NEW.target_id, NEW.domain, NEW.project_scope,
            NEW.proof, NEW.reason, NEW.member_lv1, NEW.target_lv1, NEW.member_snapshot, NEW.target_snapshot,
            NEW.effective_at, NEW.created_by, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.action_key, OLD.operation, OLD.member_id, OLD.target_id, OLD.domain, OLD.project_scope,
            OLD.proof, OLD.reason, OLD.member_lv1, OLD.target_lv1, OLD.member_snapshot, OLD.target_snapshot,
            OLD.effective_at, OLD.created_by, OLD.created_at) THEN
            RAISE EXCEPTION 'lifecycle:immutable_identity' USING ERRCODE = '23514';
        END IF;
        IF NOT (OLD.state IN ('active','contested') AND NEW.state = 'corrected') THEN
            RAISE EXCEPTION 'lifecycle:invalid_transition' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    FOR anchor IN SELECT d.id, d.domain, d.project_scope, d.status, d.dtype FROM public.documents d
                   WHERE d.id IN (NEW.member_id, NEW.target_id) ORDER BY d.id FOR UPDATE LOOP
        found_anchors := found_anchors + 1;
        IF anchor.domain <> NEW.domain OR anchor.project_scope <> NEW.project_scope OR anchor.project_scope = 'unknown' THEN
            RAISE EXCEPTION 'lifecycle:scope_mismatch' USING ERRCODE = '23514';
        END IF;
        IF anchor.status <> 'active' OR NOT public.rag_assertion_eligible_base(anchor.id, now(), false) THEN
            RAISE EXCEPTION 'lifecycle:not_current' USING ERRCODE = '23514';
        END IF;
        IF anchor.dtype = 'synthesis' OR EXISTS (SELECT 1 FROM public.synthesis_patterns p WHERE p.document_id = anchor.id) THEN
            RAISE EXCEPTION 'lifecycle:not_original' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (SELECT 1 FROM public.fact_assertions a WHERE a.document_id = anchor.id)
           OR EXISTS (SELECT 1 FROM public.entity_aliases x WHERE x.document_id = anchor.id) THEN
            RAISE EXCEPTION 'lifecycle:assertion_managed' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF found_anchors <> 2 THEN
        RAISE EXCEPTION 'lifecycle:not_found' USING ERRCODE = '23514';
    END IF;
    IF NEW.state = 'active' THEN
        IF EXISTS (SELECT 1 FROM public.lifecycle_decisions x WHERE x.member_id = NEW.member_id AND x.state = 'active') THEN
            RAISE EXCEPTION 'lifecycle:already_active' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (SELECT 1 FROM public.lifecycle_decisions x WHERE x.member_id = NEW.target_id AND x.state = 'active')
           OR EXISTS (SELECT 1 FROM public.lifecycle_decisions x WHERE x.target_id = NEW.member_id AND x.state = 'active') THEN
            RAISE EXCEPTION 'lifecycle:chain_conflict' USING ERRCODE = '23514';
        END IF;
        IF (SELECT count(*) FROM public.lifecycle_decisions x WHERE x.target_id = NEW.target_id AND x.state = 'active') >= 500 THEN
            RAISE EXCEPTION 'lifecycle:budget_exceeded' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER lifecycle_decision_guard BEFORE INSERT OR UPDATE ON public.lifecycle_decisions
    FOR EACH ROW EXECUTE FUNCTION public.rag_lifecycle_guard();

-- Events copy anchors/scope from their decision and must match its state, so the
-- history is coherent even for a direct writer.
CREATE FUNCTION public.rag_lifecycle_event_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE decision record;
BEGIN
    SELECT d.member_id, d.target_id, d.domain, d.project_scope, d.state, d.operation INTO decision
      FROM public.lifecycle_decisions d WHERE d.id = NEW.decision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'lifecycle:not_found' USING ERRCODE = '23514';
    END IF;
    IF (NEW.event = 'applied' AND decision.state <> 'active')
       OR (NEW.event = 'recorded' AND decision.state <> 'contested')
       OR (NEW.event = 'corrected' AND decision.state <> 'corrected')
       OR (NEW.event IN ('applied','recorded') AND EXISTS (SELECT 1 FROM public.lifecycle_events e WHERE e.decision_id = NEW.decision_id))
       OR (NEW.event = 'corrected' AND EXISTS (SELECT 1 FROM public.lifecycle_events e WHERE e.decision_id = NEW.decision_id AND e.event = 'corrected')) THEN
        RAISE EXCEPTION 'lifecycle:invalid_event' USING ERRCODE = '23514';
    END IF;
    NEW.member_id := decision.member_id;
    NEW.target_id := decision.target_id;
    NEW.domain := decision.domain;
    NEW.project_scope := decision.project_scope;
    RETURN NEW;
END $$;
CREATE TRIGGER lifecycle_event_guard BEFORE INSERT ON public.lifecycle_events
    FOR EACH ROW EXECUTE FUNCTION public.rag_lifecycle_event_guard();
CREATE TRIGGER lifecycle_events_append_only BEFORE UPDATE OR DELETE ON public.lifecycle_events
    FOR EACH ROW EXECUTE FUNCTION public.rag_history_append_only();
REVOKE ALL ON FUNCTION public.rag_lifecycle_guard(), public.rag_lifecycle_event_guard() FROM PUBLIC;

REVOKE ALL ON FUNCTION public.rag_assertion_eligible_base(uuid, timestamptz, boolean),
    public.rag_lifecycle_snapshot(uuid), public.rag_lifecycle_version(uuid),
    public.rag_lifecycle_event_basis(uuid), public.rag_lifecycle_hidden(uuid, timestamptz, boolean),
    public.rag_lifecycle_merge_holds(uuid, uuid, text, text, timestamptz),
    public.rag_lifecycle_historical(uuid, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rag_assertion_eligible_base(uuid, timestamptz, boolean),
    public.rag_lifecycle_snapshot(uuid), public.rag_lifecycle_version(uuid),
    public.rag_lifecycle_event_basis(uuid), public.rag_lifecycle_hidden(uuid, timestamptz, boolean),
    public.rag_lifecycle_merge_holds(uuid, uuid, text, text, timestamptz),
    public.rag_lifecycle_historical(uuid, timestamptz) TO rag_reader, rag_writer, rag_admin;

-- Strip inherited default privileges from only these relations, then grant.
DO $lifecycle_acl$
DECLARE item record;
BEGIN
 FOR item IN SELECT c.oid::regclass relation,a.grantee,r.rolname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
  LEFT JOIN pg_roles r ON r.oid=a.grantee
  WHERE n.nspname='public' AND c.relname IN ('lifecycle_decisions','lifecycle_events','rag_lifecycle_snapshots')
    AND a.grantee<>c.relowner LOOP
  EXECUTE format('REVOKE ALL ON TABLE %s FROM %s CASCADE',item.relation,
   CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
 END LOOP;
END $lifecycle_acl$;
GRANT SELECT ON public.lifecycle_decisions, public.lifecycle_events TO rag_reader;
GRANT SELECT, INSERT ON public.lifecycle_decisions, public.lifecycle_events TO rag_writer;
GRANT UPDATE (state) ON public.lifecycle_decisions TO rag_writer;
GRANT ALL ON public.lifecycle_decisions, public.lifecycle_events TO rag_admin;
GRANT SELECT ON public.rag_lifecycle_snapshots TO rag_reader, rag_writer, rag_admin;

-- Service scope: a decision follows its anchors' domain/project. A caller who can
-- read the member also reads its decision (and so stays hidden from a replaced value
-- after a later scope move). Writes need write authority on the decision scope.
ALTER TABLE public.lifecycle_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_lifecycle_decisions ON public.lifecycle_decisions
    USING (public.rag_service_document(domain, project_scope)
           OR EXISTS (SELECT 1 FROM public.documents d WHERE d.id = member_id))
    WITH CHECK (public.rag_service_document(domain, project_scope, true));
CREATE POLICY service_lifecycle_decisions_old_write ON public.lifecycle_decisions AS RESTRICTIVE FOR UPDATE
    USING (public.rag_service_document(domain, project_scope, true));
ALTER TABLE public.lifecycle_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_lifecycle_events ON public.lifecycle_events
    USING (public.rag_service_document(domain, project_scope)
           OR EXISTS (SELECT 1 FROM public.documents d WHERE d.id = member_id))
    WITH CHECK (public.rag_service_document(domain, project_scope, true));
CREATE POLICY service_lifecycle_events_old_write ON public.lifecycle_events AS RESTRICTIVE FOR UPDATE
    USING (public.rag_service_document(domain, project_scope, true));
