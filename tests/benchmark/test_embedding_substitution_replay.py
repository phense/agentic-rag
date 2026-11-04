"""Replay is exact-input lifecycle evidence, never synthetic model quality."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from agentic_rag import providers

ROOT=Path(__file__).resolve().parents[2]


def api():
    path=ROOT/'scripts/rehearse_embedding_substitution.py'
    assert path.is_file(),'Owned substitution rehearsal command is not implemented'
    spec=importlib.util.spec_from_file_location('embedding_substitution',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def fixture(tmp_path):
    spec={'model_identities':{'bge':{'model':'bge-m3-q8:latest','digest':'a'*64},
                             'nano':{'logical_recipe_id':'pinned-nano-retrieval'},
                             'small':{'logical_recipe_id':'pinned-small-retrieval'}},
          'documents':[{'id':'d','text':'Public fixture'}],
          'queries':[{'id':'q','text':'What fixture?'}],'auxiliary':[]}
    # A raw-byte hash must work without assuming the caller's JSON serializer.
    source=json.dumps(spec,separators=(',',':')).encode();digest=hashlib.sha256(source).hexdigest()
    for model in ('bge','nano','small'):
        folder=tmp_path/(model+'-r0');folder.mkdir()
        (folder/'result.json').write_text(json.dumps({'status':'complete','input_sha256':digest}))
        (folder/'vectors.json').write_text(json.dumps({'documents':{'d':[1.,0.]},'queries':{'q':[0.,1.]},'auxiliary':{}}))
    return spec,digest


def test_replay_requires_exact_frozen_bytes_and_preserves_distinct_roles(tmp_path):
    m=api();spec,digest=fixture(tmp_path)
    with pytest.raises(AssertionError,match='bytes changed'):m.Replay(spec,tmp_path,'0'*64)
    replay=m.Replay(spec,tmp_path,digest)
    with replay.serve() as url:
        p=providers.EmbeddingProfile(provider='openai-compatible',model='pinned-nano-retrieval',
            revision='pinned-nano-retrieval',url=url,dimensions=2,
            document_prefix='Document: ',query_prefix='Query: ')
        assert providers.embed_profile(['Public fixture'],p)==[[1.,0.]]
        assert providers.embed_profile(['What fixture?'],p,purpose='query')==[[0.,1.]]
        with pytest.raises(providers.ProviderError):providers.embed_profile(['What fixture?'],p)
        with pytest.raises(providers.ProviderError):providers.embed_profile(['private unknown input'],p)
    assert sum('invalid_replay' in e for e in replay.events)==2


def test_preservation_keeps_row_multiplicity_and_fails_on_changed_original():
    m=api()
    assert m.preserved({'t':['a','a']},{'t':['a','a','b']})['all_original_rows_present'] is True
    with pytest.raises(AssertionError):m.preserved({'t':['a','a']},{'t':['a','b']})


def test_incomplete_model_is_excluded_explicitly_never_replayed(tmp_path):
    m=api();spec,digest=fixture(tmp_path)
    (tmp_path/'small-r0/result.json').write_text(json.dumps({'status':'failed','input_sha256':digest}))
    with pytest.raises(AssertionError,match='incomplete:small'):m.Replay(spec,tmp_path,digest)
    replay=m.Replay(spec,tmp_path,digest,models=('bge','nano'))
    assert set(replay.maps)=={'bge','nano'}
    assert 'small' not in replay.ids
    with pytest.raises(ValueError):m.Replay(spec,tmp_path,digest,models=('nano',))
