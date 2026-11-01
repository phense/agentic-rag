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


def _recording(path):
    # Nonblocking open plus fstat refuses FIFOs/devices before any read.
    fd = os.open(Path(path), os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('source_origin_regular_recording_required')
        raw = stream.read(MAX_BYTES + 1)
    return _records(raw)


def _records(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('source_origin_recording_too_large')
    if raw and not raw.endswith(b'\n'):
        raise ValueError('source_origin_incomplete_recording')
    chain = hashlib.sha256()
    generated = []
    records = {}
    for number, line in enumerate(io.BytesIO(raw)):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            raise ValueError('source_origin_malformed_recording') from None
        chain.update(line)
        identity, text = _content(event) if isinstance(event, dict) else (None, '')
        message = event.get('message', event.get('payload', {})) if isinstance(event, dict) else {}
        role = message.get('role') if isinstance(message, dict) else None
        try:
            timestamp = parse_time(event.get('timestamp')) if isinstance(event, dict) else None
        except (ValueError, TypeError):
            timestamp = None
        source_id = f'{number}:{chain.hexdigest()}'
        records[source_id] = {'role': role, 'source_at': timestamp, 'text': text, 'identity': identity}
        if not isinstance(event, dict) or conversation_record(event):
            continue
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
    return hashlib.sha256(raw).hexdigest(), generated, records


def scan(path):
    digest, generated, _ = _recording(path)
    return digest, generated


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



def _cursor_covered(cursor, records):
    if not cursor:
        return True
    if not isinstance(cursor, str):
        return False
    if not cursor.startswith('mw1:'):
        return sum(r['identity'] == cursor for r in records.values()) == 1
    try:
        value = json.loads(cursor[4:])
        line, offset = value['line'], value['offset']
        record = records.get(f"{line}:{value['hash']}")
        return (type(line) is int and type(offset) is int and record is not None
                and 0 <= offset <= len(record['text']))
    except (ValueError, KeyError, TypeError):
        return False



def _window_covered(payload, records):
    if not _cursor_covered(payload.get('input_cursor'), records) or not _cursor_covered(payload.get('output_cursor'), records):
        return False
    for event in payload.get('window', {}).get('events', []):
        original = records.get(event.get('source_id'))
        offset, text = event.get('offset'), event.get('text')
        try:
            if not (original is not None and type(offset) is int and offset >= 0
                    and isinstance(text, str) and original['text'][offset:offset+len(text)] == text
                    and original['role'] == event.get('role')
                    and original['source_at'] == parse_time(event.get('timestamp'))):
                return False
        except (ValueError, TypeError):
            return False
    return True


def export_spool(path, partition, session, output):
    """Read an explicitly selected stopped client spool without modifying it.

    The exported bytes are the original retained recording, never reconstructed
    JSONL; hash-chain source IDs and pending-window cursors therefore survive.
    """
    import sqlite3
    from contextlib import closing
    path = Path(path).absolute()
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('source_origin_regular_spool_required')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT project,length(raw) bytes FROM sources WHERE partition=? AND session=?',
                           (partition, session)).fetchone()
        if row is None or row['bytes'] > MAX_BYTES:
            raise ValueError('source_origin_missing_or_oversized_recording')
        raw = conn.execute('SELECT raw FROM sources WHERE partition=? AND session=?',
                           (partition, session)).fetchone()['raw']
        digest, _, records = _records(raw)
        pending = list(conn.execute("SELECT id,payload FROM outbox WHERE partition=? AND session=? AND kind='window' ORDER BY rowid LIMIT 257",
                                    (partition, session)))
        if len(pending) > 256 or any(not _window_covered(json.loads(r['payload']), records) for r in pending):
            raise ValueError('source_origin_spool_coverage_conflict')
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {'format': 1, 'partition': partition, 'session': session, 'project': row['project'],
            'recording_sha256': digest, 'pending_windows': len(pending),
            'pending_window_ids': [r['id'] for r in pending], 'ready': True}

def _source_ids(value):
    if isinstance(value, dict):
        result = {value['source_id']} if isinstance(value.get('source_id'), str) else set()
        for item in value.values():
            result.update(_source_ids(item))
        return result
    if isinstance(value, list):
        return set().union(*(_source_ids(item) for item in value)) if value else set()
    return set()


def _coverage(conn, namespace, sources, records):
    """Read-only bounded preflight of the selected retained stream, not a census."""
    keys = [evidence._hash(json.dumps([namespace, s['source_id']], ensure_ascii=False)) for s in sources]
    existing = {r['source_key']: r for r in conn.execute(
        'SELECT source_key,role,source_at FROM knowledge_sources WHERE source_key=ANY(%s)', (keys,))}
    conflicts = [key for key, source in zip(keys, sources) if key in existing
                 and (existing[key]['role'] != source['role'] or existing[key]['source_at'] != source['source_at'])]
    unknown = [r['source_key'] for r in conn.execute(
        'SELECT source_key FROM knowledge_sources WHERE namespace=%s AND NOT (source_id=ANY(%s)) ORDER BY source_key LIMIT 257',
        (namespace, list(records)))]
    affected = [dict(r) for r in conn.execute(
        'SELECT DISTINCT d.id::text document_id,d.slug,assertion_eligible(d.id) eligible_before,'
        'a.value assertion_value FROM claim_evidence ce JOIN documents d ON d.id=ce.document_id '
        'LEFT JOIN fact_assertions a ON a.document_id=d.id '
        'WHERE ce.source_key=ANY(%s) ORDER BY document_id LIMIT 257', (keys,))]
    temporal = [dict(r) for r in conn.execute(
        'SELECT DISTINCT old.document_id::text document_id,d.slug,old.value,'
        'assertion_eligible(old.document_id) eligible_before '
        'FROM fact_assertions newer JOIN claim_evidence ce ON ce.document_id=newer.document_id '
        'JOIN documents nd ON nd.id=newer.document_id '
        'JOIN fact_assertions old ON old.entity=newer.entity AND old.attribute=newer.attribute '
        'JOIN documents d ON d.id=old.document_id '
        "WHERE ce.source_key=ANY(%s) AND newer.relation='replacement' "
        'AND d.domain=nd.domain AND d.project_scope=nd.project_scope '
        'AND old.event_at<newer.event_at ORDER BY document_id LIMIT 257', (keys,))]
    windows = list(conn.execute('SELECT id,payload,input_cursor,output_cursor,state FROM service_windows '
                                'WHERE session_id=%s ORDER BY created_at,id LIMIT 257', (namespace,)))
    uncovered = []
    for row in windows[:256]:
        if not _window_covered(row['payload'], records):
            uncovered.append(str(row['id']))
    batch_session = namespace[len('session:'):] if namespace.startswith('session:') else namespace
    batches = list(conn.execute('SELECT id,extraction FROM mining_batches WHERE session_id=%s '
                                'ORDER BY created_at,id LIMIT 257', (batch_session,)))
    missing_batches = [str(r['id']) for r in batches[:256] if not _source_ids(r['extraction']) <= records.keys()]
    overflow = len(windows) > 256 or len(batches) > 256 or len(affected) > 256 or len(unknown) > 256 or len(temporal) > 256
    return {'generated_source_keys': keys, 'metadata_conflicts': conflicts,
            'affected_claims': affected[:256], 'temporal_dependents': temporal[:256], 'uncovered_source_keys': unknown[:256],
            'window_coverage': {'total': len(windows), 'uncovered': uncovered},
            'batch_coverage': {'total': len(batches), 'uncovered': missing_batches},
            'overflow': overflow,
            'ready': not (conflicts or unknown or uncovered or missing_batches or overflow)}

def audit(cfg, path, namespace, *, apply=False, expected_sha256=None, writers_stopped=False):
    from .service.context import CURRENT
    if CURRENT.get() is not None or cfg.service_mode == 'client':
        raise ValueError('source_origin_local_operator_required')
    if not isinstance(namespace, str) or len(namespace) > 1000 or not (
        re.fullmatch(r'session:[^\x00-\x20]{1,256}', namespace)
        or re.fullmatch(r'svc1:[0-9a-f]{64}:[0-9a-f]{64}', namespace)
    ):
        raise ValueError('source_origin_explicit_session_namespace_required')
    digest, sources, records = _recording(path)
    if apply and (not writers_stopped or expected_sha256 != digest):
        raise ValueError('source_origin_requires_stopped_writers_and_exact_digest')
    with db.connect(cfg) as conn:
        if not apply:
            conn.execute('SET TRANSACTION READ ONLY')
        preview = _coverage(conn, namespace, sources, records)
        if apply and not preview['ready']:
            raise ValueError('source_origin_metadata_or_coverage_conflict')
        changed = quarantine(conn, namespace, sources, proof=digest) if apply else 0
        if apply:
            for item in preview['affected_claims'] + preview['temporal_dependents']:
                item['eligible_after'] = conn.execute('SELECT assertion_eligible(%s) e',
                                                     (item['document_id'],)).fetchone()['e']
    return {**preview, 'format': 2, 'applied': apply, 'namespace': namespace,
            'recording_sha256': digest,
            'generated_source_ids': [source['source_id'] for source in sources],
            'generated_sources': len(sources), 'quarantined': changed,
            'coverage': 'provided complete recording and explicit namespace only',
            'original_rows_deleted': 0}
