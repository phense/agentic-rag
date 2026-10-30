-- Durable, finite foreground requests are distinct from source extraction jobs.
CREATE TABLE service_requests (
 id uuid PRIMARY KEY,
 owner_namespace text NOT NULL,
 team text NOT NULL,
 envelope_hash text NOT NULL,
 authority jsonb NOT NULL,
 permission_hash text NOT NULL,
 tool text NOT NULL,
 arguments jsonb,
 result jsonb,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','completed','failed','cancelled','expired')),
 code text,
 lease uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 finished_at timestamptz,
 dispatched_at timestamptz,
 retry_at timestamptz NOT NULL DEFAULT now(),
 CHECK(octet_length(arguments::text)<=65536),
 CHECK(octet_length(result::text)<=131072)
);
CREATE INDEX service_requests_dispatch ON service_requests(state,created_at);
CREATE INDEX service_requests_owner ON service_requests(owner_namespace,created_at);
GRANT SELECT ON service_requests TO rag_reader;
GRANT SELECT,UPDATE ON service_requests TO rag_writer;
GRANT ALL ON service_requests TO rag_admin;
ALTER TABLE service_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_request_scope ON service_requests
 USING(NOT rag_service_active() OR owner_namespace=current_setting('rag_service.namespace',true))
 WITH CHECK(NOT rag_service_active() OR owner_namespace=current_setting('rag_service.namespace',true));
CREATE POLICY service_request_old_write ON service_requests AS RESTRICTIVE FOR UPDATE
 USING(NOT rag_service_active() OR owner_namespace=current_setting('rag_service.namespace',true));
CREATE TABLE service_foreground (
 id uuid PRIMARY KEY,
 expires_at timestamptz NOT NULL
);
REVOKE ALL ON service_foreground FROM PUBLIC,rag_reader,rag_writer;
GRANT ALL ON service_foreground TO rag_admin;
