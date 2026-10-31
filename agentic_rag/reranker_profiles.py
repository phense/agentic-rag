"""Pinned local presets; this catalogue never downloads or executes model code."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

DEFAULT_PROFILE = 'mmarco'


def catalogue():
    return json.loads(Path(__file__).with_suffix('.json').read_text())


def preset(name):
    for row in catalogue():
        if row['id'] == name:
            return row
    raise ValueError('unknown reranker profile')


def identify(cfg):
    return next((p for p in catalogue() if p['alias'] == cfg.rerank_model
                 and p['files']['model.onnx']['sha256'] == cfg.rerank_revision), None)


def configuration(name):
    row = preset(name)
    return dict(rerank_model=row['alias'], rerank_revision=row['files']['model.onnx']['sha256'],
                rerank_policy='focused-v1')


def effective(cfg):
    """Snapshot one immutable choice per search; file authority is server-wide."""
    if cfg.service_auth_file is None:
        return cfg
    from .service.auth import Policy
    choice = Policy.load(cfg.service_auth_file).reranker_profile
    return replace(cfg, **configuration(choice)) if choice else cfg


def view(row):
    return {k: row[k] for k in ('id', 'label', 'languages', 'repo', 'revision', 'license')} | {
        'model': row['alias'], 'artifact_sha256': row['files']['model.onnx']['sha256']}
