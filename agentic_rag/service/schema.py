"""Fail closed before service access when the installed scope protection is absent."""
from __future__ import annotations

import psycopg


class ServiceSchemaError(PermissionError):
    def __init__(self):
        super().__init__('incompatible_service_schema')


SCOPED_TABLES = (
    'documents', 'domains', 'chunks', 'chunk_contexts', 'edges', 'pins',
    'fact_assertions', 'assertion_sources', 'claim_records', 'claim_evidence',
    'knowledge_sources', 'entity_identities', 'assertion_entities', 'entity_aliases',
    'continuation_checkpoints', 'mining_batches', 'mining_queue', 'audit_log',
    'project_profiles', 'thematic_summaries', 'service_streams', 'service_windows',
    'service_session_access', 'service_requests',
    'embedding_vectors', 'source_revisions', 'claim_revisions', 'source_history', 'claim_history',
    'synthesis_policies', 'synthesis_backfills', 'synthesis_runs', 'synthesis_processed', 'synthesis_patterns',
    'synthesis_dependencies', 'lifecycle_decisions', 'lifecycle_events', 'extraction_policy_bindings',
    'image_originals', 'image_derivations', 'retrieval_feedback_events', 'retrieval_feedback', 'retrieval_feedback_usage',
)
IMAGE_TABLES = ('image_originals', 'image_derivations')


def image_tables_valid(conn):
    """Migration036: retained bytes and derivation identities are insert-only."""
    return not conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_catalog.pg_roles r
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND r.rolname IN ('rag_reader','rag_writer')
          AND (pg_catalog.has_table_privilege(r.oid,c.oid,'UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR (r.rolname='rag_reader' AND pg_catalog.has_table_privilege(r.oid,c.oid,'INSERT')))) bad""",
        (list(IMAGE_TABLES),)).fetchone()['bad']


def uploader_column_valid(conn):
    """The migration023 field extension must remain a nullable, plain UUID."""
    return conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute a
        WHERE a.attrelid=pg_catalog.to_regclass('public.service_sessions')
          AND a.attname='uploader_id' AND NOT a.attisdropped
          AND a.atttypid='pg_catalog.uuid'::regtype AND NOT a.attnotnull
          AND NOT a.atthasdef AND a.attgenerated='' AND a.attidentity='') ok""").fetchone()['ok']


def origin_columns_valid(conn):
    rows=conn.execute("""SELECT c.relname,a.attname,
        (a.atttypid='pg_catalog.uuid'::regtype AND NOT a.attnotnull
         AND NOT a.atthasdef AND a.attgenerated='' AND a.attidentity='') ok
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND NOT a.attisdropped
        WHERE n.nspname='public' AND c.relname IN ('service_windows','service_requests')
        AND a.attname IN ('origin_request_id','origin_correlation_id')""").fetchall()
    triggers=conn.execute("""SELECT count(*) n FROM pg_catalog.pg_trigger t
        WHERE t.tgrelid IN ('public.service_windows'::regclass,'public.service_requests'::regclass)
        AND t.tgname='immutable_request_origin' AND t.tgenabled IN ('O','A')
        AND t.tgfoid='public.rag_immutable_request_origin()'::regprocedure""").fetchone()['n']
    return len(rows)==4 and all(r['ok'] for r in rows) and triggers==2


EVIDENCE_TRIGGERS = (
    ('knowledge_sources', 'source_revision', 'rag_source_revision_trigger()'),
    ('claim_records', 'claim_record_revision', 'rag_claim_revision_trigger()'),
    ('claim_evidence', 'claim_evidence_revision', 'rag_claim_revision_trigger()'),
    ('source_history', 'source_history_append_only', 'rag_history_append_only()'),
    ('claim_history', 'claim_history_append_only', 'rag_history_append_only()'),
)


def evidence_revisions_valid(conn):
    """Migration029 revisions/history: definer-written only, triggers enabled.

    A limited role able to write a revision could reset it and recreate an
    already inspected version (ABA); a disabled trigger would let a decision
    commit without advancing the version or recording its history.
    """
    tables = ['source_revisions', 'claim_revisions', 'source_history', 'claim_history']
    exposed = conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND (
          EXISTS(SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname IN ('rag_reader','rag_writer','rag_admin')
            AND pg_catalog.has_table_privilege(r.oid,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
          OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute att CROSS JOIN LATERAL pg_catalog.aclexplode(att.attacl) a
            WHERE att.attrelid=c.oid AND NOT att.attisdropped AND a.grantee<>c.relowner))) bad""", (tables,)).fetchone()['bad']
    if exposed:
        return False
    helper = conn.execute("""SELECT p.prosecdef
        AND p.proconfig @> ARRAY['search_path=pg_catalog, public, pg_temp']
        AND NOT pg_catalog.has_function_privilege('rag_reader',p.oid,'EXECUTE')
        AND pg_catalog.has_function_privilege('rag_writer',p.oid,'EXECUTE')
        AND NOT EXISTS(SELECT 1 FROM pg_catalog.aclexplode(p.proacl) a
                       WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS ok
        FROM pg_catalog.pg_proc p
        WHERE p.oid=pg_catalog.to_regprocedure('public.rag_lock_claim_source(uuid,text)')""").fetchone()
    if helper is None or not helper['ok']:
        return False
    for table, name, function in EVIDENCE_TRIGGERS:
        ok = conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_trigger t
            WHERE t.tgrelid=pg_catalog.to_regclass(%s) AND t.tgname=%s AND t.tgenabled IN ('O','A')
            AND t.tgfoid=pg_catalog.to_regprocedure(%s)) ok""", ('public.' + table, name, 'public.' + function)).fetchone()['ok']
        if not ok:
            return False
    return True


def owner_only_tables_valid(conn, tables):
    """No nonowner ACL, inherited owner path or effective limited-role rights."""
    control=conn.execute("""SELECT c.relname,
            (EXISTS(SELECT 1 FROM pg_catalog.pg_roles r
                WHERE r.rolname IN ('rag_reader','rag_writer','rag_admin')
                  AND pg_catalog.has_table_privilege(r.oid,c.oid,
                    'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
             OR EXISTS(SELECT 1 FROM pg_catalog.aclexplode(
                coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
                WHERE a.grantee<>c.relowner)
             OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute att
                CROSS JOIN LATERAL pg_catalog.aclexplode(att.attacl) a
                WHERE att.attrelid=c.oid AND NOT att.attisdropped
                  AND a.grantee<>c.relowner)
             OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r
                WHERE r.oid<>c.relowner AND NOT r.rolsuper
                  AND pg_catalog.pg_has_role(r.oid,c.relowner,'MEMBER'))) exposed
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind='r' AND c.relname=ANY(%s)""",
            (list(tables),)).fetchall()
    return len(control)==len(tables) and not any(row['exposed'] for row in control)


def validate_schema(conn):
    """Check startup and every fresh scoped connection; never auto-migrate here.

    Migration markers alone are insufficient: disabled RLS, missing policies or
    a privileged database role must also fail before a business query executes.
    """
    from ..db import SQL_DIR
    try:
        conn.execute("SELECT set_config('statement_timeout','15000',false)")
        installed={r['filename'] for r in conn.execute('SELECT filename FROM public.schema_migrations')}
        required={'021_service_scope.sql','022_service_state.sql'} | {p.name for p in SQL_DIR.glob('*.sql')}
        if not required <= installed or not uploader_column_valid(conn) or not origin_columns_valid(conn):
            raise ServiceSchemaError()
        # Owner-only means no arbitrary ACL grantee, including groups inherited
        # by another login. A non-superuser able to SET ROLE to the owner is also
        # an unexpected control-state authority. Known limited SQL principals
        # must have no effective rights, even through direct ownership or
        # accidental elevation. Separately configured owners/DBAs stay trusted.
        if not owner_only_tables_valid(conn, ['dashboard_changes','dashboard_setup','dashboard_presence',
                                               'request_traces','retrieval_feedback_approvals',
                                               'webhook_control','webhook_subscriptions','webhook_events','webhook_deliveries']):
            raise ServiceSchemaError()
        rows=conn.execute("""
            SELECT c.relname,c.relrowsecurity,
              (SELECT count(*) FROM pg_catalog.pg_policy p WHERE p.polrelid=c.oid AND starts_with(p.polname,'service_')) policies,
              (SELECT count(*) FROM pg_catalog.pg_policy p WHERE p.polrelid=c.oid AND p.polcmd='w' AND NOT p.polpermissive) update_guards
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s)
        """,(list(SCOPED_TABLES),)).fetchall()
        if {r['relname'] for r in rows} != set(SCOPED_TABLES) or any(not r['relrowsecurity'] or not r['policies'] for r in rows):
            raise ServiceSchemaError()
        # Derived/read-only tables have no write check; remaining mutable tables
        # must enforce the original row's authority in addition to WITH CHECK.
        read_only={'chunks','chunk_contexts','audit_log','service_session_access','embedding_vectors',
                   'source_revisions','claim_revisions','source_history','claim_history',
                   'synthesis_patterns','synthesis_dependencies','retrieval_feedback_events',*IMAGE_TABLES}
        if any(not r['update_guards'] for r in rows if r['relname'] not in read_only):
            raise ServiceSchemaError()
        roles=conn.execute("SELECT rolname,rolsuper,rolbypassrls FROM pg_catalog.pg_roles WHERE rolname IN ('rag_reader','rag_writer')").fetchall()
        if len(roles)!=2 or any(r['rolsuper'] or r['rolbypassrls'] for r in roles):
            raise ServiceSchemaError()
        # A reader/writer owning a table (including inherited ownership) bypasses RLS.
        elevated=conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s)
            AND (pg_catalog.pg_has_role('rag_reader',c.relowner,'USAGE')
              OR pg_catalog.pg_has_role('rag_writer',c.relowner,'USAGE'))) bad""",(list(SCOPED_TABLES),)).fetchone()['bad']
        if elevated:
            raise ServiceSchemaError()
        # Managed descriptors/selection may be read by the limited roles, but
        # only the audited gateway/owner may change them or derived vectors.
        managed=conn.execute("""SELECT c.relname,
            (EXISTS(SELECT 1 FROM pg_catalog.aclexplode(coalesce(c.relacl,
                pg_catalog.acldefault('r',c.relowner))) a
                WHERE a.grantee<>c.relowner AND (a.privilege_type<>'SELECT'
                    OR a.grantee NOT IN (SELECT oid FROM pg_catalog.pg_roles
                        WHERE rolname IN ('rag_reader','rag_writer','rag_admin'))))
             OR EXISTS(SELECT 1 FROM pg_catalog.pg_attribute att
                CROSS JOIN LATERAL pg_catalog.aclexplode(att.attacl) a
                WHERE att.attrelid=c.oid AND NOT att.attisdropped AND a.grantee<>c.relowner)
             OR EXISTS(SELECT 1 FROM pg_catalog.pg_roles r
                WHERE r.rolname IN ('rag_reader','rag_writer','rag_admin')
                  AND pg_catalog.has_table_privilege(r.oid,c.oid,
                    'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))) exposed
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s)""",
            (['embedding_generations','embedding_selection','embedding_vectors'],)).fetchall()
        if len(managed)!=3 or any(r['exposed'] for r in managed):raise ServiceSchemaError()
        from ..webhooks import schema_valid as webhooks_valid
        if not webhooks_valid(conn):raise ServiceSchemaError()
        if not evidence_revisions_valid(conn) or not image_tables_valid(conn) or not feedback_tables_valid(conn):raise ServiceSchemaError()
        audit=conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_trigger t
            WHERE t.tgrelid='public.audit_log'::regclass AND t.tgname='service_audit_actor'
            AND t.tgenabled IN ('O','A') AND t.tgfoid='public.rag_service_audit_actor()'::regprocedure) ok""").fetchone()['ok']
        if not audit:raise ServiceSchemaError()
    except psycopg.Error:
        raise ServiceSchemaError() from None


def feedback_tables_valid(conn):
    """037 identity, append-only events and column-limited signal mutation."""
    if conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_roles r CROSS JOIN pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND r.rolname IN ('rag_reader','rag_writer','rag_admin')
        AND c.relname IN ('retrieval_feedback_events','retrieval_feedback','retrieval_feedback_usage') AND
        (has_table_privilege(r.oid,c.oid,'UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        OR (r.rolname<>'rag_writer' AND has_table_privilege(r.oid,c.oid,'INSERT')))) bad""").fetchone()['bad']:
        return False
    if conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_attribute a
        WHERE a.attrelid='public.retrieval_feedback'::regclass
          AND a.attname IN ('id','event_id','namespace','actor','client','independence_id','domain','project_scope',
                           'idempotency_key','request_digest','created_at')
          AND has_column_privilege('rag_writer',a.attrelid,a.attname,'UPDATE')) bad""").fetchone()['bad']:
        return False
    if conn.execute("""SELECT has_column_privilege('rag_writer','public.retrieval_feedback_usage','namespace','UPDATE')
        OR has_column_privilege('rag_writer','public.retrieval_feedback_usage','actor','UPDATE') bad""").fetchone()['bad']:
        return False
    # Column grants do not appear in has_table_privilege. Reject accidental
    # reader/admin mutation and event mutation even through inherited grants.
    if conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_attribute a
        JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_roles r WHERE n.nspname='public' AND NOT a.attisdropped AND a.attnum>0
        AND c.relname IN ('retrieval_feedback_events','retrieval_feedback','retrieval_feedback_usage')
        AND r.rolname IN ('rag_reader','rag_writer','rag_admin') AND (
          (has_column_privilege(r.oid,c.oid,a.attnum,'UPDATE') AND
            (r.rolname<>'rag_writer' OR c.relname='retrieval_feedback_events'))
          OR (r.rolname<>'rag_writer' AND has_column_privilege(r.oid,c.oid,a.attnum,'INSERT')))) bad""").fetchone()['bad']:
        return False
    return conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='public.retrieval_feedback'::regclass
        AND tgname='feedback_identity' AND tgenabled IN ('O','A')
        AND tgfoid='public.rag_feedback_identity()'::regprocedure) ok""").fetchone()['ok']
