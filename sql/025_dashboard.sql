-- Dashboard control state is owner-only, never knowledge or browser SQL authority.
CREATE TABLE dashboard_changes (
    operation_id uuid PRIMARY KEY,
    policy_id text NOT NULL CHECK(length(policy_id)=64),
    actor text NOT NULL CHECK(length(actor)<=256),
    kind text NOT NULL CHECK(kind IN ('bootstrap','user','machine','rotate','revoke')),
    subject text NOT NULL CHECK(length(subject)<=80),
    old_revision text NOT NULL CHECK(length(old_revision)=64),
    new_revision text NOT NULL CHECK(length(new_revision)=64),
    state text NOT NULL CHECK(state IN ('prepared','applied','not_applied')),
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX dashboard_changes_policy ON dashboard_changes(policy_id,created_at);
CREATE TABLE dashboard_setup (
    policy_id text PRIMARY KEY CHECK(length(policy_id)=64),
    mode text NOT NULL CHECK(mode IN ('new-local','existing-local','central','client')),
    checks jsonb NOT NULL DEFAULT '{}' CHECK(octet_length(checks::text)<=8192),
    completed boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE dashboard_presence (
    policy_id text NOT NULL CHECK(length(policy_id)=64),
    principal_id text NOT NULL CHECK(length(principal_id)<=164),
    seen_at timestamptz NOT NULL DEFAULT now(),
    version text NOT NULL DEFAULT '' CHECK(length(version)<=40),
    capabilities text NOT NULL DEFAULT '' CHECK(length(capabilities)<=256),
    PRIMARY KEY(policy_id,principal_id)
);
REVOKE ALL ON dashboard_changes,dashboard_setup,dashboard_presence FROM PUBLIC,rag_reader,rag_writer,rag_admin;

-- Custom ALTER DEFAULT PRIVILEGES must not leak into the new control state.
-- Only these new relations are changed; retain every historical table ACL.
DO $dashboard_acl$
DECLARE grant_row record;
BEGIN
    FOR grant_row IN
        SELECT c.oid::regclass relation, a.grantee, r.rolname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee
        WHERE n.nspname='public'
          AND c.relname IN ('dashboard_changes','dashboard_setup','dashboard_presence')
          AND a.grantee<>c.relowner
    LOOP
        EXECUTE format('REVOKE ALL ON TABLE %s FROM %s CASCADE',
            grant_row.relation,
            CASE WHEN grant_row.grantee=0 THEN 'PUBLIC' ELSE quote_ident(grant_row.rolname) END);
    END LOOP;
END
$dashboard_acl$;
