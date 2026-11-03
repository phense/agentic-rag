"""RAG-070 AC-006/AC-007: populated actual-source upgrades with image writes.

Sources are the archived production code lines: 0.6.17 (schema029, Peter's Mac)
and 0.6.23 (schema035, Hetzner). Each run seeds a multi-user, multi-domain store
with the OLD code, proves an interrupted migration changes nothing, upgrades,
writes images with the new code, and checks original-row and vector hashes,
old-code reads, independent restores of the source and target backups, and the
code-rollback boundary. Everything runs on owned rag_bench_* databases.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

pytest.importorskip('PIL')

from agentic_rag import db, images, query_cache  # noqa: E402
from agentic_rag.benchmark.database import isolated_database  # noqa: E402
from agentic_rag.config import Config  # noqa: E402
from agentic_rag.service import upgrade  # noqa: E402
from test_image_engines import FIXTURES, HAVE_TESSERACT, RUNTIME  # noqa: E402
from test_images import FakeOCR  # noqa: E402

SOURCES = {'0.6.17': ('3ba0ff0ce53ad5b59977b1f98f1c2d43655a3816', 29, '0.6.16'),
           '0.6.23': ('c33e11fd5ccc4fa1e11c92fbcd16e9fee0cbdcd9', 35, '0.6.22')}
SEED = r'''
from agentic_rag import domains, store, pins, jobs
import hashlib
assert db.__file__.startswith(os.getcwd())
def vectors(texts, cfg):
    return [[(hashlib.sha256((t + str(i // 32)).encode()).digest()[i % 32] - 128) / 256 for i in range(1024)] for t in texts]
store.try_embed_texts = vectors
db.init_db(cfg)
with db.connect(cfg) as conn:
    domains.add_domain(conn, 'finance')
    docs = []
    for domain, project in [('general', '/projects/alpha'), ('finance', '/projects/beta')]:
        body = 'Original receipt archive note ' + domain + ' ![scan](scans/receipt-' + domain + '.png)'
        saved = store.save_claim(conn, cfg, title=body, body=body, domain=domain, project=project, dtype='memory',
            claim_kind='stated', evidence=[{'namespace': 'upgrade70', 'source_id': domain + str(n), 'role': 'user',
            'quote': body, 'complete': True} for n in range(2)])
        store.review_claim(conn, saved.doc_id, state='confirmed', reason='original synthetic source reviewed')
        docs.append(saved.doc_id)
    plain = store.save_document(conn, cfg, title='Plain legacy note', body='Legacy text without claims', domain='general',
                                dtype='memory', project='/projects/alpha')
    fact = store.save_assertion(conn, cfg, entity='lyra', attribute='port', value='8766', domain='general',
        project='/projects/alpha', event_at='2026-01-01T00:00:00Z', evidence={'namespace': 'upgrade70',
        'source_id': 'port', 'role': 'user', 'quote': 'lyra port 8766', 'complete': True})
    pins.add_pin(conn, body='Original preserved pin', scope='global')
    jobs.enqueue_mine(conn, cfg, session_id='pending-image-upgrade', transcript_path='/synthetic/preserved.jsonl',
                      project='/projects/alpha')
print(json.dumps({'documents': docs, 'plain': plain.doc_id, 'fact': fact.doc_id}))
'''
READ = r'''
from agentic_rag.search import search
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope
assert db.__file__.startswith(os.getcwd())
out = {}
with db.connect(cfg, role='reader') as conn:
    out['local'] = sorted({h.document_id for h in search(conn, cfg, 'Original receipt archive', strategy='lexical')[0]})
p = Principal('reader', 'synthetic', 'upgrade70', frozenset({'finance'}), frozenset(), frozenset({'/projects/beta'}),
              frozenset())
with request_scope(p, cfg, read_only=True):
    with db.connect(cfg, role='reader') as conn:
        out['scoped'] = sorted({h.document_id for h in search(conn, cfg, 'Original receipt archive', strategy='lexical')[0]})
        out['visible'] = conn.execute('SELECT count(*) n FROM documents').fetchone()['n']
print(json.dumps(out))
'''
ROLLBACK = r'''
from agentic_rag.service import upgrade
try:
    upgrade.inventory(cfg, os.environ['OLD_LABEL'])
    print(json.dumps('accepted'))
except ValueError as error:
    print(json.dumps(str(error)))
'''
INTERRUPT = r'''
from agentic_rag import db
with db.connect(cfg) as conn:
    applied = db.apply_migrations(conn, db.SQL_DIR, commit=False)
    assert '036_image_ingestion.sql' in applied
    os._exit(9)  # killed after migrating, before commit
'''

TABLES = {'documents': 'id', 'chunks': 'id', 'knowledge_sources': 'source_key', 'claim_records': 'document_id',
          'claim_evidence': "document_id||'/'||source_key||'/'||span_hash", 'fact_assertions': 'document_id',
          'pins': 'id', 'mining_queue': 'id', 'audit_log': 'id', 'domains': 'name', 'edges': 'id'}


def row_hashes(cfg):
    out = {}
    with db.connect(cfg) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        for table, key in TABLES.items():
            out[table] = {r['k']: hashlib.sha256(r['v'].encode()).hexdigest() for r in conn.execute(
                f'SELECT ({key})::text k, to_jsonb(t)::text v FROM {table} t')}
    return out


def assert_originals_unchanged(before, after):
    for table, rows in before.items():
        assert {k: after[table].get(k) for k in rows} == rows, table


def run_code(source, cfg, code, env=None, cwd_code=True):
    environment = dict(os.environ, IMAGE_UPGRADE_DB=cfg.db_name, PYTHONPATH=str(source) if cwd_code else '',
                       AGENTIC_RAG_HOOKS_DISABLE='1', **(env or {}))
    prefix = ("import json,os\nfrom agentic_rag import db\nfrom agentic_rag.config import Config\n"
              "cfg=Config(db_name=os.environ['IMAGE_UPGRADE_DB'],db_host='127.0.0.1',ollama_url='http://127.0.0.1:1')\n")
    return subprocess.run([sys.executable, '-c', prefix + code], cwd=source, env=environment, capture_output=True,
                          text=True, timeout=120)


def old_run(source, cfg, code, **kw):
    result = run_code(source, cfg, code, **kw)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.splitlines()[-1])


def archive(commit, target):
    target.mkdir()
    tar = target.parent / (target.name + '.tar')
    with tar.open('wb') as stream:
        subprocess.run(['git', 'archive', commit, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=stream, check=True,
                       cwd=Path(__file__).resolve().parents[2])
    with tarfile.open(tar) as stream:
        stream.extractall(target, filter='data')
    return target


def image_config(cfg):
    cfg = replace(cfg, image_enabled=True)
    if HAVE_TESSERACT:
        cfg = replace(cfg, image_ocr_command=str(RUNTIME / 'usr/bin/tesseract'),
                      image_ocr_tessdata=RUNTIME / 'usr/share/tesseract-ocr/5/tessdata',
                      image_ocr_library_path=RUNTIME / 'usr/lib/x86_64-linux-gnu')
    return cfg


@pytest.mark.parametrize('label', sorted(SOURCES))
def test_populated_source_upgrade_images_restore_and_rollback(label, tmp_path, monkeypatch):
    commit, schema, old_label = SOURCES[label]
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
    calls = []
    monkeypatch.setattr(images, 'ocr_engine_for', lambda cfg: calls.append(cfg) or (
        __import__('agentic_rag.image_engines', fromlist=['x']).TesseractEngine.from_config(cfg) if HAVE_TESSERACT else FakeOCR()))
    source = archive(commit, tmp_path / 'source')
    assert f'version = "{label}"' in (source / 'pyproject.toml').read_text()
    new = Path(__file__).resolve().parents[2]
    with isolated_database(Config(), initialize=False) as cfg:
        seeded = old_run(source, cfg, SEED)
        old_reads = old_run(source, cfg, READ)
        assert old_reads['scoped'] == [seeded['documents'][1]] and len(old_reads['local']) == 2
        before = upgrade.inventory(cfg, label)
        assert len(before['migrations']) == schema and 'image_originals' not in before['tables']
        hashes = row_hashes(cfg)
        assert sum(1 for v in hashes['chunks']) >= 3
        source_backup = upgrade.verified_backup(cfg, label, tmp_path / 'source.dump')
        assert source_backup['restore_verified']

        # Interruption: the new code migrates everything, then dies before commit.
        killed = run_code(new, cfg, INTERRUPT, cwd_code=False)
        assert killed.returncode == 9, killed.stderr[-2000:]
        assert upgrade.verify_preserved(cfg, source_backup['manifest'])['unchanged']
        assert row_hashes(cfg) == hashes

        # Retry: verified backup, migrate while legacy writers see a read-only store.
        result = upgrade.local_upgrade(cfg, label, tmp_path / 'upgrade.dump', apply=True, writers_stopped=True)
        assert '036_image_ingestion.sql' in result['migrations_applied'] and result['original_rows_unchanged']
        assert calls == []  # upgrading performs zero image work
        with db.connect(cfg) as conn:
            from agentic_rag.service.schema import validate_schema
            validate_schema(conn)
            assert conn.execute('SELECT count(*) n FROM image_originals').fetchone()['n'] == 0
        assert row_hashes(cfg) == hashes
        assert old_run(source, cfg, READ) == old_reads  # old clients on the new schema

        # New image writes in both authority boundaries, a reprocess and a withdrawal.
        icfg = image_config(cfg)
        receipt = (FIXTURES / 'invoice.png').read_bytes()
        shot = (FIXTURES / 'screenshot.png').read_bytes()
        with db.connect(icfg, role='writer') as conn:
            one = images.ingest(conn, icfg, receipt, domain='finance', project='/projects/beta', label='Rechnung')
            two = images.ingest(conn, icfg, shot, domain='general', project='/projects/alpha')
        assert {d['state'] for r in (one, two) for d in r['derivations']} == {'published'}
        with db.connect(icfg, role='writer') as conn:
            again = images.reprocess(conn, icfg, one['original']['id'])
        assert again['derivations'][0]['state'] == 'existing'
        from agentic_rag import evidence_contract, store
        doc = two['derivations'][0]['document_id']
        with db.connect(icfg, role='writer') as conn:
            version = evidence_contract.inspect(conn, doc)['sources']['items'][0]['source_version']
            store.set_source_state(conn, two['original']['source_key'], state='removed', reason='withdrawn in rehearsal',
                                   anchor=doc, expected_version=version)
        assert_originals_unchanged(hashes, row_hashes(cfg))
        after = old_run(source, cfg, READ)
        # Unreviewed image claims are not retrieved by old code; the scoped reader
        # sees one more (authorized, unreviewed) document in its own scope only.
        assert (after['local'], after['scoped']) == (old_reads['local'], old_reads['scoped'])
        assert after['visible'] == old_reads['visible'] + 1

        # Privacy erasure survives backup/restore as a content-free tombstone.
        from test_images import picture
        with db.connect(icfg, role='writer') as conn:
            erased = images.ingest(conn, icfg, picture(93), domain='finance', project='/projects/beta',
                                   ocr_engine=FakeOCR(text='Unique synthetic removal control'))
        with db.connect(icfg, role='admin') as conn:
            images.erase(conn, erased['original']['id'], expected_sha256=erased['original']['sha256'],
                         reason='synthetic erasure rehearsal', apply=True)

        # Independent restore of the target backup: bytes, drilldown and withdrawal survive.
        target = upgrade.verified_backup(cfg, '0.6.25', tmp_path / 'target.dump')
        assert target['restore_verified'] and target['manifest']['tables']['image_originals']['rows'] == 3
        with isolated_database(Config(), initialize=False) as restored:
            proof = upgrade.restore_target(restored, tmp_path / 'target.dump', target['manifest'], apply=True)
            assert proof['restore_verified'] and proof['migrations_applied'] == []
            with db.connect(restored, role='reader') as conn:
                data, meta = images.original(conn, one['original']['id'])
                assert data == receipt and meta['sha256'] == hashlib.sha256(receipt).hexdigest()
                view = images.inspect(conn, one['derivations'][0]['document_id'])
                assert view['derivations'][0]['regions']['total'] > 0
                with pytest.raises(images.ImageUnavailable):
                    images.original(conn, two['original']['id'])
            with db.connect(restored) as conn:
                tombstone = conn.execute('SELECT bytes,erased_at FROM image_originals WHERE id=%s',
                                        (erased['original']['id'],)).fetchone()
                assert tombstone['bytes'] is None and tombstone['erased_at'] is not None
                assert not conn.execute('SELECT id FROM documents WHERE id=%s',
                                        (erased['derivations'][0]['document_id'],)).fetchone()
            assert_originals_unchanged(hashes, row_hashes(restored))

        # Independent restore of the SOURCE backup, then upgrade of that copy.
        with isolated_database(Config(), initialize=False) as copy:
            proof = upgrade.restore_target(copy, tmp_path / 'source.dump', source_backup['manifest'], apply=True)
            assert '036_image_ingestion.sql' in proof['migrations_applied']
            assert row_hashes(copy) == hashes

        # Code rollback: old code keeps reading; additive tables and originals stay;
        # its operator tooling refuses the newer schema (explicit downgrade boundary).
        assert old_run(source, cfg, READ) == after
        refusal = old_run(source, cfg, ROLLBACK, env={'OLD_LABEL': old_label})
        assert refusal == 'unsupported_source_schema'
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM image_originals').fetchone()['n'] == 3
