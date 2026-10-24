"""Native PluginManager registration in a credential-free child runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_native_manager_registers_route_tool_and_policy_without_yaml_dependency(tmp_path):
    source = Path(__file__).resolve().parents[1]
    home = tmp_path / 'home'
    package = home / 'plugins/model-router'
    shutil.copytree(source, package, ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__', '.hermes-catalog.json'))
    (home / 'config.yaml').write_text(json.dumps({
        'plugins': {'enabled': ['model-router']},
        'model': {'provider': 'openai-codex', 'default': 'fixture-shared'},
        'agent': {'reasoning_effort': 'medium'},
    }), encoding='utf-8')
    program = """
import json, sys, importlib.abc
class NoLegacyYaml(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'yaml' or fullname.startswith('yaml.'):
            raise ModuleNotFoundError('PyYAML deliberately unavailable', name=fullname)
sys.meta_path.insert(0, NoLegacyYaml())
from hermes_cli.plugins import get_plugin_manager
from tools.registry import registry
manager = get_plugin_manager()
manager.discover_and_load()
loaded = manager._plugins['model-router']
assert loaded.enabled and not loaded.error, loaded.error
entry = registry.get_entry('coding_route', scope=manager.scope_key)
assert entry is not None
assert entry.check_fn()
config = json.loads(entry.handler({'action': 'config'}))
assert config['enabled'] is True
assert config['heavy']['model'] == config['light']['model'] == 'fixture-shared'
assert manager.find_plugin_skill('model-router:adaptive-coding-orchestration').is_file()
print('REGISTRATION:' + json.dumps({'registered': True, 'enabled': True}))
"""
    env = dict(os.environ, HERMES_HOME=str(home))
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'HERMES_PROFILE'):
        env.pop(key, None)
    result = subprocess.run([sys.executable, '-B', '-c', program], env=env, cwd=source,
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr[-3000:]
    lines = [line for line in result.stdout.splitlines() if line.startswith('REGISTRATION:')]
    assert json.loads(lines[-1].split(':', 1)[1]) == {'registered': True, 'enabled': True}
    assert not (home / 'plugin-data').exists()
