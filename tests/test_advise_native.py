"""ask_advisor on the host's own per-home plugin manager, offline.

Real plugin load, real AIAgent children, real middleware, hooks and core pre-tool call site; only the
model turn (AIAgent.run_conversation) and credential acquisition are stubbed and HTTP is forbidden.
This is not evidence of a provider response.
"""
import contextvars
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_managed_model_overlay(monkeypatch):
    from model_router.service import Service
    monkeypatch.setattr(Service, '_read_model_overlay',
                        lambda self, profile: {'available': True, 'managed': {}, 'digest': 'fixture'})


@pytest.fixture
def real(tmp_path, monkeypatch):
    import httpx
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli import plugins
    from tools import delegate_tool as dt
    home = tmp_path / 'home'
    shutil.copytree(ROOT, home / 'plugins/model-router',
                    ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__', '.hermes-catalog.json', '.hermes'))
    (home / 'config.yaml').write_text(json.dumps({
        'plugins': {'enabled': ['model-router']},
        'model': {'provider': 'openrouter', 'default': 'fixture-heavy'},
        'delegation': {'backend': 'model-router', 'provider': 'openrouter', 'model': 'fixture-light'},
        'agent': {'reasoning_effort': 'high'},
    }), encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda **kwargs: home)
    monkeypatch.delenv('HERMES_PROFILE', raising=False)
    def forbidden(*args, **kwargs): raise AssertionError('HTTP is forbidden in this offline test')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)
    # The resolver stays native except for credential acquisition: no user key material is read.
    monkeypatch.setattr('tools.delegate_tool_routes._resolve_delegation_credentials', lambda route, parent, **kwargs: {
        'provider': 'openrouter', 'model': route['model'], 'base_url': 'http://127.0.0.1:9/v1',
        'api_key': 'offline-test-fixture', 'api_mode': 'chat_completions'})
    monkeypatch.setattr(dt, '_resolve_child_credential_pool', lambda *a, **kw: None)
    monkeypatch.setattr(dt, '_capture_origin', lambda: (None, None, None, None, False))
    parent = SimpleNamespace(session_id='offline-parent', provider='openrouter', model='fixture-parent',
                             base_url='http://127.0.0.1:9/v1', api_key='offline-test-fixture', request_overrides={},
                             tool_progress_callback=None, _delegate_spinner=None, _safe_print=lambda *a: None,
                             _delegation_backend='model-router', _delegate_depth=0, enabled_toolsets=[], disabled_toolsets=[],
                             _active_children=[], _active_children_lock=threading.Lock())
    token = set_hermes_home_override(home)
    manager = plugins.get_plugin_manager()  # the host's own manager for this home, as in production
    manager.discover_and_load()
    assert manager._plugins['model-router'].enabled and not manager._plugins['model-router'].error
    try:
        yield SimpleNamespace(home=home, parent=parent, manager=manager)
    finally:
        try:
            manager.unload()
        finally:
            reset_hermes_home_override(token)


def _ask(args):
    from tools.registry import registry
    entry = registry.get_entry('ask_advisor')
    assert entry is not None and entry.check_fn()
    return json.loads(entry.handler(dict(args), session_id='offline-parent'))


def _answer(text='use the index'):
    return {'completed': True, 'final_response': json.dumps({'recommendation': text, 'confidence': 'medium'}), 'messages': []}


def _verdict(agent, tool, args=None):
    from agent.agent_runtime_helpers import _pre_tool_block_message
    return _pre_tool_block_message(agent, tool, args or {}, '', 'call-' + tool, [])[0]


def test_real_child_is_bound_read_only_and_answers_in_the_same_call(real, monkeypatch):
    from agent.subagent_lifecycle import bind_subagent_parent
    from run_agent import AIAgent
    verdicts, children = {}, []
    def conversation(child, *args, **kwargs):
        children.append(child)
        # The host's own pre-tool call site, with the child's own identity.
        for name in ('read_file', 'write_file', 'terminal', 'delegate_task', 'tool_call', 'ask_advisor'):
            verdicts[name] = _verdict(child, name)
        verdicts['task_id_is_subagent_id'] = kwargs.get('task_id') == getattr(child, '_subagent_id', None)
        # The status-line roster binds the advisor row through the core's live registry.
        from tools.delegate_tool_registry import get_subagent_attribution
        from model_router.execution_roster import _ADVISOR_GOAL
        record = get_subagent_attribution(child._subagent_id)
        verdicts['registry_binds'] = bool(record and _ADVISOR_GOAL.match(record['goal'] or '')
                                          and record['delegation_id'] and record['delegation_id'] == child._delegation_id)
        return _answer()
    monkeypatch.setattr(AIAgent, 'run_conversation', conversation)
    with bind_subagent_parent(real.parent):
        reply = _ask({'question': 'Which index should I add?', 'context': 'Query is slow.'})
    assert reply['status'] == 'ok', reply
    assert 'use the index' in reply['advice'] and reply['route']['model'] == 'fixture-heavy'
    assert len(children) == 1 and isinstance(children[0], AIAgent)
    assert verdicts.pop('read_file') is None and verdicts.pop('task_id_is_subagent_id') is True
    assert verdicts.pop('registry_binds') is True
    assert all(message and 'read-only' in message for message in verdicts.values()), verdicts
    assert _verdict(real.parent, 'write_file') is None  # the asker itself is never restricted
    assert real.parent._active_children == []


def test_repeated_calls_and_template_like_questions_all_reach_a_child(real, monkeypatch):
    from agent.subagent_lifecycle import bind_subagent_parent
    from run_agent import AIAgent
    ran = []
    monkeypatch.setattr(AIAgent, 'run_conversation', lambda child, *a, **k: (ran.append(child), _answer())[1])
    questions = ['Which index should I add?', 'Which index should I add?',
                 'Should the endpoint be GET /users/{user_id}/orders or GET /orders?user={user_id}?',
                 'Is it fine to render <my-button> inside <app-root> before hydration?',
                 'Do I log f"{file_path}" or the relative path?', 'And which cache?']
    with bind_subagent_parent(real.parent):
        for question in questions:
            before = len(ran)
            reply = _ask({'question': question})
            assert reply['status'] == 'ok' and len(ran) == before + 1, (question, reply)
    assert len({child.session_id for child in ran}) == len(questions)
    assert all(_verdict(child, 'terminal') for child in ran)


def test_a_plugin_reload_during_and_after_a_call_keeps_every_advisor_child_read_only(real, monkeypatch):
    from agent.subagent_lifecycle import bind_subagent_parent
    from run_agent import AIAgent
    seen, children = {}, []
    def conversation(child, *args, **kwargs):
        children.append(child)
        if len(children) == 2:
            assert _verdict(child, 'terminal')
            real.manager.discover_and_load(force=True)  # what install/enable/update and auto-apply do
            seen['mid_call_terminal'] = _verdict(child, 'terminal')
            seen['mid_call_write'] = _verdict(child, 'write_file')
            seen['mid_call_read'] = _verdict(child, 'read_file')
        return _answer()
    monkeypatch.setattr(AIAgent, 'run_conversation', conversation)
    with bind_subagent_parent(real.parent):
        assert _ask({'question': 'Which index?'})['status'] == 'ok'
        first = children[0]
        assert _ask({'question': 'Which cache?'})['status'] == 'ok'
        # After the reload the earlier children stay bound and cannot be continued.
        for child in children:
            assert _verdict(child, 'terminal') and _verdict(child, 'write_file')
        for padded in (first._subagent_id, ' ' + first._subagent_id + ' '):
            assert _verdict(real.parent, 'delegate_task', {'action': 'continue', 'subagent_id': padded, 'message': 'm'})
        assert _ask({'question': 'Which queue?'})['status'] == 'ok'
        assert _verdict(children[-1], 'terminal') and _verdict(children[-1], 'write_file')
    assert seen['mid_call_terminal'] and seen['mid_call_write'] and seen['mid_call_read'] is None


def test_parallel_calls_from_one_turn_each_bind_their_own_child(real, monkeypatch):
    from agent.subagent_lifecycle import bind_subagent_parent
    from run_agent import AIAgent
    gate = threading.Barrier(2, timeout=30)
    blocked = []
    def conversation(child, *args, **kwargs):
        gate.wait()
        blocked.append(bool(_verdict(child, 'terminal')))
        return _answer()
    monkeypatch.setattr(AIAgent, 'run_conversation', conversation)
    replies = []
    with bind_subagent_parent(real.parent):
        threads = [threading.Thread(target=contextvars.copy_context().run, args=(lambda q=q: replies.append(_ask({'question': q})),))
                   for q in ('first question here', 'second question here')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    assert [reply['status'] for reply in replies] == ['ok', 'ok'] and blocked == [True, True]
    assert real.parent._active_children == []


def test_ordinary_delegate_task_cannot_use_the_advise_purpose(real, monkeypatch):
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli import middleware
    from tools import delegate_tool as dt
    from run_agent import AIAgent
    ran = []
    monkeypatch.setattr(AIAgent, 'run_conversation', lambda child, *a, **k: (ran.append(child), _answer())[1])
    with bind_subagent_parent(real.parent):
        reply = json.loads(middleware.run_tool_execution_middleware(
            'delegate_task', {'tasks': [{'goal': 'Advise me directly', 'purpose': 'advise'}]},
            lambda values: dt.delegate_task(**values, parent_agent=real.parent, background=False),
            session_id=real.parent.session_id))
    # Refused while the batch is normalised: no child is built.
    assert ran == [] and 'results' not in reply, reply
    assert 'only through the ask_advisor tool' in reply['error']
