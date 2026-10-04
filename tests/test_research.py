"""Research must earn support from real upstream sources, never hit counts."""
import importlib
import importlib.util

from agentic_rag import evidence, domains, store
from agentic_rag.config import Config


def research_module():
    assert importlib.util.find_spec('agentic_rag.research') is not None, 'bounded research capability is missing'
    return importlib.import_module('agentic_rag.research')


def claim(conn, cfg, slug, body, *, source_ids=('one','two'), project='/projects/alpha', domain='programming', edges=None, confirmed=True):
    domains.add_domain(conn, domain)
    result = evidence.save(conn,cfg,title=slug,body=body,domain=domain,
        project=project,dtype='memory',claim_kind='stated',evidence=[{'namespace':'research-tests','source_id':s,
        'role':'user','quote':body,'complete':True} for s in source_ids],edges=edges)
    if confirmed:
        evidence.review(conn,result.doc_id,state='confirmed',reason='independent fixture sources checked')
    return result


def test_local_research_does_not_promote_duplicate_sources_or_answer_semantics(conn, cfg, monkeypatch):
    # Mutation caught: promote hit count or a duplicate source to independent support.
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    claim(conn,cfg,'architecture','The architecture uses PostgreSQL with pgvector.',source_ids=('shared',))
    result=r._research(conn,cfg,'architecture PostgreSQL',project='/projects/alpha',strategy='lexical')
    assert result['abstained'] is True
    assert result['supported']==[]
    assert result['missing_evidence']
    assert result['usage']['calls']<=16
    assert len(result['context'])<=12000

import dataclasses
import json
import pytest


def test_each_quote_needs_its_own_quorum_and_refuted_review_is_not_support(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    a=claim(conn,cfg,'storage','Storage uses PostgreSQL.',source_ids=('storage-only',))
    b=claim(conn,cfg,'constraint','Constraint forbids provider forks.',source_ids=('constraint-only',))
    result=r._research(conn,cfg,'Storage PostgreSQL? Constraint provider forks?',project='/projects/alpha',strategy='lexical')
    assert len(result['questions'])==2
    assert result['supported']==[]
    assert len({k for e in result['evidence'] for k in e['source_keys']})==2
    evidence.review(conn,a.doc_id,state='refuted',reason='fixture refutation')
    result=r._research(conn,cfg,'Storage PostgreSQL',project='/projects/alpha',history=True,strategy='lexical')
    assert result['supported']==[]


def test_confirmed_exact_excerpts_are_supported_but_local_answer_abstains(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    claim(conn,cfg,'storage','Storage uses PostgreSQL with pgvector.')
    result=r._research(conn,cfg,'Storage PostgreSQL',project='/projects/alpha',strategy='lexical')
    assert result['supported'], result
    assert result['supported'][0]['statement']=='Storage uses PostgreSQL with pgvector.'
    assert len(result['supported'][0]['source_keys'])==2
    assert result['abstained'] is True
    for e in result['evidence']:
        row=conn.execute('SELECT content FROM chunks WHERE id=%s',(e['chunk_id'],)).fetchone()
        assert row['content'][e['start']:e['end']]==e['text']


@pytest.mark.parametrize('field,value',[('steps',0),('steps',True),('calls',41),('calls',0),('seconds',float('nan')),('seconds',float('inf')),('seconds',True),('seconds',0),('context_chars',511),('context_chars',32001)])
def test_rejects_invalid_resource_limits(field,value):
    r=research_module()
    with pytest.raises(ValueError):r.ResearchBudget(**{field:value})


def test_repeated_failures_and_call_step_context_caps(conn,cfg):
    r=research_module()
    def fail(*a,**kw):raise RuntimeError('password=private-value')
    result=r._research(conn,cfg,'what missing?',strategy='lexical',retrieve=fail)
    assert result['termination']=='repeated_failure'
    assert result['usage']['calls']==2
    assert 'private-value' not in json.dumps(result)
    result=r._research(conn,cfg,'one? two?',strategy='lexical',budget=r.ResearchBudget(calls=1))
    assert result['termination']=='call_budget'
    assert result['usage']['calls']==1
    result=r._research(conn,cfg,'what unknown evidence?',strategy='lexical',budget=r.ResearchBudget(steps=1,context_chars=512))
    assert result['termination']=='step_budget'
    assert result['usage']['steps']==1
    assert len(result['context'])<=512


def test_default_never_calls_provider(conn,cfg):
    r=research_module()
    def forbidden(*a,**kw):pytest.fail('provider called without explicit opt-in')
    result=r._research(conn,cfg,'unknown',strategy='lexical',structured=forbidden)
    assert result['assessment'].startswith('local')
    assert result['abstained']


def test_provider_mode_accepts_exact_quote_and_rejects_invention(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    body='Storage uses PostgreSQL with pgvector.'
    claim(conn,cfg,'storage',body)
    def provider(prompt,schema,configuration,**kw):
        data=json.loads(prompt)
        if data['task']=='plan':return {'questions':['Storage PostgreSQL']}
        assert len(json.dumps(data['evidence'],ensure_ascii=False,separators=(',',':')))<=12000
        return {'claims':[{'question_index':0,'statement':body,'evidence_ids':[0]}],'disagreements':[],'follow_up':[]}
    result=r._research(conn,cfg,'Storage PostgreSQL',provider=True,structured=provider,project='/projects/alpha',strategy='lexical')
    assert result['abstained'] is False
    assert result['supported'], result
    assert result['supported'][0]['statement']==body
    def invention(prompt,*a,**kw):
        if json.loads(prompt)['task']=='plan':return {'questions':['Storage PostgreSQL']}
        return {'claims':[{'question_index':0,'statement':'Storage is hosted on Mars.','evidence_ids':[0]}],'disagreements':[],'follow_up':[]}
    result=r._research(conn,cfg,'Storage PostgreSQL',provider=True,structured=invention,project='/projects/alpha',strategy='lexical')
    assert result['abstained'] is True
    assert all(c['statement']!='Storage is hosted on Mars.' for c in result['supported'])


def test_configured_provider_runner_disables_inherited_claude_tools(monkeypatch):
    r=research_module()
    captured=[]
    def runner(cmd,**kwargs):
        captured.append((cmd,kwargs))
        return type('Result',(),{'returncode':0,'stdout':'{"questions":["storage"]}','stderr':''})()
    r._provider_transform('question',r._PLAN_SCHEMA,Config(),timeout=1,runner=runner)
    cmd,kw=captured[0]
    assert cmd[cmd.index('--tools')+1]==''
    assert '--strict-mcp-config' in cmd
    assert json.loads(cmd[cmd.index('--mcp-config')+1])=={'mcpServers':{}}
    assert cmd[cmd.index('--setting-sources')+1]==''
    assert '--no-session-persistence' in cmd
    assert '--disable-slash-commands' in cmd
    assert kw['env']['AGENTIC_RAG_HOOKS_DISABLE']=='1'


def test_cli_and_both_mcp_privileges_expose_readonly_research(conn,cfg,hook_env,monkeypatch,capsys):
    r=research_module()
    from agentic_rag import cli,mcp_server
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    claim(conn,cfg,'storage','Storage uses PostgreSQL with pgvector.')
    assert 'memory_research' in mcp_server.tool_names(True)
    assert set(mcp_server.tool_names(False))-set(mcp_server.tool_names(True))=={
        'memory_save','memory_assert','memory_source_state','memory_review_claim','memory_pin','memory_unpin',
        'memory_entity_alias','memory_entity_alias_review'}
    assert cli.main(['research','Storage PostgreSQL','--project','/projects/alpha','--strategy','lexical','--json'])==0
    out=json.loads(capsys.readouterr().out)
    assert len(out['supported'])==1
    import asyncio
    result=asyncio.run(mcp_server.memory_research('Storage PostgreSQL',project='/projects/alpha',strategy='lexical'))
    assert result['supported'][0]['statement']=='Storage uses PostgreSQL with pgvector.'


def test_graph_selects_relevant_late_chunk_and_keeps_foreign_endpoints_out(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    late='Latch resolution confirmed by probe after replacing socket.'
    # A 4000+ character raw document creates several real gateway chunks.
    body=('Unrelated handbook introduction. '*145)+'\n\n'+late
    domains.add_domain(conn,'programming')
    target=store.save_document(conn,cfg,title='operation-manual',body=body,domain='programming',dtype='memory',project='/projects/alpha')
    foreign=claim(conn,cfg,'foreign-resolution','Latch resolution is forbidden foreign evidence.',project='/projects/beta')
    seed=claim(conn,cfg,'latch-incident','Latch incident cause is stale socket.',edges=[
        store.EdgeSpec('references',target.slug,'inspect resolution handbook','high'),
        store.EdgeSpec('references',foreign.slug,'foreign link must not broaden scope','high')])
    # Only the initial retrieval boundary is narrowed: graph selection is real.
    from agentic_rag.search import search
    def only_seed(*a,**kw):
        return search(a[0],a[1],seed.doc_id,**{**kw,'strategy':'auto'})
    result=r._research(conn,cfg,'Latch resolution probe',project='/projects/alpha',domain='programming',strategy='lexical',retrieve=only_seed)
    relevant=[e for e in result['evidence'] if e['document_id']==target.doc_id]
    assert relevant and late in relevant[0]['text']
    assert all(e['document_id']!=foreign.doc_id for e in result['evidence'])
    first=conn.execute('SELECT id FROM chunks WHERE document_id=%s ORDER BY idx,id LIMIT 1',(target.doc_id,)).fetchone()
    assert relevant[0]['chunk_id']!=str(first['id'])


def test_explicit_contradiction_removes_disputed_support_and_abstains(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    a=claim(conn,cfg,'retention-long','Retention keeps records for ninety days.',source_ids=('a1','a2'))
    b=claim(conn,cfg,'retention-short','Retention keeps records for thirty days.',source_ids=('b1','b2'),
        edges=[store.EdgeSpec('contradicts',a.slug,'retention values conflict','high')])
    result=r._research(conn,cfg,'Retention records days',project='/projects/alpha',strategy='lexical')
    assert result['disagreement']
    assert result['supported']==[]
    assert result['abstained']
    assert len(result['disagreement'][0]['citations'])==2


@pytest.mark.parametrize('boundary,expected',[
    ('expired',False),('future',False),('as-of',True),('archived',False),
    ('foreign-domain',False),('expired-edge',False),('historical-edge',True)])
def test_research_hydration_and_graph_share_temporal_active_domain_boundaries(conn,cfg,monkeypatch,boundary,expected):
    """Real gateway fixtures; stale retrieval cannot bypass hydration guards.

    No gateway supports edge expiry editing. For those two cases a read-only
    SQL projection presents a past valid_to, without changing stored rows.
    """
    r=research_module()
    from agentic_rag.search import search
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    domains.add_domain(conn,'programming');domains.add_domain(conn,'infrastructure')
    text='Boundary recovery probe returned OK.'
    options={}
    if boundary in ('expired','future','as-of'):
        event='2099-01-01T00:00:00Z' if boundary=='future' else '2026-01-01T00:00:00Z'
        expiry='2026-03-01T00:00:00Z' if boundary=='expired' else None
        if boundary=='as-of':
            event='2027-01-01T00:00:00Z';expiry='2027-03-01T00:00:00Z'
            options['as_of']='2027-02-01T00:00:00Z'
        target=store.save_assertion(conn,cfg,entity='boundary',attribute='probe',value=text,
            event_at=event,expires_at=expiry,domain='programming',project='/projects/alpha',
            evidence={'source_id':'boundary-probe','role':'user','quote':text})
    else:
        target=store.save_document(conn,cfg,title='boundary-probe',body=text,
            status='archived' if boundary=='archived' else 'active',
            domain='infrastructure' if boundary=='foreign-domain' else 'programming',
            dtype='memory',project='/projects/alpha')
    seed=claim(conn,cfg,'boundary-incident','Boundary incident cause is stale socket.',edges=[
        store.EdgeSpec('references',target.slug,'probe verifies recovery','high')])
    seed_hits=search(conn,cfg,seed.doc_id,strategy='auto',project='/projects/alpha')[0]
    stale_hits=search(conn,cfg,target.doc_id,strategy='auto',project='/projects/alpha',history=True)[0]
    def retrieve(*a,**kw):
        # Expired/future hits intentionally reach the new hydration boundary.
        return seed_hits+(stale_hits if boundary in ('expired','future','as-of') else []),[]
    class ProjectedConnection:
        def __getattr__(self,name):return getattr(conn,name)
        def execute(self,query,args=None):
            if 'FROM edges e' in query:
                columns=[row['column_name'] for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='edges' ORDER BY ordinal_position")]
                projected=','.join("'2026-01-01T00:00:00Z'::timestamptz AS valid_to" if c=='valid_to' else c for c in columns)
                query=query.replace('FROM edges e',f'FROM (SELECT {projected} FROM edges) e')
            return conn.execute(query,args)
    connection=ProjectedConnection() if boundary in ('expired-edge','historical-edge') else conn
    if boundary=='historical-edge':options['history']=True
    result=r._research(connection,cfg,'Boundary recovery probe',domain='programming',project='/projects/alpha',
        strategy='lexical',retrieve=retrieve,**options)
    assert not any('failed' in warning for warning in result['warnings']),result
    assert seed.doc_id in {e['document_id'] for e in result['evidence']}
    assert (target.doc_id in {e['document_id'] for e in result['evidence']}) is expected,repr(result)


@pytest.mark.parametrize('trust',['unreviewed','assistant','incomplete','refuted-source','proposal'])
def test_unqualified_upstream_evidence_is_never_promoted(conn,cfg,monkeypatch,trust):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    domains.add_domain(conn,'programming')
    body='Storage uses PostgreSQL with pgvector.'
    a=evidence.save(conn,cfg,title='storage',body=body,domain='programming',dtype='memory',project='/projects/alpha',
        claim_kind='proposal' if trust=='proposal' else 'stated',evidence=[dict(namespace='trust-tests',source_id=s,
        role='assistant' if trust=='assistant' else 'user',quote=body,complete=trust!='incomplete') for s in ('one','two')])
    if trust!='unreviewed':evidence.review(conn,a.doc_id,state='confirmed',reason='fixture')
    if trust=='refuted-source':
        for source in evidence.sources(conn,a.doc_id):
            evidence.source_state(conn,source['source_key'],state='refuted',reason='fixture')
    result=r._research(conn,cfg,'Storage PostgreSQL',project='/projects/alpha',strategy='lexical',history=True)
    assert result['supported']==[]
    assert result['abstained']


def test_provider_context_redaction_and_malformed_outputs_fail_closed(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    claim(conn,cfg,'storage','Storage uses PostgreSQL with pgvector.')
    prompts=[]
    def malformed(prompt,*a,**kw):
        prompts.append(prompt)
        if json.loads(prompt)['task']=='plan':return {'questions':['Storage PostgreSQL']}
        return {'claims':[{'question_index':True,'statement':'Storage uses PostgreSQL with pgvector.','evidence_ids':[0]}],'disagreements':[],'follow_up':[]}
    result=r._research(conn,cfg,'Storage PostgreSQL password=secretvalue',provider=True,structured=malformed,project='/projects/alpha',strategy='lexical')
    assert all('secretvalue' not in p for p in prompts)
    assert result['abstained']
    assert result['assessment'].startswith('local')


def test_context_cap_has_real_omissions_and_all_citations_remain_exact(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    claim(conn,cfg,'storage','Storage uses PostgreSQL with pgvector.')
    result=r._research(conn,cfg,'Storage PostgreSQL',project='/projects/alpha',strategy='lexical',budget=r.ResearchBudget(context_chars=512))
    assert len(result['context'])<=512
    assert result['evidence']==[]
    assert result['supported']==[]
    assert 'context budget omitted additional evidence' in result['warnings']


def test_hard_deadline_kills_owned_worker_and_child_and_retry_is_clean(cfg,tmp_path,monkeypatch):
    import os,sys,time
    r=research_module()
    pidfile=tmp_path/'pids.json'
    script=tmp_path/'stall.py'
    script.write_text('import os,subprocess,sys,time,json\n'
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\n'
        f'open({str(pidfile)!r},"w").write(json.dumps([os.getpid(),child.pid]))\n'
        'time.sleep(60)\n')
    monkeypatch.setattr(r,'_worker_command',lambda:[sys.executable,str(script)])
    started=time.monotonic()
    result=r.research(cfg,'unknown',budget=r.ResearchBudget(seconds=.3))
    assert result['termination']=='time_budget'
    assert result['abstained']
    assert time.monotonic()-started<2
    pids=json.loads(pidfile.read_text())
    for pid in pids:
        # Reaped parent or orphan zombie are no longer running work.
        proc=__import__('subprocess').run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
        assert not proc.stdout.strip() or proc.stdout.strip().startswith('Z')
    monkeypatch.setattr(r,'_worker_command',lambda:[sys.executable,'-m','agentic_rag.research_worker'])
    result=r.research(cfg,'unknown',strategy='lexical')
    assert result['termination']=='complete'
    assert result['abstained']


def test_async_cancellation_propagates_and_reaps_worker(cfg,tmp_path,monkeypatch):
    import asyncio,sys,subprocess
    r=research_module()
    pidfile=tmp_path/'pid'
    script=tmp_path/'stall.py'
    script.write_text(f'import os,time\nopen({str(pidfile)!r},"w").write(str(os.getpid()))\ntime.sleep(60)\n')
    monkeypatch.setattr(r,'_worker_command',lambda:[sys.executable,str(script)])
    async def run():
        task=asyncio.create_task(r.research_async(cfg,'unknown'))
        for _ in range(100):
            if pidfile.exists():break
            await asyncio.sleep(.01)
        assert pidfile.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    result=subprocess.run(['ps','-p',pidfile.read_text(),'-o','stat='],capture_output=True,text=True)
    assert not result.stdout.strip()


def test_concurrent_research_clients_keep_filters_and_write_nothing(conn,cfg,monkeypatch):
    import asyncio
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    claim(conn,cfg,'alpha-storage','Storage uses PostgreSQL for Alpha.',project='/projects/alpha')
    claim(conn,cfg,'beta-storage','Storage uses SQLite for Beta.',project='/projects/beta')
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    async def run():
        return await asyncio.gather(r.research_async(cfg,'Storage',project='/projects/alpha',strategy='lexical'),
                                   r.research_async(cfg,'Storage',project='/projects/beta',strategy='lexical'))
    alpha,beta=asyncio.run(run())
    assert all('Alpha' in e['text'] for e in alpha['evidence'])
    assert all('Beta' in e['text'] for e in beta['evidence'])
    assert alpha['evidence'] and beta['evidence']
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before


def test_parent_does_not_resolve_project_outside_worker_deadline(cfg,tmp_path,monkeypatch):
    import asyncio,sys
    r=research_module()
    script=tmp_path/'stall.py';script.write_text('import time\ntime.sleep(60)\n')
    monkeypatch.setattr(r,'_worker_command',lambda:[sys.executable,str(script)])
    def forbidden(*a,**kw):pytest.fail('parent resolved project outside deadline')
    monkeypatch.setattr('agentic_rag.scope.selection',forbidden)
    async def run():
        ticks=[]
        async def heartbeat():
            for _ in range(5):
                await asyncio.sleep(.01);ticks.append(1)
        result,_=await asyncio.gather(r.research_async(cfg,'unknown',project='/projects/alpha',budget=r.ResearchBudget(seconds=.1)),heartbeat())
        assert result['termination']=='time_budget'
        assert len(ticks)==5
    asyncio.run(run())


def test_configured_codex_runner_removes_read_web_and_delegation_tools(monkeypatch):
    from pathlib import Path
    r=research_module(); captured=[]
    def runner(cmd,**kwargs):
        captured.append(cmd)
        if 'exec' in cmd:
            Path(cmd[cmd.index('--output-last-message')+1]).write_text('{"questions":["storage"]}')
        return type('Result',(),{'returncode':0,'stdout':'','stderr':''})()
    r._provider_transform('synthetic',r._PLAN_SCHEMA,dataclasses.replace(Config(),llm_provider='codex',llm_bin='codex'),timeout=1,runner=runner)
    cmd=next(cmd for cmd in captured if 'exec' in cmd)
    configs=[cmd[i+1] for i,x in enumerate(cmd[:-1]) if x=='-c']
    assert 'features.shell_tool=false' in configs
    assert 'features.unified_exec=false' in configs
    assert 'features.view_image=false' in configs
    assert 'features.multi_agent=false' in configs
    assert 'features.apps=false' in configs
    assert 'features.plugins=false' in configs
    assert 'features.browser_use=false' in configs
    assert 'web_search="disabled"' in configs
    assert 'mcp_servers={}' in configs
    assert '--ignore-user-config' in cmd and '--ignore-rules' in cmd
    assert '--no-daemon' in cmd


@pytest.mark.parametrize('name,value',[('steps',True),('calls',True),('seconds',True),('provider',1),('provider','true'),('history','false'),('min_sources',2.0),('context_chars',True)])
def test_mcp_wire_rejects_coercion_in_sensitive_research_controls(name,value):
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata
    from pydantic import ValidationError
    from agentic_rag.mcp_server import memory_research
    with pytest.raises(ValidationError):
        func_metadata(memory_research).arg_model.model_validate({'question':'q',name:value})


def test_graph_ranks_beyond_first_sixty_four_chunks(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    domains.add_domain(conn,'programming')
    late='Latch resolution confirmed by probe after replacing socket.'
    body=('Routine filler. '*230+'\n\n')*70+late
    target=store.save_document(conn,cfg,title='long-handbook',body=body,domain='programming',dtype='memory',project='/projects/alpha')
    seed=claim(conn,cfg,'latch-incident','Latch incident cause is stale socket.',edges=[store.EdgeSpec('references',target.slug,'handbook resolution proof','high')])
    from agentic_rag.search import search
    def only_seed(*a,**kw):return search(a[0],a[1],seed.doc_id,**{**kw,'strategy':'auto'})
    result=r._research(conn,cfg,'Latch resolution probe',project='/projects/alpha',strategy='lexical',retrieve=only_seed)
    relevant=[e for e in result['evidence'] if e['document_id']==target.doc_id]
    assert relevant and late in relevant[0]['text']


def test_deadline_cleans_nested_provider_temporary_evidence(cfg,tmp_path,monkeypatch):
    import sys
    r=research_module()
    report=tmp_path/'nested-path'
    script=tmp_path/'nested.py'
    script.write_text('import tempfile,pathlib,time\n'
        'nested=pathlib.Path(tempfile.mkdtemp(prefix="provider-evidence-"))\n'
        '(nested/"output.json").write_text("private-synthetic-sentinel")\n'
        f'pathlib.Path({str(report)!r}).write_text(str(nested))\n'
        'time.sleep(60)\n')
    monkeypatch.setattr(r,'_worker_command',lambda:[sys.executable,str(script)])
    out=r.research(cfg,'synthetic',budget=r.ResearchBudget(seconds=.3))
    assert out['termination']=='time_budget'
    nested=__import__('pathlib').Path(report.read_text())
    assert not nested.exists(), f'provider evidence survived at {nested}'


def test_real_mcp_cancellation_cleans_worker_and_keeps_server_responsive(tmp_path,monkeypatch):
    import asyncio,os,sys,subprocess
    import mcp.types as types
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    pidfile=tmp_path/'worker-pid'
    stall=tmp_path/'stall.py'
    stall.write_text(f'import os,time\nopen({str(pidfile)!r},"w").write(str(os.getpid()))\ntime.sleep(60)\n')
    harness=tmp_path/'server.py'
    harness.write_text('import sys\nfrom agentic_rag import research,mcp_server\n'
        f'research._worker_command=lambda:[sys.executable,{str(stall)!r}]\n'
        'mcp_server.build_server(True).run()\n')
    env=dict(os.environ,PYTHONPATH=str(__import__('pathlib').Path(__file__).resolve().parents[1]))
    async def run():
        async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(harness)],env=env),errlog=sys.__stderr__) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                request_id=session._request_id
                task=asyncio.create_task(session.call_tool('memory_research',{'question':'synthetic','strategy':'lexical'}))
                for _ in range(200):
                    if pidfile.exists():break
                    await asyncio.sleep(.01)
                assert pidfile.exists()
                await session.send_notification(types.ClientNotification(types.CancelledNotification(
                    params=types.CancelledNotificationParams(requestId=request_id,reason='test cancellation'))))
                await asyncio.sleep(.1)
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
                except __import__("mcp.shared.exceptions",fromlist=["McpError"]).McpError as exc:
                    assert "cancelled" in str(exc).lower()
                tools=await asyncio.wait_for(session.list_tools(),2)
                assert 'memory_research' in {t.name for t in tools.tools}
                for _ in range(100):
                    result=subprocess.run(['ps','-p',pidfile.read_text(),'-o','stat='],capture_output=True,text=True)
                    if not result.stdout.strip():break
                    await asyncio.sleep(.01)
                assert not result.stdout.strip()
    asyncio.run(run())


def test_graph_relevant_evidence_keeps_resolution_sentence_end(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    domains.add_domain(conn,'programming')
    proof='Beacon recovery probe returned OK after replacing the stale socket.'
    # Full gateway chunk is slightly over400; token coverage alone must not cut
    # the resolution halfway through the last word when graph research selects it.
    target=claim(conn,cfg,'Beacon handbook','Routine background. '*17+proof)
    seed=claim(conn,cfg,'Beacon cause','Beacon incident was caused by a stale socket.',edges=[store.EdgeSpec('references',target.slug,'resolution proof','high')])
    from agentic_rag.search import search
    def only_seed(*a,**kw):return search(a[0],a[1],seed.doc_id,**{**kw,'strategy':'auto'})
    result=r._research(conn,cfg,'Beacon recovery probe',project='/projects/alpha',strategy='lexical',retrieve=only_seed)
    assert any(proof in e['text'] for e in result['evidence'] if e['document_id']==target.doc_id)


def test_failed_provider_plan_latches_local_abstention(conn,cfg,monkeypatch):
    r=research_module()
    monkeypatch.setattr('agentic_rag.store.try_embed_texts',lambda *a:None)
    body='Storage uses PostgreSQL with pgvector.'
    claim(conn,cfg,'storage',body)
    stages=[]
    def transform(prompt,*a,**kw):
        stage=json.loads(prompt)['task'];stages.append(stage)
        if stage=='plan':return {'questions':[]}
        return {'claims':[{'question_index':0,'statement':body,'evidence_ids':[0]}],'disagreements':[],'follow_up':[]}
    result=r._research(conn,cfg,'Storage PostgreSQL',provider=True,structured=transform,project='/projects/alpha',strategy='lexical')
    assert result['abstained'] is True
    assert result['assessment'].startswith('local')
    assert stages==['plan']
    assert result['usage']['provider_calls']==1
