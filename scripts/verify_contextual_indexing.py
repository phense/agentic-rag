#!/usr/bin/env python3
"""Rehearse014→015 and measure source-faithful retrieval on owned synthetic data.

Run with PYTHONPATH pointing to this checkout and its supported Python environment.
No production writes, hosted provider calls, service operations or caller-selected drop target.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import io
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from psycopg import sql

from agentic_rag import backup, cli, db, domains, jobs, mcp_server, pins, query_cache, search, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot

ROOT = Path(__file__).resolve().parents[1]
BASE = '499c656d7fcb1cf1d1938f7d2404b4043d9fb0b0'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def previous(name, directory):
    content = git('show', f'{BASE}:agentic_rag/{name}.py')
    file = directory / f'{name}.py'
    file.write_bytes(content)
    spec = importlib.util.spec_from_file_location(f'agentic_rag._context_before_{name}', file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, sha256(content).hexdigest()


def snapshot(connection, tables=None):
    if tables is None:
        tables = [r['tablename'] for r in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename NOT IN ('benchmark_ownership','schema_migrations','chunk_contexts') ORDER BY tablename")]
    result = {}
    for table in tables:
        rows = connection.execute(sql.SQL('SELECT to_jsonb(t)::text AS row FROM {} t ORDER BY to_jsonb(t)::text')
            .format(sql.Identifier(table))).fetchall()
        encoded = json.dumps([r['row'] for r in rows], separators=(',', ':')).encode()
        result[table] = {'rows': len(rows), 'sha256': sha256(encoded).hexdigest()}
    return result


def citation_check(connection, hits):
    for hit in hits:
        source = connection.execute('SELECT content,document_id FROM chunks WHERE id=%s',(hit.chunk_id,)).fetchone()
        assert source and str(source['document_id']) == hit.document_id
        assert source['content'][hit.snippet_start:hit.snippet_end] == hit.snippet
        assert hit.citation == f'{hit.document_id}#{hit.chunk_id}:{hit.snippet_start}-{hit.snippet_end}'


def index_cli(cfg, selector, limit=1):
    output = io.StringIO()
    with patch.object(cli, 'load_config', lambda:cfg), redirect_stdout(output):
        rc = cli.main(['save','--index-context',selector,'--index-limit',str(limit)])
    assert rc == 0
    return json.loads(output.getvalue())


def fixtures():
    return [
        {'id':'service-port','title':'Orion telemetry', 'query':'Orion telemetry listener port',
         'body':'Deployment overview.\n\n'+('Installation background. '*185)+'\n\nThe listener uses port 8766.\n',
         'fact':'The listener uses port 8766.'},
        {'id':'dated-unit','title':'Cedar annual operating report', 'query':'Cedar annual report 2025 revenue USD millions',
         'body':'Financial reporting overview.\n\n'+('Accounting background. '*210)+'\n\nFor 2025, revenue was 184.2 USD millions.\n',
         'fact':'For 2025, revenue was 184.2 USD millions.'},
        {'id':'late-section','title':'Vega analytics', 'query':'Vega analytics recovery checkpoint',
         'body':'Operator guide overview.\n\n'+('Installation background. '*185)+'\n\n## Disaster recovery\n\n'+
             ('Recovery preparation. '*195)+'\n\nRestore the checkpoint from the verified backup.\n',
         'fact':'Restore the checkpoint from the verified backup.'},
    ]


def stats(values):
    return {'p50_ms':round(statistics.median(values),3),
            'p95_ms':round(sorted(values)[math.ceil(.95*len(values))-1],3)}


def verified_backup(cfg,dump):
    """Capture dump and inventories in one exported read-only snapshot, restore strictly.

    Existing backup maintenance is only a smoke test. This verifies every source
    table/row and the three application roles' table privileges on an owned target.
    Source writers may continue; dump and inventory share one consistent snapshot.
    """
    dump=Path(dump)
    dump.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with dump.open('x'):pass  # Refuse to replace an existing backup.
    dump.chmod(0o600)
    with db.connect(cfg,role='owner') as source:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        tables=[r['tablename'] for r in source.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename!='benchmark_ownership' ORDER BY tablename")]
        expected=snapshot(source,tables)
        def grants(connection):
            return {role:{table:{privilege:connection.execute('SELECT has_table_privilege(%s,%s,%s) allowed',
                (role,'public.'+table,privilege)).fetchone()['allowed'] for privilege in ('SELECT','INSERT','UPDATE','DELETE')}
                for table in tables} for role in ('rag_reader','rag_writer','rag_admin')}
        privileges=grants(source)
        exported=source.execute('SELECT pg_export_snapshot() snapshot').fetchone()['snapshot']
        backup._run_pg([backup._pg_bin('pg_dump',cfg),'-Fc','--snapshot='+exported,
            '--exclude-table=public.benchmark_ownership','-f',str(dump),'-d',db.dsn(cfg)])
        # Skip schema initialization ONLY for this owned restore target; preserving
        # its creator's ownership marker still allows verified automatic cleanup.
        with patch.object(db,'init_db',lambda config:[]),isolated_database(cfg) as target:
            backup._run_pg([backup._pg_bin('pg_restore',cfg),'--single-transaction','--exit-on-error',
                '-d',db.dsn(target),str(dump)])
            with db.connect(target,role='owner') as restored:
                actual_tables=[r['tablename'] for r in restored.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename!='benchmark_ownership' ORDER BY tablename")]
                assert actual_tables==tables and snapshot(restored,tables)==expected
                assert grants(restored)==privileges
        source.rollback()
    return {'strict_restore_exit_zero':True,'all_public_table_rows_match':True,'application_table_privileges_match':True,
            'owned_database_cleanup':'verified','consistent_exported_snapshot':True,'dump_sha256':sha256(dump.read_bytes()).hexdigest(),
            'tables':expected,'dump':str(dump)}


def measure(connection,cfg,old_search,cases,repeats):
    results = {}
    for case in cases:
        routes = {}
        for strategy in ('lexical','auto'):
            samples = {'before':[], 'after':[]}
            records = {'before':[], 'after':[]}
            def run(route):
                fn = old_search.search if route == 'before' else search.search
                started = time.perf_counter()
                hits,warnings = fn(connection,cfg,case['query'],strategy=strategy,k=3,
                    project='/synthetic/a',domain='general',rerank_mode='off')
                elapsed = (time.perf_counter()-started)*1000
                citation_check(connection,hits)
                # Same k=3,1200-source-character presentation cap on both paths.
                success = any(hit.document_id==case['document_id'] and case['fact'] in hit.snippet for hit in hits)
                return elapsed,{'quality':success,'citations':len(hits),'source_chars':sum(len(h.snippet) for h in hits),
                    'warnings':warnings,'top_citation':hits[0].citation if hits else None}
            first = {route:run(route)[0] for route in ('before','after')}
            for n in range(repeats):
                for route in (('before','after') if n%2==0 else ('after','before')):
                    elapsed,row = run(route)
                    samples[route].append(elapsed);records[route].append(row)
            routes[strategy] = {route:dict(stats(samples[route]),first_call_ms=round(first[route],3),
                relevant_original_fact=sum(r['quality'] for r in records[route]),denominator=repeats,
                mean_source_chars=round(statistics.mean(r['source_chars'] for r in records[route]),1),
                raw_ms=[round(t,3) for t in samples[route]],raw_outcomes=records[route]) for route in samples}
        results[case['id']] = routes
    return results


def verify(repeats):
    cfg = Config()  # Default local backend; never load or alter production settings.
    model=query_cache.model_digest(cfg)
    if model is None:raise RuntimeError('verified local model identity required for measurement')
    with tempfile.TemporaryDirectory(prefix='rag-context-') as name:
        private = Path(name);private.chmod(0o700)
        old_store,store_hash = previous('store',private)
        old_search,search_hash = previous('search',private)
        source_sql = private/'sql014';source_sql.mkdir()
        for path in sorted((ROOT/'sql').glob('*.sql')):
            if path.name < '015':(source_sql/path.name).write_bytes(git('show',f'{BASE}:sql/{path.name}'))
        initialize = db.init_db
        # Real migrations001–014, selected at the initialization boundary only.
        with patch.object(db,'init_db',lambda config:initialize(config,sql_dir=source_sql)), isolated_database(cfg) as isolated:
            with db.connect(isolated,role='writer') as writer:
                domains.add_domain(writer,'other','Second synthetic domain',actor='user-b')
                cases=fixtures()
                for case in cases:
                    started=time.perf_counter()
                    saved=old_store.save_document(writer,isolated,title=case['title'],body=case['body'],
                        dtype='reference',domain='general',project='/synthetic/a',actor='cli' if case['id']=='dated-unit' else 'user-a',
                        edges=[old_store.EdgeSpec('references',cases[0]['slug'],evidence='Synthetic operations reference')] if case['id']=='dated-unit' else None)
                    assert not saved.warnings
                    case.update(document_id=saved.doc_id,slug=saved.slug,
                        baseline_save_ms=round((time.perf_counter()-started)*1000,3),chunks=saved.n_chunks)
                # Eligible distractors preserve all query terms but have the wrong numerical/operational fact.
                for case in cases:
                    old_store.save_document(writer,isolated,title='Old '+case['title'],
                        body=case['query']+'\nAn older synthetic fact; consult the current reference.',
                        dtype='reference',domain='general',project='/synthetic/a',actor='user-a')
                foreign=old_store.save_document(writer,isolated,title='Orion telemetry foreign user',
                    body='The listener uses port 9888.',dtype='reference',domain='other',project='/synthetic/b',actor='user-b')
                recovery=store.save_document(writer,isolated,title='Recovery telemetry',body=cases[0]['body'],
                    dtype='reference',domain='general',project='/synthetic/a',actor='user-a')
                assert not recovery.warnings  # New audited writer on actual014.
                for value,date,extra in [('7000','2026-01-01T00:00:00Z',{}),('8000','2026-02-01T00:00:00Z',{'relation':'replacement','expires_at':'2026-03-01T00:00:00Z'})]:
                    old_store.save_assertion(writer,isolated,entity='Synthetic sensor',attribute='listener',value=value,
                        event_at=date,evidence={'source_id':'sensor-'+value,'role':'user','quote':'Synthetic sensor port '+value,'event_at':date},
                        project='/synthetic/b',domain='other',actor='cli',**extra)
                old_store.save_claim(writer,isolated,title='Synthetic TLS evidence',body='Synthetic sensor uses TLS.',
                    domain='other',dtype='memory',project='/synthetic/b',claim_kind='stated',actor='user-b',
                    evidence=[{'namespace':'session:context-rehearsal','source_id':'tls-1','role':'user',
                        'quote':'Synthetic sensor uses TLS.','complete':True,'timestamp':'2026-01-01T00:00:00Z'}])
                pins.add_pin(writer,document_id=cases[0]['document_id'],scope='/synthetic/a',actor='user-a')
                checkpoints.upsert_snapshot(writer,CheckpointSnapshot(session_id='context-rehearsal',
                    turn_id='t',cursor='c',source='test',trigger='manual',cwd='/synthetic/a',project_root='/synthetic/a',artifacts=('AGENTS.md',)))
                jobs.enqueue_curate(writer,reason='Retained synthetic queue')
                old_store.refresh_profile(writer,isolated,project='/synthetic/a',actor='cli')
            with db.connect(isolated) as owner:
                before=snapshot(owner)
                assert len(owner.execute('SELECT * FROM schema_migrations').fetchall())==14
                roles=owner.execute("SELECT rolname,rolsuper,rolcanlogin FROM pg_roles WHERE rolname IN ('rag_reader','rag_writer','rag_admin') ORDER BY rolname").fetchall()
                # New code must operate on an existing014 schema before deployment.
                hits,_=search.search(owner,isolated,cases[0]['query'],strategy='lexical',rerank_mode='off')
                citation_check(owner,hits)
                assert not owner.execute("SELECT to_regclass('public.chunk_contexts') present").fetchone()['present']
                owner.rollback()
                dump=private/'014.dump';dump.touch(mode=0o600)
                backup._run_pg([backup._pg_bin('pg_dump',cfg),'-Fc','--exclude-table=public.benchmark_ownership',
                    '-f',str(dump),'-d',db.dsn(isolated)])
                strict_backup=verified_backup(isolated,private/'strict014.dump')
                # Simulated interruption before migration commit; real015 DDL must fully disappear.
                owner.execute((ROOT/'sql/015_contextual_chunks.sql').read_text());owner.rollback()
                assert not owner.execute("SELECT to_regclass('public.chunk_contexts') present").fetchone()['present']
                owner.rollback()
                applied=db.apply_migrations(owner,ROOT/'sql')
                assert applied==['015_contextual_chunks.sql'] and db.apply_migrations(owner,ROOT/'sql')==[]
                assert snapshot(owner)==before
                assert owner.execute("SELECT rolname,rolsuper,rolcanlogin FROM pg_roles WHERE rolname IN ('rag_reader','rag_writer','rag_admin') ORDER BY rolname").fetchall()==roles
                owner.rollback()
                indexing=[]
                for case in cases:
                    started=time.perf_counter();calls=[]
                    while True:
                        call=index_cli(isolated,case['slug']);calls.append(call)
                        if call['remaining_chunks']==0:break
                        if call['warnings']:raise RuntimeError('local context inference unavailable')
                    assert index_cli(isolated,case['slug'])['indexed_chunks']==0
                    indexing.append({'case':case['id'],'chunks':case['chunks'],'batch_limit':1,
                        'calls':len(calls),'elapsed_ms':round((time.perf_counter()-started)*1000,3),
                        'baseline_save_ms':case['baseline_save_ms']})
                after=snapshot(owner)
                assert {t:v for t,v in after.items() if t!='audit_log'}=={t:v for t,v in before.items() if t!='audit_log'}
                assert after['audit_log']['rows']==before['audit_log']['rows']+sum(c['chunks'] for c in cases)
                # Fingerprint the unchanged historical subset separately from legitimate new index audit rows.
                rows=owner.execute("SELECT to_jsonb(t)::text AS row FROM audit_log t WHERE op!='index_context' ORDER BY to_jsonb(t)::text").fetchall()
                assert sha256(json.dumps([r['row'] for r in rows],separators=(',',':')).encode()).hexdigest()==before['audit_log']['sha256']
                # Every existing audit row remains byte-for-byte; appended index operations only.
                audits=owner.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']
                assert audits==sum(c['chunks'] for c in cases)
                measurements=measure(owner,isolated,old_search,cases,repeats)
                assert query_cache.model_digest(isolated)==model
                assert snapshot(owner)==after
                owner.rollback()
                def mixed_read(fn):
                    with db.connect(isolated,role='reader') as reader:
                        reader.execute('SET TRANSACTION READ ONLY')
                        hits,_=fn(reader,isolated,'port 8766',project='/synthetic/a',domain='general',strategy='lexical',rerank_mode='off')
                        citation_check(reader,hits)
                        return [h.citation for h in hits]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    before_read=pool.submit(mixed_read,old_search.search)
                    after_read=pool.submit(mixed_read,search.search)
                    assert before_read.result(timeout=5)==after_read.result(timeout=5)
                with patch.object(mcp_server,'load_config',lambda:isolated),patch.dict('os.environ',{'RAG_READONLY':'1'}):
                    hits=mcp_server.memory_search('Orion telemetry listener port',project='/synthetic/a',domain='general',strategy='lexical',rerank='off',k=3)['results']
                    assert any(h['document_id']==cases[0]['document_id'] and 'port 8766' in h['snippet'] for h in hits)
                # Actual old writer corrects source/scope after partial derived progress.
                partial=index_cli(isolated,recovery.slug)
                assert partial['indexed_chunks']==1 and partial['remaining_chunks']>0
                correction={'title':'Recovery telemetry','query':'Recovery telemetry listener port','document_id':recovery.doc_id,'slug':recovery.slug}
                with db.connect(isolated,role='writer') as writer:
                    old_store.save_document(writer,isolated,title=correction['title'],body='The listener uses port 8767.',
                        dtype='reference',domain='general',doc_id=correction['document_id'],project='/synthetic/b',actor='user-b')
                assert owner.execute('SELECT count(*) n FROM chunk_contexts x JOIN chunks c ON c.id=x.chunk_id WHERE c.document_id=%s',
                    (correction['document_id'],)).fetchone()['n']==0
                owner.rollback();index_cli(isolated,correction['slug'])
                hits,_=search.search(owner,isolated,correction['query'],project='/synthetic/a',domain='general',strategy='lexical',rerank_mode='off')
                assert correction['document_id'] not in {h.document_id for h in hits}
                hits,_=search.search(owner,isolated,'Recovery telemetry port 8767',project='/synthetic/b',domain='general',strategy='lexical',rerank_mode='off')
                assert any(h.document_id==correction['document_id'] and '8767' in h.snippet for h in hits)
                citation_check(owner,hits)
                old_hits,_=old_search.search(owner,isolated,'port 8767',project='/synthetic/b',strategy='lexical',rerank_mode='off')
                assert any(h.document_id==correction['document_id'] for h in old_hits)
                citation_check(owner,old_hits);owner.rollback()
                # Old and new writers coexist; fresh new save creates lexical context without extra inference.
                with db.connect(isolated,role='writer') as writer:
                    store.save_document(writer,isolated,title='Updated foreign',body='port 9889',dtype='reference',domain='other',
                        doc_id=foreign.doc_id,actor='user-b')
                storage=dict(owner.execute('SELECT count(*) chunks,coalesce(sum(char_length(context)),0) prefix_chars FROM chunk_contexts').fetchone())
                owner.rollback()
                # Restore into another owned source014 database. Restoring014 OVER015
                # is unsupported: the added FK prevents dropping the old chunk PK.
                # Excluding the laboratory ownership marker preserves cleanup authority.
                with isolated_database(cfg) as restored:
                    backup._run_pg([backup._pg_bin('pg_restore',cfg),'--clean','--if-exists','--single-transaction',
                        '-d',db.dsn(restored),str(dump)])
                    with db.connect(restored) as recovered:
                        assert snapshot(recovered)==before
                        assert len(recovered.execute('SELECT * FROM schema_migrations').fetchall())==14
                        assert not recovered.execute("SELECT to_regclass('public.chunk_contexts') present").fetchone()['present']
                        recovered.rollback()
                        assert db.apply_migrations(recovered,ROOT/'sql')==['015_contextual_chunks.sql']
                        assert snapshot(recovered)==before
                result={'timestamp':datetime.now(timezone.utc).isoformat(),'source_revision':BASE,
                    'baseline_files_sha256':{'store':store_hash,'search':search_hash},
                    'candidate_head':git('rev-parse','HEAD').decode().strip(),
                    'candidate_files_sha256':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in
                        [ROOT/'agentic_rag'/f'{n}.py' for n in ('contextual','store','search','cli','mcp_server')]+[ROOT/'sql/015_contextual_chunks.sql',Path(__file__)]},
                    'dataset':'11 synthetic representative documents, including replaced/expired assertions and a sourced claim;2 writer actors,2 projects,2 domains; no production data',
                    'embedding_model':cfg.embed_model,'model_digest':model,'embed_dim':cfg.embed_dim,'backend':'local Ollama loopback11434',
                    'method':'alternating paired calls, no reranker/query cache, real local bge-m3; first calls separate; k3/source1200 chars',
                    'repetitions':repeats,'canonical_before':before,'canonical_after_indexing':after,
                    'source_rows_preserved':True,'migration_interrupt_retry_idempotent':True,'roles_unchanged':True,
                    'concurrent_actual_old_and_new_readers':True,
                    'reader_mcp_original_citation':True,'actual_old_writer_correction_resume':True,'actual_old_reader_code_rollback':True,
                    'verified014_backup_restore_and_reupgrade':True,'index_cost':indexing,'cases':measurements,
                    'strict_operator_backup':{k:v for k,v in strict_backup.items() if k!='dump'},
                    'context_storage':storage}
        result['owned_database_cleanup']='verified'
        return result


def trading_readonly(project,repeats):
    """Verify014 fallback on live read-only workload; export no queries or content."""
    from agentic_rag.scope import selection
    cfg=load_config()
    with tempfile.TemporaryDirectory(prefix='rag-context-reader-') as name:
        old,_=previous('search',Path(name))
        with db.connect(cfg,role='reader') as reader:
            reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            assert reader.execute("SELECT to_regclass('public.chunk_contexts') present").fetchone()['present'] is None
            row=reader.execute("SELECT d.slug FROM documents d JOIN chunks c ON c.document_id=d.id "
                "WHERE d.status='active' AND assertion_eligible(d.id,now(),false) AND d.project_scope=ANY(%s) ORDER BY d.slug,c.idx LIMIT 1",
                (selection(project),)).fetchone()
            assert row
            counts=reader.execute('SELECT (SELECT count(*) FROM documents) documents,(SELECT count(*) FROM chunks) chunks').fetchone()
            at=datetime.now(timezone.utc).isoformat()
            cases=[('eligible-document',row['slug'],'auto',None),
                ('scoped-lexical','newsletter authentication','lexical',None),
                ('scoped-question','Wie werden OAuth-Probleme bei der Newsletter-Erstellung behandelt?','auto','programming')]
            result={'timestamp':at,'source_revision':BASE,'candidate_search_sha256':sha256((ROOT/'agentic_rag/search.py').read_bytes()).hexdigest(),
                'method':'rag_reader,repeatable-read read-only,schema014,no reranker/query cache;original citations validated;no exported queries/content',
                'production_writes':0,'context_index_available':False,'store_counts':counts,'repetitions':repeats,'cases':{}}
            for label,query,strategy,domain in cases:
                samples={'before':[],'after':[]};equal=0;valid={'before':0,'after':0};first={}
                for n in range(repeats+1):
                    signatures={}
                    for route in (('before','after') if n%2==0 else ('after','before')):
                        fn=old.search if route=='before' else search.search
                        started=time.perf_counter()
                        hits,warnings=fn(reader,cfg,query,strategy=strategy,domain=domain,project=project,as_of=at,rerank_mode='off')
                        elapsed=(time.perf_counter()-started)*1000
                        if warnings:raise RuntimeError('inference unavailable; live measurement invalid')
                        citation_check(reader,hits)
                        signatures[route]=[h.citation for h in hits]
                        if n==0:first[route]=round(elapsed,3)
                        else:samples[route].append(elapsed);valid[route]+=len(hits)
                    if n and signatures['before']==signatures['after']:equal+=1
                result['cases'][label]={'equal_citation_lists':equal,'routes':{route:dict(stats(values),
                    first_call_ms=first[route],validated_citations=valid[route],raw_ms=[round(v,3) for v in values]) for route,values in samples.items()}}
            reader.rollback()
            return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--trading-readonly',action='store_true',help='only measure actual014 fallback on authorized live workload')
    parser.add_argument('--project',type=str)
    parser.add_argument('--verified-backup',type=Path,help='capture a new private dump from configured store and verify every row on owned restore target')
    args=parser.parse_args()
    if not 1<=args.repeats<=100:parser.error('repeats must be1..100')
    if args.trading_readonly and args.verified_backup:parser.error('choose one operation')
    if args.trading_readonly and (args.project is None or not Path(args.project).is_absolute()):parser.error('read-only workload needs an absolute --project')
    if args.verified_backup:result=verified_backup(load_config(),args.verified_backup)
    else:result=trading_readonly(args.project,args.repeats) if args.trading_readonly else verify(args.repeats)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ('source_rows_preserved','verified014_backup_restore_and_reupgrade','owned_database_cleanup','production_writes','context_index_available','strict_restore_exit_zero','all_public_table_rows_match') if key in result}))


if __name__=='__main__':main()
