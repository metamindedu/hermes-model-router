import hermes_bootstrap
from legacy_router_engine import legacy_start
"""Native plugin dispatch -> real Router/adoption/observer, no model or network."""
from contextvars import Context
import importlib.util
import importlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from test_routing import FakeService


@pytest.mark.parametrize('spawn_fails', [False, True])
def test_messaging_dispatch_real_router_observer(tmp_path, monkeypatch, spawn_fails):
    from gateway import session_context
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.registry import ToolRegistry
    from tools.process_registry import ProcessRegistry
    from tools.environments.local import served_profile_child_env
    import tools.process_registry
    import tools.desktop_ui
    import hermes_cli.venv_sync

    root = tmp_path / 'hermes'
    home = root / 'profiles/wallace'
    home.mkdir(parents=True)
    (home / 'config.yaml').write_text('{}', encoding='utf8')
    fake_cli = tmp_path / 'hermes.exe'
    fake_cli.write_bytes(b'fixture - never executed')
    repo = Path(__file__).resolve().parents[1]
    name = 'router_full_gateway_fixture'
    spec = importlib.util.spec_from_file_location(name, repo / '__init__.py', submodule_search_locations=[str(repo)])
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, plugin)
    spec.loader.exec_module(plugin)
    service_module = importlib.import_module(name + '.model_router.service')
    routing = importlib.import_module(name + '.model_router.routing')
    output = importlib.import_module(name + '.model_router.background_output')
    monkeypatch.setattr(service_module, 'Service', lambda: FakeService(root, 'wallace'))
    monkeypatch.setattr(hermes_cli.venv_sync, 'prepare_launch', lambda *a, **k: None)
    monkeypatch.setattr(routing.shutil, 'which', lambda _: str(fake_cli))
    monkeypatch.setenv('HERMES_SESSION_ID', 'GLOBAL_PARENT_UNCHANGED')
    monkeypatch.setattr(tools.desktop_ui, '_emit', None)
    native = ProcessRegistry()
    monkeypatch.setattr(tools.process_registry, 'process_registry', native)
    observed = []
    saw_observer = Event()
    finished_observer = Event()
    original_run = output.BackgroundOutput.run
    def observe(self):
        try:
            observed.append((session_context.get_session_env('HERMES_SESSION_ID'), self.identity['parent_session_id'], self.session.parent_session_id))
            saw_observer.set()
            original_run(self)
        finally:
            finished_observer.set()
    monkeypatch.setattr(output.BackgroundOutput, 'run', observe)
    actual_popen = subprocess.Popen
    launches = []
    processes = []
    def launch(command, **kwargs):
        launches.append(command)
        if spawn_fails:
            raise OSError('fixture spawn failure')
        # This child is a stdlib timing stub, not a Hermes/dependency probe.
        # Windows venv forwarding launchers can remain alive with the routed
        # detached flags; use the same interpreter's base executable while
        # retaining every profile env, owner, deadline and exit assertion.
        fixture_python = (getattr(sys, '_base_executable', sys.executable)
                          if sys.platform == 'win32' else sys.executable)
        process = actual_popen([fixture_python, '-c', 'import time; time.sleep(0.4)'], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(routing.subprocess, 'Popen', launch)
    registry = ToolRegistry()
    ctx = SimpleNamespace(register_cli_command=lambda *a: None, register_skill=lambda *a: None,
        register_delegation_provider=lambda *a: None, register_hook=lambda *a: None, register_tool=lambda **kw: registry.register(**kw))
    def turn():
        token = set_hermes_home_override(home)
        tokens = session_context.set_session_vars(platform='telegram', session_key='fixture-lane', profile='wallace')
        try:
            plugin.register(ctx)
            runtime_module = importlib.import_module(name + '.model_router.runtime_tracking')
            with runtime_module.route_session_context(session_id='fixture-parent', expected_profile='wallace'):
                runtime = runtime_module.capture_runtime(task_id='fixture-owner', expected_profile='wallace')
                result = legacy_start(routing.Router(service_module.Service(), runtime=runtime),
                                      'mechanical', 'fixture only', str(tmp_path), 30)
            assert len(launches) == 1
            assert session_context.get_session_env('HERMES_SESSION_ID') == ''
            import os
            assert os.environ['HERMES_SESSION_ID'] == 'GLOBAL_PARENT_UNCHANGED'
            job = home / 'plugin-data/model-router/jobs' / result['job_id']
            assert json.loads((job / 'snapshot.json').read_text())['parent_session_id'] == 'fixture-parent'
            if spawn_fails:
                assert result['status'] == 'failed'
                assert observed == []
                assert 'process_id' not in result
            else:
                assert result['status'] == 'running'
                row = native.get(result['process_id'])
                assert row.parent_session_id == 'fixture-parent'
                assert row.session_key == 'fixture-lane'
                assert row.owner_task_id == 'fixture-owner'
                assert saw_observer.wait(5), result
                assert observed == [('fixture-parent', 'fixture-parent', 'fixture-parent')]
                assert finished_observer.wait(5)
                processes[0].wait(timeout=5)
                row._reader_thread.join(timeout=5)
                assert row.exited and row.exit_code == 0
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            session_context.clear_session_vars(tokens)
            reset_hermes_home_override(token)
    Context().run(turn)
