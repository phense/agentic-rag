#!/usr/bin/env python3
"""Sequential finite CPU benchmark supervisor; no production configuration.

Use --mode primary for three fresh-process raw-body runs per candidate, or
--mode canonical for one exact canonical-chunk pass. Candidate failures retain
their artifacts and stop further repetitions; never silently retry a failure.
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
import time

import psutil


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('primary','canonical'),required=True)
    for field in ('python','models','output'):parser.add_argument('--'+field,required=True)
    parser.add_argument('--fixtures',default=str(Path(__file__).resolve().parents[1]/'docs/benchmarks/2026-11-04-embedding-comparison'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    fixtures=Path(args.fixtures);out=Path(args.output);out.mkdir(mode=0o700)
    primary=args.mode=='primary';script=root/'scripts'/('benchmark_embeddings.py' if primary else 'benchmark_embedding_chunks.py')
    files=[Path(__file__).resolve(),script,root/'scripts/benchmark_embeddings.py',
           *[fixtures/p for p in (('corpus.json','protocol.json') if primary else ('canonical-inputs.json',))]]
    def hashes():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before=hashes();write(out/'inputs-before.json',before);records=[]
    try:
        for model in ('nano','bge','small'):
            model_start=time.monotonic()
            for repeat in range(3 if primary else 1):
                if shutil.disk_usage(out).free<3*1024**3:raise RuntimeError('free disk floor')
                if psutil.virtual_memory().available<2*1024**3:raise RuntimeError('available memory floor')
                label=f'{model}-r{repeat}';target=out/label
                snapshot=Path(args.models)/('bge-ollama' if model=='bge' else model)
                command=[args.python,str(script),'--worker' if primary else '--model',model,
                    '--model-dir',str(snapshot),'--output',str(target)]
                command+=['--corpus',str(fixtures/'corpus.json'),'--protocol',str(fixtures/'protocol.json')] if primary else ['--inputs',str(fixtures/'canonical-inputs.json')]
                env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(target/'private-home'),'LANG':'C.UTF-8',
                    'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false',
                    'OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','NUMEXPR_NUM_THREADS':'2',
                    'PYTHONDONTWRITEBYTECODE':'1','MALLOC_ARENA_MAX':'2'}
                record={'label':label,'command':command,'started':datetime.now(timezone.utc).isoformat()}
                write(out/'running.json',record)
                with (out/(label+'.log')).open('w') as log,(out/(label+'-resources.jsonl')).open('w') as samples:
                    process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    started=time.monotonic();reason=None
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
                write(out/(label+'-exit.json'),record);records.append(record);write(out/'attempts.json',records)
                print(json.dumps({k:record[k] for k in ('label','exit_code','supervisor_stop','seconds')}),flush=True)
                if process.returncode!=0:break
    finally:
        after=hashes();write(out/'inputs-after.json',after)
        write(out/'terminal.json',{'finished':datetime.now(timezone.utc).isoformat(),'inputs_unchanged':before==after,'attempts':records})
        if before!=after:raise RuntimeError('experiment input changed')


if __name__=='__main__':main()
