"""Reproduce the public Issue62 fixture without private data or provider access."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


def build():
    root=Path(__file__).resolve().parents[1]
    old=json.loads((root/'agentic_rag/benchmark/corpus-failures-v1.json').read_text())
    families={'dev-failure-0','dev-failure-1'}
    result={k:deepcopy(v) for k,v in old.items() if k not in ('documents','queries')}
    result.update(name='reranker-failures-v2',source_revision='RAG062-public-v2-from-7a61955',
        documents=[d for d in old['documents'] if d['family'] in families],
        queries=[q for q in old['queries'] if q['family'] in families])
    prior=root/'docs/benchmarks/2026-10-04-failure-evaluation/evaluation/dev-results.json'
    rows=json.loads(prior.read_text())['profiles'][0]['rows']
    failed={r['query_id']:r for r in rows if not r['extractive_correct']}
    result['attribution']={'prior_revision':'5b390692e32e07c8816e98091dfa66e15e0c2cb3',
        'prior_report':str(prior.relative_to(root)),'prior_report_sha256':sha256(prior.read_bytes()).hexdigest(),
        'prior_profile':'search-title-0','confirmed_dev_failures':[
            {'query_id':q['id'],'prior_missing_expected_ids':failed[q['id']]['missing_expected_ids'],
             'prior_extractive_correct':False} for q in result['queries'] if q['id'] in failed],
        'limits':'Public previously observed synthetic failures only. Fresh held-out families are representative controls, not new confirmed real failures. Shared authoring templates limit generalization.'}
    def add_family(family,split,subject):
        project='/synthetic/reranker/'+family
        common=dict(project=project,domain='general',actor='fixture-author',family=family,split=split)
        shared=subject+' delivery recovery verification procedure. '+subject+' Zustellung Wiederherstellung Pruefung Verfahren. '
        docs=[('delivery',subject+' delivery verification',
               shared+'Delivery is verified by checking the dated receipt, not the sender success message. '+
               'Die Zustellung wird durch den datierten Empfangsbeleg geprueft.'),
              ('restore',subject+' recovery verification',
               shared+'Recovery is verified by restoring a copy and checking its original-row hashes. '+
               'Zur Wiederherstellung wird eine Kopie wiederhergestellt und ihr urspruenglicher Zeilenhash geprueft.')]
        for i in range(4):
            docs.append(('distractor-'+str(i),subject+' delivery recovery verification procedure '+str(i),
                shared+'This index entry names the procedure but describes no steps. '+
                'Dieser Indexeintrag nennt das Verfahren und beschreibt keine Pruefschritte. '+str(i)))
        for suffix,title,body in docs:
            if suffix=='restore':title=family+'-restore'
            result['documents'].append(dict(id=family+'-'+suffix,title=title,body=body,**common))
        for suffix,value,when in [('old','stopped','2026-01-01T00:00:00Z'),('current','running','2026-03-01T00:00:00Z')]:
            result['documents'].append(dict(id=family+'-'+suffix,title=subject+': status',
                body=subject+' status is now '+value+'.',assertion=dict(entity=subject,attribute='status',
                value=value,event_at=when,relation='replacement' if suffix=='current' else 'assertion'),**common))
        result['documents'].append(dict(id=family+'-status-notes',title=subject+' current status notes',
            body=subject+' current status notes contain no accepted status value.',**common))
        for lang,query in [('en',subject+' status')]:
            result['queries'].append(dict(id=family+'-temporal-'+lang,query=query,
                expected_ids=[family+'-current'],answers=['running'],expected_snippets=['running'],
                stale_answers=['stopped'],stale_ids=[family+'-old'],unanswerable=False,
                category='temporal',language=lang,as_of='2026-04-01T00:00:00Z',
                **{k:v for k,v in common.items() if k!='actor'}))
        for lang,query in [('en',subject+' delivery verification procedure'),
                           ('de',subject+' Zustellung Pruefung Verfahren')]:
            result['queries'].append(dict(id=family+'-delivery-'+lang,query=query,expected_ids=[family+'-delivery'],
                answers=['dated receipt'],expected_snippets=['dated receipt'],stale_answers=[],
                unanswerable=False,category='ordering',language=lang,as_of='2026-04-01T00:00:00Z',
                **{k:v for k,v in common.items() if k!='actor'}))
        for lang,query in [('en',subject+' delivery recovery verification procedure'),
                           ('de',subject+' Zustellung Wiederherstellung Pruefung Verfahren')]:
            result['queries'].append(dict(id=family+'-multi-'+lang,query=query,
                expected_ids=[family+'-delivery',family+'-restore'],answers=['dated receipt','original-row hashes'],
                expected_snippets=['dated receipt','original-row hashes'],stale_answers=[],unanswerable=False,
                category='multi-source',language=lang,as_of='2026-04-01T00:00:00Z',
                **{k:v for k,v in common.items() if k!='actor'}))
        result['queries'].append(dict(id=family+'-identifier',query=family+'-restore',
            expected_ids=[family+'-restore'],answers=['original-row hashes'],expected_snippets=['original-row hashes'],
            stale_answers=[],unanswerable=False,category='identifier',language='en',as_of='2026-04-01T00:00:00Z',
            **{k:v for k,v in common.items() if k!='actor'}))
        # An unsupported concept is intentionally not answered by model scores.
        result['queries'].append(dict(id=family+'-unsupported',query='What is the '+subject+' quantum capacity?',
            expected_ids=[],answers=[],expected_snippets=[],stale_answers=[],unanswerable=True,
            category='unanswerable',language='en',as_of='2026-04-01T00:00:00Z',
            **{k:v for k,v in common.items() if k!='actor'}))
    add_family('dev-orbit','dev','orbital')
    for family,subject in [('test-spruce','spruce'),('test-amber','amber'),('test-falcon','falcon')]:
        add_family(family,'test',subject)
    return result


if __name__=='__main__':
    target=Path(__file__).resolve().parents[1]/'agentic_rag/benchmark/corpus-reranker-v2.json'
    target.write_text(json.dumps(build(),indent=2,ensure_ascii=False)+'\n')
