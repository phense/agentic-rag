#!/usr/bin/env python3
"""Rehearse015→016 on owned copies; benchmark filter-aware recall without live writes.

Synthetic vector workloads are deterministic planner tests, not model-quality claims.
Trading measurements use a strict, private snapshot copy and real local embeddings.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import urlparse

from agentic_rag import backup, db, domains, embed, jobs, pins, query_cache, search, store, vector_plan
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot
from scripts.verify_contextual_indexing import citation_check, snapshot, stats, verified_backup

ROOT=Path(__file__).resolve().parents[1]
BASE='99514fe012666e67dff02ae2419e05a6c876d1f9'
QUERY=[1.0]+[0.0]*1023
MODEL='synthetic-filter-planner-v1'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def previous(name,directory):
    content=git('show',f'{BASE}:agentic_rag/{name}.py')
    file=directory/f'{name}.py';file.write_bytes(content)
    spec=importlib.util.spec_from_file_location(f'agentic_rag._filter_before_{name}',file)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module,sha256(content).hexdigest()


def table_names(conn):
    return [r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('benchmark_ownership','schema_migrations') ORDER BY tablename")]


def privileges(conn):
    return conn.execute("SELECT table_name,grantee,privilege_type FROM information_schema.role_table_grants WHERE table_schema='public' ORDER BY table_name,grantee,privilege_type").fetchall()


def oracle(conn,vector,domain,scopes,at,history=False,model=None,context=False):
    # Complete eligible materialization, independent of the implementation helper.
    # Stable document diversity then top50, matching the fixed vector fusion budget.
    if context:
        join='JOIN chunk_contexts x ON x.chunk_id=c.id'
        column='x.embedding'
        checks="AND x.version=1 AND x.model_digest=%s AND x.source_hash=chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)"
    else:join='';column='c.embedding';checks=''
    args=[domain,domain,scopes,scopes,at,history]
    if context:args.append(model)
    args.append(vector)
    rows=conn.execute(f"""WITH eligible AS MATERIALIZED (
      SELECT c.id,d.id doc_id,d.slug,c.idx,{column} embedding
      FROM chunks c JOIN documents d ON d.id=c.document_id {join}
      WHERE d.status='active' AND (%s::text IS NULL OR d.domain=%s)
        AND (%s::text[] IS NULL OR d.project_scope=ANY(%s))
        AND assertion_eligible(d.id,%s,%s) AND {column} IS NOT NULL AND l2_norm({column})>0 {checks}
    ), distances AS (SELECT e.*,embedding <=> %s::halfvec metric FROM eligible e),
    diverse AS (SELECT t.*,row_number() OVER(PARTITION BY doc_id ORDER BY metric,idx,id) n FROM distances t)
    SELECT id,doc_id FROM diverse WHERE n<=2 ORDER BY metric,slug,idx,id LIMIT 50""",tuple(args)).fetchall()
    return rows


def eligible_count(conn,domain,scopes,at):
    return conn.execute("""SELECT count(*) n FROM chunks c JOIN documents d ON d.id=c.document_id
       WHERE d.status='active' AND (%s::text IS NULL OR d.domain=%s)
       AND (%s::text[] IS NULL OR d.project_scope=ANY(%s))
       AND assertion_eligible(d.id,%s,false) AND c.embedding IS NOT NULL AND l2_norm(c.embedding)>0""",
       (domain,domain,scopes,scopes,at)).fetchone()['n']


def candidate_comparison(conn,cases,repeats):
    results={}
    vector=embed.vec_literal(QUERY)
    for case in cases:
        scopes=[case['project'],'global'];at=case.get('as_of','2026-01-15T00:00:00Z');domain=case.get('domain')
        truth=oracle(conn,vector,domain,scopes,at)
        expected={str(r['id']) for r in truth}
        args=('quasar',vector,domain,150,scopes,at,False,None)
        samples={'before':[],'after':[]};recalls={'before':[],'after':[]};counts={'before':[],'after':[]};doc_recalls={'before':[],'after':[]};first={}
        for n in range(repeats+1):
            for route in (('before','after') if n%2==0 else ('after','before')):
                start=time.perf_counter()
                if route=='before':
                    rows=conn.execute('SELECT * FROM hybrid_search_contextual(%s,%s::halfvec,%s,%s,%s,%s,%s,%s)',args).fetchall()
                else:rows=vector_plan.candidates(conn,args)
                elapsed=(time.perf_counter()-start)*1000
                found={str(r['chunk_id']) for r in rows}
                if n==0:first[route]=round(elapsed,3)
                else:
                    samples[route].append(elapsed);recalls[route].append(len(found&expected)/len(expected) if expected else 1)
                    found_docs={str(r['document_id']) for r in rows};true_docs={str(r['doc_id']) for r in truth}
                    counts[route].append(len(found_docs));doc_recalls[route].append(len(found_docs&true_docs)/len(true_docs) if true_docs else 1)
        results[case['id']]={'eligible_chunks':eligible_count(conn,domain,scopes,at),'oracle_chunks':len(expected),
          'oracle_documents':len({r['doc_id'] for r in truth}),'routes':{
          route:dict(stats(values),first_call_ms=first[route],recall_fraction=recalls[route],document_recall_fraction=doc_recalls[route],documents=counts[route],raw_ms=[round(v,3) for v in values]) for route,values in samples.items()}}
    return results


def pool_comparison(conn,repeats):
    vector=embed.vec_literal(QUERY);at='2026-01-15T00:00:00Z';scopes=['/synthetic/filter-pool']
    truth=oracle(conn,vector,'general',scopes,at);expected={str(r['id']) for r in truth}
    results={}
    with conn.transaction():
        # Experimental helper parameters force ANN for the same finite eligible set.
        # No persisted settings; planner caps remain the same for all pools.
        conn.execute("SELECT '[1]'::halfvec")
        conn.execute("SET LOCAL hnsw.ef_search=256")
        conn.execute("SET LOCAL hnsw.iterative_scan='strict_order'")
        conn.execute("SET LOCAL hnsw.max_scan_tuples=20000")
        conn.execute("SET LOCAL hnsw.scan_mem_multiplier=1")
        conn.execute("SET LOCAL statement_timeout='2s'")
        for size in (256,512,1024,4096):
            times=[];recalls=[];documents=[]
            for n in range(repeats+1):
                start=time.perf_counter()
                rows=conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,false,NULL,false,1,%s)',
                                 (vector,'general',scopes,at,size)).fetchall()
                elapsed=(time.perf_counter()-start)*1000
                if n:
                    times.append(elapsed);recalls.append(len({str(r['chunk_id']) for r in rows}&expected)/len(expected))
                    documents.append(len({r['document_id'] for r in conn.execute('SELECT document_id FROM chunks WHERE id=ANY(%s)',([r['chunk_id'] for r in rows],))}))
            results[str(size)]=dict(stats(times),recall_fraction=recalls,documents=documents,raw_ms=[round(v,3) for v in times])
    return {'eligible_chunks':eligible_count(conn,'general',scopes,at),'oracle_chunks':len(expected),'oracle_documents':len({r['doc_id'] for r in truth}),
            'method':'Forced ANN branch exact_limit1; identical controlled vectors, no FTS; pool changes alone; default optimizer may choose a sequential distance sort.',
            'pools':results}


def verify(repeats,private):
    cfg=Config();cfg=replace(cfg,ollama_url='http://localhost:1')
    with tempfile.TemporaryDirectory(prefix='rag-filter-source-') as name:
        temp=Path(name);old,old_hash=previous('search',temp);old_store,_=previous('store',temp)
        source_sql=temp/'sql015';source_sql.mkdir()
        for path in sorted((ROOT/'sql').glob('*.sql')):
            if path.name<'016':(source_sql/path.name).write_bytes(git('show',f'{BASE}:sql/{path.name}'))
        initialize=db.init_db
        def deterministic(texts,cfg):
            return [[.99,.1]+[0.0]*1022 if 'secondary-marker' in t else ([.7,.7]+[0.0]*1022 if 'distant-marker' in t else QUERY) for t in texts]
        with patch.object(db,'init_db',lambda c:initialize(c,sql_dir=source_sql)), isolated_database(cfg) as owned:
            with patch.object(store,'try_embed_texts',deterministic),patch.object(old_store,'try_embed_texts',deterministic),patch.object(search,'try_embed_texts',deterministic),patch.object(old,'try_embed_texts',deterministic):
                with db.connect(owned,role='writer') as writer:
                    domains.add_domain(writer,'rare',actor='user-b')
                    crowded=old_store.save_document(writer,owned,title='Synthetic crowded document',body='crowded-marker neutral background. '*50000,domain='general',dtype='reference',project='/synthetic/filter-a',actor='user-a')
                    second=old_store.save_document(writer,owned,title='Synthetic second document',body='secondary-marker independent fact.',domain='general',dtype='reference',project='/synthetic/filter-a',actor='user-a')
                    old_store.save_document(writer,owned,title='Rare active service',body='secondary-marker rare current source.',domain='rare',dtype='reference',project='/synthetic/filter-b',actor='user-b')
                    expired=old_store.save_assertion(writer,owned,entity='Rare sensor',attribute='port',value='8766',domain='rare',project='/synthetic/filter-b',event_at='2026-01-01T00:00:00Z',expires_at='2026-02-01T00:00:00Z',evidence={'source_id':'synthetic-expiry','role':'user','quote':'8766','event_at':'2026-01-01T00:00:00Z'})
                    old_store.save_claim(writer,owned,title='Rare claim',body='The rare sensor uses TLS.',domain='rare',dtype='memory',claim_kind='stated',project='/synthetic/filter-b',actor='user-b',evidence=[{'namespace':'synthetic-filter','source_id':'tls','role':'user','quote':'The rare sensor uses TLS.','complete':True}])
                    old_store.save_document(writer,owned,title='Foreign hidden source',body='crowded-marker foreign source.',domain='general',dtype='reference',project='/synthetic/foreign',actor='user-b')
                    old_store.save_document(writer,owned,title='Archived hidden source',body='crowded-marker archived source.',domain='general',dtype='reference',project='/synthetic/filter-a',status='archived',actor='user-a')
                    # >4096 eligible chunks exercise the real large branch, without database hand-writes.
                    paragraph='crowded-marker '+('x'*990)+'\n\n'
                    old_store.save_document(writer,owned,title='Pool crowded source',body=paragraph*1500,domain='general',dtype='reference',project='/synthetic/filter-pool',actor='user-a')
                    old_store.save_document(writer,owned,title='Pool distant source',body=('distant-marker '+('x'*990)+'\n\n')*2700,domain='general',dtype='reference',project='/synthetic/filter-pool',actor='user-b')
                    old_store.save_document(writer,owned,title='Pool second source',body='secondary-marker separate source.',domain='general',dtype='reference',project='/synthetic/filter-pool',actor='user-b')
                    pins.add_pin(writer,document_id=crowded.doc_id,scope='/synthetic/filter-a',actor='user-a')
                    checkpoints.upsert_snapshot(writer,CheckpointSnapshot(session_id='filter-rehearsal',turn_id='t',cursor='c',source='test',trigger='manual',cwd='/synthetic/filter-a',project_root='/synthetic/filter-a',artifacts=('AGENTS.md',)))
                    jobs.enqueue_curate(writer,reason='Preserved synthetic work')
                with db.connect(owned) as owner:
                    tables=table_names(owner);before=snapshot(owner,tables);grants=privileges(owner)
                    assert len(owner.execute('SELECT * FROM schema_migrations').fetchall())==15
                    owner.rollback()
                    with db.connect(owned,role='reader') as reader:
                        assert not vector_plan.available(reader)
                        old_hits,_=old.search(reader,owned,'quasar',project='/synthetic/filter-a',k=2,rerank_mode='off')
                        new_hits,_=search.search(reader,owned,'quasar',project='/synthetic/filter-a',k=2,rerank_mode='off')
                        assert [h.citation for h in old_hits]==[h.citation for h in new_hits]
                        citation_check(reader,new_hits)
                    strict=verified_backup(owned,private/'source015-synthetic.dump')
                    # Actual016 DDL interruption and retry, not a mocked migration result.
                    owner.execute((ROOT/'sql/016_filter_aware_search.sql').read_text());owner.rollback()
                    assert not vector_plan.available(owner);owner.rollback()
                    assert db.apply_migrations(owner,ROOT/'sql')==['016_filter_aware_search.sql']
                    assert db.apply_migrations(owner,ROOT/'sql')==[]
                    assert table_names(owner)==tables and snapshot(owner,tables)==before and privileges(owner)==grants
                    owner.rollback()
                    owner.execute('ANALYZE');owner.commit()  # Owned copy only; realistic optimizer statistics.
                    cases=[{'id':'small-project-second-source','project':'/synthetic/filter-a','domain':'general'},
                           {'id':'rare-domain-current','project':'/synthetic/filter-b','domain':'rare','as_of':'2026-03-01T00:00:00Z'},
                           {'id':'rare-domain-as-of','project':'/synthetic/filter-b','domain':'rare'}]
                    measurements=candidate_comparison(owner,cases,repeats)
                    pools=pool_comparison(owner,repeats)
                    owner.rollback()
                    def read(fn):
                        with db.connect(owned,role='reader') as reader:
                            reader.execute('SET TRANSACTION READ ONLY')
                            hits,_=fn(reader,owned,'quasar',project='/synthetic/filter-a',k=2,rerank_mode='off')
                            citation_check(reader,hits)
                            return {h.document_id for h in hits}
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        a=executor.submit(read,old.search);b=executor.submit(read,search.search)
                        assert a.result(timeout=5)=={crowded.doc_id}
                        assert b.result(timeout=5)=={crowded.doc_id,second.doc_id}
                    # Actual source-version writer after016, and actual old search code rollback.
                    with db.connect(owned,role='writer') as writer:
                        changed=old_store.save_document(writer,owned,title='Old client correction',body='secondary-marker corrected original fact.',domain='general',dtype='reference',doc_id=second.doc_id,actor='user-a')
                        assert changed.doc_id==second.doc_id
                    assert read(old.search)=={crowded.doc_id}
                    assert read(search.search)=={crowded.doc_id,second.doc_id}
                    with db.connect(owned,role='reader') as reader:
                        import psycopg
                        assert vector_plan.available(reader)
                        # Invoker functions never grant a reader write privilege.
                        try:reader.execute("UPDATE documents SET title='forbidden' WHERE false")
                        except psycopg.errors.InsufficientPrivilege:reader.rollback()
                        else:raise AssertionError('reader unexpectedly writable')
                    result={'timestamp':datetime.now(timezone.utc).isoformat(),'source_revision':BASE,'baseline_search_sha256':old_hash,
                      'source_schema':15,'target_schema':16,'source_rows_preserved':True,'canonical_tables':before,
                      'migration_interrupt_retry_idempotent':True,'existing_table_privileges_unchanged':True,
                      'missing016_actual_old_new_citation_parity':True,'concurrent_actual_old_new_readers':True,
                      'actual_old_writer_after016':True,'actual_old_search_code_rollback':True,'reader_cannot_write':True,
                      'strict_source_backup':{k:v for k,v in strict.items() if k!='dump'},
                      'dataset':'Owned synthetic audited fixtures; two named user actors,two populated domains,four project scopes,pin,checkpoint,queue,claim,expiring assertion; deterministic injected embedding boundary.',
                      'method':'Owned copy ANALYZE before both routes. Paired alternating SQL candidate calls; no embedding network calls, no FTS overlap, no reranker/querycache. Exhaustive independent eligible top50 oracle with <=2chunks/document.',
                      'repetitions':repeats,'cases':measurements,'pool_comparison':pools}
        result['owned_database_cleanup']='verified';return result




def planned_vectors(conn,vector,domain,scopes,at,model,context):
    """Isolated-copy oracle diagnostic under the actual planner setting policy."""
    with conn.transaction():
        conn.execute("SELECT '[1]'::halfvec")
        version=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
        names=['statement_timeout','hnsw.ef_search','hnsw.iterative_scan','hnsw.max_scan_tuples','hnsw.scan_mem_multiplier']
        original={r['name']:r['setting'] for r in conn.execute('SELECT name,setting FROM pg_settings WHERE name=ANY(%s)',(names,))}
        settings=vector_plan._planned_settings(version,original)
        for name,value in settings.items():conn.execute('SELECT set_config(%s,%s,true)',(name,value))
        rows=conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,false,%s,%s)',
                          (vector,domain,scopes,at,model,context)).fetchall()
        for name in reversed(settings):conn.execute('SELECT set_config(%s,%s,true)',(name,original[name]))
        return rows

def legacy_vector_candidates(conn,vector,domain,scopes,at,model,context):
    """Execute the exact source-revision vector CTE without conflating FTS recall."""
    name='015_contextual_chunks.sql' if context else '013_retrieval_quality.sql'
    source=git('show',f'{BASE}:sql/{name}').decode()
    branch=source.split('WITH vec AS (',1)[1].split('),\nts_en AS (',1)[0]
    values={'query_vec':vector,'p_domain':domain,'p_scopes':scopes,'p_at':at,'p_history':False,'p_model':model}
    casts={'query_vec':'halfvec','p_domain':'text','p_scopes':'text[]','p_at':'timestamptz','p_history':'boolean','p_model':'text'}
    branch=re.sub(r'\b(query_vec|p_domain|p_scopes|p_at|p_history|p_model)\b',lambda m:'%('+m[0]+')s::'+casts[m[0]],branch)
    with conn.transaction():
        old=conn.execute("SELECT current_setting('hnsw.ef_search') setting").fetchone()['setting']
        conn.execute("SET LOCAL hnsw.ef_search=256")
        rows=conn.execute('WITH vec AS ('+branch+') SELECT * FROM vec',values).fetchall()
        conn.execute("SELECT set_config('hnsw.ef_search',%s,true)",(old,))
        return rows

def trading_copy(repeats,private):
    cfg=load_config()
    if urlparse(cfg.ollama_url).hostname not in {'localhost','127.0.0.1','::1'}:
        raise ValueError('Trading measurements require loopback inference')
    model=query_cache.model_digest(cfg)
    if model is None:raise RuntimeError('verified existing local embedding model required')
    dump=private/'source015-trading.dump'
    strict=verified_backup(cfg,dump)  # Consistent production read-only dump; strict owned restore proof.
    (private/'backup-report.json').write_text(json.dumps(strict,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='rag-filter-trading-') as name:
        old,old_hash=previous('search',Path(name))
        with patch.object(db,'init_db',lambda c:[]),isolated_database(cfg) as owned:
            backup._run_pg([backup._pg_bin('pg_restore',cfg),'--single-transaction','--exit-on-error','-d',db.dsn(owned),str(dump)])
            with db.connect(owned) as owner:
                assert len(owner.execute('SELECT * FROM schema_migrations').fetchall())==15
                tables=table_names(owner);before=snapshot(owner,tables);grants=privileges(owner);owner.rollback()
                assert db.apply_migrations(owner,ROOT/'sql')==['016_filter_aware_search.sql']
                assert snapshot(owner,tables)==before and privileges(owner)==grants
                owner.rollback()
                owner.execute('ANALYZE');owner.commit()  # pg_restore does not restore planner statistics.
            from agentic_rag.scope import selection
            scopes=selection('/Users/peter/Agents/Trading');at=datetime.now(timezone.utc).isoformat()
            # Queries stay private; public report exports aggregate measurements only.
            cases=[('trading-project','Wie werden Risiken bei der Positionsgröße begrenzt?',None),
                   ('trading-domain','Welche Regeln gelten für die Marktregime und Drawdowns?','trading'),
                   ('rare-domain-in-project','Wie werden OAuth-Probleme bei der Newsletter-Erstellung behandelt?','programming')]
            output={}
            with db.connect(owned,role='reader') as reader:
                reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                counts=reader.execute('SELECT (SELECT count(*) FROM documents) documents,(SELECT count(*) FROM chunks) chunks').fetchone()
                for label,query,domain in cases:
                    vectors=embed.try_embed_texts([query],cfg)
                    if vectors is None:raise RuntimeError('local embedding unavailable')
                    literal=embed.vec_literal(vectors[0]);truth=oracle(reader,literal,domain,scopes,at)
                    truth_context=oracle(reader,literal,domain,scopes,at,model=model,context=True)
                    expected={str(r['id']) for r in truth};expected_context={str(r['id']) for r in truth_context}
                    args=(query,literal,domain,150,scopes,at,False,model)
                    candidates={}
                    for route in ('before','after'):
                        if route=='before':
                            raw=legacy_vector_candidates(reader,literal,domain,scopes,at,model,False)
                            ctx=legacy_vector_candidates(reader,literal,domain,scopes,at,model,True)
                        else:
                            vector_plan.candidates(reader,args)  # Full production candidate path/budget.
                            raw=planned_vectors(reader,literal,domain,scopes,at,model,False)
                            ctx=planned_vectors(reader,literal,domain,scopes,at,model,True)
                        candidates[route]={'raw_vector_oracle_recall':len(expected&{str(r['chunk_id']) for r in raw})/len(expected) if expected else 1,
                          'context_vector_oracle_recall':len(expected_context&{str(r['chunk_id']) for r in ctx})/len(expected_context) if expected_context else 1}
                    samples={'before':[],'after':[]};valid={'before':0,'after':0};first={};equal=0
                    for n in range(repeats+1):
                        signatures={}
                        for route in (('before','after') if n%2==0 else ('after','before')):
                            fn=old.search if route=='before' else search.search;start=time.perf_counter()
                            hits,warnings=fn(reader,owned,query,project='/Users/peter/Agents/Trading',domain=domain,as_of=at,k=3,rerank_mode='off')
                            elapsed=(time.perf_counter()-start)*1000
                            if warnings:raise RuntimeError('inference warning invalidates measurement')
                            citation_check(reader,hits);signatures[route]=[h.citation for h in hits]
                            if n==0:first[route]=round(elapsed,3)
                            else:samples[route].append(elapsed);valid[route]+=len(hits)
                        if n and signatures['before']==signatures['after']:equal+=1
                    output[label]={'eligible_chunks':eligible_count(reader,domain,scopes,at),'raw_oracle_chunks':len(expected),'context_oracle_chunks':len(expected_context),
                      'equal_top3_citation_lists':equal,'routes':{route:dict(stats(values),first_call_ms=first[route],validated_citations=valid[route],
                         **candidates[route],raw_ms=[round(v,3) for v in values]) for route,values in samples.items()}}
                reader.rollback()
            with db.connect(owned) as owner:
                assert snapshot(owner,tables)==before
            assert query_cache.model_digest(cfg)==model
            result={'timestamp':at,'source_revision':BASE,'baseline_search_sha256':old_hash,'source_schema':15,'target_schema':16,
             'production_writes':0,'copied_rows_preserved':True,'existing_table_privileges_unchanged':True,'store_counts':counts,
             'method':'Strict read-only exported production snapshot restored into owned disposable copy and ANALYZE before both routes; paired alternating complete searches, default auto/context-auto, k3,1200 original chars,no reranker/querycache; same unchanged local bge-m3; private queries/content not exported.',
             'embedding_model':cfg.embed_model,'model_digest':model,'repetitions':repeats,'cases':output,
             'strict_source_backup':{k:v for k,v in strict.items() if k!='dump'}}
        result['owned_database_cleanup']='verified';return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--private-dir',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--trading-copy',action='store_true')
    args=parser.parse_args()
    if not 1<=args.repeats<=100:parser.error('repeats must be1..100')
    args.private_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    result=trading_copy(args.repeats,args.private_dir) if args.trading_copy else verify(args.repeats,args.private_dir)
    result['candidate_head']=git('rev-parse','HEAD').decode().strip()
    result['candidate_files_sha256']={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in
        [ROOT/'agentic_rag/search.py',ROOT/'agentic_rag/vector_plan.py',ROOT/'sql/016_filter_aware_search.sql',Path(__file__)]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('source_rows_preserved','copied_rows_preserved','migration_interrupt_retry_idempotent','owned_database_cleanup','production_writes') if k in result}))


if __name__=='__main__':main()
