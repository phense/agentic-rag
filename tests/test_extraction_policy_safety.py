"""Consumer-visible safety boundaries for extraction drafts and sample evaluation."""
import json

import pytest

from agentic_rag import extraction_cli, extraction_policy


def test_sample_preserves_exact_multiline_quote(tmp_path):
    # Collapsing whitespace invents source wording before grounding/evaluation.
    text = 'The confirmed command is:\n  rag   service status\nKeep both spaces.'
    path = tmp_path / 'sample.json'
    path.write_text(json.dumps({'events': [{'role': 'user', 'text': text}]}))
    window, _ = extraction_cli._sample(path)
    assert window.events[0]['text'] == '[user] ' + text
    assert window.text == '[user] ' + text


@pytest.mark.parametrize('field', ['source_id', 'timestamp'])
def test_sample_rejects_secret_bearing_metadata_without_echo(tmp_path, field):
    # Metadata is sent as SOURCE EVENTS too, so sanitizing prose alone is insufficient.
    secret = 'sk-' + 'SyntheticOnlyKeyValueNotReal12345'
    event = {'role': 'user', 'text': 'A confirmed solution', field: secret}
    path = tmp_path / 'sample.json'
    path.write_text(json.dumps({'events': [event]}))
    with pytest.raises(extraction_cli.Refused) as error:
        extraction_cli._sample(path)
    assert secret not in str(error.value)


def test_unknown_policy_key_never_echoes_credential_into_errors():
    # TOML permits arbitrary quoted keys: locations must not expose key contents.
    secret = 'sk-' + 'SyntheticOnlyKeyValueNotReal12345'
    with pytest.raises(extraction_policy.PolicyError) as error:
        extraction_policy.validate_source('version = 1\n"' + secret + '" = true\n')
    assert secret not in str(error.value)
    assert secret not in json.dumps(error.value.errors)
    assert error.value.errors[0]['code'] == 'unknown_key'
