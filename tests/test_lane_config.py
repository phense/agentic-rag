"""Issue92 A2 typed optional settings: unset keeps every existing default.

Settings are loaded from real TOML files. Before A2 the loader silently ignores
unknown keys, so these tests fail on behavior (accepted credentials, missing
values), not merely on an unknown constructor argument.
"""
import math

import pytest

from agentic_rag.config import Config, load_config


def load(tmp_path, text):
    path = tmp_path / 'config.toml'
    path.write_text(text)
    return load_config(path)


def test_unset_lane_and_thread_settings_keep_existing_defaults(tmp_path):
    # Characterization: no new key changes the default single-lane runtime.
    cfg = load(tmp_path, '[ollama]\nurl = "http://127.0.0.1:11434"\n')
    assert cfg.ollama_url == 'http://127.0.0.1:11434'
    assert Config().ollama_url == 'http://localhost:11434'
    assert getattr(cfg, 'ollama_background_url', None) is None
    assert getattr(cfg, 'ollama_num_thread', None) is None


def test_reference_lane_configuration_loads_typed_values(tmp_path):
    cfg = load(tmp_path, '[ollama]\nurl = "http://127.0.0.1:11434"\n'
               'background_url = "http://127.0.0.1:11436"\nbackground_timeout_seconds = 60\n'
               'num_thread = 2\nbackground_num_thread = 1\n[service]\nrequest_consumers = 4\n')
    assert cfg.ollama_background_url == 'http://127.0.0.1:11436'
    assert cfg.ollama_background_timeout_seconds == 60
    assert cfg.ollama_num_thread == 2
    assert cfg.ollama_background_num_thread == 1
    assert cfg.service_request_consumers == 4


def test_enabled_lane_defaults_to_sixty_seconds_and_two_consumers(tmp_path):
    cfg = load(tmp_path, '[ollama]\nbackground_url = "https://lane.example:11436"\n')
    from agentic_rag.embed import background_timeout
    assert background_timeout(cfg) == 60.0
    assert cfg.service_request_consumers == 2
    assert load(tmp_path, '').service_request_consumers == 2


@pytest.mark.parametrize('text', [
    # Credentials, query or fragment must never be accepted (or later logged).
    'background_url = "http://user:secret@127.0.0.1:11436"',
    'background_url = "http://127.0.0.1:11436/?token=secret"',
    'background_url = "http://127.0.0.1:11436/#frag"',
    'background_url = "ftp://127.0.0.1:11436"',
    'background_url = "http://:11436"',
    'background_url = "http://127.0.0.1:notaport"',
    'background_url = ""',
    'background_url = 11436',
    # The lane must be a separate daemon, not a second lock on the primary.
    'url = "http://127.0.0.1:11434"\nbackground_url = "http://127.0.0.1:11434/"',
    # Background-only settings are invalid without the lane.
    'background_timeout_seconds = 30',
    'background_num_thread = 1',
    # Finite bounded timeout, booleans rejected.
    'background_url = "http://127.0.0.1:11436"\nbackground_timeout_seconds = 9.99',
    'background_url = "http://127.0.0.1:11436"\nbackground_timeout_seconds = 61',
    'background_url = "http://127.0.0.1:11436"\nbackground_timeout_seconds = nan',
    'background_url = "http://127.0.0.1:11436"\nbackground_timeout_seconds = inf',
    'background_url = "http://127.0.0.1:11436"\nbackground_timeout_seconds = true',
    # Integer thread counts 1..8 only.
    'num_thread = 0', 'num_thread = 9', 'num_thread = 2.0', 'num_thread = true',
    'background_url = "http://127.0.0.1:11436"\nbackground_num_thread = 0',
    'background_url = "http://127.0.0.1:11436"\nbackground_num_thread = 9',
    'background_url = "http://127.0.0.1:11436"\nbackground_num_thread = false',
])
def test_invalid_lane_settings_are_rejected_before_work(tmp_path, text):
    with pytest.raises(ValueError):
        load(tmp_path, '[ollama]\n' + text + '\n')


@pytest.mark.parametrize('value', ['0', '5', '2.0', 'true', '"2"', '-1'])
def test_request_consumers_are_bounded_integers(tmp_path, value):
    with pytest.raises(ValueError):
        load(tmp_path, f'[service]\nrequest_consumers = {value}\n')


@pytest.mark.parametrize('value', [1, 2, 3, 4])
def test_request_consumer_range_accepts_one_to_four(tmp_path, value):
    assert load(tmp_path, f'[service]\nrequest_consumers = {value}\n').service_request_consumers == value


def test_boundary_timeouts_are_accepted(tmp_path):
    for value in ('10', '60', '45.5'):
        cfg = load(tmp_path, '[ollama]\nbackground_url = "http://127.0.0.1:11436"\n'
                   f'background_timeout_seconds = {value}\n')
        assert math.isclose(cfg.ollama_background_timeout_seconds, float(value))
