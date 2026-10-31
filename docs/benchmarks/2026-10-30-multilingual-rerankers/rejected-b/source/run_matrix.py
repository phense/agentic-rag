"""Run the frozen matrix serially; each process tree gets its own resource unit."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time


def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--models-root',required=True,type=Path)
    p.add_argument('--server-python',required=True);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();here=Path(__file__).resolve().parent;repo=here.parents[2]
    a.output.mkdir(parents=True,exist_ok=False)
    frozen={str(f.relative_to(here)):digest(f) for f in here.iterdir() if f.suffix in ('.py','.json','.md')}
    metadata=json.loads((a.models_root/'models.json').read_text())
    seal=dict(utc=datetime.now(timezone.utc).isoformat(),frozen=frozen,models=metadata,
        host=dict(platform=platform.platform(),machine=platform.machine(),
            cpu_model=next(line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
            cpu_flags=next(line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('flags')),
            meminfo=Path('/proc/meminfo').read_text(),loadavg=os.getloadavg()),
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip())
    (a.output/'matrix-seal.json').write_text(json.dumps(seal,indent=2)+'\n')
    order=['minilm-l6','mmarco','jina-v2','jina-v3.5'];results=[]
    for round in range(3):
        for name in order[round:]+order[:round]:
            assert all(digest(here/f)==h for f,h in frozen.items())
            unit='rag62-four-'+name.replace('.','')+'-r'+str(round)
            dest=a.output/(name+'-r'+str(round))
            command=['systemd-run','--user','--unit',unit,'--wait','--pipe',
                '--working-directory',str(repo),'-p','CPUQuota=400%','-p','MemoryMax=8G',
                '-p','MemorySwapMax=0','-p','AllowedCPUs=0-3',
                '--setenv=PYTHONPATH='+str(repo),'taskset','-c','0-3',str(repo/'.venv/bin/python'),
                str(here/'benchmark.py'),'--name',name,'--round',str(round),
                '--models-root',str(a.models_root),'--server-python',a.server_python,'--output',str(dest)]
            before=time.perf_counter()
            print('START',name,'round',round,datetime.now(timezone.utc).isoformat(),flush=True)
            with (a.output/(name+'-r'+str(round)+'-console.log')).open('x') as log:
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            properties=subprocess.run(['systemctl','--user','show',unit,
                '-p','ActiveState','-p','SubState','-p','Result','-p','ExecMainStatus',
                '-p','CPUUsageNSec','-p','MemoryPeak'],text=True,capture_output=True)
            with socket.socket() as probe:
                port_result=probe.connect_ex(('127.0.0.1',8782))
            record=dict(model=name,round=round,unit=unit,command=command,exit=result.returncode or (1 if port_result==0 else 0),
                wall_seconds=time.perf_counter()-before,systemd_properties=properties.stdout,
                post_exit_port_connect_errno=port_result,
                finished=datetime.now(timezone.utc).isoformat())
            results.append(record)
            (a.output/'matrix-progress.json').write_text(json.dumps(results,indent=2)+'\n')
            print('END',name,'round',round,'exit',result.returncode,'wall',round_value(record['wall_seconds']),flush=True)
            if record['exit']:
                (a.output/'matrix-exit.json').write_text(json.dumps(dict(exit=1,completed=results),indent=2)+'\n')
                return 1
    assert all(digest(here/f)==h for f,h in frozen.items())
    (a.output/'matrix-exit.json').write_text(json.dumps(dict(exit=0,completed=results),indent=2)+'\n')
    print('Matrix complete, actual exit0,12ownedunits',flush=True)
    return 0


def round_value(n):
    return float(f'{n:.3f}')


if __name__=='__main__':
    raise SystemExit(main())
