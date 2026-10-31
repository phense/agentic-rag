"""RAG-063 T063-006: dashboard evidence drilldown and version-bound actions (HTTP)."""
from datetime import datetime, timezone
import time
import uuid

from starlette.testclient import TestClient

from agentic_rag import db, store
from .test_api import app_fixture
from .test_dashboard import login
from .test_evidence_transports import evidence_store, local_view  # noqa: F401  (fixture)


def envelope(tool, arguments):
    return {'tool': tool, 'arguments': arguments, 'idempotency_key': str(uuid.uuid4()),
            'created_at': datetime.now(timezone.utc).isoformat()}


def finish(client, csrf, tool, arguments):
    response = client.post('/dashboard/api/tools', headers=csrf, json=envelope(tool, arguments))
    assert response.status_code == 200, response.text
    identity = response.json()['request_id']
    for _ in range(200):
        data = client.get('/dashboard/api/requests/' + identity).json()
        if data['state'] not in {'pending', 'running'}:
            return data
        time.sleep(.05)
    raise AssertionError('queue did not finish')


def test_dashboard_reads_contract_and_requires_inspected_versions(evidence_store, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        csrf = login(client, 'alice', 'correct horse synthetic password')
        view = finish(client, csrf, 'memory_evidence', {'id_or_slug': own})
        assert view['state'] == 'completed' and view['result']['version'] == local_view(cfg, own)['version']
        history = finish(client, csrf, 'memory_evidence_history', {'id_or_slug': own, 'source_key': own_key})
        assert history['state'] == 'completed' and history['result']['scope'] == 'source'
        for tool, arguments in [
            ('memory_review_claim', {'id_or_slug': own, 'state': 'confirmed', 'reason': 'no token'}),
            ('memory_source_state', {'source_key': own_key, 'state': 'removed', 'reason': 'no token'}),
            ('memory_source_state', {'source_key': own_key, 'state': 'removed', 'reason': 'no anchor',
                                     'expected_version': view['result']['sources']['items'][0]['source_version']}),
        ]:
            rejected = client.post('/dashboard/api/tools', headers=csrf, json=envelope(tool, arguments))
            assert (rejected.status_code, rejected.json()) == (400, {'error': 'expected_version_required'})
        seen = view['result']['version']
        with db.connect(cfg) as conn:
            store.review_claim(conn, own, state='unreviewed', reason='concurrent legacy change')
        stale = finish(client, csrf, 'memory_review_claim',
                       {'id_or_slug': own, 'state': 'confirmed', 'reason': 'stale dashboard', 'expected_version': seen})
        assert stale['state'] == 'failed' and stale['code'] == 'evidence_conflict'
        fresh = local_view(cfg, own)['version']
        ok = finish(client, csrf, 'memory_review_claim',
                    {'id_or_slug': own, 'state': 'confirmed', 'reason': 'dashboard review', 'expected_version': fresh})
        assert ok['state'] == 'completed' and ok['result']['version'] != fresh
        denied = client.post('/dashboard/api/tools', headers=csrf, json=envelope('memory_save', {'title': 'x'}))
        assert denied.status_code == 403
    with db.connect(cfg) as conn:
        row = conn.execute("SELECT concurrency,inspected_version FROM claim_history WHERE operation='review'"
                           " ORDER BY revision DESC LIMIT 1").fetchone()
    assert row == {'concurrency': 'strict', 'inspected_version': fresh}


def test_readonly_dashboard_user_still_gets_scope_denial_before_validation(evidence_store, tmp_path):
    cfg, own, *_ = evidence_store
    app, path = app_fixture(tmp_path, cfg)
    path.write_text(path.read_text().replace('write_domains = ["alpha"]', 'write_domains = []')
                    .replace('write_projects = ["/projects/a"]', 'write_projects = []'))
    with TestClient(app, base_url='https://testserver') as client:
        csrf = login(client, 'alice', 'correct horse synthetic password')
        response = client.post('/dashboard/api/tools', headers=csrf,
                               json=envelope('memory_review_claim', {'id_or_slug': own, 'state': 'confirmed', 'reason': 'ro'}))
        assert response.status_code == 403
        view = finish(client, csrf, 'memory_evidence', {'id_or_slug': own})
        assert view['state'] == 'completed'
