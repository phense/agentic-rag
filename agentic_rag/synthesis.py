"""Opt-in, scoped, source-linked pattern suggestions (RAG-065, contract pattern-v1).

A pattern is a derived inference over several eligible original memories of one
concrete domain and project/global scope. Nothing here runs unless the global
`[synthesis] enabled` switch is on AND an explicit scoped policy is enabled.
Preview and every read are provider-free. Generation happens only inside the
existing singleton worker tick, one bounded provider call per run; accepted
output is committed before application and reused on retry. Application goes
through the audited gateway and is atomic. `claim_eligible`/`rag_pattern_current`
(migration030) withhold a pattern as soon as any recorded original changes.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

from . import evidence_contract as contract

CONTRACT_VERSION = 1
FLOOR_EVENTS = 3
MAX_MEMORIES = 12
MAX_SPANS_PER_MEMORY = 8
MAX_QUOTE_CHARS = 4000
MAX_SCAN = 500
PAGE = 100
MAX_BACKFILL_DAYS = 366
MAX_BACKFILL_BATCHES = 10
DEFAULT_INTERVAL = 86400
# Forward selection ignores documents younger than this, so a still-running
# writer transaction with an earlier arrival time is not skipped by the cursor.
SETTLE_SECONDS = 60
REASONS = ('derived', 'legacy_unmanaged', 'not_stated', 'no_qualifying_span', 'not_current')


class SynthesisUnavailable(ValueError):
    """Global switch off: no scheduling, provider call, enable or backfill."""
    def __init__(self):
        super().__init__('synthesis_disabled')


def installed(conn) -> bool:
    return conn.execute("SELECT to_regclass('public.synthesis_policies') IS NOT NULL AS ok").fetchone()['ok']


def _time(value):
    return value.isoformat() if value is not None else None


def _reason(reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError('reason must be nonempty and at most 1000 characters')
    from .secrets import strip_secrets
    return strip_secrets(reason)[0]


def policy_scope(project=None, scope=None) -> str:
    """A concrete canonical project or explicit global scope; never unknown."""
    from .scope import write_scope
    if scope == 'unknown' or (project is None and scope != 'global'):
        raise ValueError('synthesis policy requires a concrete project or scope=global')
    value = write_scope(project=project, scope=scope)
    if value in (None, 'unknown'):
        raise ValueError('synthesis policy requires a concrete project or scope=global')
    return value


def _owner():
    from .service.context import CURRENT
    request = CURRENT.get()
    if request is None or request.config.service_auth_file is None:
        return None
    from .service.ingest import credential_reference
    return credential_reference(request.principal, None)


def normalized(quote: str) -> str:
    """Independence key only; stored quote bytes are never changed."""
    return ' '.join(unicodedata.normalize('NFKC', quote).casefold().split())


# ------------------------------------------------------------- eligibility

_DOCUMENTS = f"""SELECT d.id,d.created_at,d.dtype,d.status,c.kind,
    EXISTS(SELECT 1 FROM public.synthesis_patterns sp WHERE sp.document_id=d.id) registered,
    EXISTS(SELECT 1 FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)
           WHERE e.document_id=d.id AND e.complete AND s.role='user' AND s.state='active'
             AND length(e.quote)<={MAX_QUOTE_CHARS} AND NOT {contract._MANUAL_SOURCE_SQL}) qualifying,
    (d.status='active' AND public.assertion_eligible(d.id,statement_timestamp(),false)) current
  FROM public.documents d LEFT JOIN public.claim_records c ON c.document_id=d.id
  WHERE d.domain=%s AND d.project_scope=%s"""


def _classify(row):
    if row['registered'] or row['dtype'] == 'synthesis':
        return 'derived'
    if row['kind'] is None:
        return 'legacy_unmanaged'
    if row['kind'] != 'stated':
        return 'not_stated'
    if not row['qualifying']:
        return 'no_qualifying_span'
    if not row['current']:
        return 'not_current'
    return None


def _scan(conn, domain, scope, *, start=None, end=None, after=None, settle=False, limit=MAX_MEMORIES):
    """Ordered by arrival (created_at, id). Returns eligible rows (≤limit),
    excluded counts, the last scanned key, whether more documents remain and
    whether the scan bound stopped early."""
    eligible, excluded, last, scanned = [], dict.fromkeys(REASONS, 0), after, 0
    while True:
        filters, params = '', [domain, scope]
        if start is not None:
            filters += ' AND d.created_at>=%s'
            params.append(start)
        if end is not None:
            filters += ' AND d.created_at<%s'
            params.append(end)
        if settle:
            filters += ' AND d.created_at<=statement_timestamp()-make_interval(secs=>%s)'
            params.append(SETTLE_SECONDS)
        if last is not None:
            filters += ' AND (d.created_at,d.id)>(%s,%s)'
            params.extend(last)
        rows = conn.execute(_DOCUMENTS + filters + ' ORDER BY d.created_at,d.id LIMIT %s', [*params, PAGE]).fetchall()
        for row in rows:
            if len(eligible) >= limit:
                return eligible, excluded, last, True, False
            scanned += 1
            last = (row['created_at'], row['id'])
            reason = _classify(row)
            if reason:
                excluded[reason] += 1
            else:
                eligible.append(row)
            if scanned >= MAX_SCAN:
                return eligible, excluded, last, True, True
        if len(rows) < PAGE:
            return eligible, excluded, last, False, False


def _spans(conn, ids):
    if not ids:
        return {}
    rows = conn.execute(
        'SELECT e.document_id,e.source_key,e.span_hash,e.quote,' + contract.SOURCE_VERSION_SQL + ' source_version'
        ' FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key)'
        ' LEFT JOIN public.source_revisions sr USING(source_key)'
        f" WHERE e.document_id=ANY(%s) AND e.complete AND s.role='user' AND s.state='active'"
        f' AND length(e.quote)<={MAX_QUOTE_CHARS} AND NOT {contract._MANUAL_SOURCE_SQL}'
        ' ORDER BY e.document_id,e.source_key,e.span_hash', ([str(i) for i in ids],)).fetchall()
    out = {}
    for r in rows:
        bucket = out.setdefault(str(r['document_id']), [])
        if len(bucket) < MAX_SPANS_PER_MEMORY:
            bucket.append(dict(r))
    return out


def _events(spans):
    """Union spans sharing a source or a normalized quote; return span->event."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in spans:
        a = 'k:' + s['source_key']
        b = 'q:' + hashlib.sha256(normalized(s['quote']).encode()).hexdigest()
        parent[find(a)] = find(b)
    roots, labels = {}, {}
    for s in spans:
        root = find('k:' + s['source_key'])
        roots.setdefault(root, 'E' + str(len(roots) + 1))
        labels[(s['document_id'], s['source_key'], s['span_hash'])] = roots[root]
    return labels


def independence(spans) -> dict:
    """Events, memories and the maximum event-to-distinct-memory matching."""
    labels = _events(spans)
    edges = {}
    for s in spans:
        edges.setdefault(labels[(s['document_id'], s['source_key'], s['span_hash'])], set()).add(s['document_id'])
    owner = {}

    def augment(event, seen):
        for memory in sorted(edges[event]):
            if memory in seen:
                continue
            seen.add(memory)
            if memory not in owner or augment(owner[memory], seen):
                owner[memory] = event
                return True
        return False

    matched = sum(augment(e, set()) for e in sorted(edges))
    memories = {s['document_id'] for s in spans}
    return {'events': len(edges), 'memories': len(memories), 'matched': matched,
            'sufficient': matched >= FLOOR_EVENTS, 'labels': labels}


def candidates(conn, domain, scope, **kwargs):
    """Bounded eligible originals plus exact qualifying spans and portable versions."""
    eligible, excluded, last, more, bounded = _scan(conn, domain, scope, **kwargs)
    by_doc = _spans(conn, [r['id'] for r in eligible])
    memories, spans = [], []
    for row in eligible:
        doc_id = str(row['id'])
        items = by_doc.get(doc_id, [])
        if not items:
            excluded['no_qualifying_span'] += 1
            continue
        for item in items:
            item['document_id'] = doc_id
        memories.append({'document_id': doc_id, 'version': contract.document_version(conn, doc_id),
                         'created_at': row['created_at'], 'spans': items})
        spans.extend(items)
    return {'memories': memories, 'spans': spans, 'excluded': excluded, 'last': last, 'more': more,
            'bounded': bounded, 'independence': independence(spans)}


def _snapshot(selection):
    labels = selection['independence']['labels']
    memories = sorted(({'document_id': m['document_id'], 'version': m['version'],
                        'spans': [{'source_key': s['source_key'], 'span_hash': s['span_hash'],
                                   'source_version': s['source_version'],
                                   'event': labels[(m['document_id'], s['source_key'], s['span_hash'])]}
                                  for s in m['spans']]}
                       for m in selection['memories']), key=lambda m: m['document_id'])
    return {'format': 1, 'memories': memories}


def _budgets(cfg):
    return {'provider_calls': 0, 'max_memories': MAX_MEMORIES, 'max_spans_per_memory': MAX_SPANS_PER_MEMORY,
            'max_input_chars': cfg.synthesis_max_input_chars, 'max_output_tokens': cfg.synthesis_max_output_tokens,
            'timeout_seconds': cfg.synthesis_timeout_seconds, 'max_suggestions': 3}


def _parse(value, name):
    from .validity import parse_time
    try:
        return parse_time(value)
    except (ValueError, TypeError):
        raise ValueError(f'invalid {name} time') from None


def _policy(conn, domain, scope, *, lock=False):
    return conn.execute('SELECT * FROM public.synthesis_policies WHERE domain=%s AND project_scope=%s'
                        + (' FOR UPDATE' if lock else ''), (domain, scope)).fetchone()


def preview(conn, cfg, *, domain, project=None, scope=None, start=None, end=None) -> dict:
    """Provider-free and write-free view of what a policy would analyse."""
    if not installed(conn):
        raise ValueError('migration030_required')
    selected = policy_scope(project, scope)
    window_start, window_end = _parse(start, 'start'), _parse(end, 'end')
    if window_start and window_end and window_start >= window_end:
        raise ValueError('invalid preview window')
    policy = _policy(conn, domain, selected)
    selection = candidates(conn, domain, selected, start=window_start, end=window_end)
    snapshot = _snapshot(selection)
    ind = selection['independence']
    return {
        'contract_version': CONTRACT_VERSION,
        'scope': {'domain': domain, 'project_scope': selected},
        'policy': {'exists': False, 'enabled': False} if policy is None else
                  {'exists': True, 'enabled': policy['enabled'], 'version': policy['version'],
                   'forward_from': _time(policy['forward_from'])},
        'window': {'start': _time(window_start), 'end': _time(window_end), 'basis': 'document_arrival'},
        'floor': {'independent_events': FLOOR_EVENTS, 'memories': FLOOR_EVENTS},
        'candidates': {'memories': ind['memories'], 'spans': len(selection['spans']),
                       'independent_events': ind['events'], 'matched_events': ind['matched'],
                       'sufficient': ind['sufficient'], 'more': selection['more'],
                       'scan_bounded': selection['bounded']},
        'excluded': selection['excluded'],
        'budgets': _budgets(cfg),
        'references': [{'document_id': m['document_id'], 'version': m['version'],
                        'reference': s['source_key'] + '#' + s['span_hash'],
                        'source_version': s['source_version'], 'event': s['event']}
                       for m in snapshot['memories'] for s in m['spans']],
    }


def _policy_view(row):
    return {'id': str(row['id']), 'domain': row['domain'], 'project_scope': row['project_scope'],
            'enabled': row['enabled'], 'version': row['version'], 'forward_from': _time(row['forward_from']),
            'interval_seconds': row['interval_seconds'], 'next_due_at': _time(row['next_due_at']),
            'changed_at': _time(row['changed_at'])}


def set_policy(conn, cfg, *, domain, enabled, reason, project=None, scope=None,
               interval_seconds=DEFAULT_INTERVAL, actor='cli', commit=True) -> dict:
    """Audited scoped opt-in/opt-out. Enabling records a server-time forward boundary."""
    try:
        if not installed(conn):
            raise ValueError('migration030_required')
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        if type(interval_seconds) is not int or not 60 <= interval_seconds <= 2592000:
            raise ValueError('interval_seconds must be between 60 and 2592000')
        reason = _reason(reason)
        selected = policy_scope(project, scope)
        if enabled and not cfg.synthesis_enabled:
            raise SynthesisUnavailable()
        if not conn.execute('SELECT 1 FROM public.domains WHERE name=%s', (domain,)).fetchone():
            raise ValueError(f'unknown domain: {domain}')
        owner = _owner() if enabled else None
        owner = json.dumps(owner) if owner else None
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('synthesis_policy:' + domain + ':' + selected,))
        current = _policy(conn, domain, selected, lock=True)
        if current is None:
            row = conn.execute(
                'INSERT INTO public.synthesis_policies(domain,project_scope,enabled,forward_from,interval_seconds,'
                'next_due_at,owner,reason,changed_by) VALUES (%s,%s,%s,CASE WHEN %s THEN now() END,%s,'
                'CASE WHEN %s THEN now() END,%s,%s,%s) RETURNING *',
                (domain, selected, enabled, enabled, interval_seconds, enabled, owner, reason, actor)).fetchone()
        else:
            starting = enabled and not current['enabled']
            row = conn.execute(
                'UPDATE public.synthesis_policies SET enabled=%s,version=version+1,interval_seconds=%s,'
                'forward_from=CASE WHEN %s THEN now() ELSE forward_from END,'
                'cursor_at=CASE WHEN %s THEN NULL ELSE cursor_at END,cursor_id=CASE WHEN %s THEN NULL ELSE cursor_id END,'
                'next_due_at=CASE WHEN %s THEN now() WHEN %s THEN next_due_at ELSE NULL END,'
                'owner=CASE WHEN %s THEN %s::jsonb ELSE owner END,reason=%s,changed_by=%s,changed_at=now() '
                'WHERE id=%s RETURNING *',
                (enabled, interval_seconds, starting, starting, starting, starting, enabled,
                 enabled, owner, reason, actor, current['id'])).fetchone()
        conn.execute('INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,%s,NULL,%s)',
                     (actor, 'synthesis_policy',
                      f"{domain} {selected}: {'enabled' if enabled else 'disabled'} v{row['version']}; {reason}"))
        if commit:
            conn.commit()
        return _policy_view(row)
    except BaseException:
        if commit:
            conn.rollback()
        raise


def request_backfill(conn, cfg, *, domain, start, end, reason, project=None, scope=None, max_batches=1,
                     actor='cli', commit=True) -> dict:
    """Explicit, finite, audited history window before the forward boundary."""
    try:
        if not installed(conn):
            raise ValueError('migration030_required')
        if not cfg.synthesis_enabled:
            raise SynthesisUnavailable()
        reason = _reason(reason)
        selected = policy_scope(project, scope)
        window_start, window_end = _parse(start, 'start'), _parse(end, 'end')
        if window_start is None or window_end is None or window_start >= window_end:
            raise ValueError('invalid backfill window: start must precede end')
        if window_end - window_start > timedelta(days=MAX_BACKFILL_DAYS):
            raise ValueError(f'backfill window exceeds {MAX_BACKFILL_DAYS} days')
        if type(max_batches) is not int or not 1 <= max_batches <= MAX_BACKFILL_BATCHES:
            raise ValueError(f'max_batches must be between 1 and {MAX_BACKFILL_BATCHES}')
        policy = _policy(conn, domain, selected, lock=True)
        if policy is None or not policy['enabled']:
            raise ValueError('policy_disabled: enable the scoped policy first')
        if window_end > policy['forward_from']:
            raise ValueError('backfill end must not exceed the policy forward boundary')
        row = conn.execute(
            'INSERT INTO public.synthesis_backfills(policy_id,domain,project_scope,window_start,window_end,max_batches,'
            'reason,owner,requested_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',
            (policy['id'], domain, selected, window_start, window_end, max_batches, reason,
             json.dumps(owner) if (owner := _owner()) else None, actor)).fetchone()
        conn.execute('INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,%s,NULL,%s)',
                     (actor, 'synthesis_backfill', f'{domain} {selected}: {_time(window_start)}..{_time(window_end)}'
                      f' max {max_batches} batches; {reason}'))
        if commit:
            conn.commit()
        return _backfill_view(row)
    except BaseException:
        if commit:
            conn.rollback()
        raise


def _backfill_view(row):
    return {'id': str(row['id']), 'policy_id': str(row['policy_id']), 'window_start': _time(row['window_start']),
            'window_end': _time(row['window_end']), 'max_batches': row['max_batches'], 'batches': row['batches'],
            'state': row['state'], 'created_at': _time(row['created_at'])}


def _run_view(row):
    usage = row['usage'] or {}
    result = row['result'] or {}
    return {'id': str(row['id']), 'policy_id': str(row['policy_id']), 'kind': row['kind'], 'state': row['state'],
            'code': row['code'], 'candidates': row['candidates'], 'provider_calls': usage.get('provider_calls', 0),
            'provider_seconds': usage.get('provider_seconds'), 'input_chars': usage.get('input_chars'),
            'applied': result.get('applied', 0), 'non_conclusions': result.get('non_conclusions', []),
            'rejected': result.get('rejected', []),
            'created_at': _time(row['created_at']), 'updated_at': _time(row['updated_at'])}


def _forward(conn, policy):
    if not policy['enabled']:
        return {'pending_memories': 0, 'waiting': 'policy_disabled'}
    after = (policy['cursor_at'], policy['cursor_id']) if policy['cursor_at'] else None
    selection = candidates(conn, policy['domain'], policy['project_scope'], start=policy['forward_from'],
                           after=after, settle=True)
    view = {'pending_memories': len(selection['memories'])}
    if selection['more']:
        view['more'] = True
    open_run = conn.execute("SELECT 1 FROM public.synthesis_runs WHERE policy_id=%s AND state IN ('pending','accepted')",
                            (policy['id'],)).fetchone()
    if (view['pending_memories'] and not open_run and not selection['independence']['sufficient']
            and len(selection['memories']) < MAX_MEMORIES and not selection['more']):
        view['waiting'] = 'insufficient_independent_support'
    return view


def status(conn, cfg, *, domain=None, project=None, scope=None, limit=20) -> dict:
    """Bounded operator view; no prompts, quotes, provider errors or owners."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('invalid_limit')
    if not installed(conn):
        return {'contract_version': CONTRACT_VERSION, 'installed': False, 'policies': [], 'backfills': [], 'runs': []}
    filters, params = 'true', []
    if domain is not None:
        filters += ' AND domain=%s'
        params.append(domain)
    if project is not None or scope is not None:
        filters += ' AND project_scope=%s'
        params.append(policy_scope(project, scope))
    policies = conn.execute('SELECT * FROM public.synthesis_policies WHERE ' + filters
                            + ' ORDER BY domain,project_scope LIMIT %s', [*params, limit]).fetchall()
    ids = [p['id'] for p in policies]
    backfills = conn.execute("SELECT * FROM public.synthesis_backfills WHERE policy_id=ANY(%s) AND state='pending'"
                             ' ORDER BY created_at LIMIT %s', (ids, limit)).fetchall()
    runs = conn.execute('SELECT * FROM public.synthesis_runs WHERE policy_id=ANY(%s) ORDER BY created_at DESC,id LIMIT %s',
                        (ids, limit)).fetchall()
    return {'contract_version': CONTRACT_VERSION, 'installed': True, 'global_enabled': cfg.synthesis_enabled,
            'policies': [{**_policy_view(p), 'forward': _forward(conn, p)} for p in policies],
            'backfills': [_backfill_view(b) for b in backfills], 'runs': [_run_view(r) for r in runs]}


# ------------------------------------------------------------- scheduling

def _create_run(conn, policy, selection, *, kind, backfill=None):
    snapshot = _snapshot(selection)
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    end_at, end_id = selection['last'] if selection['last'] else (None, None)
    row = conn.execute(
        'INSERT INTO public.synthesis_runs(policy_id,policy_version,backfill_id,kind,domain,project_scope,candidates,'
        'snapshot,snapshot_hash,end_cursor_at,end_cursor_id,owner) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'
        ' ON CONFLICT DO NOTHING RETURNING id',
        (policy['id'], policy['version'], backfill['id'] if backfill else None, kind, policy['domain'],
         policy['project_scope'], len(snapshot['memories']), json.dumps(snapshot), digest, end_at, end_id,
         json.dumps(owner) if (owner := (backfill or {}).get('owner') or policy['owner']) else None)).fetchone()
    if row is None:
        return None
    conn.execute("INSERT INTO mining_queue(kind,payload) VALUES ('synthesis',%s)", (json.dumps({'run': str(row['id'])}),))
    return row['id']


def _schedule_backfill(conn, policy):
    backfill = conn.execute("SELECT * FROM public.synthesis_backfills WHERE policy_id=%s AND state='pending'"
                            ' ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED', (policy['id'],)).fetchone()
    if backfill is None:
        return False
    after = (backfill['cursor_at'], backfill['cursor_id']) if backfill['cursor_at'] else None
    selection = candidates(conn, policy['domain'], policy['project_scope'], start=backfill['window_start'],
                           end=backfill['window_end'], after=after)
    if not selection['memories']:
        conn.execute("UPDATE public.synthesis_backfills SET state='done',finished_at=now() WHERE id=%s", (backfill['id'],))
        return False
    run = _create_run(conn, policy, selection, kind='backfill', backfill=backfill)
    if run is None:
        return False
    exhausted = not selection['more'] or backfill['batches'] + 1 >= backfill['max_batches']
    end_at, end_id = selection['last']
    conn.execute("UPDATE public.synthesis_backfills SET batches=batches+1,cursor_at=%s,cursor_id=%s,"
                 "state=CASE WHEN %s THEN 'done' ELSE state END,finished_at=CASE WHEN %s THEN now() END WHERE id=%s",
                 (end_at, end_id, exhausted, exhausted, backfill['id']))
    return True


def _schedule_forward(conn, policy):
    if policy['next_due_at'] is None or policy['next_due_at'] > datetime.now(timezone.utc):
        return False
    after = (policy['cursor_at'], policy['cursor_id']) if policy['cursor_at'] else None
    selection = candidates(conn, policy['domain'], policy['project_scope'], start=policy['forward_from'],
                           after=after, settle=True)
    full = len(selection['memories']) >= MAX_MEMORIES or selection['more']
    if not selection['memories'] or not (selection['independence']['sufficient'] or full):
        return False  # wait for more independent support; the cursor stays
    if _create_run(conn, policy, selection, kind='forward') is None:
        return False
    conn.execute('UPDATE public.synthesis_policies SET next_due_at=now()+make_interval(secs=>interval_seconds)'
                 ' WHERE id=%s', (policy['id'],))
    return True


def schedule(conn, cfg) -> dict:
    """Existing worker tick only: at most max_runs_per_tick new runs, one open run per policy."""
    if not cfg.synthesis_enabled or not installed(conn):
        return {'scheduled': 0, 'policies': 0}
    try:
        policies = conn.execute('SELECT * FROM public.synthesis_policies WHERE enabled'
                                ' ORDER BY next_due_at NULLS LAST,id LIMIT 100').fetchall()
        scheduled = 0
        for policy in policies:
            if scheduled >= cfg.synthesis_max_runs_per_tick:
                break
            if conn.execute("SELECT 1 FROM public.synthesis_runs WHERE policy_id=%s AND state IN ('pending','accepted')",
                            (policy['id'],)).fetchone():
                continue
            if _schedule_backfill(conn, policy) or _schedule_forward(conn, policy):
                scheduled += 1
        conn.commit()
        return {'scheduled': scheduled, 'policies': len(policies)}
    except BaseException:
        conn.rollback()
        raise
