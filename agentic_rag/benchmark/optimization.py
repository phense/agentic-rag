"""Bounded public failure evaluation; candidates never configure live retrieval.

Labels reach only the scorer. Retrieval sees the question and literal caller
selectors. Development and held-out documents use separate owned databases.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import time
from urllib.parse import urlsplit

from .. import db, domains, entities, search, store
from ..retrieval import terms
from ..scope import selection, write_scope
from ..secrets import strip_secrets_json
from ..validity import parse_time
from .corpus import validate as validate_original
from .database import isolated_database
from .identity import local_model, model_guard
from .runner import _revision, source_hash

DEFAULT_CORPUS = Path(__file__).with_name('corpus-failures-v1.json')
PROFILES = tuple(dict(id=f'{route}-title-{weight}', route=route, title_weight=weight)
                 for route in ('search', 'entity') for weight in (0, 1))
BASELINE = PROFILES[0]


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode()).hexdigest()


def _text(value, label, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise ValueError(f'invalid bounded {label}')


def _evidence(document):
    value = dict(namespace='public-failure-benchmark', source_id=document['id'], role='user',
                 quote=document['body'], complete=True)
    value.update(document.get('evidence', {}))
    return value


def validate(corpus):
    """Reject leakage, secret labels and unsafe selectors before any service work."""
    original_shape = deepcopy(corpus)
    if isinstance(original_shape, dict):
        for key in ('documents', 'queries'):
            items = original_shape.get(key)
            if isinstance(items, list) and any(isinstance(item, dict) and item.get('scope') == 'all' for item in items):
                raise ValueError('scope all is not permitted in exact public evaluation')
    if isinstance(original_shape, dict) and isinstance(original_shape.get('documents'), list):
        for document in original_shape['documents']:
            if isinstance(document, dict) and document.get('scope') == 'global' and document.get('project') is None:
                # Legacy version1 requires a nonempty display project even for global.
                document['project'] = 'global'
    validate_original(original_shape)
    if len(corpus['documents']) > 256 or len(corpus['queries']) > 256 or len(_json(corpus).encode()) > 2*1024*1024:
        raise ValueError('public failure corpus exceeds bounded workload')
    if strip_secrets_json(corpus)[1] or '[REDACTED' in _json(corpus).upper():
        raise ValueError('secret or redacted public fixture')
    partitions, fingerprints, source_keys = {}, {}, {}
    identity_parents, identity_declarations = {}, []
    documents = {d['id']: d for d in corpus['documents']}

    def bind(index, key, split, label):
        if key in index and index[key] != split:
            raise ValueError(f'{label} leaks across dev/held-out split')
        index[key] = split

    def declare_identity(item, name):
        # Gateways trim surrounding whitespace but preserve literal case/name.
        key = (item['domain'], write_scope(item.get('project'), item.get('scope')), name.strip())
        identity_parents.setdefault(key, key)
        identity_declarations.append((key, item['split']))
        return key

    def root(key):
        current = key
        while identity_parents[current] != current:
            current = identity_parents[current]
        while identity_parents[key] != key:
            parent = identity_parents[key]
            identity_parents[key] = current
            key = parent
        return current

    def join(left, right):
        left, right = root(left), root(right)
        if left != right:
            identity_parents[left] = right

    for item in [*corpus['documents'], *corpus['queries']]:
        for key in ('id', 'family', 'domain'):
            _text(item.get(key), key, 200)
        if not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', item['domain']):
            raise ValueError('invalid domain')
        if item.get('split') not in ('dev', 'test'):
            raise ValueError('explicit document/query split required')
        bind(partitions, item['family'], item['split'], 'source/query family')
        if item.get('scope') == 'global':
            if item.get('project') is not None:
                raise ValueError('global fixture cannot include project')
        elif not isinstance(item.get('project'), str) or not item['project'].startswith('/synthetic/'):
            raise ValueError('public fixtures require an exact synthetic project or explicit global scope')
        # Both readers and writers use the existing exact scope contract.
        selection(item.get('project'), item.get('scope'))
    for document in corpus['documents']:
        _text(document.get('actor'), 'actor', 64)
        _text(document['title'], 'title', 2000)
        _text(document['body'], 'body', 16000)
        normalized = ' '.join(document['body'].casefold().split())
        bind(fingerprints, sha256(normalized.encode()).hexdigest(), document['split'], 'copied source')
        bind(fingerprints, _digest([document['title'].casefold(), normalized]), document['split'], 'copied title/body')
        evidence = _evidence(document)
        for key in ('namespace', 'source_id', 'quote'):
            _text(evidence.get(key), 'source '+key, 4000 if key == 'quote' else 1000)
        if evidence.get('role') != 'user' or evidence.get('complete') is not True:
            raise ValueError('public truth fixtures require complete user evidence')
        bind(source_keys, (evidence['namespace'], evidence['source_id']), document['split'], 'source identity')
        bind(fingerprints, sha256(' '.join(evidence['quote'].casefold().split()).encode()).hexdigest(),
             document['split'], 'copied evidence')
        assertion = document.get('assertion')
        alias = document.get('alias')
        if assertion is not None and alias is not None:
            raise ValueError('fixture cannot be assertion and alias')
        if assertion is not None:
            if not isinstance(assertion, dict) or not set(assertion) <= {'entity','attribute','value','event_at','expires_at','relation'}:
                raise ValueError('invalid assertion fixture fields')
            for key in ('entity', 'attribute', 'value'):
                _text(assertion.get(key), 'assertion '+key)
            when = parse_time(assertion.get('event_at'))
            expiry = parse_time(assertion.get('expires_at'))
            if when is None or expiry and expiry <= when:
                raise ValueError('assertion fixture requires valid explicit event time')
            if assertion.get('relation', 'assertion') not in ('assertion', 'extension', 'replacement'):
                raise ValueError('invalid assertion relation')
            if assertion['value'] not in evidence['quote']:
                raise ValueError('assertion value missing from original user evidence')
            declare_identity(document, assertion['entity'])
        if alias is not None:
            if not isinstance(alias, dict) or set(alias) != {'alias','target','effective_at'}:
                raise ValueError('invalid alias fixture fields')
            for key in ('alias', 'target'):
                _text(alias.get(key), key)
            if alias['alias'] == alias['target'] or parse_time(alias['effective_at']) is None:
                raise ValueError('invalid alias identity/time')
            join(declare_identity(document, alias['alias']), declare_identity(document, alias['target']))
    for query in corpus['queries']:
        if parse_time(query.get('as_of')) is None or query.get('history', False):
            raise ValueError('queries require explicit as_of, without history')
        _text(query['query'], 'question', 2000)
        if (query.get('entity') is None) != (query.get('attribute') is None):
            raise ValueError('entity and attribute selectors must be supplied together')
        for key in ('entity', 'attribute'):
            if query.get(key) is not None:
                _text(query[key], key)
        if query.get('entity') is not None:
            declare_identity(query, query['entity'])
        for identity in query['expected_ids']:
            source = documents[identity]
            if source['split'] != query['split']:
                raise ValueError('expected evidence crosses split')
            if source['domain'] != query['domain'] or write_scope(source.get('project'), source.get('scope')) not in selection(query.get('project'), query.get('scope')):
                raise ValueError('expected evidence outside exact domain/scope')
        if any(not any(answer in _evidence(documents[identity])['quote'] for identity in query['expected_ids'])
               for answer in query['answers']):
            raise ValueError('authored answer absent from expected original source')
    if {q['split'] for q in corpus['queries']} != {'dev', 'test'}:
        raise ValueError('both dev and held-out queries required')
    # Entity reads deliberately use one literal boundary. Wider-visible global or
    # ancestor originals need their own exact query; never compare unequal pools.
    for query in corpus['queries']:
        exact = write_scope(query.get('project'), query.get('scope'))
        visible = selection(query.get('project'), query.get('scope'))
        for document in corpus['documents']:
            source_scope = write_scope(document.get('project'), document.get('scope'))
            if document['split'] == query['split'] and document['domain'] == query['domain'] and source_scope in visible and source_scope != exact:
                raise ValueError('public entity comparison requires exact-boundary originals; query global/ancestor separately')
    components = {}
    for key, split in identity_declarations:
        bind(components, root(key), split, 'identity/alias translation history component')


def rank(question, hits, *, title_weight):
    """A stable permutation; cannot add, rewrite or broaden original evidence."""
    if title_weight not in (0, 1):
        raise ValueError('unknown title weight')
    if not title_weight:
        return list(hits)
    wanted = terms(question)
    def key(pair):
        number, hit = pair
        title = hit['title'] if isinstance(hit, dict) else hit.title
        score_value = hit.get('score', 0) if isinstance(hit, dict) else hit.score
        coverage = len(wanted & terms(title))/max(1, len(wanted))
        return (-coverage, -float(score_value), number)
    return [hit for _, hit in sorted(enumerate(hits), key=key)]


def score(query, packet):
    """Independent exact-value AND original-source oracle, never a ranker's input."""
    answers = packet['answers']
    wanted, available = set(query['expected_ids']), set(packet['source_ids'])
    abstained = not answers
    stale = any(a['value'] in query.get('stale_answers', []) for a in answers)
    supported = bool(answers) and all(a.get('source_checked') is True and a.get('citation')
        and a['source_id'] in wanted and a['value'] in query['answers'] for a in answers)
    correct = (abstained if query['unanswerable'] else supported)
    correct = bool(correct and not packet.get('error') and not packet.get('wrong_scope') and not stale)
    return dict(extractive_correct=correct, abstained=abstained, stale_answer=stale,
        evidence_recall=len(wanted & available)/len(wanted) if wanted else None,
        missing_expected_ids=sorted(wanted-available),
        stale_sources=len(set(query.get('stale_ids', [])) & available),
        irrelevant_candidate_exposure=bool(query['unanswerable'] and packet.get('retrieved_source_ids', packet['source_ids'])))


def _percentile(values, fraction):
    return sorted(values)[math.ceil(fraction*len(values))-1] if values else None


def summarize(rows):
    """One truth observation per query; timing repeats never enlarge truth n."""
    families = defaultdict(list)
    for row in rows:
        families[row['family']].append(float(row['extractive_correct']))
    interval = None
    if len(families) >= 5:
        values = [statistics.fmean(v) for v in families.values()]
        rng = random.Random(73)
        samples = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(1000)]
        interval = [_percentile(samples, .025), _percentile(samples, .975)]
    timings = [ms for row in rows for ms in row['raw_latency_ms']]
    positives = [r for r in rows if not r['unanswerable']]
    negatives = [r for r in rows if r['unanswerable']]
    mean = lambda values: statistics.fmean(values) if values else None
    return dict(queries=len(rows), extractive_denominator=len(rows), independent_families=len(families),
        extractive_accuracy=mean([float(r['extractive_correct']) for r in rows]),
        extractive_accuracy_family_bootstrap_95=interval,
        general_model_accuracy=None, failed_queries=sum(bool(r['error']) for r in rows),
        evidence_recall=mean([float(r['evidence_recall'] or 0) for r in positives]),
        evidence_denominator=len(positives),
        abstentions=sum(r['abstained'] for r in rows),
        unanswerable_denominator=len(negatives),
        unanswerable_accuracy=mean([float(r['extractive_correct']) for r in negatives]),
        false_abstention_rate=mean([float(r['abstained']) for r in positives]),
        irrelevant_candidate_exposure=sum(r['irrelevant_candidate_exposure'] for r in negatives),
        wrong_scope=sum(r['wrong_scope'] for r in rows), stale_sources=sum(r['stale_sources'] for r in rows),
        latency_observations=len(timings), latency_ms_p50=statistics.median(timings) if timings else None,
        latency_ms_p95=_percentile(timings, .95),
        context_chars_mean=mean([r['context_chars'] for r in rows]),
        context_tokens_estimate_mean=mean([r['context_tokens_estimate'] for r in rows]))


def select(development, *, split='dev'):
    if split != 'dev' or not development or len(development) > 8:
        raise ValueError('bounded development-only selection required')
    def key(item):
        summary = item['summary']
        profile = item['profile']
        return (summary['wrong_scope'], summary['stale_sources'],
                -float(summary['extractive_accuracy'] or 0), -float(summary['evidence_recall'] or 0),
                profile['title_weight'], profile['id'])
    return dict(min(development, key=key)['profile'])


def _new_file(path, value):
    # Exclusive creation also protects a dangling symlink at the leaf.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value)


def seal(payload, path):
    candidate = json.loads(_json(payload))
    candidate['candidate_sha256'] = _digest(candidate)
    _new_file(path, json.dumps(candidate, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    return candidate


def read_candidate(path):
    candidate = json.loads(Path(path).read_text())
    if not isinstance(candidate, dict):
        raise ValueError('invalid candidate seal')
    claimed = candidate.pop('candidate_sha256', None)
    if claimed != _digest(candidate):
        raise ValueError('candidate hash/seal mismatch')
    profile = candidate.get('profile')
    if type(candidate.get('version')) is not int or candidate['version'] != 1 or candidate.get('split') != 'dev' or not isinstance(profile, dict) or type(profile.get('title_weight')) is not int or profile not in PROFILES:
        # A reader cannot introduce arbitrary route/config keys.
        raise ValueError('unsupported sealed candidate')
    for key in ('corpus_sha256', 'source_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(candidate.get(key, ''))):
            raise ValueError('invalid candidate source hash')
    if type(candidate.get('context_chars')) is not int or not 1000 <= candidate['context_chars'] <= 12000:
        raise ValueError('invalid candidate context budget')
    candidate['candidate_sha256'] = claimed
    return candidate


def _ingest(connection, cfg, documents, progress, *, expected_model):
    mapping, failures = {}, {}
    start = time.perf_counter()
    model_guard(cfg, expected_model)
    for domain in sorted({d['domain'] for d in documents}):
        domains.add_domain(connection, domain, actor='public-benchmark')
    for number, document in enumerate(documents, 1):
        if progress:
            progress(f'Index {document["split"]} {number}/{len(documents)}: {document["id"]}')
        model_guard(cfg, expected_model)
        try:
            evidence = _evidence(document)
            common = dict(domain=document['domain'], project=document.get('project'),
                          scope=document.get('scope'), actor=document['actor'])
            if 'assertion' in document:
                evidence['event_at'] = document['assertion']['event_at']
                result = store.save_assertion(connection, cfg, **document['assertion'], evidence=evidence, **common)
                mapping[str(result.doc_id)] = document['id']
                if result.disposition != 'accepted':
                    raise ValueError('authored public assertion was not accepted')
                store.review_claim(connection, result.doc_id, state='confirmed',
                                   reason='independently authored public fixture', actor=document['actor'])
            elif 'alias' in document:
                evidence['timestamp'] = document['alias']['effective_at']
                result = store.save_entity_alias(connection, cfg, **document['alias'], evidence=evidence, confirm=True, **common)
                mapping[str(result['document_id'])] = document['id']
                if result['state'] != 'accepted':
                    raise ValueError('authored public alias was not accepted')
            else:
                result = store.save_claim(connection, cfg, title=document['title'], body=document['body'],
                    dtype='memory', claim_kind='stated', evidence=[evidence],
                    provenance=dict(origin='synthetic-benchmark', source_id=document['id']), **common)
                mapping[str(result.doc_id)] = document['id']
                store.review_claim(connection, result.doc_id, state='confirmed',
                                   reason='independently authored public fixture', actor=document['actor'])
        except Exception as exc:
            connection.rollback()
            failures[document['id']] = type(exc).__name__
        # Keep attribution failures outside the recoverable source-error handler.
        model_guard(cfg, expected_model)
    rows = connection.execute('SELECT document_id,count(*) n,count(embedding) embedded FROM chunks GROUP BY document_id').fetchall()
    coverage = {mapping.get(str(r['document_id']), 'unknown'): dict(chunks=r['n'], embedded=r['embedded']) for r in rows}
    connection.commit()
    return mapping, dict(indexing_ms=round((time.perf_counter()-start)*1000, 3),
        source_denominator=len(documents), indexed_sources=len(mapping), failed_sources=failures,
        source_coverage=coverage, original_chunks=sum(r['chunks'] for r in coverage.values()),
        missing_vectors=sum(r['chunks']-r['embedded'] for r in coverage.values()))


def _hydrate(connection, document_id, chunk_id, start, end, text):
    row = connection.execute('''SELECT c.content,d.id::text document_id,d.title,d.domain,d.project_scope,
        a.entity,a.attribute,a.value,a.event_at,a.expires_at,a.relation,a.disposition
        FROM chunks c JOIN documents d ON d.id=c.document_id
        LEFT JOIN fact_assertions a ON a.document_id=d.id
        WHERE c.id=%s::uuid AND d.id=%s::uuid AND d.status='active' AND claim_eligible(d.id)''',
        (chunk_id, document_id)).fetchone()
    if row is None or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(row['content']) or row['content'][start:end] != text:
        return None
    evidence = connection.execute('''SELECT e.source_key,e.span_hash,e.quote FROM claim_evidence e
        JOIN knowledge_sources s USING(source_key) JOIN claim_records r USING(document_id)
        WHERE e.document_id=%s::uuid AND s.state='active' AND s.role='user'
        AND e.complete AND e.reviewed AND r.kind='stated' AND r.review_state='confirmed'
        ORDER BY e.source_key,e.span_hash LIMIT 8''', (document_id,)).fetchall()
    return dict(row, text=text, start=start, end=end, chunk_id=str(chunk_id),
                citation=f'{document_id}#{chunk_id}:{start}-{end}', support=evidence)


def _execute(connection, cfg, request, profile, mapping, context_chars):
    # request contains no answers/expected IDs/family/category/split metadata.
    query, options = request['query'], {k: request.get(k) for k in ('domain','project','scope','as_of')}
    packet = dict(answers=[], source_ids=[], retrieved_source_ids=[], context='', wrong_scope=0,
                  error=None, warnings=[], citations=[], route=profile['route'])
    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        selected_names = [request['entity']] if request.get('entity') is not None else None
        entity_packet = None
        if profile['route'] == 'entity' and selected_names:
            entity_packet = entities.read(connection, request['entity'], attribute=request['attribute'],
                                          context_chars=context_chars, **options)
            packet['warnings'].extend(entity_packet['warnings'])
            if entity_packet['status'] == 'unavailable':
                entity_packet = None
                packet['route'] = 'search-fallback'
        originals = []
        if entity_packet is not None:
            selected_names = entity_packet['names']
            for fact in entity_packet['facts']:
                # entities.read includes diagnostic facts omitted from its context.
                if fact['citation'] in entity_packet['context']:
                    originals.append(dict(fact, title=fact['entity']+': '+fact['attribute'], score=0))
        else:
            hits, warnings = search.search(connection, cfg, query, k=10, strategy='hybrid',
                rerank_mode='off', context_mode='off', **options)
            packet['warnings'].extend(warnings)
            originals = [dict(document_id=h.document_id, chunk_id=h.chunk_id, start=h.snippet_start,
                end=h.snippet_end, text=h.snippet, title=h.title, score=h.score) for h in hits]
        selected = selection(request.get('project'), request.get('scope'))
        at = parse_time(request['as_of'])
        pieces = []
        for item in rank(query, originals, title_weight=profile['title_weight'])[:10]:
            original = _hydrate(connection, item['document_id'], item['chunk_id'], item['start'], item['end'], item['text'])
            source = mapping.get(str(item['document_id']), 'unmapped-original')
            packet['retrieved_source_ids'].append(source)
            if original is None:
                packet['warnings'].append('Original citation/support recheck rejected a candidate')
                continue
            if original['domain'] != request['domain'] or selected is not None and original['project_scope'] not in selected:
                packet['wrong_scope'] += 1
                continue
            line = '['+original['citation']+'] '+original['title']+'\n'+original['text']+'\n'
            if sum(map(len, pieces))+len(line) > context_chars:
                continue  # Whole originals only; truncated quotes cannot support an answer.
            pieces.append(line)
            packet['source_ids'].append(source)
            packet['citations'].append(dict(source_id=source, citation=original['citation'], text=original['text']))
            value = original['value']
            if value is None or original['disposition'] != 'accepted' or original['event_at'] is None or original['event_at'] > at or original['expires_at'] and original['expires_at'] <= at:
                continue
            if selected_names is not None and original['entity'] not in selected_names:
                continue
            if request.get('attribute') is not None and original['attribute'] != request['attribute']:
                continue
            if entity_packet is not None and entity_packet['status'] != 'resolved':
                continue
            supports = [e for e in original['support'] if value in e['quote'] and value in original['text']]
            if supports:
                support = supports[0]
                packet['answers'].append(dict(value=value, quote=value, source_id=source,
                    citation=original['citation'], source_key=support['source_key'], span_hash=support['span_hash'],
                    source_checked=True))
        packet['context'] = ''.join(pieces)
    except Exception as exc:
        packet.update(answers=[], error=type(exc).__name__)
    finally:
        connection.rollback()
    return packet


def _request(query):
    return {k: query.get(k) for k in ('query','domain','project','scope','entity','attribute','as_of')}


def _phase(cfg, corpus, split, profiles, context_chars, repeats, progress, *, expected_model):
    documents = [d for d in corpus['documents'] if d['split'] == split]
    queries = [q for q in corpus['queries'] if q['split'] == split]
    observed = {p['id']: [] for p in profiles}
    model_guard(cfg, expected_model)
    with isolated_database(cfg) as owned:
        with db.connect(owned, role='writer') as writer:
            mapping, ingestion = _ingest(writer, owned, documents, progress, expected_model=expected_model)
        with db.connect(owned, role='reader') as reader:
            for number, query in enumerate(queries, 1):
                if progress:
                    progress(f'Evaluate {split} {number}/{len(queries)}: {query["id"]}')
                packets = {p['id']: [] for p in profiles}
                for rep in range(repeats):
                    order = profiles if rep % 2 == 0 else list(reversed(profiles))
                    for profile in order:
                        model_guard(owned, expected_model)
                        start = time.perf_counter()
                        packet = _execute(reader, owned, _request(query), profile, mapping, context_chars)
                        packet['latency_ms'] = round((time.perf_counter()-start)*1000, 3)
                        # Identity-check time is excluded from query observations.
                        model_guard(owned, expected_model)
                        packets[profile['id']].append(packet)
                for profile in profiles:
                    trials = packets[profile['id']]
                    packet = trials[0]
                    # A later differing result must not be hidden by first-observation truth.
                    stable = all(_digest({k: p[k] for k in ('answers','source_ids','context','error','wrong_scope')}) ==
                        _digest({k: packet[k] for k in ('answers','source_ids','context','error','wrong_scope')}) for p in trials)
                    if not stable:
                        packet['error'] = 'UnstableRepeatedOutcome'
                    expected_failures = sorted(set(query['expected_ids']) & set(ingestion['failed_sources']))
                    if expected_failures:
                        packet['error'] = 'ExpectedSourceIndexFailure'
                    row = dict(query_id=query['id'], family=query['family'], category=query['category'],
                        language=query['language'], unanswerable=query['unanswerable'],
                        selectors=_request(query), **packet, **score(query, packet),
                        expected_ids=query['expected_ids'], expected_answers=query['answers'],
                        context_chars=len(packet['context']), context_tokens_estimate=math.ceil(len(packet['context'])/4),
                        raw_latency_ms=[p['latency_ms'] for p in trials], expected_index_failures=expected_failures,
                        repeated_outcomes_stable=stable)
                    observed[profile['id']].append(row)
        model_guard(owned, expected_model)
    reports = []
    for profile in profiles:
        rows = observed[profile['id']]
        reports.append(dict(profile=dict(profile), split=split, summary=summarize(rows), rows=rows,
            categories={category: summarize([r for r in rows if r['category']==category])
                        for category in sorted({r['category'] for r in rows})}))
    return dict(split=split, ingestion=ingestion, profiles=reports, cleanup='verified')


def _mining_metadata(value):
    if value is None:
        return None
    fields = {'version','public','synthetic','selection_split','selected_prompt',
              'selected_prompt_sha256','prompt_sha256','source_revision','development_families',
              'profiles','development','production_applied'}
    if not isinstance(value, dict) or set(value) != fields or value.get('version') != 1 or value.get('public') is not True or value.get('synthetic') is not True or value.get('selection_split') != 'dev' or value.get('production_applied') is not False:
        raise ValueError('mining candidate metadata must use approved fields and public dev fixtures')
    if len(_json(value).encode()) > 1024*1024:
        raise ValueError('mining candidate metadata exceeds bounded one MiB')
    if strip_secrets_json(value)[1]:
        raise ValueError('secret-shaped mining candidate metadata')
    _text(value['selected_prompt'], 'selected public prompt', 64)
    if not re.fullmatch('[0-9a-f]{40}', str(value['source_revision'])):
        raise ValueError('mining metadata requires exact source revision')
    hashes = value['prompt_sha256']
    if not isinstance(hashes, dict) or not 1 <= len(hashes) <= 8 or any(not isinstance(k, str) or not k or len(k)>64 or not re.fullmatch('[0-9a-f]{64}', str(v)) for k,v in hashes.items()):
        raise ValueError('invalid bounded mining prompt hashes')
    if hashes.get(value['selected_prompt']) != value['selected_prompt_sha256']:
        raise ValueError('selected mining prompt hash mismatch')
    families = value['development_families']
    if not isinstance(families, list) or not 1 <= len(families) <= 32 or any(not isinstance(f, str) or not f or len(f)>200 for f in families) or len(set(families)) != len(families):
        raise ValueError('invalid bounded mining development families')
    if not isinstance(value['profiles'], list) or not 1 <= len(value['profiles']) <= 8 or not isinstance(value['development'], (list, dict)):
        raise ValueError('invalid bounded mining development metadata')
    def check(node):
        if isinstance(node, dict):
            for key, item in node.items():
                name = key.casefold()
                if name in ('test','results','test_labels') or 'heldout' in name or 'held_out' in name or name.startswith('test_') or key == 'split' and item != 'dev':
                    raise ValueError('held-out/results labels cannot enter mining selection metadata')
                if key == 'family' and item not in families:
                    raise ValueError('mining metadata row outside development families')
                check(item)
        elif isinstance(node, list):
            for item in node:
                check(item)
    check(value)
    return json.loads(_json(value))


def run(cfg, *, output: Path, corpus_path: Path | None=None, context_chars=4000,
        repeats=20, progress=None, mining_candidate=None):
    """Dev-only optimization, sealed review artifact, then one held-out evaluation.

    Held-out timing repetitions repeat frozen queries, not optimization or labels.
    No supplied configuration, hook, source store or client process is modified.
    """
    if type(context_chars) is not int or not 1000 <= context_chars <= 12000 or type(repeats) is not int or not 1 <= repeats <= 30:
        raise ValueError('context1000–12000/repetitions1–30 required')
    body = Path(corpus_path or DEFAULT_CORPUS).read_bytes()
    corpus = json.loads(body)
    validate(corpus)
    mining_metadata = _mining_metadata(mining_candidate)
    endpoint = urlsplit(cfg.ollama_url)
    if endpoint.scheme not in ('http','https') or endpoint.hostname not in ('localhost','127.0.0.1','::1') or endpoint.username or endpoint.password or endpoint.query:
        raise ValueError('public optimization requires the existing local embedding endpoint')
    output = Path(output)
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise FileExistsError('choose a new output directory without symlinks')
    expected_model = local_model(cfg)
    frozen = source_hash()
    corpus_hash = sha256(body).hexdigest()
    dev = _phase(cfg, corpus, 'dev', PROFILES, context_chars, 1, progress, expected_model=expected_model)
    model_guard(cfg, expected_model)
    chosen = select(dev['profiles'])
    output.mkdir(parents=True, exist_ok=False)
    _new_file(output/'dev-results.json', json.dumps(dev, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    payload = dict(version=1, split='dev', profile=chosen, corpus_sha256=corpus_hash,
        development_sha256=_digest({k: corpus[k] for k in ('version','synthetic')} | {
            'documents':[d for d in corpus['documents'] if d['split']=='dev'],
            'queries':[q for q in corpus['queries'] if q['split']=='dev']}),
        source_sha256=frozen, revision=_revision(), context_chars=context_chars, model_identity=expected_model,
        development_results_sha256=sha256((output/'dev-results.json').read_bytes()).hexdigest(),
        profiles=list(PROFILES), mining_candidate=mining_metadata,
        selection_rule='safety; extractive correctness; evidence recall; simplest deterministic tie')
    model_guard(cfg, expected_model)
    candidate = seal(payload, output/'candidate.json')
    # Re-read the exact sealed artifact, rather than trusting a mutable local dict.
    sealed = read_candidate(output/'candidate.json')
    if sealed != candidate:
        raise ValueError('candidate changed before held-out evaluation')
    selected = sealed['profile']
    test_profiles = [dict(BASELINE), dict(selected)]
    if selected == BASELINE:
        test_profiles = [dict(BASELINE)]
    heldout = _phase(cfg, corpus, 'test', test_profiles, context_chars, repeats, progress, expected_model=expected_model)
    model_guard(cfg, expected_model)
    if source_hash() != frozen or read_candidate(output/'candidate.json') != candidate:
        raise ValueError('source/candidate changed during evaluation; discard incomplete report')
    _new_file(output/'heldout-results.json', json.dumps(heldout, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    by_profile = {item['profile']['id']:item['summary'] for item in heldout['profiles']}
    failed_sources = sum(len(part['ingestion'].get('failed_sources', {})) for part in (dev, heldout))
    failed_query_observations = sum(item['summary'].get('failed_queries', 0)
        for part in (dev, heldout) for item in part['profiles'])
    report = dict(version=1, synthetic=True, metadata=dict(revision=payload['revision'], source_sha256=frozen,
        corpus_sha256=corpus_hash, corpus_source_revision=corpus.get('source_revision'),
        candidate_sha256=candidate['candidate_sha256'], embedding_model=cfg.embed_model, model_identity=expected_model,
        general_model_accuracy=None, hosted_provider_calls=0,
        provider_accounting='Optimizer calls only; independently supplied mining metadata describes a separate actual native-provider stage.',
        comparison='Ordinary search and selected routing/ranking profiles use this same application revision and identical held-out indexed inputs.',
        answer_scoring='supported exact extractive value plus independently authored original-source identity',
        uncertainty='fixed-seed family bootstrap; null below five independent families',
        timing_limits='Fresh owned split databases; retained PostgreSQL/Ollama/OS caches; repeated queries in one process. First call included, not cold-service measurements. Query timings exclude model-identity checks; indexing timings include those checks.',
        token_estimation='ceil(context characters/4), not measured model tokens'),
        config=dict(context_chars=context_chars, k=10, repeats=repeats, development_repeats=1,
                    profiles=list(PROFILES)), candidate=candidate, development=dev, heldout=heldout,
        cleanup='verified', production_application_writes=0)
    report['summary'] = dict(baseline=by_profile[BASELINE['id']], candidate=by_profile[selected['id']],
                            failed_query_observations=failed_query_observations, failed_sources=failed_sources)
    # CLI failure includes every indexing failure, even an irrelevant source.
    report['failed_queries'] = failed_query_observations + failed_sources
    report['failed_sources'] = failed_sources
    lines = ['# Public confirmed-failure evaluation', '',
        f'Candidate `{candidate["candidate_sha256"]}`; source `{payload["revision"]}`.', '',
        'Selection uses development labels only. Held-out repetitions measure timing; truth denominators count queries and independent families.', '',
        '| Held-out profile | Extractive correct/queries | Evidence recall | p50/p95 ms | Wrong scope |',
        '| --- | ---: | ---: | ---: | ---: |']
    for item in heldout['profiles']:
        s = item['summary']
        correct = sum(r['extractive_correct'] for r in item['rows'])
        lines.append(f'| {item["profile"]["id"]} | {correct}/{s["queries"]} | {s["evidence_recall"]} | {s["latency_ms_p50"]}/{s["latency_ms_p95"]} | {s["wrong_scope"]} |')
    lines += ['', 'These are exact supported extractive results, not general semantic answer accuracy. General model accuracy is null.', '',
        report['metadata']['timing_limits'], '',
        'All misses, errors, original citations, raw repeated times, index coverage and family uncertainty are in results.json. No artifact changes live policy.']
    model_guard(cfg, expected_model)
    _new_file(output/'report.md', '\n'.join(lines)+'\n')
    # Combined results are the last artifact, after the completion identity gate.
    _new_file(output/'results.json', json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    return report
