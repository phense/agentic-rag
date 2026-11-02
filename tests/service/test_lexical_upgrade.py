"""Real populated 0.6.21 upgrade: originals, privileges, queued work and retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from agentic_rag import db, query_cache
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service import upgrade
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection
from agentic_rag.service.schema import validate_schema
from .test_auth import policy_file
from .test_model_lane import LANE, OTHER, PRIMARY, PRIMARY_VECTOR, LANE_VECTOR, ollama  # noqa: F401

SOURCE = '64f2104d7e8b542dbfb72c6fbb40196364afdc95'
POPULATE = r'''
import json, os
from agentic_rag import db, domains, jobs, pins, store
from agentic_rag.config import Config
assert db.__file__.startswith(os.getcwd())
cfg=Config(db_name=os.environ['LEXICAL_UPGRADE_DB'], db_host='127.0.0.1', ollama_url='http://127.0.0.1:1')
store.try_embed_texts=lambda *a,**k:None
db.init_db(cfg)
with db.connect(cfg) as c:
    domains.add_domain(c,'operations')
    ids=[]
    for i,(domain,project) in enumerate([('general','/synthetic/a'),('operations','/synthetic/b')]):
        ids.append(store.save_claim(c,cfg,title='Original '+domain,body='Original blue '+domain,
            domain=domain,dtype='memory',project=project,claim_kind='stated',evidence=[{
                'namespace':'session:lexical-'+domain,'source_id':'original','role':'user',
                'quote':'Original blue '+domain,'complete':True}]).doc_id)
        store.save_assertion(c,cfg,entity=domain,attribute='mode',value='blue',
            domain=domain,project=project,event_at='2026-01-01T00:00:00Z',
            evidence={'source_id':domain,'role':'user','quote':'blue'})
    pins.add_pin(c,body='Keep original pin',scope='global')
    jobs.enqueue_mine(c,cfg,session_id='pending-lexical',transcript_path='/synthetic/preserved.jsonl',project='/synthetic/a')
    n=c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']
    assert n==33
service={}
if os.environ.get('LEXICAL_POLICY'):
    # Multi-user service state of genuine 0.6.21: an accepted source window
    # (pending central job + receipt) and a queued tool request.
    import uuid
    from datetime import datetime, timezone
    from pathlib import Path
    from agentic_rag.service.auth import Policy
    from agentic_rag.service.ingest import accept
    from agentic_rag.service import requests as queue
    with db.connect(cfg) as c:
        domains.add_domain(c,'alpha')
    scfg=Config(db_name=cfg.db_name,db_host='127.0.0.1',ollama_url='http://127.0.0.1:1',
                service_auth_file=Path(os.environ['LEXICAL_POLICY']))
    policy=Policy.load(scfg.service_auth_file)
    who=policy.authenticate_key('one.synthetic-long-random-machine-secret')
    text='[user] server port is now 9000'
    service['receipt']=accept(scfg,who,policy,{'version':1,'session_id':'upgrade-lane','input_cursor':'',
        'output_cursor':'cursor-1','project':'/projects/a','window':{'text':text,'events':[{'source_id':'event-1',
        'role':'user','timestamp':'2026-10-29T10:00:00Z','text':text,'offset':0,'complete':True}],
        'warnings':[],'synthetic':False,'has_more':False}})['receipt']
    service['request']=queue.submit(scfg,who,{'idempotency_key':str(uuid.uuid4()),
        'created_at':datetime.now(timezone.utc).isoformat(),'tool':'memory_domains','arguments':{}})['request_id']
print(json.dumps({'schema':n,'ids':ids,'service':service}))
'''

OLD_LOCK = r'''
import json,os
from agentic_rag import db
from agentic_rag.config import Config
from agentic_rag.worker import acquire_database_lock
assert db.__file__.startswith(os.getcwd())
with acquire_database_lock(Config(db_name=os.environ['LEXICAL_UPGRADE_DB'],db_host='127.0.0.1')) as keeper:
    print(json.dumps({'excluded':keeper is None}))
'''

READ_OLD = r'''
import json,os
from agentic_rag import db
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope,apply_connection
assert db.__file__.startswith(os.getcwd())
cfg=Config(db_name=os.environ['LEXICAL_UPGRADE_DB'],db_host='127.0.0.1')
out=[]
for domain,project in [('general','/synthetic/a'),('operations','/synthetic/b')]:
    p=Principal('archived-reader','owned','test',frozenset({domain}),frozenset(),frozenset({project}),frozenset())
    with db.connect(cfg,role='reader') as c:
        apply_connection(c,RequestScope(p,cfg,True))
        rows=c.execute("SELECT * FROM hybrid_search_candidates('blue',NULL,NULL,150,NULL,'2026-11-01',false)").fetchall()
        assert rows and all(r['domain']==domain for r in rows)
        out.append(rows)
print(json.dumps(out,sort_keys=True,default=str))
'''


def function_privileges(cfg):
    with db.connect(cfg) as c:
        return c.execute("""SELECT oid,proname,proowner,proacl::text,prosecdef,proleakproof,proconfig,provolatile,
            pg_get_function_identity_arguments(oid) arguments
            FROM pg_proc WHERE proname=ANY(%s) ORDER BY proname""", ([
                'hybrid_search_candidates', 'hybrid_search_candidates_planned',
                'contextual_search_candidates', 'contextual_search_candidates_planned',
                'rag_service_source_write'],)).fetchall()


def assert_source_permissions_on_reused_connection(cfg):
    with db.connect(cfg) as owner:
        source = owner.execute("SELECT source_key,namespace FROM knowledge_sources WHERE namespace='session:lexical-general'").fetchone()
        assert source is not None
    with db.connect(cfg, role='reader') as conn:
        for _ in range(12):
            for domain, project, allowed in [('general', '/synthetic/a', True),
                                             ('operations', '/synthetic/b', False)]:
                who = Principal('restored-writer', 'owned', 'test', frozenset({domain}),
                                frozenset({domain}), frozenset({project}), frozenset({project}))
                apply_connection(conn, RequestScope(who, cfg, False))
                actual = conn.execute('SELECT public.rag_service_source_write(%s,%s) ok',
                                      (source['source_key'], source['namespace'])).fetchone()['ok']
                assert actual is allowed



def document_permission_state(cfg):
    with db.connect(cfg) as conn:
        helper=conn.execute("""SELECT pg_get_userbyid(proowner) owner,
            (SELECT jsonb_agg(jsonb_build_array(
                CASE WHEN grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(grantee) END,
                pg_get_userbyid(grantor),privilege_type,is_grantable)
                ORDER BY grantee,grantor,privilege_type,is_grantable)
             FROM aclexplode(COALESCE(proacl,acldefault('f',proowner)))) acl,provolatile,
            prosecdef,proleakproof,proisstrict,proparallel,proconfig,prosrc
            FROM pg_proc WHERE oid=to_regprocedure('public.rag_service_permission(text,jsonb)')""").fetchone()
        assert helper is not None
        assert not helper['prosecdef'] and not helper['proleakproof'] and not helper['proisstrict']
        assert helper['proparallel']=='u' and helper['proconfig'] is None
        for role in ('rag_reader','rag_writer','rag_admin'):
            assert conn.execute("SELECT has_function_privilege(%s,'public.rag_service_permission(text,jsonb)','EXECUTE') ok",(role,)).fetchone()['ok']
        policy=conn.execute("""SELECT polname,polcmd,polpermissive,polroles::text,
            pg_get_expr(polqual,polrelid) using_expr,pg_get_expr(polwithcheck,polrelid) check_expr
            FROM pg_policy WHERE polname='service_documents'""").fetchone()
        assert 'rag_service_permission' in policy['using_expr']
        assert 'read_domains' in policy['using_expr'] and 'write_domains' in policy['check_expr']
        return dict(helper=dict(helper),policy=dict(policy))


def assert_document_permissions_on_reused_connection(cfg):
    for role in ('reader','writer','admin'):
        with db.connect(cfg,role=role) as conn:
            conn.execute('SET plan_cache_mode=force_generic_plan')
            conn.execute('PREPARE upgraded_document_read AS SELECT id,domain,project_scope FROM documents ORDER BY id')
            initial=None
            for domain,project in [('general','/synthetic/a'),('operations','/synthetic/b'),('general','/synthetic/a')]:
                who=Principal('upgraded-reader','owned','test',frozenset({domain}),frozenset(),frozenset({project}),frozenset())
                apply_connection(conn,RequestScope(who,cfg,True))
                seen=conn.execute('EXECUTE upgraded_document_read').fetchall()
                assert seen and all(r['domain']==domain and r['project_scope']==project for r in seen)
                if initial is None:initial=seen
            assert seen==initial


def exercise_document_policy_rollback_reapply(cfg,archived=None):
    before=upgrade.inventory(cfg,'0.6.22',identities=True)
    original=document_permission_state(cfg)
    fixture=Path(__file__).parents[1]/'fixtures/document-permission-initplans/before.sql'
    with db.connect(cfg) as conn:
        conn.execute(fixture.read_text())
        conn.execute('DROP FUNCTION public.rag_service_permission(text,jsonb)')
        conn.commit()
        assert conn.execute("SELECT count(*) n FROM schema_migrations WHERE filename='035_document_permission_initplans.sql'").fetchone()['n']==1
        validate_schema(conn)
    assert_document_permissions_on_reused_connection(cfg)
    if archived is not None:
        read,expected=archived
        assert read()==expected
    assert upgrade.verify_preserved(cfg,before)['unchanged']
    # Marker is intentionally retained; the operator explicitly reapplies the
    # owned release SQL, rather than deleting migration history or user data.
    with db.connect(cfg) as conn:
        conn.execute((db.SQL_DIR/'035_document_permission_initplans.sql').read_text())
        conn.commit()
        validate_schema(conn)
    assert document_permission_state(cfg)==original
    assert_document_permissions_on_reused_connection(cfg)
    assert upgrade.verify_preserved(cfg,before)['unchanged']

def test_populated_0_6_21_lexical_upgrade_retry_and_independent_restore(tmp_path, monkeypatch, ollama):
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
    root = Path(__file__).resolve().parents[2]
    archive = tmp_path / 'old.tar'
    old = tmp_path / 'old-0.6.21'
    old.mkdir()
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'],
                       cwd=root, stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(old, filter='data')
    assert 'version = "0.6.21"' in (old / 'pyproject.toml').read_text()
    with isolated_database(Config(), initialize=False) as cfg:
        policy = policy_file(tmp_path)
        env = {**os.environ, 'PYTHONPATH': str(old), 'LEXICAL_UPGRADE_DB': cfg.db_name,
               'PYTHONDONTWRITEBYTECODE': '1', 'LEXICAL_POLICY': str(policy)}
        result = subprocess.run([sys.executable, '-c', POPULATE], cwd=old, env=env,
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        populated = json.loads(result.stdout)
        assert populated['schema'] == 33 and set(populated['service']) == {'receipt', 'request'}
        def old_read():
            result = subprocess.run([sys.executable, '-c', READ_OLD], cwd=old, env=env,
                                    text=True, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        old_results = old_read()
        privileges = function_privileges(cfg)
        assert len(privileges) == 5
        assert {row['proname'] for row in privileges if row['prosecdef']} == {'rag_service_source_write'}
        assert not any(row['proleakproof'] for row in privileges)
        before = upgrade.inventory(cfg, '0.6.21', identities=True)
        real_apply = db.apply_migrations
        def interrupted(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('interrupted034')
        monkeypatch.setattr(db, 'apply_migrations', interrupted)
        with pytest.raises(RuntimeError, match='interrupted034'):
            upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'interrupted.dump',
                                  apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as c:
            assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 33
        assert upgrade.verify_preserved(cfg, before)['unchanged']
        changed = upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'upgrade.dump',
                                        apply=True, writers_stopped=True)
        assert changed['migrations_applied'] == ['034_lexical_eligibility_work.sql', '035_document_permission_initplans.sql']
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        # Only the documented, function-local compiler setting changes. All old
        # settings and OID/owner/grants/security/signature fields remain exact.
        expected_privileges = []
        with db.connect(cfg) as owner:
            owner.execute("SELECT '[1]'::halfvec")
            iterative = owner.execute("SELECT EXISTS(SELECT 1 FROM pg_settings WHERE name='hnsw.iterative_scan') available").fetchone()['available']
        for row in privileges:
            settings = row['proconfig'] or []
            if row['proname'] == 'rag_service_source_write':
                expected_privileges.append(row)
                continue
            settings = settings + ['jit=off']
            if not row['proname'].endswith('_planned'):
                settings += ['hnsw.iterative_scan=strict_order'] if iterative else []
            expected_privileges.append(row | {'proconfig': settings})
        assert function_privileges(cfg) == expected_privileges
        assert_source_permissions_on_reused_connection(cfg)
        assert_document_permissions_on_reused_connection(cfg)
        document_permission_state(cfg)
        exercise_document_policy_rollback_reapply(cfg,archived=(old_read,old_results))
        assert old_read() == old_results  # Genuine archived0.6.21 with schema035.
        assert upgrade.verify_preserved(cfg, before)['unchanged']
        with db.connect(cfg) as c:
            validate_schema(c)
            assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 35
            assert c.execute("SELECT count(*) n FROM mining_queue WHERE kind='mine' AND session_id='pending-lexical'").fetchone()['n'] == 1
        retry = upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'retry.dump',
                                      apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        # The target release must support its own truthful backup label, with a
        # real independent restore; accepting only its predecessor breaks recovery.
        after = upgrade.verified_backup(cfg, '0.6.22', tmp_path / 'after.dump')
        assert after['restore_verified']
        assert after['manifest']['source_version'] == '0.6.22'
        assert upgrade.verify_preserved(cfg, after['manifest'])['unchanged']
        exercise_final_runtime(cfg, policy, populated, old, env, monkeypatch, ollama)


def exercise_final_runtime(cfg, policy, populated, old, env, monkeypatch, ollama):
    """A2 runtime on the upgraded populated store, after both verified backups.

    Real accepted 0.6.21 window/job/request, worker fence, gateway and request
    consumer; only the extraction provider and Ollama HTTP are simulated.
    """
    from dataclasses import replace
    from agentic_rag import mining
    from agentic_rag.service import requests as queue
    from agentic_rag.service.engine import ResourcePressure
    from agentic_rag.service.fence import worker_scope
    from agentic_rag.service.worker import process_source
    from agentic_rag.worker import acquire_database_lock
    calls = []
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: calls.append(1) or {'memories': [{
        'title': 'Upgrade lane port', 'body': 'server port is now 9000', 'domain': 'alpha', 'edges': [],
        'claim_kind': 'stated', 'evidence': [{'source_id': 'event-1', 'quote': 'server port is now 9000'}]}]})
    default = replace(cfg, service_mode='server', service_auth_file=policy, ollama_url=PRIMARY)
    lane = replace(default, ollama_background_url=LANE, service_request_consumers=4)
    def originals():
        with db.connect(cfg) as c:
            return (c.execute('SELECT id,title,body,status,domain,project_scope FROM documents WHERE id=ANY(%s::uuid[]) ORDER BY id',
                              (populated['ids'],)).fetchall(),
                    c.execute('SELECT body,scope FROM pins ORDER BY body').fetchall(),
                    c.execute("SELECT status,attempts,transcript_path FROM mining_queue WHERE session_id='pending-lexical'").fetchall())
    before = originals()
    def window():
        with db.connect(cfg) as c:
            return (c.execute("SELECT state,result->>'code' code FROM service_windows WHERE id=%s", (receipt,)).fetchone(),
                    [json.loads(r['v']) for r in c.execute("SELECT c.embedding::text v FROM chunks c JOIN documents d "
                     "ON d.id=c.document_id WHERE d.title='Upgrade lane port'")],
                    c.execute('SELECT count(*) n FROM mining_batches WHERE applied_at IS NULL').fetchone()['n'])
    receipt = populated['service']['receipt']
    with db.connect(cfg) as c:
        job = dict(c.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON q.id=w.queue_id WHERE w.id=%s',
                             (receipt,)).fetchone())
    with acquire_database_lock(lane) as keeper:
        assert keeper is not None
        # The pending 0.6.21 queued request is foreground demand: no lane
        # page starts. (Called directly, bypassing drain's entry check, the
        # extraction is accepted once and retained for replay.)
        with worker_scope(keeper), db.connect(lane) as conn:
            with pytest.raises(ResourcePressure, match='foreground_busy'):
                process_source(conn, lane, job)
        assert calls == [1] and not ollama.embeds() and window()[2] == 1
    # The queued 0.6.21 request executes on the final consumer path.
    assert queue.run_one(lane) is True
    with db.connect(cfg) as c:
        row = c.execute('SELECT state,result FROM service_requests WHERE id=%s', (populated['service']['request'],)).fetchone()
    assert row['state'] == 'completed' and row['result']['domains'][0]['name'] == 'alpha'
    with acquire_database_lock(lane) as keeper:
        assert keeper is not None
        # Genuine 0.6.21 worker code is excluded by the same singleton lock.
        locked = subprocess.run([sys.executable, '-c', OLD_LOCK], cwd=old, env=env,
                                text=True, capture_output=True, timeout=60)
        assert locked.returncode == 0, locked.stderr
        assert json.loads(locked.stdout) == {'excluded': True}
        # Lane digest swap during inference: nothing published, batch retained.
        def swap(fake):
            fake.after_embed = None
            fake.digests['lane.test'] = OTHER
        ollama.after_embed = swap
        with worker_scope(keeper), db.connect(lane) as conn:
            with pytest.raises(ResourcePressure, match='background_model_identity'):
                process_source(conn, lane, job)
    state, vectors, accepted = window()
    assert (state['state'], state['code'], vectors, accepted, calls) == ('blocked', 'background_model_identity', [], 1, [1])
    # Optional keys removed and processes restarted: the default lane applies
    # the accepted output without a second provider call.
    lane_calls = len(ollama.embeds('lane.test'))
    assert lane_calls == 1
    with acquire_database_lock(default) as keeper:
        with worker_scope(keeper), db.connect(default) as conn:
            assert process_source(conn, default, job).saved == 1
    state, vectors, accepted = window()
    assert state['state'] == 'applied' and accepted == 0 and calls == [1]
    assert vectors and all(v == PRIMARY_VECTOR for v in vectors)
    assert len(ollama.embeds('lane.test')) == lane_calls
    assert originals() == before


def test_non_superuser_owner_upgrades_and_restores_populated_store(tmp_path, monkeypatch):
    # Mutation: a custom placeholder in CREATE/ALTER FUNCTION SET silently adds
    # a superuser requirement to supported owner migrations and dump restores.
    import uuid
    import psycopg
    from psycopg import sql

    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
    root = Path(__file__).resolve().parents[2]
    archive = tmp_path / 'limited-old.tar'
    old = tmp_path / 'limited-old-0.6.21'
    old.mkdir()
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'],
                       cwd=root, stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(old, filter='data')
    role = 'rag92_owner_' + uuid.uuid4().hex[:12]
    base = Config()
    with psycopg.connect(db.dsn(base, dbname='postgres'), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOINHERIT NOBYPASSRLS').format(sql.Identifier(role)))
        try:
            # The documented deployment preloads vector. Apply that prerequisite
            # only to this disposable role, never to the shared test cluster.
            admin.execute(sql.SQL("ALTER ROLE {} SET session_preload_libraries='vector'").format(sql.Identifier(role)))
            with isolated_database(base, initialize=False) as template:
                with db.connect(template) as c:
                    marker = c.execute('SELECT owner_id FROM benchmark_ownership').fetchone()['owner_id']
                    c.execute('DROP TABLE benchmark_ownership')
                    c.execute('CREATE EXTENSION vector')
                admin.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(
                    sql.Identifier(template.db_name), sql.Identifier(role)))
                try:
                    with monkeypatch.context() as limited:
                        limited.setenv('PGUSER', role)
                        with isolated_database(base, initialize=False, template=template.db_name) as cfg:
                            env = {**os.environ, 'PYTHONPATH': str(old),
                                   'LEXICAL_UPGRADE_DB': cfg.db_name, 'PYTHONDONTWRITEBYTECODE': '1'}
                            made = subprocess.run([sys.executable, '-c', POPULATE], cwd=old, env=env,
                                                  capture_output=True, text=True, timeout=60)
                            assert made.returncode == 0, made.stderr
                            assert json.loads(made.stdout)['schema'] == 33
                            with db.connect(cfg) as c:
                                privileges = c.execute('SELECT rolsuper,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
                                assert not any(privileges.values())
                                assert c.execute("SELECT count(*) n FROM pg_parameter_acl WHERE parname='rag.iterative_vectors'").fetchone()['n'] == 0
                            before = upgrade.inventory(cfg, '0.6.21', identities=True)
                            upgraded = upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'limited-upgrade.dump',
                                apply=True, writers_stopped=True, verification_template=template.db_name)
                            assert upgraded['migrations_applied'] == ['034_lexical_eligibility_work.sql', '035_document_permission_initplans.sql']
                            assert upgraded['restore_verified'] and upgraded['original_rows_unchanged']
                            assert upgrade.verify_preserved(cfg, before)['unchanged']
                            target = upgrade.verified_backup(cfg, '0.6.22', tmp_path / 'limited-target.dump',
                                                             verification_template=template.db_name)
                            assert target['restore_verified']
                            assert target['manifest']['identity']['owner'] == role
                            target_privileges = [{k: v for k, v in row.items() if k != 'oid'}
                                                 for row in function_privileges(cfg)]
                            assert_source_permissions_on_reused_connection(cfg)
                            permission_state=document_permission_state(cfg)
                            exercise_document_policy_rollback_reapply(cfg)
                            with db.connect(cfg) as c:
                                assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 35
                                assert c.execute("SELECT count(*) n FROM mining_queue WHERE session_id='pending-lexical'").fetchone()['n'] == 1
                            # Also restore the real target archive into a separate
                            # owner-created database and exercise the SQL there.
                            with isolated_database(base, initialize=False, template=template.db_name) as restored:
                                upgrade._restore_verification(cfg, restored, target['dump'], target['manifest'], prepared_template=True)
                                assert upgrade.verify_preserved(restored, target['manifest'])['unchanged']
                                assert [{k: v for k, v in row.items() if k != 'oid'}
                                        for row in function_privileges(restored)] == target_privileges
                                assert_source_permissions_on_reused_connection(restored)
                                assert document_permission_state(restored)==permission_state
                                assert_document_permissions_on_reused_connection(restored)
                                with db.connect(restored) as c:
                                    assert not c.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()['rolsuper']
                                    assert c.execute("SELECT count(*) n FROM hybrid_search_candidates('blue')").fetchone()['n'] > 0
                                    assert c.execute("SELECT count(*) n FROM mining_queue WHERE session_id='pending-lexical'").fetchone()['n'] == 1
                finally:
                    with db.connect(template) as c:
                        c.execute('CREATE TABLE benchmark_ownership(owner_id text PRIMARY KEY)')
                        c.execute('INSERT INTO benchmark_ownership VALUES (%s)', (marker,))
        finally:
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
