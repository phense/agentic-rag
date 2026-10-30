"""Credential-derived scopes must survive spoofed identity/filter arguments."""
import os

import pytest


def policy_file(tmp_path):
    # Imports are inside tests so the red state exercises the missing capability.
    from agentic_rag.service.auth import hash_key, hash_password
    p = tmp_path / 'principals.toml'
    p.write_text(f'''version = 1
[users.alice]
password = "{hash_password('correct horse synthetic password')}"
read_domains = ["general", "alpha"]
write_domains = ["alpha"]
read_projects = ["global", "/projects/a"]
write_projects = ["/projects/a"]
[users.admin]
password = "{hash_password('synthetic administrator password')}"
admin = true
read_domains = ["*"]
write_domains = ["*"]
read_projects = ["*"]
write_projects = ["*"]
[machines.vm1]
user = "alice"
label = "First synthetic VM"
read_domains = ["alpha"]
write_domains = ["alpha"]
read_projects = ["/projects/a"]
write_projects = ["/projects/a"]
keys = {{one = "{hash_key('one.synthetic-long-random-machine-secret')}"}}
[machines.vm2]
user = "alice"
read_domains = ["general"]
write_domains = []
read_projects = ["global"]
write_projects = []
keys = {{two = "{hash_key('two.synthetic-different-machine-secret')}"}}
''')
    p.chmod(0o600)
    return p


def test_key_identity_and_scopes_come_only_from_protected_policy(tmp_path):
    from agentic_rag.service.auth import Policy
    policy = Policy.load(policy_file(tmp_path))
    a = policy.authenticate_key('one.synthetic-long-random-machine-secret')
    b = policy.authenticate_key('two.synthetic-different-machine-secret')
    assert (a.user_id, a.machine_id, a.admin) == ('alice', 'vm1', False)
    assert a.can_read('alpha', '/projects/a')
    assert a.can_write('alpha', '/projects/a')
    assert not a.can_read('general', 'global')  # machine narrows user
    assert not a.can_write('alpha', '/projects/a/foreign')
    assert b.can_read('general', 'global') and b.readonly
    assert not b.can_read('alpha', '/projects/a')
    assert a.namespace != b.namespace  # same user/session on different VMs


def test_revocation_reload_and_uniform_bad_credentials(tmp_path):
    from agentic_rag.service.auth import Policy, AuthenticationError
    p = policy_file(tmp_path)
    for bad in ['', 'one.wrong', 'unknown.secret', 'Bearer one.synthetic-long-random-machine-secret']:
        with pytest.raises(AuthenticationError, match='invalid credentials'):
            Policy.load(p).authenticate_key(bad)
    p.write_text(p.read_text().replace('[machines.vm1]', '[machines.vm1]\nenabled = false'))
    with pytest.raises(AuthenticationError, match='invalid credentials'):
        Policy.load(p).authenticate_key('one.synthetic-long-random-machine-secret')


def test_password_login_is_separate_from_machine_identity(tmp_path):
    from agentic_rag.service.auth import Policy, AuthenticationError
    policy = Policy.load(policy_file(tmp_path))
    admin = policy.authenticate_password('admin', 'synthetic administrator password')
    assert admin.admin and admin.machine_id is None and admin.user_id == 'admin'
    for user, password in [('admin', 'bad'), ('missing', 'bad')]:
        with pytest.raises(AuthenticationError, match='invalid credentials'):
            policy.authenticate_password(user, password)


def test_policy_fails_closed_for_exposed_or_invalid_configuration(tmp_path):
    from agentic_rag.service.auth import Policy
    p = policy_file(tmp_path)
    if os.name != 'nt':
        p.chmod(0o644)
        with pytest.raises(ValueError, match='permissions'):
            Policy.load(p)
        p.chmod(0o600)
    p.write_text(p.read_text().replace('version = 1', 'version = 2'))
    with pytest.raises(ValueError, match='version'):
        Policy.load(p)
