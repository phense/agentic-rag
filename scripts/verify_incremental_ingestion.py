#!/usr/bin/env python3
"""Owned018→019 rehearsal and paired public ingestion measurements.

Canonical DB access is read-only snapshot/Trading controls. All writes, failures,
process deaths and restores occur on marker-owned databases. Embeddings for public
fixtures use the existing local Ollama; mining extraction is a deterministic fixture.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from agentic_rag import db, embed, jobs, mining, store, worker
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from scripts.verify_contextual_indexing import snapshot, verified_backup
from scripts.verify_entity_identities import assert_originals, inventories, restored, trading
from scripts.verify_filter_aware_search import privileges, table_names

ROOT = Path(__file__).resolve().parents[1]
BASE = '1294d6c44fd02b66715692f12791bfa2fd4c8856'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def config_file(cfg, path):
    path.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[ollama]\nurl="{cfg.ollama_url}"\n')
    path.chmod(0o600)
    return path


def child(source, cfg, temp, args, expected=0):
    config = config_file(cfg, temp / ('config-' + cfg.db_name + '.toml'))
    env = dict(os.environ, PYTHONPATH=str(source), AGENTIC_RAG_CONFIG=str(config), AGENTIC_RAG_HOOKS_DISABLE='1')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_incremental_ingestion.py'),
        '--child', *args], cwd=source, env=env, capture_output=True, text=True, timeout=180)
    if result.returncode != expected:
        raise RuntimeError('Owned child failed: ' + result.stderr[-3000:])
    return json.loads(result.stdout)


@contextmanager
def count_embeddings():
    counters = dict(inputs=0, calls=0, peak_requests=0)
    active = 0
    lock = threading.Lock()
    original = embed._client
    class CounterClient:
        def __init__(self, client): self.client = client
        def get(self, *args, **kwargs): return self.client.get(*args, **kwargs)
        def post(self, url, **kwargs):
            nonlocal active
            with lock:
                counters['inputs'] += len(kwargs['json']['input'])
                counters['calls'] += 1
                active += 1
                counters['peak_requests'] = max(counters['peak_requests'], active)
            try: return self.client.post(url, **kwargs)
            finally:
                with lock: active -= 1
    @contextmanager
    def counted():
        with original() as client: yield CounterClient(client)
    with patch.object(embed, '_client', counted): yield counters


def peak_mib():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024 * 1024 if sys.platform == 'darwin' else 1024), 3)


def extraction(rep, n=8):
    return dict(memories=[dict(title=f'Public item {rep}-{i}',
        body=f'Independent public fixture {rep}-{i}. ' + ('Documented configuration. ' * 12),
        domain='general', edges=[]) for i in range(n)], lessons=[], signals=[],
        contradictions=[], pin_suggestions=[], contradictions_with_pins=[], domain_proposals=[])


def child_main(args):
    cfg = load_config()
    mode, rep = args[0], int(args[1])
    # Never call hosted miners/curation or production log/profile/health paths.
    with tempfile.TemporaryDirectory(prefix='ingestion-child-') as name:
        temp = Path(name)
        worker.LOG_PATH = temp / 'worker.log'
        worker.provider_health.HEALTH_PATH = temp / 'provider-health.json'
        with db.connect(cfg, role='writer') as connection:
            if mode == 'edit':
                body = '\n\n'.join(f'## Part {i}\n\nPublic revision {rep}, section {i}. ' + ('Configuration detail. ' * 44) for i in range(12))
                fields = dict(title=f'Large public guide {rep}', body=body, domain='general', dtype='reference', project='/synthetic/ingestion/a')
                with count_embeddings() as initial:
                    saved = store.save_document(connection, cfg, **fields)
                changed = body.replace('section 6.', 'section 6 revised.')
                with count_embeddings() as measured:
                    start = time.perf_counter()
                    result = store.save_document(connection, cfg, **dict(fields, body=changed), doc_id=saved.doc_id)
                    elapsed = time.perf_counter() - start
                from agentic_rag.chunker import chunk_markdown
                target = chunk_markdown('# ' + fields['title'] + '\n\n' + changed)
                actual = connection.execute('SELECT content FROM chunks WHERE document_id=%s ORDER BY idx', (saved.doc_id,)).fetchall()
                assert [r['content'] for r in actual] == target
                return dict(ms=round(elapsed*1000, 3), **measured, initial_inputs=initial['inputs'],
                    chunks=result.n_chunks, complete_ordered_content=True, peak_mib=peak_mib(),
                    throughput_chunks_s=round(result.n_chunks/elapsed, 3), queue_delay_ms=None)
            transcript = temp / 'session.jsonl'
            ext = extraction(f'{mode}-{rep}')
            transcript.write_text(json.dumps({'uuid':'end', 'message':{'role':'user','content':'Public fixture'}})+'\n')
            session = f'public-{mode}-{rep}'
            if mode in ('backlog', 'crash', 'crash_apply'):
                jobs.enqueue_mine(connection, replace(cfg, mine_debounce_seconds=0), session_id=session,
                    transcript_path=str(transcript), project='/synthetic/ingestion/a')
                if mode == 'backlog':
                    # Three independent accepted jobs, each with8 final documents.
                    for i in range(1,3):
                        jobs.enqueue_mine(connection, replace(cfg, mine_debounce_seconds=0), session_id=session+f'-{i}',
                            transcript_path=str(transcript), project='/synthetic/ingestion/a')
                claims, delay = [], []
                real_claim = worker.claim_next
                def timed_claim(c):
                    job = real_claim(c)
                    if job:
                        claims.append(job['id'])
                        row = c.execute('SELECT extract(epoch FROM now()-created_at)*1000 AS ms FROM mining_queue WHERE id=%s', (job['id'],)).fetchone()
                        delay.append(float(row['ms']))
                    return job
                fixture_outputs = [extraction(f'backlog-{rep}-{i}') for i in range(3)] if mode == 'backlog' else [ext]
                with patch.object(mining, 'run_structured', side_effect=fixture_outputs), patch.object(worker, 'claim_next', timed_claim), count_embeddings() as measured:
                    start = time.perf_counter()
                    if mode in ('crash','crash_apply'):
                        job = worker.claim_next(connection)
                        if mode == 'crash_apply':
                            original_save = store.save_claim
                            def die_after_first(*args, **kwargs):
                                original_save(*args, **kwargs)
                                print(json.dumps(dict(uncommitted_application=True, **measured)), flush=True)
                                os._exit(78)
                            with patch.object(store,'save_claim',die_after_first):
                                worker.process_job(connection,cfg,job)
                            raise AssertionError('must exit during application')
                        result = worker.process_job(connection, cfg, job)
                        assert result.saved == 8
                        # Real process exit after application commit before queue acknowledgement.
                        packet = dict(committed_documents=8, **measured, peak_mib=peak_mib())
                        print(json.dumps(packet), flush=True)
                        os._exit(77)
                    result = worker.drain(connection, cfg)
                    elapsed = time.perf_counter()-start
                assert result == {'done':3, 'failed':0, 'provider_unavailable':0}
                assert claims == sorted(claims) and len(claims)==3
                return dict(ms=round(elapsed*1000,3), **measured, documents=24,
                    ordered_jobs=True, throughput_documents_s=round(24/elapsed,3), peak_mib=peak_mib(),
                    queue_delay_ms=delay)
            if mode in ('retry','retry_apply'):
                # Restart sees the durable batch; no extractor/LLM call is allowed.
                with patch.object(mining, 'run_structured', side_effect=AssertionError('durable extraction must win')), count_embeddings() as measured:
                    start=time.perf_counter()
                    assert worker.requeue_orphans(connection,cfg)==1
                    job=worker.claim_next(connection)
                    result=worker.process_job(connection,cfg,job)
                    worker._complete(connection,job['id'],result)
                    assert result.saved==8
                    docs=connection.execute('SELECT id,title,body FROM documents WHERE provenance->>\'session_id\'=%s ORDER BY slug', (f'public-{"crash_apply" if mode == "retry_apply" else "crash"}-{rep}',)).fetchall()
                    assert len(docs)==8
                    # Independent embedding retry requests the exact committed representations.
                    for doc in docs: store.reembed_document(connection,cfg,str(doc['id']))
                    elapsed=time.perf_counter()-start
                batch=connection.execute('SELECT count(*) AS n FROM mining_batches WHERE session_id=%s', (f'public-{"crash_apply" if mode == "retry_apply" else "crash"}-{rep}',)).fetchone()['n']
                assert batch==1
                return dict(ms=round(elapsed*1000,3),**measured,documents=8,batches=1,
                    no_reextraction=True,no_duplicate_application=True,queue_done=True,
                    peak_mib=peak_mib(),throughput_documents_s=round(8/elapsed,3),queue_delay_ms=None)
            raise ValueError('unknown child mode')


def clients(source, cfg, temp):
    config=config_file(replace(cfg,ollama_url='http://localhost:1'),temp/'client.toml')
    args=['search','Public legacy','--domain','general','--project','/synthetic/ingestion/a','--strategy','lexical','--json']
    def call(directory):
        env=dict(os.environ,PYTHONPATH=str(directory),AGENTIC_RAG_CONFIG=str(config),AGENTIC_RAG_HOOKS_DISABLE='1')
        p=subprocess.run([sys.executable,'-m','agentic_rag.cli',*args],env=env,cwd=directory,capture_output=True,text=True,check=True,timeout=30)
        return json.loads(p.stdout)['results']
    values=[call(p) for p in (source,ROOT,source)]
    assert values[0] and [h['citation'] for h in values[0]]==[h['citation'] for h in values[1]]==[h['citation'] for h in values[2]]
    async def mcp(directory,ro):
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        env=dict(os.environ,PYTHONPATH=str(directory),AGENTIC_RAG_CONFIG=str(config),RAG_READONLY='1' if ro else '0',AGENTIC_RAG_HOOKS_DISABLE='1')
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','agentic_rag.mcp_server'],env=env,cwd=str(directory))) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize();tools=await session.list_tools();names={t.name for t in tools.tools}
                assert len(names)==(10 if ro else 18) and ('memory_save' in names)==(not ro)
                result=await session.call_tool('memory_search',dict(query='Public legacy',domain='general',project='/synthetic/ingestion/a',strategy='lexical'))
                assert not result.isError
                return dict(readonly=ro,tool_count=len(names))
    result=[dict(route=route,**asyncio.run(mcp(directory,ro))) for directory,route in ((source,'source'),(ROOT,'candidate'),(source,'recovery')) for ro in (True,False)]
    return dict(source_candidate_source_citation_parity=True,mcp=result)


def activation_rehearsal(cfg, temp, private, report):
    from scripts.activate_incremental_ingestion import activate
    clone=temp/'activation-clone'
    subprocess.run(['git','clone','--quiet','--no-hardlinks',str(ROOT),str(clone)],check=True,capture_output=True)
    subprocess.run(['git','switch','--detach',BASE],cwd=clone,check=True,capture_output=True)
    target=git('rev-parse','HEAD').decode().strip()
    manifest=private/'synthetic-source018-report.json'
    manifest.write_text(json.dumps(report,indent=2));manifest.chmod(0o600)
    dump=private/'synthetic-source018.dump'
    rejected=[]
    def run(**kwargs):
        return activate(clone,ROOT,kwargs.pop('target',target),cfg=cfg,dump=dump,report=manifest,**kwargs)
    def reject(label, **kwargs):
        try:run(**kwargs)
        except ValueError as exc:rejected.append(dict(case=label,reason=str(exc)))
        else:raise AssertionError('unsafe activation must reject')
        with db.connect(cfg,role='reader') as c:
            assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==18
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=clone).decode().strip()==BASE
    with patch.object(worker,'LOCK_PATH',temp/'owned-worker.lock'):
        reject('abbreviated-target',target=target[:12])
        marker=clone/'.owned-dirty-fixture';marker.write_text('public fixture')
        try:reject('source-drift')
        finally:marker.unlink()
        held=worker.acquire_lock(worker.LOCK_PATH)
        assert held is not None
        try:reject('busy-worker-lock')
        finally:held.close()
        acquire=worker.acquire_lock
        def drift_after_lock(path):
            fd=acquire(path);marker.write_text('post-lock fixture');return fd
        try:
            with patch.object(worker,'acquire_lock',drift_after_lock):reject('post-lock-source-drift')
        finally:marker.unlink()
        first=run()
        assert first['schema']==19
        subprocess.run(['git','switch','--detach',BASE],cwd=clone,check=True,capture_output=True)
        retry=run()  # Actual migration committed before code activation acknowledged.
        recovered=run(recover=True)
        assert recovered['revision']==BASE and recovered['schema']==19
        released=worker.acquire_lock(worker.LOCK_PATH);assert released is not None;released.close()
    return dict(executed_guarded_adoption=first,committed_schema_retry=retry,executed_code_recovery=recovered,
        preflight_rejections=rejected,worker_lock_reacquired=True,source_branch_unchanged=True)


def rehearsal(source, temp, private):
    sourcecfg=Config(ollama_url='http://localhost:1')
    initial=db.init_db
    with patch.object(db,'init_db',lambda c:initial(c,sql_dir=source/'sql')),isolated_database(sourcecfg) as cfg:
        # Source module isolated from candidate gateway imports for real old-client writes.
        config=config_file(cfg,temp/'source.toml')
        env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config),AGENTIC_RAG_HOOKS_DISABLE='1')
        def old(arguments):
            subprocess.run([sys.executable,'-m','agentic_rag.cli',*arguments],cwd=source,env=env,capture_output=True,text=True,check=True,timeout=30)
        old(['save','--title','Public legacy','--body','Preserved original user-a knowledge','--domain','general','--dtype','memory','--project','/synthetic/ingestion/a'])
        old(['domain','add','infrastructure'])
        old(['save','--title','Public other','--body','Independent user-b domain','--domain','infrastructure','--dtype','memory','--project','/synthetic/ingestion/b'])
        with db.connect(cfg,role='writer') as c:
            from agentic_rag import pins
            from agentic_rag.continuity import store as checkpoints
            from agentic_rag.continuity.model import CheckpointSnapshot
            pins.add_pin(c,body='Preserved original rule',scope='/synthetic/ingestion/a',actor='user-a')
            checkpoints.upsert_snapshot(c,CheckpointSnapshot(session_id='public-upgrade',turn_id='t',cursor='c',source='test',trigger='manual',cwd='/synthetic/ingestion/a',project_root='/synthetic/ingestion/a',artifacts=('AGENTS.md',)))
        report=verified_backup(cfg,private/'synthetic-source018.dump');report.pop('dump');report['source_db_name']=cfg.db_name
        with db.connect(cfg) as c:
            tables=table_names(c);before=snapshot(c,tables);grants=privileges(c)
            assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==18
            c.execute((ROOT/'sql/019_embedding_reuse.sql').read_text());c.rollback()
            assert c.execute("SELECT to_regclass('embedding_reuse_cache') AS t").fetchone()['t'] is None
            c.rollback()
            c.rollback()
        activation=activation_rehearsal(cfg,temp,private,report)
        with db.connect(cfg) as c:
            assert db.apply_migrations(c,db.SQL_DIR)==[]
            assert snapshot(c,tables)==before
            assert [r for r in privileges(c) if r['table_name']!='embedding_reuse_cache']==grants
        observed=clients(source,cfg,temp)
        final=verified_backup(cfg,private/'synthetic-target019.dump');final.pop('dump')
    return dict(source_schema=18,target_schema=19,strict_source_restore=report,strict_target_restore=final,
        interrupted_ddl_rollback=True,retry_noop=True,original_rows_grants_preserved=True,clients=observed,activation=activation)


def private_recovery(private):
    sourcecfg=load_config()
    report=verified_backup(sourcecfg,private/'production-source018.dump')
    report['source_db_name']=sourcecfg.db_name
    (private/'production-source018-report.json').write_text(json.dumps(report,indent=2))
    (private/'production-source018-report.json').chmod(0o600)
    with restored(Config(ollama_url='http://localhost:1'),private/'production-source018.dump') as cfg:
        with db.connect(cfg) as c:
            tables=sorted(report['tables']);assert snapshot(c,tables)==report['tables']
            assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==18
            before=snapshot(c,tables);grants=privileges(c)
            c.execute((ROOT/'sql/019_embedding_reuse.sql').read_text());c.rollback()
            assert db.apply_migrations(c,db.SQL_DIR)==['019_embedding_reuse.sql']
            assert db.apply_migrations(c,db.SQL_DIR)==[]
            # Schema ledger adds019; every other source row is exactly unchanged.
            protected=[t for t in tables if t!='schema_migrations']
            assert snapshot(c,protected)=={t:before[t] for t in protected}
            assert [r for r in privileges(c) if r['table_name']!='embedding_reuse_cache']==grants
    return dict(strict_restore=True,source_schema=18,target_schema=19,interrupted_ddl_retry=True,
        original_rows_grants_preserved=True,original_counts={t:d['rows'] for t,d in report['tables'].items()},
        canonical_application_writes=0,provider_calls=0,owned_cleanup='verified')


def stat(rows):
    values=[r['ms'] for r in rows]
    return dict(p50_ms=round(statistics.median(values),3),p95_ms=round(sorted(values)[math.ceil(.95*len(values))-1],3),
        raw=rows,embedding_inputs=sum(r['inputs'] for r in rows),peak_mib_max=max(r['peak_mib'] for r in rows))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child',nargs='+');parser.add_argument('--output',type=Path)
    parser.add_argument('--private-dir',type=Path);parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--production-copy',action='store_true');parser.add_argument('--trading',action='store_true')
    args=parser.parse_args()
    if args.child:
        print(json.dumps(child_main(args.child)),flush=True);return
    if args.output is None or args.private_dir is None or not 1<=args.repeats<=30:parser.error('output/private-dir and1–30 repeats required')
    args.private_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    args.private_dir.chmod(0o700)
    cfg=load_config()
    endpoint=urlsplit(cfg.ollama_url)
    if endpoint.hostname not in ('localhost','127.0.0.1','::1') or endpoint.username or endpoint.password or endpoint.query:
        raise ValueError('Public measurement requires the existing local Ollama endpoint')
    result=dict(source_revision=BASE,candidate_revision=git('rev-parse','HEAD').decode().strip(),
        generated_at=datetime.now(timezone.utc).isoformat(),repetitions=args.repeats,
        embedding_model=cfg.embed_model,model_digest=None,hosted_provider_calls=0,production_application_writes=0,
        limits='Controlled public fixtures. Whole child peak RSS includes interpreter/client startup. Warm process/DB/OS caches are not flushed. Mining extractor is deterministic; embedding HTTP is real. No universal speedup claimed.')
    paths=[p for directory in ('agentic_rag','sql','scripts') for p in (ROOT/directory).rglob('*') if p.suffix in ('.py','.sql','.mjs') and '__pycache__' not in p.parts]
    frozen={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in paths}
    from agentic_rag.query_cache import model_digest
    result['model_digest']=model_digest(cfg)
    if result['model_digest'] is None:raise ValueError('Known local model required for measurement')
    with tempfile.TemporaryDirectory(prefix='incremental-rehearsal-') as name:
        temp=Path(name);source=temp/'source';source.mkdir()
        subprocess.run(['tar','-xf','-','-C',str(source)],input=git('archive',BASE),check=True)
        result['compatibility']=rehearsal(source,temp,args.private_dir)
        initial=db.init_db
        with patch.object(db,'init_db',lambda c:initial(c,sql_dir=source/'sql')),isolated_database(cfg) as before, isolated_database(cfg) as after:
            with db.connect(after) as c:db.apply_migrations(c,db.SQL_DIR)
            interrupted=child(ROOT,after,temp,['crash_apply','999'],expected=78)
            with db.connect(after,role='reader') as c:
                assert c.execute("SELECT count(*) n FROM documents WHERE provenance->>'session_id'='public-crash_apply-999'").fetchone()['n']==0
                assert c.execute("SELECT result FROM mining_batches WHERE session_id='public-crash_apply-999'").fetchone()['result'] is None
            result['interrupted_application']=dict(interrupted,retained_extraction=True,
                resumed=child(ROOT,after,temp,['retry_apply','999']))
            scenarios={name:{r:[] for r in ('before','after')} for name in ('small-edit','interrupted-retry','independent-backlog')}
            for rep in range(args.repeats):
                for route in (('before','after') if rep%2==0 else ('after','before')):
                    directory,owned=(source,before) if route=='before' else (ROOT,after)
                    scenarios['small-edit'][route].append(child(directory,owned,temp,['edit',str(rep)]))
                    crash=child(directory,owned,temp,['crash',str(rep)],expected=77)
                    retry=child(directory,owned,temp,['retry',str(rep)])
                    retry['committed_before_crash']=crash
                    scenarios['interrupted-retry'][route].append(retry)
                    scenarios['independent-backlog'][route].append(child(directory,owned,temp,['backlog',str(rep)]))
                print(json.dumps({'finished_pair':rep+1}),flush=True)
            result['scenarios']={name:{r:stat(rows) for r,rows in routes.items()} for name,routes in scenarios.items()}
        if args.production_copy:result['populated_private_recovery']=private_recovery(args.private_dir)
        if args.trading:result['trading_reader']=trading(args.repeats)
    assert {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in paths}==frozen
    result['measured_files_sha256']=frozen;result['measured_hashes_unchanged']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,default=str)+'\n')


if __name__=='__main__':main()
