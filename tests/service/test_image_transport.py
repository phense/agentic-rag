"""RAG-070 IC-002/003: central upload, drilldown and MCP reads on real HTTP/RLS.

The OCR provider is the in-process fake (provider seam only); authentication,
bounded bodies, request scope, SQL policies, evidence and audit are real.
"""
from dataclasses import replace
import hashlib
import json

import pytest
from starlette.testclient import TestClient

pytest.importorskip('PIL')

from agentic_rag import cli, db, images, store  # noqa: E402
from agentic_rag import image_media  # noqa: E402
from agentic_rag.benchmark.database import isolated_database  # noqa: E402
from agentic_rag.config import Config  # noqa: E402
from test_images import FakeOCR, picture  # noqa: E402
from .test_api import app_fixture, headers, KEYS  # noqa: E402


@pytest.fixture
def central(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'try_embed_texts', lambda texts, *a, **k: [[0.01] * 1024 for _ in texts])
    fake = FakeOCR()
    monkeypatch.setattr(images, 'ocr_engine_for', lambda cfg: fake)
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1', image_enabled=True)
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            for domain in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (domain,))
            conn.commit()
        app, policy = app_fixture(tmp_path, owned)
        yield owned, app, policy, fake


def upload(client, key, data, **params):
    params.setdefault('domain', 'alpha')
    params.setdefault('project', '/projects/a')
    return client.post('/v1/images', params=params, content=data,
                       headers={**headers(key), 'content-type': 'application/octet-stream'})


def test_upload_inspect_original_and_status_through_rest(central):
    cfg, app, _, fake = central
    data = picture(21)
    with TestClient(app, base_url='https://testserver') as client:
        first = upload(client, KEYS[0], data, label='Beleg')
        assert first.status_code == 200, first.text
        body = first.json()
        (ocr,) = body['derivations']
        assert ocr['state'] == 'published' and body['original']['sha256'] == hashlib.sha256(data).hexdigest()
        again = upload(client, KEYS[0], data, label='Beleg')
        assert again.json()['derivations'][0]['state'] == 'existing' and fake.calls == 1
        view = client.get('/v1/images/' + ocr['document_id'], headers=headers(KEYS[0]))
        assert view.status_code == 200 and view.json()['derivations'][0]['regions']['total'] == 5
        raw = client.get(f"/v1/images/{body['original']['id']}/original", headers=headers(KEYS[0]))
        assert raw.status_code == 200 and raw.content == data
        assert raw.headers['content-type'] == 'image/png'
        assert raw.headers['x-rag-image-sha256'] == body['original']['sha256']
        assert raw.headers['x-content-type-options'] == 'nosniff'
        assert raw.headers['content-disposition'].startswith('attachment')
        # Read-only machine of the same scope reads, but cannot upload.
        assert client.get('/v1/images/' + ocr['document_id'], headers=headers(KEYS[3])).status_code == 200
        denied = upload(client, KEYS[3], picture(22))
        assert (denied.status_code, denied.json()) == (403, {'error': 'scope_denied'})
        status = client.post('/v1/images/status', headers=headers(KEYS[0]), json={'items': [
            {'sha256': body['original']['sha256'], 'domain': 'alpha', 'project': '/projects/a'},
            {'sha256': '0' * 64, 'domain': 'alpha', 'project': '/projects/a'},
            {'sha256': '1' * 64, 'domain': 'beta', 'project': '/projects/b'}]})
        assert [i['disposition'] for i in status.json()['items']] == ['unchanged', 'selected', 'unauthorized']
        mcp = client.post('/mcp/ro/', headers={**headers(KEYS[3]), 'accept': 'application/json, text/event-stream'},
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'memory_image', 'arguments': {'id_or_slug': ocr['document_id']}}})
        result = mcp.json()['result']
        structured = result.get('structuredContent') or json.loads(result['content'][0]['text'])
        assert structured['original']['sha256'] == body['original']['sha256'] and 'bytes' not in json.dumps(structured)
        tool = client.post('/v1/tools/memory_image', headers=headers(KEYS[0]), json={'id_or_slug': ocr['document_id'],
                                                                                    'limit': 2})
        assert tool.status_code == 200 and len(tool.json()['derivations'][0]['regions']['items']) == 2
    with db.connect(cfg) as conn:
        actors = {r['actor'] for r in conn.execute("SELECT actor FROM audit_log WHERE op LIKE 'image_%'")}
        traces = [r['operation'] for r in conn.execute('SELECT operation FROM request_traces')]
    assert actors == {'service:machine:alice:vm1'}
    assert {'images.upload', 'images.inspect', 'images.original', 'images.status'} <= set(traces)


def test_foreign_unknown_and_withdrawn_images_share_one_response(central):
    cfg, app, _, _ = central
    with TestClient(app, base_url='https://testserver') as client:
        mine = upload(client, KEYS[0], picture(23)).json()
        theirs = upload(client, KEYS[2], picture(23), domain='beta', project='/projects/b').json()
        assert theirs['derivations'][0]['state'] == 'published'
        refs = [theirs['original']['id'], theirs['derivations'][0]['document_id'], '00000000-0000-0000-0000-000000000000',
                'no-such-slug']
        responses = {(r.status_code, r.text) for ref in refs for r in (
            client.get('/v1/images/' + ref, headers=headers(KEYS[0])),
            client.get('/v1/images/' + ref + '/original', headers=headers(KEYS[0])))}
        assert responses == {(404, '{"error":"image_unavailable"}')}
        foreign_upload = upload(client, KEYS[0], picture(24), domain='beta', project='/projects/b')
        assert foreign_upload.status_code == 403
        doc = mine['derivations'][0]['document_id']
        items = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json={'id_or_slug': doc}).json()
        withdrawn = client.post('/v1/tools/memory_source_state', headers=headers(KEYS[0]), json={
            'source_key': mine['original']['source_key'], 'state': 'removed', 'reason': 'owner withdrew the image',
            'id_or_slug': doc, 'expected_version': items['sources']['items'][0]['source_version']})
        assert withdrawn.status_code == 200, withdrawn.text
        for path in ('/v1/images/' + doc, f"/v1/images/{mine['original']['id']}/original"):
            r = client.get(path, headers=headers(KEYS[0]))
            assert (r.status_code, r.text) == (404, '{"error":"image_unavailable"}')
        retry = upload(client, KEYS[0], picture(23))
        assert (retry.status_code, retry.json()) == (404, {'error': 'image_unavailable'})


def test_body_bounds_disabled_feature_and_parameters_are_checked_before_decoding(central, monkeypatch, tmp_path):
    cfg, app, _, fake = central
    calls = []
    monkeypatch.setattr(image_media, '_decode', lambda *a, **k: calls.append(1))
    with TestClient(app, base_url='https://testserver') as client:
        big = upload(client, KEYS[0], b'\x89PNG\r\n\x1a\n' + b'\0' * image_media.MAX_BYTES)
        assert (big.status_code, big.json()) == (413, {'error': 'request_too_large'})
        bad = client.post('/v1/images', params={'domain': 'alpha', 'project': '/projects/a', 'path': '/etc/passwd'},
                          content=picture(25), headers={**headers(KEYS[0]), 'content-type': 'application/octet-stream'})
        assert bad.status_code == 400
        gif = upload(client, KEYS[0], b'GIF89a' + b'\0' * 32)
        assert (gif.status_code, gif.json()) == (415, {'error': 'unsupported_image_type'})
        json_body = client.post('/v1/images', params={'domain': 'alpha', 'project': '/projects/a'},
                                json={'image': 'base64'}, headers=headers(KEYS[0]))
        assert json_body.status_code == 415
    assert calls == [] and fake.calls == 0
    (tmp_path / 'off').mkdir()
    off, _ = app_fixture(tmp_path / 'off', replace(cfg, image_enabled=False))
    with TestClient(off, base_url='https://testserver') as client:
        disabled = upload(client, KEYS[0], picture(26))
        assert (disabled.status_code, disabled.json()) == (409, {'error': 'images_disabled'})
    assert fake.calls == 0


def test_revoked_writer_during_ocr_publishes_nothing(central, monkeypatch):
    cfg, app, policy, fake = central
    def revoke():
        policy.write_text(policy.read_text().replace('[machines.vm1]', '[machines.vm1]\nenabled=false'))
    fake.hook = revoke
    with TestClient(app, base_url='https://testserver') as client:
        response = upload(client, KEYS[0], picture(27))
    assert (response.status_code, response.json()) == (403, {'error': 'authorization_changed'})
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM image_derivations').fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) n FROM claim_records').fetchone()['n'] == 0


def test_real_http_remote_client_cli_upload_show_and_original(central, tmp_path, monkeypatch, capsys):
    cfg, _, policy, _ = central
    from agentic_rag.service.api import create_app
    from .http_server import server
    app = create_app(cfg, policy, allowed_hosts=['127.0.0.1'])
    token = tmp_path / 'token'
    token.write_text(KEYS[0])
    token.chmod(0o600)
    image = tmp_path / 'receipt.png'
    data = picture(28)
    image.write_bytes(data)
    with server(app) as url:
        client_cfg = replace(cfg, service_mode='client', service_url=url, service_token_file=token,
                             service_spool_dir=tmp_path / 'spool', db_name='no_local_database_access')
        monkeypatch.setattr(cli, 'load_config', lambda *a: client_cfg)
        code = cli.main(['image', 'add', str(image), '--domain', 'alpha', '--project', '/projects/a', '--label', 'Bon'])
        out = capsys.readouterr()
        assert code == 0, out.err
        result = json.loads(out.out)
        assert result['derivations'][0]['state'] == 'published'
        code = cli.main(['image', 'show', result['derivations'][0]['document_id']])
        shown = json.loads(capsys.readouterr().out)
        assert code == 0 and shown['original']['id'] == result['original']['id']
        target = tmp_path / 'copy.png'
        code = cli.main(['image', 'original', result['original']['id'], '--output', str(target)])
        capsys.readouterr()
        assert code == 0 and target.read_bytes() == data and (target.stat().st_mode & 0o777) == 0o600
        assert cli.main(['image', 'original', result['original']['id'], '--output', str(target)]) == 1
        assert 'exists' in capsys.readouterr().err
        code = cli.main(['image', 'show', '00000000-0000-0000-0000-000000000000'])
        assert code == 1 and 'image_unavailable' in capsys.readouterr().err
        assert cli.main(['image', 'references']) == 1
        assert 'client' in capsys.readouterr().err


def test_secret_image_is_quarantined_for_real_client_and_readonly_reader(central):
    cfg, app, _, fake = central
    fake.text = 'api_key=' + 'A' * 40
    with TestClient(app, base_url='https://testserver') as client:
        reply = upload(client, KEYS[0], picture(92))
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert result['derivations'][0]['state'] == 'published'
        assert 'original_quarantined' in result['derivations'][0]['warnings']
        doc = result['derivations'][0]['document_id']
        inspection = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]),
                                 json={'id_or_slug': doc})
        assert inspection.status_code == 200, inspection.text
        source = inspection.json()['sources']['items'][0]
        assert source['trust']['quarantined'] is True
        reinstate = client.post('/v1/tools/memory_source_state', headers=headers(KEYS[0]), json={
            'source_key': source['source_key'], 'state': 'active', 'reason': 'ordinary reinstatement',
            'id_or_slug': doc, 'expected_version': source['source_version']})
        assert reinstate.status_code == 400 and reinstate.json() == {'error': 'invalid_arguments'}
        for key in (KEYS[0], KEYS[3]):
            denied = client.get('/v1/images/' + result['original']['id'] + '/original', headers=headers(key))
            assert denied.status_code == 404 and denied.json() == {'error': 'image_unavailable'}
