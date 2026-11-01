"""RAG-067 T067-006: populated 0.6.19/schema031 -> 0.6.20/schema032 rehearsal on owned
disposable databases (PG of the test run, never a live store).

The source is written by the actual 0.6.19 code (git archive of main 01bc13b): a
multi-user, multi-domain store with claims, assertions, a pin, a lifecycle decision,
an old pending local mining job and an old accepted but unapplied mining batch.
Proves: interrupted migration and empty retry, verified backup, every original row,
grant, owner and sequence preserved, ev1/src1 unchanged, queue/batch/window rows
untouched by the migration, no provider call by the upgrade, actual 0.6.19 reads and
ordinary writes on schema032, old pending work mined under builtin rules even with a
custom file configured, the old accepted batch applied unchanged without reading the
file, the old-miner bypass that makes the restart gate necessary, an independently
restored post-upgrade backup with bindings and the pre-upgrade restore limit.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from dataclasses import replace

import pytest

from agentic_rag import backup, db, extraction_policy as ep, jobs, llm, mining, store, worker
from agentic_rag.benchmark import extraction_policy as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from agentic_rag.service.schema import ServiceSchemaError, validate_schema
from test_maintenance_restore import owned_source

SOURCE = '01bc13b'  # main at 0.6.19 / schema031 (PR90 merge)
A, B = '/synthetic/team-a', '/synthetic/team-b'

POPULATE = r'''
import json, os, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, evidence, pins, domains, jobs, mining, lifecycle
cfg = load_config()
assert evidence.__file__.startswith(os.getcwd()) and not os.path.exists('agentic_rag/extraction_policy.py')
store.try_embed_texts = lambda *a, **k: None
A, B = '/synthetic/team-a', '/synthetic/team-b'
ids = {}
with db.connect(cfg) as conn:
    for name in ('operations', 'programming'):
        if not conn.execute("SELECT 1 FROM domains WHERE name=%s", (name,)).fetchone():
            domains.add_domain(conn, name)
    for n in range(6):
        domain = ('general', 'programming', 'operations')[n % 3]
        project = (A, B)[n % 2]
        kind = ('stated', 'inference', 'proposal')[n % 3]
        role = 'user' if kind == 'stated' else 'assistant'
        r = store.save_claim(conn, cfg, title=f'Legacy claim {n}', body=f'Legacy claim body {n} ünïcödé',
            domain=domain, dtype='memory', project=project, claim_kind=kind,
            evidence=[{'namespace': f'session:user-{n % 2}', 'source_id': f'event-{n}', 'role': role,
                       'quote': f'Legacy claim body {n} ünïcödé', 'complete': kind == 'stated',
                       'timestamp': '2026-0%d-01T00:00:00Z' % (1 + n % 8)}])
        ids[f'claim{n}'] = r.doc_id
    ids['dup-keep'] = store.save_document(conn, cfg, title='Release checklist', body='Tag, build, publish.', domain='general', dtype='memory', project=A).doc_id
    ids['dup-copy'] = store.save_document(conn, cfg, title='Release checklist', body='Tag, build, publish.', domain='general', dtype='memory', project=A).doc_id
    evidence.review(conn, ids['claim1'], state='confirmed', reason='legacy review')
    ids['fact'] = store.save_assertion(conn, cfg, entity='legacy-service', attribute='port', value='8766', domain='general',
        event_at='2026-01-01T00:00:00Z', project=A, evidence={'source_id': 'port-8766', 'role': 'user', 'quote': 'legacy-service port 8766'}).doc_id
    pins.add_pin(conn, body='Preserve legacy evidence', scope='global')
    seen = lifecycle.preview(conn, ids['dup-copy'], ids['dup-keep'], operation='exact_duplicate'); conn.rollback()
    store.apply_lifecycle(conn, cfg, member=ids['dup-copy'], target=ids['dup-keep'], operation='exact_duplicate',
        expected_member_version=seen['member']['version'], expected_target_version=seen['target']['version'],
        reason='legacy decision', reviewed=False, actor='cli')
    conn.execute("INSERT INTO service_streams(session_id,owner_namespace,project,last_cursor) VALUES ('s-owner','owner',%s,'c1')", (A,))
    conn.commit()
    # Old pending local job (payload without policy metadata).
    jobs.enqueue_mine(conn, cfg, session_id='old-pending', transcript_path=sys.argv[1], project=A)
    # Old accepted but unapplied batch: provider output accepted, apply interrupted.
    output = json.loads(sys.argv[3])
    def provider(prompt, schema, cfg, **kw):
        events = json.loads(prompt.split('SOURCE EVENTS (consumed fragments only):\n', 1)[1])
        return json.loads(json.dumps(output).replace('r1-e1', events[0]['source_id']).replace('r1-e2', events[1]['source_id']).replace('r1-e3', events[2]['source_id']))
    mining.run_structured = provider
    try:
        mining.mine_session(conn, cfg, session_id='old-accepted', transcript_path=sys.argv[2], last_uuid=None, project=A,
                            before_apply=lambda: (_ for _ in ()).throw(RuntimeError('interrupted apply')))
    except RuntimeError:
        pass
print(json.dumps(ids))
'''

OLD_CLIENT = r'''
import json, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, search, evidence_contract
cfg = load_config()
assert not __import__('os').path.exists('agentic_rag/extraction_policy.py')
store.try_embed_texts = search.try_embed_texts = lambda *a, **k: None
ids = json.loads(sys.argv[1])
out = {}
with db.connect(cfg, role='reader') as conn:
    out['get'] = {k: (store.get_document(conn, v) or {}).get('body') for k, v in sorted(ids.items())}
    for q in ('Legacy claim body', 'release checklist'):
        hits, _ = search.search(conn, cfg, q, strategy='lexical', rerank_mode='off', context_mode='off', k=30, project='/synthetic/team-a')
        out[q] = sorted(h.document_id for h in hits)
        conn.rollback()
    out['history'] = sorted(evidence_contract.history(conn, ids['claim1']))
    conn.rollback()
if 'write' in sys.argv[2:]:
    with db.connect(cfg) as conn:
        out['written'] = store.save_claim(conn, cfg, title='Written by 0.6.19 after upgrade', body='Old writer body after upgrade',
            domain='general', dtype='memory', project='/synthetic/team-a', claim_kind='stated',
            evidence=[{'namespace': 'session:old', 'source_id': 'old-1', 'role': 'user',
                       'quote': 'Old writer body after upgrade', 'complete': True}]).doc_id
print(json.dumps(out, default=str))
'''

OLD_MINER = r'''
import json, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, mining, worker
cfg = load_config()
assert not __import__('os').path.exists('agentic_rag/extraction_policy.py')
store.try_embed_texts = lambda *a, **k: None
output = json.loads(sys.argv[2])
calls = []
def provider(prompt, schema, cfg, **kw):
    calls.append(prompt)
    events = json.loads(prompt.split('SOURCE EVENTS (consumed fragments only):\n', 1)[1])
    return json.loads(json.dumps(output).replace('r1-e1', events[0]['source_id']).replace('r1-e2', events[1]['source_id']).replace('r1-e3', events[2]['source_id']))
mining.run_structured = provider
with db.connect(cfg) as conn:
    job = dict(conn.execute("SELECT id,kind,session_id,transcript_path,payload,last_uuid,attempts FROM mining_queue WHERE session_id=%s", (sys.argv[1],)).fetchone())
    conn.commit()
    result = worker.process_job(conn, cfg, {**job, 'attempts': 1})
    batch = conn.execute("SELECT extraction FROM mining_batches WHERE session_id=%s", (sys.argv[1],)).fetchone()['extraction']
    kept = {k: len(v) for k, v in batch.items() if isinstance(v, list) and v}
print(json.dumps({'saved': result.saved, 'kept': kept, 'policy_recorded': '_policy' in batch, 'calls': len(calls),
                  'preferences_in_prompt': any('OPERATOR EXTRACTION PREFERENCES' in p for p in calls)}))
'''


def old_tree(tmp_path):
    root = tmp_path / 'old-0.6.19'
    root.mkdir()
    archive = tmp_path / 'old.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=out, check=True,
                       cwd=Path(__file__).resolve().parents[2])
    with tarfile.open(archive) as content:
        content.extractall(root, filter='data')
    archive.unlink()
    assert 'version = "0.6.19"' in (root / 'pyproject.toml').read_text()
    assert len(list((root / 'sql').glob('*.sql'))) == 31
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
    with db.connect(cfg) as conn:
        docs = {str(r['id']): r['v'] for r in conn.execute('SELECT id, rag_document_version(id) v FROM documents')}
        sources = {r['source_key']: r['v'] for r in conn.execute(
            "SELECT s.source_key, 'src1:'||encode(sha256(convert_to(jsonb_build_array(s.source_key,COALESCE(sr.revision,1),"
            "s.state,s.role,extract(epoch FROM s.source_at))::text,'UTF8')),'hex') v"
            " FROM knowledge_sources s LEFT JOIN source_revisions sr USING(source_key)")}
    return docs, sources


ORIGINAL_TABLES = ('documents', 'chunks', 'claim_records', 'claim_evidence', 'knowledge_sources', 'edges', 'pins',
                   'fact_assertions', 'assertion_sources', 'source_revisions', 'claim_revisions', 'source_history',
                   'claim_history', 'lifecycle_decisions', 'lifecycle_events', 'mining_queue', 'mining_batches',
                   'service_streams', 'service_windows')


def original_rows(cfg, tables=ORIGINAL_TABLES):
    with db.connect(cfg) as conn:
        return {t: conn.execute(f"SELECT count(*) n, md5(COALESCE(string_agg(md5(to_jsonb(x)::text),',' ORDER BY"
                                f" md5(to_jsonb(x)::text)),'')) h FROM {t} x").fetchone() for t in tables}


def restore(cfg, dump, target):
    backup._run_pg([backup._pg_bin('pg_restore', cfg), '--no-owner', '--single-transaction', '--exit-on-error',
                    '-d', db.dsn(target), str(dump)])


class ForbiddenProvider:
    calls = 0

    def __call__(self, *args, **kwargs):
        ForbiddenProvider.calls += 1
        raise AssertionError('no provider call is allowed during the extraction-policy upgrade')


def transcripts(tmp_path):
    case = fx.case('R1')
    return (fx.write_transcript(tmp_path / 'pending.jsonl', case['events']),
            fx.write_transcript(tmp_path / 'accepted.jsonl', case['events']),
            fx.write_transcript(tmp_path / 'new.jsonl', case['events']))


def test_populated_0_6_19_upgrade_old_work_old_code_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(llm, 'run_structured', ForbiddenProvider())
    monkeypatch.setattr(mining, 'run_structured', ForbiddenProvider())
    ForbiddenProvider.calls = 0
    case = fx.case('R1')
    output = json.dumps(case['provider'][0])
    report = {'source_version': '0.6.19', 'source_commit': SOURCE, 'source_schema': 31, 'target_schema': 32}
    old = old_tree(tmp_path)
    pending, accepted, new = transcripts(tmp_path)
    with owned_source(tmp_path, 31) as cfg:
        ids = run_old(old, cfg, tmp_path, POPULATE, pending, accepted, output)
        original = upgrade.inventory(cfg, '0.6.19', identities=True)
        report['original_rows'] = sum(t['rows'] for t in original['tables'].values())
        report['original_tables'] = len(original['tables'])
        before_versions = versions(cfg)
        before_rows = original_rows(cfg)
        assert before_rows['mining_batches']['n'] == 1 and before_rows['mining_queue']['n'] >= 1
        before_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids))
        with db.connect(cfg) as conn:
            with pytest.raises(ServiceSchemaError):
                validate_schema(conn)
        # 1. Interrupted migration: 032 executed, then a crash before commit.
        real_apply = db.apply_migrations

        def crash(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('simulated crash during migration032')
        monkeypatch.setattr(db, 'apply_migrations', crash)
        with pytest.raises(RuntimeError, match='simulated crash'):
            upgrade.local_upgrade(cfg, '0.6.19', tmp_path / 'interrupted.dump', apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT to_regclass('public.extraction_policy_bindings') IS NULL AS absent").fetchone()['absent']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        # 2. Retry with a fresh verified backup, then an empty retry.
        started = time.perf_counter()
        changed = upgrade.local_upgrade(cfg, '0.6.19', tmp_path / 'upgrade.dump', apply=True, writers_stopped=True)
        report['upgrade_seconds'] = round(time.perf_counter() - started, 2)
        assert changed['migrations_applied'] == ['032_extraction_policy.sql']
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert upgrade.verify_preserved(cfg, original)['unchanged']
        retry = upgrade.local_upgrade(cfg, '0.6.19', tmp_path / 'retry.dump', apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        with db.connect(cfg) as conn:
            validate_schema(conn)
            assert conn.execute('SELECT count(*) n FROM extraction_policy_bindings').fetchone()['n'] == 0
        assert versions(cfg) == before_versions and original_rows(cfg) == before_rows
        report['ev1_src1_queue_batches_unchanged_by_migration'] = True
        # 3. Actual 0.6.19 code on schema032: identical reads; ordinary writes work.
        after_old = run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids), 'write')
        written = after_old.pop('written')
        assert after_old == before_old
        report['old_reads_identical_and_old_write'] = True
        # 4. New worker with a custom file: the old pending job keeps builtin rules,
        #    the old accepted batch is applied unchanged without reading the file.
        new_cfg = replace(cfg, mine_policy_file=fx.policy_path('policy-disabled.toml'))
        mock = fx.MockProvider(case['provider'], case['events'])
        monkeypatch.setattr(mining, 'run_structured', mock)
        with db.connect(cfg) as conn:
            job = dict(conn.execute("SELECT id,kind,session_id,transcript_path,payload,last_uuid,attempts FROM mining_queue"
                                    " WHERE session_id='old-pending'").fetchone())
            conn.commit()
            assert 'extraction_policy' not in job['payload']
            legacy = worker.process_job(conn, new_cfg, {**job, 'attempts': 1})
            assert legacy.saved == 3 and mock.calls == 1
            assert conn.execute("SELECT origin FROM extraction_policy_bindings WHERE session_id='old-pending'").fetchone()['origin'] == 'legacy'
            batch_before = dict(conn.execute("SELECT extraction,domains,output_cursor FROM mining_batches WHERE session_id='old-accepted'").fetchone())
            conn.commit()
        monkeypatch.setattr(ep, 'load_file', lambda *a, **k: pytest.fail('an accepted batch wins before reading the file'))
        with db.connect(cfg) as conn:
            applied = mining.mine_session(conn, new_cfg, session_id='old-accepted', transcript_path=accepted,
                                          last_uuid=None, project=A)  # direct call: would resolve the file
            assert applied.saved == 3 and mock.calls == 1
            batch_after = dict(conn.execute("SELECT extraction,domains,output_cursor FROM mining_batches WHERE session_id='old-accepted'").fetchone())
            assert batch_after == batch_before and '_policy' not in batch_after['extraction']
            assert conn.execute("SELECT count(*) n FROM extraction_policy_bindings WHERE session_id='old-accepted'").fetchone()['n'] == 0
            assert conn.execute("SELECT count(*) n FROM documents WHERE provenance->>'session_id'='old-accepted'"
                                " AND provenance ? 'extraction_policy'").fetchone()['n'] == 0
        monkeypatch.undo()
        monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
        monkeypatch.setattr(llm, 'run_structured', ForbiddenProvider())
        report['old_pending_job_builtin'] = True
        report['old_accepted_batch_applied_unchanged_without_file_read'] = True
        # 5. The rollout gate: an actual 0.6.19 miner ignores a captured custom policy.
        custom = replace(cfg, mine_policy_file=fx.policy_path('policy-a.toml'))
        with db.connect(cfg) as conn:
            assert jobs.enqueue_mine(conn, custom, session_id='new-captured', transcript_path=new, project=A)
        bypass = run_old(old, cfg, tmp_path, OLD_MINER, 'new-captured', output)
        # Policy A disables lessons and signals for programming; the old miner keeps them.
        assert bypass['kept'] == {'memories': 1, 'lessons': 1, 'signals': 1} and bypass['saved'] == 3
        assert not bypass['preferences_in_prompt'] and not bypass['policy_recorded'] and bypass['calls'] == 1
        # Actual 0.6.19 readers with bindings and RAG-067 batches present: unchanged answers.
        assert run_old(old, cfg, tmp_path, OLD_CLIENT, json.dumps(ids)) == before_old
        report['old_reads_identical_after_bindings'] = True
        report['old_miner_bypasses_custom_policy'] = {'retained_disabled_categories': 2,
                                                      'verdict': 'stop or upgrade every old miner before activation'}
        # 6. Verified post-upgrade backup with bindings, independently restored.
        proof = upgrade.verified_backup(cfg, '0.6.19', tmp_path / 'current.dump')
        assert proof['restore_verified']
        with isolated_database(cfg, initialize=False) as target:
            restore(cfg, tmp_path / 'current.dump', target)
            with db.connect(target) as conn:
                validate_schema(conn)
                assert conn.execute('SELECT count(*) n FROM extraction_policy_bindings').fetchone()['n'] == 1
                assert conn.execute("SELECT count(*) n FROM pg_trigger WHERE tgname='extraction_policy_binding_immutable'").fetchone()['n'] == 1
        report['post_upgrade_restore_keeps_bindings'] = True
        # 7. Pre-upgrade restore: schema031 for retained 0.6.19 code; later writes are lost.
        manifest = changed['manifest']
        upgrade.check_dump(tmp_path / 'upgrade.dump', manifest)
        with isolated_database(cfg, initialize=False) as target:
            restore(cfg, tmp_path / 'upgrade.dump', target)
            with db.connect(target) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                assert upgrade._verify(conn, manifest, label='restore_mismatch')['unchanged']
                assert conn.execute("SELECT to_regclass('public.extraction_policy_bindings') IS NULL AS absent").fetchone()['absent']
                lost = conn.execute('SELECT count(*) n FROM documents WHERE id=%s', (written,)).fetchone()['n']
            assert run_old(old, target, tmp_path, OLD_CLIENT, json.dumps(ids)) == before_old
        assert lost == 0
        report['post_upgrade_writes_lost_on_pre_upgrade_restore'] = True
    assert ForbiddenProvider.calls == 0
    report['upgrade_provider_calls'] = ForbiddenProvider.calls
    print('EXTRACTION_POLICY_UPGRADE', json.dumps(report, sort_keys=True))
    if os.environ.get('RAG067_EVIDENCE'):
        Path(os.environ['RAG067_EVIDENCE']).write_text(json.dumps(report, indent=1, sort_keys=True))
