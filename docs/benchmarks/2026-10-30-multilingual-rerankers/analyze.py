"""Reconstruct all metrics and denominators from retained observations."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics


def percentile(values,p):
    values=sorted(values)
    if not values:return None
    pos=(len(values)-1)*p;lo=math.floor(pos);hi=math.ceil(pos)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)


def times(values):
    return dict(n=len(values),p50_ms=percentile(values,.5),p95_ms=percentile(values,.95),
        p99_ms=percentile(values,.99),max_ms=max(values) if values else None)


def quality(rows):
    available=[r for r in rows if r['metrics'] is not None]
    result={'n':len(rows),'scored_n':len(available),'unavailable_n':len(rows)-len(available),
        'top1_count':sum(r['metrics']['top1'] for r in available),
        'all_sources3_count':sum(r['metrics']['all_sources3'] for r in available)}
    for k in ('top1','recall3','all_sources3','mrr','ndcg3'):
        result[k]=statistics.mean(r['metrics'][k] for r in available) if available else None
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('runs',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();models={};all_rows={}
    for name in ('minilm-l6','mmarco','jina-v2','jina-v3.5'):
        rows=[];starts=[];resources=[];events=[]
        for round_index in range(3):
            root=a.runs/f'{name}-r{round_index}'
            ex=json.loads((root/'exit.json').read_text());assert ex['exit']==0 and ex['child_stopped']
            rs=[json.loads(l) for l in (root/'observations.jsonl').read_text().splitlines()]
            assert len(rs)==(520 if round_index==0 else 76),(name,round_index,len(rs))
            for r in rs:
                if r['mode'] not in ('adapter','concurrency','exact-symbol-bypass'):
                    if r['error']:
                        assert r['error'] in ('ReadTimeout','ConnectTimeout','WriteTimeout','PoolTimeout') and r['metrics'] is None
                        continue
                    scores={v['index']:v['relevance_score'] for v in r['response']['results']}
                    order=[r['input'][i] for i in sorted(scores,key=lambda i:(-scores[i],i))]
                    assert order==r['order']
                if r['expected']:
                    gold=set(r['expected']);order=r['order']
                    expected=dict(top1=order[0] in gold,
                        recall3=len(set(order[:3])&gold)/len(gold),all_sources3=gold<=set(order[:3]),
                        mrr=1/next(i+1 for i,v in enumerate(order) if v in gold),
                        ndcg3=sum(1/math.log2(i+2) for i,v in enumerate(order[:3]) if v in gold)/sum(1/math.log2(i+2) for i in range(min(3,len(gold)))))
                    assert r['metrics']==expected,(name,r['case_id'])
            rows+=rs;starts.append(json.loads((root/'startup.json').read_text()))
            resources.append(ex['envelope_after'])
            events += [json.loads(l) for l in (root/'server-events.jsonl').read_text().splitlines()]
        all_rows[name]=rows
        primary=[r for r in rows if r['mode']=='quality' and r['permutation']==0]
        assert len(primary)==96
        summary={'observations':len(rows),'primary':{},'splits':{},'families':{},'cross_language':{},
            'long_context':{},'perturbations':{},'performance':{},'adapter':{},'concurrency':{},
            'position_changes':{},'unsupported':{},'failures':[],
            'process_ready':times([s['process_to_ready_ms'] for s in starts]),
            'first_request':times([r['elapsed_ms'] for r in rows if r['mode']=='cold-first']),
            'resources':resources,'native_score_order_changes':0,'native_outside_0_1':0}
        for r in rows:
            if r.get('response'):
                raw=r['response']['measurement']['native_scores']
                native=[r['input'][i] for i in sorted(range(len(raw)),key=lambda i:(-raw[i],i))]
                summary['native_score_order_changes']+=native!=r['order']
                summary['native_outside_0_1']+=any(not 0<=v<=1 for v in raw)
        summary['peak_server_rss_mib']=max(e['rss_peak_kib'] for e in events if 'rss_peak_kib' in e)/1024
        summary['inference_count']=sum(e['kind']=='inference' for e in events)
        for language in ('de','en'):
            subset=[r for r in primary if r['language']==language]
            summary['primary'][language]=quality(subset)
            for split in ('prior-diagnostic','new-unseen'):
                summary['splits'][language+'/'+split]=quality([r for r in subset if r['split']==split])
            summary['cross_language'][language]=quality([r for r in rows if r['mode']=='cross-language' and r['language']==language])
            reversed_rows={r['case_id']:r for r in rows if r['mode']=='quality' and r['permutation']==1 and r['language']==language}
            comparable=[r for r in subset if r['metrics'] is not None and reversed_rows[r['case_id']]['metrics'] is not None]
            summary['position_changes'][language]=dict(n=len(subset),both_scored_n=len(comparable),top1_changes=sum(r['order'][0]!=reversed_rows[r['case_id']]['order'][0] for r in comparable),
                full_order_changes=sum(r['order']!=reversed_rows[r['case_id']]['order'] for r in comparable),reverse_quality=quality(list(reversed_rows.values())))
            ars=[r for r in rows if r['mode']=='adapter' and r['language']==language]
            summary['adapter'][language]=dict(quality=quality(ars),timing=times([r['elapsed_ms'] for r in ars]),
                ranked_only_quality=quality([r for r in ars if r['diagnostics']['outcome']=='ranked']),
                outcomes=dict(Counter(r['diagnostics']['outcome'] for r in ars)),
                errors=dict(Counter(r['error'] for r in ars if r['error'])))
            unsupported=[r for r in rows if r['mode']=='unsupported' and r['language']==language]
            tops=sorted([max(v['relevance_score'] for v in r['response']['results']) for r in unsupported if r['response']])
            ordered=[sorted([v['relevance_score'] for v in r['response']['results']],reverse=True) for r in unsupported if r['response']]
            margins=[s[0]-s[1] for s in ordered]
            summary['unsupported'][language]=dict(n=len(unsupported),scored_n=len(tops),top_score_min=min(tops) if tops else None,top_score_median=statistics.median(tops) if tops else None,top_score_max=max(tops) if tops else None,
                all_top_scores=tops,all_top_two_margins=margins,
                interpretation='Uncalibrated; no threshold, cross-model confidence or answerability claim.')
        for r in primary:
            if r['metrics'] is None or not r['metrics']['top1'] or not r['metrics']['all_sources3']:
                summary['failures'].append(dict(case_id=r['case_id'],expected=r['expected'],order=r['order'],metrics=r['metrics']))
        for family in sorted({r['family'] for r in primary}):
            summary['families'][family]={lang:quality([r for r in primary if r['family']==family and r['language']==lang]) for lang in ('de','en')}
        for position in ('beginning','middle','end'):
            summary['long_context'][position]={lang:quality([r for r in rows if r['mode']=='long-context' and r['position']==position and r['language']==lang]) for lang in ('de','en')}
        original={r['case_id']:r for r in primary}
        for variant in ('whitespace','umlaut-ascii','unicode-nfd'):
            rs=[r for r in rows if r['mode']=='perturbation' and r['variant']==variant]
            comparable=[r for r in rs if r['metrics'] is not None and original[r['case_id']]['metrics'] is not None]
            summary['perturbations'][variant]=dict(quality=quality(rs),both_scored_n=len(comparable),
                top1_changes=sum(r['order'][0]!=original[r['case_id']]['order'][0] for r in comparable),
                full_order_changes=sum(r['order']!=original[r['case_id']]['order'] for r in comparable))
        for n,chars in ((6,120),(6,600),(6,1200),(12,600),(12,1200)):
            rs=[r for r in rows if r['mode']=='performance' and r['candidates']==n and r['target_chars']==chars]
            assert len(rs)==45
            summary['performance'][f'{n}x{chars}']=dict(http=times([r['elapsed_ms'] for r in rs]),
                successful_http=times([r['elapsed_ms'] for r in rs if r['error'] is None]),
                timeouts=sum(r['error'] is not None for r in rs),
                per_round={str(i):times([r['elapsed_ms'] for r in rs if r['round']==i]) for i in range(3)},
                preparation=times([r['response']['measurement']['prepare_ms'] for r in rs if r['response']]),
                preparation_scope='external pretruncation subtotal only' if name=='jina-v3.5' else 'complete ONNX input preparation',
                over_1500ms=sum(r['elapsed_ms']>1500 for r in rs))
        for n in (1,2,4):
            rs=[r for r in rows if r['mode']=='concurrency' and r['concurrency']==n]
            batches={r['repeat']:r for r in rs}
            summary['concurrency'][str(n)]=dict(requests=len(rs),timing=times([r['elapsed_ms'] for r in rs]),
                outcomes=dict(Counter(r['diagnostics']['outcome'] for r in rs)),
                makespan=times([r['makespan_ms'] for r in batches.values()]),
                native_drain=times([r['drain_ms'] for r in batches.values()]))
        bypass=[r for r in rows if r['mode']=='exact-symbol-bypass']
        assert len(bypass)==1 and bypass[0]['diagnostics']['outcome']=='bypass'
        models[name]=summary
    paired={}
    names=list(models)
    for i,left in enumerate(names):
        for right in names[i+1:]:
            key=left+' vs '+right;paired[key]={}
            for lang in ('de','en'):
                arows={r['case_id']:r for r in all_rows[left] if r['mode']=='quality' and r['permutation']==0 and r['language']==lang}
                brows={r['case_id']:r for r in all_rows[right] if r['mode']=='quality' and r['permutation']==0 and r['language']==lang}
                assert arows.keys()==brows.keys()
                common=[k for k in arows if arows[k]['metrics'] is not None and brows[k]['metrics'] is not None]
                counts=Counter((bool(arows[k]['metrics']['top1']),bool(brows[k]['metrics']['top1'])) for k in common)
                paired[key][lang]={'n':len(arows),'both_scored_n':len(common),'left_only_correct':counts[True,False],
                    'right_only_correct':counts[False,True],'both_correct':counts[True,True],'both_wrong':counts[False,False]}
    output=dict(models=models,paired=paired,total_observations=sum(len(r) for r in all_rows.values()),
        percentile='Linear interpolation at (n-1)*p; p99 of45 observations is descriptive, not stable tail capacity.')
    a.output.write_text(json.dumps(output,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    for name,m in models.items():
        print(name,'DE',m['primary']['de']['top1_count'],'/48 EN',m['primary']['en']['top1_count'],'/48',
            'scored DE/EN',m['primary']['de']['scored_n'],m['primary']['en']['scored_n'],
            'unavailable DE/EN',m['primary']['de']['unavailable_n'],m['primary']['en']['unavailable_n'],
            '6x600 p95ms',round(m['performance']['6x600']['http']['p95_ms'],2),
            'RSS MiB',round(m['peak_server_rss_mib'],1),'adapter',m['adapter']['de']['outcomes'])


if __name__=='__main__':
    main()
