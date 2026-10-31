"""Offline counts, provenance and live cleanup; never imports measured/model code."""
import collections, hashlib, json, socket, subprocess, unicodedata
from datetime import datetime, timezone
from pathlib import Path
REPO=Path('/home/administrator/Claude/agentic-rag/.worktrees/request-tracing-60-20261030')
ROOT=Path('/home/administrator/Claude/.scratch/rag62-three-models-20261030')
SRC=REPO/'docs/benchmarks/2026-10-30-multilingual-rerankers'
RUNS=ROOT/'runs-f'
read=lambda p:json.loads(p.read_text())
lines=lambda p:[json.loads(x) for x in p.read_text().splitlines()]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
terminal=read(RUNS/'matrix-exit.json')
assert terminal['exit']==0 and terminal['accepted_successful_units']==9 and terminal['failed_units']==1
assert terminal['protocol_status']=='original-protocol-incomplete-model-runtime-failure'
audit=read(ROOT/'audit-final-bounded-reconstruction.json')
summary=read(ROOT/'summary-final-audited.json')
assert audit['analyzer_output_matches'] and summary['total_observations']==2338
cases=read(SRC/'corpus.json')['cases']
assert all(sum(len(c['expected'])==2 for c in cases if c['language']==lang)==5 for lang in ('de','en'))
output=dict(utc=datetime.now(timezone.utc).isoformat(),models={},systemd=[],servers=[],public_preserved={},hashes={})
for name,m in summary['models'].items():
    rows=[]
    for rnd in range(1 if name=='jina-v3.5' else 3):
        unit=RUNS/f'{name}-r{rnd}';rows+=lines(unit/'observations.jsonl')
        pid=read(unit/'startup.json')['pid'];p=Path('/proc')/str(pid)/'cmdline'
        cmd=p.read_bytes().replace(b'\0',b' ').decode(errors='replace') if p.exists() else None
        assert cmd is None or 'server.py' not in cmd
        output['servers'].append(dict(model=name,round=rnd,pid=pid,current_command=cmd))
    counts=dict(collections.Counter(r['mode'] for r in rows))
    normal={'cold-first':3,'quality':192,'adapter':96,'cross-language':32,'long-context':48,'perturbation':24,'unsupported':16,'performance':225,'concurrency':35,'exact-symbol-bypass':1}
    failed={'cold-first':1,'quality':192,'adapter':96,'cross-language':32,'long-context':1}
    assert counts==(failed if name=='jina-v3.5' else normal),(name,counts)
    extra=dict(counts=counts,raw_censoring={},performance={},adapter={},concurrency={},perturbation_noops={})
    for mode in counts:
        rs=[r for r in rows if r['mode']==mode and 'diagnostics' not in r]
        extra['raw_censoring'][mode]=dict(attempted=len(rs),successful=sum(r['error'] is None for r in rs),censored=sum(r['error'] is not None for r in rs))
        assert all(r['metrics'] is None for r in rs if r['error'])
    for cell,perf in m['performance'].items():
        n,chars=map(int,cell.split('x'))
        rs=[r for r in rows if r['mode']=='performance' and r['candidates']==n and r['target_chars']==chars]
        assert len(rs)==(0 if name=='jina-v3.5' else 45)
        assert all(sum(r['round']==rnd for r in rs)==(0 if name=='jina-v3.5' else 15) for rnd in range(3))
        assert perf['http']['n']==len(rs) and perf['successful_http']['n']==sum(r['error'] is None for r in rs)
        extra['performance'][cell]=dict(attempted=len(rs),successful=sum(r['error'] is None for r in rs),censored=sum(r['error'] is not None for r in rs))
        if name=='jina-v3.5':assert all(perf['http'][k] is None for k in ('p50_ms','p95_ms','p99_ms','max_ms'))
    def q(rs):
        vals=[r['metrics'] for r in rs if r['metrics'] is not None]
        return dict(n=len(rs),scored_n=len(vals),top1_count=sum(v['top1'] for v in vals),all_sources3_count=sum(v['all_sources3'] for v in vals))
    for lang in ('de','en'):
        rs=[r for r in rows if r['mode']=='adapter' and r['language']==lang]
        oc=collections.Counter(r['diagnostics']['outcome'] for r in rs)
        assert sum(oc.values())==48 and all(r['order']==r['input'] for r in rs if r['diagnostics']['outcome']!='ranked')
        extra['adapter'][lang]=dict(outcomes={k:oc[k] for k in ('ranked','timeout','pressure','invalid','unavailable')},ranked_only_quality=q([r for r in rs if r['diagnostics']['outcome']=='ranked']),fallback_only_quality=q([r for r in rs if r['diagnostics']['outcome']!='ranked']))
    for n in (1,2,4):
        rs=[r for r in rows if r['mode']=='concurrency' and r['concurrency']==n]
        oc=collections.Counter(r['diagnostics']['outcome'] for r in rs)
        assert len(rs)==(0 if name=='jina-v3.5' else 5*n)
        extra['concurrency'][str(n)]=dict(outcomes={k:oc[k] for k in ('ranked','timeout','pressure','invalid','unavailable')},ranked_only_timing=audit['additional'][name]['concurrency_ranked_timing'][str(n)])
    for variant in ('whitespace','umlaut-ascii','unicode-nfd'):
        def change(q):
            if variant=='whitespace':return '  '+q.replace(' ','   ')+'  '
            if variant=='unicode-nfd':return unicodedata.normalize('NFD',q)
            return q.translate(str.maketrans({'ä':'ae','ö':'oe','ü':'ue','ß':'ss'}))
        firsts=[c for c in cases[:32] if '-1-' in c['id'] and c['language']=='de']
        rs=[r for r in rows if r['mode']=='perturbation' and r['variant']==variant]
        extra['perturbation_noops'][variant]=dict(attempted=len(rs),planned_noop_cases=[c['id'] for c in firsts if change(c['query'])==c['query']])
    if name=='jina-v3.5':
        fatal=rows[-1]
        assert fatal['case_id']=='access-negation-1-de' and fatal['position']=='beginning'
        assert fatal['error']=='ReadTimeout' and fatal['response'] is fatal['metrics'] is fatal['drain_ms'] is None
        assert fatal['drain_error']=='TimeoutError' and m['inference_count']==321
        assert m['process_ready']['n']==m['first_request']['n']==1
        extra['fatal_row']=fatal
    else:
        assert m['process_ready']['n']==m['first_request']['n']==3
    output['models'][name]=extra
for letter in ('a','b','c'):
    mapping={}
    for part,original in [('source',ROOT/f'rejected-{letter}-source'),('run',ROOT/f'runs-{letter}')]:
        tree=SRC/f'rejected-{letter}'/part
        relative=lambda d:{str(p.relative_to(d)) for p in d.rglob('*') if p.is_file()}
        assert relative(tree)==relative(original),(letter,part,'file-set drift')
        for p in tree.rglob('*'):
            if p.is_file():
                rel=p.relative_to(tree);assert sha(p)==sha(original/rel)
                mapping[part+'/'+str(rel)]=sha(p)
    oldseal=read(ROOT/f'runs-{letter}'/'matrix-seal.json')
    assert all(sha(SRC/f'rejected-{letter}'/'source'/f)==h for f,h in oldseal['frozen'].items())
    output['public_preserved'][f'rejected-{letter}']=mapping
for public,original in [('aborted-e','runs-e'),('rejected-d','runs-d')]:
    tree=SRC/public;mapping={}
    for p in tree.rglob('*'):
        if p.is_file():
            rel=p.relative_to(tree);assert sha(p)==sha(ROOT/original/rel),(public,str(rel))
            mapping[str(rel)]=sha(p)
    output['public_preserved'][public]=mapping
for record in terminal['completed']:
    unit=record['unit']
    result=subprocess.run(['systemctl','--user','show',unit,'-p','LoadState','-p','ActiveState','-p','SubState','-p','MainPID','-p','Result','-p','ExecMainStatus','-p','ControlGroup'],cwd=REPO,text=True,capture_output=True)
    props=dict(line.split('=',1) for line in result.stdout.splitlines())
    assert props['MainPID']=='0' and props['ControlGroup']==''
    assert props['ActiveState'] in ('inactive','failed') and props['SubState'] in ('dead','failed')
    if props['LoadState']!='not-found':
        assert props['ExecMainStatus']==str(record['exit'])
        assert props['Result']==('success' if record['exit']==0 else 'exit-code')
    path=read(RUNS/f"{record['model']}-r{record['round']}"/'exit.json')['envelope_after']['path']
    cg=Path('/sys/fs/cgroup')/path.lstrip('/')
    assert not cg.exists(),str(cg)
    output['systemd'].append(dict(unit=unit,properties=props,cgroup_exists=False,query_exit=result.returncode))
with socket.socket() as sock:errno=sock.connect_ex(('127.0.0.1',8782))
assert errno==111
output['port_8782_connect_errno']=errno
copies=list(Path('/dev/shm').glob('rag62-four-*'));assert not copies
output['temporary_model_directories']=[str(p) for p in copies]
relevant=[]
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():continue
    try:cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
    except (OSError,PermissionError):continue
    # Match actual argv executables; avoid matching the audit shell's script text.
    argv=cmd.split()
    if len(argv)>1 and any(x.endswith('/benchmark.py') or x.endswith('/resume_matrix.py') or x.endswith('/finish_bounded_matrix.py') for x in argv[:4]):relevant.append(dict(pid=int(proc.name),command=cmd))
    if len(argv)>2 and argv[1].endswith('/server.py') and '/dev/shm/rag62-four-' in cmd:relevant.append(dict(pid=int(proc.name),command=cmd))
assert not relevant,relevant
output['relevant_processes']=relevant
warning=read(ROOT/'audit-resumed-tokenizer-warning.json')
lib=ROOT/'venv/lib/python3.12/site-packages/transformers/tokenization_utils_base.py'
assert sha(lib)==warning['library_sha256']
output['retained_warning_library_sha256']=sha(lib)
for p in [RUNS/'matrix-exit.json',RUNS/'matrix-seal.json',ROOT/'summary-final-audited.json',ROOT/'audit-final-bounded-reconstruction.json',ROOT/'final_bounded_audit.py',ROOT/'final_bounded_supplement.py']:
    output['hashes'][str(p.relative_to(ROOT))]=sha(p)
output['checks_passed']=True
p=ROOT/'audit-final-bounded-supplement.json';p.write_text(json.dumps(output,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
print('PASS:2338 actual rows,350 unattempted,counts/provenance/resources cleanup; '+str(p))
