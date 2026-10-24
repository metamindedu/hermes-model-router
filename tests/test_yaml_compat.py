"""Use the host's actual YAML policy without requiring removed core dependencies."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_native_runtime_reads_settings_without_pyyaml(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'config.yaml').write_text(json.dumps({
        'model': {'provider': 'openai-codex', 'default': 'fixture-shared'},
        'agent': {'reasoning_effort': 'medium'},
    }), encoding='utf-8')
    package = home / 'plugins/model-router'
    package.mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    program = """
import json, sys, importlib.abc
class NoLegacyYaml(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'yaml' or fullname.startswith('yaml.'):
            raise ModuleNotFoundError('PyYAML deliberately unavailable', name=fullname)
sys.meta_path.insert(0, NoLegacyYaml())
from pathlib import Path
from model_router.service import Service
s = Service(Path(sys.argv[1]))
status = s.status()
assert status['profiles'][0]['actual_models']['main']['model'] == 'fixture-shared'
assert status['profiles'][0]['routing']['enabled'] is True
assert s._loaded_cli_paths(), 'native config writes must retain the actual core/dependencies'
from model_router.yaml_compat import yaml
assert yaml.__name__ == 'hermes_yaml'
assert str(Path(yaml.__file__).resolve().parent.parent) not in s._loaded_cli_paths(), 'flat modules must not export their source parent as an import root'
print(json.dumps({'backend': yaml.__name__, 'enabled': s.routing_config('default')['enabled']}))
"""
    env = dict(os.environ, HERMES_HOME=str(home), PYTHONPATH=str(root))
    for name in ('PYTHONHOME', 'VIRTUAL_ENV', 'HERMES_PROFILE'):
        env.pop(name, None)
    result = subprocess.run([sys.executable, '-B', '-c', program, str(home)], env=env,
                            cwd=root, text=True, encoding='utf-8', capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'backend': 'hermes_yaml', 'enabled': True}
    assert not (home / 'plugin-data').exists()


def test_yaml_adapter_preserves_native_duplicate_key_rejection():
    from model_router.yaml_compat import yaml
    import pytest
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load('model: first\nmodel: second\n')


def test_adapter_uses_legacy_yaml_only_when_host_module_is_absent(monkeypatch):
    import importlib
    import runpy
    legacy = object()
    calls = []
    def load(name):
        calls.append(name)
        if name == 'hermes_yaml':
            raise ModuleNotFoundError("host absent", name='hermes_yaml')
        assert name == 'yaml'
        return legacy
    monkeypatch.setattr(importlib, 'import_module', load)
    path = Path(__file__).resolve().parents[1] / 'model_router/yaml_compat.py'
    assert runpy.run_path(str(path))['yaml'] is legacy
    assert calls == ['hermes_yaml', 'yaml']


def test_broken_host_yaml_dependency_does_not_fall_back(monkeypatch):
    import importlib
    import runpy
    import pytest
    calls = []
    def load(name):
        calls.append(name)
        raise ModuleNotFoundError('dependency absent', name='ruamel')
    monkeypatch.setattr(importlib, 'import_module', load)
    path = Path(__file__).resolve().parents[1] / 'model_router/yaml_compat.py'
    with pytest.raises(ModuleNotFoundError) as failed:
        runpy.run_path(str(path))
    assert failed.value.name == 'ruamel'
    assert calls == ['hermes_yaml']
