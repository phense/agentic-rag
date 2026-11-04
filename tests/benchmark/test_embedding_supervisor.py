"""Real finite child processes; replace only machine resource telemetry."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]


def supervisor(tmp_path,monkeypatch,*,failure=False,available=16*1024**3,only=None,mutate=False):
    telemetry=SimpleNamespace(virtual_memory=lambda:SimpleNamespace(available=available),
        Process=lambda pid:SimpleNamespace(children=lambda **kw:[],
            memory_info=lambda:SimpleNamespace(rss=0),cpu_times=lambda:SimpleNamespace(user=0,system=0)),
        NoSuchProcess=ProcessLookupError)
    monkeypatch.setitem(sys.modules,'psutil',telemetry)
    spec=importlib.util.spec_from_file_location('embedding_supervisor',ROOT/'scripts/run_embedding_benchmark.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    fixtures=tmp_path/'fixtures';fixtures.mkdir()
    for name in ('corpus.json','protocol.json'):(fixtures/name).write_text('{}')
    # Only the slow inference boundary is replaced; process and filesystem are real.
    interpreter=tmp_path/'worker'
    interpreter.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\n'
        +('Path('+repr(str(fixtures/'corpus.json'))+').write_text("changed")\n' if mutate else '')
        +('sys.exit(3 if "nano" in sys.argv else 0)\n' if failure else 'sys.exit(0)\n'))
    interpreter.chmod(0o700)
    out=tmp_path/'out'
    args=['supervisor','--mode','primary','--python',str(interpreter),'--models',str(tmp_path),
          '--fixtures',str(fixtures),'--output',str(out)]
    if only:args+=['--only',only]
    monkeypatch.setattr(sys,'argv',args)
    return m,out


def test_failed_candidate_is_nonzero_and_remaining_repetitions_are_explicit(tmp_path,monkeypatch):
    # The old supervisor returned success and dropped nano-r1/r2 from its denominator.
    m,out=supervisor(tmp_path,monkeypatch,failure=True)
    assert m.main()==1
    terminal=json.loads((out/'terminal.json').read_text())
    rows={r['label']:r for r in terminal['planned_runs']}
    assert len(rows)==9
    assert rows['nano-r0']['status']=='failed'
    assert rows['nano-r1']['status']==rows['nano-r2']['status']=='unattempted'
    assert rows['nano-r1']['reason']=='earlier_candidate_failure'
    assert all(rows[f'{name}-r{i}']['status']=='completed' for name in ('bge','small') for i in range(3))
    assert terminal['success'] is False and terminal['inputs_unchanged'] is True
    assert json.loads((out/'running.json').read_text())['status']=='finished'


def test_floor_abort_retains_reason_and_all_unattempted_runs(tmp_path,monkeypatch):
    m,out=supervisor(tmp_path,monkeypatch,available=1)
    assert m.main()==1
    terminal=json.loads((out/'terminal.json').read_text())
    assert terminal['failure']['message']=='available memory floor'
    assert len(terminal['planned_runs'])==9
    assert {r['status'] for r in terminal['planned_runs']}=={'unattempted'}
    assert terminal['attempts']==[]


def test_explicit_small_only_run_keeps_three_repeats_and_success(tmp_path,monkeypatch):
    m,out=supervisor(tmp_path,monkeypatch,only='small')
    assert m.main()==0
    terminal=json.loads((out/'terminal.json').read_text())
    assert terminal['success'] is True
    assert [r['label'] for r in terminal['planned_runs']]==['small-r0','small-r1','small-r2']
    assert {r['status'] for r in terminal['planned_runs']}=={'completed'}


def test_changed_inputs_cannot_be_success_even_when_workers_exit_zero(tmp_path,monkeypatch):
    m,out=supervisor(tmp_path,monkeypatch,mutate=True)
    assert m.main()==1
    terminal=json.loads((out/'terminal.json').read_text())
    assert terminal['inputs_unchanged'] is False
    assert terminal['success'] is False
