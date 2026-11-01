"""RAG-064 T064-004: populated source0.6.16/schema029 store written by the actual
archived 0.6.16 gateway, read by 0.6.17 with and without temporal options,
then rolled back to the actual 0.6.16 code and configuration-compatible.

No migration, no data rewrite: every public table hash (including scopes,
sources, accounts and audits) is unchanged across new reads and old reads.
"""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from starlette.testclient import TestClient

from agentic_rag import db, mcp_server, search
from agentic_rag.benchmark import temporal_query as fixture
from agentic_rag.benchmark.rerank_evaluation import _snapshot

SOURCE = '8772fbdc3216a4fa5e3abfc0ce9bdd67d1a2c7ca'  # main at 0.6.16, schema029
OPERATIONAL = {'request_traces', 'service_requests', 'service_foreground', 'dashboard_presence'}
KEY = 'five.synthetic-fifth-machine-secret'
R1 = '2026-10-30T10:00:00+01:00'

POPULATE = r'''
import json, os
from pathlib import Path
from agentic_rag import db, store, search
from agentic_rag.config import load_config
from agentic_rag.domains import seed_defaults
from agentic_rag.evidence import sources
assert str(Path(search.__file__).resolve()).startswith(str(Path.cwd()))
assert not (Path.cwd() / 'agentic_rag' / 'temporal.py').exists()
cfg = load_config()
corpus = json.loads(Path(os.environ['RAG_CORPUS']).read_text())
keys = {}
with db.connect(cfg) as conn:
    seed_defaults(conn); conn.commit()
    for d in corpus['documents']:
        if d['kind'] == 'claim':
            saved = store.save_claim(conn, cfg, title=d['title'], body=d['body'], domain='general', dtype='memory',
                project=d['project'], claim_kind=d['claim_kind'], actor='cli', evidence=[dict(namespace='synthetic',
                source_id=s['source_id'], role=s['role'], quote=d['body'], timestamp=s['timestamp'], complete=s['complete'])
                for s in d['sources']])
        elif d['kind'] == 'assertion':
            saved = store.save_assertion(conn, cfg, entity=d['entity'], attribute=d['attribute'], value=d['value'],
                event_at=d['event_at'], expires_at=d['expires_at'], relation=d['relation'], domain='general',
                project=d['project'], evidence={'namespace': 'synthetic', 'source_id': d['key'], 'role': 'user',
                'quote': d['value'], 'event_at': d['event_at']})
            assert saved.disposition == 'accepted'
        else:
            saved = store.save_document(conn, cfg, title=d['title'], body=d['body'], domain='general', dtype='memory',
                project=d['project'], actor='cli')
        keys[d['key']] = saved.doc_id
        for op in d.get('after', ()):
            if op['op'] in ('refute', 'confirm'):
                store.review_claim(conn, saved.doc_id, state={'refute': 'refuted', 'confirm': 'confirmed'}[op['op']],
                                   reason='synthetic fixture review')
            else:
                wanted = d['sources'][op['source']]['source_id']
                key = next(s['source_key'] for s in sources(conn, saved.doc_id) if s['source_id'] == wanted)
                store.set_source_state(conn, key, state='removed', reason='synthetic fixture withdrawal')
    conn.commit()
print(json.dumps(keys))
'''

READ = r'''
import json, os
from dataclasses import asdict, replace
from pathlib import Path
from starlette.testclient import TestClient
from agentic_rag import db, search
from agentic_rag.config import load_config
from agentic_rag.service.api import create_app
assert str(Path(search.__file__).resolve()).startswith(str(Path.cwd()))
cfg = load_config()
queries = json.loads(os.environ['RAG_QUERIES'])
payloads = json.loads(os.environ['RAG_PAYLOADS'])
local = {}
with db.connect(cfg, role='reader') as conn:
    for q in queries:
        hits, warnings = search.search(conn, cfg, q, domain='general', project='/synthetic/team', k=5,
                                       context_mode='off', rerank_mode='off', as_of=os.environ['RAG_AS_OF'])
        local[q] = {'results': [asdict(h) for h in hits], 'warnings': warnings}
        conn.rollback()
server = replace(cfg, service_storage_path=Path(os.environ['RAG_STORAGE']))
app = create_app(server, Path(os.environ['RAG_POLICY']), allowed_hosts=['testserver'])
http = []
with TestClient(app, base_url='https://testserver') as client:
    for p in payloads:
        r = client.post('/v1/tools/memory_search', headers={'authorization': 'Bearer ' + os.environ['RAG_KEY'],
                        'x-rag-protocol': '1'}, json=p)
        http.append({'status': r.status_code, 'body': r.json()})
print(json.dumps({'local': local, 'http': http}, default=str))
'''


def archive(tmp_path):
    target = tmp_path / 'source-0.6.16'
    target.mkdir()
    with (tmp_path / 'source.tar').open('wb') as out:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=out, check=True)
    with tarfile.open(tmp_path / 'source.tar') as content:
        content.extractall(target, filter='data')
    return target


def policy(tmp_path):
    from agentic_rag.service.auth import hash_key
    path = tmp_path / 'principals.toml'
    path.write_text(f'''version = 1
[users.carol]
read_domains = ["general"]
write_domains = []
read_projects = ["/synthetic/team"]
write_projects = []
[machines.vm5]
user = "carol"
read_domains = ["general"]
write_domains = []
read_projects = ["/synthetic/team"]
write_projects = []
keys = {{five = "{hash_key(KEY)}"}}
''')
    path.chmod(0o600)
    return path


def run_old(old, config, code, env, timeout=180):
    environment = {**os.environ, 'PYTHONPATH': str(old), 'AGENTIC_RAG_CONFIG': str(config), **env}
    output = subprocess.check_output([sys.executable, '-c', code], cwd=old, env=environment, text=True,
                                     timeout=timeout)
    return json.loads(output.strip().splitlines()[-1])


def plain(hits):
    return json.loads(json.dumps([asdict(h) for h in hits], default=str))


def test_populated_old_store_new_reads_and_actual_old_code_rollback(conn, cfg, tmp_path, monkeypatch):
    old = archive(tmp_path)
    # 0.6.16 and 0.6.17 share schema029; migration030 (0.6.18) and, since RAG-066,
    # migration031 (0.6.19) and, since RAG-067, migration032 (0.6.20) are purely additive.
    assert set(p.name for p in db.SQL_DIR.iterdir()) - set(p.name for p in (old / 'sql').iterdir()) == {
        '030_pattern_synthesis.sql', '031_memory_lifecycle.sql', '032_extraction_policy.sql', '033_trusted_replacements.sql'}
    config = tmp_path / 'config.toml'
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n[ollama]\nurl = "http://127.0.0.1:1"\n'
                      '[rerank]\nurl = "http://127.0.0.1:1"\n')
    corpus = fixture.FIXTURES / 'ranking-corpus.json'
    fixture.load('ranking-corpus.json')  # frozen hash check
    conn.rollback()
    keys = run_old(old, config, POPULATE, {'RAG_CORPUS': str(corpus)})
    assert len(keys) == 36
    original = _snapshot(conn)
    conn.rollback()
    timed = conn.execute("SELECT count(*) n FROM knowledge_sources WHERE source_at IS NOT NULL").fetchone()['n']
    legacy_rows = conn.execute("SELECT count(*) n FROM documents d WHERE NOT EXISTS (SELECT 1 FROM claim_records c "
                               "WHERE c.document_id=d.id)").fetchone()['n']
    conn.rollback()
    assert timed >= 33 and legacy_rows == 2

    # 0.6.17 reads the store written by 0.6.16: legacy calls equal, opt-in calls interpret.
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: None)
    reader_cfg = replace(cfg, ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    queries = ['nightly backup job failed', 'nightly backup job failed yesterday', 'VPN tunnel dropped',
               'certificate renewal failed']
    new_legacy = {}
    reader = db.connect(reader_cfg, role='reader')
    try:
        for q in queries:
            hits, warnings = search.search(reader, reader_cfg, q, domain='general', project='/synthetic/team', k=5,
                                           context_mode='off', rerank_mode='off', as_of=R1)
            new_legacy[q] = {'results': plain(hits), 'warnings': warnings}
            reader.rollback()
        case = next(c for c in fixture.load('ranking-cases.json')['dev'] if c['id'] == 'RD03')
        filtered, _ = search.search(reader, reader_cfg, case['query'], **fixture.options(case, mode='filter'))
        reader.rollback()
        assert fixture.ranked_keys(filtered, keys) == ['dev-backup-yesterday']
        enabled = replace(reader_cfg, temporal_enabled=True, temporal_timezone='Europe/Berlin')
        preferred, _ = search.search(reader, enabled, 'nightly backup job failed gestern', domain='general',
                                     project='/synthetic/team', k=5, context_mode='off', rerank_mode='off', as_of=R1,
                                     temporal='auto', reference=R1)
        reader.rollback()
        assert fixture.ranked_keys(preferred, keys)[0] == 'dev-backup-yesterday'
    finally:
        reader.close()
    assert _snapshot(conn) == original
    conn.rollback()

    # The actual 0.6.16 code, with a 0.6.17 configuration that enables the feature,
    # still loads, reads identical legacy results and accepts new-client payloads.
    config.write_text(config.read_text() + '\n[temporal]\nenabled = true\ntimezone = "Europe/Berlin"\n')
    base_args = {'query': 'nightly backup job failed', 'domain': 'general', 'k': 5, 'project': None,
                 'scope': None, 'as_of': R1, 'history': False, 'graph_depth': 0, 'strategy': 'auto',
                 'rerank': 'off', 'context': 'off', 'temporal': None, 'reference': None, 'timezone': None}
    unrequested = mcp_server.wire_arguments('memory_search', base_args)
    requested = mcp_server.wire_arguments('memory_search', {**base_args, 'temporal': 'prefer'})
    assert 'temporal' not in unrequested and requested['temporal'] == 'prefer'
    prior = run_old(old, config, READ, {
        'RAG_QUERIES': json.dumps(queries), 'RAG_PAYLOADS': json.dumps([unrequested, requested]),
        'RAG_AS_OF': R1, 'RAG_POLICY': str(policy(tmp_path)), 'RAG_KEY': KEY,
        'RAG_STORAGE': str(tmp_path / 'old-service')})
    assert prior['local'] == new_legacy
    assert prior['http'][0]['status'] == 200
    assert prior['http'][0]['body']['results'] == new_legacy['nightly backup job failed']['results']
    # An old service rejects an explicitly requested new option instead of ignoring it.
    assert prior['http'][1] == {'status': 400, 'body': {'error': 'invalid_arguments'}}
    after = _snapshot(conn)
    conn.rollback()
    assert {name: digest for name, digest in after.items() if name not in OPERATIONAL} == {
        name: digest for name, digest in original.items() if name not in OPERATIONAL}

    # Feature-off configuration rollback on 0.6.17 restores the 0.6.16 result.
    from agentic_rag.config import load_config
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    assert load_config().temporal_enabled is True
    config.write_text(config.read_text().replace('enabled = true', 'enabled = false'))
    restored = mcp_server.memory_search('nightly backup job failed yesterday', domain='general',
                                        project='/synthetic/team', k=5, context='off', rerank='off', as_of=R1)
    assert set(restored) == {'results', 'warnings'}
    assert restored['results'] == prior['local']['nightly backup job failed yesterday']['results']
    final = _snapshot(conn)
    conn.rollback()
    assert {name: digest for name, digest in final.items() if name not in OPERATIONAL} == {
        name: digest for name, digest in original.items() if name not in OPERATIONAL}
    if os.environ.get('RAG064_EVIDENCE'):
        Path(os.environ['RAG064_EVIDENCE']).write_text(json.dumps({
            'source_revision': SOURCE, 'documents': len(keys), 'dated_sources': timed, 'legacy_documents': legacy_rows,
            'old_http_status': [r['status'] for r in prior['http']], 'operational_tables_excluded': sorted(OPERATIONAL),
            'original': original, 'after_new_reads': original, 'after_old_reads': after, 'after_rollback': final},
            indent=1, sort_keys=True))


def test_public_upgrade_accepts_populated_0_6_16_without_schema_change(cfg, tmp_path, monkeypatch):
    """Existing operator workflow must accept the immediate source patch even
    when the target only adds read behavior and has no SQL migration."""
    from agentic_rag import store
    from agentic_rag.benchmark.database import isolated_database
    from agentic_rag.service import upgrade
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    with isolated_database(cfg) as source:
        with db.connect(source) as source_conn:
            from agentic_rag.domains import seed_defaults
            seed_defaults(source_conn)
            store.save_document(source_conn, source, title='Preserved operator corpus',
                                body='Source patch 0.6.16 keeps original content and scope.',
                                domain='general', dtype='memory', project='/synthetic/team')
        before = upgrade.inventory(source, '0.6.16')
        dry = upgrade.local_upgrade(source, '0.6.16', tmp_path / 'unused.dump')
        assert dry['plan']['ready'] and dry['applied'] is False
        assert not (tmp_path / 'unused.dump').exists()
        proof = upgrade.local_upgrade(source, '0.6.16', tmp_path / 'code-only.dump',
                                      apply=True, writers_stopped=True)
        assert proof['restore_verified'] and proof['original_rows_unchanged']
        assert proof['migrations_applied'] == []
        assert upgrade.inventory(source, '0.6.16')['tables'] == before['tables']
        assert upgrade.verify_preserved(source, proof['manifest'])['unchanged']
