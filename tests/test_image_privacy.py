"""Privacy recovery uses real gateway/roles/transactions; only OCR is synthetic."""
import hashlib
import json

import pytest

from agentic_rag import db, images
from test_images import FakeOCR, ingest, owned, picture  # noqa: F401


def test_secret_detection_quarantines_original_and_disables_claim_support(owned):
    result = ingest(owned, picture(71), ocr_engine=FakeOCR(text='password: Sommer2026x\nReferenz Sommer2026xy'))
    original = result['original']
    with db.connect(owned, role='reader') as conn:
        with pytest.raises(images.ImageUnavailable):
            images.original(conn, original['id'])
        source = conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (original['source_key'],)).fetchone()
        assert source['state'] == 'removed'
        derivation = conn.execute('SELECT regions FROM image_derivations WHERE original_id=%s', (original['id'],)).fetchone()
        assert 'Sommer2026x' not in [r['text'] for r in derivation['regions']]
    assert 'original_quarantined' in result['derivations'][0]['warnings']


def test_original_erasure_is_previewable_audited_and_keeps_other_sources(owned):
    first, second = ingest(owned, picture(72)), ingest(owned, picture(73))
    key, original = first['original']['source_key'], first['original']['id']
    shared_doc = first['derivations'][0]['document_id']
    assert shared_doc == second['derivations'][0]['document_id']
    with db.connect(owned, role='admin') as conn:
        before = conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
        preview = images.erase(conn, original, expected_sha256=first['original']['sha256'], reason='synthetic incident')
        assert preview['applied'] is False and preview['shared_documents'] == [shared_doc]
        assert images.original(conn, original)[0] == picture(72)
        assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n'] == before
        result = images.erase(conn, original, expected_sha256=first['original']['sha256'], reason='synthetic incident', apply=True)
        assert result['applied'] is True
        row = conn.execute('SELECT bytes,erased_at FROM image_originals WHERE id=%s', (original,)).fetchone()
        assert row['bytes'] is None and row['erased_at'] is not None
        assert conn.execute('SELECT count(*) n FROM claim_evidence WHERE source_key=%s', (key,)).fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) n FROM documents WHERE id=%s', (shared_doc,)).fetchone()['n'] == 1
        assert images.original(conn, second['original']['id'])[0] == picture(73)
        assert images.inspect(conn, shared_doc)['original']['id'] == second['original']['id']
        row = conn.execute('SELECT text,regions,warnings FROM image_derivations WHERE original_id=%s', (original,)).fetchone()
        assert row['text'] == '' and row['regions'] == [] and 'payload_erased' in row['warnings']
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='image_erase'").fetchone()['n'] == 1
        again = images.erase(conn, original, expected_sha256=first['original']['sha256'], reason='retry', apply=True)
        assert again['already_erased'] is True
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='image_erase'").fetchone()['n'] == 1


def test_erasure_removes_exclusive_claim_but_retains_tombstone(owned):
    result = ingest(owned, picture(74))
    original = result['original']
    doc = result['derivations'][0]['document_id']
    with db.connect(owned, role='admin') as conn:
        images.erase(conn, original['id'], expected_sha256=original['sha256'], reason='owner request', apply=True)
        assert not conn.execute('SELECT id FROM documents WHERE id=%s', (doc,)).fetchone()
        assert conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (original['source_key'],)).fetchone()['state'] == 'removed'
        assert conn.execute('SELECT sha256 FROM image_originals WHERE id=%s', (original['id'],)).fetchone()['sha256'] == original['sha256']
    with db.connect(owned, role='reader') as conn:
        with pytest.raises(images.ImageUnavailable): images.original(conn, original['id'])


def test_erasure_requires_operator_and_exact_original_digest(owned):
    result = ingest(owned, picture(75))
    original = result['original']
    for role in ('reader', 'writer'):
        with db.connect(owned, role=role) as conn:
            with pytest.raises(PermissionError):
                images.erase(conn, original['id'], expected_sha256=original['sha256'], reason='no', apply=True)
    with db.connect(owned, role='admin') as conn:
        with pytest.raises(ValueError, match='original_digest_conflict'):
            images.erase(conn, original['id'], expected_sha256='0' * 64, reason='no', apply=True)
        assert images.original(conn, original['id'])[0] == picture(75)


def test_erasure_audit_failure_rolls_back_bytes_source_and_claims(owned):
    result = ingest(owned, picture(76))
    original = result['original']
    with db.connect(owned) as conn:
        conn.execute("""CREATE FUNCTION fail_erase_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.op='image_erase' THEN RAISE EXCEPTION 'synthetic outage'; END IF; RETURN NEW; END $$""")
        conn.execute('CREATE TRIGGER fail_erase_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION fail_erase_audit()')
        conn.commit()
    with db.connect(owned, role='admin') as conn:
        with pytest.raises(Exception, match='synthetic outage'):
            images.erase(conn, original['id'], expected_sha256=original['sha256'], reason='test', apply=True)
        assert images.original(conn, original['id'])[0] == picture(76)
        assert conn.execute('SELECT id FROM documents WHERE id=%s', (result['derivations'][0]['document_id'],)).fetchone()


def test_region_redaction_does_not_use_substring_membership():
    text, regions, _ = images._sanitize('password: Sommer2026x\nReferenz Sommer2026xy',
        [{'text': 'Sommer2026x', 'box': [0, 0, 1, 1]}])
    assert regions[0]['text'] == '[REDACTED]'


def test_quarantined_image_cannot_be_reactivated_by_normal_source_state(owned):
    from agentic_rag import evidence
    result = ingest(owned, picture(81), ocr_engine=FakeOCR(text='password: Sommer2026x'))
    for role in ('writer', 'admin'):
        with db.connect(owned, role=role) as conn:
            with pytest.raises(ValueError, match='image_quarantined'):
                evidence.source_state(conn, result['original']['source_key'], state='active', reason='reinstate')
    with db.connect(owned, role='reader') as conn:
        with pytest.raises(images.ImageUnavailable): images.original(conn, result['original']['id'])


def test_image_review_tokens_equal_sql_and_change_after_new_reading(owned):
    from agentic_rag import evidence_contract
    fake = FakeOCR(text='First reading')
    result = ingest(owned, picture(82), ocr_engine=fake)
    doc = result['derivations'][0]['document_id']
    with db.connect(owned, role='writer') as conn:
        before = evidence_contract.document_version(conn, doc)
        assert before == conn.execute('SELECT rag_document_version(%s) v', (doc,)).fetchone()['v']
        fake.version, fake.text = 'fake-2', 'Different reading'
        images.reprocess(conn, owned, result['original']['id'], ocr_engine=fake)
        after = evidence_contract.document_version(conn, doc)
        assert after != before
        assert after == conn.execute('SELECT rag_document_version(%s) v', (doc,)).fetchone()['v']


def test_concurrent_erasure_of_both_shared_sources_removes_unsupported_claim(owned):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    first, second = ingest(owned, picture(83)), ingest(owned, picture(84))
    doc = first['derivations'][0]['document_id']
    barrier = threading.Barrier(2)
    class ConcurrentConnection:
        def __init__(self, conn): self.conn = conn
        def __getattr__(self, name): return getattr(self.conn, name)
        def execute(self, query, *args, **kwargs):
            # Both erasures have read their dependency set before either locks it.
            if query.startswith('SELECT document_id FROM claim_records'):
                barrier.wait(timeout=5)
            return self.conn.execute(query, *args, **kwargs)
    def erase(item):
        original = item['original']
        with db.connect(owned, role='admin') as conn:
            return images.erase(ConcurrentConnection(conn), original['id'], expected_sha256=original['sha256'],
                                reason='concurrent synthetic incident', apply=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(erase, [first, second]))
    assert all(r['applied'] for r in results)
    with db.connect(owned) as conn:
        assert not conn.execute('SELECT id FROM documents WHERE id=%s', (doc,)).fetchone()
        assert conn.execute('SELECT count(*) n FROM chunks WHERE document_id=%s', (doc,)).fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) n FROM image_originals WHERE erased_at IS NOT NULL').fetchone()['n'] == 2


def test_nonimage_document_version_remains_byte_identical_after_image_migration(owned):
    from agentic_rag import evidence_contract, store
    with db.connect(owned, role='writer') as conn:
        saved = store.save_document(conn, owned, title='Plain note', body='Preserved text', domain='alpha', dtype='memory')
        legacy = conn.execute(evidence_contract.DOCUMENT_VERSION_SQL, (saved.doc_id,)).fetchone()['version']
        assert evidence_contract.document_version(conn, saved.doc_id) == legacy
        assert conn.execute('SELECT rag_document_version(%s) v', (saved.doc_id,)).fetchone()['v'] == legacy
