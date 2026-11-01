"""RAG-067 T067-001: the frozen extraction-policy fixtures stay byte-identical."""
from hashlib import sha256
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / 'docs/benchmarks/2026-11-01-extraction-policy/fixtures'


def frozen():
    """Verify every listed checksum, then return the parsed cases and labels."""
    listed = {}
    for line in (FIXTURES / 'FROZEN.sha256').read_text().splitlines():
        digest, name = line.split(None, 1)
        listed[name.strip()] = digest
    for name, digest in listed.items():
        assert sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, f'frozen fixture changed: {name}'
    present = {str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob('*') if p.is_file() and p.name != 'FROZEN.sha256'}
    assert present == set(listed), present ^ set(listed)
    return json.loads((FIXTURES / 'cases.json').read_text()), json.loads((FIXTURES / 'labels.json').read_text())


def test_frozen_fixtures_are_intact_and_labelled():
    cases, labels = frozen()
    assert set(cases['cases']) == set(labels['cases']) == {'R1', 'L1', 'D1', 'S1', 'P1', 'Z1', 'V1'}
    languages = {'DE' if 'ä' in json.dumps(c, ensure_ascii=False) else 'EN' for c in cases['cases'].values()}
    assert languages == {'EN', 'DE'}
