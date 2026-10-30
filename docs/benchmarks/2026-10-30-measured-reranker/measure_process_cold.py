"""Supplemental process-cold smoke; independent from sealed source evaluation."""
from pathlib import Path
from hashlib import sha256
import argparse,json,os,shutil,socket,subprocess,time,math,statistics
import httpx
from agentic_rag.benchmark.rerank_evaluation import reference_snapshot
from scripts.rehearse_reranker import digest,stop_owned,remaining_group_members,QWEN_SHA,TINY_REVISION,TINY_MODEL
from agentic_rag.neural_rerank import MODEL


def new_json(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','qwen','tiny','output','work-dir'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();caps=reference_snapshot()
    for path in (args.output,args.work_dir):
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlink path refused')
        path.mkdir(parents=True,exist_ok=False,mode=0o700)
    for name,expected in [('qwen',QWEN_SHA),('tiny',TINY_REVISION)]:
        source=getattr(args,name)
        if digest(source)!=expected:raise ValueError('model checksum mismatch')
        target=args.work_dir/(name+'.gguf');shutil.copyfile(source,target)
        if digest(target)!=expected:raise ValueError('model copy mismatch')
        setattr(args,name,target)
    group=Path('/proc/self/cgroup').read_bytes();children=[];code=1;trials=[]
    before=dict(runtime=digest(args.runtime),libraries={p.name:digest(p) for p in args.runtime.parent.glob('*.so*') if p.is_file()})
    errors=[]
    try:
        for model,alias,expected,port in [(args.qwen,MODEL,QWEN_SHA,8770),(args.tiny,TINY_MODEL,TINY_REVISION,8771)]:
            for iteration in range(3):
                with socket.socket() as sock:sock.bind(('127.0.0.1',port))
                with (args.output/(alias+'-'+str(iteration)+'.log')).open('xb') as log:
                    start=time.perf_counter()
                    process=subprocess.Popen([str(args.runtime),'--model',str(model),'--host','127.0.0.1','--port',str(port),
                        '--rerank','--pooling','rank','--ctx-size','4096','--parallel','1','--threads','4','--threads-batch','4',
                        '--threads-http','2','--alias',alias,'--offline','--no-webui','--log-disable'],stdout=log,stderr=log)
                    children.append((alias,process));url='http://127.0.0.1:'+str(port)
                    try:
                        with httpx.Client(trust_env=False,follow_redirects=False,timeout=30) as client:
                            for attempt in range(300):
                                if process.poll() is not None:raise RuntimeError('model exited during startup')
                                try:
                                    if client.get(url+'/health').status_code==200:break
                                except httpx.HTTPError:pass
                                time.sleep(.1)
                            else:raise TimeoutError('model startup')
                            ready=time.perf_counter();durations=[]
                            for request in range(3):
                                t=time.perf_counter();response=client.post(url+'/v1/rerank',json={'model':alias,
                                    'query':'Which city is the capital of China?',
                                    'documents':['Beijing is the capital of China.','Paris is the capital of France.'],
                                    'top_n':2,'return_documents':False});response.raise_for_status();body=response.json()
                                durations.append((time.perf_counter()-t)*1000)
                                scores={r['index']:r['relevance_score'] for r in body['results']}
                                if (body.get('model')!=alias or set(scores)!={0,1}
                                        or not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in scores.values())
                                        or scores[0]<=scores[1]):raise ValueError('synthetic discrimination failed')
                        affinity=sorted(os.sched_getaffinity(process.pid))
                        if Path(f'/proc/{process.pid}/cgroup').read_bytes()!=group or affinity!=[0,1,2,3]:raise ValueError('child outside envelope')
                        status=Path(f'/proc/{process.pid}/status').read_text()
                        hwm=int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmHWM:')))
                        trials.append(dict(model=alias,sha256=expected,process_start=iteration+1,startup_ms=(ready-start)*1000,
                            first_ms=durations[0],warm_ms=durations[1:],ready_and_first_ms=(ready-start)*1000+durations[0],
                            peak_rss_kib=hwm,child_affinity=affinity,same_cgroup=True))
                        print(json.dumps(trials[-1]),flush=True)
                    finally:
                        stop_errors=stop_owned([(alias,process)],group);errors.extend(stop_errors)
                        if stop_errors or process.poll() is None:raise RuntimeError('model cleanup failed')
        after=dict(runtime=digest(args.runtime),libraries={p.name:digest(p) for p in args.runtime.parent.glob('*.so*') if p.is_file()})
        if before!=after or digest(args.qwen)!=QWEN_SHA or digest(args.tiny)!=TINY_REVISION:raise ValueError('runtime/model drift')
        def stats(values):return dict(n=len(values),p50_ms=statistics.median(values),p95_ms=sorted(values)[math.ceil(.95*len(values))-1])
        summary={alias:{key:stats([v for t in trials if t['model']==alias for v in (t['warm_ms'] if key=='warm_ms' else [t[key]])])
            for key in ['startup_ms','first_ms','ready_and_first_ms','warm_ms']} for alias in [MODEL,TINY_MODEL]}
        new_json(args.output/'results.json',dict(source_script_sha256=digest(Path(__file__)),runtime=before,
            reference_before=caps,trials=trials,summary=summary,
            limits=['Three fresh model processes each; warm filesystem/OS cache.','Fixed public functional payload, not full-search latency or answer accuracy.',
                'Independent supplemental experiment; no candidate selection or heldout retuning.','Shared host with separate verification tests running; no dedicated CPU proof.']))
        code=0
    finally:
        errors.extend(stop_owned(children,group));remaining=remaining_group_members()
        if errors or remaining or any(p.poll() is None for _,p in children):code=1
        new_json(args.output/'exit.json',dict(exit=code,cleanup_errors=errors,remaining_group_members=remaining,
            owned_processes_stopped=not remaining and all(p.poll() is not None for _,p in children),reference_after=reference_snapshot()))
    return code


if __name__=='__main__':raise SystemExit(main())
