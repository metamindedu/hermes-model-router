import json
import pytest
from model_router import native_watchdog as nw
from test_native_role_watchdog import routed, dispatch


def test_mixed_auto_execution_binds_role_or_ordinary_total(routed, monkeypatch):
    monkeypatch.setattr(nw, '_dispatch_backend', lambda parent: 'model-router-auto')
    routed.watchdog.total_seconds = 29
    tasks = [
        {'goal': 'malformed task refused alone', 'execution': 'profile', 'profile': 'claire', 'purpose': 'plan'},
        {'goal': 'origin light work', 'execution': 'model', 'purpose': 'mechanical'},
        {'goal': 'origin heavy work', 'execution': 'model', 'purpose': 'plan'},
        {'goal': 'specialist work', 'execution': 'profile', 'profile': 'claire'},
    ]
    def call():
        assert nw.verify_routed_binding(routed.home, tasks[1]['goal'], 'light', .5)
        assert nw.verify_routed_binding(routed.home, tasks[2]['goal'], 'heavy', 10800)
        assert nw.verify_routed_binding(routed.home, tasks[3]['goal'], 'profile', 29)
        assert not nw.verify_routed_binding(routed.home, tasks[3]['goal'], 'heavy', 10800)
        assert not nw.verify_routed_binding(routed.home, tasks[0]['goal'], 'profile', 29)
        for i in (3, 1, 2):
            routed.watchdog.on_subagent_start(parent_session_id='parent-A', child_session_id=f'c{i}', child_subagent_id=f's{i}', child_goal=tasks[i]['goal'])
        return json.dumps({'status': 'dispatched'})
    dispatch(routed, tasks, call)
    assert {k: w.total_seconds for k, w in routed.watchdog.children.items()} == {'s3': 29, 's1': .5, 's2': 10800}
    routed.watchdog.close()


def test_same_goal_across_model_and_profile_is_refused_even_with_equal_zero_budget(routed, monkeypatch):
    monkeypatch.setattr(nw, '_dispatch_backend', lambda parent: 'model-router-auto')
    tasks = [
        {'goal': 'same goal cannot bind to two roles', 'execution': 'model', 'purpose': 'plan', 'total_timeout_seconds': 0},
        {'goal': 'same goal cannot bind to two roles', 'execution': 'profile', 'profile': 'claire', 'total_timeout_seconds': 0},
    ]
    calls = []
    assert 'error' in json.loads(dispatch(routed, tasks, lambda: calls.append(1)))
    assert not calls and not routed.watchdog.children


def test_unavailable_model_settings_leave_profile_sibling_to_native_validation(routed, monkeypatch):
    monkeypatch.setattr(nw, '_dispatch_backend', lambda parent: 'model-router-auto')
    class Broken:
        def routing_config(self, profile): raise ValueError('invalid role settings')
    monkeypatch.setattr('model_router.service.Service', Broken)
    tasks = [
        {'goal': 'model refused alone', 'execution': 'model', 'purpose': 'plan'},
        {'goal': 'explicit specialist task', 'execution': 'profile', 'profile': 'claire'},
    ]
    def call():
        assert not nw.verify_routed_binding(routed.home, tasks[0]['goal'], 'heavy', 10800)
        assert nw.verify_routed_binding(routed.home, tasks[1]['goal'], 'profile', 0)
        return 'native-refuses-invalid-model-task-only'
    assert dispatch(routed, tasks, call) == 'native-refuses-invalid-model-task-only'
