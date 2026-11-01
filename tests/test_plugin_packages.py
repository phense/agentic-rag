"""Native package ownership is independent of user settings and pending input."""
import json
import sys
import pytest


def test_native_packages_are_previewed_then_installed_and_preserve_foreign(tmp_path):
    from agentic_rag.plugins.package import manage
    for host,manifest in [('claude','.claude-plugin/plugin.json'),('codex','.codex-plugin/plugin.json'),('gemini','gemini-extension.json')]:
        target=tmp_path/host
        plan=manage(host,target,python=sys.executable)
        assert plan['preview'] and not target.exists()
        manage(host,target,python=sys.executable,apply=True)
        assert json.loads((target/manifest).read_text())['name']=='agentic-rag'
        assert len(json.loads((target/'hooks/hooks.json').read_text())['hooks'])>=5
        native=target/'foreign.txt';native.write_text('keep')
        manage(host,target,action='update',python=sys.executable,apply=True)
        assert manage(host,target,action='doctor')['status']=='ok'
        manage(host,target,action='uninstall',apply=True)
        assert native.read_text()=='keep' and not (target/manifest).exists()
        assert (target/'.rag-package.json').exists()


def test_modified_owned_file_blocks_update_and_uninstall(tmp_path):
    from agentic_rag.plugins.package import manage
    manage('claude',tmp_path,python=sys.executable,apply=True)
    hooks=tmp_path/'hooks/hooks.json';hooks.write_text('foreign change')
    for action in ('update','uninstall'):
        with pytest.raises(ValueError,match='conflict'):manage('claude',tmp_path,action=action,apply=True)
    assert hooks.read_text()=='foreign change'


def test_symlink_parent_is_not_written(tmp_path):
    from agentic_rag.plugins.package import manage
    outside=tmp_path/'outside';outside.mkdir()
    target=tmp_path/'plugin';target.mkdir();(target/'hooks').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):manage('claude',target,python=sys.executable,apply=True)
    assert list(outside.iterdir())==[]


def test_interrupted_update_and_uninstall_recover_owned_generation(tmp_path,monkeypatch):
    from agentic_rag.plugins import package
    package.manage('claude',tmp_path,apply=True)
    original={p:str((tmp_path/p).read_text()) for p in package.files('claude')}
    real=package._write;calls=[]
    def interrupted(path,data):
        real(path,data);calls.append(path)
        if len(calls)==2:raise RuntimeError('power loss after first file')
    monkeypatch.setattr(package,'_write',interrupted)
    with pytest.raises(RuntimeError):package.manage('claude',tmp_path,action='update',read_only=True,apply=True)
    monkeypatch.setattr(package,'_write',real)
    package.manage('claude',tmp_path,action='recover',apply=True)
    assert {p:(tmp_path/p).read_text() for p in original}==original
    assert package.manage('claude',tmp_path,action='doctor')['status']=='ok'
    # A partial uninstall is recoverable, but user edits are never overwritten.
    record=json.loads((tmp_path/package.RECORD).read_text());record['pending_files']={};record['recovery']=original
    (tmp_path/package.RECORD).write_text(json.dumps(record));(tmp_path/'hooks/hooks.json').unlink()
    package.manage('claude',tmp_path,action='recover',apply=True)
    assert (tmp_path/'hooks/hooks.json').read_text()==original['hooks/hooks.json']


@pytest.mark.parametrize('host,manifest', [('claude', '.claude-plugin/plugin.json'),
    ('codex', '.codex-plugin/plugin.json'), ('gemini', 'gemini-extension.json')])
def test_native_update_advertises_installed_release_without_resetting_foreign_files(tmp_path, host, manifest):
    # A hardcoded old version lets the native host cache an obsolete generation.
    from importlib.metadata import version
    from agentic_rag.plugins.package import manage
    manage(host, tmp_path, python=sys.executable, apply=True)
    foreign = tmp_path / 'foreign.txt'
    foreign.write_bytes(b'keep original bytes\n')
    manage(host, tmp_path, action='update', python=sys.executable, apply=True)
    assert json.loads((tmp_path / manifest).read_text())['version'] == version('agentic-rag')
    assert foreign.read_bytes() == b'keep original bytes\n'
