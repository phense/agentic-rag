"""Regressions for large native captures and release only after durable window ACK."""
import hashlib
import json
from dataclasses import replace

import pytest

from agentic_rag.config import Config
from agentic_rag.service.spool import Spool, SpoolFull
from agentic_rag.service.client import RemoteClient
from agentic_rag.service.local import capture_transcript, stage_sources


def cfg_for(tmp_path):
    key=tmp_path/'key';key.write_text('isolated-test-key');key.chmod(0o600)
    return replace(Config(),service_mode='client',service_url='https://offline.invalid',
                   service_token_file=key,service_spool_dir=tmp_path/'private')


@pytest.mark.parametrize('source_mib',[17,94])
def test_large_capture_is_independent_of_unacknowledged_outbox_budget(tmp_path,source_mib):
    # Mutation: use the 16 MiB outbox ceiling for the entire source again.
    cfg=cfg_for(tmp_path);source=tmp_path/'large.jsonl'
    raw=(json.dumps({'uuid':'one','message':{'role':'user','content':'Retain this literal fact.'}})+'\n').encode()
    raw+=(json.dumps({'type':'tool-result','padding':'x'*(source_mib*1024*1024)})+'\n').encode()
    source.write_bytes(raw)
    capture_transcript(cfg,{'session_id':'large','cwd':'/project','transcript_path':str(source)})
    source.unlink()
    with RemoteClient(cfg) as client:
        assert client.spool.status()['source_bytes']==len(raw)
        assert stage_sources(client)==1
        pending=client.spool.pending();assert len(pending)==1
        assert json.loads(pending[0]['payload'])['window']['text']=='[user] Retain this literal fact.'
        assert client.spool.status()['source_bytes']==len(raw)  # staged is NOT durable ACK
        client.spool.ack(pending[0]['id'],{'receipt':'durable','kind':'window'})
        assert client.spool.status()['source_bytes']==0
        assert stage_sources(client)==0


def test_only_final_durable_ack_releases_snapshot_and_survives_restart(tmp_path):
    # Mutation: release on staging, on an intermediate ACK, or forget ACK across restart.
    path=tmp_path/'private'/'spool.sqlite';raw=b'a whole original snapshot'
    with Spool(path,'owner') as s:
        s.capture_source('s','/project',raw)
        one=s.enqueue('window','s',{'input_cursor':'','output_cursor':'first'})
        two=s.enqueue('window','s',{'input_cursor':'first','output_cursor':'last'})
        s.mark_source_complete('s',hashlib.sha256(raw).hexdigest(),'last')
        s.ack(one,{'receipt':'one'})
        assert s.status()['source_bytes']==len(raw)
        s.fail(two,'network_unavailable');assert len(s.pending())==1
    with Spool(path,'owner') as s:
        assert s.status()['source_bytes']==len(raw)
        s.ack(two,{'receipt':'two'})
        assert s.status()['source_bytes']==0
        assert s.cursor('s')=='last'
        s.capture_source('s','/project',raw)
        assert s.sources()==[]  # unchanged released input must not be retained again
        with pytest.raises(ValueError,match='changed'):s.capture_source('s','/project',b'changed prefix')
        with pytest.raises(ValueError,match='changed'):s.capture_source('s','/other',raw)
        s.capture_source('s','/project',raw+b' appended')
        assert s.sources()[0]['raw']==raw+b' appended'


def test_late_ack_never_releases_newer_appended_capture(tmp_path):
    # Mutation: release using a stale end marker after a concurrent source append.
    with Spool(tmp_path/'private'/'spool.sqlite','owner') as s:
        first=b'original';s.capture_source('s','/p',first)
        one=s.enqueue('window','s',{'input_cursor':'','output_cursor':'first'})
        s.mark_source_complete('s',hashlib.sha256(first).hexdigest(),'first')
        s.capture_source('s','/p',first+b' later')
        s.ack(one,{'receipt':'old'})
        assert s.status()['source_bytes']==len(first+b' later')
        s.mark_source_complete('s',hashlib.sha256(first).hexdigest(),'first')
        assert s.status()['source_bytes']==len(first+b' later')


@pytest.mark.parametrize('tail',[b'{"uuid":',b'not-json\n'])
def test_incomplete_or_malformed_tail_is_retained_after_preceding_ack(tmp_path,tail):
    # Mutation: mark a parsed prefix complete despite warnings about retained input.
    cfg=cfg_for(tmp_path);source=tmp_path/'input.jsonl'
    raw=(json.dumps({'uuid':'first','message':{'role':'user','content':'Known first fact.'}})+'\n').encode()+tail
    source.write_bytes(raw)
    capture_transcript(cfg,{'session_id':'s','cwd':'/p','transcript_path':str(source)})
    with RemoteClient(cfg) as c:
        stage_sources(c)
        for row in c.spool.pending():c.spool.ack(row['id'],{'receipt':'first'})
        assert c.spool.status()['source_bytes']==len(raw)


def test_source_budget_remains_bounded_without_evicting_other_partitions(tmp_path):
    # Mutation: silently evict a source or charge source bytes to the outbox ceiling.
    path=tmp_path/'private'/'spool.sqlite'
    with Spool(path,'a',max_bytes=1024,max_source_bytes=4096) as a:
        a.capture_source('s','/p',b'x'*3000)
        pending=a.enqueue('window','s',{'input_cursor':'','output_cursor':'c'})
        with Spool(path,'b',max_bytes=1024,max_source_bytes=4096) as b:
            with pytest.raises(SpoolFull):b.capture_source('s','/p',b'y'*2000)
            assert b.pending()==[] and b.sources()==[]
        assert a.sources()[0]['raw']==b'x'*3000
        assert a.pending()[0]['id']==pending


def test_release_reclaims_large_sqlite_file_without_losing_pending_input(tmp_path):
    # Mutation: clear quota only but leave the large raw BLOB permanently on disk.
    path=tmp_path/'private'/'spool.sqlite';raw=b'x'*(4*1024*1024)
    with Spool(path,'owner') as s:
        s.capture_source('s','/p',raw)
        item=s.enqueue('window','s',{'input_cursor':'','output_cursor':'last'})
        other=s.enqueue('window','other',{'input_cursor':'','output_cursor':'other-last','text':'must survive'})
        before=path.stat().st_size
        s.mark_source_complete('s',hashlib.sha256(raw).hexdigest(),'last')
        s.ack(item,{'receipt':'durable'})
        assert s.status()['source_bytes']==0 and s.pending()[0]['id']==other
        assert path.stat().st_size < before//2


def test_lost_http_ack_retains_raw_until_same_window_is_acknowledged(tmp_path):
    # Mutation: release merely because HTTP was sent or an ACK was lost.
    import httpx
    from agentic_rag.service.client import RemoteError
    cfg=cfg_for(tmp_path);source=tmp_path/'input.jsonl'
    raw=(json.dumps({'uuid':'one','message':{'role':'user','content':'A fact retained across a lost ACK.'}})+'\n').encode()
    source.write_bytes(raw)
    capture_transcript(cfg,{'session_id':'s','cwd':'/p','transcript_path':str(source)})
    seen=[]
    def send(request):
        if request.url.path=='/v1/capabilities':return httpx.Response(200,json={'protocol':1})
        assert request.url.path=='/v1/windows'
        seen.append(json.loads(request.content))
        if len(seen)==1:raise httpx.ReadTimeout('response lost after durable commit')
        return httpx.Response(202,json={'durable':True,'receipt':'00000000-0000-0000-0000-000000000001','state':'queued'})
    with httpx.Client(transport=httpx.MockTransport(send)) as transport:
        with RemoteClient(cfg,sender=transport) as c:
            assert stage_sources(c)==1
            c.flush();assert c.spool.status()['source_bytes']==len(raw) and len(c.spool.pending())==1
        with RemoteClient(cfg,sender=transport) as c:
            c.spool.retry_blocked();c.flush()
            assert c.spool.status()['source_bytes']==0 and c.spool.pending()==[]
    assert len(seen)==2 and seen[0]==seen[1]


def test_legacy_spool_upgrade_retains_unknown_ack_and_releases_new_ack(tmp_path):
    # Mutation: treat an old staging cursor as an independently verified ACK.
    import sqlite3
    path=tmp_path/'private'/'spool.sqlite'
    with Spool(path,'a') as s:
        s.capture_source('s','/p',b'legacy original')
        row=s.enqueue('window','s',{'input_cursor':'','output_cursor':'c1'})
    # Precisely the old schema: sources/outbox/cursors, no source_progress table.
    with sqlite3.connect(path) as old:old.execute('DROP TABLE source_progress')
    with Spool(path,'a') as s:
        assert s.sources()[0]['raw']==b'legacy original' and s.pending()[0]['id']==row
        s.mark_source_complete('s',hashlib.sha256(b'legacy original').hexdigest(),'c1')
        assert s.status()['source_bytes']==15
        s.ack(row,{'receipt':'durable-after-upgrade'})
        assert s.status()['source_bytes']==0
    with Spool(path,'a') as s:
        s.capture_source('unknown','/p',b'old fully staged')
        s.conn.execute("INSERT INTO cursors VALUES('a','unknown','old-cursor')");s.conn.commit()
        s.conn.execute("DELETE FROM source_progress WHERE session='unknown'");s.conn.commit()
        s.mark_source_complete('unknown',hashlib.sha256(b'old fully staged').hexdigest(),'old-cursor')
        assert s.status()['source_bytes']==16  # no ACK proof, so preserve original


def test_origin_export_refuses_released_snapshot_instead_of_exporting_empty_original(tmp_path):
    from agentic_rag.source_origin import export_spool
    path=tmp_path/'private'/'spool.sqlite';raw=b'original retained until acknowledged'
    with Spool(path,'a') as spool:
        spool.capture_source('s','/p',raw)
        row=spool.enqueue('window','s',{'input_cursor':'','output_cursor':'last'})
        spool.mark_source_complete('s',hashlib.sha256(raw).hexdigest(),'last')
        spool.ack(row,{'receipt':'durable'})
    output=tmp_path/'export.jsonl'
    with pytest.raises(ValueError,match='missing_or_oversized_recording'):
        export_spool(path,'a','s',output)
    assert not output.exists()


@pytest.mark.parametrize('value',[True,0,1023,1073741825,1.5,'268435456'])
def test_source_budget_configuration_rejects_invalid_limits(value):
    with pytest.raises(ValueError,match='spool_source_max_bytes'):
        replace(Config(),service_spool_source_max_bytes=value)


def test_source_budget_toml_and_repeat_capture_do_not_reset_pending_eof(tmp_path):
    from agentic_rag.config import load_config
    conf=tmp_path/'config.toml';conf.write_text('[service]\nspool_source_max_bytes =67108864\n')
    assert load_config(conf).service_spool_source_max_bytes==67108864
    with Spool(tmp_path/'private'/'spool.sqlite','a') as s:
        raw=b'original';s.capture_source('s','/p',raw)
        row=s.enqueue('window','s',{'input_cursor':'','output_cursor':'last'})
        s.mark_source_complete('s',hashlib.sha256(raw).hexdigest(),'last')
        s.capture_source('s','/p',raw)
        s.ack(row,{'receipt':'durable'})
        assert s.status()['source_bytes']==0
