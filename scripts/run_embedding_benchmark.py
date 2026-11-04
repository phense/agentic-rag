#!/usr/bin/env python3
"""Finite sequential CPU experiments; no production configuration.

Run with the dedicated, recorded benchmark environment (including psutil).
--only small explicitly schedules a new Small-only experiment, not an automatic
retry. Every planned repetition has a terminal status, including unattempted work.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import psutil


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('primary','canonical'),required=True)
    for field in ('python','models','output'):parser.add_argument('--'+field,required=True)
    parser.add_argument('--only',nargs='+',choices=('nano','bge','small'))
    parser.add_argument('--canonical-inputs',default='canonical-inputs.json')
    parser.add_argument('--fixtures',default=str(Path(__file__).resolve().parents[1]/'docs/benchmarks/2026-11-04-embedding-comparison'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    fixtures=Path(args.fixtures);out=Path(args.output);out.mkdir(mode=0o700)
    primary=args.mode=='primary';script=root/'scripts'/('benchmark_embeddings.py' if primary else 'benchmark_embedding_chunks.py')
    files=[Path(__file__).resolve(),script,root/'scripts/benchmark_embeddings.py',
           *[fixtures/p for p in (('corpus.json','protocol.json') if primary else (args.canonical_inputs,))]]
    def hashes():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before=hashes();write(out/'inputs-before.json',before);records=[];failure=None
    models=args.only or ('nano','bge','small')
    if len(set(models))!=len(models):raise ValueError('duplicate candidate')
    planned=[{'label':f'{model}-r{repeat}','model':model,'repeat':repeat,'status':'unattempted','reason':'not_started'}
             for model in models for repeat in range(3 if primary else 1)]
    write(out/'planned-runs.json',planned)
    try:
        for model in models:
            model_start=time.monotonic();candidate_failed=False
            for row in (r for r in planned if r['model']==model):
                if candidate_failed:
                    row['reason']='earlier_candidate_failure';continue
                if shutil.disk_usage(out).free<3*1024**3:raise RuntimeError('free disk floor')
                if psutil.virtual_memory().available<2*1024**3:raise RuntimeError('available memory floor')
                label=row['label'];target=out/label
                snapshot=Path(args.models)/('bge-ollama' if model=='bge' else model)
                command=[args.python,str(script),'--worker' if primary else '--model',model,
                    '--model-dir',str(snapshot),'--output',str(target)]
                command+=['--corpus',str(fixtures/'corpus.json'),'--protocol',str(fixtures/'protocol.json')] if primary else ['--inputs',str(fixtures/args.canonical_inputs)]
                env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(target/'private-home'),'LANG':'C.UTF-8',
                    'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false',
                    'OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','NUMEXPR_NUM_THREADS':'2',
                    'PYTHONDONTWRITEBYTECODE':'1','MALLOC_ARENA_MAX':'2'}
                record={'label':label,'command':command,'started':datetime.now(timezone.utc).isoformat()}
                write(out/'running.json',dict(record,status='running'))
                process=None;started=time.monotonic();reason=None
                row.update(status='failed',reason='worker_start_failed')
                with (out/(label+'.log')).open('w') as log,(out/(label+'-resources.jsonl')).open('w') as samples:
                    process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    try:
                        while process.poll() is None:
                            rss=cpu=0
                            try:
                                parent=psutil.Process(process.pid);tree=[parent,*parent.children(recursive=True)]
                            except psutil.NoSuchProcess:tree=[]
                            for item in tree:
                                try:rss+=item.memory_info().rss;t=item.cpu_times();cpu+=t.user+t.system
                                except psutil.NoSuchProcess:pass
                            available=psutil.virtual_memory().available
                            samples.write(json.dumps({'seconds':time.monotonic()-started,'tree_rss_bytes':rss,
                                'tree_cpu_seconds':cpu,'mem_available_bytes':available})+'\n');samples.flush()
                            if rss>7*1024**3:reason='resource_pressure_rss'
                            if available<2*1024**3:reason='resource_pressure_available'
                            if shutil.disk_usage(out).free<3*1024**3:reason='resource_pressure_disk'
                            if time.monotonic()-model_start>(1800 if primary else 900):reason='candidate_total_wall_deadline'
                            if reason:break
                            time.sleep(.5)
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid,signal.SIGTERM)
                            try:process.wait(timeout=10)
                            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
                record.update(exit_code=process.returncode,supervisor_stop=reason,seconds=time.monotonic()-started,
                    finished=datetime.now(timezone.utc).isoformat(),log_sha256=hashlib.sha256((out/(label+'.log')).read_bytes()).hexdigest())
                candidate_failed=process.returncode!=0 or reason is not None
                row.update(status='failed' if candidate_failed else 'completed',reason=reason or ('worker_nonzero' if candidate_failed else None))
                write(out/(label+'-exit.json'),record);records.append(record);write(out/'attempts.json',records)
                print(json.dumps({k:record[k] for k in ('label','exit_code','supervisor_stop','seconds')}),flush=True)
    except (Exception,KeyboardInterrupt) as exc:
        failure={'class':type(exc).__name__,'message':str(exc)[:1000]}
        for row in planned:
            if row['status']=='unattempted' and row['reason']=='not_started':row['reason']='supervisor_aborted'
    finally:
        try:after=hashes()
        except Exception as exc:
            after=None;failure=failure or {'class':type(exc).__name__,'message':str(exc)[:1000]}
        write(out/'inputs-after.json',after)
        success=failure is None and before==after and all(r['status']=='completed' for r in planned)
        terminal={'finished':datetime.now(timezone.utc).isoformat(),'success':success,
                  'inputs_unchanged':before==after,'attempts':records,'planned_runs':planned,'failure':failure}
        write(out/'terminal.json',terminal)
        write(out/'running.json',{'status':'finished','success':success,'finished':terminal['finished']})
    return 0 if success else 1


if __name__=='__main__':sys.exit(main())
