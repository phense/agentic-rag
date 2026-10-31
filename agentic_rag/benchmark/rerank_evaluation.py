"""Public, source-bound reranker comparison; labels enter only the scorer."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import statistics
import subprocess
import time
import httpx

from .. import db, domains, neural_rerank, search, store
from ..config import Config
from . import optimization
from .database import isolated_database

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path(__file__).with_name('corpus-reranker-v2.json')
BASE = '7a61955446119df522a34967273d8dacae56108b'
POLICIES = ('legacy-v1', 'focused-v1')
BASELINE_MODEL='agentic-rag-qwen3-reranker-0.6b-q8'
BASELINE_REVISION='22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48'
TINY_MODEL='agentic-rag-jina-tiny-en-q8'
TINY_REVISION='0defc1f8a1f4dd22183124a2a25a97765603e5a9e42258046c9b2c8a26d1f553'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def validate_corpus(corpus):
    optimization.validate(corpus)
    requests=set()
    for query in corpus['queries']:
        identity=canonical({key:query.get(key) for key in ('query','domain','project','scope','as_of')})
        if identity in requests:raise ValueError('duplicate quality request contract')
        requests.add(identity)
    attribution=corpus.get('attribution',{})
    prior=ROOT/'docs/benchmarks/2026-10-04-failure-evaluation/evaluation/dev-results.json'
    if (attribution.get('prior_report_sha256')!=sha256(prior.read_bytes()).hexdigest()
            or attribution.get('prior_profile')!='search-title-0'):
        raise ValueError('prior confirmed-failure attribution mismatch')
    rows={r['query_id']:r for r in json.loads(prior.read_text())['profiles'][0]['rows']}
    queries={q['id']:q for q in corpus['queries']}
    for item in attribution.get('confirmed_dev_failures',[]):
        q=queries.get(item.get('query_id'));old=rows.get(item.get('query_id'))
        if not q or q['split']!='dev' or not old or old['extractive_correct'] is not False:
            raise ValueError('confirmed failure must be a prior development miss')
        if old['selectors']['query']!=q['query']:
            raise ValueError('confirmed failure question changed')
    if not attribution.get('confirmed_dev_failures'):
        raise ValueError('confirmed failure attribution required')


def load_corpus():
    data=CORPUS.read_bytes();value=json.loads(data);validate_corpus(value)
    return value,sha256(data).hexdigest()


def ranking(ranked,expected,*,error=None):
    ranked=ranked[:3]
    wanted=set(expected);seen=set();dcg=0.0
    for index,identity in enumerate(ranked):
        if identity in wanted and identity not in seen:dcg+=1/math.log2(index+2)
        seen.add(identity)
    ideal=sum(1/math.log2(i+2) for i in range(min(len(wanted),3)))
    found=len(set(ranked)&wanted)
    return dict(recall=found/len(wanted) if wanted else None,
        precision=found/len(ranked) if wanted and ranked else 0.0 if wanted else None,
        ndcg=dcg/ideal if ideal else 0.0 if wanted else None,
        missing=sorted(wanted-set(ranked)),retrieval_empty=not ranked,
        correct_empty=not wanted and not ranked and error is None)


def choose(baseline,focused,*,split):
    if split!='dev' or not baseline or len(baseline)!=len(focused):
        raise ValueError('paired development-only selection required')
    if not any('ranked' in r.get('outcomes',[]) for r in focused):return 'legacy-v1'
    for a,b in zip(baseline,focused):
        if a['id']!=b['id']:raise ValueError('paired development identities required')
        if b.get('error') and not a.get('error'):return 'legacy-v1'
        for key in ('ndcg','recall'):
            if float(b.get(key) or 0)<float(a.get(key) or 0):return 'legacy-v1'
        failures=lambda row:sum(x in ('timeout','invalid','unavailable','pressure') for x in row.get('outcomes',[]))
        if failures(b)>failures(a):
            return 'legacy-v1'
    return ('focused-v1' if statistics.median(r['latency_ms'] for r in focused)
            <=.9*statistics.median(r['latency_ms'] for r in baseline) else 'legacy-v1')


def _new(path,value):
    path=Path(path)
    if any(p.is_symlink() for p in [path,*path.parents]):raise ValueError('symlink output refused')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o644)
    with os.fdopen(fd,'w') as f:f.write(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def seal(payload,path):
    value=json.loads(canonical(payload));value['seal_sha256']=sha256(canonical(value).encode()).hexdigest()
    _new(path,value);return value


def read_seal(path,source,corpus_hash):
    value=json.loads(Path(path).read_text());payload={k:v for k,v in value.items() if k!='seal_sha256'}
    if value.get('seal_sha256')!=sha256(canonical(payload).encode()).hexdigest():raise ValueError('invalid candidate seal')
    if value.get('source')!=source or value.get('corpus_sha256')!=corpus_hash:raise ValueError('candidate source/corpus drift')
    if value.get('choice') not in (*POLICIES,'tiny-focused-v1'):raise ValueError('unsupported sealed policy')
    return value


def summarize(rows):
    positive=[r for r in rows if not r['unanswerable']];negative=[r for r in rows if r['unanswerable']]
    timings=[v for r in rows for v in r['raw_ms']];warm=[v for r in rows for v in r['warm_ms']]
    mean=lambda values:statistics.fmean(values) if values else None
    percentile=lambda values:sorted(values)[math.ceil(.95*len(values))-1] if values else None
    failed=lambda row:bool(row['error']) or any(t.get('error') for t in row.get('trials',[]))
    citation_failed=any(t.get('error')=='original_citation_mismatch' for r in rows for t in r.get('trials',[]))
    return dict(queries=len(rows),answerable=len(positive),unanswerable=len(negative),
        independent_families=len({r['family'] for r in rows}),family_interval=None,
        source_recall=mean([r['recall'] for r in positive]),source_precision=mean([r['precision'] for r in positive]),
        ndcg_at_3=mean([r['ndcg'] for r in positive]),
        misses=[r['id'] for r in rows if r['missing'] or failed(r)],
        query_failures=sum(failed(r) for r in rows),
        trial_failures=sum(bool(t.get('error')) for r in rows for t in r.get('trials',[])),
        empty_retrievals=sum(r['retrieval_empty'] for r in rows),correct_empty=sum(r['correct_empty'] for r in negative),
        false_empty=sum(r['retrieval_empty'] for r in positive),
        citation_parity=not citation_failed and all(r['citation_parity'] for r in rows),
        inference_outcomes=dict(Counter(x for r in rows for x in r['outcomes'])),
        timing_observations=len(timings),p50_ms=statistics.median(timings) if timings else None,p95_ms=percentile(timings),
        first_p50_ms=statistics.median([r['first_ms'] for r in rows]) if rows else None,
        first_p95_ms=percentile([r['first_ms'] for r in rows]),
        warm_p50_ms=statistics.median(warm) if warm else None,warm_p95_ms=percentile(warm),
        sequential_queries_per_second=1000*len(timings)/sum(timings) if sum(timings) else None,
        context_chars_mean=mean([r['context_chars'] for r in rows]))


def sources():
    files=[*ROOT.joinpath('agentic_rag').rglob('*.py'),*ROOT.joinpath('sql').glob('*.sql'),
           ROOT/'scripts/evaluate_reranker.py',ROOT/'scripts/build_reranker_corpus.py',
           ROOT/'scripts/rehearse_reranker.py',ROOT/'pyproject.toml',ROOT/'uv.lock',CORPUS]
    return {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def reference_snapshot(*,require=True):
    path=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::')[-1].lstrip('/')
    result={key:(path/key).read_text().strip() for key in ('cpu.max',
        'memory.max','memory.swap.max','memory.current','memory.peak','cpu.stat','memory.events')}
    result['cpuset.cpus.effective']=((path/'cpuset.cpus.effective').read_text().strip()
        if (path/'cpuset.cpus.effective').exists() else 'not delegated')
    result['affinity_cpus']=sorted(os.sched_getaffinity(0))
    if require and (result['cpu.max']!='400000 100000' or result['affinity_cpus']!=[0,1,2,3]
            or result['memory.max']!='8589934592' or result['memory.swap.max']!='0'):
        raise ValueError('effective combined4CPU8GiBzero-swap envelope required')
    result['member_count']=len((path/'cgroup.procs').read_text().splitlines())
    return result


def owned_database_preflight(cfg,data):
    """Read-only proof that PostgreSQL belongs to this same bounded lab unit."""
    if data is None or os.environ.get('PGPORT','5432')=='5432':
        raise ValueError('explicit owned test PostgreSQL required')
    data=Path(data)
    if data.is_symlink() or data.stat().st_uid!=os.getuid():raise ValueError('owned PostgreSQL directory required')
    with db.connect(cfg,dbname='postgres') as conn:
        actual=Path(conn.execute('SHOW data_directory').fetchone()['data_directory'])
    if actual.resolve()!=data.resolve():raise ValueError('owned PostgreSQL directory mismatch')
    lines=(data/'postmaster.pid').read_text().splitlines();pid=int(lines[0])
    if lines[3]!=os.environ['PGPORT']:raise ValueError('owned PostgreSQL port mismatch')
    own=Path('/proc/self/cgroup').read_bytes()
    if Path('/proc',str(pid),'cgroup').read_bytes()!=own:raise ValueError('PostgreSQL outside measured service cgroup')
    return {'same_cgroup':True,'validated_owned_directory':True,'port_is_nonproduction':True}


def _snapshot(conn):
    from psycopg import sql
    result={}
    for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall():
        statement=sql.SQL('SELECT row_to_json(t)::text AS row FROM {} t').format(sql.Identifier(row['tablename']))
        values=sorted(x['row'] for x in conn.execute(statement))
        result[row['tablename']]=sha256(canonical(values).encode()).hexdigest()
    return result


def _ingest(conn,cfg,documents):
    mapping={};failures={}
    for name in sorted({d['domain'] for d in documents}):domains.add_domain(conn,name,actor='public-benchmark')
    for d in documents:
        try:
            evidence=optimization._evidence(d)
            common=dict(domain=d['domain'],project=d.get('project'),scope=d.get('scope'),actor='cli')
            if 'assertion' in d:
                evidence['event_at']=d['assertion']['event_at']
                saved=store.save_assertion(conn,cfg,**d['assertion'],evidence=evidence,**common)
                if saved.disposition!='accepted':raise ValueError('fixture_assertion_rejected')
                identity=saved.doc_id
            elif 'alias' in d:
                evidence['timestamp']=d['alias']['effective_at']
                saved=store.save_entity_alias(conn,cfg,**d['alias'],evidence=evidence,confirm=True,**common)
                if saved['state']!='accepted':raise ValueError('fixture_alias_rejected')
                identity=saved['document_id']
            else:
                saved=store.save_claim(conn,cfg,title=d['title'],body=d['body'],
                    dtype='memory',claim_kind='stated',evidence=[evidence],**common)
                identity=saved.doc_id
            if 'alias' not in d:store.review_claim(conn,identity,state='confirmed',reason='Public authored fixture',actor=d['actor'])
            mapping[str(identity)]=d['id']
        except Exception as exc:
            conn.rollback();failures[d['id']]=type(exc).__name__
    conn.commit();return mapping,failures


def _before_order():
    raw=subprocess.check_output(['git','show',BASE+':agentic_rag/neural_rerank.py'],cwd=ROOT)
    import types
    module=types.ModuleType('agentic_rag._rerank_before62');module.__package__='agentic_rag'
    exec(compile(raw,'<verified-before62>','exec'),module.__dict__)
    return module,sha256(raw).hexdigest()


def _drain(url):
    """Do not time the next model while a timed-out native request still runs."""
    start=time.perf_counter();observations=0
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=1) as client:
        while time.perf_counter()-start<30:
            try:
                with client.stream('GET',url+'/slots') as response:
                    response.raise_for_status();body=bytearray()
                    for part in response.iter_bytes():
                        if len(body)+len(part)>32768:raise ValueError('runtime_idle_response_oversized')
                        body.extend(part)
            except httpx.TimeoutException:
                observations+=1
                continue  # Busy native work can delay the idle endpoint itself.
            rows=json.loads(body);observations+=1
            if not isinstance(rows,list) or not rows or len(rows)>8 or any(type(r.get('is_processing')) is not bool for r in rows):
                raise ValueError('runtime_idle_unverifiable')
            if not any(r['is_processing'] for r in rows):
                return {'idle_verified':True,'observations':observations,'drain_ms':round((time.perf_counter()-start)*1000,3)}
            time.sleep(.05)
    raise TimeoutError('runtime_idle_timeout')


def _one(conn,cfg,q,mapping,policy,before,*,tiny_url=None):
    info={};original_order=neural_rerank.order
    if policy=='legacy-v1':
        original_scores=before._scores
        async def scores(url,query,passages):
            try:
                result=await original_scores(url,query,passages)
                info.update(outcome='ranked' if result is not None else 'unavailable',
                    candidates=len(passages) if result is not None else 0)
                return result
            except TimeoutError:info.update(outcome='timeout');raise
            except Exception:info.update(outcome='invalid');raise
        before._scores=scores
        def observed(query,hits,config):
            return before.order(query,hits,config)
        neural_rerank.order=observed
    else:
        def observed(query,hits,config,**kwargs):
            return original_order(query,hits,config,diagnostics=info)
        neural_rerank.order=observed
    config=replace(cfg,rerank_policy='focused-v1' if policy=='tiny-focused-v1' else policy,rerank_diagnostics=False)
    if policy=='tiny-focused-v1':
        config=replace(config,rerank_url=tiny_url,rerank_model=TINY_MODEL,rerank_revision=TINY_REVISION)
    options={key:q.get(key) for key in ('domain','project','scope','as_of')}
    error=None;values=[];warnings=[]
    start=time.perf_counter();cpu=time.process_time()
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        values,warnings=search.search(conn,config,q['query'],k=3,context_mode='off',**options)
        elapsed=(time.perf_counter()-start)*1000;used=time.process_time()-cpu
        for hit in values:
            row=conn.execute('SELECT c.content,d.domain,d.project_scope,d.status,assertion_eligible(d.id,%s::timestamptz,false) AS eligible '
                'FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=%s',
                (q['as_of'],hit.chunk_id)).fetchone()
            if row is None or row['content'][hit.snippet_start:hit.snippet_end]!=hit.snippet:
                raise ValueError('original_citation_mismatch')
            from ..scope import selection
            scopes=selection(q.get('project'),q.get('scope'))
            if row['domain']!=q['domain'] or row['status']!='active' or not row['eligible'] or scopes is not None and row['project_scope'] not in scopes:
                raise ValueError('source_eligibility_mismatch')
    except Exception as exc:
        error=(str(exc) if isinstance(exc,ValueError) and str(exc) in
            ('original_citation_mismatch','source_eligibility_mismatch') else type(exc).__name__)
        elapsed=(time.perf_counter()-start)*1000;used=time.process_time()-cpu
        values=[]
    finally:
        conn.rollback();neural_rerank.order=original_order
        if policy=='legacy-v1':before._scores=original_scores
    ranked=[mapping.get(h.document_id,'unmapped') for h in values]
    serialized=[]
    for h in values:
        item=asdict(h)
        if h.verified_at is not None:item['verified_at']=h.verified_at.isoformat()
        serialized.append(item)
    try:drain=_drain(config.rerank_url)
    except Exception as exc:
        error=error or type(exc).__name__;drain={'idle_verified':False,'drain_error':type(exc).__name__}
    return dict(ranked=ranked,hits=serialized,error=error,latency_ms=round(elapsed,3),drain=drain,
        cpu_seconds=used,diagnostic=info or {'outcome':'bypass'},
        warnings=[w for w in warnings if not w.startswith('embedding unavailable')])


def _phase(cfg,corpus,split,repeats,before,progress,*,tiny_url=None):
    policies=(*POLICIES,'tiny-focused-v1') if tiny_url else POLICIES
    rows={p:[] for p in policies};docs=[d for d in corpus['documents'] if d['split']==split]
    phase_start=time.perf_counter();cpu=time.process_time()
    with isolated_database(cfg) as owned:
        with db.connect(owned) as writer:mapping,failures=_ingest(writer,owned,docs);snapshot=_snapshot(writer)
        with db.connect(owned,role='reader') as conn:
            for q in [q for q in corpus['queries'] if q['split']==split]:
                trials={p:[] for p in policies}
                for iteration in range(repeats+1):
                    for policy in policies if iteration%2==0 else reversed(policies):
                        trials[policy].append(_one(conn,owned,q,mapping,policy,before,tiny_url=tiny_url))
                common={h['citation']:h for h in trials['legacy-v1'][0]['hits']}
                for policy in policies:
                    first=trials[policy][0];timings=[t['latency_ms'] for t in trials[policy]]
                    parity=all(h==common[h['citation']] for t in trials[policy] for h in t['hits'] if h['citation'] in common)
                    errors=[t['error'] for t in trials[policy] if t['error']]
                    error=errors[0] if errors else None
                    if any(identity in failures for identity in q['expected_ids']):error='indexing_failed'
                    score=ranking(first['ranked'],q['expected_ids'],error=error)
                    rows[policy].append(dict(id=q['id'],family=q['family'],category=q['category'],language=q['language'],
                        unanswerable=q['unanswerable'],expected=q['expected_ids'],ranked=first['ranked'],**score,
                        error=error,latency_ms=statistics.median(timings),first_ms=timings[0],
                        raw_ms=timings,warm_ms=timings[1:],cpu_seconds=sum(t['cpu_seconds'] for t in trials[policy]),
                        citation_parity=parity,context_chars=sum(len(h['snippet']) for h in first['hits']),
                        outcomes=[t['diagnostic']['outcome'] for t in trials[policy]],
                        trials=trials[policy]))
                if progress:progress(split,q['id'])
        with db.connect(owned) as writer:
            if _snapshot(writer)!=snapshot:raise ValueError('canonical_store_changed_during_reads')
    elapsed=time.perf_counter()-phase_start
    return dict(split=split,source_denominator=len(docs),indexed_sources=len(mapping),failed_sources=failures,
        canonical_rows_unchanged=True,cleanup_verified=True,elapsed_seconds=time.perf_counter()-phase_start,
        realized_queries_per_second=sum(len(r['trials']) for p in rows.values() for r in p)/elapsed,
        measured_drain_seconds=sum(t['drain'].get('drain_ms',0) for p in rows.values() for r in p for t in r['trials'])/1000,
        python_cpu_seconds=time.process_time()-cpu,python_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        profiles={p:dict(summary=summarize(rows[p]),rows=rows[p]) for p in policies})


def run(cfg,*,output,repeats=2,progress=None,tiny_url=None,owned_pg_data=None,runtime_manifest=None):
    if type(repeats) is not int or not 1<=repeats<=5:raise ValueError('repeats must be1..5')
    neural_rerank._url(cfg.rerank_url)
    if tiny_url:neural_rerank._url(tiny_url)
    if cfg.ollama_url!='http://127.0.0.1:1':raise ValueError('evaluation requires isolated disabled embedding endpoint')
    if cfg.rerank_model!=BASELINE_MODEL or cfg.rerank_revision!=BASELINE_REVISION or cfg.rerank_timeout_seconds!=1.5:
        raise ValueError('preregistered baseline model/revision/deadline required')
    corpus,corpus_hash=load_corpus();source=sources();reference=reference_snapshot();before,old_hash=_before_order()
    owned=owned_database_preflight(cfg,owned_pg_data)
    if runtime_manifest is None:raise ValueError('verified runtime manifest required')
    runtime_manifest=Path(runtime_manifest);runtime_hash=sha256(runtime_manifest.read_bytes()).hexdigest()
    profiles={
        'legacy-v1':dict(policy='legacy-v1',model=cfg.rerank_model,revision=cfg.rerank_revision,candidates=12,passage_chars=1200,endpoint_sha256=sha256(cfg.rerank_url.encode()).hexdigest()),
        'focused-v1':dict(policy='focused-v1',model=cfg.rerank_model,revision=cfg.rerank_revision,candidates=6,passage_chars=600,endpoint_sha256=sha256(cfg.rerank_url.encode()).hexdigest())}
    if tiny_url:profiles['tiny-focused-v1']=dict(policy='focused-v1',model=TINY_MODEL,revision=TINY_REVISION,candidates=6,passage_chars=600,endpoint_sha256=sha256(tiny_url.encode()).hexdigest())
    output=Path(output)
    if any(p.is_symlink() for p in [output,*output.parents]):raise ValueError('symlink output refused')
    output.mkdir(parents=True,exist_ok=False)
    development=_phase(cfg,corpus,'dev',1,before,progress,tiny_url=tiny_url);_new(output/'dev-results.json',development)
    choice=choose(development['profiles']['legacy-v1']['rows'],development['profiles']['focused-v1']['rows'],split='dev')
    if tiny_url and choose(development['profiles']['legacy-v1']['rows'],development['profiles']['tiny-focused-v1']['rows'],split='dev')=='focused-v1':
        if choice=='legacy-v1' or statistics.median(r['latency_ms'] for r in development['profiles']['tiny-focused-v1']['rows']) < statistics.median(r['latency_ms'] for r in development['profiles']['focused-v1']['rows']):
            choice='tiny-focused-v1'
    confirmed={r['query_id'] for r in corpus['attribution']['confirmed_dev_failures']}
    reproduction=[{k:r[k] for k in ('id','ranked','expected','recall','ndcg','error')}
        for r in development['profiles']['legacy-v1']['rows'] if r['id'] in confirmed]
    if sources()!=source:raise ValueError('development source drift')
    frozen=seal(dict(choice=choice,source=source,corpus_sha256=corpus_hash,source_base=BASE,
        baseline_order_sha256=old_hash,policies=list(development['profiles']),development_sha256=sha256(canonical(development).encode()).hexdigest(),
        profiles=profiles,selected_profile=profiles[choice],runtime_manifest_sha256=runtime_hash,
        budgets=dict(k=3,query_chars=512,context_chars=1200,deadline_seconds=1.5,response_bytes=32768,inflight=2),
        quality_denominator='one first observation per unique query; all trial failures retained',
        confirmed_baseline_reproductions=reproduction),output/'candidate.json')
    heldout=_phase(cfg,corpus,'test',repeats,before,progress,tiny_url=tiny_url)
    read_seal(output/'candidate.json',sources(),sha256(CORPUS.read_bytes()).hexdigest())
    if sha256(runtime_manifest.read_bytes()).hexdigest()!=runtime_hash:raise ValueError('runtime manifest drift')
    _new(output/'heldout-results.json',heldout)
    result=dict(version=1,synthetic=True,source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        candidate=frozen,development=development,heldout=heldout,reference_before=reference,reference_after=reference_snapshot(),owned_postgres=owned,
        limits=['Public synthetic families; no general answer accuracy or truth probabilities.',
          'Legacy route loads exact0.6.14 order module; both use current identical eligible lexical candidates.',
          'Disabled embeddings; no embedding-quality claim. Previously published failure families are development only.',
          'New query/connection first calls retain warm model/OS pages; runtime process-cold startup recorded separately.',
          'Shared host under combined4CPU/8GiBzero-swap envelope; no dedicated VM or fleet-capacity claim.',
          'Three held-out families; family confidence interval unavailable. Repeated timings never add quality cases.',
          'Empty retrieval is not a general answerer abstention; irrelevant candidates remain visible.'],
        hosted_provider_calls=0,default_policy_changed=False)
    _new(output/'results.json',result)
    return result
