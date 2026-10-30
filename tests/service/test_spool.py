"""Offline durability, bounded buffering and credential/session isolation."""
import pytest


def test_spool_survives_restart_ack_and_capacity_without_eviction(tmp_path):
    from agentic_rag.service.spool import Spool, SpoolFull
    path=tmp_path/'private'/'spool.sqlite'
    with Spool(path,'endpoint-credential-a',max_items=2,max_bytes=4096) as spool:
        one=spool.enqueue('window','session-a',{'input_cursor':'','output_cursor':'c1','text':'first'})
        assert spool.cursor('session-a')=='c1'
        assert spool.enqueue('window','session-a',{'input_cursor':'','output_cursor':'c1','text':'first'})==one
        two=spool.enqueue('window','session-b',{'input_cursor':'','output_cursor':'b1','text':'second'})
        with pytest.raises(SpoolFull):spool.enqueue('window','session-c',{'input_cursor':'','output_cursor':'c1','text':'third'})
        assert len(spool.pending())==2
    assert path.stat().st_mode & 0o077 == 0
    with Spool(path,'endpoint-credential-a',max_items=2,max_bytes=4096) as spool:
        assert [r['id'] for r in spool.pending()]==[one,two]
        spool.ack(one,{'receipt':'durable-1'})
        assert spool.cursor('session-a')=='c1'
        assert [r['id'] for r in spool.pending()]==[two]
        spool.fail(two,'invalid_credentials',blocked=True)
    with Spool(path,'endpoint-credential-b') as other:
        assert other.pending()==[] and other.cursor('session-a')==''
    with Spool(path,'endpoint-credential-a') as spool:
        assert spool.pending()[0]['state']=='blocked'
        assert spool.due()==[]
        spool.retry_blocked()
        assert len(spool.due())==1


def test_spool_conflicting_cursors_and_unsafe_file_are_rejected(tmp_path):
    from agentic_rag.service.spool import Spool
    path=tmp_path/'private'/'spool.sqlite'
    with Spool(path,'one') as spool:
        spool.enqueue('window','s',{'input_cursor':'','output_cursor':'c1','text':'original'})
        with pytest.raises(ValueError,match='cursor'):
            spool.enqueue('window','s',{'input_cursor':'','output_cursor':'c1','text':'different'})
        with pytest.raises(ValueError,match='cursor'):
            spool.enqueue('window','s',{'input_cursor':'unknown','output_cursor':'c2','text':'gap'})
        spool.cache('s','/project/a','retained context')
        assert spool.cached('s','/project/a')=='retained context'
        assert spool.cached('s','/project/b') is None
    path.chmod(0o644)
    with pytest.raises(ValueError,match='permissions'):Spool(path,'one')
