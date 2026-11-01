"""Operator gateway for proven native-host source misattribution.

Preserve original rows and pending batches. Withdraw trust in exact generated
source identities, including tombstones for old batches not yet attached.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat

from . import db, evidence
from .mining_window import _content
from .transcript_origin import conversation_record
from .validity import parse_time

MAX_BYTES = 64 * 1024 * 1024
MAX_GENERATED = 4096


def scan(path):
    # Nonblocking open plus fstat refuses FIFOs/devices before any read.
    fd = os.open(Path(path), os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('source_origin_regular_recording_required')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('source_origin_recording_too_large')
    if raw and not raw.endswith(b'\n'):
        raise ValueError('source_origin_incomplete_recording')
    chain = hashlib.sha256()
    generated = []
    for number, line in enumerate(io.BytesIO(raw)):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            raise ValueError('source_origin_malformed_recording') from None
        chain.update(line)
        if not isinstance(event, dict) or conversation_record(event):
            continue
        _, text = _content(event)
        if not text:
            continue
        message = event.get('message', event.get('payload', {}))
        role = message.get('role') if isinstance(message, dict) else None
        if role not in {'user', 'assistant'}:
            continue
        try:
            timestamp = parse_time(event.get('timestamp'))
        except (ValueError, TypeError):
            timestamp = None
        generated.append({'source_id': f'{number}:{chain.hexdigest()}',
                          'role': role, 'source_at': timestamp})
        if len(generated) > MAX_GENERATED:
            raise ValueError('source_origin_generated_limit')
    return hashlib.sha256(raw).hexdigest(), generated


def filter_window(conn, namespace, window):
    """Filter proven generated events in old staged windows before inference.

    Immutable accepted batches retain their original replay path; removed source
    tombstones still withhold their claims when those batches attach evidence.
    """
    if not window.events:
        return window
    keys = [evidence._hash(json.dumps([namespace, event['source_id']], ensure_ascii=False))
            for event in window.events]
    excluded = {row['source_id'] for row in conn.execute(
        "SELECT source_id FROM knowledge_sources WHERE source_key=ANY(%s) "
        "AND state='removed' AND starts_with(reason,'native_generated_origin:')", (keys,))}
    if not excluded:
        return window
    from dataclasses import replace
    events = tuple(event for event in window.events if event['source_id'] not in excluded)
    return replace(window, text='\n'.join(event['text'] for event in events), events=events)


def quarantine(conn, namespace, sources, *, proof):
    """Audited atomic trust withdrawal; callers hold the stopped-writer fence.

    Existing source identity and text stay intact. Orphan removed sources are
    intentional: attachment of an already accepted old batch cannot reset trust.
    """
    from .service.context import CURRENT
    if CURRENT.get() is not None:
        raise ValueError('source_origin_local_operator_required')
    prepared = []
    for source in sources:
        key = evidence._hash(json.dumps([namespace, source['source_id']], ensure_ascii=False))
        prepared.append((key, source))
    changed = 0
    with conn.transaction():
        for key, _ in sorted(prepared):
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (evidence._lock_key(key),))
        # Validate the entire recording's existing metadata before any write.
        for key, source in prepared:
            existing = conn.execute('SELECT role,source_at FROM knowledge_sources WHERE source_key=%s FOR UPDATE', (key,)).fetchone()
            if existing and (existing['role'] != source['role'] or existing['source_at'] != source['source_at']):
                raise ValueError('source_origin_metadata_conflict')
        for key, source in prepared:
            conn.execute('INSERT INTO knowledge_sources(source_key,namespace,source_id,role,source_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (key, namespace, source['source_id'], source['role'], source['source_at']))
            current = conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (key,)).fetchone()
            if current['state'] != 'active':
                continue
            evidence.source_state(conn, key, state='removed',
                                  reason='native_generated_origin:' + proof,
                                  actor='source-origin-upgrade', commit=False)
            changed += 1
    return changed


def audit(cfg, path, namespace, *, apply=False, expected_sha256=None, writers_stopped=False):
    from .service.context import CURRENT
    if CURRENT.get() is not None or cfg.service_mode == 'client':
        raise ValueError('source_origin_local_operator_required')
    if not isinstance(namespace, str) or len(namespace) > 1000 or not (
        re.fullmatch(r'session:[^\x00-\x20]{1,256}', namespace)
        or re.fullmatch(r'svc1:[0-9a-f]{64}:[0-9a-f]{64}', namespace)
    ):
        raise ValueError('source_origin_explicit_session_namespace_required')
    digest, sources = scan(path)
    if apply and (not writers_stopped or expected_sha256 != digest):
        raise ValueError('source_origin_requires_stopped_writers_and_exact_digest')
    with db.connect(cfg) as conn:
        if not apply:
            conn.execute('SET TRANSACTION READ ONLY')
        changed = quarantine(conn, namespace, sources, proof=digest) if apply else 0
    return {'format': 1, 'applied': apply, 'namespace': namespace,
            'recording_sha256': digest,
            'generated_source_ids': [source['source_id'] for source in sources],
            'generated_sources': len(sources), 'quarantined': changed,
            'coverage': 'provided complete recording and explicit namespace only',
            'original_rows_deleted': 0}
