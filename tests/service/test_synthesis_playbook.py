"""PB-065-OPS rehearsal: the playbook's pattern commands, run through the real CLI
and the central worker loop on an owned, automatically dropped schema030 store.

The provider boundary is the frozen scripted fixture; the outage is a synthetic
LLMUnavailableError. Parts B, C and the post-upgrade restore of part D are
covered here, C4 both through the local owner CLI and through a writer's central
client CLI against the REST API and the central worker. The B0 reader gate is
rehearsed with its exact snippets on a deliberately stale process. Part A
(populated 0.6.17 upgrade) and the forbidden code-only rollback after patterns are
rehearsed by test_synthesis_upgrade.py.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import threading
import time
import uuid

from agentic_rag import backup, cli, db, llm, store, synthesis, worker
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from agentic_rag.domains import seed_defaults
from agentic_rag.llm import LLMUnavailableError
from agentic_rag.service import runner

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / 'docs/playbooks/system/rag-065-pattern-synthesis.md'
PB063 = ROOT / 'docs/playbooks/system/rag-063-source-evidence-upgrade.md'
COMMANDS = [
    'rag pattern preview --domain DOMAIN --project PROJECT',
    'rag pattern enable --domain DOMAIN --project PROJECT --reason',
    'rag pattern status --domain DOMAIN --project PROJECT',
    'rag pattern list --domain DOMAIN --project PROJECT',
    'rag pattern show <slug>',
    'rag pattern backfill --domain DOMAIN --project PROJECT --start <ISO> --end <ISO> --reason',
    'rag pattern recover <run_id> --reason',
    'rag pattern disable --domain DOMAIN --project PROJECT --reason',
    'rag service --config CONFIG verified-backup --source-version 0.6.17 --output DIR/current.dump',
    "<<'PYFRESH'", "<<'PYGATE'", '-- PB065-CLIENTS',
]
WRITER_KEY = 'pb.synthetic-playbook-central-writer-secret'


def snippet(name):
    """The exact heredoc body named `name` from the playbook."""
    body = re.split(rf'\n[ \t]*{name}\n', PLAYBOOK.read_text().split(f"<<'{name}'\n", 1)[1], maxsplit=1)[0]
    return textwrap.dedent(body)


def gate_rehearsal(tmp_path):
    """B0: a process older than the installation is reported and blocks; after its
    restart the gate passes. The fresh-import check names the installed version."""
    expected = next(line.split('"')[1] for line in (ROOT / 'pyproject.toml').read_text().splitlines()
                    if line.startswith('version = '))
    fresh = subprocess.run([sys.executable, '-I', '-c', snippet('PYFRESH')], text=True, capture_output=True, timeout=60)
    assert fresh.returncode == 0, fresh.stderr
    version, metadata = fresh.stdout.split()
    assert version == expected and Path(metadata).name == 'METADATA' and Path(metadata).exists()
    token = 'pb065-gate-' + uuid.uuid4().hex
    reader = [sys.executable, '-c', f'import agentic_rag.store, time; time.sleep(120)  # {token}']
    cached = tmp_path / 'cached-METADATA'
    cached.write_text('cached package metadata predating the reader')
    time.sleep(1.2)
    stale = subprocess.Popen(reader)
    try:
        time.sleep(1.2)
        marker = tmp_path / 'installed-METADATA'
        os.link(cached, marker)  # uv's install preserves the old cache mtime
        assert marker.stat().st_nlink == 2
        assert marker.stat().st_ctime > marker.stat().st_mtime + 2
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
    return {'fresh_version': version, 'hardlinked_install_blocks_stale': True,
            'stale_process_blocked': True, 'restarted_process_passes': True}


def clients_sql():
    block = re.split(r'\n[ \t]*-- PB065-CLIENTS\n', PLAYBOOK.read_text(), maxsplit=1)[1].split('```', 1)[0]
    return textwrap.dedent(block)


def integrity_sql():
    text = PLAYBOOK.read_text()
    block = text.split('```sql\n-- PB065-INTEGRITY\n', 1)[1].split('```', 1)[0]
    return block


def integrity(cfg):
    with db.connect(cfg, role='owner') as conn:
        return dict(conn.execute(integrity_sql()).fetchone())


def test_pb065_pattern_operations_on_an_owned_store(tmp_path, monkeypatch, capsys):
    text = PLAYBOOK.read_text()
    assert [c for c in COMMANDS if c not in text] == []
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    report = {}
    with isolated_database(Config(ollama_url='http://127.0.0.1:1')) as owned:
        def config(name, enabled, database=owned.db_name):
            path = tmp_path / name
            path.write_text(f'[db]\nname = "{database}"\nhost = "{owned.db_host}"\n\n'
                            f'[ollama]\nurl = "http://127.0.0.1:1"\n\n[backup]\nlocal_dir = "{tmp_path / "dumps"}"\n\n'
                            f'[synthesis]\nenabled = {"true" if enabled else "false"}\n')
            return path
        on, off = config('on.toml', True), config('off.toml', False)
        cfg = load_config(on)
        assert cfg.synthesis_enabled and not load_config(off).synthesis_enabled

        def rag(path, *argv):
            monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(path))
            code = cli.main(list(argv))
            out = capsys.readouterr()
            return code, out.out, out.err

        def status(project):
            code, out, err = rag(on, 'pattern', 'status', '--domain', 'general', '--project', project, '--json')
            assert code == 0, err
            return json.loads(out)

        def tick(worker_cfg=None):
            """One iteration of the central `rag service worker` loop."""
            stop, real = threading.Event(), worker.drain
            def once(conn, cfg, **kwargs):
                try:
                    return real(conn, cfg, **kwargs)
                finally:
                    stop.set()
            monkeypatch.setattr(worker, 'drain', once)
            try:
                assert runner.run(worker_cfg or cfg, stop=stop, interval=.01) == 0
            finally:
                monkeypatch.setattr(worker, 'drain', real)

        with db.connect(cfg) as conn:
            seed_defaults(conn)
            conn.commit()
        k1, k2 = fx.project('K1'), fx.project('K2')
        scope1 = ['--domain', 'general', '--project', k1]

        # B0: the all-reader gate (fresh import, stale-process check, direct clients).
        report['reader_gate'] = gate_rehearsal(tmp_path)
        with db.connect(cfg, role='owner') as conn:
            clients = conn.execute(clients_sql()).fetchall()
            conn.commit()
        assert all(set(row) == {'pid', 'usename', 'client_addr', 'application_name', 'backend_start'} for row in clients)
        report['reader_gate']['direct_clients_listed'] = len(clients)

        # A8: an upgraded store has no policy and no run.
        code, out, _ = rag(on, 'pattern', 'status', '--json')
        assert code == 0 and json.loads(out)['policies'] == [] and json.loads(out)['runs'] == []

        # B2: with the global switch off, enabling refuses.
        assert rag(off, 'pattern', 'enable', *scope1, '--reason', 'rehearsal')[0] == 1
        # B3: enable records the forward boundary.
        code, out, _ = rag(on, 'pattern', 'enable', *scope1, '--reason', 'rehearsal')
        assert code == 0 and 'pattern policy enabled (v1); forward boundary' in out
        with db.connect(cfg) as conn:
            fx.ingest(conn, cfg, {'K1'})
        # B1: preview is provider-free and write-free.
        monkeypatch.setattr(llm, 'run_structured', fx.ForbiddenProvider())
        fx.ForbiddenProvider.calls = 0
        code, out, _ = rag(on, 'pattern', 'preview', *scope1)
        assert code == 0 and '(no provider call, no write)' in out and 'sufficient' in out
        assert 'insufficient' not in out and fx.ForbiddenProvider.calls == 0

        # C2: a provider outage keeps the run pending; it completes after the backoff.
        outage = fx.ScriptedProvider('K1', fail=LLMUnavailableError('synthetic outage'))
        monkeypatch.setattr(llm, 'run_structured', outage)
        tick()
        assert status(k1)['runs'][0]['state'] == 'pending' and len(outage.calls) == 1
        with db.connect(cfg, role='owner') as conn:  # the backoff elapses
            conn.execute("UPDATE mining_queue SET next_attempt_at=now() WHERE kind='synthesis' AND status='pending'")
            conn.commit()
        honest = fx.ScriptedProvider('K1')
        monkeypatch.setattr(llm, 'run_structured', honest)
        tick()
        run = status(k1)['runs'][0]
        assert run['state'] == 'applied' and len(honest.calls) == 1
        report['outage_then_applied'] = run['state']

        # B5/B6: status, list and show.
        code, out, _ = rag(on, 'pattern', 'status', *scope1)
        assert code == 0 and 'enabled v1' in out and 'applied' in out
        code, out, _ = rag(on, 'pattern', 'list', *scope1)
        assert code == 0 and 'VPN reconnect clears the DNS suffix list [unreviewed, medium]' in out
        slug = 'vpn-reconnect-clears-the-dns-suffix-list'
        code, out, _ = rag(on, 'pattern', 'show', slug)
        assert code == 0 and 'A reviewable hypothesis' in out and 'ev1:' in out and 'src1:' in out
        assert 'support: 4 independent events in 4 memories' in out

        # C4: accepted work parked after exhausted apply attempts is recovered
        # without a second provider call.
        scope2 = ['--domain', 'general', '--project', k2]
        assert rag(on, 'pattern', 'enable', *scope2, '--reason', 'rehearsal')[0] == 0
        with db.connect(cfg) as conn:
            fx.ingest(conn, cfg, {'K2'})
        second = fx.ScriptedProvider('K2')
        monkeypatch.setattr(llm, 'run_structured', second)
        real_register = synthesis._register
        monkeypatch.setattr(synthesis, '_register', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('disk full')))
        tick()
        with db.connect(cfg, role='owner') as conn:  # the worker's finite attempts run out
            conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'"
                         " AND status IN ('pending','processing')")
            conn.commit()
        tick()
        parked = status(k2)['runs'][0]
        assert (parked['state'], parked['code'], parked['recoverable']) == ('error', 'apply_failed', True)
        code, out, _ = rag(on, 'pattern', 'status', *scope2)
        assert '(recoverable)' in out
        monkeypatch.setattr(synthesis, '_register', real_register)
        code, out, _ = rag(on, 'pattern', 'recover', parked['id'], '--reason', 'storage fixed')
        assert code == 0 and f"run {parked['id']} re-queued (accepted)" in out
        assert rag(on, 'pattern', 'recover', parked['id'], '--reason', 'again')[0] == 1
        tick()
        assert status(k2)['runs'][0]['state'] == 'applied' and len(second.calls) == 1
        report['recovered_provider_calls'] = len(second.calls)

        # C4 (central): a writer's client CLI recovers through the API; the central
        # worker, resolving the writer's credential, applies without a provider call.
        from agentic_rag.service.api import create_app
        from agentic_rag.service.auth import hash_key
        from agentic_rag.service import client as remote
        from starlette.testclient import TestClient
        i1 = fx.project('I1')
        scope3 = ['--domain', 'general', '--project', i1]
        principals = tmp_path / 'principals.toml'
        grant = f'read_domains = ["general"]\nwrite_domains = ["general"]\nread_projects = ["{i1}"]\nwrite_projects = ["{i1}"]\n'
        principals.write_text(f'version = 1\n[users.operator]\n{grant}[machines.writer]\nuser = "operator"\n{grant}'
                              f'keys = {{pb = "{hash_key(WRITER_KEY)}"}}\n')
        principals.chmod(0o600)
        server = config('server.toml', True)
        server.write_text(server.read_text() + f'\n[service]\nmode = "server"\nauth_file = "{principals}"\n')
        server_cfg = load_config(server)
        token = tmp_path / 'writer.token'
        token.write_text(WRITER_KEY)
        token.chmod(0o600)
        client = tmp_path / 'client.toml'
        client.write_text(f'[db]\nname = "no_local_database_access"\n\n[service]\nmode = "client"\n'
                          f'url = "https://testserver"\ntoken_file = "{token}"\nspool_dir = "{tmp_path / "spool"}"\n')
        original_client = remote.RemoteClient
        with TestClient(create_app(server_cfg, principals, allowed_hosts=['testserver']),
                        base_url='https://testserver') as sender:
            monkeypatch.setattr(remote, 'RemoteClient', lambda c: original_client(c, sender=sender))
            code, out, err = rag(client, 'pattern', 'enable', *scope3, '--reason', 'central rehearsal')
            assert code == 0, err
            with db.connect(cfg) as conn:
                fx.ingest(conn, cfg, {'I1'})
            third = fx.ScriptedProvider('I1')
            monkeypatch.setattr(llm, 'run_structured', third)
            monkeypatch.setattr(synthesis, '_register', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('disk full')))
            tick(server_cfg)
            with db.connect(cfg, role='owner') as conn:
                conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'"
                             " AND status IN ('pending','processing')")
                conn.commit()
            tick(server_cfg)
            code, out, err = rag(client, 'pattern', 'status', *scope3, '--json')
            assert code == 0, err
            parked = json.loads(out)['runs'][0]
            assert (parked['state'], parked['code'], parked['recoverable']) == ('error', 'apply_failed', True)
            assert json.loads(out)['policies'][0]['forward']['held_for_recovery'] == parked['new_memories']
            monkeypatch.setattr(synthesis, '_register', real_register)
            code, out, err = rag(client, 'pattern', 'recover', parked['id'], '--reason', 'central storage fixed')
            assert code == 0 and f"run {parked['id']} re-queued (accepted)" in out, err
            tick(server_cfg)
            code, out, err = rag(client, 'pattern', 'status', *scope3, '--json')
            assert json.loads(out)['runs'][0]['state'] == 'applied' and len(third.calls) == 1, err
            code, out, err = rag(client, 'pattern', 'list', *scope3, '--json')
            assert code == 0 and len(json.loads(out)['items']) == 1, err
        monkeypatch.setattr(remote, 'RemoteClient', original_client)
        report['central_recovered_provider_calls'] = len(third.calls)

        # Integrity check after C4.
        clean = integrity(cfg)
        assert clean == {'patterns': 3, 'dependency_mismatch': 0, 'pattern_without_audit': 0,
                         'applied_without_pattern': 0, 'pattern_cites_pattern': 0,
                         'processed_without_terminal_run': 0, 'open_runs_of_disabled_policies': 0}, clean
        report['integrity'] = clean

        # C1: backfill is explicit and bounded. An empty window closes without a run;
        # a window below the floor ends without a provider call.
        boundary = datetime.fromisoformat(status(k1)['policies'][0]['forward_from'])
        monkeypatch.setattr(llm, 'run_structured', fx.ForbiddenProvider())
        fx.ForbiddenProvider.calls = 0
        late = (boundary + timedelta(days=1)).isoformat()
        assert rag(on, 'pattern', 'backfill', *scope1, '--start', boundary.isoformat(), '--end', late,
                   '--reason', 'too late', '--max-batches', '1')[0] == 1
        code, out, _ = rag(on, 'pattern', 'backfill', *scope1, '--start', (boundary - timedelta(days=30)).isoformat(),
                           '--end', boundary.isoformat(), '--reason', 'September reports', '--max-batches', '1')
        assert code == 0 and 'requested' in out and len(status(k1)['backfills']) == 1
        tick()
        assert status(k1)['backfills'] == [] and all(r['kind'] == 'forward' for r in status(k1)['runs'])
        f5, scope5 = fx.project('F5'), ['--domain', 'general', '--project', fx.project('F5')]
        with db.connect(cfg) as conn:
            fx.ingest(conn, cfg, {'F5'})
        assert rag(on, 'pattern', 'enable', *scope5, '--reason', 'rehearsal')[0] == 0
        boundary5 = datetime.fromisoformat(status(f5)['policies'][0]['forward_from'])
        assert rag(on, 'pattern', 'backfill', *scope5, '--start', (boundary5 - timedelta(days=1)).isoformat(),
                   '--end', boundary5.isoformat(), '--reason', 'history', '--max-batches', '1')[0] == 0
        tick()
        backfill_run = status(f5)['runs'][0]
        assert (backfill_run['kind'], backfill_run['state'], backfill_run['code']) == (
            'backfill', 'non_conclusion', 'insufficient_independent_support')
        assert fx.ForbiddenProvider.calls == 0
        report['backfill_below_floor'] = backfill_run['code']

        # C6: global switch off stops changes; existing patterns stay readable.
        assert rag(off, 'pattern', 'backfill', *scope1, '--start', (boundary - timedelta(days=2)).isoformat(),
                   '--end', boundary.isoformat(), '--reason', 'paused')[0] == 1
        assert rag(off, 'pattern', 'show', slug)[0] == 0

        # Integrity after a disable is checked after the next tick: a run that was open
        # when its policy was disabled is closed (withheld) by that tick.
        c1, scope4 = fx.project('C1'), ['--domain', 'general', '--project', fx.project('C1')]
        assert rag(on, 'pattern', 'enable', *scope4, '--reason', 'rehearsal')[0] == 0
        with db.connect(cfg) as conn:
            fx.ingest(conn, cfg, {'C1'})
            assert synthesis.schedule(conn, cfg)['scheduled'] == 1
        assert rag(on, 'pattern', 'disable', *scope4, '--reason', 'pause before the tick')[0] == 0
        assert integrity(cfg)['open_runs_of_disabled_policies'] == 1
        tick()
        assert integrity(cfg) == clean and status(c1)['runs'][0]['code'] == 'policy_disabled'
        assert fx.ForbiddenProvider.calls == 0
        report['integrity_after_disable_tick'] = 'clean'

        # C5/C7: disable withholds without deleting; enabling again shows it.
        code, out, _ = rag(on, 'pattern', 'disable', *scope1, '--reason', 'pause')
        assert code == 0 and 'disabled (v2)' in out
        assert 'VPN reconnect' not in rag(on, 'pattern', 'list', *scope1)[1]
        assert rag(on, 'pattern', 'show', slug)[0] == 1
        assert integrity(cfg)['patterns'] == 3
        assert rag(on, 'pattern', 'enable', *scope1, '--reason', 'resume')[0] == 0
        assert rag(on, 'pattern', 'show', slug)[0] == 0

        # D: verified backup after the upgrade, restored with PB-063 R1-R3.
        dump = tmp_path / 'current.dump'
        code, out, err = rag(on, 'service', '--config', str(on), 'verified-backup', '--source-version', '0.6.17',
                             '--output', str(dump))
        assert code == 0, err
        assert json.loads(out)['restore_verified'] is True
        snippets = [textwrap.dedent(part.split('\n   PYVERIFY', 1)[0])
                    for part in PB063.read_text().split("<<'PYVERIFY'\n")[1:]]
        assert len(snippets) == 2
        manifest = dump.with_name(dump.name + '.manifest.json')

        def check(index, *paths):
            return subprocess.run([sys.executable, '-c', snippets[index], *map(str, paths)],
                                  text=True, capture_output=True, timeout=30)
        digest = check(0, dump, manifest)
        assert digest.returncode == 0 and digest.stdout.strip() == 'dump_digest_verified', digest.stderr
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(dump)])
            restored = config('restored.toml', True, target.db_name)
            inventory = tmp_path / 'restored-inventory.json'
            code, _, err = rag(restored, 'service', '--config', str(restored), 'inventory', '--source-version', '0.6.17',
                               '--output', str(inventory))
            assert code == 0, err
            verified = check(1, manifest, inventory)
            assert verified.returncode == 0 and verified.stdout.strip() == 'restore_manifest_verified', verified.stderr
            assert integrity(load_config(restored)) == clean
            code, out, _ = rag(restored, 'pattern', 'show', slug)
            assert code == 0 and 'A reviewable hypothesis' in out
        report['restore'] = 'restore_manifest_verified'
    print('PB065_REHEARSAL', json.dumps(report, sort_keys=True))
