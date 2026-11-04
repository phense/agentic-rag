-- RAG-072. Private, explicitly enabled transactional metadata; no network work.
CREATE TABLE public.webhook_control (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), enabled boolean NOT NULL DEFAULT false,
 max_records integer NOT NULL DEFAULT 10000 CHECK(max_records BETWEEN 1 AND 10000),
 max_bytes bigint NOT NULL DEFAULT 33554432 CHECK(max_bytes BETWEEN 4096 AND 33554432)
);
INSERT INTO public.webhook_control(singleton) VALUES(true);
CREATE TABLE public.webhook_subscriptions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), namespace text NOT NULL CHECK(length(namespace)<=128),
 actor text NOT NULL CHECK(length(actor)<=256), credential_reference jsonb NOT NULL CHECK(octet_length(credential_reference::text)<=4096),
 domain text CHECK(length(domain) BETWEEN 1 AND 128), project text NOT NULL CHECK(length(project) BETWEEN 1 AND 4096),
 endpoint text NOT NULL CHECK(length(endpoint) BETWEEN 8 AND 2048),
 kinds jsonb NOT NULL CHECK(jsonb_typeof(kinds)='array' AND jsonb_array_length(kinds) BETWEEN 1 AND 16),
 enabled boolean NOT NULL DEFAULT true, revision integer NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 1024),
 generation integer NOT NULL DEFAULT 1 CHECK(generation BETWEEN 1 AND 32),
 idempotency_key uuid NOT NULL, request_digest text NOT NULL CHECK(length(request_digest)=64),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(namespace,idempotency_key)
);
CREATE TABLE public.webhook_events (
 id uuid PRIMARY KEY, kind text NOT NULL, resource text NOT NULL CHECK(length(resource)<=256),
 resource_version bigint NOT NULL CONSTRAINT webhook_event_staging_version CHECK(resource_version>=0), domain text,
 capture_xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
 capture_order bigint GENERATED ALWAYS AS IDENTITY, project text NOT NULL, owner_namespace text,
 anchors uuid[] NOT NULL DEFAULT '{}', payload jsonb NOT NULL CHECK(octet_length(payload::text)<=4096),
 wire text NOT NULL CHECK(octet_length(wire)<=4096), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE SEQUENCE public.webhook_resource_order AS bigint;
CREATE TABLE public.webhook_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id uuid NOT NULL REFERENCES public.webhook_events(id),
 subscription_id uuid NOT NULL REFERENCES public.webhook_subscriptions(id),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','leased','retry','acknowledged','dead','disabled','revoked','cancelled')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 6), replay_count integer NOT NULL DEFAULT 0 CHECK(replay_count BETWEEN 0 AND 8),
 lease uuid, lease_until timestamptz, due_at timestamptz NOT NULL DEFAULT now(),
 outcome text CHECK(outcome IN ('acknowledged','network','timeout','response','destination','key','off','disabled','revoked','exhausted','cancelled')),
 cancelled_from text CONSTRAINT webhook_cancel_origin CHECK(cancelled_from IN ('dead','revoked','disabled')),
 updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(event_id,subscription_id),
 CONSTRAINT webhook_cancel_marker CHECK((state='cancelled')=(cancelled_from IS NOT NULL))
);
CREATE INDEX webhook_due ON public.webhook_deliveries(due_at) WHERE state IN ('pending','retry','leased');
-- Scrub arbitrary ALTER DEFAULT PRIVILEGES, including unrelated grantees.
DO $acl$
DECLARE x record;
BEGIN
 FOR x IN SELECT c.relname,c.relkind,a.grantee,r.rolname FROM pg_catalog.pg_class c
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault(CASE WHEN c.relkind='S' THEN 's'::"char" ELSE 'r'::"char" END,c.relowner))) a
 LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee
 WHERE n.nspname='public' AND c.relname IN ('webhook_control','webhook_subscriptions','webhook_events','webhook_deliveries','webhook_resource_order','webhook_events_capture_order_seq') AND a.grantee<>c.relowner
 LOOP EXECUTE format('REVOKE ALL ON %s public.%I FROM %s CASCADE',CASE WHEN x.relkind='S' THEN 'SEQUENCE' ELSE 'TABLE' END,x.relname,
 CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE quote_ident(x.rolname) END); END LOOP;
END $acl$;

CREATE FUNCTION public.rag_webhook_emit(p_kind text,p_resource text,p_domain text,p_project text,p_namespace text,p_anchors uuid[],p_state text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE eid uuid; ver bigint; body jsonb; correlation text; ctl record; matches uuid[];
BEGIN
 SELECT * INTO ctl FROM public.webhook_control WHERE singleton;
 IF NOT ctl.enabled THEN RETURN; END IF;
 SELECT array_agg(id) INTO matches FROM public.webhook_subscriptions WHERE enabled AND project=p_project AND kinds ? p_kind
 AND ((p_domain IS NOT NULL AND domain=p_domain) OR (p_domain IS NULL AND domain IS NULL AND namespace=p_namespace));
 IF matches IS NULL THEN RETURN; END IF;
 -- Nonblocking per-transaction bound only; committed global admission is deferred.
 IF (SELECT count(*) FROM public.webhook_events WHERE capture_xid=pg_current_xact_id() AND resource_version=0)>=ctl.max_records OR
    (SELECT count(*) FROM public.webhook_deliveries d JOIN public.webhook_events e ON e.id=d.event_id
      WHERE e.capture_xid=pg_current_xact_id() AND e.resource_version=0)+cardinality(matches)>ctl.max_records THEN
  RAISE EXCEPTION 'webhook_capacity' USING ERRCODE='54000'; END IF;
 eid:=gen_random_uuid(); ver:=0;
 correlation:=nullif(current_setting('rag_webhook.correlation',true),'');
 IF correlation IS NULL THEN correlation:=gen_random_uuid()::text; PERFORM set_config('rag_webhook.correlation',correlation,true); END IF;
 body:=jsonb_build_object('event_id',eid,'event_version',1,'kind',p_kind,'resource_id',p_resource,
  'resource_version',ver,'at',clock_timestamp(),'scope',jsonb_build_object('domain',p_domain,'project',p_project),
  'correlation_id',correlation,'state',p_state);
 IF octet_length(body::text)>4096 OR (SELECT coalesce(sum(octet_length(wire)+octet_length(payload::text)),0) FROM public.webhook_events
   WHERE capture_xid=pg_current_xact_id() AND resource_version=0)+2*octet_length(body::text)>ctl.max_bytes THEN
  RAISE EXCEPTION 'webhook_capacity' USING ERRCODE='54000'; END IF;
 INSERT INTO public.webhook_events(id,kind,resource,resource_version,domain,project,owner_namespace,anchors,payload,wire)
 VALUES(eid,p_kind,p_resource,ver,p_domain,p_project,p_namespace,p_anchors,body,body::text);
 INSERT INTO public.webhook_deliveries(event_id,subscription_id) SELECT eid,unnest(matches);
END $$;

CREATE FUNCTION public.rag_webhook_capture() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE d record; k text; related record; op text;
BEGIN
 IF NOT (SELECT enabled FROM public.webhook_control WHERE singleton) THEN RETURN NULL; END IF;
 IF TG_TABLE_NAME='documents' THEN
  IF TG_OP='UPDATE' AND (NEW.title,NEW.body,NEW.status,NEW.domain,NEW.project_scope) IS NOT DISTINCT FROM
   (OLD.title,OLD.body,OLD.status,OLD.domain,OLD.project_scope) THEN RETURN NULL; END IF;
  k:=CASE WHEN TG_OP='INSERT' THEN 'memory.created' WHEN NEW.status='archived' THEN 'memory.archived' ELSE 'memory.changed' END;
  PERFORM public.rag_webhook_emit(k,NEW.id::text,NEW.domain,NEW.project_scope,NULL,ARRAY[NEW.id],NEW.status);
 ELSIF TG_TABLE_NAME='claim_history' THEN
  SELECT * INTO d FROM public.documents WHERE id=NEW.document_id;
  PERFORM public.rag_webhook_emit('claim.reviewed',NEW.document_id::text,d.domain,d.project_scope,NULL,ARRAY[NEW.document_id],NEW.state);
 ELSIF TG_TABLE_NAME='source_history' THEN
  FOR d IN SELECT DISTINCT doc.domain,doc.project_scope FROM public.claim_evidence e JOIN public.documents doc ON doc.id=e.document_id WHERE e.source_key=NEW.source_key
   AND EXISTS(SELECT 1 FROM public.webhook_subscriptions sub WHERE sub.enabled AND sub.domain=doc.domain
    AND sub.project=doc.project_scope AND sub.kinds ? 'source.changed')
  LOOP
   PERFORM public.rag_webhook_emit('source.changed',encode(sha256(convert_to(NEW.source_key,'UTF8')),'hex'),d.domain,d.project_scope,NULL,'{}',NEW.state);
  END LOOP;
 ELSIF TG_TABLE_NAME='lifecycle_events' THEN
  SELECT operation INTO op FROM public.lifecycle_decisions WHERE id=NEW.decision_id;
  PERFORM public.rag_webhook_emit('lifecycle.'||NEW.event,NEW.decision_id::text,NEW.domain,NEW.project_scope,NULL,ARRAY[NEW.member_id,NEW.target_id],op);
 ELSIF TG_TABLE_NAME='edges' THEN
  IF NEW.predicate NOT IN ('supersedes','duplicate_of') THEN RETURN NULL; END IF;
  SELECT * INTO d FROM public.documents WHERE id=NEW.src_id;
  SELECT * INTO related FROM public.documents WHERE id=NEW.dst_id;
  IF d.domain=related.domain AND d.project_scope=related.project_scope THEN
   PERFORM public.rag_webhook_emit('edge.'||CASE WHEN NEW.predicate='duplicate_of' THEN 'duplicate' ELSE NEW.predicate END,NEW.src_id::text,d.domain,d.project_scope,NULL,ARRAY[NEW.src_id,NEW.dst_id],NULL);
  END IF;
 ELSIF TG_TABLE_NAME='service_windows' THEN
  IF NEW.state NOT IN ('applied','error','cancelled') OR (TG_OP='UPDATE' AND OLD.state=NEW.state) THEN RETURN NULL; END IF;
  PERFORM public.rag_webhook_emit('job.'||NEW.state,NEW.id::text,NULL,NEW.project,NEW.owner_namespace,'{}',NEW.state);
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER webhook_documents AFTER INSERT OR UPDATE ON public.documents FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_capture();
CREATE TRIGGER webhook_claim_history AFTER INSERT ON public.claim_history FOR EACH ROW WHEN (NEW.operation='review') EXECUTE FUNCTION public.rag_webhook_capture();
CREATE TRIGGER webhook_source_history AFTER INSERT ON public.source_history FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_capture();
CREATE TRIGGER webhook_lifecycle AFTER INSERT ON public.lifecycle_events FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_capture();
CREATE TRIGGER webhook_edges AFTER INSERT ON public.edges FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_capture();
CREATE TRIGGER webhook_windows AFTER INSERT OR UPDATE ON public.service_windows FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_capture();

-- Management runs on the existing scoped/GROUP transaction, never a detached owner.
CREATE FUNCTION public.rag_webhook_manage(p_op text,p_args jsonb,p_reference jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE ns text; actor_name text; s public.webhook_subscriptions; prior public.webhook_subscriptions;
 dom text; proj text; kind text; digest text; did uuid; result jsonb;
BEGIN
 ns:=CASE WHEN public.rag_service_active() THEN current_setting('rag_service.namespace',true) ELSE 'local' END;
 actor_name:=CASE WHEN public.rag_service_active() THEN current_setting('rag_service.actor',true) ELSE 'webhook:local' END;
 IF ns IS NULL OR actor_name IS NULL THEN RAISE EXCEPTION 'webhook_unavailable' USING ERRCODE='42501'; END IF;
 -- NO KEY UPDATE is compatible with capture delivery FK KEY SHARE. Admission is deferred.
 IF p_op='subscribe' THEN
  dom:=p_args->>'domain'; proj:=p_args->>'project';
 ELSE
  IF p_op='status' THEN
   SELECT * INTO s FROM public.webhook_subscriptions WHERE id=(p_args->>'subscription_id')::uuid AND namespace=ns AND actor=actor_name;
  ELSE
   SELECT * INTO s FROM public.webhook_subscriptions WHERE id=(p_args->>'subscription_id')::uuid AND namespace=ns AND actor=actor_name FOR NO KEY UPDATE;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'webhook_unavailable' USING ERRCODE='P0002'; END IF;
  dom:=s.domain; proj:=s.project;
 END IF;
 IF p_op='status' THEN
  IF public.rag_service_active() AND NOT (public.rag_service_allows(proj,'projects') AND
     (CASE WHEN dom IS NULL THEN current_setting('rag_service.read_domains',true)::jsonb<>'[]'::jsonb ELSE public.rag_service_allows(dom,'domains') END)) THEN
   RAISE EXCEPTION 'webhook_unavailable' USING ERRCODE='P0002'; END IF;
  RETURN jsonb_build_object('subscription',to_jsonb(s)-'credential_reference'-'request_digest'-'endpoint'-'namespace'-'actor',
    'capture_enabled',(SELECT enabled FROM public.webhook_control),
    'deliveries',coalesce((SELECT jsonb_agg(row_to_json(x)) FROM
     (SELECT id,event_id,state,attempts,replay_count,outcome,updated_at FROM public.webhook_deliveries WHERE subscription_id=s.id ORDER BY updated_at DESC,id LIMIT 50) x),'[]'::jsonb));
 END IF;
 IF public.rag_service_active() AND NOT (public.rag_service_allows(proj,'projects',true) AND
   (CASE WHEN dom IS NULL THEN current_setting('rag_service.write_domains',true)::jsonb<>'[]'::jsonb ELSE public.rag_service_allows(dom,'domains',true) END)) THEN
  RAISE EXCEPTION 'webhook_unavailable' USING ERRCODE='42501'; END IF;
 IF p_op='subscribe' THEN
  IF dom IS NOT NULL AND (length(dom) NOT BETWEEN 1 AND 128 OR dom='*') OR proj IS NULL OR proj='*' THEN RAISE EXCEPTION 'webhook_invalid'; END IF;
  IF jsonb_typeof(p_args->'kinds')<>'array' OR jsonb_array_length(p_args->'kinds') NOT BETWEEN 1 AND 16 THEN RAISE EXCEPTION 'webhook_invalid'; END IF;
  FOR kind IN SELECT jsonb_array_elements_text(p_args->'kinds') LOOP
   IF (dom IS NULL AND kind NOT IN ('job.applied','job.error','job.cancelled')) OR
    (dom IS NOT NULL AND kind NOT IN ('memory.created','memory.changed','memory.archived','claim.reviewed','source.changed','lifecycle.applied','lifecycle.recorded','lifecycle.corrected','edge.supersedes','edge.duplicate','test')) THEN RAISE EXCEPTION 'webhook_invalid'; END IF;
  END LOOP;
  digest:=encode(sha256(convert_to((p_args-'idempotency_key')::text,'UTF8')),'hex');
  SELECT * INTO prior FROM public.webhook_subscriptions WHERE namespace=ns AND idempotency_key=(p_args->>'idempotency_key')::uuid;
  IF FOUND THEN
   IF prior.request_digest<>digest THEN RAISE EXCEPTION 'webhook_conflict' USING ERRCODE='40001'; END IF;
   RETURN jsonb_build_object('id',prior.id,'revision',prior.revision,'generation',prior.generation,'enabled',prior.enabled);
  END IF;
  IF (SELECT count(*) FROM public.webhook_subscriptions WHERE namespace=ns)>=32 OR (SELECT count(*) FROM public.webhook_subscriptions)>=10000 THEN RAISE EXCEPTION 'webhook_capacity' USING ERRCODE='54000'; END IF;
  INSERT INTO public.webhook_subscriptions(namespace,actor,credential_reference,domain,project,endpoint,kinds,idempotency_key,request_digest)
   VALUES(ns,actor_name,p_reference,dom,proj,p_args->>'endpoint',p_args->'kinds',(p_args->>'idempotency_key')::uuid,digest)
   ON CONFLICT(namespace,idempotency_key) DO NOTHING RETURNING * INTO s;
  IF NOT FOUND THEN
   SELECT * INTO prior FROM public.webhook_subscriptions WHERE namespace=ns AND idempotency_key=(p_args->>'idempotency_key')::uuid;
   IF prior.request_digest IS DISTINCT FROM digest THEN RAISE EXCEPTION 'webhook_conflict' USING ERRCODE='40001'; END IF;
   RETURN jsonb_build_object('id',prior.id,'revision',prior.revision,'generation',prior.generation,'enabled',prior.enabled);
  END IF;
 ELSE
  IF s.revision IS DISTINCT FROM (p_args->>'expected_revision')::integer THEN RAISE EXCEPTION 'webhook_conflict' USING ERRCODE='40001'; END IF;
  IF p_op='disable' THEN
   UPDATE public.webhook_subscriptions SET enabled=false,revision=revision+1 WHERE id=s.id RETURNING * INTO s;
   UPDATE public.webhook_deliveries SET state='disabled',lease=NULL,lease_until=NULL,outcome='disabled',updated_at=now() WHERE subscription_id=s.id AND state IN ('pending','retry','leased');
  ELSIF p_op='update' THEN
   UPDATE public.webhook_subscriptions SET endpoint=p_args->>'endpoint',enabled=true,revision=revision+1 WHERE id=s.id RETURNING * INTO s;
  ELSIF p_op='rotate' THEN
   IF s.generation>=32 THEN RAISE EXCEPTION 'webhook_capacity' USING ERRCODE='54000'; END IF;
   UPDATE public.webhook_subscriptions SET generation=generation+1,revision=revision+1 WHERE id=s.id RETURNING * INTO s;
  ELSIF p_op='replay' THEN
   did:=(p_args->>'delivery_id')::uuid;
   UPDATE public.webhook_deliveries SET state='pending',attempts=0,replay_count=replay_count+1,due_at=now(),lease=NULL,lease_until=NULL,outcome=NULL,cancelled_from=NULL,updated_at=now()
    WHERE id=did AND subscription_id=s.id AND state IN ('dead','acknowledged','disabled','revoked','cancelled') AND replay_count<8;
   IF NOT FOUND THEN RAISE EXCEPTION 'webhook_unavailable' USING ERRCODE='P0002'; END IF;
  ELSIF p_op='test' THEN
   IF NOT s.enabled THEN RAISE EXCEPTION 'webhook_disabled'; END IF;
   -- Explicit test intent, delivery is always performed by the separate sender.
   did:=gen_random_uuid();
   result:=jsonb_build_object('event_id',did,'event_version',1,'kind','test','resource_id',s.id,'resource_version',0,'at',clock_timestamp(),
    'scope',jsonb_build_object('domain',s.domain,'project',s.project),'correlation_id',gen_random_uuid(),'state','test');
   IF NOT (SELECT enabled FROM public.webhook_control) THEN RAISE EXCEPTION 'webhook_off'; END IF;
   INSERT INTO public.webhook_events(id,kind,resource,resource_version,domain,project,owner_namespace,payload,wire)
    VALUES(did,'test',s.id::text,(result->>'resource_version')::bigint,s.domain,s.project,s.namespace,result,result::text);
   INSERT INTO public.webhook_deliveries(event_id,subscription_id) VALUES(did,s.id);
  ELSE RAISE EXCEPTION 'webhook_invalid'; END IF;
 END IF;
 INSERT INTO public.audit_log(actor,op,summary) VALUES(actor_name,'webhook.'||p_op,s.id::text);
 RETURN jsonb_build_object('id',s.id,'revision',s.revision,'generation',s.generation,'enabled',s.enabled);
END $$;
-- At transaction end all supported canonical producers have finished acquiring
-- their resource locks. Serialize committed metadata admission and final event
-- order here, never in the immediate producer. The no-op UPDATE creates a new
-- row version: a concurrent stale REPEATABLE READ snapshot must abort40001.
CREATE FUNCTION public.rag_webhook_finalize() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE ctl record; e record; ver bigint; body jsonb;
BEGIN
 IF TG_TABLE_NAME='webhook_events' AND NOT EXISTS(SELECT 1 FROM public.webhook_events
    WHERE capture_xid=pg_current_xact_id() AND resource_version=0) THEN RETURN NULL; END IF;
 UPDATE public.webhook_control SET enabled=enabled WHERE singleton RETURNING * INTO ctl;
 IF NOT FOUND THEN RAISE EXCEPTION 'incompatible_service_schema'; END IF;
 FOR e IN SELECT id,payload FROM public.webhook_events
   WHERE capture_xid=pg_current_xact_id() AND resource_version=0 ORDER BY capture_order
 LOOP
  ver:=nextval('public.webhook_resource_order');
  body:=jsonb_set(e.payload,'{resource_version}',to_jsonb(ver));
  IF octet_length(body::text)>4096 THEN RAISE EXCEPTION 'webhook_capacity' USING ERRCODE='54000'; END IF;
  UPDATE public.webhook_events SET resource_version=ver,payload=body,wire=body::text WHERE id=e.id;
 END LOOP;
 IF (SELECT count(*) FROM public.webhook_events)>ctl.max_records OR
    (SELECT count(*) FROM public.webhook_deliveries)>ctl.max_records OR
    (SELECT coalesce(sum(octet_length(wire)+octet_length(payload::text)),0) FROM public.webhook_events)>ctl.max_bytes OR
    (SELECT count(*) FROM public.webhook_subscriptions)>10000 OR
    EXISTS(SELECT 1 FROM public.webhook_subscriptions GROUP BY namespace HAVING count(*)>32) THEN
  RAISE EXCEPTION 'webhook_capacity' USING ERRCODE='54000'; END IF;
 RETURN NULL;
END $$;
CREATE INDEX webhook_staged ON public.webhook_events(capture_xid,capture_order) WHERE resource_version=0;
CREATE CONSTRAINT TRIGGER webhook_event_admission AFTER INSERT ON public.webhook_events
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_finalize();
CREATE CONSTRAINT TRIGGER webhook_subscription_admission AFTER INSERT ON public.webhook_subscriptions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_finalize();
-- Also guard fanout when a caller explicitly forces constraints IMMEDIATE:
-- the event admission then precedes delivery INSERT, so this check is essential.
CREATE CONSTRAINT TRIGGER webhook_delivery_admission AFTER INSERT ON public.webhook_deliveries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.rag_webhook_finalize();

-- Read wrapper prevents readers from invoking the mutating RPC.
CREATE FUNCTION public.rag_webhook_status(p_args jsonb) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$ SELECT public.rag_webhook_manage('status',p_args) $$;
DO $function_acl$
DECLARE x record;
BEGIN
 FOR x IN SELECT p.oid::regprocedure identity,a.grantee,r.rolname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a LEFT JOIN pg_roles r ON r.oid=a.grantee
 WHERE n.nspname='public' AND p.proname LIKE 'rag_webhook_%' AND a.grantee<>p.proowner
 LOOP EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %s CASCADE',x.identity,CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE quote_ident(x.rolname) END); END LOOP;
END $function_acl$;
GRANT EXECUTE ON FUNCTION public.rag_webhook_manage(text,jsonb,jsonb) TO rag_writer;
GRANT EXECUTE ON FUNCTION public.rag_webhook_status(jsonb) TO rag_reader,rag_writer;
