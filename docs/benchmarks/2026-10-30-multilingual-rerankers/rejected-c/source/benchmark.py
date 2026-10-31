"""Bounded four-model comparison; public candidates only, no PostgreSQL or adoption."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unicodedata

import httpx
from agentic_rag import neural_rerank
from agentic_rag.config import Config

ROOT = Path(__file__).resolve().parent


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        while b := f.read(1024*1024):
            h.update(b)
    return h.hexdigest()


def write(p, value):
    with Path(p).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def metric(order, expected):
    if not expected:
        return None
    gold = set(expected)
    rank = next((i+1 for i,v in enumerate(order) if v in gold), None)
    gains = sum(1/math.log2(i+2) for i,v in enumerate(order[:3]) if v in gold)
    ideal = sum(1/math.log2(i+2) for i in range(min(3,len(gold))))
    return dict(top1=order[0] in gold, recall3=len(set(order[:3])&gold)/len(gold),
        all_sources3=gold<=set(order[:3]), mrr=1/rank if rank else 0, ndcg3=gains/ideal)


def permute(case, iteration=0):
    out = copy.deepcopy(case['passages'])
    random.Random(case['pair']).shuffle(out)
    return out[::-1] if iteration else out


def pad(text, length, position='beginning', language='de'):
    filler = (' Das Gebäude wird regelmäßig dokumentiert. Die allgemeine Beschreibung enthält keine weiteren Entscheidungen. '
        if language == 'de' else ' The building is documented regularly. This general description contains no further decisions. ')
    remaining = max(0, length-len(text)-2)
    extra = (filler*(remaining//len(filler)+1))[:remaining]
    if position == 'end':
        return extra+' '+text
    if position == 'middle':
        half=len(extra)//2
        return extra[:half]+' '+text+' '+extra[half:]
    return text+' '+extra


def validate(corpus):
    cases=corpus['cases']
    assert len(cases)==96 and len({c['id'] for c in cases})==96
    assert len({c['family'] for c in cases})==24
    assert all(sum(c['language']==lang for c in cases)==48 for lang in ('de','en'))
    for c in cases:
        assert len(c['passages'])==6 and set(c['expected'])<=set(p['id'] for p in c['passages'])
        assert len({p['id'] for p in c['passages']})==6
        assert all(0<len(p['text'])<599 for p in c['passages'])
        hits=[SimpleNamespace(document_id=i,score=1.0) for i in range(6)]
        assert neural_rerank.eligible(c['query'],hits),c['id']
    for pair in {c['pair'] for c in cases}:
        a,b=[c for c in cases if c['pair']==pair]
        assert a['expected']==b['expected'] and a['language']!=b['language']


def cgroup_snapshot():
    group=Path('/proc/self/cgroup').read_text().strip().split('::',1)[1]
    path=Path('/sys/fs/cgroup')/group.lstrip('/')
    result={'path':group,'affinity':sorted(os.sched_getaffinity(0)),'loadavg':os.getloadavg()}
    for name in ('cpu.max','cpu.stat','memory.current','memory.peak','memory.max','memory.swap.max','memory.events'):
        result[name]=(path/name).read_text().strip()
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',choices=['minilm-l6','mmarco','jina-v2','jina-v3.5'])
    p.add_argument('--round',type=int,default=0)
    p.add_argument('--models-root',type=Path)
    p.add_argument('--server-python')
    p.add_argument('--output',type=Path)
    p.add_argument('--port',type=int,default=8782)
    p.add_argument('--validate-only',action='store_true')
    a=p.parse_args();corpus=json.loads((ROOT/'corpus.json').read_text());validate(corpus)
    if a.validate_only:
        print('Validated96questions/48DE+48EN/24families, all adapter eligible.');return 0
    a.output.mkdir(parents=True,exist_ok=False)
    models=json.loads((a.models_root/'models.json').read_text())
    model=next(m for m in models if m['name']==a.name)
    frozen={str(f.relative_to(ROOT)):digest(f) for f in ROOT.glob('*.py')}
    frozen['corpus.json']=digest(ROOT/'corpus.json')
    before=cgroup_snapshot()
    assert before['affinity']==[0,1,2,3] and before['cpu.max']=='400000 100000'
    assert before['memory.max']=='8589934592' and before['memory.swap.max']=='0'
    product={str(f):digest(f) for f in (Path('agentic_rag/neural_rerank.py'),Path('agentic_rag/config.py'),Path('agentic_rag/retrieval.py'))}
    write(a.output/'seal.json',dict(utc=datetime.now(timezone.utc).isoformat(),
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        frozen=frozen,product=product,model=model,envelope=before,
        versions=json.loads(subprocess.check_output([a.server_python,'-c',
            'import importlib.metadata,json;print(json.dumps({n:importlib.metadata.version(n) for n in ["onnxruntime","tokenizers","numpy","torch","transformers","httpx"]}))'],text=True))))
    rows=[];child=None;code=1;cleanup=[];url=f'http://127.0.0.1:{a.port}'
    stream=(a.output/'observations.jsonl').open('x',buffering=1)
    tmp=tempfile.TemporaryDirectory(prefix='rag62-four-'+a.name+'-',dir='/dev/shm')
    try:
        # Fresh copies are charged to this measured cgroup, including tmpfs pages.
        owned=Path(tmp.name)/'model';owned.mkdir()
        for name,info in model['files'].items():
            src=a.models_root/a.name/name;dest=owned/name
            shutil.copyfile(src,dest)
            if digest(dest)!=info['sha256']:
                raise ValueError('model_copy_hash')
        with socket.socket() as s:s.bind(('127.0.0.1',a.port))
        start=time.perf_counter()
        log=(a.output/'server-console.log').open('xb')
        env=dict(os.environ,TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='4',
            MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1',HF_HUB_OFFLINE='1',
            TRANSFORMERS_OFFLINE='1',HF_HOME=str(Path(tmp.name)/'hf-cache'))
        child=subprocess.Popen([a.server_python,str(ROOT/'server.py'),'--model',str(owned),
            '--name',a.name,'--port',str(a.port),'--log',str(a.output/'server-events.jsonl')],
            env=env,stdout=log,stderr=log)
        with httpx.Client(trust_env=False,timeout=2) as client:
            until=time.monotonic()+180
            while time.monotonic()<until:
                if child.poll() is not None:raise RuntimeError('model_startup_exit')
                try:
                    if client.get(url+'/health').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise TimeoutError('model_startup_deadline')
        ready=(time.perf_counter()-start)*1000
        assert Path(f'/proc/{child.pid}/cgroup').read_text()==Path('/proc/self/cgroup').read_text()
        assert sorted(os.sched_getaffinity(child.pid))==[0,1,2,3]
        write(a.output/'startup.json',dict(process_to_ready_ms=ready,pid=child.pid,
            same_cgroup=True,affinity=sorted(os.sched_getaffinity(child.pid))))

        def drain():
            start=time.perf_counter()
            with httpx.Client(trust_env=False,timeout=2) as client:
                end=time.monotonic()+120
                while time.monotonic()<end:
                    status=client.get(url+'/health').json()
                    if status['active']==0:return (time.perf_counter()-start)*1000
                    time.sleep(.02)
            raise TimeoutError('native_drain_120s')

        def save(row):
            rows.append(row);stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')

        def raw(case, mode, passages=None, iteration=0, **extra):
            docs=passages or permute(case,iteration)
            row=dict(model=a.name,round=a.round,mode=mode,case_id=case['id'],
                family=case['family'],language=case['language'],split=case.get('split'),
                permutation=iteration,input=[d['id'] for d in docs],expected=case['expected'],**extra)
            start=time.perf_counter();error=None;body=None;order=row['input']
            try:
                with httpx.Client(trust_env=False,timeout=30) as client:
                    r=client.post(url+'/v1/rerank',json=dict(model=a.name,query=case['query'],
                        documents=[d['text'] for d in docs],top_n=len(docs),return_documents=False))
                    r.raise_for_status();body=r.json()
                rs=body['results'];scores={v['index']:v['relevance_score'] for v in rs}
                assert body['model']==a.name and len(rs)==len(docs) and set(scores)==set(range(len(docs)))
                assert all(type(v) in (int,float) and math.isfinite(v) for v in scores.values())
                order=[docs[i]['id'] for i in sorted(scores,key=lambda i:(-scores[i],i))]
            except Exception as exc:error=type(exc).__name__
            elapsed=(time.perf_counter()-start)*1000
            row.update(elapsed_ms=elapsed,error=error,order=order,
                metrics=metric(order,case['expected']) if error is None else None,response=body,
                input_chars=sum(len(d['text']) for d in docs),drain_ms=drain())
            save(row);return row

        artifact='model.safetensors' if a.name=='jina-v3.5' else 'model.onnx'
        cfg=Config(rerank_url=url,rerank_model=a.name,
            rerank_revision=model['files'][artifact]['sha256'],rerank_policy='focused-v1')

        def adapter(case,mode='adapter',passages=None,**extra):
            docs=passages or permute(case)
            hits=[SimpleNamespace(document_id=int(d['id']),score=1.0,title='',snippet=d['text']) for d in docs]
            info={};error=None;start=time.perf_counter()
            try:result=neural_rerank.order(case['query'],hits,cfg,diagnostics=info)
            except Exception as exc:result=hits;error=type(exc).__name__
            elapsed=(time.perf_counter()-start)*1000
            assert {id(h) for h in result}=={id(h) for h in hits}
            order=[str(h.document_id) for h in result]
            return dict(model=a.name,round=a.round,mode=mode,case_id=case['id'],
                family=case['family'],language=case['language'],split=case.get('split'),
                input=[d['id'] for d in docs],expected=case['expected'],order=order,
                elapsed_ms=elapsed,error=error,diagnostics=info,
                metrics=metric(order,case['expected']),**extra)

        cases=corpus['cases'];first=cases[0]
        raw(first,'cold-first')
        if a.round==0:
            for i,c in enumerate(cases):
                for iteration in range(2):raw(c,'quality',iteration=iteration)
                r=adapter(c);r['drain_ms']=drain();save(r)
                if i%16==15:print(a.name,'quality',i+1,'/96',flush=True)
            prior=[c for c in cases if c['split']=='prior-diagnostic']
            for c in prior:
                other=next(v for v in prior if v['pair']==c['pair'] and v['language']!=c['language'])
                mixed=dict(c,passages=other['passages'])
                raw(mixed,'cross-language',candidate_language=other['language'])
            for c in [v for v in prior if '-1-' in v['id']]:
                for pos in ('beginning','middle','end'):
                    docs=[dict(d,text=pad(d['text'],6000,pos,c['language'])) for d in permute(c)]
                    raw(c,'long-context',docs,position=pos,target_chars=6000)
            for c in [v for v in prior if v['language']=='de' and '-1-' in v['id']]:
                for variant in ('whitespace','umlaut-ascii','unicode-nfd'):
                    query=c['query']
                    if variant=='whitespace':query='  '+query.replace(' ','   ')+'  '
                    if variant=='umlaut-ascii':
                        for src,dst in [('ä','ae'),('ö','oe'),('ü','ue'),('ß','ss')]:query=query.replace(src,dst)
                    if variant=='unicode-nfd':query=unicodedata.normalize('NFD',query)
                    raw(dict(c,query=query),'perturbation',variant=variant)
            unrelated_de=['Wie hoch ist die Temperatur auf dem Mars?', 'Wer gewann den Segelwettbewerb in Oslo?',
                'Wann wurde die Sternwarte in Lima eröffnet?', 'Welche Zutaten enthält die Mangosuppe?',
                'Wie viele Zuschauer hatte das Theaterstück in Riga?', 'Wo liegt das Grab des Königs von Bhutan?',
                'Welche Farbe hat das Trikot des Vereins in Porto?', 'Warum wandern die Vögel nach Süden?']
            unrelated_en=['What is the temperature on Mars?', 'Who won the sailing competition in Oslo?',
                'When did the observatory in Lima open?', 'Which ingredients are in the mango soup?',
                'How many spectators attended the play in Riga?', 'Where is the tomb of the king of Bhutan?',
                'What colour is the club jersey in Porto?', 'Why do birds migrate south?']
            for lang,queries in [('de',unrelated_de),('en',unrelated_en)]:
                original=next(v for v in prior if v['language']==lang)
                for i,q in enumerate(queries):
                    raw(dict(original,id=f'unsupported-{i}-{lang}',query=q,expected=[]),'unsupported')
            print(a.name,'semantic diagnostics complete',flush=True)
        # Common payloads and 3 independent process starts; no model-specific tuning.
        grid=[(6,120),(6,600),(6,1200),(12,600),(12,1200)]
        for cell,(n,chars) in enumerate(grid):
            for repeat in range(15):
                c=cases[(repeat*7+cell*11)%len(cases)]
                docs=[dict(id=str(i),text=pad(c['passages'][i%6]['text'],chars,language=c['language'])) for i in range(n)]
                raw(dict(c,expected=[]),'performance',docs,candidates=n,target_chars=chars,repeat=repeat)
            print(a.name,'performance',n,chars,'round',a.round,flush=True)
        if a.round==0:
            # Same product client process, so its existing two-slot pressure guard applies.
            for concurrency in (1,2,4):
                for repeat in range(5):
                    c=cases[(repeat*13)%len(cases)]
                    docs=[dict(d,text=pad(d['text'],599,language=c['language'])) for d in permute(c)]
                    started=time.perf_counter()
                    with ThreadPoolExecutor(max_workers=concurrency) as pool:
                        batch=list(pool.map(lambda _:adapter(c,'concurrency',docs,
                            concurrency=concurrency,repeat=repeat),range(concurrency)))
                    makespan=(time.perf_counter()-started)*1000;drain_ms=drain()
                    for row in batch:row.update(makespan_ms=makespan,drain_ms=drain_ms);save(row)
            # Exact-symbol routing is tested without model execution.
            bypass=dict(first,query='Wie behebe ich ERR_PERMISSION_DENIED beim Öffnen des Archivs?')
            r=adapter(bypass,'exact-symbol-bypass');r['drain_ms']=drain();save(r)
        assert all(digest(ROOT/name)==h for name,h in frozen.items())
        assert all(digest(Path(name))==h for name,h in product.items())
        raw_errors=[r for r in rows if r['mode'] not in ('adapter','concurrency','exact-symbol-bypass') and r['error']]
        # A completed bounded protocol may contain censored30s observations.
        # Their semantic metric stays unavailable, never original-order quality.
        unexpected=[r for r in raw_errors if r['error'] not in ('ReadTimeout','ConnectTimeout','WriteTimeout','PoolTimeout')]
        if unexpected:raise ValueError('unexpected_raw_errors:'+str(len(unexpected)))
        code=0
    finally:
        if child is not None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
        stream.close()
        tmp.cleanup()
        after=cgroup_snapshot()
        group_path=Path('/sys/fs/cgroup')/after['path'].lstrip('/')
        members=[int(pid) for pid in (group_path/'cgroup.procs').read_text().split()]
        remaining=[pid for pid in members if pid!=os.getpid()]
        if remaining:code=1
        write(a.output/'exit.json',dict(exit=code,observations=len(rows),
            child_stopped=child is None or child.poll() is not None,
            child_exit=child.returncode if child else None,cleanup_errors=cleanup,
            remaining_group_members=remaining,temporary_model_copy_removed=not Path(tmp.name).exists(),
            envelope_after=after,utc=datetime.now(timezone.utc).isoformat()))
    print(a.name,'round',a.round,'actual exit',code,'observations',len(rows),flush=True)
    return code


if __name__=='__main__':
    raise SystemExit(main())
