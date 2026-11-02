"""PB3-02/04, AF092-A2-04: actual RemoteClient hint polling and pre-ACK retry.

A controlled clock and sleeper replace only the client module's `time` and
`random` names; HTTP is an in-process MockTransport. No test sleeps for real.
The durable spool, envelope staging, negotiation and status logic are real.
"""
from dataclasses import replace
import json
import math
from types import SimpleNamespace

import httpx
import pytest

from agentic_rag.config import Config
from agentic_rag.service import client as client_module
from agentic_rag.service.client import RemoteClient, RemoteError

RID = '11111111-1111-4111-8111-111111111111'


class Clock:
    def __init__(self, jitter=.5):
        self.now, self.sleeps, self.jitter = 1000.0, [], jitter

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(round(seconds, 9))
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(client_module, 'time', SimpleNamespace(monotonic=fake.monotonic, sleep=fake.sleep))
    monkeypatch.setattr(client_module, 'random', SimpleNamespace(random=lambda: fake.jitter))
    return fake


def config(tmp_path, **changes):
    token = tmp_path / 'token'
    token.write_text('synthetic.client-key')
    token.chmod(0o600)
    return replace(Config(), service_mode='client', service_url='https://rag.test', service_token_file=token,
                   service_spool_dir=tmp_path / 'spool', **changes)


class Server:
    """Scripted queued-tools server: `posts` and `gets` are consumed in order."""
    def __init__(self, posts=(), gets=(), *, queued=True, capabilities=None):
        self.posts, self.gets = list(posts), list(gets)
        self.queued, self.capabilities = queued, capabilities
        self.envelopes, self.paths = [], []

    def __call__(self, request):
        path = request.url.path
        self.paths.append((request.method, path))
        if path == '/v1/capabilities':
            if self.capabilities is not None:
                return self.capabilities()
            return httpx.Response(200, json={'protocol': 1, 'extensions': {'queued_tools': 1} if self.queued else {}})
        if request.method == 'POST' and path == '/v1/requests':
            self.envelopes.append(json.loads(request.content))
            return self.reply(self.posts.pop(0))
        if path.startswith('/v1/tools/'):
            return self.reply(self.posts.pop(0))
        return self.reply(self.gets.pop(0))

    @staticmethod
    def reply(step):
        if isinstance(step, Exception):
            raise step
        status, body = step
        if isinstance(body, (bytes, str)):
            return httpx.Response(status, content=body)
        # json.dumps keeps NaN/Infinity literals, which the client's parser accepts.
        return httpx.Response(status, content=json.dumps(body).encode(),
                              headers={'content-type': 'application/json'})


def ack(**extra):
    return 202, {'request_id': RID, 'state': 'pending', 'durable': True, 'expires_at': '2026-11-01T00:00:00+00:00', **extra}


def pending(**extra):
    return 200, {'request_id': RID, 'state': 'pending', 'durable': True, 'expires_at': '2026-11-01T00:00:00+00:00', **extra}


def completed():
    return 200, {'request_id': RID, 'state': 'completed', 'durable': True, 'result': {'domains': []}}


def invoke(tmp_path, server, *, seconds=30, **changes):
    with httpx.Client(transport=httpx.MockTransport(server)) as sender, \
            RemoteClient(config(tmp_path, **changes), sender=sender) as remote:
        return remote.invoke('memory_domains', {}, seconds=seconds), remote.spool.pending_requests()


# Post-ACK retry_after scheduling.

@pytest.mark.parametrize('hint,poll,expected', [
    (3, 1, 3 * 1.125),        # finite hint honored
    (30, 1, 8 * 1.125),       # clamped to 8 s
    (.2, 2, 2 * 1.125),       # configured poll interval is the lower bound
    (1, 1, 1 * 1.125),        # deployed old queued servers send 1: about 1 Hz
    (-5, 1, 1 * 1.125),       # finite but negative: clamped to the floor
    (2.5, 10, 10 * 1.125),    # explicitly larger poll interval still wins over the cap
])
def test_finite_numeric_hint_is_clamped_and_jittered(tmp_path, clock, hint, poll, expected):
    server = Server(posts=[ack(retry_after=hint)],
                    gets=[pending(retry_after=hint), pending(retry_after=hint), pending(retry_after=hint), completed()])
    result, _ = invoke(tmp_path, server, seconds=120, service_poll_seconds=poll)
    assert result == {'domains': []}
    assert clock.sleeps == [pytest.approx(expected)] * 3


@pytest.mark.parametrize('hint', ['missing', None, True, False, 'x', math.nan, math.inf, -math.inf, [1], {},
    pytest.param(10**400, id='oversized-positive-integer'),
    pytest.param(-(10**400), id='oversized-negative-integer')])
def test_invalid_or_missing_hint_keeps_bounded_exponential_fallback(tmp_path, clock, hint):
    extra = {} if hint == 'missing' else {'retry_after': hint}
    server = Server(posts=[ack(**extra)], gets=[pending(**extra)] * 5 + [completed()])
    result, _ = invoke(tmp_path, server, seconds=120)
    assert result == {'domains': []}
    assert clock.sleeps == pytest.approx([1.125, 2.25, 4.5, 9.0, 9.0])


def test_valid_hint_resets_backoff_between_transient_status_errors(tmp_path, clock):
    limited = (429, {'error': 'request_rate_limited'})
    server = Server(posts=[ack(retry_after=1)],
                    gets=[limited, pending(retry_after=1), limited,
                          pending(retry_after=1), limited, completed()])
    result, outbox = invoke(tmp_path, server)
    assert result == {'domains': []} and outbox == []
    assert clock.sleeps == pytest.approx([1.125] * 5)


@pytest.mark.parametrize('jitter,expected', [(0.0, 4.0), (1.0, 5.0)])
def test_jitter_is_zero_to_twenty_five_percent(tmp_path, clock, jitter, expected):
    clock.jitter = jitter
    server = Server(posts=[ack(retry_after=4)], gets=[pending(retry_after=4), completed()])
    invoke(tmp_path, server)
    assert clock.sleeps == [pytest.approx(expected)]


def test_hint_sleep_is_clamped_to_caller_deadline_and_waiting_is_not_success(tmp_path, clock):
    server = Server(posts=[ack(retry_after=8)], gets=[pending(retry_after=8)] * 3)
    result, outbox = invoke(tmp_path, server, seconds=5)
    assert clock.sleeps == [pytest.approx(4.8)]
    assert result['waiting'] is True and result['state'] == 'pending' and result['request_id'] == RID
    assert 'result' not in result and len(outbox) == 1


def test_post_ack_permanent_error_returns_without_polling(tmp_path, clock):
    server = Server(posts=[ack(retry_after=1)], gets=[(403, {'error': 'authorization_changed'})] * 4)
    result, _ = invoke(tmp_path, server)
    assert clock.sleeps == []
    assert result['waiting'] is True and result['state'] == 'blocked' and result['code'] == 'authorization_changed'


@pytest.mark.parametrize('state', ['failed', 'cancelled', 'expired'])
def test_terminal_states_raise_immediately(tmp_path, clock, state):
    server = Server(posts=[ack()], gets=[(200, {'request_id': RID, 'state': state, 'durable': True, 'code': 'request_' + state})])
    with pytest.raises(RemoteError, match='request_' + state):
        invoke(tmp_path, server)
    assert clock.sleeps == []


# Pre-ACK transient contention and ambiguous timeouts.

@pytest.mark.parametrize('fault', [
    (429, {'error': 'request_rate_limited'}),
    (429, {'error': 'capacity_exceeded'}),
    (429, {'error': 'request_queue_full'}),
    (408, {'error': 'request_timeout'}),
    httpx.ReadTimeout('lost ack'),
    httpx.ConnectError('server restarting'),
])
def test_pre_ack_transient_retries_the_same_durable_envelope(tmp_path, clock, fault):
    server = Server(posts=[fault, fault, ack(retry_after=1)], gets=[completed()])
    result, outbox = invoke(tmp_path, server)
    assert result == {'domains': []} and outbox == []
    assert clock.sleeps == [pytest.approx(.3375), pytest.approx(.3375)]
    assert len(server.envelopes) == 3
    assert server.envelopes[0] == server.envelopes[1] == server.envelopes[2]
    assert set(server.envelopes[0]) == {'idempotency_key', 'created_at', 'tool', 'arguments'}


def test_pre_ack_retry_stops_at_deadline_and_keeps_the_handle(tmp_path, clock):
    server = Server(posts=[(429, {'error': 'request_rate_limited'})] * 10)
    cfg = config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(server)) as sender, RemoteClient(cfg, sender=sender) as remote:
        result = remote.invoke('memory_domains', {}, seconds=1)
        handle = result['request_id']
        assert remote.spool.request_record(handle)['server_id'] is None
    assert result['waiting'] is True and result['durable'] is False and handle.startswith('local.')
    assert len(server.envelopes) == 3 and sum(clock.sleeps) < 1
    assert clock.sleeps == [pytest.approx(.3375)] * 2
    # The retained handle later reconciles with the identical envelope.
    later = Server(posts=[ack()], gets=[completed()])
    with httpx.Client(transport=httpx.MockTransport(later)) as sender, RemoteClient(cfg, sender=sender) as remote:
        assert remote.request_status(handle)['state'] == 'completed'
    assert later.envelopes == [server.envelopes[0]]


def test_pre_ack_cancel_of_retained_handle_reconciles_then_cancels(tmp_path, clock):
    server = Server(posts=[(429, {'error': 'request_rate_limited'})] * 10)
    cfg = config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(server)) as sender, RemoteClient(cfg, sender=sender) as remote:
        handle = remote.invoke('memory_domains', {}, seconds=.5)['request_id']
    later = Server(posts=[ack()], gets=[(200, {'request_id': RID, 'state': 'cancelled', 'durable': True})])
    with httpx.Client(transport=httpx.MockTransport(later)) as sender, RemoteClient(cfg, sender=sender) as remote:
        assert remote.request_status(handle, cancel=True)['state'] == 'cancelled'
    assert later.paths[-1] == ('POST', f'/v1/requests/{RID}/cancel')


@pytest.mark.parametrize('fault', [
    (400, {'error': 'invalid_request'}),
    (403, {'error': 'scope_denied'}),
    (409, {'error': 'idempotency_conflict'}),
    (413, {'error': 'request_too_large'}),
    (500, {'error': 'request_failed'}),
    (503, {'error': 'incompatible_service_schema'}),
    (507, {'error': 'storage_low'}),
    (202, {'request_id': RID, 'state': 'pending'}),   # invalid receipt: not durable
    (200, b'not json'),                                # invalid response
])
def test_pre_ack_permanent_or_invalid_failures_are_not_retried(tmp_path, clock, fault):
    server = Server(posts=[fault] * 3, gets=[completed()])
    result, outbox = invoke(tmp_path, server)
    assert len(server.envelopes) == 1 and clock.sleeps == []
    assert result['waiting'] is True and result.get('state') != 'completed' and len(outbox) == 1


@pytest.mark.parametrize('capabilities', [
    lambda: httpx.Response(503, json={'error': 'unavailable'}),
    lambda: (_ for _ in ()).throw(httpx.ConnectError('offline')),
    lambda: httpx.Response(200, json={'protocol': 2}),
])
def test_negotiation_failure_is_not_retried(tmp_path, clock, capabilities):
    server = Server(capabilities=capabilities)
    result, outbox = invoke(tmp_path, server)
    assert server.paths == [('GET', '/v1/capabilities')] and clock.sleeps == []
    assert result['waiting'] is True and result['durable'] is False and len(outbox) == 1


@pytest.mark.parametrize('busy_replies', [1, 3])
def test_discovery_capacity_retry_completes_same_durable_request(tmp_path, clock, busy_replies):
    """A transient discovery-slot refusal must not strand a fresh queued client."""
    observed = []
    def discovery():
        rows = remote.spool.pending_requests()
        assert len(rows) == 1
        observed.append((rows[0]['id'], rows[0]['envelope']))
        if len(observed) <= busy_replies:
            return httpx.Response(429, json={'error': 'capacity_exceeded'})
        return httpx.Response(200, json={'protocol': 1, 'extensions': {'queued_tools': 1}})
    server = Server(posts=[ack()], gets=[completed()], capabilities=discovery)
    with httpx.Client(transport=httpx.MockTransport(server)) as sender, \
            RemoteClient(config(tmp_path), sender=sender) as remote:
        assert remote.invoke('memory_domains', {}) == {'domains': []}
        assert remote.spool.pending_requests() == []
    assert len(observed) == busy_replies + 1 and len(set(observed)) == 1
    assert server.envelopes == [json.loads(observed[0][1])]
    assert clock.sleeps == pytest.approx([.3375] * busy_replies)


def test_persistent_discovery_capacity_keeps_original_handle_at_deadline(tmp_path, clock):
    """Retry must stop at the caller deadline without duplicate staging or submission."""
    server = Server(capabilities=lambda: httpx.Response(429, json={'error': 'capacity_exceeded'}))
    result, outbox = invoke(tmp_path, server, seconds=.5)
    assert server.paths == [('GET', '/v1/capabilities')] * 2
    assert clock.sleeps == pytest.approx([.3375]) and clock.now <= 1000.5
    assert len(outbox) == 1 and result['request_id'] == outbox[0]['id']
    assert result['state'] == 'pending' and result['waiting'] is True and result['durable'] is False
    assert result['code'] == 'capacity_exceeded' and server.envelopes == []


@pytest.mark.parametrize('status,body', [(401, {'error': 'invalid_key'}), (403, {'error': 'scope_denied'}),
    (429, b'not-json'), (429, {'error': 'different_failure'})])
def test_other_discovery_errors_remain_immediate(tmp_path, clock, status, body):
    """The capacity fix must not retry authentication, malformed or unrelated failures."""
    server = Server(capabilities=lambda: Server.reply((status, body)))
    result, outbox = invoke(tmp_path, server)
    assert server.paths == [('GET', '/v1/capabilities')] and clock.sleeps == []
    assert result['waiting'] is True and result['durable'] is False and len(outbox) == 1


def test_legacy_synchronous_call_is_never_retried(tmp_path, clock):
    server = Server(posts=[(429, {'error': 'capacity_exceeded'}), (200, {'domains': []})], queued=False)
    with pytest.raises(RemoteError, match='capacity_exceeded'):
        invoke(tmp_path, server)
    assert [p for p in server.paths if p[1].startswith('/v1/tools/')] == [('POST', '/v1/tools/memory_domains')]
    assert clock.sleeps == []
