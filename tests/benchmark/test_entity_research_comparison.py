"""Held-out reader comparison: genuine 0.6.23 against Issue69, synthetic only.

No retrieval stub is used. Timings are serial reader-engine timings (not public
end-to-end latency); process CPU excludes the PostgreSQL backend. Export only
when explicitly requested, never overwrite a checked-in measurement.
"""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
import types

from agentic_rag import domains, store
from agentic_rag.research import ResearchBudget, _research
from tests.test_research import claim

BASELINE = Path(__file__).resolve().parents[1]/'fixtures/research69/research-0.6.23.py.txt'
PROJECT='/projects/alpha'


def baseline():
    name='agentic_rag._research_baseline_0623'
    module=types.ModuleType(name)
    module.__file__=str(BASELINE)
    sys.modules[name]=module
    exec(compile(BASELINE.read_bytes(),str(BASELINE),'exec'),module.__dict__)
    return module._research


def test_held_out_reader_coverage_citations_and_resource_accounting(conn,cfg,monkeypatch):
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    cases=[]
    for hops,label,anchor in [(1,'single-hop','LyraBeacon'),(3,'multi-hop','VelaBeacon')]:
        target=claim(conn,cfg,f'{label}-resolution',f'{anchor} final resolution replaces the socket.')
        current=target
        for n in reversed(range(hops-1)):
            current=claim(conn,cfg,f'{label}-bridge-{n}',f'{anchor} routing source stage {n}.',
                edges=[store.EdgeSpec('references',current.slug,'source-backed routing proof','high')])
        seed=claim(conn,cfg,f'{label}-initial',f'{anchor} dependency handles initial incident.',
            edges=[store.EdgeSpec('references',current.slug,'source-backed incident pointer','high')])
        cases.append(dict(name=label,question=f'{anchor} dependency handles',domain='programming',
                          targets={target.doc_id},forbidden=set(),disagreement=False))
    domains.add_domain(conn,'general')
    for ambiguous,label,alias,target in [(False,'alias','lyra-retired','lyra'),(True,'ambiguous','vela-retired','vela')]:
        facts=[]
        for name,value in [(target,'8766')]+([(alias,'9000')] if ambiguous else []):
            saved=store.save_assertion(conn,cfg,entity=name,attribute='port',value=value,domain='general',
                project=PROJECT,event_at='2026-01-01T00:00:00Z',evidence={'namespace':'held-out-research',
                'source_id':name,'role':'user','quote':f'{name} port {value}','complete':True})
            assert saved.disposition=='accepted'
            facts.append(saved.doc_id)
        store.save_entity_alias(conn,cfg,alias=alias,target=target,domain='general',project=PROJECT,
            effective_at='2026-02-01T00:00:00Z',confirm=True,evidence={'namespace':'held-out-research',
            'source_id':label,'role':'user','quote':f'{alias} is another name for {target}.','complete':True})
        cases.append(dict(name=label,question=f'{alias} port',domain='general',
                          targets=set() if ambiguous else set(facts),forbidden=set(),disagreement=False))
    positive=claim(conn,cfg,'carina-old','CarinaBeacon deployment uses blue.')
    negative=claim(conn,cfg,'carina-new','CarinaBeacon dependency handles deployment using red.',
        edges=[store.EdgeSpec('contradicts',positive.slug,'mutually exclusive deployment values','high')])
    cases.append(dict(name='contradictory',question='CarinaBeacon dependency handles',domain='programming',
                      targets={positive.doc_id,negative.doc_id},forbidden=set(),disagreement=True))
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    rows=[]
    engines={'baseline':baseline(),'candidate':_research}
    for case in cases:
        for repeat in range(3):
            for label in (['baseline','candidate'] if repeat%2==0 else ['candidate','baseline']):
                cpu=time.process_time();started=time.perf_counter()
                result=engines[label](conn,cfg,case['question'],project=PROJECT,domain=case['domain'],
                    strategy='lexical',budget=ResearchBudget(steps=1))
                elapsed=time.perf_counter()-started;cpu=time.process_time()-cpu
                found={e['document_id'] for e in result['evidence']}
                assert not found & case['forbidden'],(case['name'],label,result)
                for item in result['evidence']:
                    original=conn.execute('SELECT content FROM chunks WHERE id=%s',(item['chunk_id'],)).fetchone()['content']
                    assert original[item['start']:item['end']]==item['text']
                unsupported=0
                by_citation={e['citation']:e for e in result['evidence']}
                for supported in result['supported']:
                    cited=[by_citation.get(c) for c in supported['citations']]
                    if not cited or any(e is None or supported['statement'] not in e['text'] for e in cited):
                        unsupported+=1
                        continue
                    proof=conn.execute("""SELECT count(DISTINCT e.source_key) n FROM claim_evidence e
                        JOIN knowledge_sources s USING(source_key) JOIN claim_records r USING(document_id)
                        WHERE e.document_id=ANY(%s::uuid[]) AND s.state='active' AND s.role='user'
                        AND e.complete AND e.reviewed AND r.kind='stated' AND r.review_state='confirmed'
                        AND strpos(e.quote,%s)>0""",
                        ([e['document_id'] for e in cited],supported['statement'])).fetchone()['n']
                    unsupported+=proof<2
                assert unsupported==0
                if case['name']=='ambiguous':
                    assert not result['supported']
                    assert not any(p['kind']=='entity' for e in result['evidence'] for p in e.get('paths',[]))
                assert result['abstained'] and result['usage']['provider_calls']==0
                assert result['usage']['calls']<=16 and result['usage']['steps']<=1
                assert len(result['context'])<=12000
                if case['disagreement']:
                    assert result['disagreement'] and not result['supported']
                rows.append(dict(case=case['name'],engine=label,repeat=repeat,elapsed_seconds=elapsed,
                    process_cpu_seconds=cpu,process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    relevant_originals=len(found & case['targets']),expected_originals=len(case['targets']),
                    supported=len(result['supported']),unsupported=unsupported,original_span_errors=0,
                    distinct_qualified_sources=len({s for e in result['evidence'] for s in e['source_keys']}),
                    calls=result['usage']['calls'],sql_statements=result.get('exploration',{}).get('sql_statements'),
                    examples=[{k:e[k] for k in ('text','citation','document_id','chunk_id','start','end')}
                              for e in result['evidence'] if e['document_id'] in case['targets']]))
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before
    for case in ('multi-hop','alias'):
        old=[r['relevant_originals'] for r in rows if r['case']==case and r['engine']=='baseline']
        new=[r['relevant_originals'] for r in rows if r['case']==case and r['engine']=='candidate']
        assert old==[0,0,0] and new==[1,1,1],(case,old,new)
    report=dict(source_revision='c33e11fd5ccc4fa1e11c92fbcd16e9fee0cbdcd9',
        baseline_sha256=hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
        methodology='Five held-out synthetic families; three repeats per engine, alternating order; real lexical SQL and gateways; no provider. Serial engine timings, not public endpoint latency. Process CPU/RSS exclude PostgreSQL.',
        rows=rows,summary={})
    for label in engines:
        selected=[r for r in rows if r['engine']==label];times=sorted(r['elapsed_seconds'] for r in selected)
        report['summary'][label]=dict(n=len(selected),p50_seconds=times[math.ceil(len(times)*.5)-1],
            p95_seconds=times[math.ceil(len(times)*.95)-1],process_cpu_seconds=sum(r['process_cpu_seconds'] for r in selected),
            relevant_originals=sum(r['relevant_originals'] for r in selected),
            expected_originals=sum(r['expected_originals'] for r in selected),unsupported=0,original_span_errors=0)
    destination=os.environ.get('RAG_RESEARCH_MEASUREMENT')
    if destination:
        Path(destination).write_text(json.dumps(report,indent=2)+'\n')
