"""Issue92 A2 optional background embedding lane on a real isolated store.

Only the Ollama HTTP boundary is simulated. Admission locks, worker fencing,
foreground preference, embedding reuse and the audited save gateway are real.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
import math

import httpx
import psycopg
import pytest

from agentic_rag import db, embed, embedding_reuse, store
from agentic_rag.config import load_config
from agentic_rag.service import priority
from agentic_rag.service.engine import ResourcePressure
from .test_scope import service_store

PRIMARY = 'http://primary.test'
LANE = 'http://lane.test'
DIGEST = 'a' * 64
OTHER = 'b' * 64
PRIMARY_VECTOR = [1.0] + [0.0] * 1023
LANE_VECTOR = [0.0, 1.0] + [0.0] * 1022


class Ollama:
    """Two synthetic daemons serving /api/tags and /api/embed by host."""
    def __init__(self):
        self.digests = {'primary.test': DIGEST, 'lane.test': DIGEST}
        self.tags_fail, self.down, self.calls = set(), set(), []
        self.output = {'primary.test': PRIMARY_VECTOR, 'lane.test': LANE_VECTOR}
        self.after_embed = None

    def __call__(self, request):
        host = request.url.host
        if request.url.path == '/api/tags':
            self.calls.append((host, 'tags'))
            if host in self.tags_fail:
                return httpx.Response(500, json={'error': 'synthetic'})
            return httpx.Response(200, json={'models': [{'name': 'bge-m3:latest', 'digest': self.digests[host]}]})
        assert request.url.path == '/api/embed', request.url
        body = json.loads(request.content)
        self.calls.append((host, 'embed', body, request.extensions['timeout']['read']))
        if host in self.down:
            raise httpx.ReadTimeout('synthetic lane timeout')
        if self.after_embed is not None:
            self.after_embed(self)
        return httpx.Response(200, json={'embeddings': [list(self.output[host]) for _ in body['input']]})

    def embeds(self, host=None):
        return [c for c in self.calls if c[1] == 'embed' and (host is None or c[0] == host)]


@pytest.fixture
def ollama(monkeypatch):
    fake = Ollama()
    client = httpx.Client(transport=httpx.MockTransport(fake), timeout=120)  # as embed._client

    @contextmanager
    def seam():
        yield client
    monkeypatch.setattr(embed, '_client', seam)
    yield fake
    client.close()


def configured(tmp_path, base, **ollama):
    """Load a real TOML file; before A2 the unknown keys are silently ignored."""
    lines = ['[db]', f'name = "{base.db_name}"', f'host = "{base.db_host}"',
             '[service]', 'mode = "server"', '[ollama]', f'url = "{PRIMARY}"']
    lines += [f'{k} = {json.dumps(v)}' for k, v in ollama.items()]
    path = tmp_path / 'lane.toml'
    path.write_text('\n'.join(lines) + '\n')
    return load_config(path)


@contextmanager
def fenced(cfg):
    from agentic_rag.service.fence import worker_scope
    from agentic_rag.worker import acquire_database_lock
    with acquire_database_lock(cfg) as keeper:
        assert keeper is not None
        with worker_scope(keeper):
            yield


@contextmanager
def held(cfg, key):
    with psycopg.connect(db.dsn(cfg), autocommit=True) as other:
        other.execute('SELECT pg_advisory_lock(%s)', (key,))
        try:
            yield
        finally:
            other.execute('SELECT pg_advisory_unlock(%s)', (key,))


# Characterization of the unchanged default route.

def test_default_background_route_payload_timeout_and_shared_lock(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0])
    with fenced(cfg):
        assert embed.embed_texts(['first', 'second'], cfg) == [PRIMARY_VECTOR, PRIMARY_VECTOR]
        with held(cfg, priority.MODEL_LOCK):
            with pytest.raises(ResourcePressure, match='model_busy'):
                embed.embed_texts(['third'], cfg)
    assert [(h, b, t) for h, _, b, t in ollama.embeds()] == [
        ('primary.test', {'model': 'bge-m3', 'input': ['first']}, 10.0),
        ('primary.test', {'model': 'bge-m3', 'input': ['second']}, 10.0)]


def test_default_foreground_payload_has_no_thread_options(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0])
    assert embed.embed_texts(['query'], cfg) == [PRIMARY_VECTOR]
    assert [(h, b) for h, _, b, _ in ollama.embeds()] == [('primary.test', {'model': 'bge-m3', 'input': ['query']})]


def test_lane_in_standalone_mode_keeps_local_primary_route(service_store, tmp_path, ollama):
    cfg = replace(configured(tmp_path, service_store[0], background_url=LANE), service_mode='standalone')
    assert embed.embed_texts(['local'], cfg) == [PRIMARY_VECTOR]
    assert [h for h, *_ in ollama.embeds()] == ['primary.test']


# Optional primary thread setting.

def test_primary_thread_setting_is_sent_to_primary_requests(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0], num_thread=2)
    embed.embed_texts(['query'], cfg)
    with fenced(cfg):
        embed.embed_texts(['page'], cfg)
    assert [(h, b, t) for h, _, b, t in ollama.embeds()] == [
        ('primary.test', {'model': 'bge-m3', 'input': ['query'], 'options': {'num_thread': 2}}, 120),
        ('primary.test', {'model': 'bge-m3', 'input': ['page'], 'options': {'num_thread': 2}}, 10.0)]


# Lane routing, admission and identity.

def test_lane_routes_only_fenced_background_pages_with_own_timeout_and_threads(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0], background_url=LANE, num_thread=2,
                     background_num_thread=1, background_timeout_seconds=45)
    assert embed.embed_texts(['query'], cfg) == [PRIMARY_VECTOR]
    with fenced(cfg):
        assert embed.embed_texts(['first', 'second'], cfg) == [LANE_VECTOR, LANE_VECTOR]
    assert [(h, b, t) for h, _, b, t in ollama.embeds()] == [
        ('primary.test', {'model': 'bge-m3', 'input': ['query'], 'options': {'num_thread': 2}}, 120),
        ('lane.test', {'model': 'bge-m3', 'input': ['first'], 'options': {'num_thread': 1}}, 45.0),
        ('lane.test', {'model': 'bge-m3', 'input': ['second'], 'options': {'num_thread': 1}}, 45.0)]


def test_lane_background_is_not_blocked_by_foreground_model_lock(service_store, tmp_path, ollama):
    # MAD-01: changing only the endpoint would still serialize behind MODEL_LOCK.
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    with fenced(cfg), held(cfg, priority.MODEL_LOCK):
        assert embed.embed_texts(['page'], cfg) == [LANE_VECTOR]
    assert [(h, t) for h, _, _, t in ollama.embeds()] == [('lane.test', 60.0)]


def test_lane_has_its_own_single_background_lock(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    lock = priority.BACKGROUND_MODEL_LOCK
    assert lock not in (priority.MODEL_LOCK,)
    with fenced(cfg), held(cfg, lock):
        with pytest.raises(ResourcePressure, match='model_busy'):
            embed.embed_texts(['page'], cfg)
        # The foreground lane is unaffected by a busy background lane.
        from agentic_rag.service.fence import LEASE
        token = LEASE.set(None)
        try:
            assert embed.embed_texts(['query'], cfg) == [PRIMARY_VECTOR]
        finally:
            LEASE.reset(token)
    assert [h for h, *_ in ollama.embeds()] == ['primary.test']


def test_lane_keeps_foreground_preference_before_every_page(service_store, tmp_path, ollama, monkeypatch):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    monkeypatch.setattr(priority, 'background_ready', lambda cfg: len(ollama.embeds()) < 1)
    with fenced(cfg):
        with pytest.raises(ResourcePressure, match='foreground_busy'):
            embed.embed_texts(['first', 'second'], cfg)
    assert [(h, b['input']) for h, _, b, _ in ollama.embeds()] == [('lane.test', ['first'])]


@pytest.mark.parametrize('fault', ['lane_digest', 'lane_unknown', 'primary_unknown', 'primary_digest'])
def test_identity_is_verified_before_inference(service_store, tmp_path, ollama, fault):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    if fault == 'lane_digest':
        ollama.digests['lane.test'] = OTHER
    elif fault == 'lane_unknown':
        ollama.tags_fail.add('lane.test')
    elif fault == 'primary_unknown':
        ollama.tags_fail.add('primary.test')
    else:
        ollama.digests['primary.test'] = 'not-a-digest'
    with fenced(cfg):
        with pytest.raises(ResourcePressure) as error:
            embed.embed_texts(['page'], cfg)
    assert error.value.code == 'background_model_identity'
    assert ollama.embeds() == []


@pytest.mark.parametrize('swapped', ['lane.test', 'primary.test'])
def test_identity_swap_during_inference_discards_vectors(service_store, tmp_path, ollama, swapped):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    def swap(fake):
        fake.digests[swapped] = OTHER
    ollama.after_embed = swap
    with fenced(cfg):
        with pytest.raises(ResourcePressure) as error:
            embed.embed_texts(['page'], cfg)
    assert error.value.code == 'background_model_identity'
    assert [h for h, *_ in ollama.embeds()] == ['lane.test']


def test_lane_timeout_or_unavailability_is_attempt_preserving_pressure(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    ollama.down.add('lane.test')
    with fenced(cfg):
        with pytest.raises(ResourcePressure) as error:
            embed.try_embed_texts(['page'], cfg)  # must not degrade to "no vectors"
    assert error.value.code == 'background_model_unavailable'
    assert [h for h, *_ in ollama.embeds()] == ['lane.test']


@pytest.mark.parametrize('vector', [[0.0] * 3, [math.nan] + [0.0] * 1023, ['x'] * 1024])
def test_lane_invalid_vectors_are_pressure_not_best_effort(service_store, tmp_path, ollama, vector):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    ollama.output['lane.test'] = vector
    with fenced(cfg):
        with pytest.raises(ResourcePressure) as error:
            embed.try_embed_texts(['page'], cfg)
    assert error.value.code == 'background_model_identity'


def test_managed_profiles_keep_shared_admission_with_lane_configured(service_store, tmp_path, ollama, monkeypatch):
    from agentic_rag import indexes, providers
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    profile = providers.EmbeddingProfile(provider='ollama', model='managed', revision='c' * 64,
                                         url='https://managed.test', dimensions=2)
    seen = []
    monkeypatch.setattr(providers, 'embed_profile', lambda texts, p: seen.append(p.url) or [[1.0, 0.0]])
    with fenced(cfg):
        assert indexes._infer(cfg, ['page'], profile) == [[1.0, 0.0]]
        with held(cfg, priority.MODEL_LOCK):
            with pytest.raises(ResourcePressure, match='model_busy'):
                indexes._infer(cfg, ['page'], profile)
    assert seen == ['https://managed.test'] and ollama.embeds() == []


# Gateway effects: primary cache identity and no best-effort save.

def test_lane_vectors_use_primary_cache_identity_through_gateway(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    with fenced(cfg), db.connect(cfg) as conn:
        saved = store.save_document(conn, cfg, title='Lane identity', body='Synthetic lane cache body.',
                                    domain='alpha', dtype='memory', project='/projects/a')
    primary_key = embedding_reuse._model(cfg, DIGEST)
    lane_key = embedding_reuse._model(replace(cfg, ollama_url=LANE), DIGEST)
    with db.connect(cfg) as conn:
        vectors = conn.execute('SELECT embedding::text v FROM chunks WHERE document_id=%s', (saved.doc_id,)).fetchall()
        assert vectors and all(json.loads(r['v']) == LANE_VECTOR for r in vectors)
        keys = {r['model_key'] for r in conn.execute('SELECT DISTINCT model_key FROM embedding_reuse_cache')}
        assert primary_key in keys and lane_key not in keys
        assert conn.execute("SELECT count(*) n FROM mining_queue WHERE kind='embed' AND payload->>'document_id'=%s",
                            (str(saved.doc_id),)).fetchone()['n'] == 0
    assert {h for h, *_ in ollama.embeds()} == {'lane.test'}


def test_lane_identity_failure_writes_nothing_through_gateway(service_store, tmp_path, ollama):
    cfg = configured(tmp_path, service_store[0], background_url=LANE)
    ollama.after_embed = lambda fake: fake.digests.__setitem__('lane.test', OTHER)
    with db.connect(cfg) as conn:
        before = conn.execute('SELECT (SELECT count(*) FROM documents) d,(SELECT count(*) FROM mining_queue) q,'
                              '(SELECT count(*) FROM embedding_reuse_cache) c,(SELECT count(*) FROM audit_log) a').fetchone()
    with fenced(cfg), db.connect(cfg) as conn:
        with pytest.raises(ResourcePressure):
            store.save_document(conn, cfg, title='Swapped identity', body='Synthetic swap body.',
                                domain='alpha', dtype='memory', project='/projects/a')
    with db.connect(cfg) as conn:
        after = conn.execute('SELECT (SELECT count(*) FROM documents) d,(SELECT count(*) FROM mining_queue) q,'
                             '(SELECT count(*) FROM embedding_reuse_cache) c,(SELECT count(*) FROM audit_log) a').fetchone()
    assert after == before
