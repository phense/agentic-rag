"""Source-preserving lifecycle overlay (RAG-066, contract lifecycle-v1, schema031).

Preview and detail are read-only. Apply and correct run only through the thin
store gateway (store.apply_lifecycle / store.correct_lifecycle). They write the
decision, its append-only event and one audit row in one transaction and never
touch documents, chunks, claims, evidence, edges or pins. Migration031's SQL
predicate is the authority every reader (including 0.6.18 code) applies before
its LIMIT; this module adds explicit views, labels and explanations.

Proof versus judgement: an exact duplicate is a structural proof (identical title,
body, dtype and claim identity). Semantic duplicate, extension and contradiction are
operator judgements; replacement proves only the event order. Nothing here infers
equivalence from text similarity or calls a model.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid as uuidlib

import psycopg
from psycopg.pq import TransactionStatus

OPERATIONS = ('exact_duplicate', 'semantic_duplicate', 'extension', 'replacement', 'contradiction')
HIDING = ('exact_duplicate', 'semantic_duplicate', 'extension', 'replacement')
REVIEWED = ('semantic_duplicate', 'extension', 'replacement')
VIEWS = ('current', 'latest', 'include_merged', 'historical')
MAX_SOURCES, MAX_MEMBERS, MAX_PAGE, DEFAULT_PAGE = 8, 500, 100, 20
LOCK_TIMEOUT_MS, STATEMENT_TIMEOUT_MS = 2000, 10000
_VERSION = re.compile(r'^lv1:[0-9a-f]{64}$')
STATEMENT = ('Structural checks prove only identical title, body, dtype and claim identity, or the order of '
             'qualifying source events. Semantic equivalence, extension and contradiction are operator '
             'judgement and are not proven.')

STATUS = {'not_found': 404, 'invalid_view': 400, 'invalid_arguments': 400, 'review_required': 400,
          'scope_denied': 403, 'busy': 503}


class LifecycleError(ValueError):
    """Fixed, value-free error code (contract lifecycle-v1 'Codes')."""

    def __init__(self, code: str, detail: dict | None = None):
        super().__init__(code)
        self.code, self.detail = code, detail or {}

    @property
    def status(self) -> int:
        return STATUS.get(self.code, 409)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else value


def _uuid(value) -> str | None:
    try:
        return str(uuidlib.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


# ------------------------------------------------------------------ views

def normalize_view(view, *, history=None, as_of=None):
    """None keeps every omitted-view default. Contradictory combinations fail before
    any database work: historical excludes as_of; current/include_merged exclude history."""
    if view is None:
        return None
    if not isinstance(view, str) or view not in VIEWS:
        raise LifecycleError('invalid_view')
    selected = 'current' if view == 'latest' else view
    if selected == 'historical' and as_of is not None:
        raise LifecycleError('invalid_view')
    if selected != 'historical' and history:
        raise LifecycleError('invalid_view')
    return selected


def _setting(conn):
    row = conn.execute("SELECT current_setting('rag_lifecycle.view', true) AS v").fetchone()
    value = row['v'] if isinstance(row, dict) else row[0]
    return value or ''


@contextmanager
def view_scope(conn, view):
    """Set rag_lifecycle.view transaction-locally and restore the previous value.

    SET LOCAL survives a released savepoint, so the prior value is restored
    explicitly; an autocommit connection gets a transaction for the scope."""
    if view is None:
        yield
        return
    if conn.autocommit and conn.info.transaction_status == TransactionStatus.IDLE:
        with conn.transaction(), _set_view(conn, view):
            yield
        return
    with _set_view(conn, view):
        yield


@contextmanager
def _set_view(conn, view):
    prior = _setting(conn)
    conn.execute("SELECT set_config('rag_lifecycle.view', %s, true)", (view,))
    try:
        yield
    finally:
        if conn.info.transaction_status == TransactionStatus.INTRANS:
            conn.execute("SELECT set_config('rag_lifecycle.view', %s, true)", (prior,))


@contextmanager
def current_scope(conn):
    """Derived readers (profiles, thematic, entity, context) always use current
    semantics; a request view can never widen their dependencies."""
    if conn.info.transaction_status != TransactionStatus.INTRANS or _setting(conn) in ('', 'current'):
        yield
        return
    with view_scope(conn, 'current'):
        yield


def current_only(fn):
    """Decorator for derived readers whose first argument is the connection."""
    from functools import wraps

    @wraps(fn)
    def wrapped(conn, *args, **kwargs):
        with current_scope(conn):
            return fn(conn, *args, **kwargs)
    return wrapped


def time_selection(view, as_of, history):
    """Return the SQL (at, history) pair for an explicit view. Historical passes
    history=true so legacy edge-validity filters do not drop past relations; the SQL
    predicate then applies the qualified historical gates instead of the legacy ones."""
    from .validity import selection
    if view == 'historical':
        return selection(None, True)
    if view is not None:
        return selection(as_of, False)
    return selection(as_of, history)


def labels(conn, ids, view, at=None) -> dict[str, dict]:
    """Lifecycle labels for already visible results (only when a view was requested)."""
    ids = sorted({str(i) for i in ids})
    if not ids or view is None:
        return {}
    rows = conn.execute("""
      SELECT d.id::text AS id,
        public.rag_lifecycle_hidden(d.id, COALESCE(%(at)s::timestamptz, now()), false) AS hidden,
        public.rag_assertion_eligible_base(d.id, COALESCE(%(at)s::timestamptz, now()), false) AS base,
        (SELECT ld.operation FROM public.lifecycle_decisions ld WHERE ld.member_id=d.id AND ld.state='active') AS operation,
        (SELECT ld.id::text FROM public.lifecycle_decisions ld WHERE ld.member_id=d.id AND ld.state='active') AS decision,
        (SELECT t.id::text FROM public.lifecycle_decisions ld JOIN public.documents t ON t.id=ld.target_id
          WHERE ld.member_id=d.id AND ld.state='active') AS canonical,
        (SELECT count(*) FROM public.lifecycle_decisions ld JOIN public.documents m ON m.id=ld.member_id
          WHERE ld.target_id=d.id AND ld.state='active' AND ld.operation<>'contradiction') AS members,
        EXISTS (SELECT 1 FROM public.fact_assertions a WHERE a.document_id=d.id
                AND a.expires_at IS NOT NULL AND a.expires_at <= COALESCE(%(at)s::timestamptz, now())) AS expired
      FROM public.documents d WHERE d.id = ANY(%(ids)s::uuid[])""", {'ids': ids, 'at': at}).fetchall()
    out = {}
    for r in rows:
        if r['hidden']:
            state = 'superseded' if r['operation'] == 'replacement' else 'merged'
        elif not r['base']:
            state = 'expired' if r['expired'] else 'superseded'
        else:
            state = 'current'
        label = {'view': view, 'state': state, 'role': 'canonical' if r['members'] else 'original'}
        if r['hidden']:
            label.update(decision=r['decision'], operation=r['operation'], canonical_id=r['canonical'])
            if r['canonical'] is None:
                label['resolution'] = 'canonical_unavailable'
        if r['members']:
            label['members'] = r['members']
        out[r['id']] = label
    return out


def resolve_get(conn, document: dict, view: str) -> dict:
    """Explicit-view memory_get: identify the requested original and, for current,
    the canonical original (one hop). Never redirects a citation silently."""
    requested = str(document['id'])
    label = labels(conn, [requested], view).get(requested, {'view': view, 'state': 'current', 'role': 'original'})
    block = {'requested_id': requested, **label}
    if view != 'current':
        eligible = (document.get('status') == 'active'
                    and conn.execute('SELECT assertion_eligible(%s) ok', (requested,)).fetchone()['ok'])
        if eligible:
            return {'document': document, 'lifecycle': block}
        block.pop('canonical_id', None)
        return {'document': None, 'lifecycle': {**block, 'resolution': 'not_current'}}
    if label['state'] == 'current' and conn.execute('SELECT assertion_eligible(%s) ok', (requested,)).fetchone()['ok'] \
            and document.get('status') == 'active':
        return {'document': document, 'lifecycle': {**block, 'canonical_id': requested, 'resolution': 'self'}}
    canonical = label.get('canonical_id')
    if label['state'] in ('merged', 'superseded') and canonical is not None \
            and conn.execute('SELECT assertion_eligible(%s) ok', (canonical,)).fetchone()['ok']:
        from .store import get_document
        target = get_document(conn, canonical)
        if target is not None:
            return {'document': target, 'lifecycle': {**block, 'canonical_id': canonical, 'resolution': 'canonical'}}
    block.pop('canonical_id', None)
    resolution = 'canonical_unavailable' if label['state'] in ('merged', 'superseded') else 'not_current'
    return {'document': None, 'lifecycle': {**block, 'canonical_id': None, 'resolution': resolution}}


# ------------------------------------------------------------------ anchors

_ANCHOR_SQL = """
SELECT d.id::text AS id, d.slug, d.title, d.body, d.dtype, d.status, d.domain, d.project_scope, d.created_at,
       c.kind AS claim_kind, c.review_state, c.content_hash,
       public.rag_lifecycle_version(d.id) AS version,
       public.rag_lifecycle_event_basis(d.id) AS event_at,
       public.rag_assertion_eligible_base(d.id, now(), false) AS base_current,
       (d.dtype = 'synthesis' OR EXISTS (SELECT 1 FROM public.synthesis_patterns p WHERE p.document_id=d.id)) AS derived,
       (EXISTS (SELECT 1 FROM public.fact_assertions a WHERE a.document_id=d.id)
        OR EXISTS (SELECT 1 FROM public.entity_aliases x WHERE x.document_id=d.id)) AS managed
  FROM public.documents d LEFT JOIN public.claim_records c ON c.document_id=d.id
 WHERE d.id = %s"""


def _resolve(conn, id_or_slug) -> str | None:
    if not isinstance(id_or_slug, str) or not 0 < len(id_or_slug) <= 300:
        return None
    identity = _uuid(id_or_slug)
    row = conn.execute('SELECT id::text AS id FROM documents WHERE ' + ('id=%s' if identity else 'slug=%s'),
                       (identity or id_or_slug,)).fetchone()
    return row['id'] if row else None


def _anchor(conn, doc_id):
    row = conn.execute(_ANCHOR_SQL, (doc_id,)).fetchone()
    return dict(row) if row else None


def _sources(conn, doc_id):
    rows = conn.execute("""SELECT k.source_key, k.role, k.state, k.source_at, e.complete, e.reviewed
        FROM claim_evidence e JOIN knowledge_sources k ON k.source_key=e.source_key
        WHERE e.document_id=%s ORDER BY k.source_at NULLS LAST, k.source_key LIMIT %s""",
                        (doc_id, MAX_SOURCES + 1)).fetchall()
    total = conn.execute('SELECT count(*) n FROM claim_evidence WHERE document_id=%s', (doc_id,)).fetchone()['n']
    items = [{**dict(r), 'source_at': _iso(r['source_at'])} for r in rows[:MAX_SOURCES]]
    return items, max(0, total - MAX_SOURCES)


def _ref(conn, a):
    sources, omitted = _sources(conn, a['id'])
    return {'id': a['id'], 'slug': a['slug'], 'title': a['title'], 'dtype': a['dtype'], 'domain': a['domain'],
            'project': a['project_scope'], 'created_at': _iso(a['created_at']), 'version': a['version'],
            'event_at': _iso(a['event_at']),
            'claim': {'kind': a['claim_kind'], 'review_state': a['review_state']} if a['claim_kind'] else None,
            'sources': sources, 'sources_omitted': omitted}


def _common(member, target):
    """Common anchor rules (contract 'Common anchor rules'); missing and foreign
    anchors are reported identically by the caller before this runs."""
    if member['id'] == target['id']:
        raise LifecycleError('invalid_arguments')
    if member['domain'] != target['domain'] or member['project_scope'] != target['project_scope']:
        raise LifecycleError('scope_mismatch')
    if member['project_scope'] == 'unknown':
        raise LifecycleError('unknown_scope')
    if member['derived'] or target['derived']:
        raise LifecycleError('not_original')
    if member['managed'] or target['managed']:
        raise LifecycleError('assertion_managed')
    if not all(a['status'] == 'active' and a['base_current'] for a in (member, target)):
        raise LifecycleError('not_current')


def _exact(member, target):
    differs = [field for field in ('title', 'body', 'dtype') if member[field] != target[field]]
    if (member['claim_kind'], member['content_hash']) != (target['claim_kind'], target['content_hash']):
        differs.append('claim')
    if not member['body']:
        differs.append('empty_body')
    newer = (member['created_at'], member['id']) > (target['created_at'], target['id'])
    return {'proven': not differs, 'differs': differs, 'member_newer': newer}


def _event_order(member, target, now):
    m, t = member['event_at'], target['event_at']
    if m is None or t is None:
        status = 'unknown'
    elif t > now:
        status = 'future'
    elif m == t:
        status = 'equal'
    elif m > t:
        status = 'reversed'
    else:
        status = 'proven'
    return {'member_at': _iso(m), 'target_at': _iso(t), 'status': status,
            'effective_at': _iso(t) if status == 'proven' else None}


def _operations(exact, order):
    out = {}
    for op in OPERATIONS:
        allowed, code, proof = True, None, 'judgement'
        if op == 'exact_duplicate':
            proof = 'exact'
            if not (exact['proven'] and exact['member_newer']):
                allowed, code = False, 'proof_failed'
        elif op == 'replacement':
            proof = 'event_order'
            if order['status'] != 'proven':
                allowed, code = False, 'event_order_unproven'
        out[op] = {'allowed': allowed, 'code': code, 'proof': proof,
                   'approval': 'reviewed' if op in REVIEWED else 'operator', 'hides': op in HIDING}
    return out


def _evaluate(conn, member_id, target_id, operation):
    member, target = _anchor(conn, member_id), _anchor(conn, target_id)
    if member is None or target is None:
        raise LifecycleError('not_found')
    _common(member, target)
    now = conn.execute('SELECT now() AS t').fetchone()['t']
    exact, order = _exact(member, target), _event_order(member, target, now)
    return member, target, exact, order, _operations(exact, order)


def preview(conn, member, target, operation=None) -> dict:
    """Pure bounded pair preview (IC-001). Zero writes, zero provider calls."""
    if operation is not None and operation not in OPERATIONS:
        raise LifecycleError('invalid_arguments')
    member_id, target_id = _resolve(conn, member), _resolve(conn, target)
    if member_id is None or target_id is None:
        raise LifecycleError('not_found')
    m, t, exact, order, operations = _evaluate(conn, member_id, target_id, operation)
    if operation is not None and operations[operation]['allowed']:
        classification = operation
    elif operation is None and operations['exact_duplicate']['allowed']:
        classification = 'exact_duplicate'
    else:
        classification = 'review_required'
    proof = operations[classification]['proof'] if classification != 'review_required' else 'none'
    return {'member': _ref(conn, m), 'target': _ref(conn, t), 'requested': operation,
            'classification': classification, 'proof': proof,
            'exact': {'proven': exact['proven'], 'differs': exact['differs'],
                      'canonical': 'target' if exact['member_newer'] else 'member'},
            'event_order': order, 'operations': operations, 'statement': STATEMENT,
            'writes': 0, 'provider_calls': 0}


# ------------------------------------------------------------------ gateway core

def _key(value) -> str:
    return hashlib.sha256(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _reason(reason):
    from .secrets import strip_secrets
    if not isinstance(reason, str) or not reason.strip():
        raise LifecycleError('invalid_arguments')
    cleaned = strip_secrets(reason.strip())[0]
    if not 1 <= len(cleaned) <= 1000:
        raise LifecycleError('invalid_arguments')
    return cleaned


def _request_key(value):
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise LifecycleError('invalid_arguments')
    return value


def _timeouts(conn):
    """Bounded waits; never relax a stricter caller setting."""
    for name, limit in (('lock_timeout', LOCK_TIMEOUT_MS), ('statement_timeout', STATEMENT_TIMEOUT_MS)):
        row = conn.execute("SELECT (CASE WHEN current_setting(%s) IN ('0','') THEN 0 ELSE"
                           " (SELECT setting::bigint FROM pg_settings WHERE name=%s) END) AS ms", (name, name)).fetchone()
        current = row['ms']
        if current == 0 or current > limit:
            conn.execute('SELECT set_config(%s,%s,true)', (name, f'{limit}ms'))


def _lock(conn, ids):
    """Deterministic anchor locks (ORDER BY id). The restrictive service UPDATE
    policies also make this the write-authority check: a readable but unwritable
    anchor is denied, an unreadable one is not found."""
    ids = sorted({i for i in ids if i})
    locked = {r['id'] for r in conn.execute(
        'SELECT id::text AS id FROM documents WHERE id = ANY(%s::uuid[]) ORDER BY id FOR UPDATE', (ids,)).fetchall()}
    if locked != set(ids):
        visible = {r['id'] for r in conn.execute('SELECT id::text AS id FROM documents WHERE id = ANY(%s::uuid[])',
                                                 (ids,)).fetchall()}
        raise LifecycleError('scope_denied' if visible == set(ids) else 'not_found')
    return locked


def _audit(conn, actor, op, document_id, summary):
    conn.execute('INSERT INTO audit_log(actor, op, document_id, summary) VALUES (%s,%s,%s,%s)',
                 (actor, op, document_id, summary))


def _decision(row):
    return {'id': str(row['id']), 'operation': row['operation'], 'state': row['state'], 'proof': row['proof'],
            'member_id': str(row['member_id']), 'target_id': str(row['target_id']), 'domain': row['domain'],
            'project': row['project_scope'], 'effective_at': _iso(row['effective_at']), 'reason': row['reason'],
            'created_at': _iso(row['created_at'])}


def _writable_decision(conn, decision_id):
    row = conn.execute('SELECT * FROM lifecycle_decisions WHERE id=%s FOR UPDATE', (decision_id,)).fetchone()
    if row is None:
        visible = conn.execute('SELECT 1 FROM lifecycle_decisions WHERE id=%s', (decision_id,)).fetchone()
        raise LifecycleError('scope_denied' if visible else 'not_found')
    return row


def _map(error):
    if isinstance(error, (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled)):
        return LifecycleError('busy')
    if isinstance(error, psycopg.errors.CheckViolation):
        match = re.search(r'lifecycle:([a-z_]+)', str(error))
        if match:
            return LifecycleError(match.group(1))
    if isinstance(error, psycopg.errors.UniqueViolation):
        return LifecycleError('replay_mismatch' if 'request_key' in str(error) else 'already_active')
    if isinstance(error, psycopg.errors.InsufficientPrivilege) and 'row-level security' in str(error):
        return LifecycleError('scope_denied')
    return None


def _transaction(conn, work):
    """One transaction for every effect; any failure rolls back all of it. An
    autocommit connection is switched to one explicit transaction for the call."""
    if conn.autocommit:
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise LifecycleError('busy')
        conn.autocommit = False
        try:
            return _transaction(conn, work)
        finally:
            if conn.info.transaction_status == TransactionStatus.IDLE:
                conn.autocommit = True
    try:
        _timeouts(conn)
        result = work()
        conn.commit()  # ServiceConnection re-checks current commit authority here
        return result
    except LifecycleError:
        conn.rollback()
        raise
    except psycopg.Error as error:
        conn.rollback()
        mapped = _map(error)
        if mapped is not None:
            raise mapped from None
        raise
    except BaseException:
        conn.rollback()
        raise


def apply(conn, cfg, *, member, target, operation, expected_member_version, expected_target_version, reason,
          reviewed=False, request_key=None, actor='cli') -> dict:
    if operation not in OPERATIONS or type(reviewed) is not bool:
        raise LifecycleError('invalid_arguments')
    if not all(isinstance(v, str) and _VERSION.fullmatch(v) for v in (expected_member_version, expected_target_version)):
        raise LifecycleError('invalid_arguments')
    reason, request_key = _reason(reason), _request_key(request_key)
    if operation in REVIEWED and not reviewed:
        raise LifecycleError('review_required')

    def work():
        member_id, target_id = _resolve(conn, member), _resolve(conn, target)
        if member_id is None or target_id is None:
            raise LifecycleError('not_found')
        action_key = _key([operation, member_id, target_id, expected_member_version, expected_target_version, reason])
        _lock(conn, [member_id, target_id])
        known = conn.execute('SELECT action_key FROM lifecycle_events WHERE request_key=%s', (request_key,)).fetchone() \
            if request_key else None
        if known is not None and known['action_key'] != action_key:
            raise LifecycleError('replay_mismatch')
        existing = conn.execute('SELECT * FROM lifecycle_decisions WHERE action_key=%s', (action_key,)).fetchone()
        if existing is not None:
            # Idempotent replay: no write; authority is re-checked by the row lock
            # and at commit. A corrected decision is returned, never reactivated.
            return {'decision': _decision(_writable_decision(conn, existing['id'])), 'replayed': True}
        # Anchor class/scope first (both anchors are visible here, so naming the rule
        # discloses nothing), then the inspected versions, then the operation proof.
        m, t, exact, order, operations = _evaluate(conn, member_id, target_id, operation)
        if (m['version'], t['version']) != (expected_member_version, expected_target_version):
            raise LifecycleError('stale_version', {'member_version': m['version'], 'target_version': t['version']})
        if not operations[operation]['allowed']:
            raise LifecycleError(operations[operation]['code'])
        if operation in HIDING:
            if conn.execute("SELECT 1 FROM lifecycle_decisions WHERE member_id=%s AND state='active'", (member_id,)).fetchone():
                raise LifecycleError('already_active')
            if conn.execute("SELECT 1 FROM lifecycle_decisions WHERE state='active' AND (member_id=%s OR target_id=%s)",
                            (target_id, member_id)).fetchone():
                raise LifecycleError('chain_conflict')
            if conn.execute("SELECT count(*) n FROM lifecycle_decisions WHERE target_id=%s AND state='active'",
                            (target_id,)).fetchone()['n'] >= MAX_MEMBERS:
                raise LifecycleError('budget_exceeded')
        row = conn.execute(
            "INSERT INTO lifecycle_decisions(action_key,operation,member_id,target_id,domain,project_scope,proof,reason,"
            " member_lv1,target_lv1,member_snapshot,target_snapshot,effective_at,state,created_by)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,rag_lifecycle_snapshot(%s),rag_lifecycle_snapshot(%s),%s,%s,%s)"
            " RETURNING *",
            (action_key, operation, member_id, target_id, m['domain'], m['project_scope'],
             operations[operation]['proof'], reason, expected_member_version, expected_target_version, member_id,
             target_id, order['effective_at'] if operation == 'replacement' else None,
             'contested' if operation == 'contradiction' else 'active', actor)).fetchone()
        conn.execute(
            "INSERT INTO lifecycle_events(decision_id,event,action_key,request_key,actor,reason,member_id,target_id,domain,project_scope)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (row['id'], 'recorded' if operation == 'contradiction' else 'applied', action_key, request_key, actor,
             reason, member_id, target_id, m['domain'], m['project_scope']))
        _audit(conn, actor, 'lifecycle_apply', member_id,
               f"{operation} decision {row['id']} ({row['state']}) member {member_id} target {target_id}")
        return {'decision': _decision(row), 'replayed': False}
    result = _transaction(conn, work)
    result['versions'] = _versions(conn, [result['decision']['member_id'], result['decision']['target_id']])
    return result


def _versions(conn, ids):
    rows = conn.execute('SELECT id::text AS id, rag_lifecycle_version(id) AS v FROM documents WHERE id = ANY(%s::uuid[])',
                        (ids,)).fetchall()
    conn.rollback()
    found = {r['id']: r['v'] for r in rows}
    return {'member': found.get(ids[0]), 'target': found.get(ids[1])}


def correct(conn, cfg, *, decision_id, expected_revision, reason, request_key=None, actor='cli') -> dict:
    identity = _uuid(decision_id)
    if identity is None:
        raise LifecycleError('not_found')
    if type(expected_revision) is not int or not 1 <= expected_revision <= 1000:
        raise LifecycleError('invalid_arguments')
    reason, request_key = _reason(reason), _request_key(request_key)

    def work():
        found = conn.execute('SELECT member_id::text AS m, target_id::text AS t FROM lifecycle_decisions WHERE id=%s',
                             (identity,)).fetchone()
        if found is None:
            raise LifecycleError('not_found')
        # Anchors first (ORDER BY id), then the decision: the apply lock order.
        present = [r['id'] for r in conn.execute('SELECT id::text AS id FROM documents WHERE id = ANY(%s::uuid[])',
                                                 ([found['m'], found['t']],)).fetchall()]
        _lock(conn, present)
        row = _writable_decision(conn, identity)
        key = _key(['correct', identity, expected_revision, reason])
        known = conn.execute('SELECT action_key FROM lifecycle_events WHERE request_key=%s', (request_key,)).fetchone() \
            if request_key else None
        if known is not None and known['action_key'] != key:
            raise LifecycleError('replay_mismatch')
        if conn.execute('SELECT 1 FROM lifecycle_events WHERE action_key=%s AND decision_id=%s', (key, identity)).fetchone():
            return {'decision': _decision(row), 'replayed': True}
        revision = conn.execute('SELECT count(*) n FROM lifecycle_events WHERE decision_id=%s', (identity,)).fetchone()['n']
        if row['state'] == 'corrected' or revision != expected_revision:
            raise LifecycleError('stale_version', {'revision': revision, 'state': row['state']})
        updated = conn.execute("UPDATE lifecycle_decisions SET state='corrected' WHERE id=%s RETURNING *", (identity,)).fetchone()
        conn.execute(
            "INSERT INTO lifecycle_events(decision_id,event,action_key,request_key,actor,reason,member_id,target_id,domain,project_scope)"
            " VALUES (%s,'corrected',%s,%s,%s,%s,%s,%s,%s,%s)",
            (identity, key, request_key, actor, reason, row['member_id'], row['target_id'], row['domain'], row['project_scope']))
        _audit(conn, actor, 'lifecycle_correct', row['member_id'],
               f"corrected {row['operation']} decision {identity} (revision {revision})")
        return {'decision': _decision(updated), 'replayed': False}
    return _transaction(conn, work)


# ------------------------------------------------------------------ detail and history

def _cursor(value):
    if value is None:
        return None
    try:
        at, ident = json.loads(base64.urlsafe_b64decode(value.encode()).decode())
        return datetime.fromisoformat(at), str(uuidlib.UUID(ident))
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise LifecycleError('invalid_arguments') from None


def _encode(at, ident):
    return base64.urlsafe_b64encode(json.dumps([_iso(at), str(ident)]).encode()).decode()


def _limit(limit):
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise LifecycleError('invalid_arguments')
    return limit


_RELATIONSHIP = """CASE
  WHEN ld.state='corrected' THEN 'corrected'
  WHEN ld.state='contested' THEN 'contested'
  WHEN ld.operation='replacement' THEN CASE WHEN ld.effective_at <= now() THEN 'replaced' ELSE 'not_yet_effective' END
  WHEN public.rag_lifecycle_snapshot(ld.member_id) IS DISTINCT FROM ld.member_snapshot
    OR public.rag_lifecycle_snapshot(ld.target_id) IS DISTINCT FROM ld.target_snapshot THEN 'stale'
  WHEN NOT public.rag_assertion_eligible_base(ld.target_id, now(), false) THEN 'target_unavailable'
  ELSE 'hiding' END"""


def detail(conn, id_or_slug, *, history=False, cursor=None, limit=DEFAULT_PAGE) -> dict:
    """Read-only explanation of one visible original: decisions where it is member
    or canonical, legacy archived duplicates and immutable-assertion relations. A
    canonical the caller cannot read is reported as unavailable without its id."""
    if type(history) is not bool:
        raise LifecycleError('invalid_arguments')
    limit, after = _limit(limit), _cursor(cursor)
    doc_id = _resolve(conn, id_or_slug)
    if doc_id is None:
        raise LifecycleError('not_found')
    doc = conn.execute('SELECT id::text AS id,slug,title,status,domain,project_scope,dtype FROM documents WHERE id=%s',
                       (doc_id,)).fetchone()
    from .synthesis import withheld
    if withheld(conn, doc_id, doc['dtype']):
        raise LifecycleError('not_found')
    as_member = []
    for r in conn.execute(f"""SELECT ld.*, {_RELATIONSHIP} AS relationship,
            (SELECT count(*) FROM lifecycle_events e WHERE e.decision_id=ld.id) AS revision,
            t.id::text AS visible_target, t.slug AS target_slug, t.title AS target_title
          FROM lifecycle_decisions ld LEFT JOIN documents t ON t.id=ld.target_id
          WHERE ld.member_id=%s ORDER BY ld.created_at DESC, ld.id DESC LIMIT %s""", (doc_id, DEFAULT_PAGE)).fetchall():
        item = {**_decision(r), 'relationship': r['relationship'], 'revision': r['revision']}
        item.pop('target_id')
        if r['visible_target']:
            item['canonical'] = {'id': r['visible_target'], 'slug': r['target_slug'], 'title': r['target_title']}
        else:
            item['canonical'] = None
            item['resolution'] = 'canonical_unavailable'
        as_member.append(item)
    page = conn.execute(f"""SELECT ld.*, {_RELATIONSHIP} AS relationship, m.slug AS member_slug, m.title AS member_title,
            (SELECT count(*) FROM lifecycle_events e WHERE e.decision_id=ld.id) AS revision
          FROM lifecycle_decisions ld JOIN documents m ON m.id=ld.member_id
          WHERE ld.target_id=%s AND (%s::timestamptz IS NULL OR (ld.created_at, ld.id) < (%s::timestamptz, %s::uuid))
          ORDER BY ld.created_at DESC, ld.id DESC LIMIT %s""",
                        (doc_id, after[0] if after else None, after[0] if after else None, after[1] if after else None,
                         limit + 1)).fetchall()
    members = [{**_decision(r), 'relationship': r['relationship'], 'revision': r['revision'],
                'member': {'id': str(r['member_id']), 'slug': r['member_slug'], 'title': r['member_title']}}
               for r in page[:limit]]
    for m in members:
        m.pop('target_id')
    out = {'document': {'id': doc['id'], 'slug': doc['slug'], 'title': doc['title'], 'status': doc['status'],
                        'domain': doc['domain'], 'project': doc['project_scope'], 'dtype': doc['dtype']},
           'version': conn.execute('SELECT rag_lifecycle_version(%s) v', (doc_id,)).fetchone()['v'],
           'current': conn.execute('SELECT assertion_eligible(%s) ok', (doc_id,)).fetchone()['ok'] and doc['status'] == 'active',
           'as_member': as_member,
           'as_canonical': {'members': members, 'more': len(page) > limit,
                            'cursor': _encode(page[limit - 1]['created_at'], page[limit - 1]['id']) if len(page) > limit else None},
           'legacy': _legacy(conn, doc_id), 'assertion': _assertion(conn, doc_id), 'statement': STATEMENT}
    if history:
        out['history'] = events(conn, doc_id, cursor=None, limit=limit)
    return out


def _legacy(conn, doc_id):
    """Legacy automatic curation archived the newer exact copy with duplicate_of.
    It stays archived; this is original inspection, not merged membership."""
    of = [{'label': 'legacy_duplicate', 'kept': {'id': str(r['id']), 'slug': r['slug']}} for r in conn.execute(
        "SELECT d.id,d.slug FROM edges e JOIN documents d ON d.id=e.dst_id WHERE e.src_id=%s AND e.predicate='duplicate_of'"
        " ORDER BY d.slug LIMIT 20", (doc_id,)).fetchall()]
    copies = [{'label': 'legacy_duplicate', 'archived': {'id': str(r['id']), 'slug': r['slug'], 'status': r['status']}}
              for r in conn.execute(
        "SELECT d.id,d.slug,d.status FROM edges e JOIN documents d ON d.id=e.src_id WHERE e.dst_id=%s"
        " AND e.predicate='duplicate_of' ORDER BY d.slug LIMIT 20", (doc_id,)).fetchall()]
    return {'duplicate_of': of, 'duplicates': copies}


def _assertion(conn, doc_id):
    """Immutable assertions keep their own gateway (memory_assert); explain them."""
    a = conn.execute('SELECT a.entity,a.attribute,a.relation,a.disposition,a.event_at,a.expires_at,d.domain,d.project_scope'
                     ' FROM fact_assertions a JOIN documents d ON d.id=a.document_id WHERE a.document_id=%s',
                     (doc_id,)).fetchone()
    if a is None:
        return None
    newer = conn.execute(
        "SELECT d.id::text AS id,d.slug,n.event_at FROM fact_assertions n JOIN documents d ON d.id=n.document_id"
        " WHERE n.entity=%s AND n.attribute=%s AND d.domain=%s AND d.project_scope=%s AND n.disposition='accepted'"
        " AND n.relation='replacement' AND n.event_at > %s AND n.event_at <= now() AND d.id<>%s"
        " ORDER BY n.event_at, d.id LIMIT 5",
        (a['entity'], a['attribute'], a['domain'], a['project_scope'], a['event_at'], doc_id)).fetchall() \
        if a['event_at'] is not None else []
    expired = a['expires_at'] is not None and a['expires_at'] <= datetime.now(timezone.utc)
    status = ('assertion_review' if a['disposition'] != 'accepted' else 'assertion_superseded' if newer
              else 'assertion_expired' if expired else 'assertion_current')
    return {'status': status, 'entity': a['entity'], 'attribute': a['attribute'], 'relation': a['relation'],
            'disposition': a['disposition'], 'event_at': _iso(a['event_at']), 'expires_at': _iso(a['expires_at']),
            'superseded_by': [{'id': r['id'], 'slug': r['slug'], 'event_at': _iso(r['event_at'])} for r in newer],
            'gateway': 'memory_assert'}


def events(conn, doc_id, *, cursor=None, limit=DEFAULT_PAGE) -> dict:
    limit, after = _limit(limit), _cursor(cursor)
    rows = conn.execute(
        "SELECT e.id,e.decision_id,e.event,e.actor,e.reason,e.at,d.operation FROM lifecycle_events e"
        " JOIN lifecycle_decisions d ON d.id=e.decision_id WHERE (e.member_id=%s OR e.target_id=%s)"
        " AND (%s::timestamptz IS NULL OR (e.at, e.id) < (%s::timestamptz, %s::uuid))"
        " ORDER BY e.at DESC, e.id DESC LIMIT %s",
        (doc_id, doc_id, after[0] if after else None, after[0] if after else None, after[1] if after else None,
         limit + 1)).fetchall()
    items = [{'id': str(r['id']), 'decision_id': str(r['decision_id']), 'event': r['event'], 'operation': r['operation'],
              'actor': r['actor'], 'reason': r['reason'], 'at': _iso(r['at'])} for r in rows[:limit]]
    return {'items': items, 'more': len(rows) > limit,
            'cursor': _encode(rows[limit - 1]['at'], rows[limit - 1]['id']) if len(rows) > limit else None}


def history(conn, id_or_slug, *, cursor=None, limit=DEFAULT_PAGE) -> dict:
    doc_id = _resolve(conn, id_or_slug)
    if doc_id is None:
        raise LifecycleError('not_found')
    dtype = conn.execute('SELECT dtype FROM documents WHERE id=%s', (doc_id,)).fetchone()['dtype']
    from .synthesis import withheld
    if withheld(conn, doc_id, dtype):
        raise LifecycleError('not_found')
    return {'document_id': doc_id, **events(conn, doc_id, cursor=cursor, limit=limit)}


def review(conn, limit=50) -> list[dict]:
    """Contested records and active relationships that no longer hide (stale or
    target unavailable) for rag review; bounded and scoped by RLS."""
    rows = conn.execute(f"""SELECT * FROM (SELECT ld.id::text AS id, ld.operation, ld.state, ld.member_id::text AS member_id,
            {_RELATIONSHIP} AS relationship, ld.created_at FROM lifecycle_decisions ld
            WHERE ld.state IN ('active','contested')) x
          WHERE x.relationship IN ('contested','stale','target_unavailable')
          ORDER BY x.created_at DESC, x.id LIMIT %s""", (limit,)).fetchall()
    return [{**dict(r), 'created_at': _iso(r['created_at'])} for r in rows]
