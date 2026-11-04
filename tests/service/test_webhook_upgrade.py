"""Real archived028 ->038 interruption, independent restores and old clients."""
from dataclasses import replace
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import tarfile
import uuid

import psycopg
from psycopg import sql

from agentic_rag import db,query_cache,webhooks,webhook_delivery
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from .test_feedback_upgrade import SEED,READ,ROOT,run_code,rows,originals

SOURCE='76692841c73e55f14b3da49ac7babeff2de87953'
WRITE=r'''
from agentic_rag import store
store.try_embed_texts=lambda *a,**k:None
with db.connect(cfg,role='writer') as conn:
 result=store.save_document(conn,cfg,title='Archived028 writer after038',body='Synthetic backwards compatible write',domain='general',dtype='memory',project='/projects/alpha')
print(json.dumps({'id':result.doc_id}))
'''


def archive(tmp_path):
    source=tmp_path/'028';source.mkdir()
    packed=tmp_path/'028.tar'
    with packed.open('wb') as stream:subprocess.run(['git','archive',SOURCE,'agentic_rag','sql','pyproject.toml'],cwd=ROOT,stdout=stream,check=True)
    with tarfile.open(packed) as stream:stream.extractall(source,filter='data')
    assert 'version = "0.6.28"' in (source/'pyproject.toml').read_text()
    return source


def test_archived028_populated_upgrade_interrupt_retry_source_target_restores(tmp_path,monkeypatch):
    assert version('agentic-rag')=='0.6.31'
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    source=archive(tmp_path)
    with isolated_database(Config(),initialize=False) as cfg:
        seeded=run_code(source,cfg,SEED)
        old=run_code(source,cfg,READ)
        assert len(old['local'])==2 and [len(v) for v in old['scoped'].values()]==[1,1]
        before=rows(cfg)
        inventory=upgrade.inventory(cfg,'0.6.28')
        assert len(inventory['migrations'])==37
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM chunks WHERE embedding IS NOT NULL').fetchone()['n']>=3
            assert conn.execute('SELECT count(*) n FROM pins').fetchone()['n']==1
            assert conn.execute("SELECT count(*) n FROM mining_queue WHERE status='pending'").fetchone()['n']==1
        original=upgrade.verified_backup(cfg,'0.6.28',tmp_path/'source.dump')
        run_code(ROOT,cfg,"with db.connect(cfg) as conn:\n applied=db.apply_migrations(conn,db.SQL_DIR,commit=False)\n assert applied==['038_webhooks.sql', '039_metadata_filters.sql']\n os._exit(9)\n",expected=9)
        assert rows(cfg)==before
        assert upgrade.verify_preserved(cfg,original['manifest'])['unchanged']
        migrated=upgrade.local_upgrade(cfg,'0.6.28',tmp_path/'migration.dump',apply=True,writers_stopped=True)
        assert migrated['migrations_applied']==['038_webhooks.sql', '039_metadata_filters.sql'] and migrated['restore_verified']
        assert upgrade.verify_preserved(cfg,original['manifest'])['unchanged']
        assert upgrade.local_upgrade(cfg,'0.6.30',tmp_path/'retry.dump',apply=True,writers_stopped=True)['migrations_applied']==[]
        assert run_code(source,cfg,READ)==old
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT enabled FROM webhook_control').fetchone()['enabled'] is False
        written=run_code(source,cfg,WRITE)
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT id FROM documents WHERE id=%s',(written['id'],)).fetchone()
            assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==0
        originals(before,rows(cfg))
        # Retained pending target metadata is preserved by target backup/restore.
        with db.connect(cfg,role='writer') as conn:
            sub=webhooks.subscribe(conn,cfg,endpoint='https://example.com/hook',domain='general',project='/projects/alpha',
                kinds=['memory.created'],idempotency_key=str(uuid.uuid4()))
        webhook_delivery.capture(cfg,True)
        run_code(source,cfg,WRITE)
        webhook_delivery.capture(cfg,False)
        with db.connect(cfg) as conn:
            pending=conn.execute('SELECT id,event_id,state FROM webhook_deliveries').fetchall()
            assert len(pending)==1 and pending[0]['state']=='pending'
        after=rows(cfg)
        target=upgrade.verified_backup(cfg,'0.6.30',tmp_path/'target.dump')
        for name,proof,expected in [('source',original,['038_webhooks.sql', '039_metadata_filters.sql']),('target',target,[])]:
            with isolated_database(Config(),initialize=False) as restored:
                result=upgrade.restore_target(restored,tmp_path/(name+'.dump'),proof['manifest'],apply=True)
                assert result['restore_verified'] and result['migrations_applied']==expected
                assert upgrade.verify_preserved(restored,proof['manifest'])['unchanged']
                assert run_code(source,restored,READ)==old
                if name=='source':originals(before,rows(restored))
                else:
                    assert rows(restored)==after
                    with db.connect(restored) as conn:
                        assert conn.execute('SELECT id,event_id,state FROM webhook_deliveries').fetchall()==pending
                        assert conn.execute('SELECT enabled FROM webhook_control').fetchone()['enabled'] is False
                    assert webhook_delivery.send_one(restored)=={'state':'idle'}
                # Resume accepts only the exact default seeded off control row.
                if name=='source':assert upgrade.restore_target(restored,tmp_path/'source.dump',original['manifest'],apply=True,resume=True)['migrations_applied']==[]
        refusal=run_code(source,cfg,"from agentic_rag.service import upgrade\ntry: upgrade.inventory(cfg,'0.6.28')\nexcept ValueError as e: print(json.dumps(str(e)))")
        assert refusal=='unsupported_source_schema'
        print('WEBHOOK_UPGRADE_PROOF',json.dumps({'source':SOURCE,'source_schema':37,'target_schema':39,
            'original_tables':len(before),'original_rows':sum(map(len,before.values())),'old_scoped_readers':2,
            'source_restore':True,'target_restore':True,'interrupted_exit':9,'pending_restored':len(pending)},sort_keys=True))


def test_limited_owner_installs038_and_independently_restores(tmp_path,monkeypatch):
    """Prepared vector template only; deployer remains NOSUPERUSER/NOBYPASSRLS."""
    source=archive(tmp_path)
    role='wh_owner_'+uuid.uuid4().hex[:12]
    cfg=Config()
    with psycopg.connect(db.dsn(cfg,dbname='postgres'),autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN CREATEDB NOSUPERUSER NOBYPASSRLS NOINHERIT').format(sql.Identifier(role)))
        try:
            admin.execute(sql.SQL("ALTER ROLE {} SET session_preload_libraries='vector'").format(sql.Identifier(role)))
            with isolated_database(cfg,initialize=False) as template:
                with db.connect(template) as conn:
                    marker=conn.execute('SELECT owner_id FROM benchmark_ownership').fetchone()['owner_id']
                    conn.execute('DROP TABLE benchmark_ownership');conn.execute('CREATE EXTENSION vector')
                try:
                    admin.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(sql.Identifier(template.db_name),sql.Identifier(role)))
                    with monkeypatch.context() as patch:
                        patch.setenv('PGUSER',role)
                        patch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
                        with isolated_database(cfg,initialize=False,template=template.db_name) as limited:
                            run_code(source,limited,SEED)
                            with db.connect(limited) as conn:
                                assert conn.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()=={'rolsuper':False,'rolbypassrls':False}
                            old=upgrade.verified_backup(limited,'0.6.28',tmp_path/'limited-source.dump',verification_template=template.db_name)
                            result=upgrade.local_upgrade(limited,'0.6.28',tmp_path/'limited-upgrade.dump',apply=True,writers_stopped=True,verification_template=template.db_name)
                            assert result['migrations_applied']==['038_webhooks.sql', '039_metadata_filters.sql']
                            assert upgrade.verify_preserved(limited,old['manifest'])['unchanged']
                            target=upgrade.verified_backup(limited,'0.6.30',tmp_path/'limited-target.dump',verification_template=template.db_name)
                            # verified_backup already performs a separate real restore
                            # into a new prepared-template DB under this limited owner.
                            assert target['restore_verified']
                            assert run_code(source,limited,READ)['local']
                            print('WEBHOOK_LIMITED_OWNER_PROOF',json.dumps({'role_superuser':False,'schema':39,'source_restore':old['restore_verified'],'target_restore':target['restore_verified']}))
                finally:
                    with db.connect(template) as conn:
                        conn.execute('CREATE TABLE benchmark_ownership(owner_id text PRIMARY KEY)')
                        conn.execute('INSERT INTO benchmark_ownership VALUES(%s)',(marker,))
        finally:
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
