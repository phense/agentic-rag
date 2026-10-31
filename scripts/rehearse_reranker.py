"""Owned public model/PG rehearsal inside one required4CPU/8GiB systemd cgroup.

No downloads, existing databases, production services or caller-selected cleanup.
Run explicitly under the resource envelope documented in docs/local-reranker.md.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
import signal
import shutil
from pathlib import Path
import socket
import subprocess
import time

import httpx
import psycopg

from agentic_rag.benchmark.rerank_evaluation import reference_snapshot,run,TINY_MODEL,TINY_REVISION,BASELINE_MODEL,BASELINE_REVISION
from agentic_rag.config import Config

QWEN_SHA='22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48'


def write(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')


def digest(path):
    value=sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):value.update(part)
    return value.hexdigest()


def stop_owned(processes,group):
    """Track children before readiness; one cleanup failure cannot hide the others."""
    errors=[]
    for name,process in reversed(processes):
        try:
            if process.poll() is not None:continue
            if Path(f'/proc/{process.pid}/cgroup').read_bytes()!=group:
                raise ValueError('child_cgroup_changed')
            process.send_signal(signal.SIGINT if name=='postgres' else signal.SIGTERM)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                errors.append({'child':name,'error':'forced_shutdown'})
                process.kill();process.wait(timeout=5)
        except Exception as exc:errors.append({'child':name,'error':type(exc).__name__})
    return errors


def remaining_group_members():
    group=Path('/proc/self/cgroup').read_text().strip().split('::')[-1].lstrip('/')
    members=(Path('/sys/fs/cgroup')/group/'cgroup.procs').read_text().splitlines()
    return [int(pid) for pid in members if int(pid)!=os.getpid()]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',required=True,type=Path)
    p.add_argument('--qwen',required=True,type=Path)
    p.add_argument('--tiny',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--work-dir',required=True,type=Path)
    p.add_argument('--pg-bin',type=Path,default=Path('/usr/lib/postgresql/17/bin'))
    p.add_argument('--repeats',type=int,default=2)
    args=p.parse_args();caps=reference_snapshot()
    for path in [args.output,args.work_dir]:
        if any(x.is_symlink() for x in [path,*path.parents]):raise ValueError('symlink lab output refused')
        path.mkdir(mode=0o700,parents=True,exist_ok=False)
    for model,expected in [(args.qwen,QWEN_SHA),(args.tiny,TINY_REVISION)]:
        if digest(model)!=expected:raise ValueError('pinned model checksum mismatch')
    # Charge newly created tmpfs model pages to this measured cgroup, rather than
    # relying on already charged shared model files from an unrelated parent.
    for name in ('qwen','tiny'):
        destination=args.work_dir/(name+'.gguf')
        shutil.copyfile(getattr(args,name),destination)
        setattr(args,name,destination)
    for port in (55463,8768,8769):
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    data=args.work_dir/'pgdata';sock=args.work_dir/'socket';sock.mkdir()
    processes=[];files=[];code=1
    own_group=Path('/proc/self/cgroup').read_bytes()
    metadata={'started_at':datetime.now(timezone.utc).isoformat(),'reference_before':caps,
        'runtime_version':subprocess.check_output([str(args.runtime),'--version'],stderr=subprocess.STDOUT,text=True).strip(),
        'runtime_sha256':sha256(args.runtime.read_bytes()).hexdigest(),
        'runtime_libraries':{str(x.name):sha256(x.read_bytes()).hexdigest() for x in args.runtime.parent.glob('*.so*') if x.is_file()},
        'model_probes':[],'membership':{},'child_affinity':{},'model_pages_created_in_cgroup':True,'host_cpus':os.cpu_count(),
        'host_memory_kib':int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1]),
        'limits':'One effective4CPU/8GiBzero-swap cgroup, shared8CPU/16GiB host; no dedicated VM or fleet-capacity proof.'}
    pglog=(args.output/'postgres.log').open('wb');files.append(pglog)
    try:
        subprocess.run([str(args.pg_bin/'initdb'),'-D',str(data),'-U',os.environ.get('USER','administrator'),'-A','trust','--no-locale','-E','UTF8'],stdout=pglog,stderr=pglog,check=True)
        pg_process=subprocess.Popen([str(args.pg_bin/'postgres'),'-D',str(data),'-p','55463','-k',str(sock),
            '-h','127.0.0.1','-F','-c','shared_buffers=64MB'],stdout=pglog,stderr=pglog)
        processes.append(('postgres',pg_process))
        for attempt in range(300):
            if pg_process.poll() is not None:raise RuntimeError('owned PostgreSQL exited during startup')
            try:
                with psycopg.connect(dbname='postgres',host=str(sock),port=55463,connect_timeout=1):pass
                break
            except psycopg.OperationalError:time.sleep(.1)
        else:raise TimeoutError('owned PostgreSQL startup')
        metadata['membership']['postgres']=Path(f'/proc/{pg_process.pid}/cgroup').read_bytes()==own_group
        metadata['child_affinity']['postgres']=sorted(os.sched_getaffinity(pg_process.pid))
        for model,alias,port,model_digest in [(args.qwen,BASELINE_MODEL,8768,QWEN_SHA),(args.tiny,TINY_MODEL,8769,TINY_REVISION)]:
            log=(args.output/(alias+'.log')).open('wb');files.append(log);start=time.perf_counter()
            process=subprocess.Popen([str(args.runtime),'--model',str(model),'--host','127.0.0.1','--port',str(port),
                '--rerank','--pooling','rank','--ctx-size','4096','--parallel','1','--threads','4','--threads-batch','4',
                '--threads-http','2','--slots','--alias',alias,'--offline','--no-webui','--log-disable'],stdout=log,stderr=log)
            processes.append((alias,process));url='http://127.0.0.1:'+str(port)
            with httpx.Client(trust_env=False,timeout=30) as client:
                for attempt in range(300):
                    if process.poll() is not None:raise RuntimeError('owned model exited')
                    try:
                        if client.get(url+'/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise TimeoutError('owned model startup')
                ready=time.perf_counter();timings=[];response=None
                for trial in range(3):
                    t=time.perf_counter();result=client.post(url+'/v1/rerank',json={'model':alias,
                        'query':'Which city is the capital of China?',
                        'documents':['Beijing is the capital of China.','Paris is the capital of France.'],
                        'top_n':2,'return_documents':False});result.raise_for_status();response=result.json();timings.append((time.perf_counter()-t)*1000)
                    scores={v['index']:v['relevance_score'] for v in response['results']}
                    if not scores[0]>scores[1]:raise ValueError('synthetic model discrimination failed')
            metadata['membership'][alias]=Path(f'/proc/{process.pid}/cgroup').read_bytes()==own_group
            metadata['child_affinity'][alias]=sorted(os.sched_getaffinity(process.pid))
            metadata['model_probes'].append({'model':alias,'sha256':model_digest,'startup_ms':(ready-start)*1000,
                'first_ms':timings[0],'warm_ms':timings[1:],'synthetic_scores':scores,'threads':4})
            print(json.dumps({'ready':alias,'first_ms':timings[0],'warm_ms':timings[1:]}),flush=True)
        if not all(metadata['membership'].values()):raise ValueError('measured child outside service envelope')
        if any(cpus!=[0,1,2,3] for cpus in metadata['child_affinity'].values()):raise ValueError('measured child outside CPU affinity')
        write(args.output/'runtime-manifest.json',metadata)
        os.environ['PGPORT']='55463'
        for key in ('PGHOST','PGHOSTADDR','PGSERVICE','PGSERVICEFILE'):os.environ.pop(key,None)
        result=run(Config(rerank_model=BASELINE_MODEL,rerank_revision=BASELINE_REVISION,rerank_policy='legacy-v1',db_host=str(sock),ollama_url='http://127.0.0.1:1',rerank_url='http://127.0.0.1:8768'),
            output=args.output/'comparison',tiny_url='http://127.0.0.1:8769',owned_pg_data=data,repeats=args.repeats,
            runtime_manifest=args.output/'runtime-manifest.json',
            progress=lambda split,identity:print(json.dumps({'split':split,'finished':identity}),flush=True))
        if any(phase['failed_sources'] or any(v['summary']['query_failures'] or not v['summary']['citation_parity']
                for v in phase['profiles'].values()) for phase in [result['development'],result['heldout']]):
            raise ValueError('evaluation retains indexing/query/citation failures; run invalid')
        if any(process.poll() is not None for _,process in processes):raise RuntimeError('measured child exited unexpectedly')
        if digest(args.qwen)!=QWEN_SHA or digest(args.tiny)!=TINY_REVISION:raise ValueError('model weight drift')
        code=0
    finally:
        errors=stop_owned(processes,own_group)
        for f in files:
            try:f.close()
            except Exception as exc:errors.append({'child':'log','error':type(exc).__name__})
        remaining=remaining_group_members()
        stopped=not remaining and all(p.poll() is not None for _,p in processes)
        if errors or not stopped:code=1
        write(args.output/'exit.json',{'exit':code,'cleanup_errors':errors,
            'owned_processes_stopped':stopped,'remaining_group_members':remaining,
            'owned_postgres_stopped':all(p.poll() is not None for name,p in processes if name=='postgres'),'data_retained':True,
            'reference_after':reference_snapshot(),'finished_at':datetime.now(timezone.utc).isoformat()})
    return code


if __name__=='__main__':raise SystemExit(main())
