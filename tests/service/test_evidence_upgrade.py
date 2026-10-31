"""RAG-063 T063-008: populated 0.6.15/schema028 -> 029 rehearsal on disposable copies.

The source store is populated by the actual 0.6.15 code (git archive of the base
commit), then upgraded through the existing operator framework. Proves verified
backup, original-field/ACL preservation, interrupted retry, old-client reads and
legacy writes after upgrade, restore-stable evidence versions, and the explicit
pre-upgrade restoration limit. No production system is touched.
"""
import json
import os
from pathlib import Path
import subprocess
import textwrap
import sys
import tarfile
import time

import pytest

from agentic_rag import backup, db, store
from agentic_rag import evidence_contract as contract
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from agentic_rag.service.schema import validate_schema
from test_maintenance_restore import owned_source

BASE = '5390a6f6b4a7cce4b27abc9b51226acf2dac6223'  # main at 0.6.15 / schema028

POPULATE = r'''
import json
from agentic_rag.config import load_config
from agentic_rag import db, store, evidence, pins, domains
cfg = load_config()
assert evidence.__file__.startswith(__import__('os').getcwd())
store.try_embed_texts = lambda *a, **k: None
created = {}
with db.connect(cfg) as conn:
    domains.add_domain(conn, 'alpha') if not conn.execute("SELECT 1 FROM domains WHERE name='alpha'").fetchone() else None
    def src(i, role='user', quote=None, complete=True, ns='session:legacy-a'):
        return {'namespace': ns, 'source_id': f'event-{i}', 'role': role, 'quote': quote or f'Legacy original quote {i}.',
                'complete': complete, 'timestamp': '2026-0%d-01T00:00:00Z' % (1 + i % 8)}
    for n in range(12):
        domain = ('general', 'programming', 'alpha')[n % 3]
        project = ('/synthetic/team-a', '/synthetic/team-b')[n % 2]
        kind = ('stated', 'inference', 'proposal')[n % 3]
        role = 'user' if kind == 'stated' else 'assistant'
        r = store.save_claim(conn, cfg, title=f'Legacy claim {n}', body=f'Legacy claim body {n} ünïcödé',
            domain=domain, dtype='memory', project=project, claim_kind=kind,
            evidence=[src(n, role, f'Legacy claim body {n} ünïcödé', kind == 'stated', ns=f'session:user-{n % 2}'),
                      src(100 + n % 4, 'user', f'Shared legacy statement {n % 4}', True, ns='session:shared')])
        created[f'claim{n}'] = r.doc_id
    for n in (1, 4, 7):
        evidence.review(conn, created[f'claim{n}'], state='confirmed', reason=f'legacy review {n}')
    evidence.review(conn, created['claim2'], state='refuted', reason='legacy refutation')
    keys = [r['source_key'] for r in conn.execute("SELECT source_key FROM knowledge_sources ORDER BY source_key")]
    store.set_source_state(conn, keys[0], state='refuted', reason='legacy correction')
    store.set_source_state(conn, keys[1], state='removed', reason='legacy withdrawal')
    store.set_source_state(conn, keys[1], state='active', reason='legacy reinstatement')
    for i, (value, when, rel) in enumerate([('8766', '2026-01-01T00:00:00Z', 'assertion'), ('8767', '2026-02-01T00:00:00Z', 'replacement')]):
        r = store.save_assertion(conn, cfg, entity='legacy-service', attribute='port', value=value, domain='general',
            event_at=when, relation=rel, project='/synthetic/team-a',
            evidence={'source_id': 'port-' + value, 'role': 'user', 'quote': 'legacy-service port ' + value})
        created[f'fact{i}'] = r.doc_id
    legacy = store.save_document(conn, cfg, title='Unmanaged legacy note', body='Legacy note without claim evidence',
        domain='general', dtype='memory', project='/synthetic/team-a', mark_verified=True)
    created['legacy'] = legacy.doc_id
    pins.add_pin(conn, body='Preserve legacy evidence', scope='global')
    for owner in ('owner-a', 'owner-b'):
        conn.execute("INSERT INTO service_streams(session_id,owner_namespace,project,last_cursor) VALUES (%s,%s,'/synthetic/team-a','c1')", ('s-' + owner, owner))
    conn.commit()
print(json.dumps(created))
'''

OLD_CLIENT = r'''
import json, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, search, evidence
cfg = load_config()
store.try_embed_texts = search.try_embed_texts = lambda *a, **k: None
ids = json.loads(sys.argv[1])
out = {}
with db.connect(cfg, role='reader') as conn:
    out['get'] = {k: (store.get_document(conn, v) or {}).get('body') for k, v in ids.items()}
    out['sources'] = sum(len(store.get_document(conn, v)['claim_sources']) for v in ids.values())
    hits, _ = search.search(conn, cfg, 'Legacy claim body', strategy='lexical', rerank_mode='off', project='/synthetic/team-a')
    out['search'] = sorted(h.document_id for h in hits)
if len(sys.argv) > 2:
    with db.connect(cfg) as conn:
        evidence.review(conn, sys.argv[2], state='unreviewed', reason='old 0.6.15 writer after upgrade')
print(json.dumps(out, default=str))
'''


def old_tree(tmp_path):
    root = tmp_path / 'old-0.6.15'
    root.mkdir()
    archive = tmp_path / 'old.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', 'archive', BASE, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=out, check=True,
                       cwd=Path(__file__).resolve().parents[2])
    with tarfile.open(archive) as content:
        content.extractall(root, filter='data')
    archive.unlink()
    return root


def run_old(root, cfg, tmp_path, code, *args):
    config = tmp_path / 'old.toml'
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n')
    env = {**os.environ, 'PYTHONPATH': str(root), 'AGENTIC_RAG_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c', code, *args], cwd=root, env=env, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def versions(cfg, ids):
    with db.connect(cfg, role='reader') as conn:
        return {k: contract.inspect(conn, v)['version'] for k, v in sorted(ids.items())}


def test_populated028_upgrade_interrupt_retry_old_clients_and_restore_stable_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest', lambda cfg: 'a' * 64)
    report = {'source_version': '0.6.15', 'source_commit': BASE, 'source_schema': 28, 'target_schema': 29}
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 28) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE)
        original = upgrade.inventory(cfg, '0.6.15', identities=True)
        report['original_rows'] = sum(t['rows'] for t in original['tables'].values())
        report['original_tables'] = len(original['tables'])
        report['claims'] = original['tables']['claim_records']['rows']
        report['spans'] = original['tables']['claim_evidence']['rows']
        report['sources'] = original['tables']['knowledge_sources']['rows']
        report['audit_rows'] = original['tables']['audit_log']['rows']
        with db.connect(cfg) as conn:
            report['shared_sources_cross_domain'] = conn.execute('''SELECT count(*) n FROM (SELECT e.source_key FROM claim_evidence e
                JOIN documents d ON d.id=e.document_id GROUP BY e.source_key HAVING count(DISTINCT d.domain)>1) shared''').fetchone()['n']
        assert report['shared_sources_cross_domain'] >= 1
        before_old_reads = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids))
        # 1. Interrupted migration: the crash happens after 029 executed but before commit.
        real_apply = db.apply_migrations

        def crash(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('simulated crash during migration029')
        monkeypatch.setattr(db, 'apply_migrations', crash)
        with pytest.raises(RuntimeError, match='simulated crash'):
            upgrade.local_upgrade(cfg, '0.6.15', tmp_path / 'interrupted.dump', apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT to_regclass('public.claim_history') IS NULL AS absent").fetchone()['absent']
            assert '029_source_evidence.sql' not in {r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations')}
            assert conn.execute("SELECT current_setting('default_transaction_read_only') v").fetchone()['v'] == 'off'
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        # 2. Retry with a fresh verified backup.
        started = time.perf_counter()
        changed = upgrade.local_upgrade(cfg, '0.6.15', tmp_path / 'upgrade.dump', apply=True, writers_stopped=True)
        report['upgrade_seconds'] = round(time.perf_counter() - started, 2)
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert changed['migrations_applied'] == ['029_source_evidence.sql','030_pattern_synthesis.sql']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        with db.connect(cfg) as conn:
            validate_schema(conn)
            assert conn.execute('SELECT (SELECT count(*) FROM source_revisions)+(SELECT count(*) FROM claim_revisions)'
                                '+(SELECT count(*) FROM source_history)+(SELECT count(*) FROM claim_history) n').fetchone()['n'] == 0
        retry = upgrade.local_upgrade(cfg, '0.6.15', tmp_path / 'retry.dump', apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        # 3. Existing knowledge is inspectable with explicit baseline/unknown labels.
        baseline = versions(cfg, ids)
        with db.connect(cfg, role='reader') as conn:
            legacy = contract.inspect(conn, ids['legacy'])
            assert legacy['claim'] is None and 'legacy_provenance_unknown' in legacy['eligibility']['notices']
            claim0 = contract.inspect(conn, ids['claim0'])
            assert {i['revision'] for i in claim0['sources']['items']} == {1} and claim0['claim']['revision'] == 1
            assert contract.history(conn, ids['claim1'])['items'] == []  # no fabricated pre-upgrade events
            refuted = contract.inspect(conn, ids['claim2'])
            assert refuted['eligibility']['reasons'][0] == 'claim_refuted'
        # 4. Old 0.6.15 client reads are unchanged; its legacy write invalidates a strict token.
        after_old_reads = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids), ids['claim1'])
        assert after_old_reads == before_old_reads
        with db.connect(cfg) as conn:
            row = conn.execute("SELECT concurrency,inspected_version FROM claim_history WHERE document_id=%s AND operation='review'",
                               (ids['claim1'],)).fetchone()
            assert row == {'concurrency': 'direct', 'inspected_version': None}
            with pytest.raises(contract.EvidenceConflict):
                store.review_claim(conn, ids['claim1'], state='confirmed', reason='stale', expected_version=baseline['claim1'])
            fresh = contract.inspect(conn, ids['claim4'])['version']
            store.review_claim(conn, ids['claim4'], state='unreviewed', reason='new strict decision', expected_version=fresh)
            item = contract.inspect(conn, ids['claim0'])['sources']['items'][0]
            store.set_source_state(conn, item['source_key'], state='removed', reason='strict withdrawal',
                                   anchor=ids['claim0'], expected_version=item['source_version'])
        upgraded = versions(cfg, ids)
        report['versions_changed_by_post_upgrade_writes'] = sum(upgraded[k] != baseline[k] for k in ids)
        # 5. Restore-stable versions: a verified dump restored elsewhere yields identical versions.
        proof = upgrade.verified_backup(cfg, '0.6.15', tmp_path / 'after.dump')
        assert proof['restore_verified']
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(tmp_path / 'after.dump')])
            assert versions(target, ids) == upgraded
            with db.connect(target) as conn:
                assert conn.execute('SELECT count(*) n FROM claim_history').fetchone()['n'] >= 3
        # 6. Pre-upgrade restoration (the documented recovery path) and its write-loss limit.
        manifest = changed['manifest']
        upgrade.check_dump(tmp_path / 'upgrade.dump', manifest)
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(tmp_path / 'upgrade.dump')])
            with db.connect(target) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                assert upgrade._verify(conn, manifest, label='restore_mismatch')['unchanged']
                assert conn.execute("SELECT to_regclass('public.claim_history') IS NULL AS absent").fetchone()['absent']
                lost = conn.execute("SELECT review_state FROM claim_records WHERE document_id=%s", (ids['claim4'],)).fetchone()
                report['post_backup_decision_lost_on_restore'] = lost['review_state'] == 'confirmed'
            assert run_old(old, target, tmp_path, OLD_CLIENT, json.dumps(ids)) == before_old_reads
    print('EVIDENCE_UPGRADE', json.dumps(report, sort_keys=True))
    assert report['post_backup_decision_lost_on_restore'] is True


def test_operator_cli_preflight_upgrade_retry_on_populated028(tmp_path, monkeypatch, capsys):
    """The exact PB-063-UPGRADE commands, run against a disposable populated copy."""
    from agentic_rag import cli
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest', lambda cfg: 'a' * 64)
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 28) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE)
        config = tmp_path / 'operator.toml'
        config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n'
                          f'[backup]\nlocal_dir = "{tmp_path / "dumps"}"\n')
        outputs = {}
        for name, argv in [
            ('inventory', ['inventory', '--source-version', '0.6.15', '--identities', '--output', str(tmp_path / 'upgrade' / 'inventory.json')]),
            ('preflight', ['preflight', '--source-version', '0.6.15', '--mode', 'local']),
            ('plan', ['upgrade', '--source-version', '0.6.15', '--dump', str(tmp_path / 'upgrade' / 'plan.dump')]),
            ('upgrade', ['upgrade', '--source-version', '0.6.15', '--dump', str(tmp_path / 'upgrade' / 'evidence029.dump'), '--apply', '--writers-stopped']),
            ('retry', ['upgrade', '--source-version', '0.6.15', '--dump', str(tmp_path / 'upgrade' / 'retry.dump'), '--apply', '--writers-stopped']),
            ('status', ['status']),
        ]:
            assert cli.main(['service', '--config', str(config), *argv]) == 0, capsys.readouterr().err
            outputs[name] = json.loads(capsys.readouterr().out)
        assert outputs['preflight']['ready'] and outputs['preflight']['inventory']['supported']
        assert outputs['plan']['applied'] is False and not (tmp_path / 'upgrade' / 'plan.dump').exists()
        assert outputs['upgrade']['migrations_applied'] == ['029_source_evidence.sql','030_pattern_synthesis.sql']
        assert outputs['upgrade']['restore_verified'] and outputs['upgrade']['original_rows_unchanged']
        assert (tmp_path / 'upgrade' / 'evidence029.dump.manifest.json').exists()
        assert outputs['retry']['migrations_applied'] == []
        with db.connect(cfg) as conn:
            validate_schema(conn)
        evidence_config = tmp_path / 'evidence.toml'
        evidence_config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n')
        monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(evidence_config))
        assert cli.main(['evidence', 'show', ids['claim0'], '--json']) == 0
        assert json.loads(capsys.readouterr().out)['contract_version'] == 1


        # PB063-R1: execute the public rollback path as documented, including its
        # digest/manifest snippets. A private _verify call cannot prove this path.
        playbook = Path(__file__).resolve().parents[2] / 'docs/playbooks/system/rag-063-source-evidence-upgrade.md'
        snippets = [textwrap.dedent(part.split('\n   PYVERIFY', 1)[0])
                    for part in playbook.read_text().split("<<'PYVERIFY'\n")[1:]]
        assert len(snippets) == 2
        dump = tmp_path / 'upgrade' / 'evidence029.dump'
        manifest = dump.with_name(dump.name + '.manifest.json')
        def check_snippet(index, *paths):
            return subprocess.run([sys.executable, '-c', snippets[index], *map(str, paths)],
                                  text=True, capture_output=True, timeout=30)
        digest = check_snippet(0, dump, manifest)
        assert digest.returncode == 0 and digest.stdout.strip() == 'dump_digest_verified', digest.stderr
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(dump)])
            # Switch only db.name, preserving the rest of the operator config.
            import tomlkit
            restored = tomlkit.parse(config.read_text())
            restored['db']['name'] = target.db_name
            restored_config = tmp_path / 'restored.toml'
            restored_config.write_text(tomlkit.dumps(restored))
            inventory_path = tmp_path / 'upgrade' / 'restored-inventory.json'
            assert cli.main(['service', '--config', str(restored_config), 'inventory', '--source-version', '0.6.15',
                             '--output', str(inventory_path)]) == 0, capsys.readouterr().err
            capsys.readouterr()
            checked = check_snippet(1, manifest, inventory_path)
            assert checked.returncode == 0 and checked.stdout.strip() == 'restore_manifest_verified', checked.stderr
            # A changed grant or row must block cutover, not merely print success.
            actual = json.loads(inventory_path.read_text())
            altered = tmp_path / 'altered.json'
            for field, value in [('grants', []), ('tables', {}), ('owners', {}), ('sequences', {})]:
                altered.write_text(json.dumps({**actual, field: value}))
                rejected = check_snippet(1, manifest, altered)
                assert rejected.returncode != 0 and 'restore_mismatch_' + field in rejected.stderr
            # A new service must reject028; archived 0.6.15 with the new launch
            # environment must accept it and read the original memory.
            from agentic_rag.service.schema import ServiceSchemaError
            with db.connect(target) as conn:
                with pytest.raises(ServiceSchemaError):
                    validate_schema(conn)
            env = {**os.environ, 'PYTHONPATH': str(old), 'AGENTIC_RAG_CONFIG': str(restored_config),
                   'PYTHONDONTWRITEBYTECODE': '1'}
            status = subprocess.run([sys.executable, '-m', 'agentic_rag.cli', 'service', 'status'],
                                    cwd=old, env=env, text=True, capture_output=True, timeout=60)
            assert status.returncode == 0, status.stderr
            assert json.loads(status.stdout)['database']['service_ready'] is True
            read = subprocess.run([sys.executable, '-m', 'agentic_rag.cli', 'get', ids['claim0'], '--json'],
                                  cwd=old, env=env, text=True, capture_output=True, timeout=60)
            assert read.returncode == 0 and json.loads(read.stdout)['body'] == 'Legacy claim body 0 ünïcödé', read.stderr
            # Central API launches from the same restored config with old code;
            # authenticate a real scoped read without starting workers/timers.
            central_code = r"""
import json, os
from pathlib import Path
from starlette.testclient import TestClient
from agentic_rag.config import load_config
from agentic_rag.service.api import create_app
from agentic_rag.service.auth import hash_key
assert __import__('agentic_rag').__file__.startswith(os.getcwd())
p = Path(os.environ['AGENTIC_RAG_CONFIG']).with_name('restore-policy.toml')
p.write_text('version=1\n[users.operator]\nread_domains=["general"]\nwrite_domains=[]\nread_projects=["/synthetic/team-a"]\nwrite_projects=[]\n[machines.vm]\nuser="operator"\nread_domains=["general"]\nwrite_domains=[]\nread_projects=["/synthetic/team-a"]\nwrite_projects=[]\nkeys={recovery="' + hash_key('recovery.synthetic-recovery-key') + '"}\n')
p.chmod(0o600)
app = create_app(load_config(), p, allowed_hosts=['testserver'])
with TestClient(app, base_url='https://testserver') as client:
    response = client.post('/v1/tools/memory_get', headers={'authorization':'Bearer recovery.synthetic-recovery-key','x-rag-protocol':'1'}, json={'id_or_slug':__import__('sys').argv[1]})
    assert response.status_code == 200, response.text
    assert response.json()['document']['body'] == 'Legacy claim body 0 ünïcödé', response.text
print(json.dumps({'restored_old_service_read': True}))
"""
            central = subprocess.run([sys.executable, '-c', central_code, ids['claim0']], cwd=old, env=env,
                                     text=True, capture_output=True, timeout=60)
            assert central.returncode == 0, central.stderr
            assert json.loads(central.stdout)['restored_old_service_read'] is True
        print('EVIDENCE_PUBLIC_RECOVERY', json.dumps({'digest': True, 'manifest': True,
              'mismatch_rejected': ['grants', 'tables', 'owners', 'sequences'], 'old_cli': True, 'old_api': True}))
    print('EVIDENCE_OPERATOR_CLI', json.dumps({k: v.get('migrations_applied') for k, v in outputs.items()}, sort_keys=True))
