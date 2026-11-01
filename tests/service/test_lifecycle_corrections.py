"""Independent-review regressions: scoped lifecycle metadata and public paging."""
import json

import pytest
from starlette.testclient import TestClient

from agentic_rag import db, store
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection
from .test_api import KEYS, app_fixture
from .test_lifecycle_transports import call, lifecycle_store


@pytest.mark.parametrize('operation', ['exact_duplicate', 'replacement'])
def test_moved_member_does_not_grant_its_old_decision_scope(lifecycle_store, tmp_path, operation):
    cfg, ids = lifecycle_store
    member, target = ids['copy'], ids['keep']
    if operation == 'replacement':
        with db.connect(cfg) as owner:
            pair = []
            for n, when in enumerate(('2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z')):
                body = f'The NTP server is ntp{n + 1}.'
                pair.append(store.save_claim(owner, cfg, title=f'NTP observation {n}', body=body,
                    domain='alpha', dtype='memory', project='/projects/a', claim_kind='stated',
                    evidence=[{'namespace': 'session:corrections', 'source_id': f'ntp-{n}', 'role': 'user',
                               'quote': body, 'complete': True, 'timestamp': when}]).doc_id)
            member, target = pair
    app, policy = app_fixture(tmp_path, cfg)
    # The new-scope principal can read the moved domain at either project, but
    # cannot read alpha. Claims can move domains, not project applicability.
    policy.write_text(policy.read_text().replace('read_projects=["/projects/b"]',
                                                'read_projects=["/projects/a","/projects/b"]'))
    with TestClient(app, base_url='https://testserver') as client:
        status, seen = call(client, KEYS[0], 'memory_lifecycle_preview', member=member, target=target,
                            operation=operation)
        assert status == 200
        status, made = call(client, KEYS[0], 'memory_lifecycle_apply', member=member, target=target,
            operation=operation, expected_member_version=seen['member']['version'],
            expected_target_version=seen['target']['version'], reason='Alpha confidential tray two',
            reviewed=True, request_key='alpha-confidential-key')
        assert status == 200, made
        with db.connect(cfg) as owner:
            store.set_domain(owner, member, 'beta')
            if operation == 'exact_duplicate':
                store.set_project_scope(owner, member, project='/projects/b')
        principal = Principal(user_id='bob', machine_id='vm3', credential_id='synthetic',
            read_domains=frozenset({'beta'}), write_domains=frozenset({'beta'}),
            read_projects=frozenset({'/projects/a', '/projects/b'}),
            write_projects=frozenset({'/projects/b'}))
        with db.connect(cfg, role='reader') as reader:
            apply_connection(reader, RequestScope(principal, cfg, True))
            assert reader.execute('SELECT count(*) n FROM documents WHERE id=%s', (member,)).fetchone()['n'] == 1
            assert reader.execute('SELECT count(*) n FROM documents WHERE id=%s', (target,)).fetchone()['n'] == 0
            assert reader.execute('SELECT count(*) n FROM lifecycle_decisions').fetchone()['n'] == 0
            assert reader.execute('SELECT count(*) n FROM lifecycle_events').fetchone()['n'] == 0
            hidden = reader.execute('SELECT rag_lifecycle_hidden(%s) h', (member,)).fetchone()['h']
            assert hidden is (operation == 'replacement')
            # A boolean helper cannot reveal whether an invisible member has a
            # decision; guessing the original target is indistinguishable from missing.
            assert reader.execute('SELECT rag_lifecycle_hidden(%s) h', (target,)).fetchone()['h'] is False
        status, detail = call(client, KEYS[2], 'memory_lifecycle', id_or_slug=member, history=True)
        assert status == 200, detail
        encoded = json.dumps(detail)
        for forbidden in (target, made['decision']['id'], 'Alpha confidential', 'alpha-confidential-key',
                          'service:machine:alice:vm1', '"domain": "alpha"', '"project": "/projects/a"'):
            # A moved claim may itself still have project a; only relationship
            # metadata must not carry the foreign decision scope.
            if forbidden == '"project": "/projects/a"' and operation == 'replacement':
                continue
            assert forbidden not in encoded
        assert detail['history']['items'] == []
        if operation == 'replacement':
            assert detail['current'] is False
            assert detail['as_member'] == [{'relationship': 'suppressed', 'resolution': 'decision_unavailable'}]
            status, got = call(client, KEYS[2], 'memory_get', id_or_slug=member, view='current')
            assert status == 200 and got['document'] is None
            assert got['lifecycle']['resolution'] == 'decision_unavailable'


@pytest.mark.parametrize('same_domain', [False, True])
def test_request_keys_are_independent_between_scopes(lifecycle_store, tmp_path, same_domain):
    cfg, ids = lifecycle_store
    if same_domain:
        with db.connect(cfg) as owner:
            for name in ('foreign-copy', 'foreign-keep'):
                store.set_domain(owner, ids[name], 'alpha')
    app, policy = app_fixture(tmp_path, cfg)
    if same_domain:
        policy.write_text(policy.read_text().replace('read_domains=["beta"]', 'read_domains=["alpha"]')
                          .replace('write_domains=["beta"]', 'write_domains=["alpha"]'))
    replay_arguments = []
    with TestClient(app, base_url='https://testserver') as client:
        for key, member, target in ((KEYS[0], ids['copy'], ids['keep']),
                                    (KEYS[2], ids['foreign-copy'], ids['foreign-keep'])):
            status, seen = call(client, key, 'memory_lifecycle_preview', member=member, target=target)
            assert status == 200
            arguments = dict(member=member, target=target, operation='exact_duplicate', reason='same ticket',
                expected_member_version=seen['member']['version'], expected_target_version=seen['target']['version'],
                request_key='same-ticket')
            status, made = call(client, key, 'memory_lifecycle_apply', **arguments)
            assert status == 200, made
            assert call(client, key, 'memory_lifecycle_apply', **arguments)[1]['replayed'] is True
            assert call(client, key, 'memory_lifecycle_apply', **{**arguments, 'reason': 'different payload'}) == (
                409, {'error': 'replay_mismatch'})
            status, corrected = call(client, key, 'memory_lifecycle_correct', decision_id=made['decision']['id'],
                expected_revision=1, reason='same correction ticket', request_key='same-correction')
            assert status == 200, corrected
            replay_arguments.append(arguments)
    # The same scoped lookup is required for a local operator who sees all
    # domains/projects; relying only on RLS would match the first scope's key.
    with db.connect(cfg) as owner:
        for arguments in replay_arguments:
            result = store.apply_lifecycle(owner, cfg, **arguments)
            assert result['replayed'] is True and result['decision']['state'] == 'corrected'
