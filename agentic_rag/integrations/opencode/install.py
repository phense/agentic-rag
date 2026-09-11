"""Own one OpenCode loader; never parse or rewrite host/provider configuration."""
import json
import os
from pathlib import Path
import sys
from .hooks import plain_parents


def install(*, config_dir=None, check=False, uninstall=False, python=None):
    root = config_dir or os.environ.get('OPENCODE_CONFIG_DIR') or (
        Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'opencode')
    root = Path(os.path.abspath(Path(root).expanduser()))
    target = root / 'plugins' / 'agentic-rag.js'
    plain_parents(target.parent)
    # Do not resolve the interpreter symlink: the virtualenv identity is required.
    executable = str(Path(python or sys.executable).absolute())
    module = Path(__file__).resolve().with_name('plugin.mjs')
    content = ('// Managed by agentic-rag install --opencode.\n'
               'import { createPlugin } from ' + json.dumps(module.as_uri()) + ';\n'
               'export default ctx => createPlugin(ctx, {python: ' + json.dumps(executable) + '});\n').encode()
    if target.is_symlink():
        raise ValueError('refusing symlinked OpenCode loader')
    exists = target.exists()
    if exists and (not target.is_file() or target.read_bytes() != content):
        raise ValueError('refusing foreign or modified OpenCode loader')
    if uninstall:
        if exists and not check:
            target.unlink()
        return ('Would remove: ' if check else 'Removed: ') + str(target) if exists else 'Not installed.'
    if not module.is_file() or not Path(executable).is_file():
        raise ValueError('OpenCode adapter module or interpreter unavailable')
    if exists:
        return 'Already installed: ' + str(target)
    if check:
        return 'Would install: ' + str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    plain_parents(target.parent)
    with target.open('xb') as output:
        output.write(content)
    return 'Installed: ' + str(target)
