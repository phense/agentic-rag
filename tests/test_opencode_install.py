import pytest
from agentic_rag.integrations.opencode.install import install

def test_check_install_uninstall_preserve_other_files(tmp_path):
    root=tmp_path.resolve()/'configuration'
    assert 'Would install' in install(config_dir=root,check=True)
    assert not root.exists()
    root.mkdir();other=root/'opencode.jsonc';other.write_bytes(b'// unchanged\n{}')
    install(config_dir=root)
    loader=root/'plugins/agentic-rag.js';before=loader.read_bytes()
    install(config_dir=root);assert loader.read_bytes()==before
    install(config_dir=root,uninstall=True,check=True);assert loader.exists()
    install(config_dir=root,uninstall=True);assert not loader.exists()
    assert other.read_bytes()==b'// unchanged\n{}'

def test_modified_and_symlinked_loaders_refused(tmp_path):
    root=tmp_path.resolve()/'config';install(config_dir=root)
    p=root/'plugins/agentic-rag.js';modified=p.read_bytes().replace(b'\n',b'\r\n');p.write_bytes(modified)
    for kwargs in ({},{'uninstall':True},{'check':True}):
        with pytest.raises(ValueError):install(config_dir=root,**kwargs)
        assert p.read_bytes()==modified
    p.unlink();p.symlink_to(tmp_path/'absent')
    with pytest.raises(ValueError):install(config_dir=root)

def test_symlinked_config_and_cli_target_conflicts(tmp_path):
    import subprocess,sys
    target=tmp_path/'real';target.mkdir();linked=tmp_path/'linked';linked.symlink_to(target)
    with pytest.raises(ValueError):install(config_dir=linked)
    r=subprocess.run([sys.executable,'-m','agentic_rag.cli','install','--opencode','--codex'],capture_output=True,text=True)
    assert r.returncode==2
