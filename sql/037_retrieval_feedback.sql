-- Explicit opt-in metadata only. No changes to canonical knowledge or001..036.
CREATE TABLE public.retrieval_feedback_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 namespace text NOT NULL, actor text NOT NULL, client text NOT NULL, independence_id text NOT NULL,
 domain text NOT NULL REFERENCES public.domains(name), project_scope text NOT NULL,
 idempotency_key uuid NOT NULL, request_digest text NOT NULL CHECK(length(request_digest)=64),
 query_sha256 text NOT NULL CHECK(length(query_sha256)=64),
 settings jsonb NOT NULL, runtime jsonb NOT NULL, results jsonb NOT NULL,
 origin_request_id uuid, origin_correlation_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(namespace,idempotency_key),
 CHECK(jsonb_typeof(results)='array' AND jsonb_array_length(results)<=20),
 CHECK(octet_length(settings::text)+octet_length(runtime::text)+octet_length(results::text)<=65536)
);
CREATE TABLE public.retrieval_feedback (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id uuid NOT NULL REFERENCES public.retrieval_feedback_events(id),
 namespace text NOT NULL, actor text NOT NULL, client text NOT NULL, independence_id text NOT NULL,
 domain text NOT NULL, project_scope text NOT NULL,
 idempotency_key uuid NOT NULL, request_digest text NOT NULL CHECK(length(request_digest)=64),
 kind text NOT NULL CHECK(kind IN ('useful','not_useful','wrong_source','missing_evidence')),
 result_id uuid, result_version text, expected_id uuid, expected_version text,
 comment text NOT NULL CHECK(length(comment)<=1000),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
 revision integer NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 32),
 history jsonb NOT NULL CHECK(jsonb_typeof(history)='array' AND jsonb_array_length(history)=revision),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(namespace,idempotency_key)
);
CREATE INDEX retrieval_feedback_events_owner ON public.retrieval_feedback_events(namespace,created_at);
CREATE INDEX retrieval_feedback_owner ON public.retrieval_feedback(namespace,updated_at);
-- Narrow operator-only extension seam; approval implementation follows separately.
CREATE TABLE public.retrieval_feedback_approvals (
 feedback_id uuid PRIMARY KEY REFERENCES public.retrieval_feedback(id),
 revision integer NOT NULL, query text NOT NULL CHECK(length(query)<=512),
 expected_id uuid NOT NULL, expected_version text NOT NULL,
 families jsonb NOT NULL, approved_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON public.retrieval_feedback_approvals FROM PUBLIC,rag_reader,rag_writer,rag_admin;
REVOKE ALL ON public.retrieval_feedback_events,public.retrieval_feedback FROM PUBLIC,rag_admin;
GRANT SELECT ON public.retrieval_feedback_events,public.retrieval_feedback TO rag_reader;
GRANT SELECT,INSERT ON public.retrieval_feedback_events,public.retrieval_feedback TO rag_writer;
GRANT UPDATE(kind,result_id,result_version,expected_id,expected_version,comment,state,revision,history,updated_at)
 ON public.retrieval_feedback TO rag_writer;
CREATE FUNCTION public.rag_feedback_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.id,NEW.event_id,NEW.namespace,NEW.actor,NEW.client,NEW.independence_id,NEW.domain,NEW.project_scope,
     NEW.idempotency_key,NEW.request_digest,NEW.created_at) IS DISTINCT FROM
    (OLD.id,OLD.event_id,OLD.namespace,OLD.actor,OLD.client,OLD.independence_id,OLD.domain,OLD.project_scope,
     OLD.idempotency_key,OLD.request_digest,OLD.created_at) THEN
  RAISE EXCEPTION 'feedback identity is immutable' USING ERRCODE='42501';
 END IF;
 IF NEW.revision<>OLD.revision+1 OR NEW.history->(OLD.revision-1) IS DISTINCT FROM OLD.history->(OLD.revision-1)
    OR NEW.history - (jsonb_array_length(NEW.history)-1) IS DISTINCT FROM OLD.history THEN
  RAISE EXCEPTION 'feedback history is append only' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER feedback_identity BEFORE UPDATE ON public.retrieval_feedback
 FOR EACH ROW EXECUTE FUNCTION public.rag_feedback_identity();
ALTER TABLE public.retrieval_feedback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.retrieval_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_feedback_events ON public.retrieval_feedback_events
 USING ((NOT public.rag_service_active() OR
  (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)))
  AND public.rag_service_document(domain,project_scope))
 WITH CHECK ((NOT public.rag_service_active() OR
  (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)))
  AND public.rag_service_document(domain,project_scope,true));
CREATE POLICY service_feedback ON public.retrieval_feedback
 USING ((NOT public.rag_service_active() OR
  (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)))
  AND public.rag_service_document(domain,project_scope))
 WITH CHECK ((NOT public.rag_service_active() OR
  (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)))
  AND public.rag_service_document(domain,project_scope,true)
  AND EXISTS(SELECT 1 FROM public.retrieval_feedback_events e WHERE e.id=event_id
   AND (e.namespace,e.actor,e.client,e.independence_id,e.domain,e.project_scope)=
       (retrieval_feedback.namespace,retrieval_feedback.actor,retrieval_feedback.client,
        retrieval_feedback.independence_id,retrieval_feedback.domain,retrieval_feedback.project_scope)));
CREATE POLICY service_feedback_update_guard ON public.retrieval_feedback AS RESTRICTIVE FOR UPDATE
 USING(public.rag_service_document(domain,project_scope,true));

-- Namespace accounting is independent of live domain/project visibility.
-- Otherwise revoking a scope would hide its retained rows from quota checks.
CREATE TABLE public.retrieval_feedback_usage (
 namespace text PRIMARY KEY, actor text NOT NULL,
 events integer NOT NULL DEFAULT 0 CHECK(events BETWEEN 0 AND 1024),
 signals integer NOT NULL DEFAULT 0 CHECK(signals BETWEEN 0 AND 2048),
 bytes bigint NOT NULL DEFAULT 0 CHECK(bytes BETWEEN 0 AND 16777216),
 recent jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(recent)='array' AND jsonb_array_length(recent)<=120)
);
REVOKE ALL ON public.retrieval_feedback_usage FROM PUBLIC,rag_reader,rag_writer,rag_admin;
GRANT SELECT ON public.retrieval_feedback_usage TO rag_reader;
GRANT SELECT,INSERT ON public.retrieval_feedback_usage TO rag_writer;
GRANT UPDATE(events,signals,bytes,recent) ON public.retrieval_feedback_usage TO rag_writer;
ALTER TABLE public.retrieval_feedback_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_feedback_usage ON public.retrieval_feedback_usage
 USING(NOT public.rag_service_active() OR
   (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)))
 WITH CHECK(NOT public.rag_service_active() OR
   (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)
    AND jsonb_array_length(current_setting('rag_service.write_domains',true)::jsonb)>0
    AND jsonb_array_length(current_setting('rag_service.write_projects',true)::jsonb)>0));
CREATE POLICY service_feedback_usage_update_guard ON public.retrieval_feedback_usage AS RESTRICTIVE FOR UPDATE
 USING(NOT public.rag_service_active() OR
   (namespace=current_setting('rag_service.namespace',true) AND actor=current_setting('rag_service.actor',true)
    AND jsonb_array_length(current_setting('rag_service.write_domains',true)::jsonb)>0
    AND jsonb_array_length(current_setting('rag_service.write_projects',true)::jsonb)>0));
