from pathlib import Path
from types import SimpleNamespace
import pytest
from agentic_rag.config import Config


def test_code_only_target_requires_exact_revision_before_git(tmp_path):
    from scripts.activate_failure_evaluation import guard
    with pytest.raises(ValueError,match='exact'):
        guard(tmp_path/'source',tmp_path/'candidate','abc123')


def test_code_only_backup_rejects_source018_before_database(tmp_path,monkeypatch):
    import json
    from scripts import activate_failure_evaluation as activation
    report=tmp_path/'report.json';report.write_text(json.dumps(dict(source_db_name='x',
        strict_restore_exit_zero=True,all_public_table_rows_match=True,application_table_privileges_match=True,
        consistent_exported_snapshot=True,owned_database_cleanup='verified',tables={'schema_migrations':{'rows':18}})))
    monkeypatch.setattr(activation.db,'connect',lambda *a,**k:pytest.fail('source018 backup reached database'))
    with pytest.raises(ValueError,match='019'):
        activation.backup_guard(Config(db_name='x'),tmp_path/'unused.dump',report)


def test_schema_time_drift_is_rejected_under_lock_before_git(tmp_path,monkeypatch):
    from scripts import activate_failure_evaluation as activation
    state=dict(dirty=False,checks=0,closed=False)
    def guard(*args):
        if state['dirty']:raise ValueError('checkout drift')
    def schema(*args):
        state['checks']+=1
        if state['checks']==2:state['dirty']=True
        return 19
    monkeypatch.setattr(activation,'guard',guard)
    monkeypatch.setattr(activation,'schema',schema)
    monkeypatch.setattr(activation,'backup_guard',lambda *args:None)
    monkeypatch.setattr(activation.worker,'acquire_lock',lambda path:SimpleNamespace(close=lambda:state.update(closed=True)))
    monkeypatch.setattr(activation.subprocess,'run',lambda *a,**k:pytest.fail('drift reached Git mutation'))
    with pytest.raises(ValueError,match='drift'):
        activation.activate(tmp_path/'source',tmp_path/'candidate','a'*40,cfg=Config(),dump=tmp_path/'d',report=tmp_path/'r')
    assert state['closed']
