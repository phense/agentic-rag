"""RAG-065 T065-005: populated 0.6.17/schema029 -> 0.6.18/schema030 rehearsal on
owned disposable databases (PG of the test run, never a live store).

The source is written by the actual 0.6.17 code (git archive of main 81beaf6).
Proves: interrupted migration and retry, verified backup, every original row,
grant, owner and sequence preserved, no synthesis/provider activity from the
upgrade or ordinary work, actual old-code reads and writes on the new schema,
new central startup and old central reads, accepted-job recovery across a
verified backup/restore, and the explicit pre-upgrade restoration limit.

Once a pattern exists, a code-only return to 0.6.17 is a FORBIDDEN boundary: the
test shows that a disabled pattern stays withheld on 0.6.18 but is exposed by
the old direct get, evidence and history paths. The supported rollback is the
verified pre-upgrade dump restored for retained 0.6.17 code (step 9).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import pytest

from agentic_rag import backup, db, llm, store, worker
from agentic_rag import evidence_contract as contract
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from agentic_rag.service.schema import ServiceSchemaError, validate_schema
from test_maintenance_restore import owned_source

SOURCE = '81beaf6'  # main at 0.6.17 / schema029 (PR87 merge)
K1 = [d for d in fx.load('corpus.json')['documents'] if d['case'] == 'K1']

POPULATE = r'''
import json, os
from agentic_rag.config import load_config
from agentic_rag import db, store, evidence, pins, domains, search
cfg = load_config()
assert evidence.__file__.startswith(os.getcwd()) and not os.path.exists('agentic_rag/synthesis.py')
store.try_embed_texts = lambda *a, **k: None
k1 = json.loads(os.environ['RAG_K1'])
created = {}
with db.connect(cfg) as conn:
    for name in ('alpha', 'programming'):
        if not conn.execute("SELECT 1 FROM domains WHERE name=%s", (name,)).fetchone():
            domains.add_domain(conn, name)
    for d in k1:
        r = store.save_claim(conn, cfg, title=d['title'], body=d['body'], domain='general', dtype='memory',
                             project='/synthetic/team-a', claim_kind='stated', evidence=[d['sources'][0]])
        created[d['key']] = r.doc_id
    for n in range(9):
        domain = ('general', 'programming', 'alpha')[n % 3]
        project = ('/synthetic/team-a', '/synthetic/team-b')[n % 2]
        kind = ('stated', 'inference', 'proposal')[n % 3]
        role = 'user' if kind == 'stated' else 'assistant'
        r = store.save_claim(conn, cfg, title=f'Legacy claim {n}', body=f'Legacy claim body {n} ünïcödé',
            domain=domain, dtype='memory', project=project, claim_kind=kind,
            evidence=[{'namespace': f'session:user-{n % 2}', 'source_id': f'event-{n}', 'role': role,
                       'quote': f'Legacy claim body {n} ünïcödé', 'complete': kind == 'stated',
                       'timestamp': '2026-0%d-01T00:00:00Z' % (1 + n % 8)},
                      {'namespace': 'session:shared', 'source_id': f'shared-{n % 3}', 'role': 'user',
                       'quote': f'Shared legacy statement {n % 3}', 'complete': True,
                       'timestamp': '2026-02-0%dT00:00:00Z' % (1 + n % 3)}])
        created[f'claim{n}'] = r.doc_id
    evidence.review(conn, created['claim1'], state='confirmed', reason='legacy review')
    evidence.review(conn, created['claim2'], state='refuted', reason='legacy refutation')
    keys = [r['source_key'] for r in conn.execute("SELECT source_key FROM knowledge_sources ORDER BY source_key")]
    store.set_source_state(conn, keys[0], state='removed', reason='legacy withdrawal')
    store.set_source_state(conn, keys[0], state='active', reason='legacy reinstatement')
    for i, (value, when, rel) in enumerate([('8766', '2026-01-01T00:00:00Z', 'assertion'),
                                            ('8767', '2026-02-01T00:00:00Z', 'replacement')]):
        r = store.save_assertion(conn, cfg, entity='legacy-service', attribute='port', value=value, domain='general',
            event_at=when, relation=rel, project='/synthetic/team-a',
            evidence={'source_id': 'port-' + value, 'role': 'user', 'quote': 'legacy-service port ' + value})
        created[f'fact{i}'] = r.doc_id
    created['legacy'] = store.save_document(conn, cfg, title='Unmanaged legacy note', body='Legacy note without evidence',
        domain='general', dtype='memory', project='/synthetic/team-a').doc_id
    pins.add_pin(conn, body='Preserve legacy evidence', scope='global')
    for owner in ('owner-a', 'owner-b'):
        conn.execute("INSERT INTO service_streams(session_id,owner_namespace,project,last_cursor) VALUES (%s,%s,'/synthetic/team-a','c1')", ('s-' + owner, owner))
    conn.commit()
print(json.dumps(created))
'''

OLD_CLIENT = r'''
import json, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, search
cfg = load_config()
assert not __import__('os').path.exists('agentic_rag/synthesis.py')
store.try_embed_texts = search.try_embed_texts = lambda *a, **k: None
ids = json.loads(sys.argv[1])
out = {}
with db.connect(cfg, role='reader') as conn:
    out['get'] = {k: (store.get_document(conn, v) or {}).get('body') for k, v in sorted(ids.items())}
    out['claims'] = {k: (store.get_document(conn, v) or {}).get('claim_evidence') for k, v in sorted(ids.items())}
    for q in ('VPN reconnect DNS suffix', 'Legacy claim body'):
        hits, _ = search.search(conn, cfg, q, strategy='lexical', rerank_mode='off', context_mode='off', k=30,
                                project='/synthetic/team-a')
        out[q] = sorted(h.document_id for h in hits)
        conn.rollback()
if len(sys.argv) > 2:
    with db.connect(cfg) as conn:
        r = store.save_claim(conn, cfg, title='Written by 0.6.17 after upgrade', body='Old writer body after upgrade',
                             domain='general', dtype='memory', project='/synthetic/team-a', claim_kind='stated',
                             evidence=[{'namespace': 'session:old', 'source_id': 'old-1', 'role': 'user',
                                        'quote': 'Old writer body after upgrade', 'complete': True}])
        out['written'] = r.doc_id
if 'pattern' in ids:  # the old direct evidence and history paths have no pattern guard
    from agentic_rag import evidence_contract
    with db.connect(cfg, role='reader') as conn:
        ev = evidence_contract.inspect(conn, ids['pattern'])
        out['evidence_pattern'] = {'kind': ev['claim']['kind'], 'sources': len(ev['sources']['items'])}
        out['history_pattern'] = sorted(evidence_contract.history(conn, ids['pattern']))
        conn.rollback()
print(json.dumps(out, default=str))
'''


def old_tree(tmp_path):
    root = tmp_path / 'old-0.6.17'
    root.mkdir()
    archive = tmp_path / 'old.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=out, check=True,
                       cwd=Path(__file__).resolve().parents[2])
    with tarfile.open(archive) as content:
        content.extractall(root, filter='data')
    archive.unlink()
    assert 'version = "0.6.17"' in (root / 'pyproject.toml').read_text()
    return root


def run_old(root, cfg, tmp_path, code, *args, env=None):
    config = tmp_path / 'old.toml'
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n')
    environment = {**os.environ, 'PYTHONPATH': str(root), 'AGENTIC_RAG_CONFIG': str(config),
                   'PYTHONDONTWRITEBYTECODE': '1', **(env or {})}
    result = subprocess.run([sys.executable, '-c', code, *args], cwd=root, env=environment, text=True,
                            capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def synthesis_counts(cfg):
    with db.connect(cfg) as conn:
        row = conn.execute("""SELECT (SELECT count(*) FROM synthesis_policies) policies,
            (SELECT count(*) FROM synthesis_backfills) backfills, (SELECT count(*) FROM synthesis_runs) runs,
            (SELECT count(*) FROM synthesis_processed) processed,
            (SELECT count(*) FROM synthesis_patterns) patterns, (SELECT count(*) FROM synthesis_dependencies) deps,
            (SELECT count(*) FROM mining_queue WHERE kind='synthesis') jobs,
            (SELECT count(*) FROM audit_log WHERE op LIKE 'synthesis%%') audits""").fetchone()
        return dict(row)


def test_populated_0_6_17_upgrade_retry_old_code_recovery_and_restore_limits(tmp_path, monkeypatch):
    from dataclasses import replace
    from agentic_rag import synthesis
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest', lambda cfg: 'a' * 64)
    report = {'source_version': '0.6.17', 'source_commit': SOURCE, 'source_schema': 29, 'target_schema': 30}
    forbidden = fx.ForbiddenProvider()
    fx.ForbiddenProvider.calls = 0
    monkeypatch.setattr(llm, 'run_structured', forbidden)
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 29) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE, env={'RAG_K1': json.dumps(K1)})
        original = upgrade.inventory(cfg, '0.6.17', identities=True)
        report['original_rows'] = sum(t['rows'] for t in original['tables'].values())
        report['original_tables'] = len(original['tables'])
        for table in ('documents', 'claim_records', 'claim_evidence', 'knowledge_sources', 'audit_log',
                      'source_history', 'claim_history', 'pins', 'service_streams'):
            report[table] = original['tables'][table]['rows']
        before_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids))
        # New service code refuses schema029 before the upgrade.
        with db.connect(cfg) as conn:
            with pytest.raises(ServiceSchemaError):
                validate_schema(conn)
        # 1. Interrupted migration: 030 executed, then a crash before commit.
        real_apply = db.apply_migrations

        def crash(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('simulated crash during migration030')
        monkeypatch.setattr(db, 'apply_migrations', crash)
        with pytest.raises(RuntimeError, match='simulated crash'):
            upgrade.local_upgrade(cfg, '0.6.17', tmp_path / 'interrupted.dump', apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT to_regclass('public.synthesis_policies') IS NULL AS absent").fetchone()['absent']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        # 2. Retry with a fresh verified backup.
        started = time.perf_counter()
        changed = upgrade.local_upgrade(cfg, '0.6.17', tmp_path / 'upgrade.dump', apply=True, writers_stopped=True)
        report['upgrade_seconds'] = round(time.perf_counter() - started, 2)
        assert changed['migrations_applied'] == ['030_pattern_synthesis.sql','031_memory_lifecycle.sql','032_extraction_policy.sql']
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        retry = upgrade.local_upgrade(cfg, '0.6.17', tmp_path / 'retry.dump', apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        with db.connect(cfg) as conn:
            validate_schema(conn)
        # 3. Upgrade plus ordinary worker ticks (switch off, then on without policy): no synthesis.
        on = replace(cfg, synthesis_enabled=True)
        with db.connect(cfg, role='writer') as conn:
            worker._schedule_synthesis(conn, cfg)
            worker.drain(conn, cfg)
            worker._schedule_synthesis(conn, on)
        assert synthesis_counts(cfg) == dict.fromkeys(synthesis_counts(cfg), 0)
        assert fx.ForbiddenProvider.calls == 0
        report['synthesis_after_upgrade'] = synthesis_counts(cfg)
        # 4. Actual 0.6.17 code on the new schema: identical reads; its writes still work.
        after_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids), 'write')
        written = after_old.pop('written')
        assert after_old == before_old
        report['old_reads_identical'] = True
        # 5. New code opts in, accepts work and parks it after an injected apply failure.
        provider = fx.ScriptedProvider('K1')
        monkeypatch.setattr(llm, 'run_structured', provider)
        with db.connect(cfg) as conn:
            policy = store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='rehearsal',
                                                project='/synthetic/team-a')
            from datetime import datetime, timedelta
            end = datetime.fromisoformat(policy['forward_from'])
            store.request_synthesis_backfill(conn, on, domain='general', project='/synthetic/team-a',
                                             reason='rehearsal history', start=(end - timedelta(days=30)).isoformat(),
                                             end=policy['forward_from'])
            preview = synthesis.preview(conn, on, domain='general', project='/synthetic/team-a')
            report['preview'] = {k: preview['candidates'][k] for k in ('memories', 'independent_events', 'sufficient')}
            report['preview_excluded'] = {k: v for k, v in preview['excluded'].items() if v}
            synthesis.schedule(conn, on)
            real = synthesis._register
            monkeypatch.setattr(synthesis, '_register', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('stop')))
            worker.drain(conn, on)
            monkeypatch.setattr(synthesis, '_register', real)
            run = conn.execute('SELECT id,state,accepted IS NOT NULL accepted FROM synthesis_runs').fetchone()
            conn.commit()
        assert run['state'] == 'accepted' and run['accepted'] and len(provider.calls) == 1
        # 6. A verified backup carries the accepted run; recovery on the restored copy
        #    applies it without a second provider call.
        proof = upgrade.verified_backup(cfg, '0.6.17', tmp_path / 'accepted.dump')
        assert proof['restore_verified']
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(tmp_path / 'accepted.dump')])
            restored = replace(target, synthesis_enabled=True)
            with db.connect(restored) as conn:
                conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'")
                conn.commit()  # the source job exhausted its attempts before the dump was restored
                synthesis.schedule(conn, restored)
                assert conn.execute('SELECT state,code FROM synthesis_runs').fetchone() == {'state': 'error',
                                                                                            'code': 'apply_failed'}
                conn.commit()
                store.recover_synthesis_run(conn, restored, str(run['id']), reason='restored copy recovery')
                worker.drain(conn, restored)
                pattern = conn.execute('SELECT document_id FROM synthesis_patterns').fetchone()
                assert pattern and conn.execute('SELECT rag_pattern_current(%s) ok', (pattern['document_id'],)).fetchone()['ok']
                report['restored_recovery_patterns'] = conn.execute('SELECT count(*) n FROM synthesis_patterns').fetchone()['n']
            assert len(provider.calls) == 1
        # 7. On the source, recovery applies it; versions and the guard survive dump/restore.
        with db.connect(cfg) as conn:
            conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'")
            conn.commit()
            synthesis.schedule(conn, on)
            store.recover_synthesis_run(conn, on, str(run['id']), reason='source recovery')
            worker.drain(conn, on)
            pattern = str(conn.execute('SELECT document_id FROM synthesis_patterns').fetchone()['document_id'])
            conn.commit()
        assert len(provider.calls) == 1
        report['provider_calls_total'] = len(provider.calls)
        after_dump = upgrade.verified_backup(cfg, '0.6.17', tmp_path / 'after.dump')
        assert after_dump['restore_verified']
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(tmp_path / 'after.dump')])
            with db.connect(target) as conn:
                assert conn.execute('SELECT rag_pattern_current(%s) ok', (pattern,)).fetchone()['ok']
                assert contract.document_version(conn, ids['k1-a']) == run_versions(cfg, ids['k1-a'])
        # 8. Patterns exist: code-only rollback to 0.6.17 is forbidden. The operator's
        #    disable (new code) withholds the pattern on 0.6.18, but actual 0.6.17 code
        #    still serves it through direct get, evidence and history; only ordinary
        #    search stays guarded by the SQL predicate.
        with db.connect(cfg) as conn:
            store.set_synthesis_policy(conn, on, domain='general', enabled=False, reason='rollback attempt',
                                       project='/synthetic/team-a')
        with db.connect(cfg, role='reader') as conn:
            assert synthesis.withheld(conn, pattern) and store.get_document(conn, pattern) is None
            with pytest.raises(contract.EvidenceUnavailable):
                contract.inspect(conn, pattern)
            conn.rollback()
        old_view = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps({**ids, 'pattern': pattern}))
        assert pattern not in old_view['VPN reconnect DNS suffix']
        assert old_view['get']['pattern'].startswith('Inferred pattern suggestion')
        assert old_view['claims']['pattern']['kind'] == 'inference'
        assert old_view['evidence_pattern'] == {'kind': 'inference', 'sources': 4}
        assert old_view['history_pattern']
        report['code_only_rollback_after_patterns'] = {
            'verdict': 'forbidden', 'new_code_withholds_disabled_pattern': True,
            'old_get_exposes_body': True, 'old_evidence_exposes_pattern': True, 'old_history_answers': True,
            'old_search_guarded': True}
        # 9. Supported rollback: the verified pre-upgrade dump restored for retained 0.6.17
        #    code. Schema029, old reads equal, every 0.6.18 write (patterns included) lost.
        manifest = changed['manifest']
        upgrade.check_dump(tmp_path / 'upgrade.dump', manifest)
        with isolated_database(cfg, initialize=False) as target:
            backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                            '-d', db.dsn(target), str(tmp_path / 'upgrade.dump')])
            with db.connect(target) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                assert upgrade._verify(conn, manifest, label='restore_mismatch')['unchanged']
                assert conn.execute("SELECT to_regclass('public.synthesis_policies') IS NULL AS absent").fetchone()['absent']
                lost = conn.execute('SELECT count(*) n FROM documents WHERE id=%s OR id=%s', (written, pattern)).fetchone()['n']
            assert run_old(old, target, tmp_path, OLD_CLIENT, json.dumps(ids)) == before_old
        report['post_upgrade_writes_lost_on_pre_upgrade_restore'] = lost == 0
        assert lost == 0
    print('SYNTHESIS_UPGRADE', json.dumps(report, sort_keys=True))
    if os.environ.get('RAG065_EVIDENCE'):
        Path(os.environ['RAG065_EVIDENCE']).write_text(json.dumps(report, indent=1, sort_keys=True))


def run_versions(cfg, doc_id):
    with db.connect(cfg, role='reader') as conn:
        return contract.document_version(conn, doc_id)


def test_operator_cli_and_central_service_on_populated_0_6_17(tmp_path, monkeypatch, capsys):
    """The exact PB-065-OPS upgrade commands, then old and new central services."""
    from agentic_rag import cli
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest', lambda cfg: 'a' * 64)
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 29) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE, env={'RAG_K1': json.dumps(K1)})
        config = tmp_path / 'operator.toml'
        config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n'
                          f'[backup]\nlocal_dir = "{tmp_path / "dumps"}"\n')
        outputs = {}
        for name, argv in [
            ('inventory', ['inventory', '--source-version', '0.6.17', '--identities', '--output',
                           str(tmp_path / 'upgrade' / 'inventory.json')]),
            ('preflight', ['preflight', '--source-version', '0.6.17', '--mode', 'local']),
            ('plan', ['upgrade', '--source-version', '0.6.17', '--dump', str(tmp_path / 'upgrade' / 'plan.dump')]),
            ('upgrade', ['upgrade', '--source-version', '0.6.17', '--dump', str(tmp_path / 'upgrade' / 'synthesis030.dump'),
                         '--apply', '--writers-stopped']),
            ('retry', ['upgrade', '--source-version', '0.6.17', '--dump', str(tmp_path / 'upgrade' / 'retry.dump'),
                       '--apply', '--writers-stopped']),
            ('status', ['status']),
        ]:
            assert cli.main(['service', '--config', str(config), *argv]) == 0, capsys.readouterr().err
            outputs[name] = json.loads(capsys.readouterr().out)
        assert outputs['preflight']['ready'] and outputs['preflight']['inventory']['supported']
        assert outputs['plan']['applied'] is False
        assert outputs['upgrade']['migrations_applied'] == ['030_pattern_synthesis.sql','031_memory_lifecycle.sql','032_extraction_policy.sql']
        assert outputs['upgrade']['restore_verified'] and outputs['upgrade']['original_rows_unchanged']
        assert outputs['retry']['migrations_applied'] == []
        assert synthesis_counts(cfg) == dict.fromkeys(synthesis_counts(cfg), 0)
        # Unsupported labels stay refused; the actual target version is not a source.
        assert cli.main(['service', '--config', str(config), 'preflight', '--source-version', '0.6.21',
                         '--mode', 'local']) == 1
        capsys.readouterr()
        # Old 0.6.17 central API on the upgraded schema serves a scoped read.
        central_code = r"""
import json, os, sys
from pathlib import Path
from starlette.testclient import TestClient
from agentic_rag.config import load_config
from agentic_rag.service.api import create_app
from agentic_rag.service.auth import hash_key
assert not os.path.exists('agentic_rag/synthesis.py')
p = Path(os.environ['AGENTIC_RAG_CONFIG']).with_name('policy.toml')
p.write_text('version=1\n[users.operator]\nread_domains=["general"]\nwrite_domains=[]\nread_projects=["/synthetic/team-a"]\nwrite_projects=[]\n[machines.vm]\nuser="operator"\nread_domains=["general"]\nwrite_domains=[]\nread_projects=["/synthetic/team-a"]\nwrite_projects=[]\nkeys={recovery="' + hash_key('recovery.synthetic-recovery-key') + '"}\n')
p.chmod(0o600)
app = create_app(load_config(), p, allowed_hosts=['testserver'])
with TestClient(app, base_url='https://testserver') as client:
    r = client.post('/v1/tools/memory_get', headers={'authorization':'Bearer recovery.synthetic-recovery-key','x-rag-protocol':'1'}, json={'id_or_slug':sys.argv[1]})
    assert r.status_code == 200, r.text
    unknown = client.post('/v1/tools/memory_pattern_status', headers={'authorization':'Bearer recovery.synthetic-recovery-key','x-rag-protocol':'1'}, json={})
print(json.dumps({'body': r.json()['document']['body'], 'pattern_tool_status': unknown.status_code}))
"""
        env = {**os.environ, 'PYTHONPATH': str(old), 'AGENTIC_RAG_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
        central = subprocess.run([sys.executable, '-c', central_code, ids['k1-a']], cwd=old, env=env, text=True,
                                 capture_output=True, timeout=90)
        assert central.returncode == 0, central.stderr[-2000:]
        old_central = json.loads(central.stdout.strip().splitlines()[-1])
        assert old_central == {'body': K1[0]['body'], 'pattern_tool_status': 404}
        # New central startup validates schema030 and serves the pattern tools read-only.
        from starlette.testclient import TestClient
        from agentic_rag.service.api import create_app
        from .test_api import headers, KEYS
        from .test_auth import policy_file
        app = create_app(cfg, policy_file(tmp_path), allowed_hosts=['testserver'])
        with TestClient(app, base_url='https://testserver') as client:
            r = client.post('/v1/tools/memory_pattern_status', headers=headers(KEYS[1]), json={})
            assert r.status_code == 200 and r.json()['policies'] == []
    print('SYNTHESIS_OPERATOR_CLI', json.dumps({k: v.get('migrations_applied') for k, v in outputs.items()}, sort_keys=True))
