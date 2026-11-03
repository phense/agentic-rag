"""Audited source-backed image gateway (RAG-070).

Every image write passes through `ingest`; every original/region read through
`inspect`/`original`. Sequence (docs/uml/image-ingestion-70.md):

1. Admission: feature enabled, bytes sniffed, write scope authorized, engines
   resolved and the image completely decoded. Any failure here writes nothing.
2. Tx A accepts the original: one knowledge source per scoped original (role
   `unknown`, never user testimony) and the exact retained bytes. A withdrawn
   source is refused and never reset.
3. Engine work runs without a transaction or lock. An existing derivation for
   the same original, kind and identity is reused with zero engine calls.
4. Tx B publishes one derivation atomically: claim document and spans through
   the evidence gateway, the derivation row and its audit record. OCR is a
   `stated` machine transcription with partial spans; interpretation is an
   `inference`. Both stay ineligible until an explicit confirmation.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid as uuidlib

from . import evidence, image_media
from .image_engines import EngineError, OllamaVision, TesseractEngine, identity_hash
from .secrets import strip_secrets

NAMESPACE = 'image1:'
SPAN_CHARS = 4000
MAX_SPANS = 8
VIEW_TEXT_CHARS = 8000
VIEW_DERIVATIONS = 20
REGION_PAGE = 500
CLAIM_KIND = {'ocr': 'stated', 'interpretation': 'inference'}
TITLE = {'ocr': 'Image text', 'interpretation': 'Image interpretation'}


class ImageUnavailable(ValueError):
    """Absent, foreign and withdrawn images share one non-oracular outcome."""
    def __init__(self):
        super().__init__('image_unavailable')
        self.code = 'image_unavailable'


def ocr_engine_for(cfg):
    return TesseractEngine.from_config(cfg)


def vision_engine_for(cfg):
    return OllamaVision.from_config(cfg)


def _request():
    from .service.context import CURRENT
    return CURRENT.get()


def _selected(project, scope):
    from .scope import write_scope
    if project is not None:
        project = strip_secrets(project)[0]
    return project, write_scope(project, scope) or 'unknown'


def source_identity(sha256, domain, selected):
    """Scoped source key; centrally also bound to the authenticated owner namespace."""
    base = NAMESPACE + hashlib.sha256(json.dumps([domain, selected], ensure_ascii=False).encode()).hexdigest()
    request = _request()
    namespace = f'svc1:{request.principal.namespace}:{base}' if request is not None else base
    source_id = 'sha256:' + sha256
    return namespace, source_id, evidence._hash(json.dumps([namespace, source_id], ensure_ascii=False))


def authorize(conn, domain, selected):
    request = _request()
    if request is not None and (request.read_only or request.principal.readonly
                                or not request.principal.can_write(domain, selected)):
        raise PermissionError('scope_denied')
    if not isinstance(domain, str) or not conn.execute('SELECT 1 FROM domains WHERE name=%s', (domain,)).fetchone():
        raise ValueError(f'unknown domain: {domain}')


def _audit(conn, actor, op, doc_id, text):
    conn.execute('INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,%s,%s,%s)', (actor, op, doc_id, text))


def _accept(conn, *, data, info, domain, selected, actor):
    namespace, source_id, key = source_identity(info.sha256, domain, selected)
    try:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (evidence._lock_key(key),))
        source = conn.execute('SELECT state,role,source_at FROM knowledge_sources WHERE source_key=%s', (key,)).fetchone()
        if source is None:
            conn.execute('INSERT INTO knowledge_sources(source_key,namespace,source_id,role,source_at)'
                         " VALUES (%s,%s,%s,'unknown',NULL) ON CONFLICT DO NOTHING", (key, namespace, source_id))
            source = conn.execute('SELECT state,role,source_at FROM knowledge_sources WHERE source_key=%s', (key,)).fetchone()
        if source is None or source['state'] != 'active' or source['role'] != 'unknown' or source['source_at'] is not None:
            raise ImageUnavailable()
        row = conn.execute(
            'INSERT INTO image_originals(source_key,domain,project_scope,sha256,mime,width,height,byte_size,bytes,created_by)'
            ' VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_key) DO NOTHING RETURNING id',
            (key, domain, selected, info.sha256, info.mime, info.width, info.height, info.byte_size, data, actor)).fetchone()
        created = row is not None
        if not created:
            row = conn.execute('SELECT id,sha256,erased_at FROM image_originals WHERE source_key=%s', (key,)).fetchone()
            if row is None or row['sha256'] != info.sha256 or row['erased_at'] is not None:
                raise ImageUnavailable()
        else:
            _audit(conn, actor, 'image_original', None,
                   f'retained original {row["id"]} ({info.mime} {info.width}x{info.height}, {info.byte_size} bytes,'
                   f' sha256 {info.sha256}) in {domain}')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {'id': str(row['id']), 'sha256': info.sha256, 'mime': info.mime, 'width': info.width,
            'height': info.height, 'byte_size': info.byte_size, 'source_key': key, 'created': created,
            '_namespace': namespace, '_source_id': source_id, '_scope': selected}


def _sanitize(text, regions):
    """Secret-strip text and every region; a word removed from the text is redacted too."""
    clean, count = strip_secrets(text)
    out = []
    for region in regions:
        word, n = strip_secrets(region['text'])
        if count or n:
            word = '[REDACTED]'
        out.append({**region, 'text': word})
    return clean, out, count > 0


def _spans(text):
    if len(text) <= SPAN_CHARS:
        return [text]
    spans, current = [], ''
    for line in text.split('\n'):
        candidate = line if not current else current + '\n' + line
        if len(candidate) <= SPAN_CHARS:
            current = candidate
            continue
        if current:
            spans.append(current)
        current = line
        while len(current) > SPAN_CHARS:
            spans.append(current[:SPAN_CHARS])
            current = current[SPAN_CHARS:]
    if current:
        spans.append(current)
    if len(spans) > MAX_SPANS:
        spans = [text[i:i + SPAN_CHARS] for i in range(0, len(text), SPAN_CHARS)]
    if len(spans) > MAX_SPANS:
        raise EngineError('ocr_output_too_large')
    return spans


def _existing(conn, original_id, kind, digest):
    return conn.execute('SELECT d.id,d.status,d.warnings,d.document_id,c.review_state FROM image_derivations d'
                        ' LEFT JOIN claim_records c ON c.document_id=d.document_id'
                        ' WHERE d.original_id=%s AND d.kind=%s AND d.identity_hash=%s',
                        (original_id, kind, digest)).fetchone()


def _outcome(kind, state, row):
    return {'kind': kind, 'state': state, 'derivation_id': str(row['id']),
            'document_id': str(row['document_id']) if row['document_id'] else None,
            'review_state': row['review_state'] if row['document_id'] else None,
            'status': row['status'], 'warnings': list(row['warnings'])}


def _derive(conn, cfg, original, kind, engine, identity, data, info, *, domain, project, scope, label, actor):
    digest = identity_hash(identity)
    try:
        row = _existing(conn, original['id'], kind, digest)
    finally:
        conn.rollback()  # never hold a snapshot or lock during engine work
    if row is not None:
        return _outcome(kind, 'existing', row)
    try:
        result = engine.recognize(data, info) if kind == 'ocr' else engine.interpret(data, info)
        if result.identity != identity:
            raise EngineError(kind.replace('interpretation', 'vision') + '_identity_changed')
        regions = list(getattr(result, 'regions', []))
        text, regions, redacted = _sanitize(result.text, regions)
        warnings = sorted(set(result.warnings) | ({'secret_redacted', 'original_quarantined'} if redacted else set()))
        empty = not text.strip() or (kind == 'interpretation' and 'low_information_output' in warnings)
        spans = [] if empty else _spans(text)
    except EngineError as error:
        return {'kind': kind, 'state': 'failed', 'code': error.code}
    from .service.engine import JobBlocked
    try:
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (evidence._lock_key(original['source_key']),))
        visible = conn.execute('SELECT o.id FROM image_originals o JOIN knowledge_sources s USING(source_key)'
                               " WHERE o.id=%s AND s.state='active'", (original['id'],)).fetchone()
        if visible is None:
            raise ImageUnavailable()
        row = _existing(conn, original['id'], kind, digest)
        if row is not None:
            conn.rollback()
            return _outcome(kind, 'existing', row)
        text_sha = hashlib.sha256(text.encode()).hexdigest()
        previous = conn.execute('SELECT id FROM image_derivations WHERE original_id=%s AND kind=%s'
                                ' ORDER BY created_at DESC,id LIMIT 1', (original['id'], kind)).fetchone()
        doc_id = None
        if not empty:
            items = [{'namespace': original['_namespace'], 'source_id': original['_source_id'], 'role': 'unknown',
                      'quote': span, 'complete': False} for span in spans]
            reuse = conn.execute('SELECT d.document_id FROM image_derivations d JOIN documents doc ON doc.id=d.document_id'
                                 " WHERE d.original_id=%s AND d.kind=%s AND d.text_sha256=%s AND doc.status='active'"
                                 ' ORDER BY d.created_at,d.id LIMIT 1', (original['id'], kind, text_sha)).fetchone()
            if reuse:
                doc_id = str(reuse['document_id'])
                evidence.attach(conn, doc_id, items, actor)  # never resets review or trust
            else:
                title = TITLE[kind] + (': ' + label if label else ' ' + original['sha256'][:12])
                # Deterministic per scoped source: a slug probe under RLS cannot see
                # (and must not collide with) the same image in a foreign scope.
                from .chunker import slugify
                suffix = hashlib.sha256(json.dumps([original['source_key'], kind, text_sha]).encode()).hexdigest()[:16]
                saved = evidence.save(conn, cfg, title=title, body=text, domain=domain, dtype='source',
                                      slug=f'{slugify(title)[:60].strip("-") or "image"}-{suffix}',
                                      claim_kind=CLAIM_KIND[kind], evidence=items, project=project, scope=scope,
                                      provenance={'origin': 'image', 'image_kind': kind}, actor=actor, commit=False)
                doc_id = saved.doc_id
            scoped = conn.execute('SELECT project_scope,domain FROM documents WHERE id=%s', (doc_id,)).fetchone()
            if scoped is None or (scoped['domain'], scoped['project_scope']) != (domain, original['_scope']):
                raise ValueError('image claim scope differs from its original')
        inserted = conn.execute(
            'INSERT INTO image_derivations(original_id,kind,identity_hash,identity,status,text,text_sha256,regions,'
            'warnings,document_id,previous_id,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (original['id'], kind, digest, json.dumps(identity), 'empty' if empty else 'text', text, text_sha,
             json.dumps(regions), json.dumps(warnings), doc_id, previous['id'] if previous else None, actor)).fetchone()
        if redacted:
            # Retained pixels cannot be text-redacted. Withdraw the whole source,
            # atomically with publication, rather than expose the credential image.
            evidence.source_state(conn, original['source_key'], state='removed',
                reason='image_secret_detected: original quarantined; operator erasure required',
                actor=actor, commit=False)
        _audit(conn, actor, 'image_derivation', doc_id,
               f'{kind} derivation {inserted["id"]} of original {original["id"]}, identity {digest[:16]},'
               f' {len(regions)} regions, {"empty" if empty else "text"}')
        conn.commit()
    except JobBlocked:
        conn.rollback()
        raise
    except ImageUnavailable:
        conn.rollback()
        return {'kind': kind, 'state': 'failed', 'code': 'image_unavailable'}
    except Exception:  # noqa: BLE001 - atomic failure: nothing of this derivation is published
        conn.rollback()
        try:
            row = _existing(conn, original['id'], kind, digest)
        finally:
            conn.rollback()
        if row is not None:  # a concurrent submission won the unique key
            return _outcome(kind, 'existing', row)
        return {'kind': kind, 'state': 'failed', 'code': 'publication_failed'}
    with_review = conn.execute('SELECT review_state FROM claim_records WHERE document_id=%s', (doc_id,)).fetchone() if doc_id else None
    conn.rollback()
    return {'kind': kind, 'state': 'empty' if empty else 'published', 'derivation_id': str(inserted['id']),
            'document_id': doc_id, 'review_state': with_review['review_state'] if with_review else None,
            'status': 'empty' if empty else 'text', 'warnings': warnings}


def ingest(conn, cfg, data, *, domain, project=None, scope=None, label=None, vision=False, actor='cli',
           ocr_engine=None, vision_engine=None):
    """Validate, retain and derive one image. Returns per-derivation outcomes."""
    if not cfg.image_enabled:
        raise ValueError('images_disabled')
    if type(vision) is not bool:
        raise ValueError('vision must be boolean')
    if vision and not cfg.image_vision_enabled:
        raise ValueError('vision_disabled')
    if label is not None:
        if not isinstance(label, str) or not 1 <= len(label) <= 200 or any(c in label for c in '\r\n\x00'):
            raise ValueError('label must be a single line of at most 200 characters')
        label = strip_secrets(label)[0]
    project, selected = _selected(project, scope)
    info = image_media.sniff(data)
    try:
        authorize(conn, domain, selected)
    finally:
        conn.rollback()
    engines, identities = _engines(cfg, vision, ocr_engine, vision_engine)  # unavailable: fail before writes
    info = image_media.validate(data, timeout=cfg.image_decode_timeout_seconds,
                                memory=cfg.image_engine_memory_bytes, workdir=cfg.image_work_dir)
    original = _accept(conn, data=bytes(data), info=info, domain=domain, selected=selected, actor=actor)
    outcomes = [_derive(conn, cfg, original, kind, engine, identity, bytes(data), info, domain=domain,
                        project=project, scope=scope, label=label, actor=actor)
                for (kind, engine), identity in zip(engines, identities)]
    return {'original': {k: v for k, v in original.items() if not k.startswith('_')}, 'derivations': outcomes}


def _engines(cfg, vision, ocr_engine, vision_engine):
    engines = [('ocr', ocr_engine or ocr_engine_for(cfg))]
    if vision:
        engines.append(('interpretation', vision_engine or vision_engine_for(cfg)))
    return engines, [engine.identity() for _, engine in engines]


def current_identities(cfg, *, vision=False, ocr_engine=None, vision_engine=None):
    engines, identities = _engines(cfg, vision, ocr_engine, vision_engine)
    return {kind: identity_hash(identity) for (kind, _), identity in zip(engines, identities)}


def reprocess(conn, cfg, original_id, *, vision=False, actor='cli', ocr_engine=None, vision_engine=None):
    """Operator-local derivation of a retained original with the current engines.

    Reuses the original's recorded source identity and scope (including a
    central owner namespace); never re-reads a path or rewrites the bytes.
    """
    if not cfg.image_enabled:
        raise ValueError('images_disabled')
    if vision and not cfg.image_vision_enabled:
        raise ValueError('vision_disabled')
    if _request() is not None:
        raise PermissionError('operator_local_configuration_required')
    try:
        uuidlib.UUID(str(original_id))
    except ValueError:
        raise ImageUnavailable() from None
    try:
        row = conn.execute('SELECT o.*,s.namespace,s.source_id,s.state FROM image_originals o'
                           ' JOIN knowledge_sources s USING(source_key) WHERE o.id=%s', (str(original_id),)).fetchone()
    finally:
        conn.rollback()
    if row is None or row['state'] != 'active' or row['bytes'] is None:
        raise ImageUnavailable()
    data = bytes(row['bytes'])
    if hashlib.sha256(data).hexdigest() != row['sha256']:
        raise RuntimeError('original_integrity_failed')
    engines, identities = _engines(cfg, vision, ocr_engine, vision_engine)
    info = image_media.validate(data, timeout=cfg.image_decode_timeout_seconds,
                                memory=cfg.image_engine_memory_bytes, workdir=cfg.image_work_dir)
    selected = row['project_scope']
    project, scope = (None, selected) if selected in ('global', 'unknown') else (selected, None)
    original = {'id': str(row['id']), 'sha256': row['sha256'], 'mime': row['mime'], 'width': row['width'],
                'height': row['height'], 'byte_size': row['byte_size'], 'source_key': row['source_key'],
                'created': False, '_namespace': row['namespace'], '_source_id': row['source_id'], '_scope': selected}
    outcomes = [_derive(conn, cfg, original, kind, engine, identity, data, info, domain=row['domain'],
                        project=project, scope=scope, label=None, actor=actor)
                for (kind, engine), identity in zip(engines, identities)]
    return {'original': {k: v for k, v in original.items() if not k.startswith('_')}, 'derivations': outcomes}


def original_status(conn, original_id, *, identities):
    """Preview disposition of one retained original; no write, no engine call."""
    try:
        uuidlib.UUID(str(original_id))
        row = conn.execute('SELECT o.id,s.state FROM image_originals o JOIN knowledge_sources s USING(source_key)'
                           ' WHERE o.id=%s', (str(original_id),)).fetchone()
    except ValueError:
        row = None
    if row is None:
        return {'disposition': 'missing'}
    if row['state'] != 'active':
        return {'disposition': 'withdrawn', 'original_id': str(row['id'])}
    missing = [kind for kind, digest in identities.items()
               if not conn.execute('SELECT 1 FROM image_derivations WHERE original_id=%s AND kind=%s AND identity_hash=%s',
                                   (row['id'], kind, digest)).fetchone()]
    return {'disposition': 'changed' if missing else 'unchanged', 'original_id': str(row['id']), 'pending': missing}


# ------------------------------------------------------------------ readers

_ORIGINAL_COLUMNS = 'o.id,o.source_key,o.domain,o.project_scope,o.sha256,o.mime,o.width,o.height,o.byte_size,o.created_at,o.erased_at'


def _resolve(conn, ref):
    if not isinstance(ref, str) or not 1 <= len(ref) <= 512:
        raise ImageUnavailable()
    row = None
    try:
        uuidlib.UUID(ref)
        row = conn.execute(f'SELECT {_ORIGINAL_COLUMNS} FROM image_originals o WHERE o.id=%s', (ref,)).fetchone()
        condition = 'doc.id=%s'
    except ValueError:
        condition = 'doc.slug=%s'
    if row is None:
        row = conn.execute(f'SELECT {_ORIGINAL_COLUMNS} FROM image_derivations d JOIN image_originals o ON o.id=d.original_id'
                           f' JOIN documents doc ON doc.id=d.document_id JOIN knowledge_sources ks ON ks.source_key=o.source_key'
                           f" WHERE {condition} AND o.erased_at IS NULL AND ks.state='active'"
                           " AND NOT EXISTS (SELECT 1 FROM image_derivations q WHERE q.original_id=o.id"
                           " AND q.warnings @> '[\"original_quarantined\"]'::jsonb) ORDER BY d.created_at LIMIT 1",
                           (ref,)).fetchone()
    if row is None or row['erased_at'] is not None:
        raise ImageUnavailable()
    source = conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (row['source_key'],)).fetchone()
    if source is None or source['state'] != 'active' or source_quarantined(conn, row['source_key']):
        raise ImageUnavailable()  # withdrawal disables original and region access
    return row


def source_quarantined(conn, source_key):
    """A persisted detection cannot be undone through normal trust transitions."""
    if not conn.execute("SELECT to_regclass('public.image_derivations') IS NOT NULL ok").fetchone()['ok']:
        return False
    return conn.execute("SELECT EXISTS(SELECT 1 FROM public.image_originals o JOIN public.image_derivations d"
        " ON d.original_id=o.id WHERE o.source_key=%s AND d.warnings @> '[\"original_quarantined\"]'::jsonb) ok",
        (source_key,)).fetchone()['ok']


def claim_derivation_state(conn, document_id):
    """Visible latest derivation identities; no cached eligibility or review decision.

    A new machine reading never overturns a human confirmation. Its difference
    is disclosed on the old claim and included in the optimistic review token.
    """
    if not conn.execute("SELECT to_regclass('public.image_derivations') IS NOT NULL ok").fetchone()['ok']:
        return []
    return conn.execute(
        'SELECT DISTINCT d.original_id,d.kind,latest.id,latest.identity_hash,latest.text_sha256,'
        'd.text_sha256<>latest.text_sha256 newer_differs FROM public.image_derivations d'
        ' CROSS JOIN LATERAL (SELECT n.id,n.identity_hash,n.text_sha256 FROM public.image_derivations n'
        ' WHERE n.original_id=d.original_id AND n.kind=d.kind ORDER BY n.created_at DESC,n.id DESC LIMIT 1) latest'
        ' WHERE d.document_id=%s ORDER BY d.original_id,d.kind,latest.id', (str(document_id),)).fetchall()


def claim_notices(conn, document_id):
    return ['newer_derivation_differs'] if any(r['newer_differs'] for r in claim_derivation_state(conn, document_id)) else []


def inspect(conn, ref, *, cursor=0, limit=200):
    """Original metadata (never bytes) and bounded derivations with region pages."""
    if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= REGION_PAGE:
        raise ValueError('invalid_limit')
    original = _resolve(conn, ref)
    rows = conn.execute(
        'SELECT d.id,d.kind,d.identity_hash,d.identity,d.status,left(d.text,%s) text,length(d.text)>%s text_truncated,'
        'd.warnings,d.document_id,d.previous_id,d.created_at,jsonb_array_length(d.regions) region_total,'
        'COALESCE((SELECT jsonb_agg(r ORDER BY n) FROM jsonb_array_elements(d.regions) WITH ORDINALITY x(r,n)'
        ' WHERE n>%s AND n<=%s),\'[]\'::jsonb) regions,c.kind claim_kind,c.review_state'
        ' FROM image_derivations d LEFT JOIN claim_records c ON c.document_id=d.document_id'
        ' WHERE d.original_id=%s ORDER BY d.created_at DESC,d.id LIMIT %s',
        (VIEW_TEXT_CHARS, VIEW_TEXT_CHARS, cursor, cursor + limit, original['id'], VIEW_DERIVATIONS)).fetchall()
    derivations = []
    for r in rows:
        derivations.append({
            'id': str(r['id']), 'kind': r['kind'], 'status': r['status'], 'identity_hash': r['identity_hash'],
            'identity': r['identity'], 'text': r['text'], 'text_truncated': r['text_truncated'],
            'warnings': sorted(set(r['warnings']) | set(claim_notices(conn, r['document_id']) if r['document_id'] else [])), 'transcription': 'machine' if r['kind'] == 'ocr' else 'model_inference',
            'document_id': str(r['document_id']) if r['document_id'] else None,
            'previous_id': str(r['previous_id']) if r['previous_id'] else None,
            'created_at': r['created_at'].isoformat(),
            'claim': ({'kind': r['claim_kind'], 'review_state': r['review_state']} if r['document_id'] else None),
            'regions': {'items': list(r['regions']), 'total': r['region_total'], 'cursor': cursor,
                        'next_cursor': cursor + limit if cursor + limit < r['region_total'] else None}})
    return {'original': {'id': str(original['id']), 'sha256': original['sha256'], 'mime': original['mime'],
                         'width': original['width'], 'height': original['height'], 'byte_size': original['byte_size'],
                         'domain': original['domain'], 'project_scope': original['project_scope'],
                         'source_key': original['source_key'], 'source_state': 'active',
                         'created_at': original['created_at'].isoformat()},
            'derivations': derivations, 'derivations_truncated': len(rows) >= VIEW_DERIVATIONS}


def original(conn, ref):
    """Exact retained bytes after the same authorization and trust checks."""
    row = _resolve(conn, ref)
    data = conn.execute('SELECT bytes FROM image_originals WHERE id=%s', (row['id'],)).fetchone()
    if data is None or data['bytes'] is None:
        raise ImageUnavailable()
    payload = bytes(data['bytes'])
    if hashlib.sha256(payload).hexdigest() != row['sha256']:
        raise RuntimeError('original_integrity_failed')
    return payload, {'id': str(row['id']), 'sha256': row['sha256'], 'mime': row['mime'], 'byte_size': row['byte_size']}


def status(conn, cfg, items, *, identities):
    """Preview dispositions for (sha256, domain, project/scope) items; no write, no engine call."""
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError('at most 100 status items')
    out = []
    for item in items:
        if not isinstance(item, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256', ''))):
            raise ValueError('invalid status item')
        try:
            project, selected = _selected(item.get('project'), item.get('scope'))
            authorize(conn, item.get('domain'), selected)
        except (PermissionError, ValueError, TypeError):
            out.append({'disposition': 'unauthorized'})
            continue
        _, _, key = source_identity(item['sha256'], item['domain'], selected)
        row = conn.execute('SELECT id FROM image_originals WHERE source_key=%s', (key,)).fetchone()
        out.append({'disposition': 'selected'} if row is None else original_status(conn, row['id'], identities=identities))
    conn.rollback()
    return out


_REFERENCE = re.compile(r'(?:https?://|/|\.{0,2}/|[A-Za-z0-9_-]+/)?[^\s()<>"\'\]\[]{1,200}\.(?:png|jpe?g|webp)\b', re.I)


def references(conn, *, domain=None, limit=50):
    """Read-only candidate image references in stored text. They are never fetched,
    resolved or treated as retained originals; missing provenance stays reported."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('invalid_limit')
    rows = conn.execute("SELECT id,slug,domain,left(body,200000) body FROM documents"
                        " WHERE body ~* '\\.(png|jpe?g|webp)([^a-z0-9]|$)' AND (%s::text IS NULL OR domain=%s)"
                        ' ORDER BY id LIMIT %s', (domain, domain, limit + 1)).fetchall()
    total = conn.execute("SELECT count(*) n FROM documents WHERE body ~* '\\.(png|jpe?g|webp)([^a-z0-9]|$)'"
                         ' AND (%s::text IS NULL OR domain=%s)', (domain, domain)).fetchone()['n']
    conn.rollback()
    items = []
    for row in rows[:limit]:
        found = list(dict.fromkeys(m.group(0) for m in _REFERENCE.finditer(row['body'])))[:5]
        items.append({'document_id': str(row['id']), 'slug': row['slug'], 'domain': row['domain'],
                      'references': [{'reference': strip_secrets(r)[0][:200],
                                      'kind': 'url' if r.lower().startswith(('http://', 'https://')) else 'path_or_name'}
                                     for r in found],
                      'disposition': 'reference_only_no_retained_original'})
    return {'candidates': items, 'total': total, 'truncated': len(rows) > limit,
            'note': 'candidates are text references, not verified or retained images; nothing is fetched'}



def erase(conn, original_id, *, expected_sha256, reason, apply=False, actor='operator'):
    """Operator-only, atomic privacy erasure. Preview by default.

    Keep a content-free original/engine tombstone and source history. Remove
    pixels, region/text payloads and quotes from this source. Delete claims only
    when no other source supports them; never delete another source's knowledge.
    Historical backups and externally downloaded files need separate disposal.
    """
    from .service.fence import LEASE
    from .service.queued_transaction import GROUP
    if _request() is not None or LEASE.get() is not None or GROUP.get() is not None:
        raise PermissionError('operator_local_configuration_required')
    permission = conn.execute("SELECT has_table_privilege(current_user,'public.image_originals','UPDATE') ok").fetchone()
    conn.rollback()
    if not permission['ok']:
        raise PermissionError('operator_role_required')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError('nonempty reason of at most 1000 characters required')
    try:
        uuidlib.UUID(str(original_id))
    except ValueError:
        raise ImageUnavailable() from None
    try:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='30s'")
        row = conn.execute('SELECT id,source_key,sha256,erased_at FROM image_originals WHERE id=%s',
                           (str(original_id),)).fetchone()
        if row is None:
            raise ImageUnavailable()
        if row['sha256'] != expected_sha256:
            raise ValueError('original_digest_conflict')
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (evidence._lock_key(row['source_key']),))
        row = conn.execute('SELECT id,source_key,sha256,erased_at FROM image_originals WHERE id=%s FOR UPDATE',
                           (str(original_id),)).fetchone()
        documents = conn.execute('SELECT DISTINCT e.document_id, EXISTS(SELECT 1 FROM claim_evidence other'
            ' WHERE other.document_id=e.document_id AND other.source_key<>%s) shared'
            ' FROM claim_evidence e WHERE e.source_key=%s ORDER BY e.document_id',
            (row['source_key'], row['source_key'])).fetchall()
        exclusive = [str(r['document_id']) for r in documents if not r['shared']]
        shared = [str(r['document_id']) for r in documents if r['shared']]
        result = {'original_id': str(row['id']), 'sha256': row['sha256'], 'applied': bool(apply),
                  'already_erased': row['erased_at'] is not None, 'exclusive_documents': exclusive,
                  'shared_documents': shared, 'backups_require_separate_disposal': True}
        if not apply or result['already_erased']:
            conn.rollback()
            return result
        # Serialize the support classification with attachment/review of every
        # affected claim. A concurrent lock timeout rolls the complete erase back.
        if documents:
            conn.execute('SELECT document_id FROM claim_records WHERE document_id=ANY(%s::uuid[])'
                         ' ORDER BY document_id FOR UPDATE', ([str(r['document_id']) for r in documents],)).fetchall()
        evidence.source_state(conn, row['source_key'], state='removed', reason=reason, actor=actor, commit=False)
        # Recheck after row locks: a concurrent attachment must preserve its claim.
        conn.execute('DELETE FROM claim_evidence WHERE source_key=%s', (row['source_key'],))
        deleted, retained = [], []
        # Recompute *every* affected claim after locking. Another erasure may
        # have removed the last independent support while this one was waiting.
        for item in documents:
            doc = str(item['document_id'])
            removed = conn.execute('DELETE FROM documents d WHERE id=%s AND NOT EXISTS('
                'SELECT 1 FROM claim_evidence e WHERE e.document_id=d.id) RETURNING id', (doc,)).fetchone()
            if removed:
                deleted.append(doc)
            elif conn.execute('SELECT id FROM documents WHERE id=%s', (doc,)).fetchone():
                retained.append(doc)
        result['exclusive_documents'], result['shared_documents'] = deleted, retained
        conn.execute("UPDATE image_derivations SET text='',regions='[]',warnings=warnings||'[\"payload_erased\"]'::jsonb"
                     ' WHERE original_id=%s', (row['id'],))
        conn.execute('UPDATE image_originals SET bytes=NULL,erased_at=now() WHERE id=%s', (row['id'],))
        _audit(conn, actor, 'image_erase', None, f'original {row["id"]}, sha256 {row["sha256"]}; '
               f'{len(deleted)} exclusive claims erased, {len(retained)} shared claims retained; {strip_secrets(reason)[0]}')
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
