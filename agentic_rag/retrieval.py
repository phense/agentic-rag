"""Deterministic result diversity and exact contiguous evidence spans."""
from __future__ import annotations
import re
from dataclasses import replace


def terms(query):
    return {t.casefold() for t in re.findall(r'[\w]+(?:(?:::|[_.:-])[\w]+)*',query) if len(t)>1 and t.casefold() not in {'and','or','the','der','die','das','und','oder'}}


def strong_symbols(query):
    return [t for t in re.findall(r'[\w]+(?:(?:::|[_.:-])[\w]+)*',query)
            if re.search(r'(?:Error|Exception)\d*$|^ERR_|::',t)]


def exact_symbol_match(content,symbols):
    return not symbols or any(re.search(r'(?<!\w)'+re.escape(s)+r'(?!\w)',content) for s in symbols)


def evidence_span(content,query,budget=400):
    tokens=terms(query)
    matches=[m for token in sorted(tokens) for m in re.finditer(re.escape(token),content,re.IGNORECASE)]
    symbols=strong_symbols(query)
    starts={0}|{max(0,min(m.start()-80,len(content)-budget)) for m in matches}
    def rank(start):
        end=start+budget
        covered={m.group().casefold() for m in matches if start<=m.start() and m.end()<=end}
        symbol_count=sum(exact_symbol_match(content[start:end],[symbol]) for symbol in symbols)
        return (-symbol_count,-len(covered),start)
    start=min(starts,key=rank)
    end=min(len(content),start+budget)
    return content[start:end],start,end


def present(hit,query):
    snippet,start,end=evidence_span(hit.snippet,query)
    return replace(hit,snippet=snippet,snippet_start=start,snippet_end=end,
                   citation=f'{hit.document_id}#{hit.chunk_id}:{start}-{end}')


def diverse(hits,query,k):
    chosen=[];extra=[];covered={};tokens=terms(query)
    for hit in hits:
        matches={t for t in tokens if t in hit.snippet.casefold()}
        if hit.document_id not in covered:
            covered[hit.document_id]=set(matches);chosen.append(hit)
        else:extra.append((hit,matches))
    if len(chosen)<k:
        for hit,matches in extra:
            if matches-covered[hit.document_id]:
                chosen.append(hit);covered[hit.document_id].update(matches)
                if len(chosen)>=k:break
    return chosen[:k]


def rerank(hits,ranker,warnings):
    if ranker is None:return hits
    try:
        ranked=list(ranker(list(hits)))
        original={(h.document_id,h.chunk_id):h for h in hits}
        keys=[(h.document_id,h.chunk_id) for h in ranked]
        if len(keys)!=len(original) or len(set(keys))!=len(keys) or set(keys)!=set(original):
            raise ValueError('reranker changed candidate identities')
        # Only ordering is trusted; original evidence/scope/content cannot be changed.
        return [original[key] for key in keys]
    except Exception:
        warnings.append('local reranker unavailable or invalid — deterministic hybrid fallback')
        return hits
