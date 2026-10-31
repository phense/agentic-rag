"""Operator migration proofs use only owned legacy databases and private artifacts."""
from dataclasses import replace
from pathlib import Path

import pytest
from agentic_rag import db, store
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from test_maintenance_restore import owned_source


@pytest.fixture(autouse=True)
def model_identity(monkeypatch):
    from agentic_rag import query_cache
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)


@pytest.mark.parametrize('version',['0.5.9','0.7.0','9.0.0','unknown'])
def test_unsupported_source_refuses_before_database_access(monkeypatch,version):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(db,'connect',lambda *a,**k:pytest.fail('unsupported source connected'))
    with pytest.raises(ValueError,match='unsupported_source_version'):upgrade.inventory(Config(),version)


@pytest.mark.parametrize('schema',[18,19])
def test_verified_local_upgrade_preserves_rows_grants_and_retries(tmp_path,monkeypatch,schema):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,schema) as cfg:
        before=upgrade.inventory(cfg,'0.6.3',identities=True)
        assert before['supported'] and len(before['migrations'])==schema
        assert before['tables']['documents']['rows']==2
        assert upgrade.inventory(cfg,'0.6.3')['tables']==before['tables']
        plan=upgrade.local_upgrade(cfg,'0.6.3',tmp_path/'upgrade.dump')
        assert plan['mode']=='local' and plan['applied'] is False
        assert not (tmp_path/'upgrade.dump').exists()
        result=upgrade.local_upgrade(cfg,'0.6.3',tmp_path/'upgrade.dump',apply=True,writers_stopped=True)
        assert result['original_rows_unchanged'] and result['restore_verified']
        assert result['applied'] and len(result['migrations_applied'])==28-schema
        assert upgrade.verify_preserved(cfg,result['manifest'])['unchanged']
        retry=upgrade.local_upgrade(cfg,'0.6.3',tmp_path/'retry.dump',apply=True,writers_stopped=True)
        assert retry['migrations_applied']==[]
        with db.connect(cfg) as conn:
            assert conn.execute('SHOW default_transaction_read_only').fetchone()['default_transaction_read_only']=='off'


def test_strict_backup_tamper_and_legitimate_source_drift_are_distinct(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,19) as cfg:
        verified=upgrade.verified_backup(cfg,'0.6.3',tmp_path/'source.dump')
        assert verified['restore_verified']
        with db.connect(cfg) as conn:store.save_document(conn,cfg,title='New after snapshot',body='Preserve later writes',domain='general',dtype='memory')
        with pytest.raises(ValueError,match='source_drift'):upgrade.verify_preserved(cfg,verified['manifest'])
        with (tmp_path/'source.dump').open('ab') as fh:fh.write(b'tampered')
        with pytest.raises(ValueError,match='dump_digest_mismatch'):upgrade.check_dump(tmp_path/'source.dump',verified['manifest'])


def test_remote_preflight_refuses_unresolved_transcripts_and_reports_collisions(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,19) as cfg:
        with db.connect(cfg) as conn:conn.execute("INSERT INTO mining_queue(kind,session_id,transcript_path) VALUES ('mine','old-vm-session','/old-vm/private-transcript.jsonl')")
        local=upgrade.preflight(cfg,'0.6.3',mode='local')
        remote=upgrade.preflight(cfg,'0.6.3',mode='remote')
        assert local['ready'] and not remote['ready']
        assert 'unresolved_transcript_paths' in remote['blockers']
        one=upgrade.inventory(cfg,'0.6.3',identities=True)
        report=upgrade.collision_report([one,one])
        assert not report['ready'] and report['collisions']
        assert report['sources_untouched']


def test_cutover_fences_legacy_writes_and_restore_resumes_without_overwrite(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,19) as source:
        with upgrade.source_fence(source,writers_stopped=True) as fence:
            with db.connect(source) as old:
                with pytest.raises(__import__('psycopg').errors.ReadOnlySqlTransaction):
                    old.execute("UPDATE documents SET title='must fail'")
            verified=upgrade.verified_backup(source,'0.6.3',tmp_path/'move.dump')
            with isolated_database(source,initialize=False) as target:
                report=upgrade.restore_target(target,tmp_path/'move.dump',verified['manifest'],apply=True)
                assert report['restore_verified'] and report['original_rows_unchanged']
                assert upgrade.restore_target(target,tmp_path/'move.dump',verified['manifest'],apply=True,resume=True)['resumed']
                with db.connect(target) as conn:store.save_document(conn,target,title='Target accepted later write',body='Must survive failed rollback',domain='general',dtype='memory')
                with pytest.raises(ValueError,match='target_drift'):
                    upgrade.restore_target(target,tmp_path/'move.dump',verified['manifest'],apply=True,resume=True)
                with db.connect(target) as conn:assert conn.execute("SELECT count(*) n FROM documents WHERE title='Target accepted later write'").fetchone()['n']==1


def test_interrupted_local_upgrade_rolls_back_and_releases_read_only_fence(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,19) as cfg:
        original=upgrade.inventory(cfg,'0.6.3')
        real=db.apply_migrations
        def interrupt(conn,*a,**k):
            real(conn,*a,**k)
            raise RuntimeError('synthetic interruption before verification/commit')
        monkeypatch.setattr(db,'apply_migrations',interrupt)
        with pytest.raises(RuntimeError,match='synthetic interruption'):
            upgrade.local_upgrade(cfg,'0.6.3',tmp_path/'interrupted.dump',apply=True,writers_stopped=True)
        assert upgrade.inventory(cfg,'0.6.3')['tables']==original['tables']
        with db.connect(cfg) as conn:assert conn.execute('SHOW default_transaction_read_only').fetchone()['default_transaction_read_only']=='off'


def test_restore_rejects_changed_embedding_identity_before_mutation(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    from agentic_rag import query_cache
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,19) as cfg:
        proof=upgrade.verified_backup(cfg,'0.6.3',tmp_path/'model.dump')
        with isolated_database(cfg,initialize=False) as target:
            monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'b'*64)
            with pytest.raises(ValueError,match='embedding_identity_mismatch'):
                upgrade.restore_target(target,tmp_path/'model.dump',proof['manifest'],apply=True)
            with db.connect(target) as conn:assert upgrade._tables(conn)==[]


def test_role_database_override_refuses_ineffective_source_fence(tmp_path):
    from agentic_rag.service import upgrade
    from psycopg import sql
    with owned_source(tmp_path,19) as cfg:
        with db.connect(cfg) as conn:
            conn.execute(sql.SQL('ALTER ROLE rag_writer IN DATABASE {} SET default_transaction_read_only=off').format(sql.Identifier(cfg.db_name)))
        with pytest.raises(ValueError,match='role_read_only_override'):
            with upgrade.source_fence(cfg,writers_stopped=True):pytest.fail('ineffective fence accepted')


def test_populated_original022_adds_uploader_without_rewriting_session_history(tmp_path,monkeypatch):
    """M058-08: applied022 must not be replayed; retain old sessions and require fresh login."""
    from starlette.testclient import TestClient
    from .test_api import app_fixture, headers
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,22) as cfg:
        with db.connect(cfg) as conn:
            # Exact original022 shape, before uploader profiles were introduced.
            assert conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='service_sessions' AND column_name='uploader_id'").fetchone() is None
            conn.execute("INSERT INTO service_sessions(token_hash,user_id,password_revision,expires_at) VALUES ('old-session-hash','alice','old-revision',now()+interval '1 hour')")
            old=dict(conn.execute('SELECT * FROM service_sessions').fetchone())
            conn.commit()
        result=upgrade.local_upgrade(cfg,'0.6.9',tmp_path/'original022.dump',apply=True,writers_stopped=True)
        assert result['migrations_applied']==['023_claim_lookup.sql','024_request_queue.sql','025_dashboard.sql','026_request_tracing.sql','027_provider_indexes.sql','028_reranker_settings.sql']
        assert result['original_rows_unchanged'] and result['restore_verified']
        assert upgrade.verify_preserved(cfg,result['manifest'])['unchanged']
        with db.connect(cfg) as conn:
            current=dict(conn.execute("SELECT * FROM service_sessions WHERE token_hash='old-session-hash'").fetchone())
            assert current.pop('uploader_id') is None
            assert current==old
        # Projection compatibility must still detect an altered ORIGINAL field.
        with db.connect(cfg) as conn:
            conn.execute("UPDATE service_sessions SET user_id='changed' WHERE token_hash='old-session-hash'")
            with pytest.raises(ValueError,match='source_drift'):
                upgrade._verify(conn,result['manifest'],preserved=True)
            conn.rollback()
            conn.execute("UPDATE service_sessions SET uploader_id='c5f32e62-3f88-4c5c-9f6e-f1e4216c6cc9' WHERE token_hash='old-session-hash'")
            with pytest.raises(ValueError,match='source_drift'):
                upgrade._verify(conn,result['manifest'],preserved=True)
            conn.rollback()
        app,_=app_fixture(tmp_path,cfg)
        with TestClient(app,base_url='https://testserver') as client:
            login=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={
                'username':'alice','password':'correct horse synthetic password',
                'uploader_id':'c5f32e62-3f88-4c5c-9f6e-f1e4216c6cc9'})
            assert login.status_code==200,login.text
            assert client.get('/v1/capabilities',headers=headers(login.json()['access_token'])).status_code==200


@pytest.mark.parametrize('drift',[
    'ALTER COLUMN uploader_id TYPE integer USING uploader_id::text::integer',
    'ALTER COLUMN uploader_id SET NOT NULL',
    'ALTER COLUMN uploader_id SET DEFAULT gen_random_uuid()',
])
def test_original022_compatibility_rejects_uploader_schema_drift(tmp_path,monkeypatch,drift):
    """A NULL-only row projection must never certify an incompatible login schema."""
    from agentic_rag.service import upgrade
    from agentic_rag.service.schema import validate_schema,ServiceSchemaError
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,22) as cfg:
        original=upgrade.inventory(cfg,'0.6.9')
        with db.connect(cfg) as conn:
            db.apply_migrations(conn,db.SQL_DIR)
            conn.execute('ALTER TABLE public.service_sessions '+drift)
        with pytest.raises(ValueError,match='uploader_schema'):
            upgrade.verify_preserved(cfg,original)
        with db.connect(cfg) as conn:
            with pytest.raises(ServiceSchemaError):validate_schema(conn)


def test_populated023_upgrade_current024_backup_restore_and_retry(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,23) as cfg:
        with db.connect(cfg) as conn:
            conn.execute("INSERT INTO mining_queue(kind,session_id,transcript_path) VALUES ('mine','preserve-pending','/owned/original.jsonl')")
        old=upgrade.inventory(cfg,'0.6.10')
        result=upgrade.local_upgrade(cfg,'0.6.10',tmp_path/'upgrade024.dump',apply=True,writers_stopped=True)
        assert result['original_rows_unchanged'] and result['restore_verified']
        assert result['migrations_applied']==['024_request_queue.sql','025_dashboard.sql','026_request_tracing.sql','027_provider_indexes.sql','028_reranker_settings.sql']
        assert upgrade.verify_preserved(cfg,result['manifest'])['unchanged']
        current=upgrade.verified_backup(cfg,'0.6.11',tmp_path/'current024.dump')
        assert current['restore_verified']
        retry=upgrade.local_upgrade(cfg,'0.6.11',tmp_path/'retry024.dump',apply=True,writers_stopped=True)
        assert retry['migrations_applied']==[] and retry['original_rows_unchanged']
        assert upgrade.inventory(cfg,'0.6.11')['tables']==current['manifest']['tables']


def test_populated024_upgrade025_preserves_all_originals_and_retry(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    from agentic_rag.service.schema import validate_schema
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,24) as cfg:
        original=upgrade.inventory(cfg,'0.6.11')
        changed=upgrade.local_upgrade(cfg,'0.6.11',tmp_path/'upgrade025.dump',apply=True,writers_stopped=True)
        assert changed['migrations_applied']==['025_dashboard.sql','026_request_tracing.sql','027_provider_indexes.sql','028_reranker_settings.sql']
        assert changed['original_rows_unchanged'] and changed['restore_verified']
        assert upgrade.verify_preserved(cfg,original)['unchanged']
        with db.connect(cfg) as conn:
            validate_schema(conn)
            assert conn.execute('SELECT count(*) n FROM dashboard_changes').fetchone()['n']==0
        backup=upgrade.verified_backup(cfg,'0.6.12',tmp_path/'current025.dump')
        assert backup['restore_verified']
        repeated=upgrade.local_upgrade(cfg,'0.6.12',tmp_path/'retry025.dump',apply=True,writers_stopped=True)
        assert repeated['migrations_applied']==[] and repeated['original_rows_unchanged']


def test_verified_backup_accepts_explicit_empty_extension_template(tmp_path,monkeypatch):
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with owned_source(tmp_path,24) as cfg:
        with isolated_database(cfg,initialize=False) as template:
            with db.connect(template) as conn:
                marker=conn.execute('SELECT owner_id FROM benchmark_ownership').fetchone()['owner_id']
                conn.execute('DROP TABLE benchmark_ownership')
                conn.execute('CREATE EXTENSION vector')
            # Restore verification creates its own random database; it never
            # mutates or cleans up this explicitly selected operator template.
            try:
                proof=upgrade.verified_backup(cfg,'0.6.11',tmp_path/'template.dump',verification_template=template.db_name)
                assert proof['restore_verified']
            finally:
                with db.connect(template) as conn:
                    conn.execute('CREATE TABLE benchmark_ownership(owner_id text PRIMARY KEY)')
                    conn.execute('INSERT INTO benchmark_ownership VALUES (%s)',(marker,))


def test_prepared_vector_template_restores_without_superuser(tmp_path,monkeypatch):
    """The deployment role cannot create/comment vector; only DBA prepares it."""
    import os,uuid,subprocess,psycopg
    from psycopg import sql
    from agentic_rag import backup
    from agentic_rag.service.upgrade import _restore_verification
    cfg=Config()
    role='rag_verify_'+uuid.uuid4().hex[:12]
    with psycopg.connect(db.dsn(cfg,'owner',dbname='postgres'),autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN CREATEDB NOSUPERUSER NOINHERIT').format(sql.Identifier(role)))
        try:
            with isolated_database(cfg,initialize=False) as template,isolated_database(cfg,initialize=False) as source:
                with db.connect(template) as conn:
                    marker=conn.execute('SELECT owner_id FROM benchmark_ownership').fetchone()['owner_id']
                    conn.execute('DROP TABLE benchmark_ownership');conn.execute('CREATE EXTENSION vector')
                    ext=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
                admin.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(sql.Identifier(template.db_name),sql.Identifier(role)))
                try:
                    with db.connect(source) as conn:
                        conn.execute('CREATE EXTENSION vector')
                        conn.execute('CREATE TABLE synthetic_embedding(id int PRIMARY KEY,value vector(3))')
                        conn.execute("INSERT INTO synthetic_embedding VALUES (1,'[1,2,3]')")
                        conn.execute(sql.SQL('ALTER TABLE synthetic_embedding OWNER TO {}').format(sql.Identifier(role)))
                    dump=tmp_path/'limited.dump'
                    subprocess.run([backup._pg_bin('pg_dump',cfg),'-Fc','--table=synthetic_embedding','-f',str(dump),'-d',db.dsn(source)],check=True,capture_output=True)
                    # Include the actual vector extension TOC entries too.
                    subprocess.run([backup._pg_bin('pg_dump',cfg),'-Fc','--exclude-table=benchmark_ownership','-f',str(dump),'-d',db.dsn(source)],check=True,capture_output=True)
                    with monkeypatch.context() as patch:
                        patch.setenv('PGUSER',role)
                        with isolated_database(cfg,initialize=False,template=template.db_name) as target:
                            _restore_verification(cfg,target,dump,{'identity':{'vector_version':ext}},prepared_template=True)
                            with db.connect(target) as conn:
                                assert conn.execute('SELECT value::text value FROM synthetic_embedding').fetchone()['value']=='[1,2,3]'
                                assert not conn.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()['rolsuper']
                finally:
                    with db.connect(template) as conn:
                        conn.execute('CREATE TABLE benchmark_ownership(owner_id text PRIMARY KEY)')
                        conn.execute('INSERT INTO benchmark_ownership VALUES (%s)',(marker,))
        finally:
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
