import importlib.util
import json
from pathlib import Path
import sys
from core.app_paths import runtime_root


def test_source_paths_unchanged_without_packaging(monkeypatch):
    monkeypatch.delenv('JARVIS_PACKAGED', raising=False)
    monkeypatch.delenv('JARVIS_DATA_DIR', raising=False)
    monkeypatch.delattr(sys,'frozen',raising=False)
    assert runtime_root()==Path(__file__).resolve().parents[1]


def test_frozen_state_never_uses_installation_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setenv('JARVIS_DATA_DIR',str(tmp_path/'private'))
    assert runtime_root()==tmp_path/'private'


def test_export_omits_credentials_notes_graph_and_artifacts(tmp_path):
    path=Path(__file__).resolve().parents[1]/'packaging/export_source.py'
    spec=importlib.util.spec_from_file_location('export_source_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ('main.py','config.json','config/api_keys.json','memory/long_term.json','notes/private.md','viewer/graph-data.js','viewer/app.js','.artifacts/report.md','core/example.py'):
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('private' if 'json' in name else 'source')
    selected={p.relative_to(tmp_path).as_posix() for p in module.sources(tmp_path)}
    assert selected=={'main.py','viewer/app.js','core/example.py'}


def test_bootstrap_preserves_existing_configuration(monkeypatch,tmp_path):
    from desktop import prepare_runtime
    monkeypatch.setenv('JARVIS_DATA_DIR',str(tmp_path));monkeypatch.delattr(sys,'frozen',raising=False)
    monkeypatch.chdir(tmp_path)
    config=tmp_path/'config.json';config.write_text('{"existing":"keep"}')
    prepare_runtime()
    assert json.loads(config.read_text())=={'existing':'keep'}


def test_portable_bootstrap_updates_code_but_preserves_private_data(monkeypatch, tmp_path):
    from desktop import prepare_runtime
    bundle, private = tmp_path/'installed', tmp_path/'user-data'
    (bundle/'app-source/core').mkdir(parents=True)
    (bundle/'app-source/core/worker.py').write_text('new version')
    (bundle/'app-manifest.json').write_text('["core/worker.py"]')
    private.mkdir()
    (private/'config.json').write_text('{"private":true}')
    (private/'notes').mkdir()
    (private/'notes/private.md').write_text('my private note')
    monkeypatch.delattr(sys,'frozen',raising=False)
    monkeypatch.setenv('JARVIS_PACKAGED','1')
    monkeypatch.setenv('JARVIS_RESOURCE_DIR',str(bundle))
    monkeypatch.setenv('JARVIS_DATA_DIR',str(private))
    monkeypatch.chdir(tmp_path)
    assert prepare_runtime() == private
    assert (private/'core/worker.py').read_text() == 'new version'
    assert json.loads((private/'config.json').read_text()) == {'private':True}
    assert (private/'notes/private.md').read_text() == 'my private note'
    assert not (bundle/'config.json').exists()


def test_portable_runtime_uses_user_directory(monkeypatch, tmp_path):
    monkeypatch.delattr(sys,'frozen',raising=False)
    monkeypatch.delenv('JARVIS_DATA_DIR',raising=False)
    monkeypatch.setenv('JARVIS_PACKAGED','1')
    monkeypatch.setattr(sys,'platform','linux')
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path))
    assert runtime_root()==tmp_path/'jarvis-agent'
