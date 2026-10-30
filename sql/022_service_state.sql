-- Transport/identity state is additive; canonical source evidence stays untouched.
CREATE TABLE service_sessions (
 token_hash text PRIMARY KEY,
 user_id text NOT NULL,
 password_revision text NOT NULL,
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON service_sessions FROM rag_reader,rag_writer;
GRANT ALL ON service_sessions TO rag_admin;
CREATE TABLE service_streams (
 session_id text PRIMARY KEY,
 owner_namespace text NOT NULL,
 project text NOT NULL,
 last_cursor text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(session_id,owner_namespace,project)
);
CREATE TABLE service_windows (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 owner_namespace text NOT NULL,
 session_id text NOT NULL,
 input_cursor text NOT NULL,
 output_cursor text NOT NULL,
 content_hash text NOT NULL,
 payload jsonb NOT NULL,
 project text NOT NULL,
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','applied','cancelled','blocked','error')),
 queue_id bigint REFERENCES mining_queue(id),
 result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 applied_at timestamptz,
 UNIQUE(session_id,input_cursor),
 UNIQUE(session_id,output_cursor),
 FOREIGN KEY(session_id,owner_namespace,project) REFERENCES service_streams(session_id,owner_namespace,project),
 CHECK(octet_length(payload::text)<=1048576)
);
GRANT SELECT ON service_streams,service_windows TO rag_reader;
GRANT SELECT,INSERT,UPDATE ON service_streams,service_windows TO rag_writer;
GRANT ALL ON service_streams,service_windows TO rag_admin;
ALTER TABLE service_streams ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_stream_scope ON service_streams
 USING(NOT rag_service_active() OR (owner_namespace=current_setting('rag_service.namespace',true) AND rag_service_allows(project,'projects')))
 WITH CHECK(NOT rag_service_active() OR (owner_namespace=current_setting('rag_service.namespace',true) AND rag_service_allows(project,'projects',true)));
ALTER TABLE service_windows ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_window_scope ON service_windows
 USING(NOT rag_service_active() OR (owner_namespace=current_setting('rag_service.namespace',true) AND rag_service_allows(project,'projects')))
 WITH CHECK(NOT rag_service_active() OR (owner_namespace=current_setting('rag_service.namespace',true) AND rag_service_allows(project,'projects',true)));
ALTER TABLE mining_queue DROP CONSTRAINT mining_queue_kind_check;
ALTER TABLE mining_queue ADD CONSTRAINT mining_queue_kind_check
 CHECK(kind IN ('mine','embed','curate','backup','checkpoint_enrich','profile_refresh','source_window'));

CREATE POLICY service_stream_old_write ON service_streams AS RESTRICTIVE FOR UPDATE
 USING(NOT rag_service_active() OR (owner_namespace=current_setting('rag_service.namespace',true) AND rag_service_allows(project,'projects',true)));
CREATE POLICY service_window_old_write ON service_windows AS RESTRICTIVE FOR UPDATE
 USING(NOT rag_service_active() OR (owner_namespace=current_setting('rag_service.namespace',true) AND rag_service_allows(project,'projects',true)));

-- Immutable publication team, separate from each uploader's stream/authority.
-- Retained team history survives the original author's departure. Current
-- membership is supplied only by the authenticated server policy.
CREATE TABLE service_session_access (
 session_id text PRIMARY KEY,
 owner_namespace text NOT NULL,
 project text NOT NULL,
 teams jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(teams)='array' AND jsonb_array_length(teams)<=16),
 actor text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX service_session_access_created ON service_session_access(created_at DESC,session_id);
CREATE INDEX service_session_access_teams ON service_session_access USING gin(teams);
GRANT SELECT ON service_session_access TO rag_reader;
GRANT SELECT,INSERT ON service_session_access TO rag_writer;
GRANT ALL ON service_session_access TO rag_admin;
ALTER TABLE service_session_access ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_session_access_scope ON service_session_access
 USING(NOT rag_service_active() OR
  (rag_service_allows(project,'projects') AND
   (owner_namespace=current_setting('rag_service.namespace',true) OR
    teams ?| ARRAY(SELECT jsonb_array_elements_text(current_setting('rag_service.read_teams',true)::jsonb)))))
 WITH CHECK(NOT rag_service_active() OR
  (owner_namespace=current_setting('rag_service.namespace',true)
   AND starts_with(session_id,'svc1:' || current_setting('rag_service.namespace',true) || ':')
   AND actor=current_setting('rag_service.actor',true)
   AND teams <@ current_setting('rag_service.write_teams',true)::jsonb
   AND rag_service_allows(project,'projects',true)));
-- SELECT-only additions cannot grant job cancellation, reauthorization or
-- checkpoint mutation: the original-row restrictive UPDATE guards remain.
CREATE POLICY service_stream_team_read ON service_streams FOR SELECT
 USING(EXISTS(SELECT 1 FROM public.service_session_access a
              WHERE a.session_id=service_streams.session_id AND a.project=service_streams.project));
CREATE POLICY service_window_team_read ON service_windows FOR SELECT
 USING(EXISTS(SELECT 1 FROM public.service_session_access a
              WHERE a.session_id=service_windows.session_id AND a.project=service_windows.project));
CREATE POLICY service_checkpoint_team_read ON continuation_checkpoints FOR SELECT
 USING(EXISTS(SELECT 1 FROM public.service_session_access a
              WHERE a.session_id=continuation_checkpoints.session_id
               AND a.project=COALESCE(continuation_checkpoints.project_root,'unknown')));
