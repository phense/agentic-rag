#!/usr/bin/env python3
"""Rehearse populated017→018 and measure public controlled entity scenarios.

Every mutation is on marker-owned disposable databases and uses audited gateways.
Private recovery is checksum-verified and outputs aggregates only. Trading is
reader-only. No hosted provider, deployment, configuration edit or service operation.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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

from psycopg import sql
from agentic_rag import backup, db, domains, entities, jobs, pins, profiles, search, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot
from scripts.verify_contextual_indexing import citation_check, snapshot, verified_backup
from scripts.verify_filter_aware_search import privileges, table_names

ROOT=Path(__file__).resolve().parents[1]
BASE='2a29c50a2fa435d2caeb3354da9dbce92e85e6bb'
PROJECT='/synthetic/entities/alpha'
OTHER='/synthetic/entities/beta'
BUDGET=4800
NEW_TABLES={'entity_identities','assertion_entities','entity_aliases'}
SOURCE_DEPENDENCIES=('search','retrieval','validity','evidence','scope','embed','config','db',
                     'vector_plan','contextual','query_cache','neural_rerank','thematic')


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def stats(values):
    return dict(p50_ms=round(statistics.median(values),3),
        p95_ms=round(sorted(values)[math.ceil(.95*len(values))-1],3),raw_ms=[round(v,3) for v in values])


def config_file(cfg,path):
    path.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[ollama]\nurl="http://localhost:1"\n')
    path.chmod(0o600)
    return path


def cli_call(source,config,args):
    env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config),AGENTIC_RAG_HOOKS_DISABLE='1')
    p=subprocess.run([sys.executable,'-m','agentic_rag.cli',*args],env=env,cwd=source,
        capture_output=True,text=True,check=True,timeout=30)
    return json.loads(p.stdout)


def source_search(source):
    spec=importlib.util.spec_from_file_location('agentic_rag._entities_source_search',source/'agentic_rag/search.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module.search


def inventories(conn,tables):
    return {table:{r['row'] for r in conn.execute(sql.SQL('SELECT to_jsonb(t)::text row FROM {} t')
        .format(sql.Identifier(table)))} for table in tables}


def assert_originals(conn,originals):
    current=inventories(conn,originals)
    assert all(rows<=current[table] for table,rows in originals.items()),'An original source row changed or disappeared'


@contextmanager
def restored(cfg,dump):
    with patch.object(db,'init_db',lambda c:[]),isolated_database(cfg) as owned:
        backup._run_pg([backup._pg_bin('pg_restore',cfg),'--single-transaction','--exit-on-error',
                       '-d',db.dsn(owned),str(dump)])
        yield owned


def seed(cfg,source,config):
    def fact(name,attribute,value,project=PROJECT,when='2026-01-01T00:00:00Z',relation='assertion',scope=None):
        args=['assert','--entity',name,'--attribute',attribute,'--value',value,'--domain','general',
            '--source-id',name+attribute+value+project,'--quote',f'{name} {attribute} is now {value}',
            '--event-at',when,'--relation',relation]
        args+=['--scope',scope] if scope else ['--project',project]
        result=cli_call(source,config,args)
        assert result['disposition']==('review' if scope=='unknown' else 'accepted')
        return result['doc_id']
    a=fact('orion','port','8766');b=fact('orion-old','tls','enabled')
    old=fact('cedar-old','status','stopped')
    current=fact('cedar-new','status','running',when='2026-03-01T00:00:00Z',relation='replacement')
    north=fact('gateway','status','north-running');south=fact('gateway','status','south-offline',project=OTHER)
    fact('unscoped','status','uncertain',scope='unknown')
    relations=[dict(alias='orion-old',target='orion',project=PROJECT),
               dict(alias='cedar-old',target='cedar-new',project=PROJECT),
               dict(alias='gateway-alt',target='gateway',project=PROJECT),
               dict(alias='gateway-alt',target='gateway',project=OTHER)]
    with db.connect(cfg,role='writer') as c,patch.object(store,'try_embed_texts',return_value=None):
        domains.add_domain(c,'infrastructure',actor='synthetic-user-b')
        domains.add_domain(c,'trading',actor='synthetic-user-a')
        for n,relation in enumerate(relations):
            quote=f"{relation['alias']} is another name for {relation['target']}."
            relation['evidence']=dict(namespace='synthetic-original-alias',source_id=str(n),role='user',quote=quote,complete=True)
            store.save_claim(c,cfg,title='Original operator alias evidence '+str(n),body=quote,domain='general',dtype='memory',
                project=relation['project'],claim_kind='stated',evidence=[relation['evidence']],actor='synthetic-user-a' if n%2 else 'synthetic-user-b')
        store.save_document(c,cfg,title='Another domain control',body='gateway-alt has an unrelated role.',
                            domain='infrastructure',dtype='memory',project=PROJECT)
        store.save_document(c,cfg,title='Global control',body='gateway-alt is a different global name.',domain='general',dtype='memory',scope='global')
        pins.add_pin(c,body='Exact synthetic standing rule.',scope=PROJECT,actor='synthetic-user-a')
        checkpoints.upsert_snapshot(c,CheckpointSnapshot(session_id='synthetic-entities',turn_id='t',cursor='c',source='test',
            trigger='manual',cwd=PROJECT,project_root=PROJECT,artifacts=('AGENTS.md',)))
        jobs.enqueue_curate(c,reason='Preserved synthetic queue work')
        profiles.refresh(c,cfg,PROJECT)
    cases=[dict(id='two-names',queries=[dict(name='orion-old',project=PROJECT,expected=[a,b])],denominator=2),
           dict(id='historical-rename-current-status',queries=[dict(name='cedar-old',attribute='status',project=PROJECT,
                expected=[current],stale=[old])],denominator=1),
           dict(id='same-names-independent-projects',queries=[dict(name='gateway-alt',attribute='status',project=PROJECT,expected=[north],foreign=[south]),
                dict(name='gateway-alt',attribute='status',project=OTHER,expected=[south],foreign=[north])],denominator=2)]
    return relations,cases


def pre018_clients(cfg,source,config):
    query=['search','orion-old','--project',PROJECT,'--domain','general','--strategy','lexical','--json']
    before=cli_call(source,config,query);candidate=cli_call(ROOT,config,query)
    assert [h['citation'] for h in before['results']]==[h['citation'] for h in candidate['results']]
    unavailable=cli_call(ROOT,config,['entity','resolve','orion-old','--project',PROJECT,'--domain','general'])
    assert unavailable['status']=='unavailable' and unavailable['facts']==[]
    saved=cli_call(ROOT,config,['assert','--entity','pre018-candidate','--attribute','port','--value','9011',
        '--domain','general','--source-id','pre018-candidate','--quote','port9011','--project',PROJECT,'--event-at','2026-01-01T00:00:00Z'])
    assert saved['disposition']=='accepted'
    with db.connect(cfg,role='writer') as c:
        packet=entities.read(c,'orion-old',domain='general',project=PROJECT)
        assert packet['status']=='unavailable' and c.execute('SELECT 1 ok').fetchone()['ok']==1
    return dict(candidate_legacy_cli_reads_writes_on017=True,entity_unavailable_without_aborted_connection=True,
        mcp=[mcp_call(ROOT,config,ro,True,schema018=False) for ro in (True,False)])


def adoption(cfg,source,temp):
    with db.connect(cfg,role='owner') as c:
        tables=table_names(c);before=snapshot(c,tables);grants=privileges(c);originals=inventories(c,tables)
        assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==17
    report=verified_backup(cfg,temp/'synthetic-source017.dump');report.pop('dump')
    with db.connect(cfg,role='owner') as c:
        c.execute((ROOT/'sql/018_entity_identities.sql').read_text());c.rollback()
        assert not entities.available(c);c.rollback()
        assert db.apply_migrations(c,ROOT/'sql')==['018_entity_identities.sql']
        assert db.apply_migrations(c,ROOT/'sql')==[]
        assert snapshot(c,tables)==before
        assert [r for r in privileges(c) if r['table_name'] not in NEW_TABLES]==grants
        assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==18
    with db.connect(cfg,role='writer') as c:
        interrupted=store.backfill_entity_identities(c,limit=2,commit=False)
        assert interrupted['mapped']==2;c.rollback()
        assert c.execute('SELECT count(*) n FROM assertion_entities').fetchone()['n']==0
        resumed=[]
        while True:
            packet=store.backfill_entity_identities(c,limit=2);resumed.append(packet)
            if packet['remaining']==0:break
        audit_count=c.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
        assert store.backfill_entity_identities(c)['mapped']==0
        assert c.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==audit_count
        assert_originals(c,originals)
    return dict(supported_source=BASE,source_schema=17,target_schema=18,strict_source_restore=report,
        interrupted_ddl_rollback=True,migration_retry_noop=True,original_rows_grants_preserved=True,
        interrupted_backfill_rollback=True,resumed_batches=resumed,noop_backfill_no_audit=True),originals


def compare(before_cfg,after_cfg,source,cases,repeats):
    baseline=source_search(source);results=[]
    for case in cases:
        samples={r:[] for r in ('before','after')};quality={r:[] for r in samples};first={}
        for n in range(repeats+1):
            for route in (('before','after') if n%2==0 else ('after','before')):
                elapsed=0;row=dict(correct_facts=0,denominator=case['denominator'],stale_current_facts=0,
                    foreign_facts=0,unexpected_assertions=0,citation_errors=0,context_chars=[],returned_facts=0)
                for query in case['queries']:
                    cfg=before_cfg if route=='before' else after_cfg
                    with db.connect(cfg,role='reader') as c:
                        start=time.perf_counter()
                        if route=='before':
                            text=query['name']+(' '+query['attribute'] if 'attribute' in query else '')
                            hits,warnings=baseline(c,cfg,text,domain='general',project=query['project'],k=8,
                                strategy='lexical',rerank_mode='off',as_of='2026-04-01T00:00:00Z')
                            api_elapsed=(time.perf_counter()-start)*1000
                            citation_check(c,hits)
                            lines=[];visible=[]
                            for h in hits:
                                line=f'- [{h.citation}] '+json.dumps(h.snippet,ensure_ascii=False)
                                if len('\n'.join(lines+[line]))<=BUDGET:
                                    lines.append(line);visible.append(h.document_id)
                            chars=len('\n'.join(lines));facts={h.document_id for h in hits if h.document_id in visible}
                        else:
                            packet=entities.read(c,query['name'],domain='general',project=query['project'],
                                attribute=query.get('attribute'),context_chars=BUDGET,as_of='2026-04-01T00:00:00Z')
                            api_elapsed=(time.perf_counter()-start)*1000
                            assert packet['status']=='resolved',packet['warnings']
                            facts=set()
                            for f in packet['facts']:
                                original=c.execute('SELECT content,document_id FROM chunks WHERE id=%s',(f['chunk_id'],)).fetchone()
                                assert original and str(original['document_id'])==f['document_id']
                                assert original['content'][f['start']:f['end']]==f['text']
                                assert f['citation']==f"{f['document_id']}#{f['chunk_id']}:{f['start']}-{f['end']}"
                                if f['citation'] in packet['context']:facts.add(f['document_id'])
                            chars=packet['context_chars']
                        elapsed+=api_elapsed
                        assert chars<=BUDGET
                        row['correct_facts']+=len(facts&set(query['expected']))
                        row['stale_current_facts']+=len(facts&set(query.get('stale',[])))
                        # Check every returned document against the literal scope/domain
                        # selector, and every returned assertion against the labeled
                        # fact oracle. Alias evidence notes are separately valid originals.
                        if facts:
                            returned=c.execute('SELECT d.id,d.project_scope,d.domain,a.document_id assertion_id FROM documents d'
                                ' LEFT JOIN fact_assertions a ON a.document_id=d.id WHERE d.id=ANY(%s::uuid[])',(list(facts),)).fetchall()
                            row['foreign_facts']+=sum(d['project_scope']!=query['project'] or d['domain']!='general' for d in returned)
                            row['unexpected_assertions']+=sum(d['assertion_id'] is not None and str(d['id']) not in query['expected'] for d in returned)
                        row['context_chars'].append(chars);row['returned_facts']+=len(facts)
                if n==0:first[route]=round(elapsed,3)
                else:samples[route].append(elapsed);quality[route].append(row)
        assert all(r['correct_facts']==case['denominator'] and not r['foreign_facts'] and not r['stale_current_facts'] and not r['unexpected_assertions'] for r in quality['after'])
        results.append(dict(scenario=case['id'],queries=[{k:v for k,v in q.items() if k in ('name','attribute','project')} for q in case['queries']],
            context_budget_per_query=BUDGET,as_of='2026-04-01T00:00:00Z',k_before=8,fact_limit_after=entities.FACT_LIMIT,repetitions=repeats,
            first_observation='API wall time, excluding citation/oracle validation and separate baseline context formatting; candidate formats context inside its API. First calls do not flush OS/DB caches. Warm paired route order alternates.',
            denominator_source='Literal source assertion IDs labeled before indexing/alias creation; independent of resolver eligibility.',
            routes={r:dict(stats(samples[r]),first_call_ms=first[r],raw_quality=quality[r]) for r in samples}))
    return results


def mcp_call(source,config,readonly,candidate,schema018=True):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def run():
        env=dict(os.environ,PYTHONPATH=str(source),AGENTIC_RAG_CONFIG=str(config),RAG_READONLY='1' if readonly else '0',AGENTIC_RAG_HOOKS_DISABLE='1')
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','agentic_rag.mcp_server'],env=env,cwd=str(source))) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize();tools=await session.list_tools();names={t.name for t in tools.tools}
                assert len(names)==((10 if readonly else 18) if candidate else (9 if readonly else 15))
                result=await session.call_tool('memory_search',dict(query='orion-old',project=PROJECT,domain='general',strategy='lexical'))
                assert not result.isError
                payload=result.structuredContent or json.loads(result.content[0].text);assert payload['results']
                if candidate:
                    result=await session.call_tool('memory_entity',dict(name='orion-old',project=PROJECT,domain='general'))
                    assert not result.isError
                    packet=result.structuredContent or json.loads(result.content[0].text)
                    assert packet['provider_calls']==0
                    if schema018:assert len(packet['facts'])==2
                    else:assert packet['status']=='unavailable' and packet['facts']==[]
                    assert ('memory_entity_alias' in names)==(not readonly)
                    bad=await session.call_tool('memory_entity',dict(name='orion-old',project=PROJECT,domain='general',history='true'))
                    assert bad.isError
                return dict(tool_count=len(names),write_tools_present='memory_save' in names,search_results=len(payload['results']))
    return asyncio.run(run())


def client_compatibility(cfg,source,config):
    query=['search','orion-old','--project',PROJECT,'--domain','general','--strategy','lexical','--json']
    packets=[cli_call(directory,config,query) for directory in (source,ROOT,source)]
    assert [h['citation'] for h in packets[0]['results']]==[h['citation'] for h in packets[1]['results']]==[h['citation'] for h in packets[2]['results']]
    old=cli_call(source,config,['assert','--entity','late-old-client','--attribute','port','--value','9001',
        '--domain','general','--source-id','late-client','--quote','port 9001','--project',PROJECT,'--event-at','2026-01-01T00:00:00Z'])
    with db.connect(cfg,role='reader') as c:
        initial=entities.read(c,'late-old-client',domain='general',project=PROJECT)
        assert initial['facts'][0]['document_id']==old['doc_id'] and not initial['identity_persisted']
        identity=initial['identity_id']
    with db.connect(cfg,role='writer') as c:
        assert store.backfill_entity_identities(c)['mapped']==1
    with db.connect(cfg,role='reader') as c:
        later=entities.read(c,'late-old-client',domain='general',project=PROJECT)
        assert later['identity_id']==identity and later['identity_persisted']
    return dict(source_candidate_source_citation_parity=True,old_client_new_assertion_readable=True,
        stable_id_before_after_backfill=True,mcp=[dict(route='candidate' if candidate else 'source/rollback',readonly=ro,
        **mcp_call(directory,config,ro,candidate)) for directory,candidate in ((source,False),(ROOT,True),(source,False)) for ro in (True,False)])


def overlapping_clients(source,config):
    observations=[]
    for n in range(3):
        gate=Barrier(2);target=f'overlap-host-{n}';alias=f'overlap-alias-{n}'
        quote=f'{alias} is another name for {target}, port 9010.'
        def run(route):
            arguments=(['assert','--entity',target,'--attribute','port','--value','9010','--domain','general',
                '--source-id','overlap-'+str(n),'--quote',quote,'--project',PROJECT,'--event-at','2026-01-01T00:00:00Z'] if route=='source'
                else ['entity','alias','--alias',alias,'--target',target,'--domain','general','--namespace','operator',
                '--source-id','overlap-'+str(n),'--quote',quote,'--complete','--confirm','--project',PROJECT,'--effective-at','2026-01-01T00:00:00Z'])
            gate.wait(timeout=5);start=time.monotonic()
            result=cli_call(source if route=='source' else ROOT,config,arguments)
            return start,time.monotonic(),result
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(run,['source','candidate']))
        assert outcomes[0][2]['disposition']=='accepted' and outcomes[1][2]['state']=='accepted'
        overlaps=max(v[0] for v in outcomes)<min(v[1] for v in outcomes)
        assert overlaps,'Processes did not overlap; concurrency evidence invalid'
        packet=cli_call(ROOT,config,['entity','resolve',alias,'--project',PROJECT,'--domain','general'])
        assert packet['facts'][0]['document_id']==outcomes[0][2]['doc_id']
        observations.append(dict(overlapping_intervals=overlaps,source_ms=round((outcomes[0][1]-outcomes[0][0])*1000,3),
            candidate_ms=round((outcomes[1][1]-outcomes[1][0])*1000,3),shared_original_source=True,current_fact_recovered=True))
    return dict(source_new_overlapping_rounds=3,observations=observations)


def private_recovery(dump,report):
    manifest=json.loads(report.read_text())
    if sha256(dump.read_bytes()).hexdigest()!=manifest['dump_sha256']:
        raise ValueError('Private backup checksum mismatch')
    result=dict(source_schema=17,target_schema=18,provider_calls=0,canonical_writes=0)
    with restored(Config(ollama_url='http://localhost:1'),dump) as cfg:
        with db.connect(cfg,role='owner') as c:
            tables=sorted(manifest['tables']);assert snapshot(c,tables)==manifest['tables']
            assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==17
            originals=inventories(c,tables);grants=privileges(c)
            assert db.apply_migrations(c,ROOT/'sql')==['018_entity_identities.sql']
            assert db.apply_migrations(c,ROOT/'sql')==[]
            assert [r for r in privileges(c) if r['table_name'] not in NEW_TABLES]==grants
        with db.connect(cfg,role='writer') as c:
            rounds=[]
            while True:
                packet=store.backfill_entity_identities(c,limit=100);rounds.append(packet)
                if not packet['remaining']:break
            audits=c.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
            assert store.backfill_entity_identities(c)['mapped']==0
            assert c.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==audits
            assert_originals(c,originals)
        result.update(strict_restore_inventory_match=True,original_rows_and_audits_preserved=True,original_grants_preserved=True,
            table_count=len(tables),original_counts={t:manifest['tables'][t]['rows'] for t in tables},backfill_batches=rounds,
            alias_links_created=0,noop_backfill_no_audit=True)
    result['owned_copy_cleanup']='verified'
    return result


def trading(repeats):
    cfg=load_config();observations=[]
    with db.connect(cfg,role='reader') as c:
        c.execute('SET TRANSACTION READ ONLY')
        count=c.execute("SELECT count(*) n FROM documents WHERE domain='trading'").fetchone()['n']
        for query in ('portfolio','earnings','regime'):
            samples=[];counts=[]
            for n in range(repeats+1):
                start=time.perf_counter()
                hits,_=search.search(c,cfg,query,domain='trading',project='/Users/peter/Agents/Trading',
                    strategy='lexical',rerank_mode='off',k=8)
                elapsed=(time.perf_counter()-start)*1000;citation_check(c,hits)
                if n:samples.append(elapsed);counts.append(len(hits))
                else:first=round(elapsed,3)
            observations.append(dict(query=query,first_call_ms=first,**stats(samples),valid_citation_counts=counts))
    return dict(document_count=count,application_writes=0,provider_calls=0,repetitions=repeats,observations=observations,
        limits='Live source017 ordinary retrieval controls only; no entity links created, production semantic gains not measured.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=20)
    p.add_argument('--trading',action='store_true');p.add_argument('--private-recovery-dump',type=Path);p.add_argument('--private-recovery-report',type=Path)
    args=p.parse_args()
    if not 1<=args.repeats<=30:raise ValueError('repeats must be1–30')
    if bool(args.private_recovery_dump)!=bool(args.private_recovery_report):raise ValueError('Private recovery requires dump and verification report')
    assert all(git('show',f'{BASE}:agentic_rag/{n}.py')==(ROOT/f'agentic_rag/{n}.py').read_bytes() for n in SOURCE_DEPENDENCIES)
    paths=sorted(str(path.relative_to(ROOT)) for directory in ('agentic_rag','sql','scripts')
        for path in (ROOT/directory).rglob('*') if path.is_file() and path.suffix in ('.py','.sql','.mjs')
        and '__pycache__' not in path.parts)
    def hashes():return {name:sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    frozen=hashes();result=dict(baseline_revision=BASE,candidate_revision=git('rev-parse','HEAD').decode().strip(),
        candidate_files_sha256=frozen,source_search_dependencies_unchanged=list(SOURCE_DEPENDENCIES),
        generated_at=datetime.now(timezone.utc).isoformat(),provider_calls=0,production_application_writes=0,synthetic_scenarios=True)
    with tempfile.TemporaryDirectory(prefix='entity-acceptance-') as name:
        temp=Path(name);source=temp/'source';source.mkdir()
        subprocess.run(['tar','-xf','-','-C',str(source)],input=git('archive',BASE),check=True)
        initial=db.init_db
        with patch.object(db,'init_db',lambda c:initial(c,sql_dir=source/'sql')),isolated_database(Config(ollama_url='http://localhost:1')) as cfg:
            config=config_file(cfg,temp/'config.toml');relations,cases=seed(cfg,source,config)
            result['pre018_clients']=pre018_clients(cfg,source,config)
            result['compatibility'],originals=adoption(cfg,source,temp)
            with restored(cfg,temp/'synthetic-source017.dump') as before_cfg:
                with db.connect(cfg,role='writer') as c,patch.object(store,'try_embed_texts',return_value=None):
                    for r in relations:
                        saved=store.save_entity_alias(c,cfg,**r,domain='general',effective_at='2026-02-01T00:00:00Z',confirm=True)
                        assert saved['state']=='accepted'
                result['scenarios']=compare(before_cfg,cfg,source,cases,args.repeats)
            result['clients']=client_compatibility(cfg,source,config)
            result['clients']['concurrent_source_new']=overlapping_clients(source,config)
            with db.connect(cfg,role='reader') as c:assert_originals(c,originals)
            final=verified_backup(cfg,temp/'synthetic-target018.dump');final.pop('dump');result['target018_strict_restore']=final
        if args.private_recovery_dump:result['private_snapshot_recovery']=private_recovery(args.private_recovery_dump,args.private_recovery_report)
    if args.trading:result['trading_reader']=trading(args.repeats)
    assert hashes()==frozen,'Measured implementation changed; rerun on frozen bytes'
    result['measured_hashes_unchanged']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(dict(scenarios=3,upgrade=True,restore=True,output=str(args.output))))


if __name__=='__main__':main()
