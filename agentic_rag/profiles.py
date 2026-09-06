"""Rebuildable, bounded references to current project evidence, never new knowledge."""
from __future__ import annotations

import hashlib
import json
import re

from . import scope

VERSION = 'profile-v1'
SECTION_LIMIT = 6
TEXT_LIMIT = 600
SOURCE_LIMIT = 8
_CONVENTION = re.compile(r'(prefer|preference|convention|always|never|bevorzug|konvention|immer|niemals|we use|wir nutzen|wir verwenden)', re.I)


def _identity(project):
    return scope.project_id(project) if project else 'global'


def config_key(cfg):
    return f'{VERSION}:{SECTION_LIMIT}:{TEXT_LIMIT}:{SOURCE_LIMIT}:{cfg.stale_days}'


def revision(conn, cfg, project=None):
    """One scalar fingerprint; no canonical bodies or quotes cross this boundary.

    Visible tuple versions catch out-of-order commits. Temporal booleans catch
    eligibility changes without writes; no per-document eligibility function runs.
    """
    scopes = scope.selection(project, None if project else 'global')
    row = conn.execute("""
      SELECT md5(COALESCE(string_agg(token,',' ORDER BY id),'')) AS digest FROM (
        SELECT d.id, concat_ws(':',d.id,d.xmin::text,c.xmin::text,a.xmin::text,
          d.updated_at >= statement_timestamp()-make_interval(days => %s),
          a.event_at <= statement_timestamp(),a.expires_at <= statement_timestamp(),
          (SELECT md5(string_agg(concat_ws(':',e.source_key,e.span_hash,e.xmin::text,s.xmin::text),
             ',' ORDER BY e.source_key,e.span_hash)) FROM claim_evidence e
             JOIN knowledge_sources s USING(source_key) WHERE e.document_id=d.id),
          (SELECT md5(string_agg(concat_ws(':',z.source_hash,z.xmin::text),',' ORDER BY z.source_hash))
             FROM assertion_sources z WHERE z.document_id=d.id)) AS token
        FROM documents d LEFT JOIN claim_records c ON c.document_id=d.id
        LEFT JOIN fact_assertions a ON a.document_id=d.id
        WHERE d.project_scope=ANY(%s)
      ) versions
      """,(cfg.stale_days,scopes)).fetchone()
    return hashlib.sha256(json.dumps([config_key(cfg),scopes,row['digest']]).encode()).hexdigest()


def _rows(conn,cfg,project,*,ids=None,stable=None,exclude=None):
    """Resolve at most twelve eligible references; refresh uses bounded SQL selection."""
    scopes = scope.selection(project, None if project else 'global')
    return conn.execute("""
        SELECT d.id,d.slug,d.title,left(d.body,601) AS body,d.created_at,d.xmin::text AS doc_version,
          d.status, c.kind,c.review_state,c.xmin::text AS claim_version,
          a.event_at,a.expires_at,a.xmin::text AS assertion_version,
          assertion_eligible(d.id,statement_timestamp()) AS eligible,
          d.updated_at >= statement_timestamp()-make_interval(days => %s) AS recent,
          a.event_at <= statement_timestamp() AS event_started,
          a.expires_at <= statement_timestamp() AS expired,
          COALESCE((SELECT jsonb_agg(to_jsonb(selected) ORDER BY selected.priority,selected.source_key,selected.span_hash)
            FROM (
              SELECT s.source_key,s.state,s.role,e.quote,e.complete,e.reviewed,e.span_hash,
                CASE WHEN s.state='active' AND s.role='user' AND e.complete
                          AND position(btrim(d.body) IN e.quote)>0 THEN 0
                     WHEN s.state='active' AND ((c.review_state='confirmed' AND e.reviewed)
                          OR (c.kind='stated' AND s.role='user' AND e.complete)) THEN 1
                     ELSE 2 END AS priority
              FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
              WHERE e.document_id=d.id ORDER BY priority,s.source_key,e.span_hash LIMIT 8
            ) selected),'[]'::jsonb) AS sources,
          (SELECT bool_and(e.complete) FROM claim_evidence e
             JOIN knowledge_sources s USING(source_key) WHERE e.document_id=d.id
             AND s.state='active' AND ((c.review_state='confirmed' AND e.reviewed)
                OR (c.kind='stated' AND s.role='user' AND e.complete))) AS sources_complete,
          (SELECT count(*)>8 FROM claim_evidence e WHERE e.document_id=d.id) AS sources_omitted
        FROM documents d LEFT JOIN claim_records c ON c.document_id=d.id
        LEFT JOIN fact_assertions a ON a.document_id=d.id
        WHERE d.project_scope=ANY(%s) AND d.status='active'
          AND assertion_eligible(d.id,statement_timestamp())
          AND (%s::uuid[] IS NULL OR d.id=ANY(%s::uuid[]))
          AND (%s::boolean IS NULL OR CASE WHEN %s THEN
            c.kind='stated' AND length(btrim(d.body)) BETWEEN 1 AND 600
            AND d.body ~* %s
            AND EXISTS(SELECT 1 FROM claim_evidence se JOIN knowledge_sources ss USING(source_key)
              WHERE se.document_id=d.id AND ss.state='active' AND ss.role='user'
              AND se.complete AND position(btrim(d.body) IN se.quote)>0)
          ELSE d.updated_at >= statement_timestamp()-make_interval(days => %s) END)
          AND NOT (d.id=ANY(%s::uuid[]))
        ORDER BY COALESCE(a.event_at,d.updated_at) DESC,d.id DESC LIMIT 12
        """, (cfg.stale_days, scopes, ids, ids, stable, stable, _CONVENTION.pattern, cfg.stale_days, exclude or [])).fetchall()


def _item(row):
    sources = [s for s in row['sources'] if s['state']=='active' and (
        (row['review_state']=='confirmed' and s['reviewed']) or
        (row['kind']=='stated' and s['role']=='user' and s['complete']))]
    body = row['body'].strip()
    return {'id':str(row['id']), 'slug':row['slug'], 'title':row['title'],
            'text':body if len(body)<=TEXT_LIMIT else body[:TEXT_LIMIT-1]+'…',
            'source_keys':list(dict.fromkeys(s['source_key'] for s in sorted(
                sources,key=lambda s:(not (s['role']=='user' and s['complete'] and body in s['quote']),
                                      s['source_key']))))[:SOURCE_LIMIT],
            'kind':row['kind'] or 'legacy',
            'review_state':row['review_state'] or 'unreviewed',
            'provenance_status':'complete' if row['sources_complete'] else 'incomplete',
            'event_at':row['event_at'], 'expires_at':row['expires_at']}


def _stable(row):
    body = row['body'].strip()
    return (row['kind']=='stated' and bool(body) and len(body)<=TEXT_LIMIT
            and bool(_CONVENTION.search(body)) and any(
                s['state']=='active' and s['role']=='user' and s['complete']
                and body in s['quote'] for s in row['sources']))


def _eligible(row):
    return row['status']=='active' and row['eligible'] and bool(row['body'].strip())


def read(conn, cfg, project=None):
    """Read cached IDs, resolving every item against live applicability and trust."""
    key = _identity(project)
    cached = conn.execute('SELECT * FROM project_profiles WHERE project_key=%s',(key,)).fetchone()
    current = revision(conn,cfg,project)
    result = {'project':key,'revision':current,'generated_at':None,'status':'missing',
              'warnings':[],'sections':{'stable':[],'recent':[]}}
    if not cached:
        result['warnings'].append('Project profile missing; refresh queued by startup maintenance.')
        return result
    result['generated_at'] = cached['generated_at']
    result['status'] = ('fresh' if cached['revision']==current and
                        cached['config_key']==config_key(cfg) else 'stale')
    if result['status']=='stale':
        result['warnings'].append('Dated project profile; current eligibility revalidated, refresh needed.')
    rows = _rows(conn,cfg,project,ids=list(cached['stable_ids'])+list(cached['recent_ids']))
    available = {str(r['id']):r for r in rows if _eligible(r)}
    for section in ('stable','recent'):
        if len(cached[f'{section}_ids']) == SECTION_LIMIT:
            result['warnings'].append(f'Profile {section} limited to six entries; additional entries may be omitted.')
        for doc_id in cached[f'{section}_ids']:
            row = available.get(str(doc_id))
            if row and (_stable(row) if section=='stable' else row['recent']):
                result['sections'][section].append(_item(row))
                if row['sources_omitted']:
                    result['warnings'].append(f'Profile source references capped at eight spans: {doc_id}')
            else:
                result['warnings'].append(f'Profile {section} reference omitted after revalidation: {doc_id}')
    return result


def _audit(conn, actor, project):
    from .secrets import strip_secrets
    conn.execute('INSERT INTO audit_log(actor,op,summary) VALUES (%s,%s,%s)',
                 (actor,'profile_refresh',strip_secrets(f'Rebuilt bounded profile references for {project}')[0]))


def _refresh(conn, cfg, project=None, *, actor='worker'):
    key = _identity(project)
    try:
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('project_profile:'+key,))
        current = revision(conn,cfg,project)
        stable = [str(r['id']) for r in _rows(conn,cfg,project,stable=True)][:SECTION_LIMIT]
        recent = [str(r['id']) for r in _rows(conn,cfg,project,stable=False,exclude=stable)][:SECTION_LIMIT]
        conn.execute('''INSERT INTO project_profiles(project_key,config_key,revision,stable_ids,recent_ids)
            VALUES (%s,%s,%s,%s::uuid[],%s::uuid[]) ON CONFLICT(project_key) DO UPDATE SET
            config_key=excluded.config_key,revision=excluded.revision,
            stable_ids=excluded.stable_ids,recent_ids=excluded.recent_ids,
            generated_at=clock_timestamp()''', (key,config_key(cfg),current,stable,recent))
        _audit(conn,actor,key)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return read(conn,cfg,project)


def refresh(conn, cfg, project=None, *, actor='worker'):
    """Public refresh always enters the audited store gateway."""
    from .store import refresh_profile
    return refresh_profile(conn,cfg,project,actor=actor)
