"""Adaptive candidates, optional query inference reuse and original-source spans."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import re
import uuid

import psycopg

from . import temporal
from .config import Config
from .embed import try_embed_texts, vec_literal


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    chunk_id: str
    title: str
    slug: str
    domain: str
    dtype: str
    snippet: str
    score: float
    verified_at: datetime | None
    provenance: dict
    evidence: dict = field(default_factory=dict)
    snippet_start: int = 0
    snippet_end: int = 0
    citation: str = ""
    graph_depth: int = 0


def search(
    conn, cfg: Config, query: str, domain: str | None = None, k: int = 8,
    *, project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool = False, graph_depth: int = 0, reranker=None, baseline: bool = False,
    strategy: str = "auto",
    query_cache=None,
    rerank_mode: str = "auto",
    context_mode: str = "auto",
    temporal: str | None = None,
    reference: str | None = None,
    timezone: str | None = None,
    diagnostics: dict | None = None,
) -> tuple[list[SearchHit], list[str]]:
    """temporal=None keeps library callers on the legacy path; client surfaces
    pass 'auto' (configuration decides), 'off', or explicit 'prefer'/'filter'.
    diagnostics, when given, receives the additive temporal explanation."""
    validate_strategy(strategy)
    validate_rerank_mode(rerank_mode)
    if context_mode not in ("auto", "off"):
        raise ValueError("context must be auto or off")
    if type(k) is not int or not 1<=k<=100:raise ValueError("k must be between 1 and 100")
    if type(graph_depth) is not int or not 0<=graph_depth<=2:raise ValueError("graph_depth must be 0, 1 or 2")
    if baseline and (graph_depth or reranker is not None):
        raise ValueError("baseline cannot combine with optional retrieval stages")
    if baseline and strategy == "lexical":
        raise ValueError("baseline cannot combine with lexical strategy")
    from .scope import selection
    scopes = selection(project, scope)
    from .validity import selection as time_selection
    at, history = time_selection(as_of, history)
    warnings: list[str] = []
    interpretation, report = _interpret(cfg, query, temporal, reference, timezone, baseline)
    if report is not None and diagnostics is not None:
        diagnostics['temporal'] = report
    if interpretation is not None and interpretation.status == 'interval' and interpretation.residual:
        query = interpretation.residual
    elif interpretation is not None and interpretation.status in ('ambiguous', 'unsupported'):
        warnings.append('temporal expression not applied: ' + interpretation.status)
    from . import indexes
    selected_space = indexes.active(conn, cfg)
    managed_query = indexes.BoundQuery(selected_space, None) if selected_space is not None else None
    from .retrieval import strong_symbols, exact_symbol_match
    function="hybrid_search_temporal" if baseline else "hybrid_search_candidates"
    query_model = None
    def candidates(qvec):
        from . import contextual
        if selected_space is not None:
            return indexes.candidates(conn, managed_query, query, domain=domain,
                scopes=scopes, at=at, history=history, k=k if baseline else 150,
                warnings=warnings, include_context=(context_mode == 'auto' and not baseline
                    and strategy != 'hybrid' and not strong_symbols(query)))
        if context_mode == 'auto' and not baseline and strategy != 'hybrid' and not strong_symbols(query) and contextual.available(conn):
            if qvec is not None:
                from . import vector_plan
                if vector_plan.available(conn):
                    return vector_plan.candidates(conn,(query,qvec,domain,150,scopes,at,history,query_model))
            return conn.execute('SELECT * FROM hybrid_search_contextual(%s,%s::halfvec,%s,%s,%s,%s,%s,%s)',
                (query,qvec,domain,150,scopes,at,history,query_model)).fetchall()
        return conn.execute(
            f"SELECT * FROM {function}(%s, %s::halfvec, %s, %s, %s, %s, %s)",
            (query, qvec, domain, k if baseline else 150, scopes, at, history),
        ).fetchall()

    rows = None
    shortcut = False
    if strategy == "auto" and not baseline:
        rows = _identity_candidates(conn, query, domain, scopes, at, history)
        symbols = strong_symbols(query)
        if rows is None and len(symbols) == 1 and query.strip() == symbols[0]:
            lexical = candidates(None)
            # Empty or rejected lexical evidence is not a shortcut success.
            if any(exact_symbol_match(row["snippet"], symbols) for row in lexical):
                rows = lexical
    shortcut = rows is not None
    if rows is None and selected_space is not None:
        if strategy != 'lexical':
            from .providers import ProviderError
            from .service.engine import ResourcePressure
            try:
                managed_query = indexes.query_vector(selected_space, cfg, query)
            except (ProviderError, ResourcePressure) as error:
                warnings.append(f'managed embedding {error.code}; full-text search only')
        rows = candidates(None)
    if rows is None:
        qvec = None
        if strategy != "lexical":
            from . import contextual
            from .query_cache import model_digest
            contextual_vectors = (context_mode == 'auto' and not baseline
                and strategy != 'hybrid' and not strong_symbols(query)
                and contextual.available(conn) and contextual.has_vectors(conn))
            before_model = model_digest(cfg) if contextual_vectors else None
            if query_cache is None or baseline:
                vecs = try_embed_texts([query], cfg)
            else:
                vecs = query_cache.vectors(query, cfg, {
                    'database': cfg.db_name, 'host': cfg.db_host,
                    'role': conn.info.user, 'domain': domain, 'scopes': scopes,
                    'as_of': as_of, 'history': history,
                }, try_embed_texts)
            if vecs is None:
                warnings.append("embedding unavailable — full-text search only")
            else:
                qvec = vec_literal(vecs[0])
                if before_model is not None and model_digest(cfg) == before_model:
                    query_model = before_model
        rows = candidates(qvec)
    from .evidence import summary
    hits = [
        SearchHit(str(r["document_id"]), str(r["chunk_id"]), r["title"],
                  r["slug"], r["domain"], r["dtype"], r["snippet"],
                  float(r["score"]), r["verified_at"], r["provenance"])
        for r in rows
    ]
    def with_evidence(selected):
        summaries={identity:summary(conn,identity) for identity in {h.document_id for h in selected}}
        return [replace(h,evidence=summaries[h.document_id]) for h in selected]
    if baseline:return with_evidence(hits),warnings
    from .retrieval import diverse,present,rerank,strong_symbols,exact_symbol_match
    symbols=strong_symbols(query)
    hits=[h for h in hits if exact_symbol_match(h.snippet,symbols)]
    if (reranker is None and rerank_mode == "auto" and strategy == "auto"
            and not shortcut and not symbols):
        from .neural_rerank import order
        decision = {} if cfg.rerank_diagnostics else None
        reranker = (lambda candidates: order(query, candidates, cfg, diagnostics=decision)) if decision is not None else (
            lambda candidates: order(query, candidates, cfg))
    else:
        decision = None
    hits=rerank(hits,reranker,warnings)
    if decision:
        from .neural_rerank import diagnostic_text
        warnings.append(diagnostic_text(decision))
    stage = None
    if interpretation is not None and interpretation.status == 'interval':
        stage = _TemporalStage(conn, interpretation, report, at, history)
        hits = stage.apply(hits, warnings)
    hits=diverse(hits,query,k)
    if graph_depth:
        before_graph = hits
        hits=_expand(conn,hits,query,k,graph_depth,project,scope,as_of,history,domain)
        if stage is not None and stage.available:
            # Graph promotion applies its own k limit. Retain the eligible base
            # selection until after temporal ordering so out-of-period graph
            # neighbours cannot evict matching original hits at that boundary.
            expanded_chunks = {h.chunk_id for h in hits}
            candidates = hits + [h for h in before_graph if h.chunk_id not in expanded_chunks]
            hits = stage.apply(candidates, warnings, graph=True)[:k]
    final = with_evidence([present(h,query) for h in hits])
    if stage is not None and stage.available:
        final = [replace(h, evidence={**h.evidence, 'temporal': stage.explain(h.document_id)}) for h in final]
    return final, warnings


_EVENT_TIME = ('assertion event time, otherwise qualifying active source event time; never document import '
               'or update time; a known source date is not independent verification')
_CANDIDATE_LIMIT, _GRAPH_NODE_LIMIT = 150, 20
_MAX_TEMPORAL_IDS = _CANDIDATE_LIMIT + _GRAPH_NODE_LIMIT


def _interpret(cfg, query, requested, reference, zone, baseline):
    """Resolve the request mode; return (interpretation or None, envelope or None)."""
    if requested is not None:
        temporal.validate_mode(requested)
    if reference is not None:
        temporal.parse_reference(reference)
    if zone is not None:
        temporal.parse_zone(zone)
    mode = requested if requested in ('prefer', 'filter') else (
        'prefer' if requested == 'auto' and cfg.temporal_enabled else None)
    if mode is None:
        if requested == 'auto' and (reference is not None or zone is not None):
            return None, {'requested': 'auto', 'mode': 'off', 'applied': 'none', 'status': 'disabled',
                          'reasons': ['disabled_by_configuration']}
        return None, None
    if baseline:
        raise ValueError('baseline cannot combine with temporal interpretation')
    interpretation = temporal.interpret(query, reference=reference, timezone=zone or cfg.temporal_timezone)
    if mode == 'filter' and interpretation.status != 'interval':
        raise ValueError('temporal_filter_requires_interval: hard filtering needs exactly one supported date, '
                         'range or calendar period')
    if interpretation.status == 'none' and requested == 'auto':
        return None, None  # no temporal intent: the exact legacy path
    report = {'requested': requested, 'mode': mode, 'applied': 'none', **interpretation.describe(),
              'retrieval_query': 'without_time_expressions' if interpretation.residual else 'original',
              'event_time': _EVENT_TIME,
              'effect': {'candidates': 0, 'matching': 0, 'outside': 0, 'unknown': 0, 'excluded': 0,
                         'reordered': False, 'graph_checked': 0},
              'limits': {'candidate_limit': _CANDIDATE_LIMIT, 'graph_node_limit': _GRAPH_NODE_LIMIT,
                         'recall': 'candidate_limited'}}
    if interpretation.status == 'current':
        report['current'] = 'existing current-validity selection applies; no recency interval is invented'
    return interpretation, report


# Canonical event basis for already visible candidates, under the caller's role
# and RLS. Only finite aggregates leave the database, never quotes or locators.
_TEMPORAL_SQL = """/* rag-temporal-metadata */
SELECT d.id::text AS document_id,
       assertion_eligible(d.id, %(at)s, %(history)s) AS eligible,
       a.document_id IS NOT NULL AS asserted, a.event_at AS assertion_event_at,
       q.known, q.inside, q.first_inside, q.earliest, q.reviewed, q.user_event, q.manual
FROM documents d
LEFT JOIN fact_assertions a ON a.document_id = d.id
LEFT JOIN LATERAL (
    SELECT count(DISTINCT s.source_key) FILTER (WHERE s.source_at IS NOT NULL) AS known,
           count(DISTINCT s.source_key) FILTER (WHERE s.source_at >= %(start)s AND s.source_at < %(end)s) AS inside,
           min(s.source_at) FILTER (WHERE s.source_at >= %(start)s AND s.source_at < %(end)s) AS first_inside,
           min(s.source_at) AS earliest,
           bool_or(s.reviewed_basis) AS reviewed,
           bool_or(s.user_basis AND NOT s.manual) AS user_event,
           bool_or(s.user_basis AND s.manual) AS manual
    FROM (SELECT k.source_key, k.source_at,
                 (c.review_state = 'confirmed' AND e.reviewed) AS reviewed_basis,
                 (c.kind = 'stated' AND k.role = 'user' AND e.complete) AS user_basis,
                 (k.namespace IN ('operator','manual')
                  OR (left(k.namespace,5) = 'svc1:' AND position(':manual:' IN k.namespace) > 0)) AS manual
          FROM claim_records c
          JOIN claim_evidence e ON e.document_id = c.document_id
          JOIN knowledge_sources k ON k.source_key = e.source_key
          WHERE c.document_id = d.id AND a.document_id IS NULL
            AND c.review_state <> 'refuted' AND k.state = 'active'
            AND ((c.review_state = 'confirmed' AND e.reviewed)
                 OR (c.kind = 'stated' AND k.role = 'user' AND e.complete))) s
) q ON true
WHERE d.id = ANY(%(ids)s::uuid[])
"""


def _utc(value):
    from datetime import timezone as tz
    return None if value is None else value.astimezone(tz.utc).isoformat()


def _event_metadata(conn, ids, interpretation, at, history):
    """Batch event basis for at most candidate+graph budget visible document IDs."""
    if len(ids) > _MAX_TEMPORAL_IDS:
        raise ValueError('temporal metadata request must stay bounded')
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    rows = conn.execute(_TEMPORAL_SQL, {'ids': ids, 'at': at, 'history': history,
                                        'start': interpretation.start, 'end': interpretation.end}).fetchall()
    result = {}
    for r in rows:
        support = []
        if r['asserted']:
            event = r['assertion_event_at']
            basis, count = ('assertion_event', 1) if event is not None else ('unknown', 0)
            match = 'unknown' if event is None else 'inside' if interpretation.contains(event) else 'outside'
        elif r['known']:
            basis, count, event = 'source_event', r['known'], r['first_inside'] or r['earliest']
            match = 'inside' if r['inside'] else 'outside'
            support = [label for label, flag in (('operator_review', r['reviewed']), ('user_source_event', r['user_event']),
                                                 ('manual_attestation', r['manual'])) if flag]
        else:
            basis, count, event, match = 'unknown', 0, None, 'unknown'
        result[r['document_id']] = {'eligible': bool(r['eligible']), 'basis': basis, 'match': match,
                                    'event_at': _utc(event), 'qualifying_events': count, 'support': support}
    return result


class _TemporalStage:
    """Stable matching-first preference or strict subset over already eligible hits."""
    def __init__(self, conn, interpretation, report, at, history):
        self.conn, self.interpretation, self.report = conn, interpretation, report
        self.at, self.history, self.mode = at, history, report['mode']
        self.metadata, self.available = {}, True

    def _load(self, ids, warnings, graph):
        missing = [i for i in dict.fromkeys(ids) if i not in self.metadata]
        if not missing:
            return True
        try:
            # A savepoint keeps the caller's transaction usable after a failure.
            with self.conn.transaction():
                self.metadata.update(_event_metadata(self.conn, missing, self.interpretation, self.at, self.history))
        except psycopg.Error:
            if self.mode == 'filter':
                raise RuntimeError('temporal_metadata_unavailable: hard filter not applied') from None
            warnings.append('temporal metadata unavailable — original order kept')
            self.report['reasons'] = self.report['reasons'] + ['graph_metadata_unavailable' if graph else 'metadata_unavailable']
            if not graph:
                self.available = False
            return False
        if graph:
            self.report['effect']['graph_checked'] += len(missing)
        return True

    def matches(self, identity):
        item = self.metadata.get(identity)
        return item is not None and item['eligible'] and item['match'] == 'inside'

    def explain(self, identity):
        item = dict(self.metadata.get(identity) or {'basis': 'unknown', 'match': 'unknown', 'event_at': None,
                                                     'qualifying_events': 0, 'support': [], 'eligible': True})
        if not item.pop('eligible'):
            item['match'] = 'unknown'
        return item

    def apply(self, hits, warnings, *, graph=False):
        if not self.available or not self._load([h.document_id for h in hits], warnings, graph):
            return hits
        ordered = [h for h in hits if self.matches(h.document_id)]
        if self.mode == 'prefer':
            # A rejected or no-longer-visible document is not an unknown-date
            # candidate. Respect the fresh authority result in soft mode too.
            ordered += [h for h in hits if not self.matches(h.document_id)
                        and self.metadata.get(h.document_id, {}).get('eligible', False)]
        effect = self.report['effect']
        if not graph:
            documents = list(dict.fromkeys(h.document_id for h in hits))
            explained = [self.explain(i)['match'] for i in documents]
            effect.update(candidates=len(documents), matching=explained.count('inside'),
                          outside=explained.count('outside'), unknown=explained.count('unknown'))
            self.report['applied'] = 'filter' if self.mode == 'filter' else 'preference'
        effect['excluded'] += len({h.document_id for h in hits} - {h.document_id for h in ordered})
        effect['reordered'] = effect['reordered'] or [h.chunk_id for h in ordered] != [
            h.chunk_id for h in hits if h in ordered]
        return ordered


def validate_strategy(strategy):
    if strategy not in ("auto", "hybrid", "lexical"):
        raise ValueError("strategy must be auto, hybrid, or lexical")


def validate_rerank_mode(mode):
    if mode not in ("auto", "off"):
        raise ValueError("rerank must be auto or off")


def _identity_candidates(conn, query, domain, scopes, at, history):
    """Strict selectors only; ineligible/missing targets fall back to hybrid."""
    selector = query.strip()
    try:
        document_id = str(uuid.UUID(selector))
        if selector.casefold() != document_id:
            return None
    except ValueError:
        document_id = None
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", selector):
            return None
    rows = conn.execute("""
        SELECT d.id AS document_id, c.id AS chunk_id, d.title, d.slug, d.domain,
               d.dtype, left(c.content,4000) AS snippet,
               (1.0/(61+c.idx))::double precision AS score, d.verified_at, d.provenance
        FROM documents d JOIN chunks c ON c.document_id=d.id
        WHERE (d.id=%s::uuid OR (%s::uuid IS NULL AND d.slug=%s))
          AND d.status='active' AND assertion_eligible(d.id,%s,%s)
          AND (%s::text IS NULL OR d.domain=%s)
          AND (%s::text[] IS NULL OR d.project_scope=ANY(%s))
        ORDER BY c.idx,c.id LIMIT 150
        """, (document_id, document_id, selector, at, history, domain, domain, scopes, scopes)).fetchall()
    return rows or None


def _expand(conn,hits,query,k,depth,project,scope,as_of,history,domain):
    """At most three seeds, twenty discovered nodes, eight edges per frontier."""
    from .scope import selection
    from .validity import selection as time_selection
    from .retrieval import strong_symbols,exact_symbol_match
    scopes=selection(project,scope);at,history=time_selection(as_of,history)
    seeds=hits[:min(3,max(1,k//2))]
    visited={h.document_id for h in seeds};expanded=[]
    initial={h.document_id:h for h in reversed(hits)}
    frontier=[(h.document_id,0,h.score) for h in seeds]
    predicates=['references','depends_on','extends','derived_from']
    discovered=0
    while frontier and discovered<20:
        current,level,score=frontier.pop(0)
        if level>=depth:continue
        rows=conn.execute("""
            SELECT DISTINCT d.id,d.slug,d.title,d.domain,d.dtype,d.verified_at,d.provenance
            FROM edges e JOIN documents src ON src.id=e.src_id JOIN documents dst ON dst.id=e.dst_id
            JOIN documents d ON d.id=CASE WHEN e.src_id=%s::uuid THEN e.dst_id ELSE e.src_id END
            WHERE (e.src_id=%s::uuid OR e.dst_id=%s::uuid) AND e.predicate=ANY(%s)
              AND nullif(btrim(e.evidence),'') IS NOT NULL
              AND src.status='active' AND dst.status='active'
              AND assertion_eligible(src.id,%s,%s) AND assertion_eligible(dst.id,%s,%s)
              AND (%s::boolean OR (e.valid_from<=%s AND (e.valid_to IS NULL OR e.valid_to>%s)))
              AND (%s::text[] IS NULL OR (src.project_scope=ANY(%s) AND dst.project_scope=ANY(%s)))
              AND (%s::text IS NULL OR d.domain=%s)
            ORDER BY d.slug,d.id LIMIT 8
            """,(current,current,current,predicates,at,history,at,history,history,at,at,scopes,scopes,scopes,domain,domain)).fetchall()
        for r in rows:
            identity=str(r['id'])
            if identity in visited:continue
            visited.add(identity);discovered+=1
            chunk=conn.execute('SELECT id,content FROM chunks WHERE document_id=%s ORDER BY idx,id LIMIT 1',(identity,)).fetchone()
            if identity in initial:
                expanded.append(initial[identity])
            elif chunk and exact_symbol_match(chunk['content'],strong_symbols(query)):
                expanded.append(SearchHit(identity,str(chunk['id']),r['title'],r['slug'],r['domain'],r['dtype'],
                    chunk['content'][:4000],score/(level+2),r['verified_at'],r['provenance'],graph_depth=level+1))
            frontier.append((identity,level+1,score))
            if discovered>=20:break
    promoted={h.document_id for h in seeds+expanded}
    return (seeds+expanded+[h for h in hits if h.document_id not in promoted])[:k]
