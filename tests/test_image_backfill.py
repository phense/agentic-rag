"""RAG-070 IC-001/IC-004: local CLI and explicit, bounded, resumable historical processing."""
import json
import os

import pytest

pytest.importorskip('PIL')

from agentic_rag import cli, db, image_backfill, images, store  # noqa: E402
from agentic_rag.benchmark.database import isolated_database  # noqa: E402
from agentic_rag.config import Config  # noqa: E402
from test_images import FakeOCR, picture  # noqa: E402


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    fake = FakeOCR()
    monkeypatch.setattr(images, 'ocr_engine_for', lambda cfg: fake)
    base = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    with isolated_database(base) as owned:
        with db.connect(owned) as conn:
            for domain in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (domain,))
            conn.commit()
        config = tmp_path / 'config.toml'
        config.write_text(f'[db]\nname = "{owned.db_name}"\nhost = "{owned.db_host}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n'
                          '[images]\nenabled = true\n')
        monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
        yield owned, fake, tmp_path


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def counts(cfg):
    with db.connect(cfg) as conn:
        return conn.execute('SELECT (SELECT count(*) FROM image_originals) o,(SELECT count(*) FROM image_derivations) d,'
                            '(SELECT count(*) FROM documents) docs').fetchone()


def test_local_cli_add_show_original_and_references(local, capsys):
    cfg, fake, tmp = local
    image = tmp / 'bon.png'
    image.write_bytes(picture(31))
    code, out, err = run(capsys, 'image', 'add', str(image), '--domain', 'alpha', '--project', '/projects/a')
    assert code == 0, err
    result = json.loads(out)
    doc = result['derivations'][0]['document_id']
    code, out, _ = run(capsys, 'image', 'show', doc, '--limit', '1')
    assert code == 0 and len(json.loads(out)['derivations'][0]['regions']['items']) == 1
    target = tmp / 'out.png'
    code, out, _ = run(capsys, 'image', 'original', result['original']['id'], '--output', str(target))
    assert code == 0 and target.read_bytes() == image.read_bytes() and result['original']['sha256'] in out
    link = tmp / 'link.png'
    link.symlink_to(image)
    code, _, err = run(capsys, 'image', 'add', str(link), '--domain', 'alpha', '--project', '/projects/a')
    assert code == 1 and 'image_file_unavailable' in err
    code, _, err = run(capsys, 'image', 'add', 'https://example.com/a.png', '--domain', 'alpha')
    assert code == 1 and 'image_file_unavailable' in err
    with db.connect(cfg) as conn:
        store.save_document(conn, cfg, title='Notiz', body='Siehe ![Beleg](belege/scan-1.png) und https://x.test/a.jpg',
                            domain='alpha', dtype='memory')
    code, out, _ = run(capsys, 'image', 'references', '--domain', 'alpha')
    refs = json.loads(out)
    assert code == 0 and refs['total'] == 1
    assert {r['reference'] for r in refs['candidates'][0]['references']} == {'belege/scan-1.png', 'https://x.test/a.jpg'}
    assert refs['candidates'][0]['disposition'] == 'reference_only_no_retained_original'
    assert fake.calls == 1


def manifest(tmp, items):
    path = tmp / 'manifest.json'
    path.write_text(json.dumps({'version': 1, 'items': items}))
    return path


def test_preview_classifies_every_candidate_without_engine_calls_or_writes(local):
    cfg, fake, tmp = local
    (tmp / 'imgs').mkdir()
    for n in range(3):
        (tmp / 'imgs' / f'{n}.png').write_bytes(picture(40 + n))
    (tmp / 'imgs' / 'bad.png').write_bytes(b'not an image')
    from dataclasses import replace
    with db.connect(cfg, role='writer') as conn:
        done = images.ingest(conn, replace(cfg, image_enabled=True), (tmp / 'imgs' / '0.png').read_bytes(),
                             domain='alpha', project='/projects/a', ocr_engine=fake)
    calls = fake.calls
    path = manifest(tmp, [
        {'path': 'imgs/0.png', 'domain': 'alpha', 'project': '/projects/a'},
        {'path': 'imgs/1.png', 'domain': 'alpha', 'project': '/projects/a'},
        {'path': 'imgs/missing.png', 'domain': 'alpha', 'project': '/projects/a'},
        {'path': 'imgs/bad.png', 'domain': 'alpha', 'project': '/projects/a'},
        {'path': 'imgs/2.png', 'domain': 'nope', 'project': '/projects/a'},
        {'original': done['original']['id']},
        {'original': '00000000-0000-0000-0000-000000000000'},
    ])
    before = counts(cfg)
    from agentic_rag.config import load_config
    report = image_backfill.preview(load_config(), path)
    assert [i['disposition'] for i in report['items']] == [
        'unchanged', 'selected', 'missing', 'invalid', 'unauthorized', 'unchanged', 'missing']
    assert report['counts']['selected'] == 1 and report['estimated_engine_items'] == 1
    assert fake.calls == calls and counts(cfg) == before
    fake.version = 'fake-ocr-2'  # changed processing identity
    changed = image_backfill.preview(load_config(), path)
    assert [i['disposition'] for i in changed['items']][:2] == ['changed', 'selected']
    assert changed['items'][5]['disposition'] == 'changed'


def test_apply_is_bounded_resumable_cancellable_and_never_duplicates(local, capsys):
    cfg, fake, tmp = local
    (tmp / 'imgs').mkdir()
    items = []
    for n in range(5):
        (tmp / 'imgs' / f'{n}.png').write_bytes(picture(50 + n))
        items.append({'path': f'imgs/{n}.png', 'domain': 'alpha', 'project': '/projects/a'})
    path = manifest(tmp, items)
    state = tmp / 'state'
    code, out, err = run(capsys, 'image', 'backfill', str(path), '--apply', '--limit', '2', '--state-dir', str(state))
    first = json.loads(out)
    assert code == 0, err
    assert first['run']['cursor'] == 2 and first['run']['state'] == 'paused' and counts(cfg)['d'] == 2
    # Interruption: the stop request is honored between items, never mid-publication.
    from agentic_rag.config import load_config
    stopped = image_backfill.apply(load_config(), path, limit=10, state_dir=state, should_stop=lambda: True)
    assert stopped['run']['state'] == 'canceled' and stopped['run']['cursor'] == 2 and counts(cfg)['d'] == 2
    # Lost cursor: a full rerun is still safe because PostgreSQL keys are idempotent.
    for f in state.iterdir():
        f.unlink()
    rerun = image_backfill.apply(load_config(), path, limit=10, state_dir=state)
    assert rerun['run']['state'] == 'complete' and rerun['run']['cursor'] == 5
    assert [p['state'] for p in rerun['processed']] == ['existing', 'existing', 'published', 'published', 'published']
    assert counts(cfg) == {'o': 5, 'd': 5, 'docs': 5}
    done = image_backfill.apply(load_config(), path, limit=10, state_dir=state)
    assert done['processed'] == [] and done['run']['state'] == 'complete'
    code, out, _ = run(capsys, 'image', 'backfill', str(path), '--dry-run', '--state-dir', str(state))
    assert code == 0 and json.loads(out)['counts'] == {'unchanged': 5}
    assert sorted(os.listdir(state))[0].endswith('.json') and (state / os.listdir(state)[0]).stat().st_mode & 0o077 == 0


def test_cancel_marker_and_engine_failure_keep_resumable_state(local, capsys):
    cfg, fake, tmp = local
    (tmp / 'imgs').mkdir()
    for n in range(3):
        (tmp / 'imgs' / f'{n}.png').write_bytes(picture(60 + n))
    path = manifest(tmp, [{'path': f'imgs/{n}.png', 'domain': 'alpha', 'project': '/projects/a'} for n in range(3)])
    state = tmp / 'state'
    fake.error = 'ocr_timeout'
    from agentic_rag.config import load_config
    failed = image_backfill.apply(load_config(), path, limit=1, state_dir=state)
    assert failed['processed'][0]['state'] == 'failed' and failed['processed'][0]['code'] == 'ocr_timeout'
    assert failed['run']['counts']['failed'] == 1
    code, out, _ = run(capsys, 'image', 'backfill', str(path), '--cancel', '--state-dir', str(state))
    assert code == 0 and json.loads(out)['run']['cancel_requested'] is True
    canceled = image_backfill.apply(load_config(), path, limit=5, state_dir=state)
    assert canceled['run']['state'] == 'canceled' and canceled['processed'] == []
    fake.error = None
    resumed = image_backfill.apply(load_config(), path, limit=5, state_dir=state, resume=True)
    assert resumed['run']['state'] == 'complete' and [p['state'] for p in resumed['processed']] == ['published', 'published']
    # The earlier failure is recoverable by an explicit retry of the retained original.
    retry = image_backfill.apply(load_config(), path, limit=5, state_dir=state, restart=True)
    assert [p['state'] for p in retry['processed']] == ['published', 'existing', 'existing']


def test_disabled_installation_and_manifest_bounds(local, capsys, monkeypatch):
    cfg, fake, tmp = local
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(tmp / 'off.toml'))
    (tmp / 'off.toml').write_text(f'[db]\nname = "{cfg.db_name}"\nhost = "{cfg.db_host}"\n')
    (tmp / 'a.png').write_bytes(picture(70))
    path = manifest(tmp, [{'path': 'a.png', 'domain': 'alpha'}])
    code, _, err = run(capsys, 'image', 'backfill', str(path), '--apply', '--state-dir', str(tmp / 's'))
    assert code == 1 and 'images_disabled' in err and fake.calls == 0 and counts(cfg)['o'] == 0
    code, _, err = run(capsys, 'image', 'add', str(tmp / 'a.png'), '--domain', 'alpha')
    assert code == 1 and 'images_disabled' in err
    for bad in [{'version': 2, 'items': []}, {'version': 1, 'items': [{'path': 'a.png'}]},
                {'version': 1, 'items': [{'url': 'https://x.test/a.png', 'domain': 'alpha'}]},
                {'version': 1, 'items': [{'path': 'a.png', 'domain': 'alpha'}] * (image_backfill.MAX_ITEMS + 1)}]:
        (tmp / 'bad.json').write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            image_backfill.load_manifest(tmp / 'bad.json')
