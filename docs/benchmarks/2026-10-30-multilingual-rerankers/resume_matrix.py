"""Resume the quota-interrupted matrix without repeating successful observations."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time

from run_matrix import digest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--previous', required=True, type=Path)
    p.add_argument('--models-root', required=True, type=Path)
    p.add_argument('--server-python', required=True)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    previous = json.loads((a.previous/'matrix-exit.json').read_text())
    old_seal = json.loads((a.previous/'matrix-seal.json').read_text())
    assert previous['exit'] == 1
    records = previous['completed']
    assert [(r['model'], r['round'], r['exit']) for r in records] == [
        ('minilm-l6', 0, 0), ('mmarco', 0, 0), ('jina-v2', 0, 0), ('jina-v3.5', 0, 1)]
    for name, sha in old_seal['frozen'].items():
        assert digest(HERE/'executed-sources/runs-d'/name) == sha
        if name != 'benchmark.py': assert digest(HERE/name) == sha
    assert json.loads((a.models_root/'models.json').read_text()) == old_seal['models']
    a.output.mkdir(parents=True, exist_ok=False)
    frozen = {f.name: digest(f) for f in HERE.glob('*.py')}
    frozen.update({name: digest(HERE/name) for name in ('corpus.json', 'PLAN.md')})
    seal = dict(old_seal, utc=datetime.now(timezone.utc).isoformat(), frozen=frozen,
        previous_run=str(a.previous), previous_matrix_sha256=digest(a.previous/'matrix-exit.json'),
        previous_frozen=old_seal['frozen'],
        note='Three successful R0 units reused byte-for-byte; only missing units execute. '
             'No corpus, model, scoring, timing envelope or model-server change. '
             'benchmark.py now retains attempted observations on a fatal native-drain failure.')
    (a.output/'matrix-seal.json').write_text(json.dumps(seal, indent=2)+'\n')
    results = []
    for record in records[:3]:
        name = record['model']+'-r0'
        unit_exit = json.loads((a.previous/name/'exit.json').read_text())
        assert unit_exit['exit'] == 0 and unit_exit['observations'] == 520
        assert unit_exit['child_stopped'] and unit_exit['temporary_model_copy_removed']
        assert not unit_exit['remaining_group_members']
        shutil.copytree(a.previous/name, a.output/name)
        shutil.copy2(a.previous/(name+'-console.log'), a.output/(name+'-console.log'))
        results.append(dict(record, reused_from=str(a.previous/name)))
    order = ['minilm-l6', 'mmarco', 'jina-v2', 'jina-v3.5']
    sequence = [(name, round) for round in range(3) for name in order[round:]+order[:round]]
    status = 1
    try:
        for name, round in sequence[3:]:
            assert all(digest(HERE/f) == sha for f, sha in frozen.items())
            unit = 'rag62-four-'+a.output.name+'-'+name.replace('.', '')+'-r'+str(round)
            dest = a.output/(name+'-r'+str(round))
            command = ['systemd-run', '--user', '--unit', unit, '--wait', '--pipe',
                '--working-directory', str(REPO), '-p', 'CPUQuota=400%', '-p', 'MemoryMax=8G',
                '-p', 'MemorySwapMax=0', '-p', 'AllowedCPUs=0-3',
                '--setenv=PYTHONPATH='+str(REPO), 'taskset', '-c', '0-3', str(REPO/'.venv/bin/python'),
                str(HERE/'benchmark.py'), '--name', name, '--round', str(round),
                '--models-root', str(a.models_root), '--server-python', a.server_python, '--output', str(dest)]
            before = time.perf_counter()
            print('START', name, 'round', round, datetime.now(timezone.utc).isoformat(), flush=True)
            with (a.output/(name+'-r'+str(round)+'-console.log')).open('x') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            properties = subprocess.run(['systemctl', '--user', 'show', unit,
                '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainStatus',
                '-p', 'CPUUsageNSec', '-p', 'MemoryPeak'], text=True, capture_output=True)
            with socket.socket() as probe: port_result = probe.connect_ex(('127.0.0.1', 8782))
            record = dict(model=name, round=round, unit=unit, command=command,
                exit=result.returncode or (1 if port_result == 0 else 0),
                wall_seconds=time.perf_counter()-before, systemd_properties=properties.stdout,
                post_exit_port_connect_errno=port_result, finished=datetime.now(timezone.utc).isoformat())
            results.append(record)
            (a.output/'matrix-progress.json').write_text(json.dumps(results, indent=2)+'\n')
            print('END', name, 'round', round, 'exit', record['exit'], 'wall', record['wall_seconds'], flush=True)
            if record['exit']: return 1
        assert all(digest(HERE/f) == sha for f, sha in frozen.items())
        status = 0
        print('Resumed matrix complete; actual exit0,12 accepted units including3 unchanged R0 units', flush=True)
        return 0
    finally:
        (a.output/'matrix-exit.json').write_text(json.dumps(dict(exit=status, completed=results), indent=2)+'\n')


if __name__ == '__main__': raise SystemExit(main())
