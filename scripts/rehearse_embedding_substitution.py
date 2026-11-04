"""Owned populated-store rehearsal using exact actual-model vector replay.

Never a model-speed measurement. The HTTP replay recognizes only exact frozen
input bytes and explicit task prefixes; it cannot synthesize unknown vectors.
"""
from __future__ import annotations
import argparse,asyncio,contextlib,dataclasses,hashlib,io,json,os,threading,time
from contextlib import contextmanager
from collections import Counter
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from psycopg import sql
from agentic_rag import db,domains,indexes,pins,providers,search,store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.continuity.model import CheckpointSnapshot
from agentic_rag.continuity.store import upsert_snapshot
from agentic_rag.service import upgrade
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope


def require(value,reason):
 if not value:raise AssertionError(reason)


def write(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+'\n')


def digest_rows(cfg):
 with db.connect(cfg) as conn:
  conn.execute('SET TRANSACTION READ ONLY')
  conn.execute("SET LOCAL TIME ZONE 'UTC'")
  tables=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('benchmark_ownership','embedding_selection','embedding_generations','embedding_vectors') ORDER BY tablename")]
  return {table:[r['value'] for r in conn.execute(sql.SQL('SELECT to_jsonb(t)::text value FROM public.{} t ORDER BY to_jsonb(t)::text COLLATE "C"').format(sql.Identifier(table)))] for table in tables}


def preserved(before,after):
 for table,rows in before.items():
  require(not (Counter(rows)-Counter(after[table])),'original row changed or missing:'+table)
 return {'tables':len(before),'original_rows':sum(len(r) for r in before.values()),'all_original_rows_present':True,
         'derivative_tables_excluded':['embedding_selection','embedding_generations','embedding_vectors']}


def generation_rows(cfg,generation):
 with db.connect(cfg) as conn:
  return [r['value'] for r in conn.execute('SELECT to_jsonb(v)::text value FROM embedding_vectors v WHERE generation_id=%s ORDER BY chunk_id',(generation.id,))]


class Replay:
 def __init__(self,spec,results,input_sha256,*,models=('bge','nano','small')):
  if not models or models[0]!='bge' or len(models)<2 or len(set(models))!=len(models) or set(models)-{'bge','nano','small'}:raise ValueError('BGE and at least one distinct measured candidate required')
  self.spec=spec;self.maps={};self.events=[];self.mode='normal';self.models=models;self.input_files={}
  for model in models:
   root=results/(model+'-r0');raw={name:(root/name).read_bytes() for name in ('result.json','vectors.json')}
   self.input_files[model]={name:hashlib.sha256(data).hexdigest() for name,data in raw.items()}
   result=json.loads(raw['result.json'])
   require(result['status']=='complete','canonical model pass incomplete:'+model)
   require(result['input_sha256']==input_sha256,'canonical input bytes changed')
   vectors=json.loads(raw['vectors.json']);mapping={}
   for group in ('documents','queries','auxiliary'):
    for row in spec[group]:
     purpose=row.get('purpose','query' if group=='queries' else 'document')
     prefix=('Query: ' if purpose=='query' else 'Document: ') if model!='bge' else ''
     text=prefix+row['text'];vector=vectors[group][row['id']]
     if text in mapping:
      require(len(mapping[text])==len(vector) and max(abs(a-b) for a,b in zip(mapping[text],vector))<=1e-5,'same input vector differs beyond frozen float tolerance')
      continue
     mapping[text]=vector
   self.maps[model]=mapping
  self.ids={'bge':spec['model_identities']['bge']['model'],
            **{m:spec['model_identities'][m]['logical_recipe_id'] for m in models if m!='bge'}}

 @contextmanager
 def serve(self):
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def answer(self,status,payload):
    body=json.dumps(payload).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def do_GET(self):
    if self.path=='/api/tags':self.answer(200,{'models':[{'name':owner.ids['bge'],'digest':('0'*64 if owner.mode=='identity-drift' else owner.spec['model_identities']['bge']['digest'])}]})
    elif self.path=='/v1/models':self.answer(200,{'data':[{'id':('changed' if owner.mode=='identity-drift' else v)} for v in owner.ids.values()]})
    else:self.answer(404,{})
   def do_POST(self):
    try:
     count=int(self.headers.get('Content-Length','0'));require(0<count<=1024**2,'oversized replay input')
     body=json.loads(self.rfile.read(count));name=body['model'];model=next(k for k,v in owner.ids.items() if v==name)
     texts=body['input'];require(isinstance(texts,list) and 1<=len(texts)<=32,'replay batch bounds')
     require(all(isinstance(t,str) and t in owner.maps[model] for t in texts),'unknown replay input')
     if self.path not in ('/api/embed','/v1/embeddings'):return self.answer(404,{})
     owner.events.append({'model':model,'input_sha256':[hashlib.sha256(t.encode()).hexdigest() for t in texts],
         'path':self.path,'mode':owner.mode})
     if owner.mode=='outage':return self.answer(503,{'error':'synthetic owned outage'})
     if owner.mode=='query-probe-failed' and any(t=='Query: Synthetic connectivity probe; no stored knowledge.' for t in texts):return self.answer(503,{})
     values=[owner.maps[model][t] for t in texts]
     if owner.mode=='wrong-dimension':values=[v[:-1] for v in values]
     if self.path=='/api/embed':self.answer(200,{'embeddings':values})
     else:self.answer(200,{'model':name,'data':[{'index':i,'embedding':v} for i,v in enumerate(values)]})
    except Exception as exc:
     owner.events.append({'invalid_replay':type(exc).__name__});self.answer(422,{'error':'unknown or invalid public replay input'})
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:yield 'http://127.0.0.1:'+str(server.server_port)
  finally:server.shutdown();server.server_close();thread.join(timeout=5)


def operation(cfg,fn,*args,**kw):
 with db.connect(cfg) as conn:return fn(conn,cfg,*args,**kw)


def build_all(cfg,name):
 progress=[]
 for _ in range(64):
  result=operation(cfg,store.build_embedding_index,name,limit=4,allow_corpus=True);progress.append(result)
  if result['remaining']==0:return progress
 raise AssertionError('bounded build did not complete')


def read_queries(cfg,spec,doc_ids):
 reverse={value:key for key,value in doc_ids.items()};output=[]
 for q in spec['queries']:
  with db.connect(cfg,role='reader') as conn:
   hits,warnings=search.search(conn,cfg,q['text'],k=10,strategy='hybrid',rerank_mode='off',context_mode='off',temporal='off')
  require(not warnings,'unexpected hybrid fallback')
  output.append({'id':q['id'],'hits':[{'id':reverse[str(h.document_id)],'score':h.score} for h in hits]})
 return output


def run(args):
 require(os.environ.get('PGPORT')=='55460','owned test port55460 required')
 for key in ('PGHOST','PGHOSTADDR','PGSERVICE','PGSERVICEFILE'):require(not os.environ.get(key),'unset:'+key)
 out=Path(args.output);out.mkdir(mode=0o700);spec_path=Path(args.inputs);spec=json.loads(spec_path.read_text())
 replay=Replay(spec,Path(args.results),hashlib.sha256(spec_path.read_bytes()).hexdigest(),models=tuple(args.models));report={'status':'failed','started':datetime.now(timezone.utc).isoformat(),
  'model_timing_claim':False,'replay_only':True,'models':replay.models,
  'replay_inputs':replay.input_files,'rehearsal_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
  'unrehearsed_models':sorted({'bge','nano','small'}-set(replay.models)),'input_sha256':hashlib.sha256(spec_path.read_bytes()).hexdigest(),
  'steps':[],'hybrid':{}}
 def step(label,**facts):report['steps'].append({'label':label,**facts});write(out/'report.json',report)
 try:
  with replay.serve() as url:
   profile_map={m:providers.EmbeddingProfile(provider='ollama' if m=='bge' else 'openai-compatible',model=replay.ids[m],
    revision=spec['model_identities'][m].get('digest',replay.ids[m]),url=url,
    dimensions=spec['model_identities'][m]['dimensions'],normalization='l2',max_batch=4,
    document_prefix='' if m=='bge' else 'Document: ',query_prefix='' if m=='bge' else 'Query: ') for m in replay.models}
   cfg=Config(db_host='127.0.0.1',ollama_url=url,embed_model=replay.ids['bge'],embedding_profiles=profile_map)
   with isolated_database(cfg) as source:
    doc_ids={}
    with db.connect(source) as conn:
     domains.add_domain(conn,'benchmark-de','Public synthetic German fixture')
     domains.add_domain(conn,'benchmark-en','Public synthetic English fixture')
     original=json.loads((Path(args.corpus)).read_text())
     for row in original['documents']:
      saved=store.save_document(conn,source,title=row['title'],body=row['text'],domain='benchmark-'+row['language'],dtype='reference',slug=row['id'],scope='global',provenance={'source':'public-fictional-corpus','issue':83})
      require(not saved.warnings and not saved.redactions and saved.n_chunks==1,'canonical fixture ingestion changed input')
      doc_ids[row['id']]=str(saved.doc_id)
     pins.add_pin(conn,body='Keep the public source and previous index during model substitution.',scope='global')
     upsert_snapshot(conn,CheckpointSnapshot(session_id='benchmark83',turn_id='fixture',cursor='public-cursor',source='codex',trigger='manual',cwd='/synthetic/project',project_root='/synthetic/project'))
     actual={r['slug']:r['content'] for r in conn.execute('SELECT d.slug,c.content FROM documents d JOIN chunks c ON c.document_id=d.id')}
     require(actual=={r['id']:r['text'] for r in spec['documents']},'stored chunks differ from actual model inputs')
    baseline=digest_rows(source)
    step('populated-source',documents=len(doc_ids),pins=1,checkpoints=1)
    proof=upgrade.verified_backup(source,'0.6.32',out/'source.dump')
    require(proof['restore_verified'],'source strict restore')
    with isolated_database(cfg,initialize=False) as target:
     restored=upgrade.restore_target(target,out/'source.dump',proof['manifest'],apply=True)
     require(restored['restore_verified'] and restored['original_rows_unchanged'],'populated copy restore')
     require(digest_rows(target)==baseline,'source and restored original rows differ')
     step('verified-populated-restore',original_rows_unchanged=True)
     generations={};retained_vectors=None
     for m in replay.models:
      generations[m]=operation(target,store.create_embedding_index,m,m)
      first=operation(target,store.build_embedding_index,m,limit=1,allow_corpus=True)
      require(first['remaining']==45,'interrupted first batch coverage')
      replay.mode='outage'
      event_start=len(replay.events)
      with db.connect(target) as conn:
       before=conn.execute('SELECT count(*) n FROM embedding_vectors').fetchone()['n']
      try:operation(target,store.build_embedding_index,m,limit=4,allow_corpus=True)
      except providers.ProviderError as error:require(error.code=='transient','outage failed for an unrelated reason')
      else:raise AssertionError('outage accepted a build')
      require(any(e.get('mode')=='outage' and e.get('model')==m for e in replay.events[event_start:]),'outage inference was not reached')
      with db.connect(target) as conn:require(conn.execute('SELECT count(*) n FROM embedding_vectors').fetchone()['n']==before,'outage stored vectors')
      replay.mode='normal';progress=build_all(target,m)
      require(progress[-1]['remaining']==0,'resume coverage')
      if m!='bge':
       replay.mode='query-probe-failed'
       event_start=len(replay.events)
       with db.connect(target) as conn:previous=indexes.active(conn,target)
       try:operation(target,store.select_embedding_index,m)
       except providers.ProviderError as error:require(error.code=='transient','query-role probe failed for an unrelated reason')
       else:raise AssertionError('failed query-role probe switched pointer')
       query_hash=hashlib.sha256(b'Query: Synthetic connectivity probe; no stored knowledge.').hexdigest()
       require(any(e.get('mode')=='query-probe-failed' and query_hash in e.get('input_sha256',[]) for e in replay.events[event_start:]),'query-role inference was not reached')
       with db.connect(target) as conn:
        now=indexes.active(conn,target);require((now.id if now else None)==(previous.id if previous else None),'failed activation changed pointer')
       replay.mode='normal'
      operation(target,store.select_embedding_index,m)
      report['hybrid'][m]=read_queries(target,spec,doc_ids)
      require(preserved(baseline,digest_rows(target))['all_original_rows_present'],'original preservation')
      step('generation-'+m,dimensions=generations[m].dimensions,identity=generations[m].identity,build_batches=len(progress)+1,hybrid_queries=len(report['hybrid'][m]))
      if m=='bge':retained_vectors=generation_rows(target,generations['bge'])
      else:require(generation_rows(target,generations['bge'])==retained_vectors,'retained BGE vectors changed during candidate build')
     if 'small' in generations:
      require(generations['small'].dimensions==generations['bge'].dimensions and generations['small'].identity!=generations['bge'].identity,'equal dimension identity separation')
     for lang in ('de','en'):
      principal=Principal('reader-'+lang,None,'public-fixture',frozenset({'benchmark-'+lang}),frozenset(),frozenset({'global'}),frozenset())
      with request_scope(principal,target,read_only=True):
       with db.connect(target,role='reader') as conn:
        rows=conn.execute('SELECT id,domain FROM documents').fetchall();require(len(rows)==23 and all(r['domain']=='benchmark-'+lang for r in rows),'reader domain leak')
        hits,warnings=search.search(conn,target,spec['queries'][0]['text'],k=10,strategy='hybrid',rerank_mode='off',context_mode='off',temporal='off')
        require(not warnings and all(str(h.document_id) in {str(r['id']) for r in rows} for h in hits),'hybrid RLS leak')
      step('reader-'+lang,visible_documents=len(rows))
     # These failures must not change the selected generation or publish vectors.
     with db.connect(target) as conn:before=indexes.active(conn,target)
     for mode in ('wrong-dimension','identity-drift'):
      replay.mode=mode
      try:indexes.query_vector(before,target,spec['queries'][0]['text'])
      except providers.ProviderError as error:require(error.code==('invalid_response' if mode=='wrong-dimension' else 'model_missing'),'invalid provider failed for an unrelated reason:'+mode)
      else:raise AssertionError('invalid provider accepted:'+mode)
      replay.mode='normal'
      with db.connect(target) as conn:require(indexes.active(conn,target).id==before.id,'failure changed selected generation')
     # A same-dimension changed profile is refused before sending any text.
     candidate=replay.models[-1]
     edited=dataclasses.replace(target,embedding_profiles={**target.embedding_profiles,
         candidate:dataclasses.replace(profile_map[candidate],query_prefix='question: ')})
     event_count=len(replay.events)
     try:indexes.query_vector(before,edited,spec['queries'][0]['text'])
     except providers.ProviderError as error:require(error.code=='identity_mismatch','edited profile failed for an unrelated reason')
     else:raise AssertionError('edited profile reinterpreted retained vectors')
     require(len(replay.events)==event_count,'identity mismatch leaked an input')
     step('identity-dimension-and-profile-refused',selection_unchanged=True)
     aux=next(r for r in spec['auxiliary'] if r['id']=='post-write')
     with db.connect(target) as conn:
      added=store.save_document(conn,target,title=aux['title'],body=aux['body'],domain='benchmark-en',dtype='reference',scope='global')
      a=store.save_document(conn,target,title=aux['title'],body=aux['body'],domain='benchmark-en',dtype='reference',project='/synthetic/after-a')
      require(not added.warnings and not a.warnings,'post-cutover canonical writes')
     first=operation(target,store.build_embedding_index,'bge',limit=1,allow_corpus=True)
     require(first['remaining']==1,'partial catchup did not remain incomplete')
     with db.connect(target) as conn:
      b=store.save_document(conn,target,title=aux['title'],body=aux['body'],domain='benchmark-en',dtype='reference',project='/synthetic/after-b')
      require(not b.warnings,'write arriving between rebuild batches')
     try:operation(target,store.select_embedding_index,'bge',rollback=True)
     except ValueError:pass
     else:raise AssertionError('rollback ignored writes during rebuild')
     build_all(target,'bge');operation(target,store.select_embedding_index,'bge',rollback=True)
     require(not (Counter(retained_vectors)-Counter(generation_rows(target,generations['bge']))),'rollback changed retained BGE vectors')
     query=next(r['text'] for r in spec['auxiliary'] if r['id']=='post-query')
     with db.connect(target,role='reader') as conn:
      hits,warnings=search.search(conn,target,query,k=10,strategy='hybrid',rerank_mode='off',context_mode='off',temporal='off')
      require(not warnings and {str(added.doc_id),str(a.doc_id),str(b.doc_id)}<={str(h.document_id) for h in hits},'post-writes lost after rollback')
     from agentic_rag.scope import project_id
     principal=Principal('project-a',None,'public-fixture',frozenset({'benchmark-en'}),frozenset(),frozenset({project_id('/synthetic/after-a')}),frozenset())
     with request_scope(principal,target,read_only=True):
      with db.connect(target,role='reader') as conn:
       visible={str(r['id']) for r in conn.execute('SELECT id FROM documents')}
       require(visible=={str(a.doc_id)},'cross-project rows visible')
       hits,warnings=search.search(conn,target,query,k=10,strategy='hybrid',rerank_mode='off',context_mode='off',temporal='off')
       require(not warnings and {str(h.document_id) for h in hits}==visible,'cross-project vector results visible')
     # Real MCP tool dispatch and its scoped reader; no fake result transport.
     from agentic_rag.service.engine import invoke
     packet=asyncio.run(invoke('memory_search',{'query':query,'strategy':'hybrid','rerank':'off','context':'off','temporal':'off','k':10},principal,target,read_only=True))
     require(not packet['warnings'] and {str(h['document_id']) for h in packet['results']}=={str(a.doc_id)},'central MCP dispatch escaped project')
     # Execute the real owner CLI parser/entrypoint against this exact configuration.
     from agentic_rag import cli
     prior_loader=cli.load_config;cli.load_config=lambda:target
     try:
      with contextlib.redirect_stdout(io.StringIO()) as printed:exit_code=cli._main(['index','status','bge'])
     finally:cli.load_config=prior_loader
     status=json.loads(printed.getvalue());require(exit_code==0 and status['remaining']==0,'owner CLI coverage status')
     step('catchup-rollback-post-write',postwrite_preserved=True,writes_between_batches=True,project_RLS=True,central_MCP_dispatch=True,owner_CLI=True)
     report['preservation']=preserved(baseline,digest_rows(target))
     finalproof=upgrade.verified_backup(target,'0.6.32',out/'target.dump')
     require(finalproof['restore_verified'],'target strict restore')
     step('target-backup-verified',restore_verified=True)
    require(digest_rows(source)==baseline,'source was modified during copy rehearsal')
    step('source-unchanged',exact_all_rows=True)
  require(not any('invalid_replay' in e for e in replay.events),'unrecognized model input was attempted')
  report['status']='complete'
 except Exception as exc:
  report['failure']={'class':type(exc).__name__,'message':str(exc)[:1000]};raise
 finally:
  report['events']=replay.events;report['finished']=datetime.now(timezone.utc).isoformat();write(out/'report.json',report)


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 for field in ('inputs','results','corpus','output'):parser.add_argument('--'+field,required=True)
 parser.add_argument('--models',nargs='+',choices=('bge','nano','small'),default=('bge','nano','small'))
 run(parser.parse_args())
