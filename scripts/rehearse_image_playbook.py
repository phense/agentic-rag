"""PB07001 CLI rehearsal on owned rag_bench_* databases. Usage: PGPORT=... python -I THIS OUT.json WORKDIR

Seeds a 0.6.23/schema035 store with the archived old code, then runs the
playbook's real `rag` commands A1..A6, B1..B5, C2..C4, D1..D3, E1..E3 as
subprocesses and records exit codes plus bounded, non-secret output excerpts.
"""
import json, os, subprocess, sys, tarfile, time
from dataclasses import replace
from pathlib import Path

WT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WT)); sys.path.insert(0, str(WT / 'tests')); sys.path.insert(0, str(WT / 'tests/service'))
from agentic_rag.benchmark.database import isolated_database  # noqa: E402
from agentic_rag.config import Config  # noqa: E402
from test_image_upgrade import SEED, run_code  # noqa: E402
from test_image_engines import FIXTURES, RUNTIME  # noqa: E402

OUT = Path(sys.argv[1]); WORK = Path(sys.argv[2]); WORK.mkdir(parents=True, exist_ok=True)
RAG = str(WT / '.venv/bin/rag')
log = []


def run(step, argv, cfgfile, expect=0):
    env = dict(os.environ, AGENTIC_RAG_CONFIG=str(cfgfile), AGENTIC_RAG_HOOKS_DISABLE='1')
    start = time.monotonic()
    r = subprocess.run([RAG, *argv], env=env, capture_output=True, text=True, timeout=300)
    out = r.stdout.strip()
    try:
        parsed = json.loads(out) if out else None
    except ValueError:
        try:
            parsed = json.loads(out.splitlines()[-1])
        except ValueError:
            parsed = None
    log.append({'step': step, 'argv': ['rag', *[a.replace(str(WORK), 'WORK').replace(str(WT), 'REPO') for a in argv]], 'exit': r.returncode,
                'expected_exit': expect, 'seconds': round(time.monotonic() - start, 2),
                'stdout_excerpt': out[:600].replace(str(WORK), 'WORK'), 'stderr_excerpt': r.stderr.strip()[-300:]})
    assert r.returncode == expect, (step, r.returncode, r.stderr[-800:])
    return parsed, out


def config(cfg, path, images=True):
    text = f'[db]\nname = "{cfg.db_name}"\nhost = "127.0.0.1"\n\n[ollama]\nurl = "{FAKE}"\n'
    if images:
        text += (f'\n[images]\nenabled = true\nocr_command = "{RUNTIME}/usr/bin/tesseract"\n'
                 f'ocr_tessdata = "{RUNTIME}/usr/share/tesseract-ocr/5/tessdata"\n'
                 f'ocr_library_path = "{RUNTIME}/usr/lib/x86_64-linux-gnu"\nwork_dir = "{WORK}/engine"\n')
    path.write_text(text); path.chmod(0o600)
    return path


# Owned loopback fake that only reports the embedding model's tag digest
# (restore-target compares it); embeddings themselves stay unavailable.
import http.server, threading
NAME = Config().embed_model if ':' in Config().embed_model else Config().embed_model + ':latest'
class Tags(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'models': [{'name': NAME, 'digest': 'd' * 64}]}).encode() if self.path == '/api/tags' else b'{}'
        self.send_response(200 if self.path == '/api/tags' else 404); self.send_header('content-length', str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        self.send_response(404); self.send_header('content-length', '0'); self.end_headers()
    def log_message(self, *a):
        pass
fake = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Tags)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = f'http://127.0.0.1:{fake.server_port}'
old = WORK / 'old-0.6.23'
if not old.exists():
    old.mkdir()
    tar = WORK / 'old.tar'
    with tar.open('wb') as s:
        subprocess.run(['git', 'archive', 'c33e11fd5ccc4fa1e11c92fbcd16e9fee0cbdcd9', 'agentic_rag', 'sql', 'pyproject.toml'],
                       stdout=s, check=True, cwd=WT)
    with tarfile.open(tar) as s:
        s.extractall(old, filter='data')
(WORK / 'engine').mkdir(exist_ok=True)
base = Config(db_host='127.0.0.1', ollama_url='http://127.0.0.1:1')
with isolated_database(base, initialize=False) as cfg, isolated_database(base, initialize=False) as target:
    seeded = run_code(old, cfg, SEED)
    assert seeded.returncode == 0, seeded.stderr[-1500:]
    pre = config(cfg, WORK / 'pre.toml', images=False)
    full = config(cfg, WORK / 'store.toml')
    tgt = config(target, WORK / 'target.toml')
    D = WORK / 'backups'
    # Part A
    run('A1', ['service', '--config', str(pre), 'inventory', '--source-version', '0.6.23', '--output', f'{D}/inventory.json'], pre)
    log[-1]['migrations_in_inventory'] = len(json.loads((D / 'inventory.json').read_text())['migrations'])
    run('A2', ['service', '--config', str(pre), 'preflight', '--source-version', '0.6.23', '--mode', 'local'], pre)
    run('A4-without-confirmation', ['service', '--config', str(pre), 'upgrade', '--source-version', '0.6.23', '--dump',
                                    f'{D}/refused.dump', '--apply'], pre, expect=1)
    a4, _ = run('A4', ['service', '--config', str(pre), 'upgrade', '--source-version', '0.6.23', '--dump', f'{D}/pre-images.dump',
                       '--apply', '--writers-stopped'], pre)
    log[-1]['checked'] = {'last_migration': a4['migrations_applied'][-1], 'restore_verified': a4['restore_verified'],
                          'original_rows_unchanged': a4['original_rows_unchanged'],
                          'manifest_exists': (D / 'pre-images.dump.manifest.json').is_file()}
    run('A5', ['service', '--config', str(pre), 'status'], pre)
    (D / 'empty.json').write_text('{"version": 1, "items": []}')
    run('A6-disabled', ['image', 'backfill', f'{D}/empty.json', '--apply', '--limit', '1', '--state-dir', f'{WORK}/state'], pre, expect=1)
    dry, _ = run('A6-dry-run', ['image', 'backfill', f'{D}/empty.json', '--dry-run'], full)
    log[-1]['checked'] = {'ocr_identity_len': len(dry['identities']['ocr'])}
    ap, _ = run('A6-apply', ['image', 'backfill', f'{D}/empty.json', '--apply', '--limit', '1', '--state-dir', f'{WORK}/state'], full)
    log[-1]['checked'] = {'run_state': ap['run']['state']}
    # Part B
    b1, _ = run('B1', ['image', 'add', str(FIXTURES / 'invoice.png'), '--domain', 'finance', '--project', '/projects/beta',
                       '--label', 'Receipt 2026-11'], full)
    doc, orig = b1['derivations'][0]['document_id'], b1['original']['id']
    log[-1]['checked'] = {'created': b1['original']['created'], 'kind': b1['derivations'][0]['kind'],
                          'state': b1['derivations'][0]['state'], 'review_state': b1['derivations'][0]['review_state']}
    b1r, _ = run('B1-repeat', ['image', 'add', str(FIXTURES / 'invoice.png'), '--domain', 'finance', '--project', '/projects/beta',
                               '--label', 'Receipt 2026-11'], full)
    log[-1]['checked'] = {'created': b1r['original']['created'], 'state': b1r['derivations'][0]['state']}
    run('B1-rejected-non-image', ['image', 'add', str(D / 'empty.json'), '--domain', 'finance', '--project', '/projects/beta'], full, expect=1)
    b2, _ = run('B2', ['image', 'show', doc, '--limit', '50'], full)
    words = {r['text']: r['box'] for r in b2['derivations'][0]['regions']['items']}
    log[-1]['checked'] = {'sha256': b2['original']['sha256'], 'has_identity': bool(b2['derivations'][0]['identity']),
                          'box_RE-2026-0471': words.get('RE-2026-0471')}
    log[-1]['stdout_excerpt'] = '(omitted: full OCR text)'
    b3, _ = run('B3', ['image', 'original', orig, '--output', f'{WORK}/copy.png'], full)
    import hashlib
    log[-1]['checked'] = {'sha_matches': hashlib.sha256((WORK / 'copy.png').read_bytes()).hexdigest() == b2['original']['sha256']}
    run('B3-exists', ['image', 'original', orig, '--output', f'{WORK}/copy.png'], full, expect=1)
    _, before = run('B5-before-review', ['search', 'RE-2026-0471', '--strategy', 'lexical', '--project', '/projects/beta', '--domain', 'finance'], full)
    log[-1]['checked'] = {'found': 'image-text-' in before}
    show, _ = run('B4-show', ['evidence', 'show', doc, '--json'], full)
    log[-1]['checked'] = {'keys': sorted(show), 'notices': [n for n in json.dumps(show).split('"') if n in ('machine_transcription','review_required','model_interpretation')]}
    log[-1]['stdout_excerpt'] = '(omitted)'
    run('B4', ['evidence', 'review', doc, '--state', 'confirmed', '--reason', 'checked against the original',
               '--expected-version', show['version']], full)
    _, after = run('B5', ['search', 'RE-2026-0471', '--strategy', 'lexical', '--project', '/projects/beta', '--domain', 'finance'], full)
    log[-1]['checked'] = {'found': 'image-text-' in after}
    log[-1]['stdout_excerpt'] = log[-1]['stdout_excerpt'][:200]
    # Part C
    (D / 'manifest.json').write_text(json.dumps({'version': 1, 'items': [
        {'path': str(FIXTURES / 'screenshot.png'), 'domain': 'finance', 'project': '/projects/beta'},
        {'path': str(FIXTURES / 'invoice.png'), 'domain': 'finance', 'project': '/projects/beta'},
        {'path': str(WORK / 'missing.png'), 'domain': 'finance', 'project': '/projects/beta'},
        {'original': orig}]}))
    refs, _ = run('C1', ['image', 'references', '--domain', 'finance', '--limit', '5'], full)
    dry, _ = run('C2', ['image', 'backfill', f'{D}/manifest.json', '--dry-run'], full)
    log[-1]['checked'] = {'dispositions': [i['disposition'] for i in dry['items']], 'engine_calls': dry['engine_calls'],
                          'writes': dry['writes'], 'estimated_engine_items': dry['estimated_engine_items']}
    run('C3-cancel', ['image', 'backfill', f'{D}/manifest.json', '--cancel', '--state-dir', f'{WORK}/state'], full)
    c, _ = run('C3-after-cancel', ['image', 'backfill', f'{D}/manifest.json', '--apply', '--limit', '2', '--state-dir', f'{WORK}/state'], full)
    log[-1]['checked'] = {'run_state': c['run']['state'], 'processed': len(c['processed'])}
    c, _ = run('C3', ['image', 'backfill', f'{D}/manifest.json', '--apply', '--resume', '--limit', '2', '--state-dir', f'{WORK}/state'], full)
    log[-1]['checked'] = {'run_state': c['run']['state'], 'cursor': c['run']['cursor'], 'states': [p['state'] for p in c['processed']]}
    c, _ = run('C4', ['image', 'backfill', f'{D}/manifest.json', '--apply', '--limit', '2', '--state-dir', f'{WORK}/state'], full)
    log[-1]['checked'] = {'run_state': c['run']['state'], 'states': [p['state'] for p in c['processed']]}
    c, _ = run('C4-final', ['image', 'backfill', f'{D}/manifest.json', '--apply', '--limit', '2', '--state-dir', f'{WORK}/state'], full)
    log[-1]['checked'] = {'run_state': c['run']['state'], 'processed': c['processed']}
    # Part E (before withdrawal, so the restored original is readable)
    e1, _ = run('E1', ['service', '--config', str(full), 'verified-backup', '--source-version', '0.6.25', '--output',
                       f'{D}/with-images.dump'], full)
    tables = json.loads((D / 'with-images.dump.manifest.json').read_text())['tables']
    log[-1]['checked'] = {'restore_verified': e1['restore_verified'], 'image_tables': sorted(t for t in tables if t.startswith('image_'))}
    log[-1]['stdout_excerpt'] = '(omitted: manifest)'
    run('E2', ['service', '--config', str(tgt), 'restore-target', '--dump', f'{D}/with-images.dump', '--manifest',
               f'{D}/with-images.dump.manifest.json', '--apply'], tgt)
    run('E3', ['image', 'original', orig, '--output', f'{WORK}/restored.png'], tgt)
    log[-1]['checked'] = {'sha_matches': hashlib.sha256((WORK / 'restored.png').read_bytes()).hexdigest() == b2['original']['sha256']}
    # Part D
    ev, _ = run('D1', ['evidence', 'show', doc, '--json'], full)
    src = ev['sources']['items'][0]
    log[-1]['checked'] = {'origin': src.get('origin')}
    log[-1]['stdout_excerpt'] = '(omitted)'
    run('D2', ['evidence', 'source-state', src['source_key'], '--state', 'removed', '--reason', 'withdrawn by owner',
               '--document', doc, '--expected-version', src['source_version']], full)
    run('D3', ['image', 'show', doc], full, expect=1)
    run('D3-reupload', ['image', 'add', str(FIXTURES / 'invoice.png'), '--domain', 'finance', '--project', '/projects/beta'], full, expect=1)
    _, gone = run('D3-search', ['search', 'RE-2026-0471', '--strategy', 'lexical', '--project', '/projects/beta', '--domain', 'finance'], full)
    log[-1]['checked'] = {'found': 'image-text-' in gone}
OUT.write_text(json.dumps({'source': '0.6.23 c33e11f seeded with archived code', 'port': os.environ.get('PGPORT'),
                           'steps': log}, indent=1, ensure_ascii=False))
print('ok', len(log))
