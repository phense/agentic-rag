"""Operator-only, data-preserving inventory and explicit local/remote upgrades.

No endpoint exposes these operations. Source evidence is copied intact; several
independent databases are never silently concatenated or overwritten.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import uuid
import re
import subprocess
import tempfile

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .. import backup, db, query_cache
from ..benchmark.database import isolated_database
from .context import CURRENT
from .fence import OWNER_LOCK, EXECUTION_LOCK

SUPPORTED_VERSIONS=frozenset('0.6.'+str(n) for n in range(18))
EXCLUDED={'benchmark_ownership'}
ROLES=('rag_reader','rag_writer','rag_admin')


def _operator(cfg,version=None):
    if CURRENT.get() is not None or cfg.service_mode=='client':raise ValueError('operator_local_configuration_required')
    if version is not None and version not in SUPPORTED_VERSIONS:raise ValueError('unsupported_source_version')
    if cfg.embed_dim!=1024:raise ValueError('unsupported_embedding_dimensions')


def private_json(path,data):
    """Create a private artifact exactly once; never replace a prior proof."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(data,stream,sort_keys=True,indent=2,default=str);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return path


def _tables(conn):
    return [r['tablename'] for r in conn.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename") if r['tablename'] not in EXCLUDED]


def _hash_table(conn,table,*,omit_columns=()):
    columns=conn.execute('''SELECT a.attname FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
        WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY array_position(i.indkey,a.attnum)''',('public.'+table,)).fetchall()
    order=sql.SQL(',').join(sql.Identifier(r['attname']) for r in columns) if columns else sql.SQL('to_jsonb(t)::text COLLATE "C"')
    digest=sha256();count=0
    # Server cursor bounds Python RAM even for a populated multi-GiB store.
    with conn.cursor(name='rag_hash_'+uuid.uuid4().hex) as cursor:
        value=sql.SQL('to_jsonb(t)') if not omit_columns else sql.SQL('to_jsonb(t)-{}::text[]').format(sql.Literal(list(omit_columns)))
        cursor.execute(sql.SQL('SELECT ({})::text value FROM public.{} t ORDER BY {}').format(value,sql.Identifier(table),order))
        while rows:=cursor.fetchmany(256):
            for row in rows:
                encoded=row['value'].encode();digest.update(len(encoded).to_bytes(8,'big'));digest.update(encoded);count+=1
    return {'rows':count,'sha256':digest.hexdigest()}


def _grants(conn,tables):
    rows=conn.execute('''SELECT c.relname object,c.relkind,
          CASE WHEN a.grantor=c.relowner THEN '__OWNER__' ELSE pg_get_userbyid(a.grantor) END grantor,
          CASE WHEN a.grantee=c.relowner THEN '__OWNER__' WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END grantee,
          a.privilege_type,a.is_grantable
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault(CASE WHEN c.relkind='S' THEN 'S'::"char" ELSE 'r'::"char" END,c.relowner))) a
        WHERE n.nspname='public' AND (c.relname=ANY(%s) OR c.relkind='S')
        ORDER BY object,grantor,grantee,privilege_type,is_grantable''',(tables,)).fetchall()
    return [dict(r) for r in rows]


def _identity(conn):
    identity=dict(conn.execute('''SELECT d.oid database_oid,current_database() database,
        current_user owner,inet_server_addr()::text address,current_setting('port') port,
        current_setting('server_version_num') server_version,d.datcollate collate,d.datctype ctype,
        (SELECT extversion FROM pg_extension WHERE extname='vector') vector_version
        FROM pg_database d WHERE datname=current_database()''').fetchone())
    allowed=conn.execute("SELECT has_function_privilege(current_user,'pg_catalog.pg_control_system()','EXECUTE') ok").fetchone()['ok']
    identity['system_identifier']=str(conn.execute('SELECT system_identifier FROM pg_catalog.pg_control_system()').fetchone()['system_identifier']) if allowed else None
    return identity


def _sequences(conn):
    result={}
    for row in conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='S' ORDER BY c.relname"):
        result[row['relname']]=dict(conn.execute(sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(row['relname']))).fetchone())
    return result


def _ownership(conn):
    return {r['relname']:r['owner'] for r in conn.execute("SELECT c.relname,pg_get_userbyid(c.relowner) owner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','S') ORDER BY c.relname") if r['relname'] not in EXCLUDED}


def _snapshot(conn):
    conn.execute("SET LOCAL timezone='UTC'")
    tables=_tables(conn)
    return {'tables':{table:_hash_table(conn,table) for table in tables},'grants':_grants(conn,tables),'sequences':_sequences(conn),'owners':_ownership(conn)}


def _inventory(conn,cfg,version,identities=False):
    installed=[r['filename'] for r in conn.execute('SELECT filename FROM public.schema_migrations ORDER BY filename')]
    expected=[p.name for p in sorted(db.SQL_DIR.glob('*.sql'))]
    if not 18<=len(installed)<=len(expected) or installed!=expected[:len(installed)]:raise ValueError('unsupported_source_schema')
    identity=_identity(conn)
    if int(identity['server_version'])//10000!=17:raise ValueError('unsupported_postgresql_version')
    report={'format':1,'source_version':version,'supported':True,'identity':identity,'migrations':installed,
            'models':{'embedding':cfg.embed_model,'dimension':cfg.embed_dim,'digest':query_cache.model_digest(cfg),'provider':cfg.llm_provider,'model':cfg.llm_model},**_snapshot(conn)}
    report['migration_rows']=[{'filename':r['filename'],'applied_at':str(r['applied_at'])} for r in conn.execute('SELECT * FROM public.schema_migrations ORDER BY filename')]
    report['queue']=[dict(r) for r in conn.execute("SELECT kind,status,count(*) count FROM public.mining_queue GROUP BY kind,status ORDER BY kind,status")]
    paths=conn.execute("SELECT id,kind,session_id,transcript_path FROM public.mining_queue WHERE status IN ('pending','processing','error') AND transcript_path IS NOT NULL AND transcript_path<>'' ORDER BY id LIMIT 51").fetchall()
    report['unresolved_paths']=[dict(r) for r in paths[:50]]
    report['paths_truncated']=len(paths)>50
    report['configuration']={'mode':cfg.service_mode,'database_name':cfg.db_name,'embedding_compatible':cfg.embed_dim==1024}
    report['roles']=[dict(r) for r in conn.execute("SELECT rolname,rolsuper,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname IN (current_user,'rag_reader','rag_writer','rag_admin') ORDER BY rolname")]
    report['memberships']=[dict(r) for r in conn.execute("SELECT member.rolname member,parent.rolname granted_role,m.admin_option FROM pg_auth_members m JOIN pg_roles member ON member.oid=m.member JOIN pg_roles parent ON parent.oid=m.roleid WHERE member.rolname IN (current_user,'rag_reader','rag_writer','rag_admin') ORDER BY member,granted_role")]
    report['configuration'].update({'database_host':cfg.db_host,'provider':cfg.llm_provider,'provider_model':cfg.llm_model,'provider_timeout':cfg.llm_timeout,'context_max_chars':cfg.context_max_chars,'spool_dir':str(cfg.service_spool_dir),'auth_file_configured':cfg.service_auth_file is not None})
    if identities:
        keys=[]
        for table,column in [('documents','id'),('documents','slug'),('knowledge_sources','source_key'),('entity_aliases','alias_key')]:
            exists=conn.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=\'public\' AND table_name=%s AND column_name=%s',(table,column)).fetchone()
            if not exists:continue
            for row in conn.execute(sql.SQL('SELECT {}::text key FROM public.{} ORDER BY {} LIMIT 100001').format(sql.Identifier(column),sql.Identifier(table),sql.Identifier(column))):
                if len(keys)>=100000:raise ValueError('inventory_identity_limit')
                keys.append({'kind':table+'.'+column,'key':row['key']})
        report['identities']=keys
    return report


def inventory(cfg,source_version,*,identities=False):
    _operator(cfg,source_version)
    with db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return _inventory(conn,cfg,source_version,identities)


def preflight(cfg,source_version,*,mode='local'):
    if mode not in {'local','remote'}:raise ValueError('invalid_upgrade_mode')
    data=inventory(cfg,source_version)
    blockers=['unresolved_transcript_paths'] if mode=='remote' and data['unresolved_paths'] else []
    if mode=='remote' and not data['models']['digest']:blockers.append('embedding_identity_unverified')
    return {'mode':mode,'ready':not blockers,'blockers':blockers,'inventory':data,'source_untouched':True}


def collision_report(inventories):
    if not 1<=len(inventories)<=16:raise ValueError('inventory_count_limit')
    seen={};collisions=[];count=0
    for source,report in enumerate(inventories):
        if report.get('format')!=1 or not report.get('supported') or 'identities' not in report:raise ValueError('complete_identity_inventory_required')
        for item in report['identities']:
            count+=1
            if count>100000:raise ValueError('combined_identity_limit')
            key=(item['kind'],item['key'])
            if key in seen:collisions.append({'kind':key[0],'key':key[1],'sources':[seen[key],source]})
            else:seen[key]=source
    return {'ready':len(inventories)==1 and not collisions,'collisions':collisions,
            'requires_explicit_mapping':len(inventories)>1,'sources_untouched':True,
            'automatic_multi_store_import':False}


def _file_digest(path):
    digest=sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1048576):digest.update(block)
    return digest.hexdigest()


def check_dump(path,manifest):
    if manifest.get('format')!=1 or _file_digest(path)!=manifest.get('dump_sha256'):raise ValueError('dump_digest_mismatch')


def _verify(conn,manifest,*,preserved=False,label='source_drift'):
    actual=_snapshot(conn);expected=manifest['tables']
    installed={r['filename']:str(r['applied_at']) for r in conn.execute('SELECT * FROM public.schema_migrations')}
    from .schema import uploader_column_valid,origin_columns_valid
    if '026_request_tracing.sql' in installed and not origin_columns_valid(conn):
        raise ValueError(label+'_origin_schema')
    if '023_claim_lookup.sql' in installed and not uploader_column_valid(conn):
        raise ValueError(label+'_uploader_schema')
    if preserved:
        if any(installed.get(r['filename'])!=r['applied_at'] for r in manifest.get('migration_rows',[])):raise ValueError(label+'_migration_history')
        names=[p.name for p in db.SQL_DIR.glob('*.sql')]
        if set(installed)-set(names):raise ValueError('unsupported_source_schema')
        # The sole existing-table shape change in023 is a nullable UUID profile
        # on original022 sessions. Compare every original field and row, omitting
        # ONLY that newly added all-NULL field. Never hide registered profiles,
        # changes to original fields, missing rows, or arbitrary schema changes.
        original=manifest.get('migrations',[])
        if ('022_service_state.sql' in original and '023_claim_lookup.sql' not in original
                and 'service_sessions' in expected
                and actual['tables']['service_sessions']!=expected['service_sessions']):
            assigned=conn.execute('SELECT EXISTS(SELECT 1 FROM public.service_sessions WHERE uploader_id IS NOT NULL) present').fetchone()['present']
            if not assigned:
                legacy=_hash_table(conn,'service_sessions',omit_columns=('uploader_id',))
                if legacy==expected['service_sessions']:
                    actual['tables']['service_sessions']=legacy

    #026 adds nullable durable origins only. An upgrade must preserve every
    # original field, and may omit the new columns solely while all are NULL.
    if preserved and '026_request_tracing.sql' not in manifest.get('migrations',[]):
        for table in ('service_windows','service_requests'):
            if table in expected and '026_request_tracing.sql' in installed:
                assigned=conn.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM {} WHERE origin_request_id IS NOT NULL OR origin_correlation_id IS NOT NULL) present').format(sql.Identifier(table))).fetchone()['present']
                if not assigned:
                    legacy=_hash_table(conn,table,omit_columns=('origin_request_id','origin_correlation_id'))
                    if legacy==expected[table]:actual['tables'][table]=legacy

    if (not preserved and set(actual['tables'])!=set(expected)) or any(actual['tables'].get(t)!=v for t,v in expected.items() if not(preserved and t=='schema_migrations')):
        raise ValueError(label)
    # Additive migrations may create new table/sequence ACLs; existing grants
    # must match, including custom grantees. Owner mapping is explicit/normalized.
    names=set(expected)
    relevant=lambda rows:[r for r in rows if r['object'] in names or r['relkind']=='S']
    if relevant(actual['grants'])!=relevant(manifest['grants']):raise ValueError(label+'_grants')
    current_owner=conn.execute('SELECT current_user owner').fetchone()['owner']
    old_owner=manifest['identity']['owner']
    for name,owner in manifest.get('owners',{}).items():
        expected_owner=current_owner if owner==old_owner else owner
        if actual['owners'].get(name)!=expected_owner:raise ValueError(label+'_ownership')
    for name,expected_sequence in manifest.get('sequences',{}).items():
        sequence=actual['sequences'].get(name)
        if sequence is None or sequence['last_value']<expected_sequence['last_value'] or (sequence['last_value']==expected_sequence['last_value'] and expected_sequence['is_called'] and not sequence['is_called']):raise ValueError(label+'_sequence')
    return {'unchanged':True,'original_rows_unchanged':True}


def verify_preserved(cfg,manifest):
    _operator(cfg)
    with db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return _verify(conn,manifest,preserved=True)


def _restore_verification(cfg,target,path,manifest,*,prepared_template=False):
    command=[backup._pg_bin('pg_restore',cfg),'--single-transaction','--exit-on-error','-d',db.dsn(target)]
    if not prepared_template:
        backup._run_pg([*command,str(path)])
        return
    # A DBA installs vector in the explicit empty template. Never grant the
    # runtime owner superuser, recreate the extension, or mutate its comments.
    with db.connect(target) as conn:
        extension=conn.execute("SELECT extversion,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE extname='vector'").fetchone()
        if not extension or extension['extversion']!=manifest['identity']['vector_version'] or extension['nspname']!='public':
            raise ValueError('verification_template_extension_mismatch')
    with tempfile.TemporaryDirectory(prefix='.restore-list-',dir=Path(path).parent) as directory:
        listing=Path(directory)/'restore.list'
        with listing.open('wb') as output:
            subprocess.run([backup._pg_bin('pg_restore',cfg),'--list',str(path)],stdout=output,stderr=subprocess.PIPE,check=True)
        # Match just vector's extension/COMMENT TOC records, never application
        # schemas, privileges, data, comments or extension-dependent objects.
        lines=listing.read_text().splitlines()
        pattern=r'^\d+; \d+ \d+ (?:EXTENSION - vector|COMMENT - EXTENSION vector)\s*$'
        listing.write_text('\n'.join(line for line in lines if not re.fullmatch(pattern,line))+'\n')
        backup._run_pg([*command,'--use-list',str(listing),str(path)])


def verified_backup(cfg,source_version,path,*,verification_template=None):
    _operator(cfg,source_version);path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with db.connect(cfg) as sizing:
        size=sizing.execute('SELECT pg_database_size(current_database()) bytes').fetchone()['bytes']
        backup.ensure_storage(cfg,path.parent,incoming=size*3)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    with db.connect(cfg) as source:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        manifest=_inventory(source,cfg,source_version)
        exported=source.execute('SELECT pg_export_snapshot() snapshot').fetchone()['snapshot']
        backup._run_pg([backup._pg_bin('pg_dump',cfg),'-Fc','--snapshot='+exported,'--exclude-table=public.benchmark_ownership','-f',str(path),'-d',db.dsn(cfg)])
        manifest['dump_sha256']=_file_digest(path)
        with isolated_database(cfg,initialize=False,template=verification_template) as target:
            _restore_verification(cfg,target,path,manifest,prepared_template=verification_template is not None)
            with db.connect(target) as restored:
                restored.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                _verify(restored,manifest,label='restore_mismatch')
    manifest['restore_verified']=True
    private_json(path.with_suffix(path.suffix+'.manifest.json'),manifest)
    return {'restore_verified':True,'manifest':manifest,'dump':str(path)}


@contextmanager
def source_fence(cfg,*,writers_stopped=False):
    _operator(cfg)
    if not writers_stopped:raise ValueError('writers_stopped_confirmation_required')
    with psycopg.connect(db.dsn(cfg),autocommit=True,row_factory=dict_row) as control:
        control.execute('SET default_transaction_read_only=off')
        identity=_identity(control)
        locks=[];prior=None;changed=False
        try:
            for key in (OWNER_LOCK,EXECUTION_LOCK):
                if not control.execute('SELECT pg_try_advisory_lock(%s) ok',(key,)).fetchone()['ok']:raise ValueError('worker_still_active')
                locks.append(key)
            active=control.execute("SELECT count(*) n FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'").fetchone()['n']
            if active:raise ValueError('database_clients_still_active')
            # Role settings take precedence over database defaults. Refuse a
            # persisted override that would let a returning legacy login write.
            overrides=control.execute("""SELECT 1 FROM pg_db_role_setting s,
                LATERAL unnest(s.setconfig) setting WHERE s.setrole<>0
                AND s.setdatabase IN (0,(SELECT oid FROM pg_database WHERE datname=current_database()))
                AND setting IN ('default_transaction_read_only=off','default_transaction_read_only=false','default_transaction_read_only=0') LIMIT 1""").fetchone()
            if overrides:raise ValueError('role_read_only_override')
            row=control.execute("SELECT unnest(setconfig) setting FROM pg_db_role_setting WHERE setdatabase=(SELECT oid FROM pg_database WHERE datname=current_database()) AND setrole=0").fetchall()
            prior=next((r['setting'].partition('=')[2] for r in row if r['setting'].startswith('default_transaction_read_only=')),None)
            control.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only='on'").format(sql.Identifier(cfg.db_name)));changed=True
            fence={'identity':identity,'prior_read_only':prior,'source_read_only':True,'retain':False}
            yield fence
        finally:
            if changed and not locals().get('fence',{}).get('retain',False):
                statement=sql.SQL('ALTER DATABASE {} RESET default_transaction_read_only') if prior is None else sql.SQL('ALTER DATABASE {} SET default_transaction_read_only={}').format(sql.Identifier(cfg.db_name),sql.Literal(prior))
                control.execute(statement.format(sql.Identifier(cfg.db_name)) if prior is None else statement)
            for key in reversed(locks):control.execute('SELECT pg_advisory_unlock(%s)',(key,))


def _migrate_preserving(cfg,manifest):
    with db.connect(cfg) as conn:
        # Only this confirmed operator connection may write while legacy clients
        # see a read-only database. Migrations and preservation check commit once.
        conn.execute('SET default_transaction_read_only=off');conn.commit()
        applied=db.apply_migrations(conn,db.SQL_DIR,commit=False)
        _verify(conn,manifest,preserved=True)
        conn.commit()
        return applied


def local_upgrade(cfg,source_version,path,*,apply=False,writers_stopped=False,verification_template=None):
    plan=preflight(cfg,source_version,mode='local')
    if not apply:return {'mode':'local','applied':False,'plan':plan}
    with source_fence(cfg,writers_stopped=writers_stopped):
        proof=verified_backup(cfg,source_version,path,verification_template=verification_template)
        applied=_migrate_preserving(cfg,proof['manifest'])
    return {'mode':'local','applied':True,'migrations_applied':applied,'original_rows_unchanged':True,**proof}


def prepare_cutover(cfg,source_version,path,*,apply=False,writers_stopped=False,verification_template=None):
    plan=preflight(cfg,source_version,mode='remote')
    if not apply:return {'mode':'remote','applied':False,'plan':plan}
    if not plan['ready']:raise ValueError('unresolved_transcript_paths')
    with source_fence(cfg,writers_stopped=writers_stopped) as fence:
        proof=verified_backup(cfg,source_version,path,verification_template=verification_template)
        private_json(Path(path).with_suffix('.fence.json'),fence)
        fence['retain']=True
    return {'mode':'remote','applied':True,'source_remains_read_only':True,**proof}


def restore_target(cfg,path,manifest,*,apply=False,resume=False):
    _operator(cfg);check_dump(path,manifest)
    if not manifest.get('restore_verified'):raise ValueError('verified_backup_required')
    if cfg.embed_model!=manifest['models']['embedding'] or cfg.embed_dim!=manifest['models']['dimension']:raise ValueError('embedding_configuration_mismatch')
    if not apply:return {'mode':'remote-target','applied':False}
    digest=manifest['models'].get('digest')
    if not digest or query_cache.model_digest(cfg)!=digest:raise ValueError('embedding_identity_mismatch')
    if any(owner!=manifest['identity']['owner'] for owner in manifest.get('owners',{}).values()):raise ValueError('explicit_owner_mapping_required')
    with db.connect(cfg) as conn:
        current=_tables(conn)
        identity=_identity(conn)
        if identity['collate']!=manifest['identity']['collate'] or identity['ctype']!=manifest['identity']['ctype']:raise ValueError('target_collation_mismatch')
    if current:
        if not resume:raise ValueError('target_not_empty')
        with db.connect(cfg) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            _verify(conn,manifest,preserved=True,label='target_drift')
            allowed=set(manifest['tables'])|{'service_sessions','service_streams','service_windows','service_session_access','service_requests','service_foreground','dashboard_changes','dashboard_setup','dashboard_presence','request_traces','embedding_generations','embedding_selection','embedding_vectors','source_revisions','claim_revisions','source_history','claim_history','synthesis_policies','synthesis_backfills','synthesis_runs','synthesis_patterns','synthesis_dependencies'}
            if set(current)-allowed:raise ValueError('target_drift')
            for table in set(current)-set(manifest['tables']):
                if conn.execute(sql.SQL('SELECT 1 FROM public.{} LIMIT 1').format(sql.Identifier(table))).fetchone():raise ValueError('target_drift')
    else:
        backup._run_pg([backup._pg_bin('pg_restore',cfg),'--no-owner','--single-transaction','--exit-on-error','-d',db.dsn(cfg),str(path)])
        with db.connect(cfg) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY');_verify(conn,manifest,label='restore_mismatch')
    applied=_migrate_preserving(cfg,manifest)
    return {'restore_verified':True,'original_rows_unchanged':True,'migrations_applied':applied,'resumed':bool(current),'applied':True}
