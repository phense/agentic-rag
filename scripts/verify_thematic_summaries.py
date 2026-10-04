#!/usr/bin/env python3
"""Rehearse populated016→017 and measure three public, source-grounded views.

Fixture and cache writes use gateways on randomly owned disposable databases.
Canonical Trading is reader-only; public output contains aggregates, never bodies.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from agentic_rag import backup, db, domains, evidence, jobs, pins, profiles, store, thematic
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot
from scripts.verify_contextual_indexing import snapshot, verified_backup
from scripts.verify_filter_aware_search import privileges, table_names

ROOT = Path(__file__).resolve().parents[1]
BASE = 'bd01d97b1188e6bb0cf71e838c7c35e3449d8f3b'
PROJECT = '/synthetic/thematic/alpha'
BUDGET = 4800


def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT)


def stats(values):
    return dict(p50_ms=round(statistics.median(values),3),
        p95_ms=round(sorted(values)[math.ceil(.95*len(values))-1],3), raw_ms=[round(v,3) for v in values])


def claim(conn,cfg,title,body,project=PROJECT,domain='infrastructure',actor='synthetic-operator-a'):
    return store.save_claim(conn,cfg,title=title,body=body,domain=domain,dtype='lesson',project=project,
        actor=actor,claim_kind='stated',evidence=[dict(namespace='synthetic-theme:'+title,
        source_id='operator-session',role='user',quote=body,complete=True)])


def seed(conn,cfg):
    for domain in ('infrastructure','trading','programming','projects','user','unsorted'):
        domains.add_domain(conn,domain)
    topics = [('provider outage','Provider outage episode {n} recovered after OAuth renewal.'),
              ('deployment architecture','Deployment architecture stage {n} uses one PostgreSQL and pgvector store.'),
              ('operational recovery lesson','Operational recovery lesson session {n} requires a verified restore probe.')]
    cases=[]
    for topic,template in topics:
        docs=[]; facts=[]
        for n in range(8):
            fact=template.format(n=n)
            body=fact+'\n\n'+('Recorded public synthetic background and operational context. '*35)
            doc=claim(conn,cfg,topic+str(n),body,actor='synthetic-operator-a' if n%2 else 'synthetic-operator-b')
            docs.append(doc.doc_id);facts.append(fact)
        cases.append(dict(topic=topic,expected=docs,facts=facts))
    claim(conn,cfg,'Foreign provider outage','Provider outage foreign project.',project='/synthetic/thematic/beta')
    claim(conn,cfg,'Trading provider outage','Provider outage in another domain.',domain='trading')
    store.save_document(conn,cfg,title='Global provider outage control',body='Provider outage global-only control.',domain='user',dtype='lesson',scope='global')
    pins.add_pin(conn,body='Preserve the shared synthetic store.')
    checkpoints.upsert_snapshot(conn,CheckpointSnapshot(session_id='synthetic-thematic',turn_id='t',cursor='c',
        source='test',trigger='manual',cwd=PROJECT,project_root=PROJECT,artifacts=('AGENTS.md',)))
    jobs.enqueue_curate(conn,reason='synthetic-thematic')
    profiles.refresh(conn,cfg,PROJECT)
    return cases


def old_search(source):
    # All imported search dependencies are checked byte-identical below. Only
    # the baseline search module is loaded under an alternate package name.
    spec=importlib.util.spec_from_file_location('agentic_rag._thematic_baseline_search',source/'agentic_rag/search.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module.search


def check_citations(conn,entries):
    for e in entries:
        original=conn.execute('SELECT document_id,content FROM chunks WHERE id=%s',(e['chunk_id'],)).fetchone()
        assert original and str(original['document_id'])==e['document_id']
        assert original['content'][e['start']:e['end']]==e['text']
        assert e['citation']==f"{e['document_id']}#{e['chunk_id']}:{e['start']}-{e['end']}"


def compare(cfg,cases,repeats,baseline):
    results=[]
    for case in cases:
        with db.connect(cfg,role='writer') as writer:
            creation=store.refresh_summaries(writer,cfg,case['topic'],project=PROJECT,domain='infrastructure',context_chars=BUDGET)
        assert creation['usage']['rebuilt']==8
        timings={route:[] for route in ('before','after')}; quality={route:[] for route in timings}; first={}
        with db.connect(cfg,role='reader') as conn:
            for repetition in range(repeats+1):
                for route in (('before','after') if repetition%2==0 else ('after','before')):
                    start=time.perf_counter()
                    if route=='before':
                        hits,_=baseline(conn,cfg,case['topic'],project=PROJECT,domain='infrastructure',
                            strategy='lexical',rerank_mode='off',k=24)
                        lines=[];entries=[]
                        for h in hits:
                            line=f'- [{h.citation}] '+json.dumps(h.snippet,ensure_ascii=False)+'; '+json.dumps(h.evidence,sort_keys=True)
                            if len('\n'.join(lines+[line]))<=BUDGET:
                                lines.append(line);entries.append(dict(document_id=h.document_id,chunk_id=h.chunk_id,
                                    start=h.snippet_start,end=h.snippet_end,text=h.snippet,citation=h.citation))
                        text='\n'.join(lines)
                    else:
                        packet=thematic.read(conn,cfg,case['topic'],project=PROJECT,domain='infrastructure',context_chars=BUDGET)
                        assert packet['status']=='fresh'
                        entries=packet['entries']; text=packet['context']
                    milliseconds=(time.perf_counter()-start)*1000
                    check_citations(conn,entries)
                    assert len(text)<=BUDGET
                    row=dict(source_coverage=len({e['document_id'] for e in entries}&set(case['expected'])),
                        source_denominator=8,exact_facts=sum(any(f in e['text'] for e in entries) for f in case['facts']),
                        fact_denominator=8,context_chars=len(text),citation_errors=0)
                    if repetition==0: first[route]=round(milliseconds,3)
                    else: timings[route].append(milliseconds);quality[route].append(row)
                    conn.rollback()
        with db.connect(cfg,role='writer') as writer:
            refreshes=[];reuse=[]
            for _ in range(repeats):
                packet=store.refresh_summaries(writer,cfg,case['topic'],project=PROJECT,domain='infrastructure',context_chars=BUDGET)
                refreshes.append(packet['usage']['elapsed_ms']);reuse.append(packet['usage'])
            assert all(r['rebuilt']==0 and r['reused']==8 for r in reuse)
            withdrawn=evidence.sources(writer,case['expected'][0])[0]['source_key']
            store.set_source_state(writer,withdrawn,state='removed',reason='synthetic incident correction')
            updated=claim(writer,cfg,case['topic']+' corrected',case['facts'][0]+' Corrected source record.')
            changed=store.refresh_summaries(writer,cfg,case['topic'],project=PROJECT,domain='infrastructure',context_chars=BUDGET)
            assert changed['usage']['rebuilt']==1 and changed['usage']['reused']==7
            assert case['expected'][0] not in {e['document_id'] for e in changed['entries']}
            assert updated.doc_id in {e['document_id'] for e in changed['entries']}
        results.append(dict(topic=case['topic'],context_budget=BUDGET,repetitions=repeats,
            first_observation='First API call; database/OS caches not flushed. Warm paired calls alternate route order.',
            routes={route:dict(stats(timings[route]),first_call_ms=first[route],raw_quality=quality[route]) for route in timings},
            creation=creation['usage'],unchanged_refresh=dict(stats(refreshes),raw_usage=reuse),changed_refresh=changed['usage']))
    return results


def cli_call(source,config,args):
    env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config),AGENTIC_RAG_HOOKS_DISABLE='1')
    p=subprocess.run([sys.executable,'-m','agentic_rag.cli',*args],env=env,cwd=source,
        capture_output=True,text=True,check=True,timeout=30)
    return json.loads(p.stdout)


def mcp_call(source,config,readonly,candidate):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def run():
        env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config),RAG_READONLY='1' if readonly else '0',AGENTIC_RAG_HOOKS_DISABLE='1')
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','agentic_rag.mcp_server'],env=env,cwd=str(source))) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize(); tools=await session.list_tools(); names=sorted(t.name for t in tools.tools)
                expected=(9 if readonly else 15) if candidate else (8 if readonly else 14)
                assert len(names)==expected
                result=await session.call_tool('memory_search',dict(query='provider outage',project=PROJECT,domain='infrastructure',strategy='lexical'))
                assert not result.isError
                packet=result.structuredContent or json.loads(result.content[0].text);assert packet['results']
                if candidate:
                    result=await session.call_tool('memory_summary',dict(topic='provider outage',project=PROJECT,domain='infrastructure'))
                    assert not result.isError
                    summary=result.structuredContent or json.loads(result.content[0].text)
                    assert summary['entries'] and summary['status']=='fresh'
                return dict(tool_count=len(names),write_tools_present='memory_save' in names,search_citations=len(packet['results']))
    return asyncio.run(run())


def adoption(cfg,source,temp):
    config=temp/'config.toml';config.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[ollama]\nurl="http://localhost:1"\n')
    with db.connect(cfg,role='owner') as c:
        tables=table_names(c);before=snapshot(c,tables);grants=privileges(c)
    source_cli=cli_call(source,config,['search','provider outage','--project',PROJECT,'--domain','infrastructure','--strategy','lexical','--json'])
    result=dict(source_revision=BASE,supported_schema_from=16,supported_schema_to=17)
    result['source016_strict_backup_restore']=verified_backup(cfg,temp/'source016.dump');result['source016_strict_backup_restore'].pop('dump')
    with db.connect(cfg,role='owner') as c:
        c.execute((ROOT/'sql/017_thematic_summaries.sql').read_text());c.rollback()
        assert not c.execute("SELECT to_regclass('public.thematic_summaries') t").fetchone()['t']
        c.rollback()
        result['migration_applied']=db.apply_migrations(c,ROOT/'sql')
        assert result['migration_applied']==['017_thematic_summaries.sql']
        assert db.apply_migrations(c,ROOT/'sql')==[]
        assert snapshot(c,tables)==before
        retained=[r for r in privileges(c) if r['table_name']!='thematic_summaries']
        assert retained==grants
        assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']==17
        result.update(interrupted_ddl_rolled_back=True,retry_idempotent=True,protected_tables=len(tables),
            all_original_rows_preserved=True,old_grants_preserved=True)
    candidate_cli=cli_call(ROOT,config,['search','provider outage','--project',PROJECT,'--domain','infrastructure','--strategy','lexical','--json'])
    rollback_cli=cli_call(source,config,['search','provider outage','--project',PROJECT,'--domain','infrastructure','--strategy','lexical','--json'])
    assert [h['citation'] for h in source_cli['results']]==[h['citation'] for h in candidate_cli['results']]==[h['citation'] for h in rollback_cli['results']]
    result['source_candidate_rollback_search_parity']=True
    return result,config


def trading():
    cfg=load_config();rows=[]
    with db.connect(cfg,role='reader') as c:
        c.execute('SET TRANSACTION READ ONLY')
        for topic in thematic.DEFAULT_THEMES:
            start=time.perf_counter()
            packet=thematic.read(c,cfg,topic,project='/Users/peter/Agents/Trading',domain='trading')
            rows.append(dict(topic=topic,status=packet['status'],entries=len(packet['entries']),milliseconds=round((time.perf_counter()-start)*1000,3)))
        count=c.execute("SELECT count(*) n FROM documents WHERE domain='trading'").fetchone()['n']
    return dict(document_count=count,application_writes=0,provider_calls=0,observations=rows,
        limits='Canonical016 has no summary cache. These are reader fallback controls, not production quality/speedup measurements.')


def private_recovery(dump,report,source,repeats):
    """Authorized isolated recovery of a verified dump; publish aggregate metrics.

    No private body, title, ID, prompt or dump path crosses the result boundary.
    The restore destination is always marker-owned, never caller-selected.
    """
    manifest=json.loads(report.read_text())
    if sha256(dump.read_bytes()).hexdigest()!=manifest['dump_sha256']:
        raise ValueError('Private backup checksum mismatch')
    result=dict(source_schema=16,target_schema=17,provider_calls=0,canonical_writes=0)
    with patch.object(db,'init_db',lambda cfg:[]),isolated_database(Config(ollama_url='http://localhost:1')) as cfg:
        backup._run_pg([backup._pg_bin('pg_restore',cfg),'--single-transaction','--exit-on-error','-d',db.dsn(cfg),str(dump)])
        with db.connect(cfg,role='owner') as conn:
            tables=sorted(manifest['tables'])
            actual=snapshot(conn,tables)
            assert actual==manifest['tables']
            assert len(conn.execute('SELECT filename FROM schema_migrations').fetchall())==16
            protected=[t for t in tables if t not in ('schema_migrations','audit_log')]
            before=snapshot(conn,protected);grants=privileges(conn)
            audit_ids=[r['id'] for r in conn.execute('SELECT id FROM audit_log ORDER BY id')]
            db.apply_migrations(conn,ROOT/'sql')
            assert db.apply_migrations(conn,ROOT/'sql')==[]
            assert before==snapshot(conn,protected)
            assert [r for r in privileges(conn) if r['table_name']!='thematic_summaries']==grants
            result['recovered_public_tables']=len(tables)
            result['nonempty_protected_tables']={t:before[t]['rows'] for t in protected}
        baseline=old_search(source)
        cases=[('provider-outages','/Users/peter/Agents/agentic-rag','infrastructure'),
               ('deployment-architecture','/Users/peter/Agents/Mac-Tech','infrastructure'),
               ('operational-lessons','/Users/peter/Agents/agentic-rag',None)]
        observations=[]
        for topic,project,domain in cases:
            with db.connect(cfg,role='writer') as writer:
                packet=store.refresh_summaries(writer,cfg,topic,project=project,domain=domain,context_chars=BUDGET)
                creation=packet['usage']
            timing={r:[] for r in ('before','after')};quality={r:[] for r in timing};first={}
            with db.connect(cfg,role='reader') as reader:
                # Independent full current eligible lexical oracle, document-only.
                oracle={str(r['id']) for r in reader.execute("""
                    SELECT DISTINCT d.id FROM documents d JOIN chunks c ON c.document_id=d.id
                    WHERE d.status='active' AND assertion_eligible(d.id,statement_timestamp())
                      AND d.project_scope=ANY(%s) AND (%s::text IS NULL OR d.domain=%s)
                      AND (c.tsv_en @@ websearch_to_tsquery('english',%s)
                        OR c.tsv_de @@ websearch_to_tsquery('german',%s))
                    """,(packet['scopes'],domain,domain,thematic.QUERIES[topic],thematic.QUERIES[topic]))}
                for n in range(repeats+1):
                    for route in (('before','after') if n%2==0 else ('after','before')):
                        start=time.perf_counter()
                        if route=='before':
                            hits,_=baseline(reader,cfg,thematic.QUERIES[topic],project=project,domain=domain,
                                strategy='lexical',rerank_mode='off',k=24)
                            lines=[];entries=[]
                            for h in hits:
                                line=f'- [{h.citation}] '+json.dumps(h.snippet,ensure_ascii=False)+'; '+json.dumps(h.evidence,sort_keys=True)
                                if len('\n'.join(lines+[line]))<=BUDGET:
                                    lines.append(line);entries.append(dict(document_id=h.document_id,chunk_id=h.chunk_id,
                                        start=h.snippet_start,end=h.snippet_end,text=h.snippet,citation=h.citation))
                            text='\n'.join(lines)
                        else:
                            packet=thematic.read(reader,cfg,topic,project=project,domain=domain,context_chars=BUDGET)
                            assert packet['status']=='fresh'
                            entries=packet['entries'];text=packet['context']
                        elapsed=(time.perf_counter()-start)*1000
                        check_citations(reader,entries)
                        observed={e['document_id'] for e in entries}
                        assert observed<=oracle
                        row=dict(eligible_document_coverage=len(observed),eligible_document_denominator=len(oracle),
                            context_chars=len(text),citation_errors=0,filter_errors=0)
                        if n==0: first[route]=round(elapsed,3)
                        else: timing[route].append(elapsed);quality[route].append(row)
                        reader.rollback()
            with db.connect(cfg,role='writer') as writer:
                refreshes=[];usage=[]
                for _ in range(repeats):
                    refreshed=store.refresh_summaries(writer,cfg,topic,project=project,domain=domain,context_chars=BUDGET)
                    refreshes.append(refreshed['usage']['elapsed_ms']);usage.append(refreshed['usage'])
                assert all(u['rebuilt']==0 for u in usage)
            observations.append(dict(topic=topic,context_budget=BUDGET,repetitions=repeats,creation=creation,
                routes={r:dict(stats(timing[r]),first_call_ms=first[r],raw_quality=quality[r]) for r in timing},
                unchanged_refresh=dict(stats(refreshes),raw_usage=usage)))
        with db.connect(cfg,role='owner') as conn:
            assert before==snapshot(conn,protected)
            assert set(audit_ids)<={r['id'] for r in conn.execute('SELECT id FROM audit_log')}
        result.update(strict_restore_inventory_match=True,all_original_protected_rows_preserved=True,
            historical_audits_retained=len(audit_ids),scenarios=observations,
            limits='Private verified snapshot, not the live corpus. Lexical eligible-document coverage is structural, '
                   'not a human semantic relevance or answer-quality score. First calls did not flush OS/DB caches. '
                   'The24-source pool and4800-character context intentionally expose partial coverage.')
    result['owned_copy_cleanup']='verified'
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=20);parser.add_argument('--trading',action='store_true')
    parser.add_argument('--private-recovery-dump',type=Path)
    parser.add_argument('--private-recovery-report',type=Path)
    args=parser.parse_args()
    if bool(args.private_recovery_dump)!=bool(args.private_recovery_report):
        raise ValueError('Private recovery requires both a verified dump and its inventory report')
    if not 1<=args.repeats<=30: raise ValueError('repeats must be1–30')
    paths=['agentic_rag/thematic.py','agentic_rag/profiles.py','agentic_rag/context.py','agentic_rag/store.py',
        'agentic_rag/cli.py','agentic_rag/mcp_server.py','sql/017_thematic_summaries.sql','scripts/verify_thematic_summaries.py']
    def hashes(): return {p:sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    frozen=hashes()
    dependencies=['search','retrieval','scope','evidence','validity','vector_plan','query_cache','embed','config','db']
    assert all(git('show',f'{BASE}:agentic_rag/{p}.py')==(ROOT/f'agentic_rag/{p}.py').read_bytes() for p in dependencies)
    result=dict(baseline_revision=BASE,candidate_revision=git('rev-parse','HEAD').decode().strip(),
        candidate_files_sha256=frozen,baseline_search_dependencies_unchanged=dependencies,synthetic=True,provider_calls=0,
        generated_at=datetime.now(timezone.utc).isoformat())
    with tempfile.TemporaryDirectory(prefix='thematic-acceptance-') as name:
        temp=Path(name);source=temp/'source';source.mkdir()
        subprocess.run(['tar','-xf','-','-C',str(source)],input=git('archive',BASE),check=True)
        initial=db.init_db
        with patch.object(db,'init_db',lambda cfg: initial(cfg,sql_dir=source/'sql')),isolated_database(Config(ollama_url='http://localhost:1')) as cfg:
            with db.connect(cfg,role='writer') as c,patch('agentic_rag.store.try_embed_texts',return_value=None): cases=seed(c,cfg)
            result['compatibility'],config=adoption(cfg,source,temp)
            with patch('agentic_rag.store.try_embed_texts',return_value=None):
                result['scenarios']=compare(cfg,cases,args.repeats,old_search(source))
            result['compatibility']['mcp']=[dict(route='candidate' if candidate else 'source/rollback',readonly=ro,
                **mcp_call(directory,config,ro,candidate)) for directory,candidate in ((source,False),(ROOT,True),(source,False)) for ro in (True,False)]
            result['candidate017_strict_backup_restore']=verified_backup(cfg,temp/'candidate017.dump')
            result['candidate017_strict_backup_restore'].pop('dump')
        if args.private_recovery_dump:
            result['private_snapshot_recovery']=private_recovery(args.private_recovery_dump,args.private_recovery_report,source,args.repeats)
    if args.trading: result['trading_reader']=trading()
    assert hashes()==frozen,'Measured sources changed; rerun on frozen bytes'
    result['hashes_match_after_measurement']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(dict(scenarios=3,upgrade=True,restore=True,output=str(args.output))))


if __name__=='__main__': main()
