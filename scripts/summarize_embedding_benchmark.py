#!/usr/bin/env python3
"""Export native-only public-fixture evidence, keeping every missing denominator.

No model calls, private input, daemon keys or production configuration are read.
This does not turn a failed experiment into a pass or attest a served endpoint.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import gzip
import json
import math
from pathlib import Path
import statistics

from benchmark_embeddings import DEFAULT, denominators, evaluate, paired_comparison, query_groups, stats, truncate, write


def duplicate_summary(pairs,observations):
    observed={r['id']:r for r in observations}
    if len(observed)!=len(observations) or set(observed)-{p['id'] for p in pairs}:
        raise ValueError('duplicate or unknown pair observation')
    def count(rows):
        complete=[p for p in rows if p['id'] in observed]
        return {'n':len(rows),'completed':len(complete),'missing':len(rows)-len(complete),
            'positive':sum(p['same'] for p in rows),'negative':sum(not p['same'] for p in rows),
            'false_positive':sum(observed[p['id']]['predicted_same'] and not p['same'] for p in complete),
            'false_negative':sum(not observed[p['id']]['predicted_same'] and p['same'] for p in complete)}
    groups={}
    for p in pairs:
        kind='identical' if p['left']==p['right'] else 'paraphrase' if p['same'] else 'cross_language_negative'
        groups.setdefault(kind,[]).append(p)
    return {'as_frozen':count(pairs),'erratum_excluded':count([p for p in pairs if p['id']!='paraphrase-32']),
        'pair_types':{k:count(v) for k,v in groups.items()},'excluded_pair_ids':['paraphrase-32'],
        'interpretation':'Descriptive only; negatives are cross-language, threshold0.95 is not calibrated. Jina text-matching is not product retrieval dedup.'}


def hybrid_quality(corpus,rows):
    by_id={r['id']:r for r in rows}
    if len(by_id)!=len(rows) or set(by_id)-{q['id'] for q in corpus['queries']}:
        raise ValueError('duplicate or unknown hybrid query')
    observations=[];groups={}
    for q in corpus['queries']:
        observed=q['id'] in by_id
        row={'id':q['id'],'status':'completed' if observed else 'missing_inference','metrics':None}
        if observed:
            order=[r['id'] for r in by_id[q['id']]['hits']]
            if len(set(order))!=len(order):raise ValueError('duplicate hybrid document result')
            row['ranking']=by_id[q['id']]['hits']
            labels=q['relevance']
            if labels:
                rank=next((i+1 for i,id in enumerate(order) if id in labels),None)
                metrics={'mrr':1/rank if rank else 0.}
                gains=sorted((2**r-1 for r in labels.values()),reverse=True)
                for k in (1,3,5,10):
                    top=order[:k]
                    metrics[f'recall_at_{k}']=len(set(top)&labels.keys())/len(labels)
                    metrics[f'all_required_at_{k}']=int(all(set(group)&set(top) for group in q['required_groups']))
                    dcg=math.fsum((2**labels.get(id,0)-1)/math.log2(i+2) for i,id in enumerate(top))
                    ideal=math.fsum(g/math.log2(i+2) for i,g in enumerate(gains[:k]))
                    metrics[f'ndcg_at_{k}']=dcg/ideal
                row['metrics']=metrics
        observations.append(row)
        for group in query_groups(q):groups.setdefault(group,[]).append((q,row))
    means={}
    for name,group in groups.items():
        metrics=[r['metrics'] for q,r in group if r['metrics'] is not None]
        means[name]={'n':len(metrics),'denominators':denominators([q for q,r in group],by_id)}
        if metrics:means[name].update({key:statistics.mean(r[key] for r in metrics) for key in metrics[0]})
    return {'complete':len(by_id)==len(corpus['queries']),'denominators':denominators(corpus['queries'],by_id),
        'groups':means,'observations':observations,'interpretation':'Managed hybrid IDs over exact native-vector replay. Lifecycle and ranking consistency only; no served-endpoint quality or adoption evidence. Completed empty results count as zero coverage.'}


def load(path):return json.loads(path.read_text())


def publish_raw(roots,destination):
    """Copy exact public-fixture artifacts; never traverse private daemon homes."""
    destination=Path(destination);destination.mkdir(mode=0o700)
    manifest=[]
    for name,root in roots.items():
        if name not in {'primary','small-corrected','canonical'}:raise ValueError('unknown public run label')
        paths=['terminal.json','inputs-before.json','inputs-after.json','planned-runs.json','attempts.json']
        for model in ('bge','nano','small'):
            for repeat in range(3):
                label=f'{model}-r{repeat}'
                paths.extend(label+suffix for suffix in ('.log','-exit.json','-resources.jsonl'))
                paths.extend(label+'/'+file for file in ('worker-result.json','result.json','vectors.json','observations.jsonl'))
        for relative in paths:
            source=Path(root)/relative
            if source.is_symlink() or not source.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError('symlink or escaped public artifact')
            if not source.is_file():continue
            data=source.read_bytes();compressed=relative.endswith(('vectors.json','-resources.jsonl'))
            target=destination/name/(relative+'.gz' if compressed else relative)
            target.parent.mkdir(parents=True,exist_ok=True)
            encoded=gzip.compress(data,compresslevel=6,mtime=0) if compressed else data
            with target.open('xb') as stream:stream.write(encoded)
            manifest.append({'source':name+'/'+relative,'archive':str(target.relative_to(destination)),
                'source_sha256':hashlib.sha256(data).hexdigest(),'archive_sha256':hashlib.sha256(encoded).hexdigest(),
                'source_bytes':len(data),'archive_bytes':len(encoded)})
    write(destination/'manifest.json',manifest)
    return manifest


def run(args):
    out=Path(args.output);out.mkdir(mode=0o700)
    fixtures=Path(args.fixtures)
    inputs={};report={'status':'failed','started':datetime.now(timezone.utc).isoformat(),
        'native_only':True,'adoption_or_served_endpoint_parity':False,'model_timing_from_replay':False,
        'primary':{},'canonical':{},'paired':{},'inputs':inputs}
    def read(path):
        data=path.read_bytes();inputs[str(path)]=hashlib.sha256(data).hexdigest();return json.loads(data)
    try:
        if args.hybrid and not args.canonical_root:raise ValueError('rehearsal requires --canonical-root')
        corpus=read(fixtures/'corpus.json');protocol=read(fixtures/'protocol.json')
        errata=read(fixtures/'errata.json')
        if errata.get('dedup_label',{}).get('id','paraphrase-32')!='paraphrase-32':raise ValueError('unsupported dedup erratum')
        roots={'bge':Path(args.primary_root),'nano':Path(args.primary_root),'small':Path(args.small_root)}
        for root in set(roots.values()):
            terminal=read(root/'terminal.json')
            if not terminal.get('finished') or not terminal['inputs_unchanged']:raise ValueError('experiment is nonterminal or inputs changed')
        for model,root in roots.items():
            runs=[]
            for repeat in range(3):
                label=f'{model}-r{repeat}';target=root/label
                attempted=target.exists() or any((root/(label+suffix)).exists() for suffix in ('-resources.jsonl','-exit.json','.log'))
                row={'label':label,'status':'incomplete-no-result' if attempted else 'unattempted','quality':None}
                result={}
                if (target/'worker-result.json').exists():
                    result=read(target/'worker-result.json');row.update(status=result['status'],result=result)
                row['dedup']=duplicate_summary(corpus['duplicate_pairs'],result.get('duplicates',{}).get('observations',[]))
                if (target/'vectors.json').exists():
                    if not result:row['status']='incomplete-no-result'
                    vectors=read(target/'vectors.json')
                    if set(vectors['documents'])=={d['id'] for d in corpus['documents']}:
                        row['quality']=evaluate(corpus,vectors['documents'],vectors['queries'],protocol['models'][model]['dimensions'])
                samples=root/(label+'-resources.jsonl')
                if samples.exists():
                    data=samples.read_bytes();inputs[str(samples)]=hashlib.sha256(data).hexdigest()
                    rows=[json.loads(line) for line in data.splitlines()]
                    row['resources']={'sample_interval_seconds':.5,'samples':len(rows),
                        'peak_sampled_tree_rss_bytes':max((r['tree_rss_bytes'] for r in rows),default=None),
                        'minimum_sampled_mem_available_bytes':min((r['mem_available_bytes'] for r in rows),default=None),
                        'cpu_efficiency_claim':False}
                exit_path=root/(label+'-exit.json')
                if exit_path.exists():
                    row['supervisor']=read(exit_path)
                    if row['supervisor']['exit_code']!=0 or row['supervisor'].get('supervisor_stop'):
                        row['status']='failed'
                observations=target/'observations.jsonl'
                if observations.exists():
                    data=observations.read_bytes();inputs[str(observations)]=hashlib.sha256(data).hexdigest()
                    observed=[json.loads(line) for line in data.splitlines()]
                    row['recorded_query_seconds']=stats([r['seconds'] for r in observed])
                runs.append(row)
            report['primary'][model]={'planned_repetitions':3,'runs':runs}
        baseline=report['primary']['bge']['runs'][0]['quality']
        for model in ('nano','small'):
            candidate=report['primary'][model]['runs'][0]['quality']
            statuses={n:report['primary'][n]['runs'][0]['status'] for n in ('bge',model)}
            if baseline is not None and candidate is not None and set(statuses.values())=={'complete'}:
                report['paired']['primary:'+model]={**paired_comparison(corpus,baseline,candidate),'run_statuses':statuses}
        if args.canonical_root:
            root=Path(args.canonical_root);terminal=read(root/'terminal.json')
            if not terminal.get('finished') or not terminal['inputs_unchanged']:raise ValueError('nonterminal canonical pass')
            spec=read(fixtures/'canonical-inputs-v2.json')
            canonical_hash=inputs[str(fixtures/'canonical-inputs-v2.json')]
            for model in ('bge','nano','small'):
                target=root/(model+'-r0');row={'status':'unattempted','slices':{}}
                proven=False
                if (target/'result.json').exists():
                    result=read(target/'result.json')
                    if result['input_sha256']!=canonical_hash:raise ValueError('canonical input hash mismatch')
                    row.update(status=result['status'],result=result)
                    proven=True
                elif target.exists() or (root/(model+'-r0-exit.json')).exists():
                    row['status']='incomplete-no-result'
                if (root/(model+'-r0-exit.json')).exists():
                    row['supervisor']=read(root/(model+'-r0-exit.json'))
                    if row['supervisor']['exit_code']!=0 or row['supervisor'].get('supervisor_stop'):row['status']='failed'
                if proven and (target/'vectors.json').exists():
                    vectors=read(target/'vectors.json')
                    if set(vectors['documents'])=={d['id'] for d in spec['documents']}:
                        for name,queries in [('original',[q for q in spec['queries'] if q['split']!='independent-heldout']),
                                             ('independent',[q for q in spec['queries'] if q['split']=='independent-heldout'])]:
                            c={'documents':spec['documents'],'queries':queries};ids={q['id'] for q in queries}
                            qv={id:v for id,v in vectors['queries'].items() if id in ids};width=protocol['models'][model]['dimensions']
                            row['slices'][name]=evaluate(c,vectors['documents'],qv,width)
                            if model!='bge':row['slices'][name+'-256']=evaluate(c,
                                {id:truncate(v,256) for id,v in vectors['documents'].items()},
                                {id:truncate(v,256) for id,v in qv.items()},256)
                report['canonical'][model]=row
            for name in ('original','independent'):
                queries=[q for q in spec['queries'] if (q['split']=='independent-heldout')==(name=='independent')]
                c={'queries':queries};base=report['canonical']['bge']['slices'].get(name)
                for model in ('nano','small'):
                    cand=report['canonical'][model]['slices'].get(name)
                    statuses={n:report['canonical'][n]['status'] for n in ('bge',model)}
                    if base is not None and cand is not None and set(statuses.values())=={'complete'}:
                        report['paired']['canonical:'+name+':'+model]={**paired_comparison(c,base,cand),'run_statuses':statuses}
            if args.hybrid:
                hybrid=read(Path(args.hybrid))
                if hybrid['status']!='complete':raise ValueError('lifecycle rehearsal not complete')
                if hybrid.get('input_sha256')!=canonical_hash:raise ValueError('rehearsal canonical inputs differ')
                script=Path(__file__).parent/'rehearse_embedding_substitution.py'
                if hybrid.get('rehearsal_script_sha256')!=hashlib.sha256(script.read_bytes()).hexdigest():raise ValueError('rehearsal code differs')
                if set(hybrid.get('models',[]))!=set(hybrid['hybrid']):raise ValueError('rehearsal model list differs')
                if set(hybrid.get('unrehearsed_models',[]))!=set(('bge','nano','small'))-set(hybrid['hybrid']):raise ValueError('rehearsal missing-model list differs')
                report['hybrid']={m:{'status':'unrehearsed'} for m in ('bge','nano','small')}
                for model,rows in hybrid['hybrid'].items():
                    if model not in report['canonical'] or report['canonical'][model]['status']!='complete':raise ValueError('replay model is incomplete')
                    actual={name:inputs[str(root/(model+'-r0')/name)] for name in ('result.json','vectors.json')}
                    if hybrid.get('replay_inputs',{}).get(model)!=actual:raise ValueError('replay vector or result identity differs')
                    report['hybrid'][model]={}
                    for name in ('original','independent'):
                        queries=[q for q in spec['queries'] if (q['split']=='independent-heldout')==(name=='independent')]
                        ids={q['id'] for q in queries}
                        report['hybrid'][model][name]=hybrid_quality({'queries':queries},[r for r in rows if r['id'] in ids])
        report['errata']=errata
        if getattr(args,'copy_raw',False):
            sources={'primary':Path(args.primary_root),'small-corrected':Path(args.small_root)}
            if args.canonical_root:sources['canonical']=Path(args.canonical_root)
            report['public_raw']=publish_raw(sources,out/'raw')
        report['exporter_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report['scorer_sha256']=hashlib.sha256((Path(__file__).parent/'benchmark_embeddings.py').read_bytes()).hexdigest()
        report['status']='complete-export; experiment statuses are reported independently'
    except Exception as exc:
        report['failure']={'class':type(exc).__name__,'message':str(exc)[:1000]};raise
    finally:
        report['finished']=datetime.now(timezone.utc).isoformat();write(out/'report.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('primary-root','small-root','output'):parser.add_argument('--'+field,required=True)
    parser.add_argument('--fixtures',default=str(DEFAULT))
    parser.add_argument('--canonical-root');parser.add_argument('--hybrid')
    parser.add_argument('--copy-raw',action='store_true')
    run(parser.parse_args())
