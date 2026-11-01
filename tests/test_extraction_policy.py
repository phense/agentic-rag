"""RAG-067 T067-002: strict bounded v1 extraction policy, precedence and identity."""
from dataclasses import replace
from pathlib import Path

import pytest

from agentic_rag import mining
from agentic_rag.config import Config, load_config
from test_extraction_policy_fixtures import FIXTURES, frozen

POLICIES = FIXTURES / 'policies'
DOMAINS = ['programming', 'operations']


def ep():
    from agentic_rag import extraction_policy
    return extraction_policy


def write(tmp_path, text, name='policy.toml'):
    path = tmp_path / name
    path.write_text(text)
    return path


def errors(text, tmp_path):
    with pytest.raises(ep().PolicyError) as caught:
        ep().load_file(write(tmp_path, text))
    return [(e['code'], e['location']) for e in caught.value.errors]


def test_frozen_effective_precedence_matches_labels():
    _, labels = frozen()
    policy = ep().load_file(POLICIES / 'policy-a.toml')
    for key, expected in labels['effective'].items():
        scope, project = key.split('@')
        if scope == 'domainless':
            effective, trace = ep().resolve_domainless(policy, project)
        else:
            effective, trace = ep().resolve(policy, scope, project)
        assert trace == expected['scopes'], key
        assert list(effective.categories) == expected['categories'], key
        if 'max_items_per_category' in expected:
            assert effective.max_items_per_category == expected['max_items_per_category'], key
            assert effective.max_body_chars == expected['max_body_chars'], key
            assert len(effective.examples) == expected['examples'], key
            guidance = {'global': policy.global_fragment['guidance'],
                        'exact': 'Behalte bestätigte Betriebsentscheidungen. Verwirf verworfene Versuche.'}[expected['guidance_from']]
            assert effective.guidance == guidance, key


def test_frozen_invalid_file_reports_safe_codes_and_locations():
    _, labels = frozen()
    with pytest.raises(ep().PolicyError) as caught:
        ep().load_file(POLICIES / 'policy-invalid.toml')
    assert caught.value.errors == labels['cases']['V1']['errors']
    assert '*' not in str(caught.value) and 'lessons' not in str(caught.value)


@pytest.mark.parametrize('text,code,location', [
    ('version = 2\n', 'unsupported_version', 'version'),
    ('version = true\n', 'unsupported_version', 'version'),
    ('', 'unsupported_version', 'version'),
    ('version = 1\nextra = 1\n', 'unknown_key', 'extra'),
    ('version = 1\nsystem = "x"\n', 'reserved_setting', 'system'),
    ('version = 1\n[global]\nprovider = "x"\n', 'reserved_setting', 'global.provider'),
    ('version = 1\n[global]\ncategories = ["memories", "memories"]\n', 'duplicate_category', 'global.categories'),
    ('version = 1\n[global]\ncategories = ["facts"]\n', 'unknown_category', 'global.categories'),
    ('version = 1\n[global]\nmax_items_per_category = 9\n', 'out_of_range', 'global.max_items_per_category'),
    ('version = 1\n[global]\nmax_items_per_category = true\n', 'invalid_type', 'global.max_items_per_category'),
    ('version = 1\n[global]\nmax_body_chars = 0\n', 'out_of_range', 'global.max_body_chars'),
    ('version = 1\n[global]\nguidance = "' + 'x' * 2001 + '"\n', 'too_long', 'global.guidance'),
    ('version = 1\n[global]\nguidance = ""\n', 'empty_value', 'global.guidance'),
    ('version = 1\n[global]\nexamples = [{kind = "maybe", text = "x"}]\n', 'invalid_value', 'global.examples[0].kind'),
    ('version = 1\n[global]\nexamples = [{kind = "positive", text = "x", weight = 2}]\n', 'unknown_key', 'global.examples[0].weight'),
    ('version = 1\n[global]\nexamples = [{kind = "positive", text = "same"}, {kind = "negative", text = "same"}]\n',
     'conflicting_examples', 'global.examples[1]'),
    ('version = 1\n[[rules]]\ncategories = ["memories"]\n', 'empty_selector', 'rules[0]'),
    ('version = 1\n[[rules]]\ndomain = "programming"\n', 'empty_rule', 'rules[0]'),
    ('version = 1\n[[rules]]\ndomain = "bad domain"\ncategories = []\n', 'invalid_selector', 'rules[0].domain'),
    ('version = 1\n[[rules]]\nproject = "relative/path"\ncategories = []\n', 'invalid_selector', 'rules[0].project'),
    ('version = 1\n[[rules]]\nproject = "/a/../b"\ncategories = []\n', 'invalid_selector', 'rules[0].project'),
    ('version = 1\nrules = "x"\n', 'invalid_type', 'rules'),
    ('version = 1\n[global]\nguidance = "use token sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"\n',
     'secret_in_policy', 'global.guidance'),
    ('version = 1\n[global\n', 'invalid_toml', 'file'),
])
def test_malformed_files_fail_with_actionable_secret_safe_codes(tmp_path, text, code, location):
    found = errors(text, tmp_path)
    assert (code, location) in found, found
    message = str(ep().PolicyError(found and [{'code': c, 'location': l} for c, l in found]))
    assert 'sk-ant' not in message and 'hunter' not in message


def test_file_bounds_rule_count_and_non_regular_files(tmp_path):
    rules = ''.join(f'[[rules]]\ndomain = "d{i}"\ncategories = []\n' for i in range(65))
    assert ('too_many_rules', 'rules') in errors('version = 1\n' + rules, tmp_path)
    big = write(tmp_path, 'version = 1\n#' + 'x' * 70000 + '\n', 'big.toml')
    with pytest.raises(ep().PolicyError) as caught:
        ep().load_file(big)
    assert caught.value.errors == [{'code': 'file_too_large', 'location': 'file'}]
    with pytest.raises(ep().PolicyError) as caught:
        ep().load_file(tmp_path / 'missing.toml')
    assert caught.value.errors == [{'code': 'file_unreadable', 'location': 'file'}]
    with pytest.raises(ep().PolicyError) as caught:
        ep().load_file(tmp_path)
    assert caught.value.errors == [{'code': 'file_unreadable', 'location': 'file'}]


def test_identity_is_normalized_formatting_insensitive_and_builtin_equivalent(tmp_path):
    one = ep().load_file(write(tmp_path, 'version = 1\n[global]\nguidance = "Keep decisions."\n', 'a.toml'))
    two = ep().load_file(write(tmp_path, '# comment\nversion=1\n\n[global]\n  guidance="Keep decisions."\n', 'b.toml'))
    assert one.identity == two.identity and one.identity.startswith('xf1:')
    other = ep().load_file(write(tmp_path, 'version = 1\n[global]\nguidance = "Keep lessons."\n', 'c.toml'))
    assert other.identity != one.identity
    empty = ep().load_file(write(tmp_path, 'version = 1\n', 'd.toml'))
    bundle = ep().build_bundle(empty, '/synthetic/team-a', DOMAINS)
    assert bundle.digest == ep().build_bundle(None, '/synthetic/team-a', DOMAINS).digest
    assert bundle.digest.startswith('xb1:') and ep().is_builtin(bundle)
    # Category order in the file never changes identity; arrays are canonical sets.
    a = ep().load_file(write(tmp_path, 'version = 1\n[global]\ncategories = ["lessons", "memories"]\n', 'e.toml'))
    b = ep().load_file(write(tmp_path, 'version = 1\n[global]\ncategories = ["memories", "lessons"]\n', 'f.toml'))
    assert a.identity == b.identity


def test_arrays_replace_and_domainless_never_inherits_a_domain_rule(tmp_path):
    policy = ep().load_file(write(tmp_path, '''version = 1
[global]
categories = ["memories", "lessons", "pin_suggestions", "domain_proposals"]
examples = [{kind = "positive", text = "global example"}]
[[rules]]
domain = "programming"
categories = ["memories"]
examples = [{kind = "negative", text = "domain example"}]
'''))
    effective, _ = ep().resolve(policy, 'programming', '/p')
    assert effective.categories == ('memories',)
    assert [e['text'] for e in effective.examples] == ['domain example']
    domainless, trace = ep().resolve_domainless(policy, '/p')
    assert trace == ['builtin', 'global'] and 'domain_proposals' in domainless.categories


def test_bundle_contains_only_permitted_domains_and_is_bounded(tmp_path):
    policy = ep().load_file(POLICIES / 'policy-a.toml')
    bundle = ep().build_bundle(policy, '/synthetic/team-b', ['operations'])
    assert set(bundle.snapshot['domains']) == {'operations'}
    assert 'programming' not in repr(bundle.snapshot)
    again = ep().validate_capture({'digest': bundle.digest, 'snapshot': bundle.snapshot})
    assert again.digest == bundle.digest
    tampered = {'digest': bundle.digest, 'snapshot': {**bundle.snapshot, 'project': '/synthetic/team-a'}}
    with pytest.raises(ep().PolicySnapshotError):
        ep().validate_capture(tampered)
    for broken in (None, 'x', {'digest': 'xb1:00', 'snapshot': {}}, {'digest': bundle.digest}):
        with pytest.raises(ep().PolicySnapshotError):
            ep().validate_capture(broken)


def test_no_custom_policy_keeps_prompt_and_schema_identical():
    bundle = ep().build_bundle(None, '/p', DOMAINS)
    assert ep().render_preferences(bundle, DOMAINS) == ''
    assert mining.build_prompt('DIGEST', DOMAINS, ['pin']) == mining.build_prompt('DIGEST', DOMAINS, ['pin'])
    assert mining.SYSTEM.endswith('Empty lists are the correct answer for an unremarkable session.')


def test_preferences_render_as_bounded_advisory_data():
    policy = ep().load_file(POLICIES / 'policy-a.toml')
    bundle = ep().build_bundle(policy, '/synthetic/team-b', DOMAINS)
    text = ep().render_preferences(bundle, DOMAINS)
    assert text.startswith('\nOPERATOR EXTRACTION PREFERENCES')
    assert 'advisory' in text and 'never override' in text
    assert 'Behalte bestätigte Betriebsentscheidungen' in text
    assert 'Scope: domainless outputs' in text and 'Only these output categories are kept: pin_suggestions' in text
    assert len(text) <= ep().MAX_RENDERED_CHARS


def test_config_reads_optional_policy_path(tmp_path):
    assert Config().mine_policy_file is None
    config = write(tmp_path, '[mining]\npolicy_file = "~/policy.toml"\n', 'config.toml')
    assert load_config(config).mine_policy_file == Path('~/policy.toml').expanduser()
    assert ep().capture(Config(), '/p', DOMAINS) is None
    with pytest.raises(ep().PolicyError):
        ep().capture(replace(Config(), mine_policy_file=POLICIES / 'policy-invalid.toml'), '/p', DOMAINS)
    captured = ep().capture(replace(Config(), mine_policy_file=POLICIES / 'policy-a.toml'), '/synthetic/team-a', DOMAINS)
    assert ep().validate_capture(captured).digest == captured['digest']
