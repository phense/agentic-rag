"""Private confirmed correction snapshots and network-free local evaluation.

This format cannot enter the synthetic benchmark or a provider stage. Reader
snapshots do not change review state, source trust, schema, caches or audit rows.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from uuid import UUID

from .. import db, entities
from ..secrets import strip_secrets_json, strip_secrets
from ..scope import project_id
from ..validity import parse_time

ROOT = Path(__file__).resolve().parents[2]
MAX_CASES = 32
MAX_HISTORY = 64
MAX_BYTES = 8 * 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}')
SENSITIVE_ATTRIBUTE = re.compile(r'password|passwd|pwd|secret|token|api[_ -]?key|access[_ -]?key|authorization|credential', re.I)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return sha256(_encoded(value)).hexdigest()


def _safe(value):
    _, count = strip_secrets_json(value)
    def redacted(item):
        if isinstance(item, str): return '[REDACTED]' in item
        if isinstance(item, list): return any(redacted(v) for v in item)
        if isinstance(item, dict):
            if isinstance(item.get('attribute'),str) and SENSITIVE_ATTRIBUTE.search(item['attribute']): return True
            return any(redacted(k) or redacted(v) or strip_secrets(str(k))[1] for k,v in item.items())
        return False
    if count or redacted(value):
        raise ValueError('secret or redacted private labels are withheld')


def _git_roots():
    try:
        result = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
            '-C', str(ROOT), 'worktree', 'list', '--porcelain', '-z'],
            check=True, capture_output=True, timeout=3)
        return [Path(line[9:].decode()).resolve() for line in result.stdout.split(b'\0') if line.startswith(b'worktree ')]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ValueError('cannot verify private path outside Git worktrees') from None


def _private_path(path, *, existing=False):
    path = Path(path)
    if not path.is_absolute(): raise ValueError('private artifact requires an absolute path')
    # Inspect before resolve: symlink ancestors must not hide a public target.
    for part in [path, *path.parents]:
        if part.is_symlink(): raise ValueError('private artifact symlink is forbidden')
    path = path.resolve()
    if any(path.is_relative_to(root) for root in _git_roots()) or any((p/'.git').exists() for p in path.parents):
        raise ValueError('private artifacts must stay outside Git repositories and worktrees')
    if existing:
        if not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ValueError('private input must be a regular 0600 file')
        if path.stat().st_size > MAX_BYTES: raise ValueError('private artifact exceeds size bound')
    elif path.exists():
        raise ValueError('private artifact already exists; choose a new path')
    if path.parent.exists() and stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise ValueError('private artifact parent must have 0700 permissions')
    return path


def _write_private(path, data):
    _safe(data)
    encoded = _encoded(data)
    if len(encoded) > MAX_BYTES: raise ValueError('private artifact exceeds size bound')
    path = _private_path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Recheck after directory creation and create mode0600 before writing bytes.
    path = _private_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise ValueError('private artifact cannot be created safely') from None
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd, 'wb') as file:
            file.write(encoded + b'\n')
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _selector(domain, project, scope, limit):
    if not isinstance(domain, str) or not domain.strip() or len(domain)>1000:
        raise ValueError('exact nonempty domain is required')
    if type(limit) is not int or not 1 <= limit <= MAX_CASES:
        raise ValueError('case limit must be an integer between 1 and 32')
    if scope == 'global' and project is None:
        selected = 'global'
    elif scope in (None, 'project') and project is not None:
        selected = project_id(project)
    else:
        raise ValueError('one exact project or explicit global scope is required')
    _safe({'domain':domain,'project_scope':selected})
    return selected


@contextmanager
def _reader_snapshot(cfg):
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        conn.execute("SET LOCAL statement_timeout='5s'")
        schema = [r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
        expected = [p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name <= '018_entity_identities.sql']
        if schema not in (expected, expected + ['019_embedding_reuse.sql'],
                           expected + ['019_embedding_reuse.sql', '020_domain_assertions.sql']):
            raise ValueError('correction export supports populated schema018/019/020 only')
        at = conn.execute('SELECT transaction_timestamp() AS at').fetchone()['at'].isoformat()
        yield conn, at, schema
        conn.rollback()


def _revision():
    try:
        return subprocess.check_output(['git', '--no-optional-locks', '-C', str(ROOT), 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL, timeout=3, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError('export code revision is unavailable') from None


def _stamp(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _family(scope, domain, entity, attribute):
    return _hash([scope, domain, entity, attribute])


def _split(family):
    return 'dev' if int(family[:2], 16) < 128 else 'test'


def _case_hash(case):
    return _hash({k:v for k,v in case.items() if k not in ('original_sha256','split','split_family')})


def _split_groups(cases):
    """Keep connected original sources/copied spans and correction histories whole."""
    remaining=list(cases); groups={}
    while remaining:
        component=[remaining.pop(0)];tokens=set(component[0]['source_families'])
        changed=True
        while changed:
            changed=False
            for case in list(remaining):
                if tokens.intersection(case['source_families']):
                    component.append(case);tokens.update(case['source_families']);remaining.remove(case);changed=True
        anchor=_hash(sorted(tokens))
        for case in component:groups[case['family']]=anchor
    return groups


def _original_support(conn, row):
    evidence = row['evidence']
    if not isinstance(evidence, dict) or evidence.get('role') != 'user': return None
    namespace = evidence.get('namespace', 'operator')
    source_id, quote = evidence.get('source_id'), evidence.get('quote')
    if not all(isinstance(x, str) and x.strip() for x in (namespace, source_id, quote)): return None
    if row['value'] not in quote: return None
    try: _safe({'namespace':namespace, 'source_id':source_id, 'quote':quote})
    except ValueError: return None
    key = sha256(json.dumps([namespace, source_id], ensure_ascii=False).encode()).hexdigest()
    span = sha256(quote.encode()).hexdigest()
    retained = sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    support = conn.execute("""SELECT s.namespace,s.source_id,s.role,s.source_at,s.state,s.changed_at,
        e.quote,e.complete,e.reviewed,e.xmin::text AS evidence_version,s.xmin::text AS source_version,
        r.recorded_at,r.xmin::text AS retained_version
        FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
        JOIN assertion_sources r ON r.document_id=e.document_id
        WHERE e.document_id=%s AND e.source_key=%s AND e.span_hash=%s AND e.quote=%s
          AND e.complete AND e.reviewed AND s.role='user' AND s.state='active'
          AND r.source_hash=%s AND r.evidence=%s::jsonb""",
        (row['document_id'],key,span,quote,retained,json.dumps(evidence))).fetchone()
    if support is None: return None
    source = {k:_stamp(v) for k,v in dict(support).items()}
    source.update(source_key=key,span_hash=span,retained_hash=retained)
    source['original_sha256'] = _hash(source)
    return source


def _collect(conn, scope, domain, at, limit, *, only=None):
    roots = conn.execute("""SELECT a.entity,a.attribute FROM fact_assertions a
        JOIN documents d ON d.id=a.document_id
        WHERE d.project_scope=%s AND d.domain=%s AND a.disposition='accepted'
          AND a.relation='replacement' AND a.event_at<=%s
          AND (%s::text IS NULL OR a.entity=%s) AND (%s::text IS NULL OR a.attribute=%s)
        GROUP BY a.entity,a.attribute ORDER BY a.entity,a.attribute LIMIT %s""",
        (scope,domain,at,only[0] if only else None,only[0] if only else None,
         only[1] if only else None,only[1] if only else None,limit+1)).fetchall()
    cases=[]; withheld=0
    for root in roots[:limit]:
        rows = conn.execute("""SELECT a.*,d.title,d.body,d.domain,d.project_scope,d.status,
            d.xmin::text AS document_version,a.xmin::text AS assertion_version,
            cr.kind,cr.review_state,cr.content_hash,cr.xmin::text AS claim_version
            FROM fact_assertions a JOIN documents d ON d.id=a.document_id
            LEFT JOIN claim_records cr ON cr.document_id=d.id
            WHERE d.project_scope=%s AND d.domain=%s AND a.entity=%s AND a.attribute=%s
              AND a.disposition='accepted' AND a.event_at<=%s
            ORDER BY a.event_at,a.document_id LIMIT %s""",
            (scope,domain,root['entity'],root['attribute'],at,MAX_HISTORY+1)).fetchall()
        # Never cut a family before determining its newest replacement/conflicts.
        if not rows or len(rows)>MAX_HISTORY:
            withheld+=1; continue
        newest = max(r['event_at'] for r in rows if r['relation']=='replacement')
        current = [r for r in rows if r['event_at']>=newest]
        replacements = [r for r in current if r['relation']=='replacement']
        if len(replacements)!=1 or len({r['value'] for r in current})!=1:
            withheld+=1; continue
        row = replacements[0]
        if (row['status']!='active' or row['kind']!='stated' or row['review_state']!='confirmed'
            or row['body']!=row['value'] or row['content_hash']!=md5(row['value'].encode()).hexdigest()
            or (row['expires_at'] is not None and row['expires_at']<=parse_time(at))):
            withheld+=1; continue
        source = _original_support(conn,row)
        if source is None:
            withheld+=1; continue
        identity=entities.read(conn,row['entity'],domain=domain,project=None if scope=='global' else scope,
            scope='global' if scope=='global' else None,attribute=row['attribute'],as_of=at,context_chars=1000)
        if identity.get('status')!='resolved' or not any(f.get('document_id')==str(row['document_id']) and f.get('value')==row['value'] for f in identity.get('facts',[])):
            withheld+=1;continue
        # Confirmed alias names and every attribute under their shared root stay
        # together even when the original user spans are otherwise independent.
        identity_family=_hash([scope,domain,identity['identity_id']])
        family = _family(scope,domain,row['entity'],row['attribute'])
        if any(not isinstance(r['evidence'],dict) or any(not isinstance(r['evidence'].get(k),str) or not r['evidence'][k].strip()
                                                       for k in ('source_id','quote')) for r in rows):
            withheld+=1;continue
        history = [dict(document_id=str(r['document_id']),entity=r['entity'],attribute=r['attribute'],
            value=r['value'],relation=r['relation'],event_at=_stamp(r['event_at']),
            expires_at=_stamp(r['expires_at']),document_version=r['document_version'],
            assertion_version=r['assertion_version'],original_sha256=_hash([r['title'],r['body'],r['evidence']]),
            source_key=sha256(json.dumps([r['evidence'].get('namespace','operator'),r['evidence']['source_id']],ensure_ascii=False).encode()).hexdigest(),
            span_hash=sha256(r['evidence']['quote'].encode()).hexdigest()) for r in rows]
        case = dict(id=str(row['document_id']),document_id=str(row['document_id']),family=family,split=_split(family),
            question=row['entity']+' / '+row['attribute'],entity=row['entity'],attribute=row['attribute'],value=row['value'],
            domain=domain,project_scope=scope,event_at=_stamp(row['event_at']),expires_at=_stamp(row['expires_at']),
            document_version=row['document_version'],assertion_version=row['assertion_version'],claim_version=row['claim_version'],
            sources=[source],history=history,identity_family=identity_family,
            source_families=sorted({'identity:'+identity_family} | {token for h in history for token in ('source:'+h['source_key'],'span:'+h['span_hash'])}))
        try: _safe(case)
        except ValueError:
            withheld+=1; continue
        cases.append(case)
    groups=_split_groups(cases)
    for case in cases:
        case['split_family']=groups[case['family']]
        case['split']=_split(case['split_family'])
        case['original_sha256']=_case_hash(case)
    return cases, dict(families_seen=len(roots[:limit]),withheld_families=withheld,limited=len(roots)>limit)


def export_confirmed_corrections(cfg, *, domain, project=None, scope=None, limit=32, output_path):
    selected = _selector(domain,project,scope,limit)
    _private_path(output_path)
    with _reader_snapshot(cfg) as (conn, at, schema):
        cases, counts = _collect(conn,selected,domain,at,limit)
        payload = dict(kind='private-confirmed-corrections',synthetic=False,version=1,
            domain=domain,project_scope=selected,as_of=at,source_revision=_revision(),source_schema=schema,
            source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),cases=cases,counts=counts)
    payload['artifact_sha256'] = _hash(payload)
    _write_private(output_path,payload)
    return dict(cases=len(cases),**counts,provider_calls=0,application_writes=0)


def _validate_export(data):
    if not isinstance(data,dict) or data.get('kind')!='private-confirmed-corrections' or data.get('synthetic') is not False or type(data.get('version')) is not int or data['version']!=1:
        raise ValueError('distinct private correction format is required')
    _safe(data)
    if set(data)!= {'kind','synthetic','version','domain','project_scope','as_of','source_revision','source_schema',
                   'source_sha256','cases','counts','artifact_sha256'}:
        raise ValueError('unknown or missing private export fields')
    digest=data.get('artifact_sha256')
    if not isinstance(digest,str) or not HEX.fullmatch(digest) or digest!=_hash({k:v for k,v in data.items() if k!='artifact_sha256'}):
        raise ValueError('private export hash mismatch')
    if not isinstance(data.get('domain'),str) or not data['domain'].strip() or not isinstance(data.get('project_scope'),str) or (data['project_scope']!='global' and not data['project_scope'].startswith('/')):
        raise ValueError('exact export selectors are required')
    if parse_time(data.get('as_of')) is None:
        raise ValueError('explicit export snapshot time is required')
    expected=[p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name<='018_entity_identities.sql']
    if (not isinstance(data.get('source_revision'),str) or not re.fullmatch('[0-9a-f]{40}',data['source_revision'])
        or not isinstance(data.get('source_sha256'),str) or not HEX.fullmatch(data['source_sha256'])
        or data.get('source_schema') not in (expected,expected+['019_embedding_reuse.sql'],
                                            expected+['019_embedding_reuse.sql','020_domain_assertions.sql'])):
        raise ValueError('invalid original code/schema revision')
    cases=data.get('cases')
    if not isinstance(cases,list) or len(cases)>MAX_CASES: raise ValueError('invalid bounded cases')
    seen=set();families=set()
    counts=data.get('counts')
    if (not isinstance(counts,dict) or set(counts)!={'families_seen','withheld_families','limited'}
        or type(counts['families_seen']) is not int or not 0<=counts['families_seen']<=MAX_CASES
        or type(counts['withheld_families']) is not int or counts['withheld_families']!=counts['families_seen']-len(cases)
        or type(counts['limited']) is not bool):
        raise ValueError('invalid correction denominators')
    for case in cases:
        if not isinstance(case,dict) or any(not isinstance(case.get(k),str) or not case[k].strip() for k in ('id','document_id','entity','attribute','question','value','domain','project_scope','family')):
            raise ValueError('invalid correction labels')
        if set(case)!={'id','document_id','family','split','question','entity','attribute','value','domain','project_scope',
                       'event_at','expires_at','document_version','assertion_version','claim_version','sources','history','original_sha256',
                       'source_families','split_family','identity_family'}:
            raise ValueError('unknown or missing correction fields')
        try: UUID(case['document_id'])
        except (ValueError,AttributeError): raise ValueError('invalid original document identity') from None
        if case['id']!=case['document_id'] or case['question']!=case['entity']+' / '+case['attribute']:
            raise ValueError('correction identity/question drift')
        if any(len(case[k])>2000 for k in ('entity','attribute','value')):
            raise ValueError('unbounded correction label')
        if any(not isinstance(case.get(k),str) or not re.fullmatch('[0-9]{1,20}',case[k])
               for k in ('document_version','assertion_version','claim_version')):
            raise ValueError('original row revisions are required')
        family=_family(data['project_scope'],data['domain'],case['entity'],case['attribute'])
        if case['family']!=family or case['id'] in seen or family in families:
            raise ValueError('duplicate correction or family split leakage')
        if case['domain']!=data['domain'] or case['project_scope']!=data['project_scope']:
            raise ValueError('correction selector drift')
        if case.get('original_sha256')!=_case_hash(case):
            raise ValueError('correction original hash mismatch')
        if not isinstance(case.get('sources'),list) or len(case['sources'])!=1 or not isinstance(case.get('history'),list) or not 1<=len(case['history'])<=MAX_HISTORY:
            raise ValueError('correction original support is required')
        source=case['sources'][0]
        if (not isinstance(source,dict) or source.get('role')!='user' or source.get('state')!='active'
            or source.get('complete') is not True or source.get('reviewed') is not True
            or not isinstance(source.get('quote'),str) or case['value'] not in source['quote']
            or source.get('span_hash')!=sha256(source['quote'].encode()).hexdigest()
            or source.get('original_sha256')!=_hash({k:v for k,v in source.items() if k!='original_sha256'})):
            raise ValueError('unconfirmed original source')
        if set(source)!={'namespace','source_id','role','source_at','state','changed_at','quote','complete','reviewed',
                        'evidence_version','source_version','recorded_at','retained_version','source_key','span_hash','retained_hash','original_sha256'}:
            raise ValueError('invalid retained source fields')
        if (any(not isinstance(source.get(k),str) or not source[k].strip() or len(source[k])>1000 for k in ('namespace','source_id'))
            or len(source['quote'])>4000 or source['source_key']!=sha256(json.dumps([source['namespace'],source['source_id']],ensure_ascii=False).encode()).hexdigest()
            or not isinstance(source.get('retained_hash'),str) or not HEX.fullmatch(source['retained_hash'])
            or parse_time(source['changed_at']) is None or parse_time(source['recorded_at']) is None
            or any(not isinstance(source.get(k),str) or not re.fullmatch('[0-9]{1,20}',source[k]) for k in ('source_version','evidence_version','retained_version'))):
            raise ValueError('invalid original source identity/revision')
        parse_time(source['source_at'])
        history_ids=set()
        for history in case['history']:
            if not isinstance(history,dict) or set(history)!={'document_id','entity','attribute','value','relation','event_at','expires_at',
                                                             'document_version','assertion_version','original_sha256','source_key','span_hash'}:
                raise ValueError('invalid correction history')
            if (history['entity']!=case['entity'] or history['attribute']!=case['attribute']
                or history['relation'] not in ('assertion','extension','replacement')
                or not isinstance(history['value'],str) or not history['value'].strip() or len(history['value'])>2000
                or not isinstance(history['original_sha256'],str) or not HEX.fullmatch(history['original_sha256'])
                or parse_time(history['event_at']) is None or parse_time(history['event_at'])>parse_time(data['as_of'])
                or history['document_id'] in history_ids):
                raise ValueError('invalid original correction family')
            try: UUID(history['document_id'])
            except (ValueError,AttributeError,TypeError): raise ValueError('invalid original history identity') from None
            if any(not isinstance(history[k],str) or not re.fullmatch('[0-9]{1,20}',history[k]) for k in ('document_version','assertion_version')):
                raise ValueError('invalid history revisions')
            if history['expires_at'] is not None and parse_time(history['expires_at'])<=parse_time(history['event_at']):
                raise ValueError('invalid history expiry')
            history_ids.add(history['document_id'])
            if any(not isinstance(history[k],str) or not HEX.fullmatch(history[k]) for k in ('source_key','span_hash')):
                raise ValueError('invalid retained history source family')
        if case['document_id'] not in history_ids:
            raise ValueError('correction is missing its original family member')
        if not isinstance(case['identity_family'],str) or not HEX.fullmatch(case['identity_family']):
            raise ValueError('original alias identity family is required')
        expected_tokens=sorted({'identity:'+case['identity_family']} | {token for h in case['history'] for token in ('source:'+h['source_key'],'span:'+h['span_hash'])})
        if case['source_families']!=expected_tokens or not any(h['document_id']==case['document_id'] and h['source_key']==source['source_key']
            and h['span_hash']==source['span_hash'] and h['value']==case['value'] and h['relation']=='replacement' for h in case['history']):
            raise ValueError('correction history/source family mismatch')
        if parse_time(case.get('event_at')) is None or parse_time(case['event_at'])>parse_time(data['as_of']):
            raise ValueError('invalid correction event time')
        if case.get('expires_at') is not None and parse_time(case['expires_at'])<=parse_time(data['as_of']):
            raise ValueError('expired correction label')
        seen.add(case['id']);families.add(family)
    groups=_split_groups(cases)
    if any(case['split_family']!=groups[case['family']] or case['split']!=_split(groups[case['family']]) for case in cases):
        raise ValueError('copied source or correction family split leakage')
    return data


def _fts_facts(conn, case, at):
    # NULL vector, one literal scope and raw snippets: no embedding, contextual
    # representation, reranker, graph expansion or provider can enter this route.
    rows=conn.execute("""SELECT h.*,a.value,a.entity,a.attribute
        FROM hybrid_search_temporal(%s,NULL,%s,8,%s,%s,false) h
        LEFT JOIN fact_assertions a ON a.document_id=h.document_id""",
        (case['question'],case['domain'],[case['project_scope']],at)).fetchall()
    facts=[]
    for row in rows:
        text=row['snippet'];document_id=str(row['document_id']);chunk_id=str(row['chunk_id'])
        facts.append(dict(document_id=document_id,chunk_id=chunk_id,value=row['value'],text=text,start=0,end=len(text),
            citation=f'{document_id}#{chunk_id}:0-{len(text)}'))
    return dict(status='resolved',facts=facts,domain=case['domain'],project_scope=case['project_scope'])


def _score_case(conn, cfg, case, at, profile):
    try:
        if profile=='entity':
            packet=entities.read(conn,case['entity'],domain=case['domain'],
                project=None if case['project_scope']=='global' else case['project_scope'],
                scope='global' if case['project_scope']=='global' else None,
                attribute=case['attribute'],context_chars=12000,as_of=at)
        elif profile=='fts':
            packet=_fts_facts(conn,case,at)
        else:
            raise ValueError('unknown private local profile')
        facts=packet.get('facts',[]) if packet.get('status')=='resolved' else []
        wrong_scope=int(packet.get('domain')!=case['domain'] or packet.get('project_scope')!=case['project_scope'])
        current,_=_collect(conn,case['project_scope'],case['domain'],at,1,only=(case['entity'],case['attribute']))
        trusted=any(c['document_id']==case['document_id'] and c['original_sha256']==case['original_sha256'] for c in current)
        stale=sum(not trusted or (f.get('value') is not None and f['value']!=case['value'])
            or f.get('superseded',False) or f.get('expired',False) for f in facts)
        supported=False;used=0
        for fact in facts:
            original=conn.execute('SELECT c.content,d.domain,d.project_scope FROM chunks c JOIN documents d ON d.id=c.document_id '
                'WHERE c.id=%s AND c.document_id=%s',(fact.get('chunk_id'),fact.get('document_id'))).fetchone()
            if original is None:continue
            if original['domain']!=case['domain'] or original['project_scope']!=case['project_scope']:
                wrong_scope+=1;continue
            start,end=fact.get('start'),fact.get('end')
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(original['content']):continue
            text=original['content'][start:end]
            if used+len(text)>12000:continue
            used+=len(text)
            if fact.get('document_id')!=case['document_id'] or fact.get('value')!=case['value']:continue
            citation=f"{case['document_id']}#{fact['chunk_id']}:{start}-{end}"
            supported |= bool(trusted and not wrong_scope and case['value'] in text and text==fact.get('text') and citation==fact.get('citation'))
        supported=bool(supported and not wrong_scope)
        error='EntityReadUnavailable' if packet.get('status')=='unavailable' else None
    except Exception as exc:
        # Never expose exception arguments carrying SQL or original content.
        supported=False;wrong_scope=0;stale=0;used=0;error=type(exc).__name__
    return dict(id=case['id'],family=case['family'],split_family=case['split_family'],split=case['split'],
        supported=bool(supported),miss=not supported,stale=stale,wrong_scope=wrong_scope,error=error,context_chars=used)


def _summary(details):
    return dict(cases=len(details),supported=sum(r['supported'] for r in details),misses=sum(r['miss'] for r in details),
        stale=sum(r['stale'] for r in details),wrong_scope=sum(r['wrong_scope'] for r in details),
        failed_cases=sum(r['error'] is not None for r in details),provider_calls=0,application_writes=0,
        accuracy=sum(r['supported'] for r in details)/len(details) if details else None,uncertainty=None)


def _verify_private_candidate(path, expected):
    """Verify the original seal, including exact bytes and private file modes."""
    try:
        path=_private_path(path,existing=True)
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as file:
            before=os.fstat(file.fileno())
            if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode)!=0o600 or before.st_size>MAX_BYTES:
                raise ValueError
            raw=file.read(MAX_BYTES+1)
            after=os.fstat(file.fileno())
        current=_private_path(path,existing=True).stat()
        fingerprint=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if fingerprint(before)!=fingerprint(after) or fingerprint(after)!=fingerprint(current):
            raise ValueError
        if raw!=_encoded(expected)+b'\n':raise ValueError
        actual=json.loads(raw)
        if actual!=expected or actual['artifact_sha256']!=_hash({k:v for k,v in actual.items() if k!='artifact_sha256'}):
            raise ValueError
        return actual
    except (OSError,ValueError,TypeError,KeyError):
        raise ValueError('private candidate integrity verification failed') from None


def evaluate_export(cfg, *, export_path, output_path):
    source_path = _private_path(export_path,existing=True)
    _private_path(output_path)
    try:
        payload = _validate_export(json.loads(source_path.read_bytes()))
    except (json.JSONDecodeError, UnicodeError, TypeError, KeyError):
        raise ValueError('invalid private correction artifact') from None
    candidate_path=Path(output_path).with_name(Path(output_path).name+'.candidate.json')
    if {c['split'] for c in payload['cases']}=={'dev','test'}:
        _private_path(candidate_path)
    from . import runner
    frozen_revision, frozen_source = _revision(), runner.source_hash()
    def source_guard():
        if _revision()!=frozen_revision or runner.source_hash()!=frozen_source:
            raise ValueError('private evaluation source changed')
    source_guard()
    candidate=None
    details=[];optimization=dict(status='unavailable',reason='independent dev and test source/alias families are required',
        profiles=2,chosen=None,dev=None,heldout=None,candidate_sha256=None)
    with _reader_snapshot(cfg) as (conn,at,schema):
        dev=[c for c in payload['cases'] if c['split']=='dev'];test=[c for c in payload['cases'] if c['split']=='test']
        if dev and test:
            dev_rows={profile:[_score_case(conn,cfg,case,at,profile) for case in dev] for profile in ('fts','entity')}
            summaries={profile:_summary(rows) for profile,rows in dev_rows.items()}
            # Fixed tie order; labels from held-out cases never enter this choice.
            chosen=min(('fts','entity'),key=lambda p:(summaries[p]['wrong_scope'],summaries[p]['stale'],
                summaries[p]['failed_cases'],-summaries[p]['supported']))
            candidate=dict(kind='private-correction-candidate',version=1,synthetic=False,profile=chosen,
                context_chars=12000,profiles=['fts','entity'],dev=summaries,
                dev_evidence_sha256=_hash([c['original_sha256'] for c in dev]),
                source_revision=frozen_revision,source_sha256=frozen_source)
            candidate['artifact_sha256']=_hash(candidate)
            _write_private(candidate_path,candidate)  # Seal before any held-out scoring.
            chosen=_verify_private_candidate(candidate_path,candidate)['profile']
            heldout=[_score_case(conn,cfg,case,at,chosen) for case in test]
            details=dev_rows['entity']+([_score_case(conn,cfg,case,at,'entity') for case in test] if chosen!='entity' else heldout)
            optimization=dict(status='sealed',reason=None,profiles=2,chosen=chosen,dev=summaries,heldout=_summary(heldout),
                candidate_sha256=candidate['artifact_sha256'],heldout_evaluations=1,
                dev_families=len({c['split_family'] for c in dev}),test_families=len({c['split_family'] for c in test}))
        else:
            details=[_score_case(conn,cfg,case,at,'entity') for case in payload['cases']]
    summary = _summary(details)
    summary['optimization']=optimization
    report = dict(kind='private-correction-evaluation',version=1,synthetic=False,export_sha256=payload['artifact_sha256'],
        source_revision=frozen_revision,source_sha256=frozen_source,source_schema=schema,
        as_of=at,summary=summary,cases=details)
    report['artifact_sha256'] = _hash(report)
    if candidate is not None:_verify_private_candidate(candidate_path,candidate)
    source_guard()
    _write_private(output_path,report)
    return summary
