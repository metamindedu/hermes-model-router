import json
import pytest
from model_router import native_watchdog as nw
from test_native_watchdog import NativeHarness, ManualScheduler


@pytest.fixture
def routed(tmp_path, monkeypatch):
    h = NativeHarness(tmp_path, total=0)
    monkeypatch.setattr(nw, '_dispatch_backend', lambda parent: 'model-router')
    monkeypatch.setattr('model_router.native_delegation._origin', lambda home, service: 'default')
    class Service:
        def routing_config(self, profile):
            return {'enabled': True, 'light_timeout_seconds': .5, 'heavy_timeout_seconds': 10800}
    monkeypatch.setattr('model_router.service.Service', Service)
    return h


def dispatch(h, tasks, callback):
    return h.watchdog.middleware(tool_name='delegate_task', args={'tasks': tasks}, session_id='parent-A', next_call=callback)


def test_mixed_budgets_exact_goal_async_and_queue(routed):
    h = routed
    tasks = [{'goal': 'perform the light task', 'purpose': 'mechanical'}, {'goal': 'perform the heavy task', 'purpose': 'plan'}]
    def call():
        assert nw.verify_routed_binding(h.home, tasks[0]['goal'], 'light', .5)
        assert not nw.verify_routed_binding(h.home, tasks[0]['goal'], 'heavy', 10800)
        for i in (1, 0):
            h.watchdog.on_subagent_start(parent_session_id='parent-A', child_session_id=f'c{i}', child_subagent_id=f'sa{i}', child_goal=tasks[i]['goal'])
        return json.dumps({'status': 'dispatched'})
    dispatch(h, tasks, call)
    assert h.watchdog.children['sa0'].total_seconds == .5
    assert h.watchdog.children['sa1'].total_seconds == 10800
    h.watchdog.poll_once()
    assert h.watchdog.children['sa1'].deadline is None
    h.add_native('sa1', 999, status='queued')
    h.watchdog.poll_once()
    assert h.watchdog.children['sa1'].deadline is None
    h.add_native('sa0', .25)
    h.add_native('sa1', 100)
    h.watchdog.poll_once()
    assert h.watchdog.children['sa0'].deadline == pytest.approx(100.25)
    assert h.watchdog.children['sa1'].deadline == pytest.approx(10800)
    h.now[0] = 100.25
    h.watchdog.poll_once()
    assert [c[2] for c in h.calls if c[0] == 'stop'] == ['sa0']
    h.watchdog.close()


def test_duplicate_goal_conflicting_policy_refuses_before_downstream(routed):
    goal = 'same exact goal for both'
    tasks = [{'goal': goal, 'purpose': 'plan'}, {'goal': goal, 'purpose': 'mechanical'}]
    calls = []
    result = dispatch(routed, tasks, lambda: calls.append(1))
    assert 'error' in json.loads(result)
    assert not calls and not routed.watchdog.children


def test_duplicate_same_policy_allowed_and_zero_override(routed):
    goal = 'same exact goal for both'
    tasks = [{'goal': goal, 'purpose': 'mechanical', 'total_timeout_seconds': 0},
             {'goal': goal, 'purpose': 'mechanical', 'total_timeout_seconds': 0}]
    def call():
        assert nw.verify_routed_binding(routed.home, goal, 'light', 0)
        routed.watchdog.on_subagent_start(parent_session_id='parent-A', child_session_id='child', child_subagent_id='sa', child_goal=goal)
        return 'ok'
    assert dispatch(routed, tasks, call) == 'ok'
    assert not routed.watchdog.children


def test_refuse_scheduler_failure_without_downstream(routed):
    class Broken(ManualScheduler):
        def start(self): raise RuntimeError('failure')
    routed.watchdog.scheduler_factory = Broken
    calls = []
    result = dispatch(routed, [{'goal': 'perform task sufficiently specific', 'purpose': 'plan'}], lambda: calls.append(1))
    assert 'error' in json.loads(result) and not calls


def test_invalid_origin_or_parent_refuses(routed):
    routed.watchdog.get_hermes_home = lambda: routed.home.parent
    result = dispatch(routed, [{'goal': 'perform task sufficiently specific', 'purpose': 'plan'}], lambda: pytest.fail('dispatched'))
    assert 'error' in json.loads(result)


def test_profile_uses_ordinary_budget_and_override(routed, monkeypatch):
    monkeypatch.setattr(nw, '_dispatch_backend', lambda parent: 'model-router-profiles')
    routed.watchdog.total_seconds = 33
    tasks = [{'goal': 'profile task without override'}, {'goal': 'profile task with override', 'total_timeout_seconds': 2.5}]
    def call():
        for i, task in enumerate(tasks):
            routed.watchdog.on_subagent_start(parent_session_id='parent-A', child_session_id=f'c{i}', child_subagent_id=f's{i}', child_goal=task['goal'])
        return json.dumps({'status': 'dispatched'})
    dispatch(routed, tasks, call)
    assert routed.watchdog.children['s0'].total_seconds == 33
    assert routed.watchdog.children['s1'].total_seconds == 2.5


def test_scheduler_stays_alive_while_dispatch_is_resolving_before_first_child(routed):
    goal = 'Long credential resolution before child creation'
    def call():
        scheduler = routed.watchdog._scheduler
        routed.watchdog.poll_once()
        assert routed.watchdog._scheduler is scheduler
        assert nw.verify_routed_binding(routed.home, goal, 'heavy', 10800)
        return json.dumps({'results': [], 'status': 'completed'})
    dispatch(routed, [{'goal': goal, 'purpose': 'plan'}], call)
    assert routed.watchdog._scheduler is None
    assert routed.watchdog._pending_dispatches == set()


@pytest.mark.parametrize('invalid', ['invalid', [], {}])
def test_invalid_task_policy_is_left_for_native_per_task_refusal(routed, invalid):
    seen = []
    tasks = [{'goal': 'Invalid purpose is refused alone', 'purpose': invalid},
             {'goal': 'Valid sibling gets its own policy', 'purpose': 'mechanical'}]
    assert dispatch(routed, tasks, lambda: seen.append(1) or 'native-result') == 'native-result'
    assert seen == [1]


@pytest.mark.parametrize('invalid', ['invalid', [], {}])
def test_actual_core_dispatch_with_stubbed_child_and_no_provider_calls(tmp_path, monkeypatch, invalid):
    from types import SimpleNamespace
    from hermes_cli import middleware, plugins
    from hermes_cli.plugins_manifest import parse_manifest_file
    from pathlib import Path
    from model_router.native_delegation import ModelRouterProvider
    from tools import delegate_tool as dt
    from tools import delegate_tool_routes as routes
    import tools.delegation_live_log as live

    (tmp_path / 'config.yaml').write_text('{}')
    parent = SimpleNamespace(session_id='parent-A', _delegate_depth=0, _delegation_backend='model-router')
    h = NativeHarness(tmp_path, parent=parent, total=0)
    manager = plugins.PluginManager(scope_key=str(tmp_path))
    root = Path(__file__).resolve().parents[1]
    manifest = parse_manifest_file(root / 'plugin.yaml', root, 'user', '')
    ctx = plugins.PluginContext(manifest, manager)
    ctx.register_middleware('tool_execution', h.watchdog.middleware)
    ctx.register_hook('subagent_start', h.watchdog.on_subagent_start)
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: manager)
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: tmp_path)
    class Service:
        root = tmp_path
        def active_profile(self): return 'default'
        def routing_config(self, profile):
            return {'enabled': True, 'light': {'provider': 'p', 'model': 'light', 'reasoning': 'low'},
                    'heavy': {'provider': 'p', 'model': 'heavy', 'reasoning': 'high'},
                    'light_timeout_seconds': 2, 'heavy_timeout_seconds': 10800}
        native_route_config = routing_config
    monkeypatch.setattr('model_router.service.Service', Service)
    provider = ModelRouterProvider(tmp_path, Service)
    monkeypatch.setattr(routes, '_active_provider', lambda config: provider)
    monkeypatch.setattr(dt, '_load_config', lambda: {'backend': 'model-router'})
    monkeypatch.setattr(dt, '_get_max_spawn_depth', lambda: 5)
    monkeypatch.setattr(dt, '_get_max_concurrent_children', lambda: 5)
    monkeypatch.setattr(dt, '_oneshot_spawn_budget', lambda *args: None)
    monkeypatch.setattr(dt, 'is_spawn_paused', lambda: False)
    monkeypatch.setattr(live, 'create_live_transcripts', lambda *args, **kwargs: (None, [], []))
    monkeypatch.setattr(dt, '_announce_batch', lambda *args: None)
    monkeypatch.setattr(dt, '_capture_origin', lambda: (None, None, None, None, False))
    monkeypatch.setattr(dt, '_resolve_delegation_credentials', lambda route, parent: {'provider': route['provider'], 'model': route['model'], 'base_url': None, 'api_key': None, 'api_mode': None})
    built = []
    def build(**kw):
        built.append(kw)
        manager.invoke_hook('subagent_start', parent_session_id='parent-A', child_session_id=f"c{len(built)}", child_subagent_id=f"s{len(built)}", child_goal=kw['goal'])
        return SimpleNamespace(tool_progress_callback=None)
    monkeypatch.setattr(dt, '_build_child_preserving_parent_tools', build)
    monkeypatch.setattr('tools.delegate_tool_tuning.pin_child_service_tier', lambda *args: None)
    monkeypatch.setattr(dt, '_run_batch', lambda batch, background: json.dumps({'status': 'dispatched'}))
    tasks = [{'goal': 'refused invalid purpose task', 'purpose': invalid}, {'goal': 'perform the light task', 'purpose': 'mechanical'}, {'goal': 'perform the heavy task', 'purpose': 'plan'}]
    args = {'tasks': tasks}
    try:
        result = middleware.run_tool_execution_middleware('delegate_task', args, lambda value: dt.delegate_task(**value, parent_agent=parent), session_id='parent-A')
        assert json.loads(result)['status'] == 'dispatched'
        assert [item['model'] for item in built] == ['light', 'heavy']
        assert all(item['routing_cfg']['fallback_providers'] == [] for item in built)
        assert h.watchdog.children['s1'].total_seconds == 2
        assert h.watchdog.children['s2'].total_seconds == 10800
    finally:
        h.watchdog.close()
        manager.unload('model-router')
