"""Operational limits cover legacy work and graceful process shutdown too."""
from dataclasses import replace
import threading

import pytest
from agentic_rag import backup, db, worker
from agentic_rag.config import Config
from .test_scope import service_store


def test_stop_between_jobs_leaves_next_job_unclaimed(service_store,monkeypatch):
    cfg,_=service_store; stop=threading.Event();jobs=iter([
        {'id':1,'kind':'backup','payload':{},'attempts':1},
        {'id':2,'kind':'backup','payload':{},'attempts':1}]);seen=[]
    monkeypatch.setattr(worker,'claim_next',lambda conn:next(jobs,None))
    monkeypatch.setattr(worker,'process_job',lambda *a,**k:(seen.append(a[2]['id']),stop.set())[0])
    monkeypatch.setattr(worker,'_complete',lambda *a:None)
    with db.connect(cfg) as conn:
        assert worker.drain(conn,cfg,stop=stop)['done']==1
    assert seen==[1]
    assert next(jobs)['id']==2


def test_legacy_central_job_respects_storage_before_model_call(service_store,monkeypatch):
    from agentic_rag.service.engine import ResourcePressure
    cfg,docs=service_store;cfg=replace(cfg,service_mode='server',service_max_database_bytes=1)
    monkeypatch.setattr(worker.store,'reembed_document',lambda *a,**k:pytest.fail('provider reached under storage pressure'))
    with db.connect(cfg) as conn:
        with pytest.raises(ResourcePressure,match='database_budget_exceeded'):
            worker.process_job(conn,cfg,{'kind':'embed','payload':{'document_id':docs['allowed']}})


def test_cli_worker_handles_sigterm_and_restores_handlers(monkeypatch):
    import signal
    from agentic_rag.service import runner
    original=signal.getsignal(signal.SIGTERM)
    def run(cfg,**kwargs):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        assert kwargs['stop'].is_set()
        return 0
    monkeypatch.setattr(runner,'run',run)
    assert runner.run_with_signals(Config())==0
    assert signal.getsignal(signal.SIGTERM)==original


def test_backup_uses_configured_host_and_does_not_overwrite(tmp_path,monkeypatch):
    commands=[]
    monkeypatch.setattr(backup,'_run_pg',lambda command:commands.append(command))
    cfg=Config(db_name='owned_example',db_host='127.0.0.1',backup_local_dir=tmp_path)
    result=backup.run_backup(cfg)
    assert 'host=127.0.0.1' in commands[0][commands[0].index('-d')+1]
    with pytest.raises(FileExistsError):backup.run_backup(cfg)
    assert result.local_path.stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('value',[0,-1,True,10000])
def test_backup_retention_must_be_finite_and_keep_last_verified_copy(value):
    with pytest.raises(ValueError,match='backup_keep_local'):Config(backup_keep_local=value)


def test_backup_under_disk_pressure_preserves_old_copy(service_store,tmp_path,monkeypatch):
    from collections import namedtuple
    from agentic_rag.service.engine import ResourcePressure
    cfg,_=service_store;cfg=replace(cfg,service_mode='server',backup_local_dir=tmp_path)
    old=tmp_path/'agentic_rag-20260101-000000.dump';old.write_bytes(b'prior backup')
    monkeypatch.setattr(backup.shutil,'disk_usage',lambda p:namedtuple('Usage','total used free')(100,99,1))
    monkeypatch.setattr(backup,'_run_pg',lambda *a:pytest.fail('dump started without space'))
    with pytest.raises(ResourcePressure,match='backup_storage_low'):backup.run_backup(cfg)
    assert list(tmp_path.iterdir())==[old]
