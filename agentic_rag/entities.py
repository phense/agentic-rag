"""Exact scoped identities and operator-confirmed reversible alias selections.

Original assertions never change. This module is local: neither embeddings nor
providers participate. All mutation entry points are exposed through store.py.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from . import scope
from .secrets import strip_secrets, strip_secrets_json
from .validity import parse_time, selection
from .thematic import _bounded

NAMESPACE = uuid.UUID('f3d3af6d-2d06-4d99-88d1-902aa4de6c51')
LINK_LIMIT = 32
FACT_LIMIT = 100


def _text(value, label, limit=2000):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or '\x00' in value:
        raise ValueError(f'{label} requires 1–{limit} nonempty characters without NUL')
    return strip_secrets(value.strip())[0]


def _selector(project, selected_scope, domain):
    domain = _text(domain, 'domain', 120)
    chosen = scope.write_scope(project=project, scope=selected_scope)
    if chosen is None or chosen == 'unknown':
        raise ValueError('entity resolution requires a known project or explicit global scope')
    return chosen, domain


def available(conn):
    return conn.execute("SELECT to_regclass('public.entity_aliases') IS NOT NULL present").fetchone()['present']


def _lock(conn, project_scope, domain):
    encoded = json.dumps(['entity-boundary-v1', project_scope, domain], ensure_ascii=False)
    key = int.from_bytes(hashlib.sha256(encoded.encode()).digest()[:8], signed=True)
    conn.execute('SELECT pg_advisory_xact_lock(%s)', (key,))


def _exact_id(project_scope, domain, name):
    return str(uuid.uuid5(NAMESPACE, json.dumps([project_scope, domain, name], ensure_ascii=False)))


def _identity(conn, project_scope, domain, name, actor):
    identity = _exact_id(project_scope,domain,name)
    row = conn.execute('INSERT INTO entity_identities(id,project_scope,domain,name) VALUES (%s,%s,%s,%s)'
                       ' ON CONFLICT DO NOTHING RETURNING id', (identity, project_scope, domain, name)).fetchone()
    if row:
        _audit(conn, actor, 'entity_identity', None, f'created exact identity {identity}')
    return identity


def _audit(conn, actor, op, document_id, message):
    conn.execute('INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,%s,%s,%s)',
                 (actor, op, document_id, strip_secrets(message)[0]))


def attach_assertion(conn, document_id, actor):
    """Audited derived attachment; caller owns its assertion transaction."""
    if not available(conn):
        return False
    row = conn.execute('SELECT a.entity,d.project_scope,d.domain FROM fact_assertions a'
                       ' JOIN documents d ON d.id=a.document_id WHERE a.document_id=%s FOR SHARE OF d',
                       (document_id,)).fetchone()
    if not row or row['project_scope'] == 'unknown':
        return False
    _lock(conn, row['project_scope'], row['domain'])
    identity = _identity(conn, row['project_scope'], row['domain'], row['entity'], actor)
    changed = conn.execute('INSERT INTO assertion_entities(document_id,entity_id) VALUES (%s,%s)'
                           ' ON CONFLICT(document_id) DO UPDATE SET entity_id=EXCLUDED.entity_id,indexed_at=now()'
                           ' WHERE assertion_entities.entity_id<>EXCLUDED.entity_id RETURNING document_id',
                           (document_id, identity)).fetchone()
    if changed:
        _audit(conn, actor, 'entity_attachment', document_id, f'exact identity {identity}')
    return bool(changed)


def _backfill(conn, *, limit=100, actor='cli', commit=True):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('limit must be an integer between 1 and 500')
    try:
        if not available(conn):
            raise ValueError('migration018 is required for entity backfill')
        # Serialize only indexing runs. Alias writers never take this lock,
        # and existing assertion/mining clients acquire no new identity locks.
        conn.execute('SELECT pg_advisory_xact_lock(%s)',
                     (int.from_bytes(hashlib.sha256(b'entity-backfill-v1').digest()[:8],signed=True),))
        # No cursor that could miss a concurrent lower UUID. Successfully mapped
        # rows drop out; each unfinished batch rolls back, then retry resumes.
        rows = conn.execute('SELECT a.document_id FROM fact_assertions a JOIN documents d ON d.id=a.document_id'
            ' LEFT JOIN assertion_entities m ON m.document_id=a.document_id LEFT JOIN entity_identities i ON i.id=m.entity_id'
            " WHERE d.project_scope<>'unknown' AND (i.id IS NULL OR i.project_scope<>d.project_scope OR i.domain<>d.domain OR i.name<>a.entity)"
            ' ORDER BY d.project_scope,d.domain,a.document_id LIMIT %s', (limit,)).fetchall()
        mapped = sum(attach_assertion(conn, str(row['document_id']), actor) for row in rows)
        counts = conn.execute("SELECT count(*) FILTER(WHERE d.project_scope='unknown') unresolved,"
            " count(*) FILTER(WHERE d.project_scope<>'unknown' AND (i.id IS NULL OR i.project_scope<>d.project_scope OR i.domain<>d.domain OR i.name<>a.entity)) remaining"
            ' FROM fact_assertions a JOIN documents d ON d.id=a.document_id LEFT JOIN assertion_entities m ON m.document_id=a.document_id'
            ' LEFT JOIN entity_identities i ON i.id=m.entity_id').fetchone()
        if commit:
            conn.commit()
        return dict(mapped=mapped, remaining=counts['remaining'], unresolved=counts['unresolved'])
    except BaseException:
        if commit:
            conn.rollback()
        raise


# Both mutation checks and reader SQL bind support to the original source span.
_SUPPORT = """
    d.status='active' AND d.project_scope=i.project_scope AND d.domain=i.domain
    AND cr.review_state<>'refuted' AND s.state='active' AND s.role='user'
    AND e.complete AND strpos(e.quote,i.name)>0 AND strpos(e.quote,t.name)>0
"""


def _support(conn, document_id):
    return conn.execute('SELECT ('+_SUPPORT+') supported FROM entity_aliases l'
        ' JOIN entity_identities i ON i.id=l.alias_id JOIN entity_identities t ON t.id=l.target_id'
        ' JOIN documents d ON d.id=l.document_id JOIN claim_records cr ON cr.document_id=d.id'
        ' JOIN claim_evidence e ON (e.document_id=l.document_id AND e.source_key=l.source_key AND e.span_hash=l.span_hash)'
        ' JOIN knowledge_sources s ON s.source_key=e.source_key WHERE l.document_id=%s', (document_id,)).fetchone()['supported']


def _conflict(conn, row):
    # Conservatively retain accepted state records in this check even if their
    # support was withdrawn: revoke the old relation before a conflicting repair.
    return conn.execute("SELECT 1 FROM entity_aliases WHERE state='accepted' AND document_id<>%s AND"
        ' (target_id=%s OR alias_id=%s OR (alias_id=%s AND target_id<>%s)) LIMIT 1',
        (row['document_id'], row['alias_id'], row['target_id'], row['alias_id'], row['target_id'])).fetchone()


def _accept(conn, row, actor, reason):
    boundary = conn.execute('SELECT a.project_scope=a2.project_scope AND a.domain=a2.domain ok'
        ' FROM entity_identities a JOIN entity_identities a2 ON a2.id=%s WHERE a.id=%s',
        (row['target_id'], row['alias_id'])).fetchone()
    if not boundary['ok'] or not _support(conn, row['document_id']):
        return 'original complete active user evidence and unchanged scope/domain are required'
    if _conflict(conn, row):
        return 'competing anchor or transitive alias chain requires review/revocation'
    conn.execute('UPDATE claim_evidence SET reviewed=true WHERE document_id=%s AND source_key=%s AND span_hash=%s',
                 (row['document_id'], row['source_key'], row['span_hash']))
    conn.execute("UPDATE entity_aliases SET state='accepted',reason=%s,changed_at=now() WHERE document_id=%s", (reason,row['document_id']))
    _audit(conn, actor, 'entity_alias_review', row['document_id'], 'accepted: '+reason)
    return None


def _save_alias(conn, cfg, *, alias, target, domain, evidence, effective_at,
                project=None, scope=None, confirm=False, actor='cli', commit=True):
    from . import store
    from .evidence import attach
    try:
        if type(confirm) is not bool:
            raise ValueError('confirm must be boolean')
        alias, target = _text(alias, 'alias'), _text(target, 'target')
        if alias == target:
            raise ValueError('alias and target must be distinct exact names')
        selected, domain = _selector(project, scope, domain)
        when = parse_time(effective_at)
        if when is None:
            raise ValueError('effective_at requires an explicit timezone-aware time')
        clean, _ = strip_secrets_json(evidence)
        if not isinstance(clean,dict) or not all(isinstance(clean.get(k),str) and clean[k].strip()
                                               for k in ('namespace','source_id','role','quote')):
            raise ValueError('alias evidence requires namespace, source_id, role and quote')
        if clean['role'] not in ('user','assistant','unknown') or len(clean['quote'])>4000 or len(clean['namespace'])>1000 or len(clean['source_id'])>1000:
            raise ValueError('invalid or unbounded alias evidence')
        if len(json.dumps(clean,ensure_ascii=False)) > 16000:
            raise ValueError('alias evidence exceeds 16000 characters')
        if '\x00' in json.dumps(clean,ensure_ascii=False).replace('\\u0000','\x00'):
            raise ValueError('evidence cannot contain NUL')
        if not available(conn):
            raise ValueError('migration018 is required for aliases')
        _lock(conn, selected, domain)
        key = hashlib.sha256(json.dumps([selected,domain,alias,target,when.isoformat(),clean],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        existing = conn.execute('SELECT * FROM entity_aliases WHERE request_key=%s', (key,)).fetchone()
        if existing:
            if confirm and existing['state']=='review':
                reason = _accept(conn, existing, actor, 'explicit operator confirmation')
                if reason:
                    conn.execute('UPDATE entity_aliases SET reason=%s WHERE document_id=%s AND reason<>%s',
                                 (reason,existing['document_id'],reason))
            row = conn.execute('SELECT document_id,state,reason FROM entity_aliases WHERE request_key=%s', (key,)).fetchone()
            if commit:
                conn.commit()
            return dict(row, document_id=str(row['document_id']), duplicate=True)
        alias_id, target_id = (_identity(conn,selected,domain,name,actor) for name in (alias,target))
        result = store.save_document(conn,cfg,title=f'Entity alias: {alias} → {target}',body=clean['quote'],
            domain=domain,dtype='memory',project=project,scope=scope,
            provenance={'origin':'entity-alias','effective_at':when.isoformat()},actor=actor,commit=False)
        conn.execute("INSERT INTO claim_records(document_id,kind,content_hash) VALUES (%s,'stated',%s)",
                     (result.doc_id,hashlib.sha256(clean['quote'].encode()).hexdigest()))
        attach(conn,result.doc_id,[clean],actor)
        source_key = hashlib.sha256(json.dumps([clean['namespace'],clean['source_id']],ensure_ascii=False).encode()).hexdigest()
        span_hash = hashlib.sha256(clean['quote'].encode()).hexdigest()
        conn.execute("INSERT INTO entity_aliases(document_id,request_key,alias_id,target_id,source_key,span_hash,effective_at,state,reason)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,'review','operator confirmation required')",
            (result.doc_id,key,alias_id,target_id,source_key,span_hash,when))
        _audit(conn, actor, 'entity_alias_save', result.doc_id, 'review: original evidence retained')
        if confirm:
            row = conn.execute('SELECT * FROM entity_aliases WHERE document_id=%s', (result.doc_id,)).fetchone()
            reason = _accept(conn,row,actor,'explicit operator confirmation')
            if reason:
                conn.execute('UPDATE entity_aliases SET reason=%s WHERE document_id=%s', (reason,result.doc_id))
        row = conn.execute('SELECT state,reason FROM entity_aliases WHERE document_id=%s', (result.doc_id,)).fetchone()
        if commit:
            conn.commit()
        return dict(row,document_id=result.doc_id,duplicate=False)
    except BaseException:
        if commit:
            conn.rollback()
        raise


def _review_alias(conn, document_id, *, state, reason, actor='cli', commit=True):
    try:
        if state not in ('accepted','revoked'):
            raise ValueError('alias review state must be accepted or revoked')
        reason = _text(reason,'reason',4000)
        document_id = str(uuid.UUID(document_id))
        row = conn.execute('SELECT l.*,i.project_scope,i.domain FROM entity_aliases l'
                           ' JOIN entity_identities i ON i.id=l.alias_id WHERE l.document_id=%s', (document_id,)).fetchone()
        if not row:
            raise ValueError('alias relation not found')
        _lock(conn,row['project_scope'],row['domain'])
        row = conn.execute('SELECT * FROM entity_aliases WHERE document_id=%s FOR UPDATE', (document_id,)).fetchone()
        if state=='accepted':
            failure = _accept(conn,row,actor,reason)
            if failure:
                raise ValueError(failure)
        elif row['state'] != state or row['reason'] != reason:
            conn.execute('UPDATE entity_aliases SET state=%s,reason=%s,changed_at=now() WHERE document_id=%s', (state,reason,document_id))
            _audit(conn,actor,'entity_alias_review',document_id,'revoked: '+reason)
        if commit:
            conn.commit()
        return dict(document_id=document_id,state=state,reason=reason)
    except BaseException:
        if commit:
            conn.rollback()
        raise


def read(conn, name, *, domain, project=None, scope=None, attribute=None,
         as_of=None, history=False, context_chars=4800):
    """Read original facts across a directly confirmed star, in one snapshot.

    Project selection is exact, not project-plus-global. History includes trusted
    accepted expired/superseded facts, explicitly labeled; future events stay out.
    Limits fail closed so omitted replacements cannot revive an old answer.
    """
    name = _text(name,'name')
    selected, domain = _selector(project,scope,domain)
    if attribute is not None:
        attribute = _text(attribute,'attribute')
    if type(history) is not bool:
        raise ValueError('history must be boolean')
    if type(context_chars) is not int or not 1000<=context_chars<=12000:
        raise ValueError('context_chars must be an integer between 1000 and 12000')
    at, history = selection(as_of,history)
    packet = dict(name=name,project_scope=selected,domain=domain,as_of=at.isoformat(),
        history=history,status='unavailable',identity_id=None,identity_persisted=False,names=[name],name_count=1,links=[],suggestions=[],
        facts=[],context='',context_chars=0,context_budget=context_chars,warnings=[],provider_calls=0)
    try:
        with _bounded(conn):
            if not available(conn):
                packet['warnings']=['Entity index unavailable: migration018 required; use exact-name search/get.']
                return packet
            row = conn.execute("""
              WITH valid_links AS (
                SELECT l.*,i.name alias,t.name target
                FROM entity_aliases l JOIN entity_identities i ON i.id=l.alias_id
                JOIN entity_identities t ON t.id=l.target_id JOIN documents d ON d.id=l.document_id
                JOIN claim_records cr ON cr.document_id=d.id
                JOIN claim_evidence e ON (e.document_id=l.document_id AND e.source_key=l.source_key AND e.span_hash=l.span_hash)
                JOIN knowledge_sources s ON s.source_key=e.source_key
                WHERE l.state='accepted' AND l.effective_at<=%(at)s AND e.reviewed
                  AND i.project_scope=%(scope)s AND t.project_scope=i.project_scope
                  AND i.domain=%(domain)s AND t.domain=i.domain AND
            """+_SUPPORT+"""
              ), named AS (
                SELECT * FROM entity_identities WHERE project_scope=%(scope)s AND domain=%(domain)s AND name=%(name)s
              ), roots AS (
                SELECT DISTINCT target_id id FROM valid_links WHERE alias_id IN(SELECT id FROM named)
                UNION SELECT id FROM named WHERE NOT EXISTS(SELECT 1 FROM valid_links WHERE alias_id=named.id)
              ), names AS (
                SELECT i.id,i.name FROM entity_identities i WHERE i.id IN(SELECT id FROM roots)
                  OR i.id IN(SELECT alias_id FROM valid_links WHERE target_id IN(SELECT id FROM roots))
                UNION SELECT COALESCE((SELECT id FROM named),%(exact_id)s::uuid),%(name)s
              ), linked AS (
                SELECT * FROM valid_links WHERE target_id IN(SELECT id FROM roots)
              ), all_facts AS (
                SELECT a.*,d.slug,d.domain,d.project_scope,d.status,i.id identity_id,
                  EXISTS(SELECT 1 FROM assertion_entities m JOIN entity_identities x ON x.id=m.entity_id
                    WHERE m.document_id=d.id AND x.project_scope=d.project_scope AND x.domain=d.domain AND x.name=a.entity) indexed,
                  d.xmin::text document_version,a.xmin::text assertion_version
                FROM fact_assertions a JOIN documents d ON d.id=a.document_id
                JOIN names i ON i.name=a.entity
                WHERE d.project_scope=%(scope)s AND d.domain=%(domain)s
                  AND a.disposition='accepted' AND a.event_at<=%(at)s
                  AND (%(attribute)s::text IS NULL OR a.attribute=%(attribute)s)
              ), source_facts AS (
                SELECT * FROM all_facts WHERE status='active' AND claim_eligible(document_id)
              ), classified AS (
                SELECT f.*, EXISTS(SELECT 1 FROM all_facts n WHERE n.attribute=f.attribute
                    AND n.relation='replacement' AND n.event_at>f.event_at) superseded,
                  f.expires_at IS NOT NULL AND f.expires_at<=%(at)s expired
                FROM source_facts f
              ), eligible AS (
                SELECT * FROM classified WHERE %(history)s OR (NOT expired AND NOT superseded)
              ), conflicts AS (
                SELECT attribute FROM eligible WHERE NOT %(history)s AND relation<>'extension'
                GROUP BY attribute HAVING count(DISTINCT value)>1
              ), presented AS (
                SELECT f.*,c.id chunk_id,left(c.content,4000) text,c.xmin::text chunk_version,
                  f.attribute IN(SELECT attribute FROM conflicts) ambiguous
                FROM eligible f CROSS JOIN LATERAL (
                    SELECT id,content,xmin FROM chunks WHERE document_id=f.document_id ORDER BY (strpos(content,f.value)>0) DESC,idx,id LIMIT 1
                ) c ORDER BY f.attribute,f.event_at,f.document_id LIMIT %(facts)s
              ), suggestions AS (
                SELECT l.document_id,l.state,l.reason,l.effective_at,i.name alias,t.name target
                FROM entity_aliases l JOIN entity_identities i ON i.id=l.alias_id JOIN entity_identities t ON t.id=l.target_id
                JOIN documents d ON d.id=l.document_id
                WHERE i.project_scope=%(scope)s AND t.project_scope=i.project_scope AND i.domain=%(domain)s AND t.domain=i.domain
                  AND d.project_scope=i.project_scope AND d.domain=i.domain
                  AND (i.name=%(name)s OR t.id IN(SELECT id FROM roots))
                  AND l.document_id NOT IN(SELECT document_id FROM valid_links)
                ORDER BY l.document_id LIMIT %(links)s
              )
              SELECT (SELECT id FROM roots ORDER BY id LIMIT 1) identity_id,
                (SELECT count(*) FROM roots) roots_count,
                (SELECT count(*) FROM names) name_count,
                (SELECT jsonb_agg(name ORDER BY name) FROM (SELECT name FROM names ORDER BY name LIMIT %(names_limit)s) chosen_names) names,
                (SELECT count(*) FROM linked) link_count,
                (SELECT count(*) FROM eligible) fact_count,
                COALESCE((SELECT jsonb_agg(to_jsonb(l)) FROM (SELECT document_id,alias,target,effective_at,source_key,span_hash
                    FROM linked ORDER BY document_id LIMIT %(links)s) l),'[]') links,
                COALESCE((SELECT jsonb_agg(to_jsonb(s)) FROM suggestions s),'[]') suggestions,
                COALESCE((SELECT jsonb_agg(to_jsonb(p) ORDER BY attribute,event_at,document_id) FROM presented p),'[]') facts
              """,dict(at=at,scope=selected,domain=domain,name=name,attribute=attribute,history=history,
                         facts=FACT_LIMIT+1,links=LINK_LIMIT+1,names_limit=LINK_LIMIT+1,exact_id=_exact_id(selected,domain,name))).fetchone()
            packet.update(identity_id=str(row['identity_id']) if row['identity_id'] else _exact_id(selected,domain,name),
                identity_persisted=row['roots_count']>0,names=row['names'],name_count=row['name_count'],links=row['links'][:LINK_LIMIT],suggestions=row['suggestions'][:LINK_LIMIT],status='resolved')
            if row['roots_count']>1:
                packet['status']='ambiguous'
                packet['warnings'].append('Competing identity anchors; answer context withheld.')
            if row['link_count']>LINK_LIMIT or row['fact_count']>FACT_LIMIT:
                packet['status']='limited'
                packet['warnings'].append('Entity relation/fact bound exceeded; incomplete answer withheld.')
            if len(row['suggestions'])>LINK_LIMIT:
                packet['warnings'].append('Additional review relations omitted.')
            if packet['status']!='resolved':
                return packet
            if any(not f['indexed'] for f in row['facts']):
                packet['warnings'].append('Unindexed or changed-domain assertions use derived stable IDs and exact original rows. Run audited backfill to persist attachments.')
            if any(f['ambiguous'] for f in row['facts']):
                packet['status']='ambiguous'
                packet['warnings'].append('Conflicting current values without an unambiguous replacement; affected attributes withheld.')
            lines=[]
            for f in row['facts']:
                text=f['text']
                item={k:f[k] for k in ('document_id','entity','attribute','value','event_at','expires_at','relation','identity_id',
                    'chunk_id','slug','document_version','assertion_version','chunk_version','superseded','expired','ambiguous')}
                item.update(text=text,start=0,end=len(text),citation=f"{f['document_id']}#{f['chunk_id']}:0-{len(text)}")
                packet['facts'].append(item)
                if item['ambiguous']:
                    continue
                label=('historical'+('_superseded' if item['superseded'] else '')+('_expired' if item['expired'] else '')) if history else 'current'
                line=f"- [{item['citation']}] {label}; {item['entity']} / {item['attribute']} / {item['value']}; "+json.dumps(text,ensure_ascii=False)
                if len('\n'.join(lines+[line]))<=context_chars:
                    lines.append(line)
                else:
                    packet['warnings'].append('Whole fact excerpt omitted by context budget.')
            packet['context']='\n'.join(lines)
            packet['context_chars']=len(packet['context'])
            return packet
    except Exception as exc:
        # _bounded's savepoint rolls back optional SQL failure, preserving callers.
        # No private exception text (SQL arguments may contain source content).
        packet.update(status='unavailable',identity_id=None,identity_persisted=False,names=[name],name_count=1,links=[],suggestions=[],facts=[],context='',context_chars=0)
        packet['warnings']=[f'Entity read unavailable ({type(exc).__name__}); use exact-name search/get.']
        return packet
