"""Frozen public DE/EN diagnostic, isolated native models; no database or adoption."""
from pathlib import Path
import argparse,hashlib,json,math,os,random,shutil,socket,statistics,subprocess,time
from types import SimpleNamespace
import httpx
from agentic_rag import neural_rerank
from agentic_rag.config import Config
from agentic_rag.benchmark.rerank_evaluation import _drain,reference_snapshot,sources,TINY_MODEL,TINY_REVISION
from scripts.rehearse_reranker import digest,stop_owned,remaining_group_members,QWEN_SHA


def write(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')


def validate(corpus):
    assert len(corpus['cases'])==32 and corpus['permutations']==2
    assert len({c['id'] for c in corpus['cases']})==32
    assert len({c['family'] for c in corpus['cases']})==8
    assert len({c['query'] for c in corpus['cases']})==32
    for c in corpus['cases']:
        assert c['language'] in ('de','en') and len(c['passages'])==6
        ids=[p['id'] for p in c['passages']];assert len(set(ids))==6
        assert c['expected'] and set(c['expected'])<=set(ids)
        assert all(0<len(p['text'])<=599 for p in c['passages'])
        hits=[SimpleNamespace(document_id=i,score=1.0) for i in range(6)]
        assert neural_rerank.eligible(c['query'],hits),c['id']
    for pair in {c['pair'] for c in corpus['cases']}:
        a,b=[c for c in corpus['cases'] if c['pair']==pair]
        assert {a['language'],b['language']}=={'de','en'} and a['expected']==b['expected']


def metrics(order,expected):
    gold=set(expected);top=order[:3]
    gain=sum(1/math.log2(i+2) for i,name in enumerate(top) if name in gold)
    ideal=sum(1/math.log2(i+2) for i in range(min(3,len(gold))))
    return dict(top1=order[0] in gold,recall3=len(set(top)&gold)/len(gold),
        all_sources3=gold<=set(top),ndcg3=gain/ideal)


def permutation(case,iteration):
    order=list(range(6));random.Random(case['pair']).shuffle(order)
    if iteration:order.reverse()
    return [case['passages'][i] for i in order]


def raw_score(client,url,alias,case,passages,capture):
    with client.stream('POST',url+'/v1/rerank',json=dict(model=alias,query=case['query'],documents=[p['text'] for p in passages],top_n=6,return_documents=False)) as response:
        response.raise_for_status();body=bytearray()
        for part in response.iter_bytes():
            if len(body)+len(part)>32768:raise ValueError('response_size')
            body.extend(part)
    with capture.open('xb') as stream:stream.write(body)
    data=json.loads(body);scores={}
    if data.get('model')!=alias or len(data.get('results',[]))!=6:raise ValueError('model_or_count')
    for row in data['results']:
        i,s=row.get('index'),row.get('relevance_score')
        if type(i) is not int or not 0<=i<6 or i in scores or type(s) not in (int,float) or not math.isfinite(s):raise ValueError('scores')
        scores[i]=s
    return [passages[i]['id'] for i in sorted(scores,key=lambda i:(-scores[i],i))],scores


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',required=True,type=Path)
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--models',choices=['tiny','both'],default='both')
    for name in ('runtime','qwen','tiny','output','work-dir'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args();corpus=json.loads(args.corpus.read_text());validate(corpus)
    if args.validate_only:print('Validated32cases/16DE+16EN/8families;allquerieseligible.');return 0
    assert all(getattr(args,k) is not None for k in ('runtime','qwen','tiny','output','work_dir'))
    caps=reference_snapshot();group=Path('/proc/self/cgroup').read_bytes();processes=[];rows=[];errors=[];code=1
    frozen=dict(source=sources(),helper=digest(Path(__file__)),corpus=digest(args.corpus),runtime=digest(args.runtime),libraries={p.name:digest(p) for p in args.runtime.parent.glob('*.so*') if p.is_file()})
    if frozen['runtime']!='dbfeea380cdc1de9bbfe32399befbcd8381a3c5ac83e573d79d0fa41bdc40037':raise ValueError('runtime_checksum')
    frozen['runtime_version']=subprocess.check_output([str(args.runtime),'--version'],stderr=subprocess.STDOUT,text=True).strip()
    for p in (args.output,args.work_dir):
        if any(q.is_symlink() for q in (p,*p.parents)):raise ValueError('symlink_path')
        p.mkdir(parents=True,exist_ok=False,mode=0o700)
    selected=['tiny'] if args.models=='tiny' else ['tiny','qwen']
    for name,expected in [('tiny',TINY_REVISION),('qwen',QWEN_SHA)]:
        if name not in selected:continue
        p=getattr(args,name)
        if digest(p)!=expected:raise ValueError('model_checksum')
        target=args.work_dir/(name+'.gguf');shutil.copyfile(p,target)
        if digest(target)!=expected:raise ValueError('model_copy')
        setattr(args,name,target)
    write(args.output/'seal.json',dict(frozen=frozen,models={n:QWEN_SHA if n=='qwen' else TINY_REVISION for n in selected},evaluated_models=selected,decision_rule=corpus['decision_rule'],reference_before=caps,source_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))
    try:
        endpoints={};membership={}
        for name,alias,port in [('tiny',TINY_MODEL,8772),('qwen',neural_rerank.MODEL,8773)]:
            if name not in selected:continue
            with socket.socket() as sock:sock.bind(('127.0.0.1',port))
            with (args.output/(name+'.log')).open('xb') as log:
                process=subprocess.Popen([str(args.runtime),'--model',str(getattr(args,name)),'--host','127.0.0.1','--port',str(port),'--rerank','--pooling','rank','--ctx-size','4096','--parallel','1','--threads','4','--threads-batch','4','--threads-http','2','--alias',alias,'--offline','--no-webui','--log-disable'],stdout=log,stderr=log)
            processes.append((name,process));url='http://127.0.0.1:'+str(port);endpoints[name]=(url,alias)
            with httpx.Client(trust_env=False,timeout=1) as client:
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('model_startup')
                    try:
                        if client.get(url+'/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise TimeoutError('model_health')
                if not any(m['id']==alias for m in client.get(url+'/v1/models').json()['data']):raise ValueError('model_identity')
            affinity=sorted(os.sched_getaffinity(process.pid))
            if Path(f'/proc/{process.pid}/cgroup').read_bytes()!=group or affinity!=[0,1,2,3]:raise ValueError('model_envelope')
            membership[name]=dict(same_cgroup=True,affinity=affinity)
        with (args.output/'observations.jsonl').open('x') as stream,httpx.Client(trust_env=False,follow_redirects=False,timeout=30) as client:
            for case in corpus['cases']:
                for iteration in range(2):
                    passages=permutation(case,iteration)
                    for name in selected:
                        url,alias=endpoints[name];before=time.perf_counter();error=None;scores=None
                        try:ranked,scores=raw_score(client,url,alias,case,passages,args.output/('raw-'+str(len(rows))+'.json'))
                        except Exception as exc:ranked=[p['id'] for p in passages];error=type(exc).__name__
                        elapsed=(time.perf_counter()-before)*1000;drain=_drain(url)
                        row=dict(case_id=case['id'],pair=case['pair'],family=case['family'],language=case['language'],permutation=iteration,model=name,mode='semantic30s',input=[p['id'] for p in passages],order=ranked,scores=scores,production_score_range_compatible=all(0<=v<=1 for v in scores.values()) if scores is not None else False,expected=case['expected'],metrics=metrics(ranked,case['expected']),elapsed_ms=elapsed,error=error,drain=drain)
                        rows.append(row);stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
                        if iteration==0:
                            cfg=Config(rerank_url=url,rerank_model=alias,rerank_revision=TINY_REVISION if name=='tiny' else QWEN_SHA,rerank_policy='focused-v1')
                            hits=[SimpleNamespace(document_id=int(p['id']),score=1.0,title='',snippet=p['text']) for p in passages]
                            before=time.perf_counter();info={};error=None
                            try:result=neural_rerank.order(case['query'],hits,cfg,diagnostics=info)
                            except Exception as exc:result=hits;error=type(exc).__name__
                            elapsed=(time.perf_counter()-before)*1000;drain=_drain(url)
                            assert {id(h) for h in result}=={id(h) for h in hits}
                            ranked=[str(h.document_id) for h in result]
                            row=dict(case_id=case['id'],pair=case['pair'],family=case['family'],language=case['language'],permutation=0,model=name,mode='adapter1.5s',input=[p['id'] for p in passages],order=ranked,expected=case['expected'],metrics=metrics(ranked,case['expected']),elapsed_ms=elapsed,error=error,diagnostics=info,drain=drain)
                            rows.append(row);stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
                print(case['id'],len(rows),'observations',flush=True)
        assert len(rows)==96*len(selected)
        if any(r['error'] for r in rows if r['mode']=='semantic30s'):raise ValueError('raw_scoring_errors')
        if sources()!=frozen['source'] or digest(Path(__file__))!=frozen['helper'] or digest(args.corpus)!=frozen['corpus'] or digest(args.runtime)!=frozen['runtime']:raise ValueError('frozen_drift')
        if {p.name:digest(p) for p in args.runtime.parent.glob('*.so*') if p.is_file()}!=frozen['libraries']:raise ValueError('library_drift')
        if any(digest(getattr(args,n))!=(QWEN_SHA if n=='qwen' else TINY_REVISION) for n in selected):raise ValueError('model_drift')
        write(args.output/'results.json',dict(frozen=frozen,evaluated_models=selected,membership=membership,rows=rows,limits=['32authoredparallelquestions,8families;16DE+16EN,notpopulationaccuracy.','Primaryqualityusesfirstpermutation;secondpermutationtestspositionrobustness.Rawsemanticorderingacceptsallfinitescalarsincludingnegatives;actualadapterretainsstrict0to1guard.','Semantic30sHTTPtimeoutisperoperationandonlyformeasurement;productionadapterunchanged1.5stotaldeadline.','NoPG/retrieval/citation/sourceeligibility/answergenerationmeasurement;allcandidatespublicandpreselected.','Adaptertimingsarewarmrepeatedcaseprobesafterrawscoring;passagesmax138chars,notrepresentative600char/coldproductionlatency.']))
        code=0
    finally:
        errors.extend(stop_owned(processes,group));remaining=remaining_group_members()
        if errors or remaining or any(p.poll() is None for _,p in processes):code=1
        write(args.output/'exit.json',dict(exit=code,cleanup_errors=errors,remaining_group_members=remaining,owned_processes_stopped=not remaining and all(p.poll() is not None for _,p in processes),reference_after=reference_snapshot()))
    return code


if __name__=='__main__':raise SystemExit(main())
