"""RAG-066 T066-007: populated 0.6.18/schema030 -> 0.6.19/schema031 rehearsal on owned
disposable databases (PG of the test run, never a live store).

The source is written by the actual 0.6.18 code (git archive of main d4d2372).
Proves: interrupted migration and empty retry, verified backup, every original
row, grant, owner and sequence preserved, ev1/src1 of every document and source
unchanged by the migration and by lifecycle decisions, no decision/provider call
from the upgrade, actual 0.6.18 reads/get/history/ordinary writes before and after
the first decision, the old automatic curation limit (it still archives a
differently titled pair) and its supported fallback curation_budget=0, an
independently restored verified backup that keeps decisions, and the explicit
pre-upgrade restore limit (later writes are lost).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import pytest

from agentic_rag import backup, db, lifecycle, llm, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from agentic_rag.service.schema import ServiceSchemaError, validate_schema
from test_maintenance_restore import owned_source

SOURCE = 'd4d2372'  # main at 0.6.18 / schema030 (PR88 merge)
A, B = '/synthetic/team-a', '/synthetic/team-b'

POPULATE = r'''
import json, os
from agentic_rag.config import load_config
from agentic_rag import db, store, evidence, pins, domains
cfg = load_config()
assert evidence.__file__.startswith(os.getcwd()) and not os.path.exists('agentic_rag/lifecycle.py')
store.try_embed_texts = lambda *a, **k: None
A, B = '/synthetic/team-a', '/synthetic/team-b'
ids = {}
def memory(key, title, body, domain='general', project=A, dtype='memory'):
    ids[key] = store.save_document(conn, cfg, title=title, body=body, domain=domain, dtype=dtype, project=project).doc_id
with db.connect(cfg) as conn:
    for name in ('alpha', 'programming'):
        if not conn.execute("SELECT 1 FROM domains WHERE name=%s", (name,)).fetchone():
            domains.add_domain(conn, name)
    memory('dup-keep', 'Release checklist', 'Tag the release, build the wheel, then publish the changelog.')
    memory('dup-copy', 'Release checklist', 'Tag the release, build the wheel, then publish the changelog.')
    memory('alpha-port', 'Build server alpha port', 'The service listens on port 8443.')
    memory('beta-port', 'Build server beta port', 'The service listens on port 8443.')
    memory('short', 'Printer P1 toner', 'Printer P1 uses toner TN-243.')
    memory('rich', 'Printer P1 toner and drum', 'Printer P1 uses toner TN-243 and drum DR-243.')
    memory('team-b-copy', 'Release checklist', 'Tag the release, build the wheel, then publish the changelog.', project=B)
    memory('programming', 'Lint command', 'Run ruff check before every commit.', domain='programming')
    memory('alpha-domain', 'Alpha runbook', 'Alpha runbook body ünïcödé.', domain='alpha', project=B)
    for n in range(6):
        domain = ('general', 'programming', 'alpha')[n % 3]
        project = (A, B)[n % 2]
        kind = ('stated', 'inference', 'proposal')[n % 3]
        role = 'user' if kind == 'stated' else 'assistant'
        r = store.save_claim(conn, cfg, title=f'Legacy claim {n}', body=f'Legacy claim body {n} ünïcödé',
            domain=domain, dtype='memory', project=project, claim_kind=kind,
            evidence=[{'namespace': f'session:user-{n % 2}', 'source_id': f'event-{n}', 'role': role,
                       'quote': f'Legacy claim body {n} ünïcödé', 'complete': kind == 'stated',
                       'timestamp': '2026-0%d-01T00:00:00Z' % (1 + n % 8)}])
        ids[f'claim{n}'] = r.doc_id
    evidence.review(conn, ids['claim1'], state='confirmed', reason='legacy review')
    keys = [r['source_key'] for r in conn.execute("SELECT source_key FROM knowledge_sources ORDER BY source_key")]
    store.set_source_state(conn, keys[0], state='removed', reason='legacy withdrawal')
    store.set_source_state(conn, keys[0], state='active', reason='legacy reinstatement')
    for i, (value, when, rel) in enumerate([('8766', '2026-01-01T00:00:00Z', 'assertion'),
                                            ('8767', '2026-02-01T00:00:00Z', 'replacement')]):
        ids[f'fact{i}'] = store.save_assertion(conn, cfg, entity='legacy-service', attribute='port', value=value,
            domain='general', event_at=when, relation=rel, project=A,
            evidence={'source_id': 'port-' + value, 'role': 'user', 'quote': 'legacy-service port ' + value}).doc_id
    pins.add_pin(conn, body='Preserve legacy evidence', scope='global')
    for owner in ('owner-a', 'owner-b'):
        conn.execute("INSERT INTO service_streams(session_id,owner_namespace,project,last_cursor) VALUES (%s,%s,%s,'c1')",
                     ('s-' + owner, owner, A))
    conn.commit()
print(json.dumps(ids))
'''

OLD_CLIENT = r'''
import json, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, search, evidence_contract, graph
cfg = load_config()
assert not __import__('os').path.exists('agentic_rag/lifecycle.py')
store.try_embed_texts = search.try_embed_texts = lambda *a, **k: None
ids = json.loads(sys.argv[1])
out = {}
with db.connect(cfg, role='reader') as conn:
    out['get'] = {k: (store.get_document(conn, v) or {}).get('body') for k, v in sorted(ids.items())}
    out['claims'] = {k: (store.get_document(conn, v) or {}).get('claim_evidence') for k, v in sorted(ids.items())}
    for q in ('release wheel changelog', 'Printer toner', 'port 8443', 'Legacy claim body'):
        hits, _ = search.search(conn, cfg, q, strategy='lexical', rerank_mode='off', context_mode='off', k=30, project='/synthetic/team-a')
        out[q] = sorted(h.document_id for h in hits)
        conn.rollback()
    out['history'] = sorted(evidence_contract.history(conn, ids['claim1']))
    out['neighbors'] = len(graph.neighbors(conn, ids['dup-keep']))
    conn.rollback()
for arg in sys.argv[2:]:
    with db.connect(cfg) as conn:
        if arg == 'write':
            out['written'] = store.save_claim(conn, cfg, title='Written by 0.6.18 after upgrade', body='Old writer body after upgrade',
                domain='general', dtype='memory', project='/synthetic/team-a', claim_kind='stated',
                evidence=[{'namespace': 'session:old', 'source_id': 'old-1', 'role': 'user',
                           'quote': 'Old writer body after upgrade', 'complete': True}]).doc_id
        elif arg.startswith('edit:'):
            doc = store.get_document(conn, arg[5:])
            for body in ('Old writer edit in progress', doc['body']):  # content ABA by an old writer
                store.save_document(conn, cfg, doc_id=arg[5:], title=doc['title'], body=body, domain=doc['domain'], dtype=doc['dtype'])
            out['edited'] = arg[5:]
print(json.dumps(out, default=str))
'''

OLD_CURATION = r'''
import json
from agentic_rag.config import load_config
from agentic_rag import db, curation
cfg = load_config()  # the old worker calls curation.run_pass(conn, cfg) with cfg.curation_budget
with db.connect(cfg, role='writer') as conn:
    report = curation.run_pass(conn, cfg, runner=None)
    archived = sorted(str(r['id']) for r in conn.execute("SELECT id FROM documents WHERE status='archived'"))
print(json.dumps({'budget': cfg.curation_budget, 'merged': report.merged, 'archived': archived}))
'''


def old_tree(tmp_path):
    root = tmp_path / 'old-0.6.18'
    root.mkdir()
    archive = tmp_path / 'old.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=out, check=True,
                       cwd=Path(__file__).resolve().parents[2])
    with tarfile.open(archive) as content:
        content.extractall(root, filter='data')
    archive.unlink()
    assert 'version = "0.6.18"' in (root / 'pyproject.toml').read_text()
    assert len(list((root / 'sql').glob('*.sql'))) == 30
    return root


def run_old(root, cfg, tmp_path, code, *args, extra=''):
    config = tmp_path / ('old-%s.toml' % cfg.db_name)
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n{extra}')
    environment = {**os.environ, 'PYTHONPATH': str(root), 'AGENTIC_RAG_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c', code, *args], cwd=root, env=environment, text=True,
                            capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def versions(cfg):
    """ev1 of every document and src1 of every source (same SQL as migration030)."""
    with db.connect(cfg) as conn:
        docs = {str(r['id']): r['v'] for r in conn.execute('SELECT id, rag_document_version(id) v FROM documents')}
        sources = {r['source_key']: r['v'] for r in conn.execute(
            "SELECT s.source_key, 'src1:'||encode(sha256(convert_to(jsonb_build_array(s.source_key,COALESCE(sr.revision,1),"
            "s.state,s.role,extract(epoch FROM s.source_at))::text,'UTF8')),'hex') v"
            " FROM knowledge_sources s LEFT JOIN source_revisions sr USING(source_key)")}
    return docs, sources


ORIGINAL_TABLES = ('documents', 'chunks', 'claim_records', 'claim_evidence', 'knowledge_sources', 'edges', 'pins',
                   'fact_assertions', 'assertion_sources', 'source_revisions', 'claim_revisions', 'source_history',
                   'claim_history', 'service_streams')


def original_rows(cfg):
    """Order-independent hash of every row in the original knowledge tables."""
    with db.connect(cfg) as conn:
        return {t: conn.execute(f"SELECT count(*) n, md5(COALESCE(string_agg(md5(to_jsonb(x)::text),',' ORDER BY"
                                f" md5(to_jsonb(x)::text)),'')) h FROM {t} x").fetchone() for t in ORIGINAL_TABLES}


def lifecycle_counts(cfg):
    with db.connect(cfg) as conn:
        return dict(conn.execute("""SELECT (SELECT count(*) FROM lifecycle_decisions) decisions,
            (SELECT count(*) FROM lifecycle_events) events,
            (SELECT count(*) FROM audit_log WHERE op LIKE 'lifecycle%%') audits""").fetchone())


def restore(cfg, dump, target):
    backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                    '-d', db.dsn(target), str(dump)])


def decide(cfg, member, target, operation, reason):
    with db.connect(cfg) as conn:
        seen = lifecycle.preview(conn, member, target, operation=operation)
        conn.rollback()
        return store.apply_lifecycle(conn, cfg, member=member, target=target, operation=operation,
                                     expected_member_version=seen['member']['version'],
                                     expected_target_version=seen['target']['version'], reason=reason,
                                     reviewed=operation != 'exact_duplicate', actor='cli')


class ForbiddenProvider:
    calls = 0

    def __call__(self, *args, **kwargs):
        ForbiddenProvider.calls += 1
        raise AssertionError('no provider call is allowed during the lifecycle upgrade')


def test_populated_0_6_18_upgrade_old_code_curation_limit_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(llm, 'run_structured', ForbiddenProvider())
    ForbiddenProvider.calls = 0
    report = {'source_version': '0.6.18', 'source_commit': SOURCE, 'source_schema': 30, 'target_schema': 31}
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 30) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE)
        original = upgrade.inventory(cfg, '0.6.18', identities=True)
        report['original_rows'] = sum(t['rows'] for t in original['tables'].values())
        report['original_tables'] = len(original['tables'])
        report['documents'] = original['tables']['documents']['rows']
        before_versions = versions(cfg)
        before_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids))
        with db.connect(cfg) as conn:
            with pytest.raises(ServiceSchemaError):
                validate_schema(conn)
        # 1. Interrupted migration: 031 executed, then a crash before commit.
        real_apply = db.apply_migrations

        def crash(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('simulated crash during migration031')
        monkeypatch.setattr(db, 'apply_migrations', crash)
        with pytest.raises(RuntimeError, match='simulated crash'):
            upgrade.local_upgrade(cfg, '0.6.18', tmp_path / 'interrupted.dump', apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT to_regclass('public.lifecycle_decisions') IS NULL AS absent").fetchone()['absent']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        # 2. Retry with a fresh verified backup, then an empty retry.
        started = time.perf_counter()
        changed = upgrade.local_upgrade(cfg, '0.6.18', tmp_path / 'upgrade.dump', apply=True, writers_stopped=True)
        report['upgrade_seconds'] = round(time.perf_counter() - started, 2)
        assert changed['migrations_applied'] == ['031_memory_lifecycle.sql', '032_extraction_policy.sql']
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        retry = upgrade.local_upgrade(cfg, '0.6.18', tmp_path / 'retry.dump', apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        with db.connect(cfg) as conn:
            validate_schema(conn)
        assert lifecycle_counts(cfg) == {'decisions': 0, 'events': 0, 'audits': 0}
        assert versions(cfg) == before_versions
        report['ev1_src1_unchanged_by_migration'] = True
        # 3. Actual 0.6.18 code on schema031 with an empty overlay: identical reads; writes work.
        after_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids), 'write')
        written = after_old.pop('written')
        assert after_old == before_old
        report['old_reads_identical_before_decisions'] = True
        # 4. New code applies decisions; untouched ev1/src1 and original rows stay identical.
        rows_before = original_rows(cfg)
        exact = decide(cfg, ids['dup-copy'], ids['dup-keep'], 'exact_duplicate', 'same release checklist')
        extension = decide(cfg, ids['short'], ids['rich'], 'extension', 'rich note covers the short one')
        assert lifecycle_counts(cfg) == {'decisions': 2, 'events': 2, 'audits': 2}
        assert original_rows(cfg) == rows_before
        docs_after, sources_after = versions(cfg)
        assert {k: v for k, v in docs_after.items() if k != written} == before_versions[0]
        assert sources_after.keys() >= before_versions[1].keys()
        assert {k: sources_after[k] for k in before_versions[1]} == before_versions[1]
        report['ev1_src1_unchanged_by_decisions'] = True
        # 5. Actual 0.6.18 readers honor decisions in search (SQL predicate), still
        #    inspect originals by get, answer evidence history and write normally.
        decided_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids), 'write', 'edit:' + ids['short'])
        assert ids['dup-copy'] not in decided_old['release wheel changelog']
        assert ids['dup-keep'] in decided_old['release wheel changelog']
        assert decided_old['get']['dup-copy'] == before_old['get']['dup-copy']
        assert decided_old['history'] == before_old['history']
        report['old_after_decision'] = {'search_hides_member': True, 'get_inspects_original': True,
                                        'history_unchanged': True, 'ordinary_write': True}
        # The old writer's content ABA makes the extension stale: the member is current again.
        with db.connect(cfg, role='reader') as conn:
            assert conn.execute('SELECT assertion_eligible(%s) ok', (ids['short'],)).fetchone()['ok']
            assert lifecycle.detail(conn, ids['short'])['as_member'][0]['relationship'] == 'stale'
            assert not conn.execute('SELECT assertion_eligible(%s) ok', (ids['dup-copy'],)).fetchone()['ok']
        report['old_writer_edit_makes_relationship_stale'] = True
        # 6. Verified backup with decisions, independently restored: overlay and guard survive.
        proof = upgrade.verified_backup(cfg, '0.6.18', tmp_path / 'decided.dump')
        assert proof['restore_verified']
        with isolated_database(cfg, initialize=False) as target:
            restore(cfg, tmp_path / 'decided.dump', target)
            with db.connect(target) as conn:
                validate_schema(conn)
                assert conn.execute('SELECT count(*) n FROM lifecycle_decisions').fetchone()['n'] == 2
                assert not conn.execute('SELECT assertion_eligible(%s) ok', (ids['dup-copy'],)).fetchone()['ok']
                assert conn.execute("SELECT count(*) n FROM pg_trigger WHERE tgname IN"
                                    " ('lifecycle_decision_guard','lifecycle_event_guard','lifecycle_events_append_only')").fetchone()['n'] == 3
            # 7. Old automatic curation cannot enforce the title guard; the supported
            #    old-code fallback is curation_budget=0. Proven on this restored copy.
            fallback = run_old(old, target, tmp_path, OLD_CURATION, extra='\n[curation]\nbudget = 0\n')
            assert fallback == {'budget': 0, 'merged': 0, 'archived': []}
            unsafe = run_old(old, target, tmp_path, OLD_CURATION)
            assert ids['beta-port'] in unsafe['archived'] and unsafe['budget'] == 20
            report['old_curation'] = {'budget_0_archived': 0, 'default_budget_archived_different_title_pair': True,
                                      'verdict': 'old workers and hook launchers must be upgraded and restarted'}
        # 8. New automatic curation on another restored copy archives only identical-title copies.
        with isolated_database(cfg, initialize=False) as target:
            restore(cfg, tmp_path / 'decided.dump', target)
            from agentic_rag import curation
            with db.connect(target, role='writer') as conn:
                curation.run_pass(conn, target, budget=20, runner=None)
                archived = {str(r['id']) for r in conn.execute("SELECT id FROM documents WHERE status='archived'")}
            assert ids['beta-port'] not in archived and ids['alpha-port'] not in archived
            report['new_curation_archived'] = len(archived)
        # 9. Pre-upgrade restore: schema030 for retained 0.6.18 code; every later write is lost.
        manifest = changed['manifest']
        upgrade.check_dump(tmp_path / 'upgrade.dump', manifest)
        with isolated_database(cfg, initialize=False) as target:
            restore(cfg, tmp_path / 'upgrade.dump', target)
            with db.connect(target) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                assert upgrade._verify(conn, manifest, label='restore_mismatch')['unchanged']
                assert conn.execute("SELECT to_regclass('public.lifecycle_decisions') IS NULL AS absent").fetchone()['absent']
                lost = conn.execute('SELECT count(*) n FROM documents WHERE id=%s', (written,)).fetchone()['n']
            assert run_old(old, target, tmp_path, OLD_CLIENT, json.dumps(ids)) == before_old
        assert lost == 0
        report['post_upgrade_writes_lost_on_pre_upgrade_restore'] = True
        assert exact['decision']['id'] != extension['decision']['id']
    assert ForbiddenProvider.calls == 0
    report['provider_calls'] = ForbiddenProvider.calls
    print('LIFECYCLE_UPGRADE', json.dumps(report, sort_keys=True))
    if os.environ.get('RAG066_EVIDENCE'):
        Path(os.environ['RAG066_EVIDENCE']).write_text(json.dumps(report, indent=1, sort_keys=True))


def test_operator_cli_and_old_central_service_on_populated_0_6_18(tmp_path, monkeypatch, capsys):
    """The exact PB-066-OPS upgrade commands, then an actual 0.6.18 central service."""
    from agentic_rag import cli, mcp_server
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    old = old_tree(tmp_path)
    with owned_source(tmp_path, 30) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE)
        config = tmp_path / 'operator.toml'
        config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n'
                          f'[backup]\nlocal_dir = "{tmp_path / "dumps"}"\n')
        outputs = {}
        for name, argv in [
            ('inventory', ['inventory', '--source-version', '0.6.18', '--identities', '--output',
                           str(tmp_path / 'upgrade' / 'inventory.json')]),
            ('preflight', ['preflight', '--source-version', '0.6.18', '--mode', 'local']),
            ('plan', ['upgrade', '--source-version', '0.6.18', '--dump', str(tmp_path / 'upgrade' / 'plan.dump')]),
            ('upgrade', ['upgrade', '--source-version', '0.6.18', '--dump', str(tmp_path / 'upgrade' / 'lifecycle031.dump'),
                         '--apply', '--writers-stopped']),
            ('retry', ['upgrade', '--source-version', '0.6.18', '--dump', str(tmp_path / 'upgrade' / 'retry.dump'),
                       '--apply', '--writers-stopped']),
        ]:
            assert cli.main(['service', '--config', str(config), *argv]) == 0, capsys.readouterr().err
            outputs[name] = json.loads(capsys.readouterr().out)
        assert outputs['preflight']['ready'] and outputs['preflight']['inventory']['supported']
        assert outputs['plan']['applied'] is False
        assert outputs['upgrade']['migrations_applied'] == ['031_memory_lifecycle.sql', '032_extraction_policy.sql']
        assert outputs['upgrade']['restore_verified'] and outputs['upgrade']['original_rows_unchanged']
        assert outputs['retry']['migrations_applied'] == []
        assert lifecycle_counts(cfg) == {'decisions': 0, 'events': 0, 'audits': 0}
        assert cli.main(['service', '--config', str(config), 'preflight', '--source-version', '0.6.20',
                         '--mode', 'local']) == 1
        capsys.readouterr()
        decide(cfg, ids['dup-copy'], ids['dup-keep'], 'exact_duplicate', 'same release checklist')
        # Actual 0.6.18 central API on schema031: a new client's call without view (as
        # wire_arguments sends it) works and honors the decision; an explicit view and the
        # new tools are refused by the old service, never silently ignored.
        plain = mcp_server.wire_arguments('memory_search', {'query': 'release wheel changelog', 'strategy': 'lexical',
                                                            'rerank': 'off', 'project': A, 'view': None, 'temporal': None,
                                                            'reference': None, 'timezone': None})
        explicit = {**plain, 'view': 'current'}
        central_code = r"""
import json, os, sys
from pathlib import Path
from starlette.testclient import TestClient
from agentic_rag.config import load_config
from agentic_rag.service.api import create_app
from agentic_rag.service.auth import hash_key
assert not os.path.exists('agentic_rag/lifecycle.py')
p = Path(os.environ['AGENTIC_RAG_CONFIG']).with_name('policy.toml')
p.write_text('version=1\n[users.operator]\nread_domains=["general"]\nwrite_domains=[]\nread_projects=["/synthetic/team-a"]\nwrite_projects=[]\n[machines.vm]\nuser="operator"\nread_domains=["general"]\nwrite_domains=[]\nread_projects=["/synthetic/team-a"]\nwrite_projects=[]\nkeys={recovery="' + hash_key('recovery.synthetic-recovery-key') + '"}\n')
p.chmod(0o600)
h = {'authorization':'Bearer recovery.synthetic-recovery-key','x-rag-protocol':'1'}
app = create_app(load_config(), p, allowed_hosts=['testserver'])
with TestClient(app, base_url='https://testserver') as client:
    got = client.post('/v1/tools/memory_get', headers=h, json={'id_or_slug':sys.argv[1]})
    plain = client.post('/v1/tools/memory_search', headers=h, json=json.loads(sys.argv[2]))
    explicit = client.post('/v1/tools/memory_search', headers=h, json=json.loads(sys.argv[3]))
    tool = client.post('/v1/tools/memory_lifecycle', headers=h, json={'id_or_slug':sys.argv[1]})
print(json.dumps({'get': got.status_code, 'body': got.json()['document']['body'], 'plain': plain.status_code,
                  'ids': sorted(r['document_id'] for r in plain.json()['results']),
                  'explicit': [explicit.status_code, explicit.json()], 'tool': tool.status_code}))
"""
        env = {**os.environ, 'PYTHONPATH': str(old), 'AGENTIC_RAG_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
        central = subprocess.run([sys.executable, '-c', central_code, ids['dup-copy'], json.dumps(plain), json.dumps(explicit)],
                                 cwd=old, env=env, text=True, capture_output=True, timeout=90)
        assert central.returncode == 0, central.stderr[-2000:]
        old_central = json.loads(central.stdout.strip().splitlines()[-1])
        assert old_central['get'] == 200 and old_central['plain'] == 200 and old_central['tool'] == 404
        assert old_central['ids'] == [ids['dup-keep']]
        assert old_central['explicit'] == [400, {'error': 'invalid_arguments'}]
    print('LIFECYCLE_OPERATOR_CLI', json.dumps({k: v.get('migrations_applied') for k, v in outputs.items()}, sort_keys=True))
