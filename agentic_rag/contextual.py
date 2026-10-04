"""Source excerpts for advisory indexing; original chunks remain the evidence."""
from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from pathlib import PurePath

from .secrets import strip_secrets

VERSION = 1
PREFIX_CHARS = 768
SOURCE_HASH = 'chunk_context_source_hash(d.title,d.body,d.project_scope,c.content)'


def available(conn):
    return conn.execute("SELECT to_regclass('public.chunk_contexts') IS NOT NULL AS present").fetchone()['present']


def has_vectors(conn):
    return conn.execute('SELECT EXISTS(SELECT 1 FROM chunk_contexts WHERE embedding IS NOT NULL) AS present').fetchone()['present']


def prefixes(rows, title, project):
    """Parse the original chunk stream so even split headings/fences stay grounded."""
    from bisect import bisect_right
    text = ''.join(row['content'] for row in rows)
    opening = text[:240]
    stack, lead, fence = [], '', None
    events, positions = [], []
    offset = 0
    for line in text.splitlines(keepends=True):
        value = line.rstrip('\r\n')
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', value)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]))
        else:
            heading = re.match(r'^ {0,3}(#{1,6})[ \t]+(.+)$', value)
            if heading:
                level = len(heading[1])
                stack = [(n,s) for n,s in stack if n < level] + [(level,heading[2][:160])]
                lead = ''
            elif value.strip() and not lead:
                lead = value.strip()[:240]
        positions.append(offset)
        events.append((' / '.join(s for _,s in stack)[-240:], lead))
        offset += len(line)
    output, offset = [], 0
    for row in rows:
        index = bisect_right(positions, offset)-1
        headings, section_lead = events[index] if index >= 0 else ('','')
        fields = ['Document: '+title[:160], 'Opening excerpt: '+opening]
        if project != 'unknown':
            fields.append('Project: '+('global' if project == 'global' else PurePath(project).name)[:64])
        fields += ['Section: '+headings, 'Section excerpt: '+section_lead]
        output.append(strip_secrets('\n'.join(fields))[0][:PREFIX_CHARS])
        offset += len(row['content'])
    return output


def source_rows(conn, doc_id, revision=None):
    # Index refresh must bind hashes to the same metadata used by its prefix.
    expression = SOURCE_HASH if revision is None else 'chunk_context_source_hash(%s,%s,%s,c.content)'
    params = (doc_id,) if revision is None else (revision['title'],revision['body'],revision['project_scope'],doc_id)
    return conn.execute(f"""SELECT c.id,c.idx,c.content,{expression} AS source_hash,
        x.context,x.embedding::text AS context_embedding,x.model_digest,x.source_hash AS indexed_hash
        FROM chunks c JOIN documents d ON d.id=c.document_id
        LEFT JOIN chunk_contexts x ON x.chunk_id=c.id AND x.version=1
        WHERE d.id=%s ORDER BY c.idx,c.id""",params).fetchall()


def lexical_save(conn, doc_id):
    """Called only inside save_document after its atomic raw-chunk replacement."""
    if not available(conn):
        return
    doc = conn.execute('SELECT title,project_scope FROM documents WHERE id=%s',(doc_id,)).fetchone()
    rows = source_rows(conn, doc_id)
    if rows:
        conn.execute('SELECT put_chunk_contexts(%s,%s,%s,%s,%s,%s)',
            (doc_id,[r['id'] for r in rows],prefixes(rows,doc['title'],doc['project_scope']),
             [None]*len(rows),[r['source_hash'] for r in rows],None))


@dataclass(frozen=True)
class ContextIndexResult:
    doc_id: str
    indexed_chunks: int
    remaining_chunks: int
    warnings: list[str] = field(default_factory=list)


def refresh(conn,cfg,*,doc_id,title,body,domain,dtype,limit=8,actor='cli',commit=True):
    """Index-only branch of the audited save gateway. Never replaces canonical rows."""
    from . import embed, query_cache
    if type(limit) is not int or not 1<=limit<=32:
        raise ValueError('index_limit must be between 1 and 32')
    if doc_id is None:
        raise ValueError('index-only save requires an existing document')
    if not available(conn):
        raise ValueError('context indexing requires migration015')
    doc=conn.execute('SELECT id,title,body,domain,dtype,project_scope FROM documents WHERE id=%s',(doc_id,)).fetchone()
    if doc is None:
        raise ValueError('index document not found')
    if (title,body,domain,dtype)!=(doc['title'],doc['body'],doc['domain'],doc['dtype']):
        raise ValueError('index-only save cannot modify canonical document fields')
    rows=source_rows(conn,doc_id,revision=doc)
    headers=prefixes(rows,doc['title'],doc['project_scope'])
    digest=query_cache.model_digest(cfg)
    needed=[(row,header) for row,header in zip(rows,headers)
        if row['indexed_hash']!=row['source_hash'] or row['context']!=header
        or row['context_embedding'] is None or digest is None or row['model_digest']!=digest]
    batch=needed[:limit];warnings=[]
    if not batch:
        if commit:conn.commit()
        return ContextIndexResult(str(doc_id),0,0,warnings)
    vectors=None
    if digest is not None:
        from . import embedding_reuse
        vectors=embedding_reuse.vectors(conn,cfg,[h+'\n'+r['content'][:4000] for r,h in batch],
            loader=embed.try_embed_texts,actor=actor,representation="context-v1",expected_digest=digest)
        valid=(isinstance(vectors,list) and len(vectors)==len(batch)
            and all(isinstance(v,list) and len(v)==cfg.embed_dim
                    and all(type(x) in (int,float) and math.isfinite(x) for x in v) for v in vectors))
        if not valid or query_cache.model_digest(cfg)!=digest:
            vectors=None
            warnings.append('context embedding unavailable or model changed; lexical context retained')
    else:
        warnings.append('context model identity unavailable; lexical context retained')
    # Avoid rewriting identical lexical representations when inference is unavailable.
    changed=[(i,r,h) for i,(r,h) in enumerate(batch) if vectors is not None
        or r['indexed_hash']!=r['source_hash'] or r['context']!=h]
    if changed:
        # Inference occurs before the row lock. Concurrent source edits must win.
        conn.execute('SELECT id FROM documents WHERE id=%s FOR UPDATE NOWAIT',(doc_id,)).fetchone()
        literals=[embed.vec_literal(vectors[i]) if vectors is not None else None for i,_,_ in changed]
        conn.execute('SELECT put_chunk_contexts(%s,%s,%s,%s,%s,%s)',
            (doc_id,[r['id'] for _,r,_ in changed],[h for _,_,h in changed],literals,
             [r['source_hash'] for _,r,_ in changed],digest if vectors is not None else None))
        conn.execute("INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,'index_context',%s,%s)",
            (actor,doc_id,f'version1 contextual representations: {len(changed)} chunks'))
    if commit:conn.commit()
    remaining=len(needed)-(len(batch) if vectors is not None else 0)
    return ContextIndexResult(str(doc_id),len(changed),remaining,warnings)
