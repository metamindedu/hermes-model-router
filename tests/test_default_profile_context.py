"""Default local turns bind profile='', not the plugin's canonical 'default'."""
from contextvars import Context
from concurrent.futures import ThreadPoolExecutor
import importlib
import importlib.util
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
import sys

import pytest

from gateway import session_context
from model_router.runtime_tracking import capture_runtime


def test_bound_local_default_profile_alias_preserves_native_owner(monkeypatch):
    monkeypatch.setenv('HERMES_SESSION_PROFILE', 'foreign-global-profile')
    monkeypatch.setenv('HERMES_SESSION_ID', 'foreign-global-parent')

    def turn():
        tokens = session_context.set_session_vars(
            platform='local', source='', profile='', session_id='local-default-parent',
            session_key='agent:main:local:dm:local-default-parent', ui_session_id='',
        )
        try:
            runtime = capture_runtime(
                expected_profile='default', task_id='owned-task',
                registry=SimpleNamespace(adopt_local=lambda *a, **k: None), emit=lambda *a: True,
            )
            assert runtime is not None
            assert runtime.parent_session_id == 'local-default-parent'
            assert runtime.session_key == 'agent:main:local:dm:local-default-parent'
            assert runtime.task_id == 'owned-task'
            assert runtime.ui_session_id == ''
            # Matching is presentation-only: never rebind or copy global identity.
            assert session_context.get_session_env('HERMES_SESSION_PROFILE') == ''
            assert session_context.get_session_env('HERMES_SESSION_ID') == 'local-default-parent'
        finally:
            session_context.clear_session_vars(tokens)

    Context().run(turn)


_MISSING = object()


@pytest.mark.parametrize('field,value', [
    ('HERMES_SESSION_PROFILE', _MISSING), ('HERMES_SESSION_PROFILE', None),
    ('HERMES_SESSION_PROFILE', 0), ('HERMES_SESSION_PROFILE', 'named'),
    ('HERMES_SESSION_PROFILE', 'default '),
    ('HERMES_SESSION_PLATFORM', _MISSING), ('HERMES_SESSION_PLATFORM', None),
    ('HERMES_SESSION_PLATFORM', 'desktop'), ('HERMES_SESSION_PLATFORM', 'telegram'),
    ('HERMES_SESSION_PLATFORM', ''),
    ('HERMES_SESSION_SOURCE', _MISSING), ('HERMES_SESSION_SOURCE', None),
    ('HERMES_SESSION_SOURCE', 'desktop'), ('HERMES_SESSION_SOURCE', 'local'),
    ('HERMES_UI_SESSION_ID', _MISSING), ('HERMES_UI_SESSION_ID', None),
    ('HERMES_UI_SESSION_ID', 'ui-parent'),
    ('HERMES_SESSION_ID', ''), ('HERMES_SESSION_ID', '../bad'),
    ('HERMES_SESSION_KEY', ''), ('HERMES_SESSION_KEY', 'lane\n'),
    ('HERMES_SESSION_KEY', 'x' * 513),
])
def test_default_alias_never_repairs_missing_malformed_or_foreign_context(field, value):
    values = {
        'HERMES_SESSION_ID': 'parent', 'HERMES_SESSION_KEY': 'local-lane',
        'HERMES_SESSION_PLATFORM': 'local', 'HERMES_SESSION_SOURCE': '',
        'HERMES_SESSION_PROFILE': '', 'HERMES_UI_SESSION_ID': '',
    }
    if value is _MISSING:
        del values[field]
    else:
        values[field] = value
    with pytest.raises(ValueError):
        capture_runtime(expected_profile='default', get_env=values.get,
            registry=SimpleNamespace(adopt_local=lambda *a, **k: None), emit=lambda *a: True)


def test_empty_local_profile_cannot_enter_a_named_plugin_scope():
    def turn():
        tokens = session_context.set_session_vars(platform='local', profile='',
            session_id='parent', session_key='lane')
        try:
            with pytest.raises(ValueError, match='routing profile does not match'):
                capture_runtime(expected_profile='claire')
        finally:
            session_context.clear_session_vars(tokens)
    Context().run(turn)


def test_default_local_and_named_turns_keep_concurrent_parent_lane_and_profile():
    barrier = Barrier(2)
    def turn(profile):
        raw = '' if profile == 'default' else profile
        tokens = session_context.set_session_vars(platform='local', profile=raw,
            session_id='parent-' + profile, session_key='lane-' + profile)
        try:
            barrier.wait(timeout=5)
            runtime = capture_runtime(expected_profile=profile,
                registry=SimpleNamespace(adopt_local=lambda *a, **k: None), emit=lambda *a: True)
            assert runtime is not None
            assert runtime.parent_session_id == 'parent-' + profile
            assert runtime.session_key == 'lane-' + profile
            assert session_context.get_session_env('HERMES_SESSION_PROFILE') == raw
            return runtime.parent_session_id
        finally:
            session_context.clear_session_vars(tokens)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(turn, ['default', 'claire'])) == {'parent-default', 'parent-claire'}


def test_default_local_native_tool_dispatch_reaches_router_once(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.registry import ToolRegistry
    import tools.process_registry

    repo = Path(__file__).resolve().parents[1]
    name = 'default_profile_dispatch_fixture'
    spec = importlib.util.spec_from_file_location(name, repo / '__init__.py',
        submodule_search_locations=[str(repo)])
    assert spec is not None and spec.loader is not None
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, plugin)
    spec.loader.exec_module(plugin)
    service = importlib.import_module(name + '.model_router.service')
    routing = importlib.import_module(name + '.model_router.routing')
    observed = []
    class Service:
        def routing_config(self, profile):
            assert profile == 'default'
            return {'enabled': True}
        def active_profile(self): return 'default'
    class Router:
        def __init__(self, service, *, runtime=None, fast_snapshot=None):
            assert runtime is not None
            self.runtime = runtime
            assert fast_snapshot is None
        def join(self, *args, **kwargs):
            observed.append((self.runtime.parent_session_id, self.runtime.session_key,
                self.runtime.task_id, session_context.get_session_env('HERMES_SESSION_PROFILE')))
            return {'status': 'fixture-admitted'}
    monkeypatch.setattr(service, 'Service', Service)
    monkeypatch.setattr(routing, 'Router', Router)
    monkeypatch.setattr(tools.process_registry, 'process_registry',
        SimpleNamespace(adopt_local=lambda *a, **k: None))
    registry = ToolRegistry()
    ctx = SimpleNamespace(register_cli_command=lambda *a: None, register_skill=lambda *a: None,
        register_delegation_provider=lambda *a: None, register_hook=lambda *a: None, register_tool=lambda **kw: registry.register(**kw))
    def turn():
        home_token = set_hermes_home_override(tmp_path)
        tokens = session_context.set_session_vars(platform='local', profile='',
            session_id='fixture-parent', session_key='fixture-lane')
        try:
            plugin.register(ctx)
            response = registry.dispatch('coding_route',
                {'action': 'join', 'job_id': 'fixture-job'},
                task_id='fixture-task', session_id='fixture-parent')
            assert isinstance(response, str)
            result = json.loads(response)
            assert result == {'status': 'fixture-admitted'}, result
            assert observed == [('fixture-parent', 'fixture-lane', 'fixture-task', '')]
        finally:
            session_context.clear_session_vars(tokens)
            reset_hermes_home_override(home_token)
    Context().run(turn)
