"""Real Hermes child construction/execution; only model responses are stubbed.

This is an offline integration test, NOT evidence of a provider/model response.
All state belongs to a temporary home and HTTP sending is forbidden.
"""
from contextvars import copy_context
import json
from pathlib import Path
import shutil
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('cancel,profile_route,automatic', [
    (cancel, profile, auto)
    for cancel in ('complete', 'stop', 'budget', 'noncooperative')
    for profile in (False, True) for auto in (False, True)
] + [('complete', 'mixed', True)])
def test_real_native_child_completion_and_cooperative_stop(tmp_path, monkeypatch, cancel, profile_route, automatic):
    import httpx
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli import plugins, middleware
    from agent.subagent_lifecycle import bind_subagent_parent
    from tools import delegate_tool as dt
    from run_agent import AIAgent

    root = Path(__file__).resolve().parents[1]
    home = tmp_path / 'home'
    shutil.copytree(root, home / 'plugins/model-router',
        ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__', '.hermes-catalog.json'))
    backend = 'model-router-auto' if automatic else ('model-router-profiles' if profile_route else 'model-router')
    target = home / 'profiles/specialist'
    target.mkdir(parents=True)
    (target / 'config.yaml').write_text(json.dumps({'model': {'provider': 'openrouter', 'default': 'fixture-target', 'base_url': 'http://127.0.0.1:9/v1', 'api_key': 'target-offline-fixture'}, 'agent': {'reasoning_effort': 'low'}}), encoding='utf-8')
    (target / 'SOUL.md').write_text('Offline specialist identity fixture', encoding='utf-8')
    (home / 'config.yaml').write_text(json.dumps({
        'plugins': {'enabled': ['model-router']},
        'model': {'provider': 'openrouter', 'default': 'fixture-heavy'},
        'delegation': {'backend': backend, 'provider': 'openrouter', 'model': 'fixture-light', 'backends': {'model-router-profiles': {'schema': 1, 'profiles': [{'name': 'specialist', 'description': 'Offline evidence specialist'}], 'default': None}}},
        'agent': {'reasoning_effort': 'high'},
    }), encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: home)
    monkeypatch.delenv('HERMES_PROFILE', raising=False)
    def forbidden(*args, **kwargs): raise AssertionError('HTTP is forbidden in offline native execution test')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)
    # The native resolver is retained except for credential acquisition: never
    # read user OAuth/key material to construct this offline child.
    monkeypatch.setattr(dt, '_resolve_delegation_credentials', lambda route, parent: {
        'provider': 'openrouter', 'model': route['model'], 'base_url': 'http://127.0.0.1:9/v1',
        'api_key': 'offline-test-fixture', 'api_mode': 'chat_completions'})
    monkeypatch.setattr(dt, '_resolve_child_credential_pool', lambda *a, **kw: None)
    monkeypatch.setattr(dt, '_capture_origin', lambda: (None, None, None, None, False))
    entered = threading.Event()
    release_work = threading.Event()
    workload_finished = threading.Event()
    children = []
    def offline_conversation(child, *args, **kwargs):
        children.append(child)
        entered.set()
        if cancel == 'noncooperative':
            release_work.wait(5)  # deliberately ignores interrupt until test releases it
            workload_finished.set()
            return {'completed': False, 'interrupted': True, 'final_response': '', 'messages': []}
        if cancel != 'complete':
            limit = time.monotonic() + 5
            while not child._interrupt_requested and time.monotonic() < limit:
                time.sleep(.01)
            return {'completed': False, 'interrupted': True, 'final_response': '', 'messages': []}
        return {'completed': True, 'final_response': 'offline fixture completion', 'messages': []}
    monkeypatch.setattr(AIAgent, 'run_conversation', offline_conversation)
    parent = SimpleNamespace(session_id='offline-parent', provider='openrouter', model='fixture-parent',
        base_url='http://127.0.0.1:9/v1', api_key='offline-test-fixture', request_overrides={},
        tool_progress_callback=None, _delegate_spinner=None, _safe_print=lambda *a: None,
        _delegation_backend=backend, _delegate_depth=0, enabled_toolsets=[], disabled_toolsets=[],
        _active_children=[], _active_children_lock=threading.Lock())
    token = set_hermes_home_override(home)
    manager = plugins.PluginManager(scope_key=str(home))
    monkeypatch.setattr(plugins, '_delivery_manager', lambda: manager)
    result = {}
    thread = None
    try:
        manager.discover_and_load()
        assert manager._plugins['model-router'].enabled and not manager._plugins['model-router'].error
        def run():
            with bind_subagent_parent(parent):
                selectors = ([{'purpose': 'mechanical'}, {'purpose': 'plan'}, {'profile': 'specialist'}]
                             if profile_route == 'mixed' else [{'profile': 'specialist'} if profile_route else {'purpose': 'mechanical'}])
                tasks = [{'goal': f'Exercise the real offline native child {i}', **selection,
                          **({'execution': 'profile' if 'profile' in selection else 'model'} if automatic else {}),
                          **({'total_timeout_seconds': .05} if cancel == 'budget' else {})}
                         for i, selection in enumerate(selectors)]
                if profile_route == 'mixed':
                    tasks.append({'goal': 'Contradictory selectors must refuse alone', 'execution': 'profile', 'profile': 'specialist', 'purpose': 'plan'})
                args = {'tasks': tasks}
                result['value'] = json.loads(middleware.run_tool_execution_middleware(
                    'delegate_task', args, lambda values: dt.delegate_task(**values, parent_agent=parent),
                    session_id=parent.session_id))
        if cancel != 'complete':
            thread = threading.Thread(target=copy_context().run, args=(run,))
            thread.start()
            assert entered.wait(10), result
            owned = json.loads(dt.delegate_task(action='list', parent_agent=parent))
            assert owned['count'] == 1
            if cancel in ('stop', 'noncooperative'):
                stopped = json.loads(dt.delegate_task(action='stop', subagent_id=owned['subagents'][0]['subagent_id'], parent_agent=parent))
                assert 'error' not in stopped
                if cancel == 'noncooperative':
                    assert children[0]._interrupt_requested and not workload_finished.is_set()
                    assert stopped['status'] == 'interrupt_requested'
                    assert stopped.get('terminated') is not True
                    release_work.set()
            thread.join(10)
            assert not thread.is_alive()
        else:
            run()
        assert len(children) == (3 if profile_route == 'mixed' else 1)
        assert all(isinstance(child, AIAgent) for child in children)
        expected = ['fixture-light', 'fixture-heavy', 'fixture-target'] if profile_route == 'mixed' else ['fixture-target' if profile_route else 'fixture-light']
        for entry, model in zip(result['value']['results'], expected):
            assert entry['status'] in ({'interrupted', 'failed'} if cancel != 'complete' else {'completed'})
            assert entry['route']['backend'] == backend
            assert entry['route']['model'] == model
            assert entry['api_calls'] == 0
            if automatic:
                assert entry['route']['label'].startswith('profile:' if model == 'fixture-target' else 'model:')
            if model == 'fixture-target':
                assert entry['route']['reasoning_effort'] == 'low'
        if profile_route == 'mixed':
            assert result['value']['results'][3]['status'] == 'error'
            assert result['value']['results'][3]['route']['refused'] is True
        if profile_route:
            child = next(child for child in children if child.model == 'fixture-target')
            assert child._delegate_profile_home == target
            assert child.api_key != parent.api_key  # target's unauthenticated local endpoint never borrows the parent key
        assert parent._active_children == []
        if cancel == 'budget':
            rows = [json.loads(line) for line in (home/'plugin-data/model-router/native-watchdog.jsonl').read_text().splitlines()]
            assert rows[-1]['kind'] == 'native_total_timeout_stop' and rows[-1]['total_seconds'] == .05
            assert rows[-1]['request_outcome'] == 'accepted'
    finally:
        release_work.set()
        for child in children:
            if thread is not None and thread.is_alive(): child.interrupt('test cleanup')
        if thread is not None: thread.join(10)
        manager.unload()
        reset_hermes_home_override(token)
