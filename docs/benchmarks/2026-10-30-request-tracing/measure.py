"""Metadata-only HTTP measurement. All database targets disposable, synthetic only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import json,os,resource,statistics,subprocess,sys,time
sys.path.insert(0,os.getcwd())
from starlette.testclient import TestClient
from agentic_rag.config import Config
from agentic_rag import db
from agentic_rag.benchmark.database import isolated_database
from tests.service.test_api import app_fixture,headers,KEYS

def percentile(values,p):return sorted(values)[min(len(values)-1,int(len(values)*p))]
with TemporaryDirectory(prefix='trace-measure-',dir=os.environ['TMPDIR']) as temp:
 with isolated_database(Config(ollama_url='http://127.0.0.1:1',rerank_url='http://127.0.0.1:1')) as cfg:
  app,policy=app_fixture(Path(temp),cfg)
  with TestClient(app,base_url='https://testserver') as client:
   # Warm caches/session setup before sampling; each response is drained.
   for _ in range(5):assert client.post('/v1/tools/memory_domains',headers=headers(KEYS[0]),json={}).status_code==200
   fds_before=len(os.listdir('/proc/self/fd'));started=time.perf_counter();cpu=time.process_time()
   def one(i):
    before=time.perf_counter();r=client.post('/v1/tools/memory_domains',headers=headers(KEYS[0]),json={});assert r.status_code==200,r.text
    return (time.perf_counter()-before)*1000
   with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(one,range(120)))
   elapsed=time.perf_counter()-started;cpu=time.process_time()-cpu
   fds_after=len(os.listdir('/proc/self/fd'))
   with db.connect(cfg) as conn:
    exists=conn.execute("SELECT to_regclass('public.request_traces') present").fetchone()['present']
    state=None if not exists else dict(conn.execute("SELECT count(*) rows,coalesce(sum(octet_length(to_jsonb(t)::text)),0) logical_bytes,pg_total_relation_size('request_traces') relation_bytes FROM request_traces t").fetchone())
   result={'revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'samples':len(values),'parallelism':4,'route':'POST /v1/tools/memory_domains','median_ms':statistics.median(values),'p95_ms':percentile(values,.95),'elapsed_seconds':elapsed,'cpu_seconds':cpu,'fds_before':fds_before,'fds_after':fds_after,'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'trace_state':state,'limits':'Synthetic ASGI in-process, localhost isolated PostgreSQL55461; no model; no TLS/network/long soak claim'}
   print(json.dumps(result,sort_keys=True))
