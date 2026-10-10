"""Regression: cached messaging turns clear ID but dispatcher supplies it."""
from contextvars import Context
import importlib.util
import json
from pathlib import Path
import sys
import pytest
from types import SimpleNamespace

from gateway import session_context
from tools.registry import ToolRegistry


@pytest.mark.parametrize('surface,allowed', [
    ({'platform': 'telegram'}, True),
    ({'platform': 'telegram', 'source': 'desktop'}, False),
    ({'source': 'desktop'}, False),
    ({'platform': 'telegram', 'source': 'cli'}, False),
])
def test_cached_telegram_dispatch_retains_native_process_parent(monkeypatch, surface, allowed):
    root = Path(__file__).resolve().parents[1]
    name = 'gateway_router_regression'
    spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, plugin)
    spec.loader.exec_module(plugin)
    from importlib import import_module
    service = import_module(name + '.model_router.service')
    routing = import_module(name + '.model_router.routing')
    runtime = import_module(name + '.model_router.runtime_tracking')
    registry = ToolRegistry()
    observed = []
    class Service:
        def routing_config(self, profile): return {'enabled': True}
        def active_profile(self): return 'wallace'
    class Router:
        def __init__(self, service, *, runtime=None, fast_snapshot=None):
            self.runtime = runtime
            assert fast_snapshot is None  # fake context exposes no Fast controller authority
        def start(self, *args, **kwargs):
            observed.append((self.runtime.parent_session_id, self.runtime.session_key,
                             session_context.get_session_env('HERMES_SESSION_ID')))
            return {'status': 'running'}
    monkeypatch.setattr(service, 'Service', Service)
    monkeypatch.setattr(routing, 'Router', Router)
    import tools.process_registry
    monkeypatch.setattr(tools.process_registry, 'process_registry', SimpleNamespace(adopt_local=lambda *a, **k: None))
    monkeypatch.setenv('HERMES_SESSION_ID', 'FOREIGN_GLOBAL_PARENT')
    ctx = SimpleNamespace(register_cli_command=lambda *a: None, register_skill=lambda *a: None,
        register_hook=lambda *a: None, register_tool=lambda **kw: registry.register(**kw))
    plugin.register(ctx)
    def turn():
        tokens = session_context.set_session_vars(**surface, profile='wallace', session_key='telegram:wallace:fixture')
        try:
            result = json.loads(registry.dispatch('coding_route', {'action': 'start', 'purpose': 'mechanical', 'prompt': 'fixture', 'cwd': str(root)}, task_id='task-fixture', session_id='fixture-current-parent'))
            if allowed:
                assert result == {'status': 'running'}, result
                assert observed == [('fixture-current-parent', 'telegram:wallace:fixture', 'fixture-current-parent')]
            else:
                assert result['error'] == 'invalid_or_denied'
                assert observed == []
            assert session_context.get_session_env('HERMES_SESSION_ID') == ''
        finally:
            session_context.clear_session_vars(tokens)
    Context().run(turn)


import pytest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from model_router.runtime_tracking import route_session_context, capture_runtime


@pytest.mark.parametrize('bindings,sid', [
    ({}, 'parent'),
    ({'platform': 'telegram', 'profile': 'wallace'}, 'parent'),
    ({'platform': 'telegram', 'session_key': 'lane'}, 'parent'),
    ({'platform': 'telegram', 'profile': 'other', 'session_key': 'lane'}, 'parent'),
    ({'platform': 'desktop', 'profile': 'wallace', 'session_key': 'lane'}, 'parent'),
    ({'platform': 'telegram', 'profile': 'wallace', 'session_key': 'lane', 'ui_session_id': 'foreign-ui'}, 'parent'),
    ({'platform': 'cli', 'profile': 'wallace', 'session_key': 'lane'}, 'parent'),
    ({'platform': 'telegram', 'profile': 'wallace', 'session_key': 'lane\n'}, 'parent'),
    ({'platform': 'telegram', 'profile': 'wallace', 'session_key': 'lane'}, '../bad'),
    ({'platform': 'telegram', 'profile': 'wallace', 'session_key': 'lane'}, 123),
    ({'platform': 'telegram', 'profile': 'wallace', 'session_key': 'lane', 'session_id': 'other-parent'}, 'parent'),
])
def test_dispatch_identity_does_not_repair_foreign_or_incomplete_lane(bindings, sid):
    def turn():
        tokens = session_context.set_session_vars(**bindings)
        try:
            with pytest.raises(ValueError):
                with route_session_context(session_id=sid, expected_profile='wallace'):
                    pytest.fail('unsafe context admitted')
        finally:
            session_context.clear_session_vars(tokens)
    Context().run(turn)


def test_cleared_or_unbound_context_cannot_use_dispatch_or_global_identity(monkeypatch):
    monkeypatch.setenv('HERMES_SESSION_ID', 'GLOBAL_PARENT')
    monkeypatch.setenv('HERMES_SESSION_PLATFORM', 'telegram')
    monkeypatch.setenv('HERMES_SESSION_KEY', 'GLOBAL_LANE')
    monkeypatch.setenv('HERMES_SESSION_PROFILE', 'wallace')
    def check():
        with pytest.raises(ValueError):
            with route_session_context(session_id='parent', expected_profile='wallace'):
                pytest.fail('unbound context admitted')
    Context().run(check)
    def cleared():
        tokens = session_context.set_session_vars(platform='telegram', session_key='lane', profile='wallace')
        session_context.clear_session_vars(tokens)
        check()
    Context().run(cleared)


@pytest.mark.parametrize('platform', ['telegram', 'discord', 'slack'])
def test_messaging_scope_restores_on_failure_and_copies_observer_identity(platform, monkeypatch):
    monkeypatch.setenv('HERMES_SESSION_ID', 'GLOBAL_PARENT')
    def turn():
        tokens = session_context.set_session_vars(platform=platform, session_key='lane', profile='wallace')
        try:
            with pytest.raises(RuntimeError, match='launch fixture'):
                with route_session_context(session_id='parent', expected_profile='wallace'):
                    runtime = capture_runtime(expected_profile='wallace', registry=SimpleNamespace(adopt_local=lambda *a, **k: None), emit=lambda *a: True)
                    assert runtime.parent_session_id == 'parent'
                    observer_context = copy_context()
                    raise RuntimeError('launch fixture')
            assert session_context.get_session_env('HERMES_SESSION_ID') == ''
            assert observer_context.run(session_context.get_session_env, 'HERMES_SESSION_ID') == 'parent'
            import os
            assert os.environ['HERMES_SESSION_ID'] == 'GLOBAL_PARENT'
        finally:
            session_context.clear_session_vars(tokens)
    Context().run(turn)


def test_cached_messaging_lanes_are_isolated_under_concurrency():
    from threading import Barrier
    barrier = Barrier(2)
    def turn(profile):
        tokens = session_context.set_session_vars(platform='telegram', session_key='lane-' + profile, profile=profile)
        try:
            with route_session_context(session_id='parent-' + profile, expected_profile=profile):
                barrier.wait(timeout=5)
                assert session_context.get_session_env('HERMES_SESSION_ID') == 'parent-' + profile
            assert session_context.get_session_env('HERMES_SESSION_ID') == ''
        finally:
            session_context.clear_session_vars(tokens)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(turn, ['wallace', 'claire']))


def test_existing_desktop_context_is_not_rebound():
    def turn():
        tokens = session_context.set_session_vars(platform='desktop', session_id='parent', session_key='lane', profile='wallace', ui_session_id='ui')
        try:
            with route_session_context(session_id='parent', expected_profile='wallace'):
                runtime = capture_runtime(expected_profile='wallace', registry=SimpleNamespace(adopt_local=lambda *a, **k: None), emit=lambda *a: True)
                assert runtime.parent_session_id == 'parent'
                assert runtime.ui_session_id == 'ui'
            assert session_context.get_session_env('HERMES_SESSION_ID') == 'parent'
        finally:
            session_context.clear_session_vars(tokens)
    Context().run(turn)


def test_cached_telegram_native_adoption_uses_scoped_dispatch_parent(tmp_path):
    import subprocess
    from tools.process_registry import ProcessRegistry
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    def turn():
        home_token = set_hermes_home_override(str(tmp_path))
        tokens = session_context.set_session_vars(platform='telegram', session_key='test-lane', profile='wallace')
        process = None
        try:
            registry = ProcessRegistry()
            with route_session_context(session_id='test-parent', expected_profile='wallace'):
                runtime = capture_runtime(task_id='test-owner', expected_profile='wallace', registry=registry, emit=lambda *a: True)
                with (tmp_path / 'worker.log').open('wb') as out:
                    process = subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True)
                process_id = runtime.track(process, job_id='test-job', purpose='mechanical', cwd=str(tmp_path))
                row = registry.get(process_id)
                assert row.parent_session_id == 'test-parent'
                assert row.session_key == 'test-lane'
                assert row.owner_task_id == 'test-owner'
                process.wait(timeout=5)
                row._reader_thread.join(timeout=5)
                assert row.exited and row.exit_code == 0
            assert session_context.get_session_env('HERMES_SESSION_ID') == ''
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            session_context.clear_session_vars(tokens)
            reset_hermes_home_override(home_token)
    Context().run(turn)
