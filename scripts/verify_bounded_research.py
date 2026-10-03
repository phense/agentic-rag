#!/usr/bin/env python3
"""Paired public synthetic research evidence and populated016 compatibility.

All fixture writes use audited gateways on randomly owned disposable databases.
Production Trading is read-only and provider-free; publish aggregate metrics only.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from agentic_rag import db,domains,evidence,jobs,mcp_server,pins,search,store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config,load_config
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot
from agentic_rag.research import ResearchBudget,research
from scripts.verify_contextual_indexing import snapshot,verified_backup

ROOT=Path(__file__).resolve().parents[1]
BASE='19ed09c1b3c46d907254f63a1370586ea3213966'
PROJECT='/synthetic/research/alpha'
BUDGET=12000


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def stats(values):
    return {'p50_ms':round(statistics.median(values),3),'p95_ms':round(sorted(values)[math.ceil(.95*len(values))-1],3),
            'raw_ms':[round(v,3) for v in values]}


def source_claim(conn,cfg,title,body,quote=None,project=PROJECT,domain='programming',edges=None):
    result=evidence.save(conn,cfg,title=title,body=body,domain=domain,dtype='memory',project=project,
        claim_kind='stated',evidence=[dict(namespace='synthetic-research-v1',source_id=title+':'+s,
            role='user',quote=quote or body,complete=True) for s in ('operator-record','independent-probe')],edges=edges)
    evidence.review(conn,result.doc_id,state='confirmed',reason='public synthetic oracle checked')
    return result


def seed(conn,cfg):
    for domain in ('programming','trading','infrastructure'):domains.add_domain(conn,domain)
    storage=source_claim(conn,cfg,'Aurora storage decision','Aurora storage decision uses one PostgreSQL store with pgvector for all clients.')
    constraint=source_claim(conn,cfg,'Aurora present constraints','Aurora present constraints require reader isolation and audited writes; provider forks are forbidden.')
    proof='Beacon recovery probe returned OK after replacing the stale socket.'
    resolution=source_claim(conn,cfg,'Beacon operations handbook',('Routine handbook introduction. '*140+'\n\n')*70+proof,quote=proof)
    cause=source_claim(conn,cfg,'Beacon incident cause','Beacon incident was caused by a stale socket.',edges=[store.EdgeSpec('references',resolution.slug,'operations handbook records recovery proof','high')])
    retention_a=source_claim(conn,cfg,'Cinder retention ninety','Cinder retention is ninety days.')
    retention_b=source_claim(conn,cfg,'Cinder retention thirty','Cinder retention is thirty days.',edges=[store.EdgeSpec('contradicts',retention_a.slug,'same policy has opposing retention values','high')])
    source_claim(conn,cfg,'Foreign Aurora','Aurora storage decision uses a foreign provider fork.',project='/synthetic/research/beta')
    source_claim(conn,cfg,'Trading control','Trading control remains manual and read-only.',domain='trading')
    source_claim(conn,cfg,'Infrastructure control','Infrastructure control uses existing jobs and clients.',domain='infrastructure')
    store.save_document(conn,cfg,title='Global rule',body='Global control preserves existing access boundaries.',domain='programming',dtype='lesson',scope='global')
    pins.add_pin(conn,body='Preserve the synthetic shared store.')
    checkpoints.upsert_snapshot(conn,CheckpointSnapshot(session_id='synthetic-research',turn_id='t',cursor='c',source='test',trigger='manual',cwd=PROJECT,project_root=PROJECT,artifacts=('AGENTS.md',)))
    jobs.enqueue_curate(conn,reason='synthetic-research')
    return [
        dict(id='architecture',question='What is Aurora storage decision? What are Aurora present constraints?',expected=[storage.doc_id,constraint.doc_id],facts=[
            'Aurora storage decision uses one PostgreSQL store with pgvector for all clients.',
            'Aurora present constraints require reader isolation and audited writes; provider forks are forbidden.']),
        dict(id='incident',question='What caused Beacon incident? What is the Beacon recovery probe result?',expected=[cause.doc_id,resolution.doc_id],facts=[
            'Beacon incident was caused by a stale socket.',proof]),
        dict(id='contradictory-missing',question='What is Cinder retention days? What is Cinder approved replica count?',expected=[retention_a.doc_id,retention_b.doc_id],facts=[
            'Cinder retention is ninety days.','Cinder retention is thirty days.'])]


def raw_search(connection,cfg,query,options):
    return search.search(connection,cfg,query,k=6,strategy='lexical',rerank_mode='off',**options)[0]


def citations(connection,records):
    for item in records:
        row=connection.execute('SELECT document_id,content FROM chunks WHERE id=%s',(item['chunk_id'],)).fetchone()
        assert row and str(row['document_id'])==item['document_id']
        assert row['content'][item['start']:item['end']]==item['text']
        assert item['citation']==f"{item['document_id']}#{item['chunk_id']}:{item['start']}-{item['end']}"


def compare(cfg,cases,repeats):
    result=[]
    with db.connect(cfg,role='reader') as conn:
        for case in cases:
            times={'before':[],'after':[]};quality={'before':[],'after':[]};first={};example={}
            for repetition in range(repeats+1):
                for route in (('before','after') if repetition%2==0 else ('after','before')):
                    started=time.perf_counter()
                    if route=='before':
                        hits=raw_search(conn,cfg,case['question'],{'project':PROJECT,'domain':'programming'})
                        rows=[]
                        for h in hits:
                            item=dict(document_id=h.document_id,chunk_id=h.chunk_id,text=h.snippet,start=h.snippet_start,end=h.snippet_end,citation=h.citation)
                            if len(json.dumps(rows+[item],ensure_ascii=False,separators=(',',':')))<=BUDGET:rows.append(item)
                        packet={'evidence':rows,'context':json.dumps(rows,ensure_ascii=False,separators=(',',':')),
                                'supported':[],'disagreement':[],'missing_evidence':[],'abstained':None,'usage':None,'termination':'ordinary_search'}
                    else:
                        packet=research(cfg,case['question'],project=PROJECT,domain='programming',strategy='lexical',budget=ResearchBudget(context_chars=BUDGET))
                        rows=packet['evidence']
                    elapsed=(time.perf_counter()-started)*1000
                    citations(conn,rows)
                    assert len(packet['context'])<=BUDGET
                    doc_count=len({r['document_id'] for r in rows}&set(case['expected']))
                    fact_count=sum(any(fact in r['text'] for r in rows) for fact in case['facts'])
                    measurement=dict(eligible_sources_found=doc_count,eligible_sources_expected=len(case['expected']),
                        fact_excerpts_found=fact_count,fact_excerpts_expected=len(case['facts']),citation_errors=0,
                        supported_statements=len(packet['supported']),disagreements=len(packet['disagreement']),
                        missing_facets=len(packet['missing_evidence']),abstained=packet['abstained'],
                        context_chars=len(packet['context']),usage=packet['usage'],termination=packet['termination'])
                    if repetition==0:first[route]=round(elapsed,3)
                    else:times[route].append(elapsed);quality[route].append(measurement)
                    example[route]=measurement
            result.append(dict(id=case['id'],question=case['question'],context_budget=BUDGET,repetitions=repeats,
                first_observation_label='first call; database/OS cache not flushed',routes={route:dict(stats(times[route]),
                first_call_ms=first[route],raw_quality=quality[route],example=example[route]) for route in times}))
    return result


def tools_at(source,config_file,readonly):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    import os
    async def call():
        env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config_file),RAG_READONLY='1' if readonly else '0',AGENTIC_RAG_HOOKS_DISABLE='1')
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','agentic_rag.mcp_server'],env=env,cwd=str(source))) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools=await session.list_tools()
                found=await session.call_tool('memory_search',{'query':'Aurora storage decision','strategy':'lexical','project':PROJECT,'domain':'programming'})
                assert not found.isError
                packet=found.structuredContent or json.loads(found.content[0].text)
                assert packet['results']
                if source==ROOT:
                    found=await session.call_tool('memory_research',{'question':'Aurora storage decision','strategy':'lexical','project':PROJECT,'domain':'programming'})
                    assert not found.isError
                    packet=found.structuredContent or json.loads(found.content[0].text)
                    assert packet['supported'] and packet['abstained']
                names=sorted(t.name for t in tools.tools)
                assert len(names)==((8 if readonly else 14) if source==ROOT else (7 if readonly else 13))
                assert ('memory_research' in names)==(source==ROOT)
                return {'tools':names,'citations':len(packet.get('results',packet.get('evidence',[])))}
    return asyncio.run(call())


def compatibility(cfg,source_directory,temp):
    config=temp/'config.toml';config.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[ollama]\nurl="http://localhost:1"\n')
    from scripts.verify_filter_aware_search import privileges,table_names
    with db.connect(cfg,role='owner') as conn:
        tables=table_names(conn)
        before=snapshot(conn,tables);grants=privileges(conn)
        schema=[r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
    import os
    cli=[];mcp=[]
    for source in (source_directory,ROOT,source_directory):
        env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config),AGENTIC_RAG_HOOKS_DISABLE='1')
        proc=subprocess.run([sys.executable,'-m','agentic_rag.cli','search','Aurora storage decision','--project',PROJECT,'--domain','programming','--strategy','lexical','--json'],env=env,cwd=temp,capture_output=True,text=True,check=True,timeout=20)
        data=json.loads(proc.stdout);assert data['results']
        cli.append([h['citation'] for h in data['results']])
        for readonly in (True,False):mcp.append(dict(source='candidate' if source==ROOT else 'source/rollback',readonly=readonly,**tools_at(source,config,readonly)))
    assert cli[0]==cli[1]==cli[2]
    with db.connect(cfg,role='owner') as conn:
        after=snapshot(conn,tables)
        assert before==after and grants==privileges(conn)
        assert schema==[r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
    return dict(source_revision=BASE,schema_count=len(schema),tables=len(tables),full_row_fingerprints_preserved=True,
        table_privileges_preserved=True,source_candidate_rollback_cli_citation_parity=True,mcp=mcp,
        migration_required=False,application_knowledge_writes_during_acceptance=0)


def trading(cfg,repeats):
    # Real canonical reader; no fixture writes and no structured-provider calls.
    queries=['PEAD green close','regime risk filter','manual portfolio constraints']
    output=[]
    with db.connect(cfg,role='reader') as conn:
        eligible=conn.execute("SELECT count(*) n FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.status='active' AND d.domain='trading' AND assertion_eligible(d.id)").fetchone()['n']
        for n,query in enumerate(queries):
            latencies=[];samples=[]
            for _ in range(repeats):
                start=time.perf_counter()
                result=research(cfg,query,domain='trading',project='/Users/peter/Agents/Trading',provider=False,budget=ResearchBudget(seconds=30))
                latencies.append((time.perf_counter()-start)*1000)
                citations(conn,result['evidence'])
                samples.append(dict(evidence_count=len(result['evidence']),supported_count=len(result['supported']),
                    abstained=result['abstained'],context_chars=len(result['context']),calls=result['usage']['calls'],steps=result['usage']['steps'],termination=result['termination'],citation_errors=0))
            output.append(dict(case=f'trading-reader-{n+1}',repetitions=repeats,**stats(latencies),raw_quality=samples))
    return {'eligible_chunks':eligible,'provider_calls':0,'application_writes':0,'cases':output,
            'limits':'Real reader safety/latency controls; no private text or query output published; no answer-quality gain claimed.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=20);p.add_argument('--trading',action='store_true');p.add_argument('--provider-smoke',action='store_true');args=p.parse_args()
    if not 1<=args.repeats<=30:raise ValueError('repeats must be1–30')
    measured_paths=[ROOT/'agentic_rag/research.py',ROOT/'agentic_rag/research_worker.py',ROOT/'agentic_rag/cli.py',ROOT/'agentic_rag/mcp_server.py',Path(__file__).resolve()]
    def fingerprints():return {str(path.relative_to(ROOT)):sha256(path.read_bytes()).hexdigest() for path in measured_paths}
    frozen=fingerprints()
    result={'baseline_revision':BASE,'candidate_revision':git('rev-parse','HEAD').decode().strip(),'candidate_working_tree':bool(git('status','--porcelain')),
        'search_bytes_unchanged':git('show',f'{BASE}:agentic_rag/search.py')==(ROOT/'agentic_rag/search.py').read_bytes(),
        'candidate_files_sha256':frozen,
        'synthetic':True,'controlled_provider_calls':0,'generated_at':datetime.now(timezone.utc).isoformat()}
    cfg=Config(ollama_url='http://localhost:1')
    with tempfile.TemporaryDirectory(prefix='bounded-research-acceptance-') as name:
        temp=Path(name);source=temp/'source';source.mkdir()
        archive=git('archive',BASE)
        subprocess.run(['tar','-xf','-','-C',str(source)],input=archive,check=True)
        with isolated_database(cfg) as isolated:
            with db.connect(isolated,role='writer') as conn,patch('agentic_rag.store.try_embed_texts',return_value=None):
                cases=seed(conn,isolated)
            result['compatibility']=compatibility(isolated,source,temp)
            result['scenarios']=compare(isolated,cases,args.repeats)
            if args.provider_smoke:
                live=replace(load_config(),db_name=isolated.db_name,db_host=isolated.db_host,ollama_url=isolated.ollama_url)
                samples=[]
                for case in cases:
                    start=time.perf_counter()
                    packet=research(live,case['question'],project=PROJECT,domain='programming',strategy='lexical',provider=True,budget=ResearchBudget(seconds=120))
                    with db.connect(isolated,role='reader') as reader:citations(reader,packet['evidence'])
                    samples.append(dict(case=case['id'],milliseconds=round((time.perf_counter()-start)*1000,3),
                        provider=live.llm_provider,model=live.llm_model,abstained=packet['abstained'],
                        supported_statements=len(packet['supported']),disagreements=len(packet['disagreement']),
                        missing_facets=len(packet['missing_evidence']),calls=packet['usage']['calls'],provider_calls=packet['usage']['provider_calls'],steps=packet['usage']['steps'],
                        context_chars=len(packet['context']),termination=packet['termination'],warnings=packet['warnings'],citation_errors=0))
                result['configured_provider_smoke']={'synthetic_only':True,'repetitions_per_case':1,'provider_calls':sum(s['provider_calls'] for s in samples),'samples':samples,
                    'limits':'One live observation per case is integration evidence, not model accuracy or latency distribution.'}

            result['strict_backup_restore']=verified_backup(isolated,temp/'source016.dump')
            result['strict_backup_restore'].pop('dump',None)
    if args.trading:result['trading_reader']=trading(load_config(),5)
    assert frozen==fingerprints(),'measured source changed during acceptance; repeat on frozen code'
    result['candidate_hashes_match_after_measurement']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps({'output':str(args.output),'scenarios':len(result['scenarios']),'compatibility':True,'strict_backup_restore':True}))


if __name__=='__main__':main()
