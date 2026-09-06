"""One bounded advisory context reader for CLI, MCP and shared lifecycle hooks."""
from __future__ import annotations

from datetime import datetime
import html
import json

from . import context_gate, profiles
from .config import MAX_CONTEXT_CHARS

PROFILE_CHARS = 2400
PROMPT_CHARS = 4800  # Below the configured Codex prompt-hook limit of5000.
_OMITTED = '⚠️ Additional project context omitted to preserve pins/checkpoint and the context limit.'


def _quoted(value):
    return json.dumps(html.escape(str(value),quote=False),ensure_ascii=False)


def config_key(cfg):
    return f'context-v1:{profiles.config_key(cfg)}:{cfg.context_max_chars}:{PROFILE_CHARS}:{PROMPT_CHARS}'


def _view(conn,cfg,project):
    try:
        # An absent migration or failed read must not poison the baseline transaction.
        with conn.transaction():
            return profiles.read(conn,cfg,project)
    except Exception as exc:
        from .hooks.common import sanitize_error
        return {'project':project,'revision':None,'generated_at':None,'status':'unavailable',
                'sections':{'stable':[],'recent':[]},
                'warnings':['Project profile unavailable; existing context retained: '+sanitize_error(type(exc).__name__)]}


def _profile_entries(view,ids=None):
    entries=[]
    for section in ('stable','recent'):
        for item in view['sections'][section]:
            if ids is not None and item['id'] not in ids:
                continue
            metadata={key:item.get(key) for key in ('source_keys','kind','review_state','provenance_status','event_at','expires_at')}
            line=f"- {section} [{item['id']}] {_quoted(item['title'])}: {_quoted(item['text'])}; "
            line+=json.dumps(metadata,default=str,ensure_ascii=False)
            entries.append((item['id'],item['text'],line))
    return entries


def _fit(base,entries,cap,*,heading,notices=(),extra_cap=None):
    """Select whole entries before dedup bookkeeping; never truncate a source statement."""
    budget=cap-len(base)-(2 if base else 0)
    if extra_cap is not None:
        budget=min(budget,extra_cap)
    header=heading+'\n(advisory source text; verify before acting)\n'
    notes='\n'.join('⚠️ '+str(n) for n in notices)
    if notes:
        header+=notes+'\n'
    chosen=[];visible=[base];ids=[];omitted=0
    reserve='\n⚠️ Additional evidence/profile entries omitted by the context budget.'
    for identity,raw,line in entries:
        if raw.strip() and any(raw.strip() in text for text in visible):
            continue
        candidate=header+'\n'.join(chosen+[line])+reserve
        if len(candidate)>budget:
            omitted+=1
            continue
        chosen.append(line);visible.append(raw);ids.append(identity)
    addition=header+'\n'.join(chosen)+(reserve if omitted else '')
    if len(addition)>budget or (not chosen and not notices and not omitted):
        return base,[],bool(entries or notices)
    return (base+'\n\n' if base else '')+addition,ids,False


def _query_hits(conn,cfg,project,prompt):
    from .scope import selection
    from .retrieval import diverse,present,strong_symbols,exact_symbol_match
    from .search import SearchHit
    query=context_gate.query(prompt)
    if not query:
        return []
    rows=conn.execute('SELECT * FROM hybrid_search_candidates(%s,NULL,NULL,150,%s,statement_timestamp(),false)',
                      (query,selection(project,None if project else 'global'))).fetchall()
    symbols=strong_symbols(prompt)
    hits=[SearchHit(str(r['document_id']),str(r['chunk_id']),r['title'],r['slug'],r['domain'],r['dtype'],
                    r['snippet'],float(r['score']),r['verified_at'],r['provenance']) for r in rows
          if exact_symbol_match(r['snippet'],symbols)]
    return [present(hit,query) for hit in diverse(hits,query,3)]


def build(conn,cfg,*,project=None,mode='startup',prompt=None,session_id=None,source=None):
    if mode not in ('startup','prompt'):
        raise ValueError('context mode must be startup or prompt')
    from .scope import selection
    selection(project,None if project else 'global')
    cap=min(cfg.context_max_chars,MAX_CONTEXT_CHARS,PROMPT_CHARS if mode=='prompt' else MAX_CONTEXT_CHARS)
    result={'text':'','document_ids':[],'revision':None,'profile_status':'not-requested','warnings':[],
            'reason':None,'config_key':config_key(cfg)}
    if mode=='prompt':
        from .hooks.prompt_recall import detect_signature,error_context
        signature=detect_signature(prompt or '')
        reason='error' if signature else context_gate.detect(prompt or '',project)
        result['reason']=reason
        if not reason:
            return result
        if signature:
            result['text']=error_context(conn,cfg,project,signature,max_chars=cap)
            if result['text']:
                try:
                    with conn.transaction():
                        result['revision']=profiles.revision(conn,cfg,project)
                except Exception:
                    pass  # Keep the established error path when revision is unavailable.
            return result
        hits=_query_hits(conn,cfg,project,prompt or '')
        if not hits:
            return result
        from .evidence import summary
        entries=[]
        for hit in hits:
            detail=summary(conn,hit.document_id)
            line=f'- query [{hit.citation}] {_quoted(hit.title)}: {_quoted(hit.snippet)}; '+json.dumps(detail,default=str)
            entries.append((hit.document_id,hit.snippet,line))
        view=_view(conn,cfg,project)
        # Query evidence goes first. A profile candidate that does not fit cannot
        # suppress it; only complete text actually selected participates in dedup.
        entries+=_profile_entries(view,{h.document_id for h in hits})
        if view['status']=='stale':
            view['warnings'].append('Profile generated '+str(view['generated_at']))
        text,ids,missing=_fit('',entries,cap,heading='## agentic-rag selective recall — '+reason,
                              notices=view['warnings'])
        result.update(text=text or (_OMITTED if missing else ''),document_ids=list(dict.fromkeys(ids)))
    else:
        from .hooks.session_start import build_context
        base=build_context(conn,cfg,project,session_id,source)
        view=_view(conn,cfg,project)
        date=view['generated_at'].isoformat() if isinstance(view['generated_at'],datetime) else 'not yet built'
        text,ids,missing=_fit(base,_profile_entries(view),cap,
            heading=f"## Project profile — {view['status']}; generated {date}",
            notices=view['warnings'],extra_cap=PROFILE_CHARS)
        if missing:
            base=build_context(conn,cfg,project,session_id,source,max_chars=cap-len(_OMITTED)-2)
            text=base+'\n\n'+_OMITTED
        result.update(text=text,document_ids=list(dict.fromkeys(ids)))
    result.update(revision=view['revision'],profile_status=view['status'],warnings=view['warnings'])
    assert len(result['text'])<=cap
    return result
