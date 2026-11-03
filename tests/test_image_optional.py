"""RAG-070: Pillow is an optional extra; text features never depend on it.

Characterization test added after implementation (not a red-first test): a fresh
interpreter that cannot import PIL still imports the CLI, service, upgrade and
image modules, and the child decoder reports exit 4 (`decoder_unavailable`).
"""
import subprocess
import sys

BLOCKED = r'''
import sys
sys.modules['PIL'] = None  # any `import PIL...` now raises ImportError
from agentic_rag import cli, images, image_backfill, image_cli, image_engines, image_media
from agentic_rag.service import api, upgrade
from agentic_rag import image_decode
assert 'PIL' not in {name.split('.')[0] for name, module in sys.modules.items() if module is not None}
print(image_decode.main(['decode', sys.argv[1], '1000']))
'''


def test_without_pillow_modules_import_and_decoder_is_unavailable(tmp_path):
    sample = tmp_path / 'any.png'
    sample.write_bytes(b'\x89PNG\r\n\x1a\n')
    result = subprocess.run([sys.executable, '-c', BLOCKED, str(sample)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip().splitlines()[-1] == '4'
