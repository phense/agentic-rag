import sys
from types import SimpleNamespace
from agentic_rag import cli
from agentic_rag.config import Config


def test_new_optimization_cli_keeps_bounded_explicit_arguments(tmp_path,monkeypatch,capsys):
    calls=[]
    def run(cfg,**kwargs):calls.append(kwargs);return dict(summary={},failed_queries=0)
    monkeypatch.setattr(cli,'load_config',lambda:Config())
    monkeypatch.setitem(sys.modules,'agentic_rag.benchmark.optimization',SimpleNamespace(run=run))
    assert cli._main(['benchmark','optimize','--output',str(tmp_path/'new'),'--repeats','2'])==0
    assert calls[0]['repeats']==2 and calls[0]['context_chars']==4000


def test_correction_cli_prints_only_returned_aggregate_counts(tmp_path,monkeypatch,capsys):
    calls=[]
    def export(cfg,**kwargs):calls.append(kwargs);return dict(cases=0)
    monkeypatch.setattr(cli,'load_config',lambda:Config())
    monkeypatch.setitem(sys.modules,'agentic_rag.benchmark.corrections',SimpleNamespace(export_confirmed_corrections=export))
    assert cli._main(['benchmark','export-corrections','--domain','general','--project','/synthetic/a','--output',str(tmp_path/'private.json')])==0
    assert calls[0]['project']=='/synthetic/a' and calls[0]['limit']==32
    assert 'cases' in capsys.readouterr().out
