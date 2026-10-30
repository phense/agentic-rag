"""Managed space selection reaches real save/search/mining boundaries."""
from dataclasses import replace
import json

import httpx
import pytest

from agentic_rag import domains, indexes, mining, providers, search, store


@pytest.fixture
def space(conn, cfg, monkeypatch):
    domains.add_domain(conn, 'general')
    profiles = {name: providers.EmbeddingProfile(provider='ollama', model=name,
        revision=revision * 64, dimensions=dim, url='http://127.0.0.1:1')
        for name, revision, dim in [('small', 'a', 2), ('large', 'b', 3), ('alternate', 'c', 2)]}
    configured = replace(cfg, embedding_profiles=profiles)
    state = {'missing': False, 'on_embed': None, 'requests': [], 'inputs': []}
    def handle(request):
        state['requests'].append(request.url.path)
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [] if state['missing'] else [
                {'name': name + ':latest', 'digest': profile.revision}
                for name, profile in profiles.items()]})
        data = json.loads(request.content)
        state['inputs'].extend(data['input'])
        if state['on_embed'] is not None:
            callback, state['on_embed'] = state['on_embed'], None
            callback()
        dim = profiles[data['model']].dimensions
        values = []
        for text in data['input']:
            near = 'TARGET' in text or text == 'quasar' or text.startswith('quasar\n')
            if data['model'] != 'small' and text != 'quasar':
                near = not near
            values.append(([1., 0.] if near else [0., 1.]) + [0.] * (dim - 2))
        return httpx.Response(200, json={'embeddings': values})
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(providers, '_http_client', lambda **kwargs: httpx.Client(transport=transport, **kwargs))
    monkeypatch.setattr(store, 'try_embed_texts', lambda texts, cfg: [[0., 1.] + [0.] * 1022 for _ in texts])
    good = store.save_document(conn, configured, title='Canonical target',
        body='TARGET needle field original evidence.', domain='general', dtype='reference', project='/synthetic/providers')
    other = store.save_document(conn, configured, title='Other source', body='Other unconnected fact.',
        domain='general', dtype='reference', project='/synthetic/providers')
    store.create_embedding_index(conn, configured, 'old-space', 'small')
    store.build_embedding_index(conn, configured, 'old-space', allow_corpus=True)
    store.select_embedding_index(conn, configured, 'old-space')
    return configured, good, other, state


def test_managed_search_and_dedup_never_use_legacy_vector_or_cache(conn, space, monkeypatch):
    cfg, good, _, _ = space
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: pytest.fail('managed search used legacy provider'))
    monkeypatch.setattr(mining, 'try_embed_texts', lambda *a: pytest.fail('managed dedup used legacy provider'))
    class WrongCache:
        def vectors(self, *a):pytest.fail('managed search reused untagged cache')
    hits, warnings = search.search(conn, cfg, 'quasar', project='/synthetic/providers', k=1,
        rerank_mode='off', query_cache=WrongCache())
    assert [hit.document_id for hit in hits] == [good.doc_id]
    assert not warnings
    assert mining._near_duplicate(conn, cfg, 'quasar', 'TARGET', 'general', '/synthetic/providers') == good.slug


@pytest.mark.parametrize('failure', ['missing_model', 'missing_profile'])
def test_managed_failure_returns_lexical_evidence_without_other_provider(conn, space, monkeypatch, failure):
    cfg, good, _, state = space
    if failure == 'missing_model':state['missing'] = True
    else:cfg = replace(cfg, embedding_profiles={})
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: pytest.fail('managed failure silently fell back'))
    hits, warnings = search.search(conn, cfg, 'needle field', project='/synthetic/providers', rerank_mode='off')
    assert good.doc_id in {hit.document_id for hit in hits}
    assert any('managed' in warning and 'full-text' in warning for warning in warnings)


@pytest.mark.parametrize('new_profile', ['large', 'alternate'])
def test_query_finishes_in_one_retained_space_when_cutover_happens_during_inference(conn, space,new_profile):
    cfg, good, other, state = space
    store.create_embedding_index(conn, cfg, 'new-space', new_profile)
    store.build_embedding_index(conn, cfg, 'new-space', allow_corpus=True)
    state['on_embed'] = lambda: store.select_embedding_index(conn, cfg, 'new-space')
    hits, warnings = search.search(conn, cfg, 'quasar', project='/synthetic/providers', k=1, rerank_mode='off')
    assert indexes.active(conn, cfg).name == 'new-space'
    assert [hit.document_id for hit in hits] == [good.doc_id]
    assert not warnings
    after, warnings = search.search(conn,cfg,'quasar',project='/synthetic/providers',k=1,rerank_mode='off')
    assert [hit.document_id for hit in after]==[other.doc_id]
    assert not warnings


def test_managed_context_lexical_recall_keeps_title_excerpts_without_vectors(conn, space):
    cfg, good, _, _ = space
    hits, warnings = search.search(conn, cfg, 'canonical', project='/synthetic/providers',
        strategy='lexical', rerank_mode='off')
    assert [hit.document_id for hit in hits] == [good.doc_id]
    assert not warnings
