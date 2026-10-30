-- Metadata is a separate, owner-only operational plane. No captured bodies/errors.
CREATE TABLE request_traces (
    request_id uuid PRIMARY KEY,
    policy_id text NOT NULL CHECK(length(policy_id)=64),
    started_at timestamptz NOT NULL,
    correlation_id uuid,
    principal text CHECK(length(principal)<=80),
    client text CHECK(length(client)<=80),
    owner_namespace text CHECK(length(owner_namespace)=64),
    read_domains text[] NOT NULL DEFAULT '{}',
    read_projects text[] NOT NULL DEFAULT '{}',
    operation text NOT NULL CHECK(length(operation)<=96 AND operation ~ '^[a-z0-9_.]+$'),
    status integer NOT NULL CHECK(status BETWEEN 100 AND 599),
    outcome text NOT NULL CHECK(outcome IN ('completed','accepted','failed','disconnected')),
    error_class text CHECK(length(error_class)<=64 AND error_class ~ '^[a-z0-9_]+$'),
    duration_ms double precision NOT NULL CHECK(duration_ms>=0 AND duration_ms<1e12),
    response_bytes bigint NOT NULL CHECK(response_bytes>=0),
    server_version text NOT NULL CHECK(length(server_version)<=40),
    client_version text NOT NULL DEFAULT '' CHECK(length(client_version)<=40),
    logical_bytes integer NOT NULL CHECK(logical_bytes BETWEEN 500 AND 20000),
    job_id uuid,
    job_kind text CHECK(job_kind IN ('source','foreground')),
    CHECK(cardinality(read_domains)<=64 AND cardinality(read_projects)<=64),
    CHECK(octet_length(read_domains::text)+octet_length(read_projects::text)<=16384)
);
CREATE INDEX request_traces_page ON request_traces(policy_id,started_at DESC,request_id DESC);
CREATE INDEX request_traces_job ON request_traces(policy_id,job_id) WHERE job_id IS NOT NULL;
CREATE INDEX request_traces_correlation ON request_traces(policy_id,correlation_id) WHERE correlation_id IS NOT NULL;
REVOKE ALL ON request_traces FROM PUBLIC,rag_reader,rag_writer,rag_admin;
DO $trace_acl$
DECLARE grant_row record;
BEGIN
    FOR grant_row IN
        SELECT a.grantee,r.rolname FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee
        WHERE n.nspname='public' AND c.relname='request_traces' AND a.grantee<>c.relowner
    LOOP
        EXECUTE format('REVOKE ALL ON TABLE public.request_traces FROM %s CASCADE',
            CASE WHEN grant_row.grantee=0 THEN 'PUBLIC' ELSE quote_ident(grant_row.rolname) END);
    END LOOP;
END
$trace_acl$;
-- Additive nullable fields preserve all025 originals. No retention foreign key.
ALTER TABLE service_windows ADD COLUMN origin_request_id uuid, ADD COLUMN origin_correlation_id uuid;
ALTER TABLE service_requests ADD COLUMN origin_request_id uuid, ADD COLUMN origin_correlation_id uuid;
CREATE FUNCTION rag_immutable_request_origin() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.origin_request_id IS DISTINCT FROM NEW.origin_request_id
       OR OLD.origin_correlation_id IS DISTINCT FROM NEW.origin_correlation_id THEN
        RAISE EXCEPTION 'immutable request origin' USING ERRCODE='42501';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION rag_immutable_request_origin() FROM PUBLIC,rag_reader,rag_writer,rag_admin;
CREATE TRIGGER immutable_request_origin BEFORE UPDATE ON service_windows FOR EACH ROW EXECUTE FUNCTION rag_immutable_request_origin();
CREATE TRIGGER immutable_request_origin BEFORE UPDATE ON service_requests FOR EACH ROW EXECUTE FUNCTION rag_immutable_request_origin();
