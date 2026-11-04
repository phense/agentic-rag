"""Finite supervisor; kills only its own process group, retains every attempt."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,os,signal,subprocess,time,shutil,sys
import psutil
ROOT=Path.cwd().resolve()
OUT=Path('/home/administrator/Claude/.scratch/rag083-measurement-a')
OUT.mkdir(mode=0o700)
PYTHON='/home/administrator/Claude/.scratch/rag083-cpu-env/bin/python'
SCRIPT=ROOT/'scripts/benchmark_embeddings.py'
BASE=Path('/home/administrator/Claude/.scratch/rag083-models')
CORPUS=ROOT/'docs/benchmarks/2026-11-04-embedding-comparison/corpus.json'
PROTOCOL=CORPUS.with_name('protocol.json')
inputs={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCRIPT,CORPUS,PROTOCOL,Path(__file__).resolve())}
(OUT/'inputs-before.json').write_text(json.dumps(inputs,indent=2)+'\n')
(OUT/'environment.json').write_text(subprocess.check_output(['uv','pip','freeze','--python',PYTHON],text=True))
records=[]
try:
 for model in ('nano','bge','small'):
  if not (BASE/(model+'-manifest.json')).exists() and model!='bge':
   # Download may still be running. This is a preparation boundary, not inference.
   limit=time.monotonic()+900
   while not (BASE/(model+'-manifest.json')).exists():
    if time.monotonic()>limit:raise RuntimeError('model download preparation deadline')
    time.sleep(1)
  model_started=time.monotonic()
  for repeat in range(3):
   assert shutil.disk_usage(OUT).free>=3*1024**3
   assert psutil.virtual_memory().available>=2*1024**3
   label=f'{model}-r{repeat}';output=OUT/label
   modeldir=BASE/('bge-ollama' if model=='bge' else model)
   cmd=[PYTHON,'-I',str(SCRIPT),'--worker',model,'--model-dir',str(modeldir),'--output',str(output),'--corpus',str(CORPUS),'--protocol',str(PROTOCOL)]
   env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(output/'private-home'),'LANG':'C.UTF-8',
        'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
        'TOKENIZERS_PARALLELISM':'false','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2',
        'NUMEXPR_NUM_THREADS':'2','PYTHONDONTWRITEBYTECODE':'1','MALLOC_ARENA_MAX':'2'}
   record={'label':label,'command':cmd,'started':datetime.now(timezone.utc).isoformat(),'inputs':inputs}
   (OUT/'running.json').write_text(json.dumps(record,indent=2)+'\n')
   with (OUT/(label+'.log')).open('w') as log,(OUT/(label+'-resources.jsonl')).open('w') as samples:
    child=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    began=time.monotonic(); reason=None
    try:
     while child.poll() is None:
      process=psutil.Process(child.pid)
      children=[]
      try:children=process.children(recursive=True)
      except psutil.NoSuchProcess:pass
      rss=0;cpu=0
      for p in [process,*children]:
       try:
        rss+=p.memory_info().rss;t=p.cpu_times();cpu+=t.user+t.system
       except psutil.NoSuchProcess:pass
      available=psutil.virtual_memory().available
      samples.write(json.dumps({'seconds':time.monotonic()-began,'tree_rss_bytes':rss,'tree_cpu_seconds':cpu,'mem_available_bytes':available})+'\n');samples.flush()
      if rss>7*1024**3:reason='resource_pressure_rss'
      if available<2*1024**3:reason='resource_pressure_available'
      if time.monotonic()-model_started>1800:reason='candidate_total_wall_deadline'
      if reason:
       os.killpg(child.pid,signal.SIGTERM)
       try:child.wait(timeout=10)
       except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
       break
      time.sleep(.5)
    finally:
     if child.poll() is None:
      os.killpg(child.pid,signal.SIGTERM)
      try:child.wait(timeout=10)
      except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
   record.update(exit_code=child.returncode,supervisor_stop=reason,seconds=time.monotonic()-began,finished=datetime.now(timezone.utc).isoformat(),log_sha256=hashlib.sha256((OUT/(label+'.log')).read_bytes()).hexdigest())
   (OUT/(label+'-exit.json')).write_text(json.dumps(record,indent=2)+'\n');records.append(record)
   (OUT/'attempts.json').write_text(json.dumps(records,indent=2)+'\n')
   print(json.dumps({k:record[k] for k in ('label','exit_code','supervisor_stop','seconds')}),flush=True)
   if child.returncode!=0:break  # Do not retry a failed candidate.
finally:
 after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCRIPT,CORPUS,PROTOCOL,Path(__file__).resolve())}
 (OUT/'inputs-after.json').write_text(json.dumps(after,indent=2)+'\n')
 (OUT/'terminal.json').write_text(json.dumps({'finished':datetime.now(timezone.utc).isoformat(),'inputs_unchanged':inputs==after,'attempts':records},indent=2)+'\n')
 if inputs!=after:raise RuntimeError('experiment inputs changed during run')
