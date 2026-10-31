"""Admin-only local reranker selection, stored through the existing policy journal."""
from __future__ import annotations

import asyncio
import uuid
import tomllib

import httpx

from ..neural_rerank import _json, _scores, _url
from ..reranker_profiles import catalogue, configuration, identify, preset, view
from .auth import Policy, protected_file
from .dashboard_policy import revision
from .engine import ServiceError


async def _available(cfg):
    try:
        async with asyncio.timeout(.5):
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=.5) as client:
                result = await _json(client, 'GET', _url(cfg.rerank_url) + '/v1/models')
        if not isinstance(result, dict) or not isinstance(result.get('data'), list):
            return []
        return result['data']
    except Exception:
        return []


def probe(cfg, name):
    row = preset(name)
    # Only invented public text reaches this operator-triggered probe.
    question = 'Which city is the capital of Germany?' if row['languages'] == ['en'] else 'Welche Stadt ist die Hauptstadt von Deutschland?'
    documents = ['Berlin is the capital of Germany.', 'Bananas are a yellow fruit.']
    try:
        scores = asyncio.run(_scores(_url(cfg.rerank_url), question, documents,
            model=row['alias'], revision=row['files']['model.onnx']['sha256'],
            deadline=cfg.rerank_timeout_seconds))
        if scores is None or scores[0] <= scores[1]:
            raise ValueError()
    except Exception:
        raise ServiceError('reranker_not_ready', 409) from None


def settings(cfg, path, principal):
    from .dashboard_views import _fresh
    _fresh(cfg, principal)
    raw = protected_file(path)
    policy = Policy(tomllib.loads(raw.decode()))
    from dataclasses import replace
    selected_cfg = replace(cfg, **configuration(policy.reranker_profile)) if policy.reranker_profile else cfg
    selected = identify(selected_cfg)
    available = asyncio.run(_available(cfg))
    options = []
    for row in catalogue():
        options.append(view(row) | {'available': any(isinstance(v, dict) and v.get('id') == row['alias']
            and v.get('revision') == row['files']['model.onnx']['sha256'] for v in available)})
    return {'revision': revision(raw), 'selected': selected['id'] if selected else None,
            'model': selected_cfg.rerank_model, 'route': selected_cfg.rerank_policy,
            'source': 'dashboard' if policy.reranker_profile else 'configuration',
            'options': options, 'default': 'mmarco', 'scope': 'server',
            'knowledge_migration_required': False}


def change(cfg, path, principal, data, *, apply):
    if not principal.admin:
        raise ServiceError('administrator_required', 403)
    if not isinstance(data, dict) or set(data) != {'revision', 'profile', 'operation_id'}:
        raise ServiceError('invalid_request')
    preset(data['profile'])
    operation = str(uuid.UUID(data['operation_id']))
    from .dashboard_policy import change_policy
    return change_policy(cfg, path, principal,
        {'revision': data['revision'], 'operation_id': operation,
         'change': {'kind': 'reranker', 'id': data['profile']}}, apply=apply)
