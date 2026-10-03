"""Incremental local extractive views. Canonical evidence remains the authority."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import re
import time

from . import scope
from .secrets import strip_secrets

VERSION = 'thematic-v1'
SOURCE_LIMIT = 24
EXCERPT_CHARS = 240
CHUNK_CHARS = 4096
DEFAULT_THEMES = ('provider-outages', 'deployment-architecture', 'operational-lessons')
QUERIES = {
    'provider-outages': 'provider OR outage OR authentication OR oauth OR Ausfall OR Störung',
    'deployment-architecture': 'deployment OR architecture OR PostgreSQL OR pgvector OR Architektur OR Bereitstellung',
    'operational-lessons': 'lesson OR recovery OR restore OR rehearsal OR Lehre OR Wiederherstellung',
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _selection(topic, project, domain, history, context_chars):
    if not isinstance(topic, str) or not 1 <= len(topic.strip()) <= 120 or '\x00' in topic:
        raise ValueError('topic requires 1–120 nonempty characters')
    if domain is not None and (not isinstance(domain, str) or not 1 <= len(domain) <= 120 or '\x00' in domain):
        raise ValueError('domain requires 1–120 characters')
    if type(history) is not bool:
        raise ValueError('history must be boolean')
    if type(context_chars) is not int or not 1000 <= context_chars <= 12000:
        raise ValueError('context_chars must be an integer between 1000 and 12000')
    topic = topic.strip()
    scopes = scope.selection(project, None if project else 'global')
    key = _digest([topic, scopes, domain, history])
    return topic, scopes, key


@contextmanager
def _bounded(conn):
    """Bound SQL/lock waits, preserve any shorter caller limit and restore settings."""
    with conn.transaction():
        prior = conn.execute("SELECT current_setting('statement_timeout') s, current_setting('lock_timeout') l").fetchone()
        # pg_settings exposes milliseconds regardless of the input unit.
        limits = conn.execute("SELECT name,setting::int value FROM pg_settings WHERE name IN ('statement_timeout','lock_timeout')").fetchall()
        for row in limits:
            cap = 5000 if row['name'] == 'statement_timeout' else 2000
            conn.execute('SELECT set_config(%s,%s,true)', (row['name'], str(min(row['value'] or cap, cap))))
        yield
        conn.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)", (prior['s'], prior['l']))


def _available(conn):
    return conn.execute("SELECT to_regclass('public.thematic_summaries') IS NOT NULL present").fetchone()['present']


def _state(conn, topic, scopes, domain, history, key):
    """Cache and current eligible/versioned pool share one statement snapshot.

    Each FTS branch filters before limiting. SQL scan cost still depends on the
    visible corpus; transferred rows, chunks and excerpt work are bounded.
    """
    row = conn.execute("""
      WITH matches AS (
        SELECT d.id document_id,c.id chunk_id,c.idx,
          ts_rank_cd(c.tsv_en,websearch_to_tsquery('english',%(query)s)) +
          ts_rank_cd(c.tsv_de,websearch_to_tsquery('german',%(query)s)) rank
        FROM chunks c JOIN documents d ON d.id=c.document_id
        LEFT JOIN fact_assertions a ON a.document_id=d.id
        WHERE (c.tsv_en @@ websearch_to_tsquery('english',%(query)s)
            OR c.tsv_de @@ websearch_to_tsquery('german',%(query)s))
          AND d.status='active' AND d.project_scope=ANY(%(scopes)s)
          AND (%(domain)s::text IS NULL OR d.domain=%(domain)s)
          AND claim_eligible(d.id)
          AND CASE WHEN %(history)s THEN a.document_id IS NULL OR
            (a.disposition='accepted' AND a.event_at<=statement_timestamp()
             AND (a.expires_at IS NULL OR a.expires_at>statement_timestamp()))
            ELSE assertion_eligible(d.id,statement_timestamp()) END
      ), chosen AS (
        SELECT DISTINCT ON (document_id) document_id,chunk_id,rank FROM matches
        ORDER BY document_id,rank DESC,idx,chunk_id
      ), pool AS (
        SELECT * FROM chosen ORDER BY rank DESC,document_id LIMIT 25
      ), versions AS (
        SELECT d.id document_id,c.id chunk_id,left(d.title,160) title,d.slug,d.domain,
          d.project_scope,d.dtype,d.created_at,a.event_at,a.expires_at,
          COALESCE(cr.kind,'legacy') source_kind,COALESCE(cr.review_state,'unreviewed') review_state,
          d.xmin::text document_version,c.xmin::text chunk_version,
          cr.xmin::text claim_version,a.xmin::text assertion_version,
          (SELECT md5(string_agg(concat_ws(':',e.source_key,e.span_hash,e.xmin::text,s.xmin::text),
            ',' ORDER BY e.source_key,e.span_hash)) FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
            WHERE e.document_id=d.id) sources_version,
          (SELECT md5(string_agg(concat_ws(':',z.source_hash,z.xmin::text),',' ORDER BY z.source_hash))
            FROM assertion_sources z WHERE z.document_id=d.id) assertion_sources_version,
          EXISTS(SELECT 1 FROM fact_assertions newer JOIN documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute AND nd.project_scope=d.project_scope
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at>a.event_at AND newer.event_at<=statement_timestamp()) superseded,
          COALESCE((SELECT jsonb_agg(to_jsonb(x)) FROM (
            SELECT s.source_key,e.span_hash,s.xmin::text source_version,e.xmin::text span_version,
              s.role,s.source_at,e.complete,e.reviewed
            FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
            WHERE e.document_id=d.id AND s.state='active'
              AND ((cr.review_state='confirmed' AND e.reviewed) OR (cr.kind='stated' AND s.role='user' AND e.complete))
            ORDER BY s.source_key,e.span_hash LIMIT 8
          ) x),'[]'::jsonb) sources,
          (SELECT count(*)>8 FROM claim_evidence e WHERE e.document_id=d.id) sources_omitted,
          pool.rank
        FROM pool JOIN documents d ON d.id=pool.document_id JOIN chunks c ON c.id=pool.chunk_id
        LEFT JOIN claim_records cr ON cr.document_id=d.id LEFT JOIN fact_assertions a ON a.document_id=d.id
      )
      SELECT (SELECT to_jsonb(t) FROM thematic_summaries t WHERE selection_key=%(key)s) cache,
        COALESCE((SELECT jsonb_agg(to_jsonb(v) ORDER BY rank DESC,document_id) FROM versions v),'[]'::jsonb) candidates
      """, dict(query=QUERIES.get(topic, topic), scopes=scopes, domain=domain, history=history, key=key)).fetchone()
    candidates = row['candidates']
    for item in candidates:
        item.pop('rank')
        item['source_version'] = _digest(item)
    return row['cache'], candidates[:SOURCE_LIMIT], len(candidates) > SOURCE_LIMIT


def _excerpt(content, topic):
    # Select an exact sentence when possible; long sentences stay visibly clipped.
    terms = re.findall(r'\w+', QUERIES.get(topic, topic).lower())
    terms = [t for t in terms if t != 'or']
    spans = list(re.finditer(r'[^.!?\n]+(?:[.!?]+|$)', content))
    ranked = sorted(spans, key=lambda m: (-sum(t in m.group().lower() for t in terms), m.start()))
    match = ranked[0] if ranked else None
    start = match.start() if match else 0
    end = match.end() if match else len(content)
    while start < end and content[start].isspace(): start += 1
    while end > start and content[end-1].isspace(): end -= 1
    clipped = end-start > EXCERPT_CHARS
    end = min(end, start+EXCERPT_CHARS)
    return start, end, clipped


def _build_entry(conn, candidate, topic):
    # Verify chunk/document versions again during hydration. Concurrent changes
    # fail closed; the next read revalidates every complete source fingerprint.
    row = conn.execute('SELECT left(c.content,%s) content,length(c.content)>%s chunk_clipped '
        'FROM chunks c JOIN documents d ON d.id=c.document_id '
        'WHERE c.id=%s AND c.xmin::text=%s AND d.xmin::text=%s',
        (CHUNK_CHARS, CHUNK_CHARS, candidate['chunk_id'], candidate['chunk_version'], candidate['document_version'])).fetchone()
    if not row or not row['content'].strip(): return None
    content = row['content']
    start, end, clipped = _excerpt(content, topic)
    entry = {k:candidate[k] for k in ('document_id','chunk_id','slug','title','domain','project_scope',
                'source_kind','review_state','event_at','expires_at','sources','sources_omitted','source_version')}
    entry.update(text=content[start:end], start=start, end=end,
        citation=f"{candidate['document_id']}#{candidate['chunk_id']}:{start}-{end}",
        versions={k.removesuffix('_version'):v for k,v in candidate.items() if k.endswith('_version') and k!='source_version'},
        provenance_status='complete' if candidate['sources'] and all(s['complete'] for s in candidate['sources']) and not candidate['sources_omitted'] else 'incomplete',
        temporal_status='historical_superseded' if candidate['superseded'] else 'current',
        clipped=clipped or row['chunk_clipped'])
    return entry


def _packet(topic, scopes, domain, history, context_chars):
    return dict(topic=topic, scopes=scopes, domain=domain, history=history, status='missing',
        inference_status='extractive_theme_membership', generated_at=None, revision=None,
        entries=[], context='', warnings=[], context_chars=0, context_budget=context_chars,
        usage={'candidates':0,'rebuilt':0,'reused':0,'provider_calls':0,'elapsed_ms':0},
        invalidated=0, omitted=0, baseline='Use ordinary search/get/profile for original evidence.')


def _present(packet, cache, candidates, capped, context_chars):
    current = _digest([VERSION, candidates, capped])
    packet['revision'] = current
    packet['usage']['candidates'] = len(candidates)
    if not cache:
        packet['warnings'].append('Thematic cache missing; original evidence remains available.')
        return packet
    packet['generated_at'] = cache['generated_at']
    valid = {c['document_id']:c for c in candidates}
    entries = [e for e in cache['entries'] if e['document_id'] in valid
               and e['source_version'] == valid[e['document_id']]['source_version']]
    packet['invalidated'] = len(cache['entries'])-len(entries)
    missing = len(candidates)-len(entries)
    packet['status'] = 'fresh' if cache['revision']==current and cache['config_key']==VERSION and not missing else 'stale'
    if cache['config_key'] != VERSION:
        packet['invalidated'] = len(cache['entries']); entries = []
    if packet['status']=='stale': packet['warnings'].append('Changed evidence withheld; refresh needed.')
    if missing: packet['warnings'].append(f'{missing} eligible source excerpts are not cached.')
    if capped: packet['warnings'].append('Eligible source pool capped at 24 documents; coverage is partial.')
    header = f"Theme: {packet['topic']} (extractive grouping; no synthesized canonical truth)\n"
    lines = []
    for entry in entries:
        line = f"- {entry['temporal_status']} [{entry['citation']}] {json.dumps(entry['text'],ensure_ascii=False)}"
        line += f"; kind={entry['source_kind']}, review={entry['review_state']}, provenance={entry['provenance_status']}"
        if entry['clipped']: line += ' [clipped excerpt]'
        if len(header+'\n'.join(lines+[line])) <= context_chars:
            lines.append(line); packet['entries'].append(entry)
        else: packet['omitted'] += 1
    packet['context'] = header+'\n'.join(lines) if lines else ''
    packet['context_chars'] = len(packet['context'])
    if packet['omitted']: packet['warnings'].append('Whole excerpts omitted by the context budget.')
    return packet


def read(conn, cfg, topic, *, project=None, domain=None, history=False, context_chars=4800):
    """Reader-safe derived view; SQL/cache failure retains the baseline transaction."""
    started = time.perf_counter()
    topic, scopes, key = _selection(topic, project, domain, history, context_chars)
    packet = _packet(topic, scopes, domain, history, context_chars)
    try:
        with _bounded(conn):
            if not _available(conn):
                packet['status'] = 'unavailable'
                packet['warnings'].append('Migration017 unavailable; baseline evidence access retained.')
            else:
                cache, candidates, capped = _state(conn, topic, scopes, domain, history, key)
                _present(packet, cache, candidates, capped, context_chars)
    except Exception as exc:
        packet.update(status='unavailable', entries=[], context='', context_chars=0)
        packet['warnings'] = ['Thematic read unavailable: '+type(exc).__name__+'; baseline access retained.']
    packet['usage']['elapsed_ms'] = round((time.perf_counter()-started)*1000, 3)
    return packet


def _refresh(conn, cfg, topic, *, project=None, domain=None, history=False, context_chars=4800, actor='worker', commit=True):
    started = time.perf_counter()
    topic, scopes, key = _selection(topic, project, domain, history, context_chars)
    reused = rebuilt = 0
    try:
        if conn.autocommit:
            raise ValueError('Thematic refresh requires a transactional connection')
        # Own the transaction explicitly; _bounded must only own a savepoint.
        # In particular commit=False on an initially idle connection stays open.
        conn.execute('SELECT 1')
        with _bounded(conn):
            if not _available(conn):
                return read(conn,cfg,topic,project=project,domain=domain,history=history,context_chars=context_chars)
            allowed = conn.execute("SELECT has_table_privilege(current_user,'thematic_summaries','INSERT') "
                "AND has_table_privilege(current_user,'thematic_summaries','UPDATE') "
                "AND has_table_privilege(current_user,'audit_log','INSERT') allowed").fetchone()['allowed']
            if not allowed:
                raise PermissionError('Thematic refresh requires audited writer authority')
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (int.from_bytes(bytes.fromhex(key[:16]),signed=True),))
            cache, candidates, capped = _state(conn, topic, scopes, domain, history, key)
            old = {e['document_id']:e for e in cache['entries']} if cache and cache['config_key']==VERSION else {}
            entries = []
            for candidate in candidates:
                previous = old.get(candidate['document_id'])
                if previous and previous['source_version']==candidate['source_version']:
                    entries.append(previous); reused += 1
                else:
                    entry = _build_entry(conn,candidate,topic)
                    if entry: entries.append(entry); rebuilt += 1
            current = _digest([VERSION, candidates, capped])
            # A no-change retry does not rewrite the cache or grow the audit log.
            if not cache or cache['revision']!=current or cache['config_key']!=VERSION or cache['entries']!=entries:
                conn.execute('INSERT INTO thematic_summaries(selection_key,config_key,revision,entries) VALUES (%s,%s,%s,%s) '
                    'ON CONFLICT(selection_key) DO UPDATE SET config_key=excluded.config_key,revision=excluded.revision,'
                    'entries=excluded.entries,generated_at=clock_timestamp()', (key,VERSION,current,json.dumps(entries,default=str)))
                _audit(conn,actor,key,rebuilt,reused)
        if commit: conn.commit()
    except BaseException:
        if commit: conn.rollback()
        raise
    packet = read(conn,cfg,topic,project=project,domain=domain,history=history,context_chars=context_chars)
    packet['usage'].update(rebuilt=rebuilt,reused=reused,elapsed_ms=round((time.perf_counter()-started)*1000,3))
    return packet


def _audit(conn,actor,key,rebuilt,reused):
    conn.execute("INSERT INTO audit_log(actor,op,summary) VALUES (%s,'summary_refresh',%s)",
                 (actor,strip_secrets(f'Thematic view {key}; rebuilt={rebuilt}; reused={reused}')[0]))


def refresh(conn, cfg, topic, **kwargs):
    from .store import refresh_summaries
    return refresh_summaries(conn,cfg,topic,**kwargs)
