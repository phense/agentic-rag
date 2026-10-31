"""Offline hook input survives source removal and compaction without local inference."""
import json
from dataclasses import replace
from io import StringIO

import pytest

from agentic_rag.config import Config


def remote_config(tmp_path):
    token=tmp_path/'key';token.write_text('synthetic-client-key');token.chmod(0o600)
    return replace(Config(),service_mode='client',service_url='https://rag.invalid',service_token_file=token,service_spool_dir=tmp_path/'spool')


def test_owned_source_survives_removed_original_and_replays_exactly(tmp_path):
    from agentic_rag.service.client import RemoteClient
    from agentic_rag.service.local import capture_transcript, stage_sources
    cfg=remote_config(tmp_path);source=tmp_path/'session.jsonl'
    first=json.dumps({'uuid':'one','message':{'role':'user','content':'A durable project fact.'}})+'\n'
    source.write_text(first)
    payload={'session_id':'s','cwd':str(tmp_path),'transcript_path':str(source)}
    capture_transcript(cfg,payload)
    with source.open('a') as f:f.write(json.dumps({'uuid':'two','message':{'role':'assistant','content':'Recorded.'}})+'\n')
    capture_transcript(cfg,payload);source.unlink()
    with RemoteClient(cfg) as client:
        assert stage_sources(client)==1
        pending=client.spool.pending()
        assert len(pending)==1
        assert pending[0]['kind']=='window'
        window=json.loads(pending[0]['payload'])
        assert window['window']['text']=='[user] A durable project fact.\n[assistant] Recorded.'
        assert stage_sources(client)==0
        assert len(client.spool.pending())==1


def test_offline_compaction_and_startup_never_connect_database(tmp_path,monkeypatch):
    from agentic_rag import db
    from agentic_rag.hooks import pre_compact,post_compact,session_start,common
    from agentic_rag.service.client import RemoteClient
    cfg=remote_config(tmp_path)
    for module in (pre_compact,post_compact,session_start):monkeypatch.setattr(module,'load_config',lambda:cfg)
    monkeypatch.setattr(common,'spawn_worker',lambda:None)
    monkeypatch.setattr(db,'connect',lambda *a,**k:pytest.fail('client hook opened local DB'))
    monkeypatch.setattr(RemoteClient,'context',lambda *a,**k:'⚠️ agentic-rag unavailable: network_unavailable')
    payload={'session_id':'s','cwd':str(tmp_path),'trigger':'manual','source':'compact','turn_id':'turn-1'}
    pre_compact.run(payload,StringIO())
    post_compact.run({**payload,'compact_summary':'<summary>Continue the unfinished migration safely.</summary>'},StringIO())
    out=StringIO();session_start.run(payload,out)
    assert 'Continue the unfinished migration safely.' in out.getvalue()
    assert 'local checkpoint' in out.getvalue()
    with RemoteClient(cfg) as client:
        packet=client.spool.latest_checkpoint('s')
        assert packet['compacted'] is True
        assert packet['snapshot']['turn_id']=='turn-1'
        assert packet['snapshot']['trigger']=='manual'


def test_source_change_and_capacity_never_discard_buffered_input(tmp_path):
    from agentic_rag.service.spool import Spool,SpoolFull
    with Spool(tmp_path/'private'/'spool.sqlite','a',max_bytes=1024) as spool:
        spool.capture_source('s','/a',b'original\n')
        with pytest.raises(ValueError,match='changed'):spool.capture_source('s','/a',b'changed\n')
        with pytest.raises(SpoolFull):spool.capture_source('other','/a',b'x'*1024)
        assert spool.sources()[0]['raw']==b'original\n'


def test_stop_prompt_and_agy_hooks_never_use_local_database(tmp_path,monkeypatch):
    from agentic_rag import config,db
    from agentic_rag.hooks import transcript_delta,prompt_recall,agy,common
    from agentic_rag.service.client import RemoteClient
    cfg=remote_config(tmp_path)
    for module in (config,transcript_delta,prompt_recall):monkeypatch.setattr(module,'load_config',lambda:cfg)
    monkeypatch.setattr(common,'spawn_worker',lambda:None)
    monkeypatch.setattr(db,'connect',lambda *a,**k:pytest.fail('remote adapter opened local DB'))
    monkeypatch.setattr(RemoteClient,'context',lambda *a,**k:'shared remote context')
    source=tmp_path/'session.jsonl';source.write_text('{}\n')
    transcript_delta.enqueue_transcript_delta({'session_id':'s','cwd':str(tmp_path),'transcript_path':str(source)},hook='test')
    out=StringIO();prompt_recall.run({'session_id':'s','cwd':str(tmp_path),'prompt':'RuntimeError: broken'},out)
    assert 'shared remote context' in out.getvalue()
    assert 'shared remote context' in str(agy.session_start({'conversationId':'s','workspacePaths':[str(tmp_path)]}))


def test_stdio_proxy_exposes_only_ro_tools_and_forwards_without_database(tmp_path,monkeypatch):
    import asyncio
    from agentic_rag import config,db,mcp_server
    from agentic_rag.service.client import RemoteClient
    cfg=remote_config(tmp_path);monkeypatch.setattr(config,'load_config',lambda:cfg)
    monkeypatch.setattr(db,'connect',lambda *a,**k:pytest.fail('stdio proxy opened local DB'))
    calls=[]
    def invoke(self,name,args,**kwargs):calls.append((name,args));return {'remote':True}
    monkeypatch.setattr(RemoteClient,'invoke',invoke)
    server=mcp_server.build_server(True)
    async def probe():
        tools=await server.list_tools()
        names={t.name for t in tools}
        assert len(tools)==16 and 'memory_save' not in names
        assert {'memory_pattern_preview','memory_pattern_status','memory_patterns','memory_pattern'} <= names
        assert not {'memory_pattern_policy','memory_pattern_backfill','memory_pattern_recover'} & names
        result=await server.call_tool('memory_domains',{})
        assert 'true' in str(result).lower()
    asyncio.run(probe())
    assert calls==[('memory_domains',{})]


def test_opencode_remote_idle_and_compaction_keep_durable_local_handoff(tmp_path,monkeypatch):
    from agentic_rag import config,db
    from agentic_rag.integrations.opencode import hooks
    from agentic_rag.hooks import common
    from agentic_rag.service.client import RemoteClient
    cfg=remote_config(tmp_path);monkeypatch.setattr(config,'load_config',lambda:cfg)
    monkeypatch.setattr(hooks,'TRANSCRIPT_DIR',tmp_path/'opencode')
    monkeypatch.setattr(common,'spawn_worker',lambda:None)
    monkeypatch.setattr(db,'connect',lambda *a,**k:pytest.fail('OpenCode client opened local DB'))
    payload={'session_id':'s','cwd':str(tmp_path),'messages':[{'id':'m1','role':'user','text':'Remember the pending deployment.'}],
        'boundary_id':'b1','trigger':'auto'}
    assert hooks.dispatch('idle',payload)['ok']
    assert hooks.dispatch('pre-compact',payload)['ok']
    assert hooks.dispatch('post-compact',{**payload,'summary':'Resume the pending deployment.'})['ok']
    with RemoteClient(cfg) as client:
        assert client.spool.latest_checkpoint('opencode:s')['handoff']=='Resume the pending deployment.'


def test_startup_exposes_retained_blocked_uploads_without_payloads(tmp_path,monkeypatch):
    from agentic_rag.service.client import RemoteClient
    from agentic_rag.service.local import context
    cfg=remote_config(tmp_path)
    with RemoteClient(cfg) as client:
        item=client.spool.enqueue('window','s',{'input_cursor':'','output_cursor':'c1','private':'SECRET SOURCE CONTENT'})
        client.spool.fail(item,'scope_denied',blocked=True)
    monkeypatch.setattr(RemoteClient,'context',lambda *a,**k:'Remote knowledge context')
    text=context(cfg,{'session_id':'s','cwd':str(tmp_path)})
    assert '1 pending' in text and '1 blocked' in text
    assert 'SECRET SOURCE CONTENT' not in text
