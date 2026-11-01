"""PB-067-OPS rehearsal: the playbook's commands run through the real CLI, the
operator commands and REST on an owned, automatically dropped store that the
actual 0.6.19 code (git archive of main 01bc13b) populated at schema031.

Part A upgrades through `rag service upgrade`; B1 runs the exact gate snippets
against a deliberately stale process; B2-B5 validate, inspect, dry-run and
activate a policy through `rag extraction`; C1 rehearses an invalid file on the
hook path and the central `/v1/windows` path and recovers; C2/C3 inspect queued
work and retry under the admitted policy after the file changed; part D rolls the
policy back prospectively, takes a post-upgrade verified backup and restores it
into an empty owned database with the PB-063 commands.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import time
import uuid

from starlette.testclient import TestClient

from agentic_rag import cli, db, jobs, llm, mining, store, worker
from agentic_rag.benchmark import extraction_policy as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import load_config
from test_maintenance_restore import owned_source
from .test_api import app_fixture, headers, KEYS
from .test_extraction_policy_upgrade import POPULATE, old_tree, run_old, transcripts

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / 'docs/playbooks/system/rag-067-extraction-policy.md'
PB063 = ROOT / 'docs/playbooks/system/rag-063-source-evidence-upgrade.md'
COMMANDS = [
    'rag service --config CONFIG inventory --source-version 0.6.19 --identities --output DIR/inventory.json',
    'rag service --config CONFIG preflight --source-version 0.6.19 --mode local',
    'rag service --config CONFIG upgrade --source-version 0.6.19 --dump DIR/policy032.dump --apply --writers-stopped',
    'rag service --config CONFIG status',
    'rag extraction validate --file POLICY.new',
    'rag extraction inspect --file POLICY.new --project PROJECT',
    'rag extraction dry-run --file POLICY.new --project PROJECT --sample SAMPLE',
    'mv POLICY.new POLICY', 'mv POLICY.prev POLICY', 'rag extraction inspect --queued',
    'rag service job-retry RECEIPT',
    'rag service --config CONFIG verified-backup --source-version 0.6.20 --output DIR/current.dump',
    "<<'PYFRESH'", "<<'PYGATE'", '-- PB067-CLIENTS', '-- PB067-INTEGRITY', '[mining] policy_file',
]


def snippet(name, text=None):
    body = re.split(rf'\n[ \t]*{name}\n', (text or PLAYBOOK.read_text()).split(f"<<'{name}'\n")[-1], maxsplit=1)[0]
    return textwrap.dedent(body)


def sql_block(marker):
    block = re.split(rf'\n[ \t]*{re.escape(marker)}\n', PLAYBOOK.read_text(), maxsplit=1)[1].split('```', 1)[0]
    return textwrap.dedent(block)


def integrity(cfg):
    with db.connect(cfg, role='owner') as conn:
        return dict(conn.execute(sql_block('-- PB067-INTEGRITY')).fetchone())


def gate_rehearsal(tmp_path):
    """B1: a process older than the installation blocks the gate; after its restart it passes."""
    expected = next(line.split('"')[1] for line in (ROOT / 'pyproject.toml').read_text().splitlines()
                    if line.startswith('version = '))
    fresh = subprocess.run([sys.executable, '-I', '-c', snippet('PYFRESH')], text=True, capture_output=True, timeout=60)
    assert fresh.returncode == 0, fresh.stderr
    version, metadata = fresh.stdout.split()
    assert version == expected == '0.6.20' and Path(metadata).name == 'METADATA'
    token = 'pb067-gate-' + uuid.uuid4().hex
    reader = [sys.executable, '-c', f'import time; time.sleep(120)  # {token}']
    stale = subprocess.Popen(reader)
    try:
        time.sleep(1.2)
        marker = tmp_path / 'installed-METADATA'
        marker.write_text('installed after the stale miner started')
        blocked = subprocess.run([sys.executable, '-c', snippet('PYGATE'), str(marker), token],
                                 text=True, capture_output=True, timeout=60)
        assert blocked.returncode == 1 and blocked.stdout.split()[0] == str(stale.pid), blocked
    finally:
        stale.kill()
        stale.wait()
    time.sleep(1.2)
    restarted = subprocess.Popen(reader)
    try:
        passed = subprocess.run([sys.executable, '-c', snippet('PYGATE'), str(marker), token],
                                text=True, capture_output=True, timeout=60)
        assert passed.returncode == 0 and passed.stdout.strip() == 'no_stale_processes', passed
    finally:
        restarted.kill()
        restarted.wait()


def test_pb067_upgrade_activate_recover_retry_rollback_and_restore(tmp_path, monkeypatch, capsys):
    text = PLAYBOOK.read_text()
    assert [c for c in COMMANDS if c not in text] == []
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)

    def forbidden(*args, **kwargs):
        raise AssertionError('no provider call outside the explicit rehearsal steps')
    monkeypatch.setattr(llm, 'run_structured', forbidden)
    monkeypatch.setattr(mining, 'run_structured', forbidden)
    proofs = tmp_path / 'proofs'
    proofs.mkdir()
    old = old_tree(tmp_path)
    pending, accepted, new_transcript = transcripts(tmp_path)
    case = fx.case('R1')
    with owned_source(tmp_path, 31) as source:
        run_old(old, source, tmp_path, POPULATE, pending, accepted, json.dumps(case['provider'][0]))
        policy = tmp_path / 'policy' / 'extraction.toml'
        policy.parent.mkdir()
        base = (f'[db]\nname = "{source.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n'
                f'[rerank]\nurl = "http://127.0.0.1:1"\n\n[backup]\nlocal_dir = "{tmp_path / "dumps"}"\n')
        config = tmp_path / 'source.toml'
        config.write_text(base)
        active = tmp_path / 'active.toml'
        active.write_text(base + f'\n[mining]\npolicy_file = "{policy}"\ndebounce_seconds = 0\n')

        def rag(*argv, path=config):
            monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(path))
            code = cli.main(list(argv))
            out = capsys.readouterr()
            return code, out.out, out.err

        def ok(*argv, path=config):
            code, out, err = rag(*argv, path=path)
            assert code == 0, (argv, err)
            return out

        def operator(*argv):
            return json.loads(ok('service', '--config', str(config), *argv).strip().splitlines()[-1])

        def extraction(*argv, path=active, expect=0):
            code, out, err = rag('extraction', *argv, path=path)
            assert code == expect, (argv, err)
            return json.loads(out) if out.strip() else err

        # Part A
        assert operator('inventory', '--source-version', '0.6.19', '--identities',
                        '--output', str(proofs / 'inventory.json'))['supported'] is True
        assert operator('preflight', '--source-version', '0.6.19', '--mode', 'local')['ready'] is True
        a4 = operator('upgrade', '--source-version', '0.6.19', '--dump', str(proofs / 'policy032.dump'),
                      '--apply', '--writers-stopped')
        assert a4['migrations_applied'] == ['032_extraction_policy.sql']
        assert a4['restore_verified'] and a4['original_rows_unchanged']
        assert (proofs / 'policy032.dump.manifest.json').exists()
        a5 = operator('upgrade', '--source-version', '0.6.19', '--dump', str(proofs / 'retry.dump'),
                      '--apply', '--writers-stopped')
        assert a5['migrations_applied'] == [] and a5['restore_verified']
        operator('status')
        assert rag('service', '--config', str(config), 'upgrade', '--source-version', '0.6.21', '--dump',
                   str(proofs / 'refused.dump'))[0] == 1
        zero = {'bindings': 0, 'malformed_digests': 0, 'bindings_minus_audit': 0, 'batch_policy_mismatch': 0}
        assert integrity(load_config(config)) == zero

        # B1: gate snippets and direct clients.
        gate_rehearsal(tmp_path)
        cfg = load_config(active)
        with db.connect(cfg) as conn:
            clients = conn.execute(sql_block('-- PB067-CLIENTS')).fetchall()
        assert all(set(row) >= {'pid', 'client_addr', 'backend_start'} for row in clients)

        # B2-B5: validate, inspect, dry-run, activate atomically.
        draft = policy.with_name('extraction.toml.new')
        shutil.copyfile(fx.policy_path('policy-a.toml'), draft)
        b2 = extraction('validate', '--file', str(draft))
        assert b2['valid'] and b2['identity'].startswith('xf1:')
        b3 = extraction('inspect', '--file', str(draft), '--project', A_PROJECT)
        assert b3['domains']['programming']['scopes'] == ['builtin', 'global', 'domain:programming']
        sample = tmp_path / 'sample.json'
        sample.write_text(json.dumps({'events': case['events']}))
        b4 = extraction('dry-run', '--file', str(draft), '--project', A_PROJECT, '--sample', str(sample))
        assert b4['provider_calls'] == 0 and b4['writes'] == 0 and b4['would_call_provider']
        assert subprocess.run(['mv', str(draft), str(policy)]).returncode == 0
        b5 = extraction('validate')
        assert b5['configured'] and b5['identity'] == b2['identity']
        shutil.copyfile(policy, policy.with_name('extraction.toml.prev'))

        # C1: invalid file on the hook path and the central path, then recovery.
        shutil.copyfile(fx.policy_path('policy-invalid.toml'), policy)
        assert extraction('validate', expect=1)['valid'] is False
        with db.connect(cfg) as conn:
            before = conn.execute('SELECT count(*) n FROM mining_queue').fetchone()['n']
            try:
                jobs.enqueue_mine(conn, cfg, session_id='pb067-hook', transcript_path=new_transcript, project=A_PROJECT)
                raise AssertionError('invalid file must refuse admission')
            except ValueError as error:
                assert 'invalid extraction policy: reserved_setting at rules[1].write_domains' in str(error)
            assert conn.execute('SELECT count(*) n FROM mining_queue').fetchone()['n'] == before
        service_cfg = replace(cfg, service_auth_file=None)
        (tmp_path / "central").mkdir()
        app, central_cfg = app_fixture(tmp_path / "central", service_cfg)
        window = {'version': 1, 'session_id': 'pb067-window', 'input_cursor': '', 'output_cursor': 'c1',
                  'project': '/projects/a', 'window': {'text': case['events'][0]['text'],
                  'events': [case['events'][0]], 'warnings': [], 'synthetic': False, 'has_more': False}}
        with TestClient(app, base_url='https://testserver') as client:
            refused = client.post('/v1/windows', headers=headers(KEYS[0]), json=window)
            assert refused.status_code == 503 and refused.json() == {'error': 'extraction_policy_invalid'}
            assert subprocess.run(['mv', str(policy.with_name('extraction.toml.prev')), str(policy)]).returncode == 0
            assert extraction('validate')['identity'] == b2['identity']
            admitted = client.post('/v1/windows', headers=headers(KEYS[0]), json=window)
            assert admitted.status_code == 202, admitted.text
            receipt = admitted.json()['receipt']
        with db.connect(cfg) as conn:
            assert jobs.enqueue_mine(conn, cfg, session_id='pb067-hook', transcript_path=new_transcript, project=A_PROJECT)

        # C2/C3: queued identities, provider outage, file replaced, retry under the admitted policy.
        queued = extraction('inspect', '--queued')
        hook_job = next(j for j in queued['jobs'] if j['admitted'].startswith('xb1:'))
        assert any(j['admitted'] == 'legacy-builtin' for j in queued['jobs'])
        assert [w['admitted'] for w in queued['windows'] if w['receipt'] == receipt][0].startswith('xb1:')
        outputs = ['PROVIDER_UNAVAILABLE', case['provider'][0]]
        mock = fx.MockProvider(outputs, case['events'])
        monkeypatch.setattr(mining, 'run_structured', mock)
        with db.connect(cfg) as conn:
            job = dict(conn.execute('SELECT id,kind,session_id,transcript_path,payload,last_uuid,attempts FROM mining_queue'
                                    ' WHERE id=%s', (int(hook_job['job']),)).fetchone())
            conn.commit()
            try:
                worker.process_job(conn, cfg, {**job, 'attempts': 1})
                raise AssertionError('the synthetic outage must fail the attempt')
            except llm.LLMUnavailableError:
                conn.rollback()
        shutil.copyfile(fx.policy_path('policy-b.toml'), policy)  # operator changes the file meanwhile
        assert extraction('inspect', '--queued')['jobs'][[j['job'] for j in queued['jobs']].index(hook_job['job'])]['bound'] == hook_job['admitted']
        with db.connect(cfg) as conn:
            result = worker.process_job(conn, cfg, {**job, 'attempts': 2})
        assert result.saved == 1 and mock.calls == 2
        with db.connect(cfg) as conn:
            batch = conn.execute("SELECT extraction->'_policy' p FROM mining_batches WHERE session_id='pb067-hook'").fetchone()['p']
        assert batch['digest'] == hook_job['admitted'] and batch['rejected'] == {'lessons': {'category_disabled': 1},
                                                                                  'signals': {'category_disabled': 1}}
        assert integrity(cfg)['batch_policy_mismatch'] == 0

        # D: prospective rollback, then post-upgrade backup and independent restore.
        shutil.copyfile(fx.policy_path('policy-a.toml'), policy)
        with db.connect(cfg) as conn:
            assert jobs.enqueue_mine(conn, cfg, session_id='pb067-after-rollback', transcript_path=new_transcript, project=A_PROJECT)
            rolled = conn.execute("SELECT payload->'extraction_policy'->>'digest' d FROM mining_queue"
                                  " WHERE session_id='pb067-after-rollback'").fetchone()['d']
            unchanged = conn.execute("SELECT extraction->'_policy'->>'digest' d FROM mining_batches"
                                     " WHERE session_id='pb067-hook'").fetchone()['d']
        assert rolled == hook_job['admitted'] and unchanged == hook_job['admitted']
        final = integrity(cfg)
        assert final['bindings'] >= 1 and {k: v for k, v in final.items() if k != 'bindings'} == dict.fromkeys(
            ['malformed_digests', 'bindings_minus_audit', 'batch_policy_mismatch'], 0)
        current = operator('verified-backup', '--source-version', '0.6.20', '--output', str(proofs / 'current.dump'))
        assert current['restore_verified']
        with isolated_database(cfg, initialize=False) as target:
            from agentic_rag import backup
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(proofs / 'current.dump')])
            assert integrity(target) == final
            with db.connect(target) as conn:
                assert conn.execute("SELECT count(*) n FROM pg_trigger WHERE tgname='extraction_policy_binding_immutable'").fetchone()['n'] == 1
        # Interrupted-upgrade decision: both markers present means A4 committed.
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT to_regclass('public.extraction_policy_bindings') IS NOT NULL AS t,"
                                " EXISTS (SELECT 1 FROM schema_migrations WHERE filename='032_extraction_policy.sql') AS m"
                                ).fetchone() == {'t': True, 'm': True}
    print('PB067_REHEARSAL', json.dumps({'a4': a4['migrations_applied'], 'identity': b2['identity'],
                                          'retry_digest': batch['digest'], 'provider_calls': mock.calls,
                                          'integrity': final}, sort_keys=True))


A_PROJECT = '/synthetic/team-a'
