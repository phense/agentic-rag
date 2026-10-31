"""Source evidence contract v1: one bounded, versioned view of existing evidence.

This module presents the canonical claim/source/assertion registry. It is not a
second truth store: `claim_eligible`/`assertion_eligible` stay authoritative and
the reasons below only explain their outcome. Every read is anchored to one
document visible under the caller's current scope; a source is reachable only
through that anchor. Opaque source keys and span hashes replace recorded host
namespaces/session locators, which are never returned as navigation.
"""
from __future__ import annotations

import json
import re
import uuid as uuidlib

CONTRACT_VERSION = 1
PAGE_LIMIT = 20
HISTORY_LIMIT = 20
QUOTE_PAGE_BYTES = 64 * 1024  # JSON-encoded quote bytes per page
HISTORY_PAGE_BYTES = 64 * 1024  # JSON-encoded reason bytes per page
ITEM_PAGE_BYTES = 80 * 1024  # Include state, actor and locator metadata as well.
QUOTE_MAX_CHARS = 4000
REASON_MAX_CHARS = 1000
HISTORY_REASON_CHARS = 2000
MAX_STRICT_SOURCES = 128

_HEX = re.compile(r'[0-9a-f]{64}')
DOCUMENT_VERSION = re.compile(r'ev1:[0-9a-f]{64}')
SOURCE_VERSION = re.compile(r'src1:[0-9a-f]{64}')


class EvidenceUnavailable(ValueError):
    """Missing, inaccessible and unlinked anchors share one non-oracular error."""
    def __init__(self):
        super().__init__('evidence_unavailable')


class EvidenceConflict(ValueError):
    """The inspected version is no longer current; nothing was changed."""
    def __init__(self):
        super().__init__('evidence_conflict')


# Portable versions use only persisted values: revisions, content digests and
# epoch-encoded timestamps. No xmin/ctid or session time zone participates, so
# a verified dump/restore yields the same version.
SOURCE_VERSION_SQL = ("'src1:'||encode(sha256(convert_to(jsonb_build_array(s.source_key,COALESCE(sr.revision,1),"
                      "s.state,s.role,extract(epoch FROM s.source_at))::text,'UTF8')),'hex')")

DOCUMENT_VERSION_SQL = """SELECT 'ev1:'||encode(sha256(convert_to(jsonb_build_array(
    d.id::text,d.domain,d.project_scope,d.status,extract(epoch FROM d.refuted_at),
    c.kind,c.review_state,c.content_hash,COALESCE(cr.revision,1),
    (SELECT COALESCE(jsonb_agg(jsonb_build_array(e.source_key,e.span_hash,
            encode(sha256(convert_to(e.quote,'UTF8')),'hex'),e.complete,e.reviewed,
            s.state,s.role,extract(epoch FROM s.source_at),COALESCE(sr.revision,1))
            ORDER BY e.source_key,e.span_hash),'[]'::jsonb)
       FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
       LEFT JOIN public.source_revisions sr USING(source_key) WHERE e.document_id=d.id),
    (SELECT jsonb_build_array(a.disposition,extract(epoch FROM a.event_at),extract(epoch FROM a.expires_at),a.relation)
       FROM public.fact_assertions a WHERE a.document_id=d.id)
  )::text,'UTF8')),'hex') AS version
  FROM public.documents d LEFT JOIN public.claim_records c ON c.document_id=d.id
  LEFT JOIN public.claim_revisions cr ON cr.document_id=d.id WHERE d.id=%s"""


def _limit(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('invalid_limit')
    return value


def _source_key(value):
    if value is None:
        return None
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise EvidenceUnavailable()
    return value


def check_version(value, pattern=DOCUMENT_VERSION):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError('invalid_expected_version')
    return value


def check_reason(reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > REASON_MAX_CHARS:
        raise ValueError('reason must be nonempty and at most 1000 characters')
    return reason


def installed(conn):
    """Migration029 present? Legacy calls stay usable on older schemas."""
    return conn.execute("SELECT to_regclass('public.claim_history') IS NOT NULL AS ok").fetchone()['ok']


def require(conn):
    if not installed(conn):
        raise ValueError('migration029_required')


def resolve(conn, id_or_slug):
    """Return the visible anchor document; otherwise the shared unavailable error."""
    if not isinstance(id_or_slug, str) or not 1 <= len(id_or_slug) <= 512:
        raise EvidenceUnavailable()
    try:
        uuidlib.UUID(id_or_slug)
        row = conn.execute('SELECT id,slug,title,domain,project_scope,status FROM public.documents WHERE id=%s',
                           (id_or_slug,)).fetchone()
    except ValueError:
        row = conn.execute('SELECT id,slug,title,domain,project_scope,status FROM public.documents WHERE slug=%s',
                           (id_or_slug,)).fetchone()
    if row is None:
        raise EvidenceUnavailable()
    return row


def document_version(conn, doc_id):
    row = conn.execute(DOCUMENT_VERSION_SQL, (str(doc_id),)).fetchone()
    if row is None:
        raise EvidenceUnavailable()
    return row['version']


def source_version(conn, key, *, lock=False):
    row = conn.execute('SELECT ' + SOURCE_VERSION_SQL + ' AS version,COALESCE(sr.revision,1) AS revision'
                       ' FROM public.knowledge_sources s LEFT JOIN public.source_revisions sr USING(source_key)'
                       ' WHERE s.source_key=%s' + (' FOR UPDATE OF s' if lock else ''), (key,)).fetchone()
    if row is None:
        raise EvidenceUnavailable()
    return row


def linked(conn, doc_id, key):
    if not conn.execute('SELECT 1 FROM public.claim_evidence e WHERE e.document_id=%s AND e.source_key=%s LIMIT 1',
                        (str(doc_id), key)).fetchone():
        raise EvidenceUnavailable()


def _manual(namespace):
    # Operator attestations: local manual assertions use 'operator'/'manual';
    # the service rewrites caller-chosen namespaces to 'svc1:<owner>:manual:<digest>'.
    return namespace in {'operator', 'manual'} or (namespace.startswith('svc1:') and ':manual:' in namespace)


def _origin(row):
    if _manual(row['namespace']):
        return 'manual_attestation'
    return {'user': 'user_source_event', 'assistant': 'assistant_statement'}.get(row['role'], 'unknown_role')


def _encoded(value):
    # Escaped control characters can grow six-fold; budget what is transferred.
    return len(json.dumps(value, ensure_ascii=False).encode()) if value is not None else 0


def _time(value):
    return value.isoformat() if value is not None else None


def _fact(conn, doc_id):
    row = conn.execute("""SELECT a.disposition,a.event_at,a.expires_at,a.relation,
        (a.event_at IS NOT NULL AND a.event_at>now()) future,
        (a.expires_at IS NOT NULL AND a.expires_at<=now()) expired,
        EXISTS(SELECT 1 FROM public.fact_assertions newer JOIN public.documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute
              AND nd.project_scope=d.project_scope AND nd.domain=d.domain
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at>a.event_at AND newer.event_at<=now()) superseded
        FROM public.fact_assertions a JOIN public.documents d ON d.id=a.document_id
        WHERE a.document_id=%s""", (str(doc_id),)).fetchone()
    if row is None:
        return None
    if row['disposition'] != 'accepted':
        state = 'not_accepted'
    elif row['event_at'] is None:
        state = 'no_event_time'
    elif row['future']:
        state = 'future'
    elif row['expired']:
        state = 'expired'
    elif row['superseded']:
        state = 'superseded'
    else:
        state = 'current'
    return {'state': state, 'disposition': row['disposition'], 'relation': row['relation'],
            'event_at': _time(row['event_at']), 'expires_at': _time(row['expires_at'])}


# Same namespace classification as _manual; role=user alone also includes an
# operator's assertion. This affects contract explanations, never eligibility.
_MANUAL_SOURCE_SQL = "(s.namespace IN ('operator','manual') OR (left(s.namespace,5)='svc1:' AND position(':manual:' IN s.namespace)>0))"


def _claim(conn, doc_id):
    row = conn.execute(f"""SELECT c.kind,c.review_state,left(c.reason,1000) reason,
        length(c.reason)>1000 reason_truncated,COALESCE(cr.revision,1) revision,
        claim_eligible(c.document_id) eligible,
        EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
               WHERE e.document_id=c.document_id AND s.state='active' AND e.reviewed) reviewed_support,
        EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
               WHERE e.document_id=c.document_id AND s.state='active' AND s.role='user' AND e.complete
                 AND NOT {_MANUAL_SOURCE_SQL}) user_support,
        EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
               WHERE e.document_id=c.document_id AND s.state='active' AND s.role='user' AND e.complete
                 AND {_MANUAL_SOURCE_SQL}) manual_support,
        (SELECT count(DISTINCT e.source_key) FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
         WHERE e.document_id=c.document_id AND s.state='active' AND s.role='user'
           AND NOT {_MANUAL_SOURCE_SQL}) independent_user_events,
        EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
               WHERE e.document_id=c.document_id AND s.state<>'active') withdrawn,
        EXISTS(SELECT 1 FROM public.claim_evidence e WHERE e.document_id=c.document_id AND NOT e.complete) partial
        FROM public.claim_records c LEFT JOIN public.claim_revisions cr ON cr.document_id=c.document_id
        WHERE c.document_id=%s""", (str(doc_id),)).fetchone()
    return row


def inspect(conn, id_or_slug, *, source_key=None, cursor=None, limit=PAGE_LIMIT):
    """Contract v1 envelope for one visible document and one finite source page."""
    limit = _limit(limit, PAGE_LIMIT)
    after = None
    if cursor is not None:
        parts = cursor.split('.') if isinstance(cursor, str) and len(cursor) <= 129 else []
        if len(parts) != 2 or not all(_HEX.fullmatch(p) for p in parts):
            raise ValueError('invalid_cursor')
        after = tuple(parts)
    doc = resolve(conn, id_or_slug)
    doc_id = str(doc['id'])
    key = _source_key(source_key)
    if key is not None:
        linked(conn, doc_id, key)
    version = document_version(conn, doc_id)
    claim = _claim(conn, doc_id)
    fact = _fact(conn, doc_id)
    current = conn.execute('SELECT assertion_eligible(%s) ok', (doc_id,)).fetchone()['ok'] and doc['status'] == 'active'
    filters, params = 'e.document_id=%s', [doc_id]
    if key is not None:
        filters += ' AND e.source_key=%s'
        params.append(key)
    total = conn.execute('SELECT count(*) spans,count(DISTINCT e.source_key) sources FROM public.claim_evidence e WHERE '
                         + filters, params).fetchone()
    page_filter = filters + (' AND (e.source_key,e.span_hash)>(%s,%s)' if after else '')
    from .service.read_limits import rows as bounded_rows
    rows = bounded_rows(conn, 'SELECT e.source_key,e.span_hash,left(e.quote,%s) quote,length(e.quote)>%s quote_truncated,'
                        'e.complete,e.reviewed,s.role,s.namespace,s.source_at,s.state,left(s.reason,1000) reason,'
                        'length(s.reason)>1000 reason_truncated,s.changed_at,'
                        'COALESCE(sr.revision,1) revision,' + SOURCE_VERSION_SQL + ' source_version'
                        ' FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)'
                        ' LEFT JOIN public.source_revisions sr USING(source_key) WHERE ' + page_filter +
                        ' ORDER BY e.source_key,e.span_hash LIMIT %s',
                        [QUOTE_MAX_CHARS, QUOTE_MAX_CHARS, *params, *(after or ()), limit + 1])
    items, used, item_bytes, budget_cut = [], 0, 0, False
    for row in rows[:limit]:
        size = _encoded(row['quote'])
        item = {
            'source_key': row['source_key'], 'span_hash': row['span_hash'],
            'reference': row['source_key'] + '#' + row['span_hash'],
            'source_version': row['source_version'], 'revision': row['revision'],
            'quote': row['quote'], 'quote_truncated': row['quote_truncated'],
            'completeness': 'complete' if row['complete'] else 'partial', 'reviewed': row['reviewed'],
            'role': row['role'], 'origin': _origin(row),
            'source_event_at': _time(row['source_at']),
            'event_time': 'known' if row['source_at'] is not None else 'unknown',
            'trust': {'state': row['state'], 'reason': row['reason'],
                      'reason_truncated': bool(row['reason_truncated']), 'changed_at': _time(row['changed_at'])},
        }
        encoded = _encoded(item)
        if items and (used + size > QUOTE_PAGE_BYTES or item_bytes + encoded > ITEM_PAGE_BYTES):
            budget_cut = True
            break
        used += size
        item_bytes += encoded
        items.append(item)
    more = budget_cut or len(rows) > limit
    last = items[-1] if items else None
    reasons, notices = [], []
    if doc['status'] != 'active':
        reasons.append('document_' + doc['status'])
    if claim is None:
        notices.append('legacy_provenance_unknown')
        basis, verification = 'legacy_unmanaged', 'none'
    else:
        if claim['review_state'] == 'refuted':
            reasons.append('claim_refuted')
        elif claim['review_state'] != 'confirmed' and claim['kind'] != 'stated':
            reasons.append('review_required')
        elif not claim['eligible']:
            reasons.append('no_active_support')
        if claim['withdrawn']:
            notices.append('source_withdrawn')
        if claim['partial']:
            notices.append('partial_quote')
        if claim['review_state'] == 'confirmed' and claim['reviewed_support']:
            basis = 'operator_review'
        elif claim['kind'] == 'stated' and claim['user_support'] and claim['review_state'] != 'refuted':
            basis = 'complete_user_statement'
        elif claim['kind'] == 'stated' and claim['manual_support'] and claim['review_state'] != 'refuted':
            basis = 'manual_attestation'
        else:
            basis = 'none'
        verification = 'operator_review' if claim['review_state'] == 'confirmed' else 'none'
    if fact is not None and fact['state'] != 'current':
        reasons.append('fact_' + fact['state'])
    if not current and not reasons:
        reasons.append('not_current')
    from .evidence import summary
    compact = summary(conn, doc_id)
    return {
        'contract_version': CONTRACT_VERSION,
        'document': {'id': doc_id, 'slug': doc['slug'], 'title': doc['title'], 'domain': doc['domain'],
                     'project_scope': doc['project_scope']},
        'version': version,
        'claim': None if claim is None else {
            'kind': claim['kind'], 'review_state': claim['review_state'], 'review_reason': claim['reason'],
            'review_reason_truncated': bool(claim['reason_truncated']),
            'revision': claim['revision'], 'support_basis': basis},
        'lifecycle': {'document_status': doc['status'], 'fact': fact},
        'eligibility': {'current': bool(current), 'claim_eligible': True if claim is None else bool(claim['eligible']),
                        'reasons': reasons, 'notices': notices},
        'provenance': {'registry': 'legacy_unmanaged' if claim is None else 'claim',
                       'status': compact['provenance_status'],
                       'independent_user_events': claim['independent_user_events'] if claim else 0},
        'verification': {'independent': False, 'origin': verification},
        'sources': {'items': items, 'total': total['spans'], 'distinct_sources': total['sources'], 'limit': limit,
                    'truncated': budget_cut, 'next_cursor': f"{last['source_key']}.{last['span_hash']}" if more and last else None},
    }


def history(conn, id_or_slug, *, source_key=None, cursor=None, limit=HISTORY_LIMIT):
    """Finite, newest-first decision events for the anchored claim or linked source."""
    limit = _limit(limit, HISTORY_LIMIT)
    before = None
    if cursor is not None:
        if not isinstance(cursor, str) or not cursor.isdigit() or len(cursor) > 18:
            raise ValueError('invalid_cursor')
        before = int(cursor)
    doc = resolve(conn, id_or_slug)
    doc_id = str(doc['id'])
    key = _source_key(source_key)
    columns = ('revision,operation,state,left(reason,%s) reason,length(reason)>%s reason_truncated,'
               'actor,concurrency,inspected_version,recorded_at')
    if key is None:
        rows = conn.execute('SELECT ' + columns + ',source_key,span_hash FROM public.claim_history WHERE document_id=%s'
                            ' AND (%s::bigint IS NULL OR revision<%s) ORDER BY revision DESC LIMIT %s',
                            (HISTORY_REASON_CHARS, HISTORY_REASON_CHARS, doc_id, before, before, limit + 1)).fetchall()
    else:
        linked(conn, doc_id, key)
        rows = conn.execute('SELECT ' + columns + ' FROM public.source_history WHERE source_key=%s'
                            ' AND (%s::bigint IS NULL OR revision<%s) ORDER BY revision DESC LIMIT %s',
                            (HISTORY_REASON_CHARS, HISTORY_REASON_CHARS, key, before, before, limit + 1)).fetchall()
    items, used, item_bytes, budget_cut = [], 0, 0, False
    for row in rows[:limit]:
        size = _encoded(row['reason'])
        item = {k: row[k] for k in ('revision', 'operation', 'state', 'reason', 'reason_truncated', 'actor',
                                    'concurrency', 'inspected_version')}
        item['recorded_at'] = _time(row['recorded_at'])
        if key is None and row['source_key'] is not None:
            item['source_key'], item['span_hash'] = row['source_key'], row['span_hash']
        encoded = _encoded(item)
        if items and (used + size > HISTORY_PAGE_BYTES or item_bytes + encoded > ITEM_PAGE_BYTES):
            budget_cut = True
            break
        used += size
        item_bytes += encoded
        items.append(item)
    return {'contract_version': CONTRACT_VERSION, 'scope': 'claim' if key is None else 'source',
            'anchor': {'document_id': doc_id, **({'source_key': key} if key else {})},
            'items': items, 'limit': limit,
            'next_cursor': str(items[-1]['revision']) if (budget_cut or len(rows) > limit) and items else None,
            # Events are captured from migration029 on; earlier audit rows stay
            # in the original audit log and are not converted into history.
            'pre_upgrade_history': 'not_captured'}
