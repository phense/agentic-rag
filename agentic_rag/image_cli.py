"""`rag image add|show|original|backfill|references` (RAG-070).

Local mode uses the audited gateway directly; client mode uploads bytes to the
central service and never sends a local path. Output is JSON; errors are bounded
codes on stderr (exit 1), never image content.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys


def add_parser(sub) -> None:
    p = sub.add_parser('image', help='opt-in local image OCR and interpretation with retained originals')
    s = p.add_subparsers(dest='image_cmd', required=True)
    a = s.add_parser('add', help='validate, retain and OCR one explicit local image file')
    a.add_argument('path')
    a.add_argument('--domain', required=True)
    where = a.add_mutually_exclusive_group()
    where.add_argument('--project')
    where.add_argument('--scope', choices=['global', 'unknown'])
    a.add_argument('--label')
    a.add_argument('--vision', action='store_true', help='also request the configured local interpretation')
    show = s.add_parser('show', help='original metadata, derivations and word regions (no bytes)')
    show.add_argument('ref', help='original UUID or derived document ID/slug')
    show.add_argument('--cursor', type=int, default=0)
    show.add_argument('--limit', type=int, default=200)
    o = s.add_parser('original', help='write the exact retained original to a new private file')
    o.add_argument('ref')
    o.add_argument('--output', type=Path, required=True)
    b = s.add_parser('backfill', help='explicit manifest: --dry-run preview, --apply bounded batch, --cancel')
    b.add_argument('manifest', type=Path)
    mode = b.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--cancel', action='store_true')
    b.add_argument('--limit', type=int, default=10)
    b.add_argument('--state-dir', type=Path)
    b.add_argument('--vision', action='store_true')
    b.add_argument('--resume', action='store_true', help='continue after an explicit --cancel')
    b.add_argument('--restart', action='store_true', help='start again at the first item (idempotent)')
    r = s.add_parser('references', help='read-only candidate image references in stored text (never fetched)')
    r.add_argument('--domain')
    r.add_argument('--limit', type=int, default=50)


def _print(value):
    from .mcp_server import _plain
    print(json.dumps(_plain(value), ensure_ascii=False, sort_keys=True))


def _write_new(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _local(cfg, args):
    from . import db, images, image_media
    if args.image_cmd == 'add':
        data = image_media.read_file(args.path)
        with db.connect(cfg, role='writer') as conn:
            return images.ingest(conn, cfg, data, domain=args.domain, project=args.project, scope=args.scope,
                                 label=args.label, vision=args.vision, actor='cli')
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if args.image_cmd == 'show':
            return images.inspect(conn, args.ref, cursor=args.cursor, limit=args.limit)
        if args.image_cmd == 'original':
            return images.original(conn, args.ref)
        return images.references(conn, domain=args.domain, limit=args.limit)


def _remote(cfg, args):
    from . import image_media
    from .service.client import RemoteConnection
    from urllib.parse import quote
    if args.image_cmd == 'references':
        raise ValueError('unsupported_in_client_mode: references reads the service database; run it on the service host')
    with RemoteConnection(cfg) as client:
        if args.image_cmd == 'add':
            data = image_media.read_file(args.path)
            params = {k: v for k, v in {'domain': args.domain, 'project': args.project, 'scope': args.scope,
                                         'label': args.label}.items() if v is not None}
            return client.upload_image(data, params, vision=args.vision)
        if args.image_cmd == 'show':
            return client.image_json('GET', '/v1/images/' + quote(args.ref, safe=''),
                                     params={'cursor': args.cursor, 'limit': args.limit})
        return client.image_original(quote(args.ref, safe=''))


def _backfill(cfg, args):
    from . import image_backfill
    if args.dry_run:
        return 0, image_backfill.preview(cfg, args.manifest, vision=args.vision)
    if args.cancel:
        return 0, image_backfill.cancel(cfg, args.manifest, state_dir=args.state_dir)
    stop = {'requested': False}
    def request_stop(signum, frame):
        stop['requested'] = True  # finish the current bounded item, then persist the cursor
    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        result = image_backfill.apply(cfg, args.manifest, limit=args.limit, state_dir=args.state_dir,
                                      should_stop=lambda: stop['requested'], resume=args.resume,
                                      restart=args.restart, vision=args.vision)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return (1 if any(p['state'] == 'failed' for p in result['processed']) else 0), result


def run(args, cfg) -> int:
    from .image_engines import EngineError
    from .image_media import ImageRejected
    from .images import ImageUnavailable
    from .service.client import RemoteError
    try:
        if args.image_cmd == 'backfill':
            code, result = _backfill(cfg, args)
            _print(result)
            return code
        result = _remote(cfg, args) if cfg.service_mode == 'client' else _local(cfg, args)
        if args.image_cmd == 'original':
            data, meta = result
            try:
                _write_new(args.output, data)
            except FileExistsError:
                print('error: output file exists; choose a new path', file=sys.stderr)
                return 1
            _print({'written': str(args.output), **meta})
            return 0
        _print(result)
        if args.image_cmd == 'add' and any(d['state'] == 'failed' for d in result['derivations']):
            return 1
        return 0
    except (ImageRejected, EngineError, ImageUnavailable, RemoteError) as error:
        print(f'error: {error.code}', file=sys.stderr)
        return 1
    except PermissionError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
