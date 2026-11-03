"""Explicit, previewable, bounded and resumable historical image processing (IC-004).

Input is an operator-written manifest; nothing is discovered automatically:

    {"version": 1, "items": [
        {"path": "receipts/2026-11.png", "domain": "finance", "project": "/srv/books"},
        {"original": "<retained original UUID>"}]}

Relative paths resolve against the manifest's directory. Only regular files are
read (no symlinks, devices, URLs). `original` items reprocess an already retained
original with the current engines and are operator-local only.

Progress is a private cursor file per manifest digest. It is a convenience: a lost
or concurrent cursor is safe because publication is idempotent in PostgreSQL.
"""
from __future__ import annotations

from collections import Counter
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path

from . import image_media, images
from .image_engines import EngineError

MAX_ITEMS = 10000
MANIFEST_BYTES = 4 * 1024 * 1024
MAX_LIMIT = 1000
DEFAULT_STATE = Path.home() / '.agentic-rag' / 'state' / 'image-backfill'
_PATH_KEYS = {'path', 'domain', 'project', 'scope', 'label'}


@dataclass(frozen=True)
class Item:
    index: int
    path: Path | None
    original: str | None
    domain: str | None
    project: str | None
    scope: str | None
    label: str | None


def load_manifest(path):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ValueError('manifest_unavailable') from None
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('manifest_unavailable')
        raw = stream.read(MANIFEST_BYTES + 1)
    if len(raw) > MANIFEST_BYTES:
        raise ValueError('manifest_too_large')
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError('invalid_manifest') from None
    if not isinstance(data, dict) or set(data) != {'version', 'items'} or data['version'] != 1:
        raise ValueError('invalid_manifest: version 1 with items required')
    entries = data['items']
    if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
        raise ValueError(f'invalid_manifest: at most {MAX_ITEMS} items')
    items, base = [], path.resolve().parent
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f'invalid_manifest: item {index}')
        if set(entry) == {'original'} and isinstance(entry['original'], str):
            items.append(Item(index, None, entry['original'], None, None, None, None))
            continue
        if 'path' not in entry or not set(entry) <= _PATH_KEYS or not isinstance(entry.get('domain'), str) or not all(
                isinstance(entry.get(k), (str, type(None))) for k in _PATH_KEYS) or not entry['path']:
            raise ValueError(f'invalid_manifest: item {index} needs path and domain only')
        if '://' in entry['path'] or '\x00' in entry['path']:
            raise ValueError(f'invalid_manifest: item {index} must be a local file path')
        location = Path(entry['path'])
        items.append(Item(index, location if location.is_absolute() else base / location, None, entry['domain'],
                          entry.get('project'), entry.get('scope'), entry.get('label')))
    return items, hashlib.sha256(raw).hexdigest()


def _client(cfg):
    if cfg.service_mode != 'client':
        return None
    from .service.client import RemoteConnection
    return RemoteConnection(cfg)


def _classify_file(item):
    try:
        data = image_media.read_file(item.path)
    except image_media.ImageRejected as rejected:
        return None, {'disposition': 'missing' if rejected.code == 'image_file_unavailable' else 'invalid',
                      'code': rejected.code}
    try:
        info = image_media.sniff(data)
    except image_media.ImageRejected as rejected:
        return None, {'disposition': 'invalid', 'code': rejected.code}
    return info, None


def preview(cfg, manifest_path, *, vision=False):
    """Classify every item: selected, unchanged, changed, missing, unauthorized, invalid, withdrawn."""
    items, digest = load_manifest(manifest_path)
    results, sizes, pending = [None] * len(items), {}, []
    for item in items:
        if item.path is None:
            continue
        info, outcome = _classify_file(item)
        if outcome is not None:
            results[item.index] = outcome
        else:
            sizes[item.index] = info.byte_size
            pending.append((item, {'sha256': info.sha256, 'domain': item.domain, 'project': item.project,
                                   'scope': item.scope}))
    client = _client(cfg)
    identities = None
    if client is None:
        from . import db
        identities = images.current_identities(cfg, vision=vision)
        with db.connect(cfg, role='reader') as conn:
            for item, query in pending:
                results[item.index] = images.status(conn, cfg, [query], identities=identities)[0]
            for item in items:
                if item.original is not None:
                    results[item.index] = images.original_status(conn, item.original, identities=identities)
                    conn.rollback()
    else:
        with client:
            for start in range(0, len(pending), 100):
                chunk = pending[start:start + 100]
                answer = client.image_json('POST', '/v1/images/status', {'items': [q for _, q in chunk]})
                for (item, _), result in zip(chunk, answer['items']):
                    results[item.index] = result
                identities = answer.get('identities')
        for item in items:
            if item.original is not None:
                results[item.index] = {'disposition': 'unsupported_in_client_mode'}
    work = [i for i, r in enumerate(results) if r['disposition'] in ('selected', 'changed')]
    return {'manifest_sha256': digest, 'items': [{'index': i, **r} for i, r in enumerate(results)],
            'counts': dict(sorted(Counter(r['disposition'] for r in results).items())),
            'estimated_engine_items': len(work), 'estimated_bytes': sum(sizes.get(i, 0) for i in work),
            'identities': identities, 'engine_calls': 0, 'writes': 0}


def _private_dir(state_dir):
    state_dir = Path(state_dir or DEFAULT_STATE)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    return state_dir


def _write_state(path, state):
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(state, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_state(path, digest, total):
    try:
        state = json.loads(path.read_text())
        if state.get('manifest_sha256') == digest and state.get('total') == total:
            return state
    except (OSError, ValueError):
        pass
    return {'format': 1, 'manifest_sha256': digest, 'total': total, 'cursor': 0, 'state': 'new', 'counts': {}}


def _public(state, marker):
    return {**state, 'cancel_requested': marker.exists()}


def cancel(cfg, manifest_path, *, state_dir=None):
    _, digest = load_manifest(manifest_path)
    directory = _private_dir(state_dir)
    marker = directory / (digest + '.cancel')
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    state = _read_state(directory / (digest + '.json'), digest, None)
    return {'run': _public(state, marker)}


@contextlib.contextmanager
def _exclusive(directory, digest):
    fd = os.open(directory / (digest + '.lock'), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('backfill_already_running') from None
        yield
    finally:
        os.close(fd)


def _summary(result):
    states = [d['state'] for d in result['derivations']]
    failed = [d for d in result['derivations'] if d['state'] == 'failed']
    out = {'original_id': result['original']['id'],
           'document_ids': [d['document_id'] for d in result['derivations'] if d.get('document_id')]}
    if failed:
        return {'state': 'failed', 'code': failed[0]['code'], **out}
    if all(s == 'existing' for s in states):
        return {'state': 'existing', **out}
    return {'state': 'published' if 'published' in states else 'empty', **out}


def _process(cfg, conn, client, item, vision):
    try:
        if item.original is not None:
            if client is not None:
                return {'state': 'skipped', 'code': 'unsupported_in_client_mode'}
            return _summary(images.reprocess(conn, cfg, item.original, vision=vision, actor='backfill'))
        data = image_media.read_file(item.path)
        params = {'domain': item.domain, 'project': item.project, 'scope': item.scope, 'label': item.label}
        if client is not None:
            return _summary(client.upload_image(data, {k: v for k, v in params.items() if v is not None}, vision=vision))
        return _summary(images.ingest(conn, cfg, data, vision=vision, actor='backfill', **params))
    except image_media.ImageRejected as rejected:
        return {'state': 'missing' if rejected.code == 'image_file_unavailable' else 'invalid', 'code': rejected.code}
    except images.ImageUnavailable:
        return {'state': 'unavailable', 'code': 'image_unavailable'}
    except PermissionError:
        return {'state': 'unauthorized', 'code': 'scope_denied'}
    except EngineError:
        raise  # an unavailable engine stops the run before any further item
    except ValueError as error:
        if str(error) in ('images_disabled', 'vision_disabled'):
            raise
        return {'state': 'unauthorized' if str(error).startswith('unknown domain') else 'invalid',
                'code': 'unknown_domain' if str(error).startswith('unknown domain') else 'invalid_item'}
    # Transport/service errors are never evidence of a bad manifest item.
    # Let apply persist an interrupted cursor at this exact item and propagate.


def apply(cfg, manifest_path, *, limit=10, state_dir=None, should_stop=None, resume=False, restart=False,
          vision=False):
    """Process at most `limit` items from the durable cursor, one bounded item at a time."""
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be between 1 and {MAX_LIMIT}')
    client = _client(cfg)
    if client is None and not cfg.image_enabled:
        raise ValueError('images_disabled')
    items, digest = load_manifest(manifest_path)
    directory = _private_dir(state_dir)
    path, marker = directory / (digest + '.json'), directory / (digest + '.cancel')
    with _exclusive(directory, digest):
        state = _read_state(path, digest, len(items))
        if restart:
            state.update(cursor=0, counts={}, state='new')
        if resume or restart:
            marker.unlink(missing_ok=True)
        processed = []
        if marker.exists():
            state['state'] = 'canceled'
            _write_state(path, state)
            return {'run': _public(state, marker), 'processed': processed}
        if state['cursor'] >= len(items):
            state['state'] = 'complete'
            _write_state(path, state)
            return {'run': _public(state, marker), 'processed': processed}
        from . import db
        conn = None if client is not None else db.connect(cfg, role='writer')
        try:
            with (client or contextlib.nullcontext()):
                state['state'] = 'running'
                while state['cursor'] < len(items) and len(processed) < limit:
                    if (should_stop is not None and should_stop()) or marker.exists():
                        state['state'] = 'canceled'
                        break
                    item = items[state['cursor']]
                    outcome = {'index': item.index, **_process(cfg, conn, client, item, vision)}
                    processed.append(outcome)
                    state['counts'][outcome['state']] = state['counts'].get(outcome['state'], 0) + 1
                    if outcome['state'] == 'failed':
                        state['state'] = 'blocked'
                        state['last_error'] = outcome
                        break
                    state.pop('last_error', None)
                    state['cursor'] += 1
                    _write_state(path, state)
                else:
                    state['state'] = 'complete' if state['cursor'] >= len(items) else 'paused'
        except BaseException:
            state['state'] = 'interrupted'
            _write_state(path, state)
            raise
        finally:
            if conn is not None:
                conn.close()
        _write_state(path, state)
        return {'run': _public(state, marker), 'processed': processed}
