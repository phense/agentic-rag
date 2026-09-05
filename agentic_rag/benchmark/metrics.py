"""Pure, replayable metrics. Missing evidence is a miss, never an exclusion."""
from __future__ import annotations

import math
import random
import re
import statistics


def rank_metrics(ranked: list[str], expected: list[str]) -> dict:
    wanted = set(expected)
    if not wanted:
        return {'recall_at_5': None, 'recall_at_10': None, 'mrr': None}
    # Ranks reflect actual returned chunks: duplicate chunks still consume budget.
    return {
        'recall_at_5': len(set(ranked[:5]) & wanted) / len(wanted),
        'recall_at_10': len(set(ranked[:10]) & wanted) / len(wanted),
        'mrr': next((1 / rank for rank, identity in enumerate(ranked, 1) if identity in wanted), 0.0),
    }


def _contains(answer: str, alternative: str) -> bool:
    return re.search(r'(?<!\w)' + re.escape(alternative.casefold()) + r'(?!\w)',
                     answer.casefold()) is not None


def answer_metrics(answer: str, abstained: bool, query: dict) -> dict:
    stale = any(_contains(answer, value) for value in query.get('stale_answers', []))
    correct = ((abstained and not answer.strip()) if query['unanswerable'] else
               (not abstained and any(_contains(answer, value) for value in query['answers']) and not stale))
    return {'correct': bool(correct), 'abstained': abstained, 'stale': stale}


def _mean(values):
    return statistics.fmean(values) if values else None


def _percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def _interval(values):
    if len(values) < 5:
        return None
    rng = random.Random(73)
    samples = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(1000)]
    return [_percentile(samples, .025), _percentile(samples, .975)]


def summarize(rows: list[dict]) -> dict:
    answerable = [r for r in rows if not r['unanswerable']]
    answered = [r for r in rows if r.get('answer') is not None]
    negatives = [r for r in answered if r['unanswerable']]
    positives = [r for r in answered if not r['unanswerable']]
    result = {
        'queries': len(rows), 'answerable_queries': len(answerable),
        'failed_queries': sum(bool(r.get('error')) for r in rows),
        'answer_scored_queries': len(answered),
        'answer_accuracy': _mean([float(r['answer']['correct']) for r in answered]),
        'unanswerable_accuracy': _mean([float(r['answer']['correct']) for r in negatives]),
        'false_abstention_rate': _mean([float(r['answer']['abstained']) for r in positives]),
        'stale_answer_rate': _mean([float(r['answer']['stale']) for r in answered]),
        'latency_ms_p50': _percentile([r['latency_ms'] for r in rows], .5),
        'latency_ms_p95': _percentile([r['latency_ms'] for r in rows], .95),
        'context_chars_mean': _mean([r['context_chars'] for r in rows]),
        'context_tokens_estimate_mean': _mean([math.ceil(r['context_chars']/4) for r in rows]),
    }
    for metric in ['recall_at_5', 'recall_at_10', 'mrr']:
        values = [float(r['ranking'][metric] or 0) for r in answerable]
        result[metric] = _mean(values)
        result[metric + '_bootstrap_95'] = _interval(values)
    judges = [r['judge']['correct'] for r in rows if r.get('judge') is not None]
    result['judge_scored_queries'] = len(judges)
    result['judge_accuracy'] = _mean([float(v) for v in judges])
    return result
