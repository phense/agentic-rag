"""Confirmed S058-01 review reproductions, using owned synthetic databases."""
import asyncio
from dataclasses import replace
import json

import psycopg
import pytest

from agentic_rag import db, store
from agentic_rag.config import Config
from agentic_rag.service.context import request_scope
from .test_scope import service_store, principal


def test_readable_document_cannot_be_moved_into_owned_scope(service_store):
    cfg, _ = service_store
    with db.connect(cfg) as conn:
        doc = store.save_document(conn, cfg, title='Read only global', body='Original evidence',
                                  domain='general', dtype='memory', scope='global')
    p = replace(principal(), read_domains=frozenset({'alpha', 'general'}),
                read_projects=frozenset({'/projects/a', 'global'}))
    with request_scope(p, cfg), db.connect(cfg, role='writer') as conn:
        with pytest.raises((ValueError, psycopg.errors.InsufficientPrivilege)):
            store.save_document(conn, cfg, title='Taken over', body='Replacement',
                                domain='alpha', dtype='memory', doc_id=doc.doc_id, project='/projects/a')
    with db.connect(cfg) as conn:
        row = conn.execute('SELECT body,domain,project_scope FROM documents WHERE id=%s', (doc.doc_id,)).fetchone()
        assert row == {'body': 'Original evidence', 'domain': 'general', 'project_scope': 'global'}


def test_reader_cannot_exploit_temporary_relation_in_definer(service_store):
    cfg, docs = service_store
    with db.connect(cfg, role='reader') as conn:
        conn.execute("""CREATE FUNCTION pg_temp.poison() RETURNS boolean LANGUAGE plpgsql AS $$
            BEGIN UPDATE public.documents SET title='poisoned' WHERE slug='allowed'; RETURN true; END $$""")
        conn.execute("CREATE TEMP VIEW documents AS SELECT id,domain,project_scope FROM public.documents WHERE pg_temp.poison()")
        conn.execute("SELECT set_config('rag_service.active','1',false)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT public.rag_service_assert_document(%s)', (docs['allowed'],))
    # A legitimate writer also must resolve the real relation and never execute the view.
    with request_scope(principal(), cfg), db.connect(cfg, role='writer') as conn:
        conn.execute("""CREATE FUNCTION pg_temp.poison() RETURNS boolean LANGUAGE plpgsql AS $$
            BEGIN UPDATE public.documents SET title='poisoned' WHERE slug='allowed'; RETURN true; END $$""")
        conn.execute("CREATE TEMP VIEW documents AS SELECT id,domain,project_scope FROM public.documents WHERE pg_temp.poison()")
        conn.execute('SELECT public.rag_service_assert_document(%s)', (docs['allowed'],))
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT title FROM documents WHERE id=%s', (docs['allowed'],)).fetchone()['title'] == 'allowed'


def test_service_graph_write_preserves_actor_and_bounded_origin(service_store,tmp_path):
    from agentic_rag import mcp_server
    from .test_auth import policy_file
    from agentic_rag.service.auth import Policy
    cfg, _ = service_store
    cfg=replace(cfg,service_auth_file=policy_file(tmp_path))
    authenticated=Policy.load(cfg.service_auth_file).authenticate_key('one.synthetic-long-random-machine-secret')
    with request_scope(authenticated, cfg):
        result = mcp_server.memory_save(title='Owned graph', body='Synthetic relation', domain='alpha',
            project='/projects/a', edges=[{'predicate':'references','dst_slug':'allowed'}])
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT created_by FROM edges WHERE src_id=%s', (result['doc_id'],)).fetchone()['created_by'] == 'manual'
        assert conn.execute("SELECT actor FROM audit_log WHERE document_id=%s AND op='save_document'", (result['doc_id'],)).fetchone()['actor'] == 'service:machine:alice:vm1'


def test_owned_dangling_reference_resolves_later_and_hides_foreign_target(service_store,tmp_path):
    from .test_auth import policy_file
    from agentic_rag.service.auth import Policy
    cfg, _ = service_store
    cfg=replace(cfg,service_auth_file=policy_file(tmp_path))
    authenticated=Policy.load(cfg.service_auth_file).authenticate_key('one.synthetic-long-random-machine-secret')
    with request_scope(authenticated, cfg), db.connect(cfg, role='writer') as conn:
        result = store.save_document(conn, cfg, title='Future reference', body='Known source', domain='alpha',
            dtype='memory', project='/projects/a', actor='manual', edges=[store.EdgeSpec('references','future-owned-target')])
        row = conn.execute('SELECT dst_id,dst_slug FROM edges WHERE src_id=%s', (result.doc_id,)).fetchone()
        assert row['dst_id'] is None and row['dst_slug'] == 'future-owned-target'
        target = store.save_document(conn, cfg, title='Future owned target', slug='future-owned-target', body='Later source',
            domain='alpha', dtype='memory', project='/projects/a', actor='manual')
        assert str(conn.execute('SELECT dst_id FROM edges WHERE src_id=%s', (result.doc_id,)).fetchone()['dst_id']) == target.doc_id
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.save_document(conn, cfg, title='Foreign target denied', body='No foreign link', domain='alpha',
                dtype='memory', project='/projects/a', actor='manual', edges=[store.EdgeSpec('references','foreign')])


def test_unfinished_bodies_expire_and_release_all_capacity(monkeypatch,tmp_path):
    from agentic_rag.service import api
    monkeypatch.setattr(api, 'BODY_TIMEOUT', .03, raising=False)
    async def run():
        called=[]
        async def app(scope, receive, send):
            called.append(scope['path'])
        gateway=api.Gateway(app, Config(), tmp_path/'unused-policy.toml')
        async def never():
            await asyncio.Event().wait()
        scope={'type':'http','method':'POST','path':'/v1/tools/memory_get','scheme':'https',
               'headers':[(b'x-rag-protocol',b'1'),(b'authorization',b'Bearer invalid')], 'client':('203.0.113.1',123)}
        async def one():
            messages=[]
            async def send(message): messages.append(message)
            await gateway(dict(scope), never, send)
            return messages
        try:
            messages=await asyncio.wait_for(asyncio.gather(*(one() for _ in range(8))),timeout=.5)
        except TimeoutError:
            pytest.fail('Unfinished requests never release the eight service slots')
        assert all(next(m['status'] for m in result if m['type']=='http.response.start') == 408 for result in messages)
        assert not gateway.slots.locked()
        assert not called
        assert json.loads(messages[0][-1]['body']) == {'error':'request_timeout'}
    asyncio.run(run())


def test_window_cannot_reference_foreign_stream(service_store):
    cfg, _ = service_store
    p=principal()
    other=replace(p, machine_id='other-vm')
    with request_scope(other, cfg), db.connect(cfg, role='writer') as conn:
        conn.execute('INSERT INTO service_streams(session_id,owner_namespace,project) VALUES (%s,%s,%s)',
                     (other.session_id('same'), other.namespace, '/projects/a'))
    with request_scope(p, cfg), db.connect(cfg, role='writer') as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("""INSERT INTO service_windows(owner_namespace,session_id,project,input_cursor,output_cursor,content_hash,payload)
                VALUES (%s,%s,'/projects/a','','next','synthetic','{}')""", (p.namespace, other.session_id('same')))


def test_service_refuses_legacy_schema_and_disabled_rls(service_store, tmp_path):
    from agentic_rag.service.api import create_app
    from .test_auth import policy_file
    from agentic_rag.service.auth import Policy
    cfg, _ = service_store
    policy=policy_file(tmp_path)
    for unsafe in ("DELETE FROM schema_migrations WHERE filename IN ('021_service_scope.sql','022_service_state.sql')",
                   'ALTER TABLE documents DISABLE ROW LEVEL SECURITY'):
        with db.connect(cfg) as owner:
            original=owner.execute('SELECT filename,applied_at FROM schema_migrations').fetchall()
            owner.execute(unsafe)
            owner.commit()
            try:
                with pytest.raises(PermissionError, match='incompatible_service_schema'):
                    create_app(cfg,policy)
                # A previously constructed service must also fail closed on new connections.
                with request_scope(principal(),cfg):
                    with pytest.raises(PermissionError, match='incompatible_service_schema'):
                        with db.connect(cfg,role='reader'):
                            pytest.fail('unsafe service connection escaped validation')
            finally:
                owner.execute('ALTER TABLE documents ENABLE ROW LEVEL SECURITY')
                for row in original:
                    owner.execute('INSERT INTO schema_migrations(filename,applied_at) VALUES (%s,%s) ON CONFLICT DO NOTHING', (row['filename'],row['applied_at']))
                owner.commit()


def test_remote_checkpoint_lookup_never_probes_server_filesystem(service_store,monkeypatch):
    from agentic_rag import mcp_server
    from agentic_rag.hooks import session_start
    cfg, _=service_store
    probes=[]
    def forbidden_capture(*args,**kwargs):
        probes.append((args,kwargs))
        raise AssertionError('Remote project is not a service-host path')
    monkeypatch.setattr(session_start.capture,'capture_snapshot',forbidden_capture)
    with request_scope(principal(readonly=True),cfg,read_only=True):
        mcp_server.memory_context(project='/server/other-tenant',session_id=principal().session_id('missing'))
    assert probes == []
    from agentic_rag.continuity.model import CheckpointSnapshot
    from agentic_rag.continuity import store as checkpoints
    session=principal().session_id('existing')
    with request_scope(principal(),cfg), db.connect(cfg,role='writer') as conn:
        checkpoints.upsert_snapshot(conn,CheckpointSnapshot(session,None,'cursor','PreCompact','auto','/projects/a','/projects/a'))
    with request_scope(principal(readonly=True),cfg,read_only=True):
        result=mcp_server.memory_context(project='/projects/a',session_id=session)
        assert 'Continuation checkpoint' in result['text']
    assert probes == []


def test_remote_context_replaces_operator_details_with_status_codes(service_store,tmp_path,monkeypatch):
    from agentic_rag import mcp_server
    from agentic_rag.hooks import session_start
    from agentic_rag.provider_health import ProviderHealth
    cfg,_=service_store
    warning=tmp_path/'warning'; warning.write_text('/srv/OTHER_TENANT/project-secret/private.dump')
    monkeypatch.setattr(session_start,'WARNING_STATE',warning)
    monkeypatch.setattr(session_start.provider_health,'read_health',lambda: ProviderHealth('/srv/OTHER_PROVIDER/private',False,reason='/secret/operator/detail'))
    with request_scope(principal(readonly=True),cfg,read_only=True):
        result=mcp_server.memory_context(project='/projects/a')
    assert 'OTHER_TENANT' not in json.dumps(result)
    assert 'backup_warning' in json.dumps(result)
    assert 'provider_unavailable' in json.dumps(result)
    assert 'OTHER_PROVIDER' not in json.dumps(result)
    assert '/secret/operator/detail' not in json.dumps(result)


def test_human_and_machine_named_human_have_distinct_audit_actors():
    p=principal()
    human=replace(p,machine_id=None)
    machine=replace(p,machine_id='human')
    assert human.actor != machine.actor
    assert human.namespace != machine.namespace


def test_remote_checkpoint_failure_does_not_echo_operator_exception(service_store,monkeypatch):
    from agentic_rag import mcp_server
    from agentic_rag.hooks import session_start
    cfg,_=service_store
    def failed_lookup(*args,**kwargs):
        raise ValueError('/srv/OTHER_TENANT/operator/private-state')
    monkeypatch.setattr(session_start,'_checkpoint_for_context',failed_lookup)
    with request_scope(principal(readonly=True),cfg,read_only=True):
        result=mcp_server.memory_context(project='/projects/a')
    assert 'OTHER_TENANT' not in json.dumps(result)
    assert 'checkpoint_unavailable' in result['text']


def test_eight_idle_mcp_gets_cannot_reserve_rest_capacity(monkeypatch,tmp_path):
    from agentic_rag.service import api
    monkeypatch.setattr(api.Policy,'load',lambda _:None)
    monkeypatch.setattr(api,'authenticate',lambda *args:principal(readonly=True))
    async def run():
        release=asyncio.Event()
        async def app(scope,receive,send):
            if scope['path'].startswith('/mcp/'):
                await release.wait()
            await api.JSONResponse({'status':'ok'})(scope,receive,send)
        gateway=api.Gateway(app, Config(), tmp_path/'unused-policy.toml')
        async def one(path,method):
            messages=[]
            async def receive():
                return {'type':'http.request','body':b'','more_body':False}
            async def send(message): messages.append(message)
            scope={'type':'http','method':method,'path':path,'scheme':'https','client':('203.0.113.1',123),
                'headers':[(b'authorization',b'Bearer synthetic'),(b'x-rag-protocol',b'1'),(b'accept',b'text/event-stream')]}
            await gateway(scope,receive,send)
            return next(m['status'] for m in messages if m['type']=='http.response.start')
        streams=[asyncio.create_task(one('/mcp/ro/','GET')) for _ in range(8)]
        try:
            done,pending=await asyncio.wait(streams,timeout=.1)
            assert not pending, 'Idle MCP GET streams consume all eight shared slots'
            assert [task.result() for task in streams] == [405]*8
            assert await one('/v1/capabilities','GET') == 200
            assert not gateway.slots.locked()
        finally:
            release.set()
            for task in streams: task.cancel()
            await asyncio.gather(*streams,return_exceptions=True)
    asyncio.run(run())


def test_service_rejects_disabled_authenticated_audit_actor(service_store,tmp_path):
    from .test_auth import policy_file
    from agentic_rag.service.auth import Policy
    from agentic_rag.service.api import create_app
    cfg,_=service_store
    with db.connect(cfg) as owner:
        owner.execute('ALTER TABLE audit_log DISABLE TRIGGER service_audit_actor')
        owner.commit()
        try:
            with pytest.raises(PermissionError,match='incompatible_service_schema'):
                create_app(cfg,policy_file(tmp_path))
        finally:
            owner.execute('ALTER TABLE audit_log ENABLE TRIGGER service_audit_actor');owner.commit()
