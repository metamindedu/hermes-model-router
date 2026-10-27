"""Retired public starts never read a prompt, create a job or spawn a worker."""
from pathlib import Path
import json
import pytest
from model_router.routing import Router
import importlib.util
import sys


def test_direct_router_start_is_retired_without_initialized_runtime(monkeypatch):
    import model_router.routing as routing
    monkeypatch.setattr(routing.subprocess, 'Popen', lambda *a, **k: pytest.fail('process spawned'))
    router = object.__new__(Router)
    result = router.start('independent-review', 'not persisted', 'missing-path', completion_mode='join')
    assert result['error'] == 'start_retired'
    assert not hasattr(Router, '_legacy_start')


def test_cli_retired_start_does_not_read_prompt(tmp_path, monkeypatch, capsys):
    import httpx
    import run_agent
    import model_router.routing as routing
    home = tmp_path / 'credential-free-home'
    home.mkdir()
    (home/'config.yaml').write_text('{}', encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    def forbidden(*args, **kwargs): pytest.fail('retired CLI attempted execution/network')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)
    monkeypatch.setattr(run_agent.AIAgent, 'run_conversation', forbidden)
    monkeypatch.setattr(routing.subprocess, 'Popen', forbidden)
    source = Path(__file__).resolve().parents[1] / 'cli.py'
    spec = importlib.util.spec_from_file_location('model_router_retired_cli_fixture', source)
    assert spec is not None and spec.loader is not None
    plugin_cli = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, plugin_cli)
    spec.loader.exec_module(plugin_cli)
    assert Path(plugin_cli.__file__).resolve() == source.resolve()
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        if str(path) == 'nonexistent': pytest.fail('prompt was read')
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    assert plugin_cli.main(['route', '--purpose', 'plan', '--prompt-file', 'nonexistent', '--cwd', 'nonexistent']) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'start_retired'
