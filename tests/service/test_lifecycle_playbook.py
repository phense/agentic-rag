"""PB-066-OPS rehearsal: the playbook's commands run through the real CLI, the
operator commands and REST on an owned, automatically dropped store that the
actual 0.6.18 code (git archive of main d4d2372) populated at schema030.

Part A upgrades through `rag service upgrade`; B0 runs the exact gate snippets
against a deliberately stale process and the old-code `[curation] budget = 0`
fallback; B and C apply, refuse, correct and review through `rag lifecycle` and
`/v1/tools`; part D takes a post-upgrade verified backup, restores it into an
empty owned database with the PB-063 commands and checks the manifest. The
populated old-code reads and writes on schema031 are rehearsed by
test_lifecycle_upgrade.py.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import time
import uuid

from starlette.testclient import TestClient

from agentic_rag import backup, cli, db, llm, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import load_config
from test_maintenance_restore import owned_source
from .test_api import app_fixture, headers, KEYS
from .test_lifecycle_upgrade import OLD_CURATION, POPULATE, old_tree, run_old

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / 'docs/playbooks/system/rag-066-memory-lifecycle.md'
PB063 = ROOT / 'docs/playbooks/system/rag-063-source-evidence-upgrade.md'
COMMANDS = [
    'rag service --config CONFIG inventory --source-version 0.6.18 --identities --output DIR/inventory.json',
    'rag service --config CONFIG preflight --source-version 0.6.18 --mode local',
    'rag service --config CONFIG upgrade --source-version 0.6.18 --dump DIR/lifecycle031.dump --apply --writers-stopped',
    'rag service --config CONFIG status',
    'rag review',
    'rag lifecycle preview MEMBER TARGET',
    'rag lifecycle apply MEMBER TARGET --operation OP --member-version V1 --target-version V2 --reason',
    'rag lifecycle show MEMBER',
    'rag lifecycle correct DECISION --revision N --reason',
    'rag lifecycle history MEMBER',
    'rag get MEMBER --view current',
    'rag service --config CONFIG verified-backup --source-version 0.6.18 --output DIR/current.dump',
    "<<'PYFRESH'", "<<'PYGATE'", '-- PB066-CLIENTS', '-- PB066-INTEGRITY', 'budget = 0',
]


def snippet(name, text=None):
    """The exact heredoc body named `name` (the last one of that name)."""
    body = re.split(rf'\n[ \t]*{name}\n', (text or PLAYBOOK.read_text()).split(f"<<'{name}'\n")[-1], maxsplit=1)[0]
    return textwrap.dedent(body)


def sql_block(marker):
    block = re.split(rf'\n[ \t]*{re.escape(marker)}\n', PLAYBOOK.read_text(), maxsplit=1)[1].split('```', 1)[0]
    return textwrap.dedent(block)


def integrity(cfg):
    with db.connect(cfg, role='owner') as conn:
        return dict(conn.execute(sql_block('-- PB066-INTEGRITY')).fetchone())


def gate_rehearsal(tmp_path):
    """B0: a process older than the installation blocks the gate; after its restart it passes."""
    expected = next(line.split('"')[1] for line in (ROOT / 'pyproject.toml').read_text().splitlines()
                    if line.startswith('version = '))
    fresh = subprocess.run([sys.executable, '-I', '-c', snippet('PYFRESH')], text=True, capture_output=True, timeout=60)
    assert fresh.returncode == 0, fresh.stderr
    version, metadata = fresh.stdout.split()
    assert version == expected == '0.6.19' and Path(metadata).name == 'METADATA'
    token = 'pb066-gate-' + uuid.uuid4().hex
    reader = [sys.executable, '-c', f'import time; time.sleep(120)  # {token}']
    stale = subprocess.Popen(reader)
    try:
        time.sleep(1.2)
        marker = tmp_path / 'installed-METADATA'
        marker.write_text('installed after the stale reader started')
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


def test_pb066_upgrade_decide_refuse_correct_and_restore(tmp_path, monkeypatch, capsys):
    text = PLAYBOOK.read_text()
    assert [c for c in COMMANDS if c not in text] == []
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr('agentic_rag.search.try_embed_texts', lambda *a, **k: None)

    def forbidden(*args, **kwargs):
        raise AssertionError('no provider call in PB-066')
    monkeypatch.setattr(llm, 'run_structured', forbidden)
    proofs = tmp_path / 'proofs'
    proofs.mkdir()
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 30) as source:
        ids = run_old(old, source, tmp_path, POPULATE)
        config = tmp_path / 'source.toml'
        config.write_text(f'[db]\nname = "{source.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n'
                          f'[rerank]\nurl = "http://127.0.0.1:1"\n\n[backup]\nlocal_dir = "{tmp_path / "dumps"}"\n')
        cfg = load_config(config)

        def rag(*argv, path=config):
            monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(path))
            code = cli.main(list(argv))
            out = capsys.readouterr()
            return code, out.out, out.err

        def ok(*argv, path=config):
            code, out, err = rag(*argv, path=path)
            assert code == 0, (argv, err)
            return out

        def as_json(*argv):
            return json.loads(ok(*argv, '--json'))

        def operator(*argv):
            return json.loads(ok('service', '--config', str(config), *argv).strip().splitlines()[-1])

        # Part A
        assert operator('inventory', '--source-version', '0.6.18', '--identities',
                        '--output', str(proofs / 'inventory.json'))['supported'] is True
        assert operator('preflight', '--source-version', '0.6.18', '--mode', 'local')['ready'] is True
        a4 = operator('upgrade', '--source-version', '0.6.18', '--dump', str(proofs / 'lifecycle031.dump'),
                      '--apply', '--writers-stopped')
        assert a4['migrations_applied'] == ['031_memory_lifecycle.sql', '032_extraction_policy.sql']
        assert a4['restore_verified'] and a4['original_rows_unchanged']
        assert (proofs / 'lifecycle031.dump.manifest.json').exists()
        a5 = operator('upgrade', '--source-version', '0.6.18', '--dump', str(proofs / 'retry.dump'),
                      '--apply', '--writers-stopped')
        assert a5['migrations_applied'] == [] and a5['restore_verified']
        operator('status')
        assert rag('service', '--config', str(config), 'upgrade', '--source-version', '0.6.20', '--dump',
                   str(proofs / 'refused.dump'))[0] == 1
        zero = {'decisions': 0, 'decision_without_event': 0, 'correction_without_event': 0,
                'events_minus_audit': 0, 'chains': 0}
        assert integrity(cfg) == zero

        # B0: gate snippets, direct clients and the old-code fallback.
        gate_rehearsal(tmp_path)
        with db.connect(cfg) as conn:
            clients = conn.execute(sql_block('-- PB066-CLIENTS')).fetchall()
        assert all(set(row) >= {'pid', 'client_addr', 'backend_start'} for row in clients)
        fallback = run_old(old, cfg, tmp_path, OLD_CURATION, extra='\n[curation]\nbudget = 0\n')
        assert fallback == {'budget': 0, 'merged': 0, 'archived': []}

        # B1-B4: exact duplicate through the CLI.
        review = ok('review')
        assert 'duplicate candidates:' in review and 'lifecycle review:' in review
        seen = as_json('lifecycle', 'preview', ids['dup-copy'], ids['dup-keep'])
        assert seen['classification'] == 'exact_duplicate' and seen['writes'] == 0
        assert 'No write, no provider call.' in ok('lifecycle', 'preview', ids['dup-copy'], ids['dup-keep'])
        out = ok('lifecycle', 'apply', ids['dup-copy'], ids['dup-keep'], '--operation', 'exact_duplicate',
                 '--member-version', seen['member']['version'], '--target-version', seen['target']['version'],
                 '--reason', 'same release checklist')
        decision = re.match(r'decision (\S+): exact_duplicate active$', out.strip()).group(1)
        assert as_json('lifecycle', 'show', ids['dup-copy'])['as_member'][0]['relationship'] == 'hiding'

        def found(view):
            hits = as_json('search', 'release wheel changelog', '--scope', 'all', '--strategy', 'lexical',
                           '--rerank', 'off', '--context', 'off', '--view', view)
            return {h['document_id'] for h in hits['results']}
        assert ids['dup-copy'] not in found('current') and ids['dup-keep'] in found('current')
        assert ids['dup-copy'] in found('include_merged')
        got = as_json('get', ids['dup-copy'], '--view', 'current')
        assert got['document']['id'] == ids['dup-keep'] and got['lifecycle']['resolution'] == 'canonical'

        # C: refusals write nothing.
        def refused(*argv):
            code, out, err = rag(*argv)
            assert code == 1, (argv, out)
            return err.strip()
        before = integrity(cfg)
        ext = as_json('lifecycle', 'preview', ids['short'], ids['rich'], '--operation', 'extension')
        apply_ext = ['lifecycle', 'apply', ids['short'], ids['rich'], '--operation', 'extension',
                     '--member-version', ext['member']['version'], '--target-version', ext['target']['version'],
                     '--reason', 'rich note covers the short one']
        assert refused(*apply_ext) == 'error: review_required'
        with db.connect(cfg) as conn:
            store.save_document(conn, cfg, doc_id=ids['short'], title='Printer P1 toner',
                                body='Printer P1 uses toner TN-243.', domain='general', dtype='memory')
        assert refused(*apply_ext, '--reviewed') == 'error: stale_version'  # C1
        titles = as_json('lifecycle', 'preview', ids['alpha-port'], ids['beta-port'], '--operation', 'exact_duplicate')
        assert titles['operations']['exact_duplicate']['code'] == 'proof_failed'
        assert refused('lifecycle', 'apply', ids['alpha-port'], ids['beta-port'], '--operation', 'exact_duplicate',
                       '--member-version', titles['member']['version'], '--target-version', titles['target']['version'],
                       '--reason', 'different titles') == 'error: proof_failed'
        assert refused('lifecycle', 'preview', ids['team-b-copy'], ids['dup-keep']) == 'error: scope_mismatch'
        assert integrity(cfg) == before
        ext = as_json('lifecycle', 'preview', ids['short'], ids['rich'], '--operation', 'extension')
        keyed = ['lifecycle', 'apply', ids['short'], ids['rich'], '--operation', 'extension', '--reviewed',
                 '--member-version', ext['member']['version'], '--target-version', ext['target']['version'],
                 '--request-key', 'pb066-ext-1']
        assert ok(*keyed, '--reason', 'rich note covers the short one').strip().endswith('extension active')
        assert refused(*keyed, '--reason', 'another reason') == 'error: replay_mismatch'  # C2
        chain = as_json('lifecycle', 'preview', ids['dup-keep'], ids['rich'], '--operation', 'semantic_duplicate')
        assert refused('lifecycle', 'apply', ids['dup-keep'], ids['rich'], '--operation', 'semantic_duplicate',
                       '--reviewed', '--member-version', chain['member']['version'],
                       '--target-version', chain['target']['version'],
                       '--reason', 'would chain') == 'error: chain_conflict'  # C3
        contra = as_json('lifecycle', 'preview', ids['alpha-port'], ids['beta-port'], '--operation', 'contradiction')
        assert ok('lifecycle', 'apply', ids['alpha-port'], ids['beta-port'], '--operation', 'contradiction',
                  '--member-version', contra['member']['version'], '--target-version', contra['target']['version'],
                  '--reason', 'two servers claim one port').strip().endswith('contradiction contested')
        assert 'contested' in ok('review').split('lifecycle review:', 1)[1]
        # C6: correct the exact duplicate; the member answers again and history keeps both events.
        out = ok('lifecycle', 'correct', decision, '--revision', '1', '--reason', 'kept both copies on purpose')
        assert out.strip() == f'decision {decision}: exact_duplicate corrected'
        assert ids['dup-copy'] in found('current')
        events = [e['event'] for e in as_json('lifecycle', 'history', ids['dup-copy'])['items']]
        assert sorted(events) == ['applied', 'corrected']
        # C7: an ordinary edit after the decision makes the extension stale; nothing hides.
        with db.connect(cfg) as conn:
            store.save_document(conn, cfg, doc_id=ids['short'], title='Printer P1 toner',
                                body='Printer P1 uses toner TN-243 (checked).', domain='general', dtype='memory')
        assert as_json('lifecycle', 'show', ids['short'])['as_member'][0]['relationship'] == 'stale'
        assert 'stale' in ok('review').split('lifecycle review:', 1)[1]

        # B5 central: a writer of alpha:/projects/a decides and corrects over REST.
        with db.connect(cfg) as conn:
            remote = {k: store.save_document(conn, cfg, title='Plotter paper size', body='The plotter is loaded with A0 rolls.',
                                             domain='alpha', dtype='memory', project='/projects/a').doc_id
                      for k in ('keep', 'copy')}
        app, _ = app_fixture(tmp_path, cfg)
        with TestClient(app, base_url='https://testserver') as client:
            def call(name, **arguments):
                response = client.post('/v1/tools/' + name, headers=headers(KEYS[0]), json=arguments)
                return response.status_code, response.json()
            status, seen = call('memory_lifecycle_preview', member=remote['copy'], target=remote['keep'])
            assert status == 200 and seen['classification'] == 'exact_duplicate'
            status, made = call('memory_lifecycle_apply', member=remote['copy'], target=remote['keep'],
                                operation='exact_duplicate', expected_member_version=seen['member']['version'],
                                expected_target_version=seen['target']['version'], reason='central copy')
            assert status == 200 and made['decision']['state'] == 'active'
            status, undone = call('memory_lifecycle_correct', decision_id=made['decision']['id'],
                                  expected_revision=1, reason='central undo')
            assert status == 200 and undone['decision']['state'] == 'corrected'
        final = integrity(cfg)
        assert final == {**zero, 'decisions': 4}

        # Part D: post-upgrade verified backup, restored into an empty database with PB-063 R2/R3.
        current = operator('verified-backup', '--source-version', '0.6.18', '--output', str(proofs / 'current.dump'))
        assert current['restore_verified']
        verify = snippet('PYVERIFY', PB063.read_text())
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(proofs / 'current.dump')])
            restored = tmp_path / 'restored.toml'
            restored.write_text(config.read_text().replace(source.db_name, target.db_name))
            assert json.loads(ok('service', '--config', str(restored), 'inventory', '--source-version', '0.6.18',
                                 '--output', str(proofs / 'restored-inventory.json')).strip().splitlines()[-1])['supported']
            checked = subprocess.run([sys.executable, '-c', verify, str(proofs / 'current.dump.manifest.json'),
                                      str(proofs / 'restored-inventory.json')], text=True, capture_output=True, timeout=60)
            assert checked.returncode == 0 and checked.stdout.strip() == 'restore_manifest_verified', checked
            assert integrity(target) == final
            with db.connect(target) as conn:
                assert conn.execute("SELECT count(*) n FROM pg_trigger WHERE tgname IN ('lifecycle_decision_guard',"
                                    "'lifecycle_event_guard','lifecycle_events_append_only')").fetchone()['n'] == 3
        # Interrupted-upgrade decision: both markers present means A4 committed.
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT to_regclass('public.lifecycle_decisions') IS NOT NULL AS t,"
                                " EXISTS (SELECT 1 FROM schema_migrations WHERE filename='031_memory_lifecycle.sql') AS m"
                                ).fetchone() == {'t': True, 'm': True}
