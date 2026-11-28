"""ask_advisor: synchronous read-only advisor and its session-bound guard."""
import contextvars
import copy
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

from model_router import advise_guard as ag
from model_router import native_delegation as nd
from model_router import native_settings as ns
from model_router import slots

try:
    from agent.delegation_provider import DelegationRouteError
except ModuleNotFoundError:  # pragma: no cover - core absent
    DelegationRouteError = nd.DelegationRouteError

READ = sorted(ag.READ_ONLY_TOOLS)
OFF = {'mode': 'off', 'chain': [], 'consent': None}


def make_guard(tmp_path, *, backend='model-router', route=None, run=None, parent=None, enabled=True):
    parent = parent or SimpleNamespace(session_id='parent-1', provider='openai-codex', model='gpt-main')
    calls = []

    def default_run(request, owner, kwargs):
        calls.append(copy.deepcopy(request))
        task = request['tasks'][0]
        assert ag.advisor_call_active(tmp_path, task['goal'])
        guard.on_subagent_start(parent_session_id=owner.session_id, child_session_id='child-1',
                                child_subagent_id='sa-1', child_goal=task['goal'])
        return json.dumps({'results': [{'status': 'completed', 'summary': '{"recommendation": "do A", "confidence": "high"}',
                                        'schema_valid': True, 'model': 'gpt-advisor', 'route': {'backend': backend},
                                        'duration_seconds': 3.0}]})

    guard = ag.AdviseGuard(tmp_path, get_active_parent=lambda: parent, dispatch_backend=lambda _p: backend,
                           resolve_route=lambda: route or {'provider': 'openai-codex', 'model': 'gpt-advisor', 'reasoning': 'high'},
                           run_delegation=run or default_run, routing_enabled=lambda: enabled)
    guard.ready = True
    return guard, parent, calls


# ---- slot table and stored blocks ------------------------------------------------------------

def test_advise_is_a_builtin_slot_appended_last():
    assert slots.BUILTIN_SLOTS[-1] == 'advise'
    assert list(slots.PURPOSE_SLOTS)[-1] == 'advise' and slots.PURPOSE_SLOTS['advise'] == 'advise'
    assert not hasattr(slots, 'SLOT_TIERS')


@pytest.mark.parametrize('validator', ['settings', 'delegation'])
def test_a_block_must_name_every_slot_including_advise(validator):
    validate = ((lambda block: ns.validate_slot_policy_block('default', block)) if validator == 'settings'
                else (lambda block: nd.validate_native_policy(block, 'default')))
    full = {'schema': 2, 'fallbacks': {s: dict(OFF) for s in slots.BUILTIN_SLOTS}}
    validate(full)
    for keys in (slots.BUILTIN_SLOTS[:6], slots.BUILTIN_SLOTS[:5], (*slots.BUILTIN_SLOTS, 'bogus'), (*slots.BUILTIN_SLOTS[:6], 'bogus')):
        with pytest.raises(ValueError):
            validate({'schema': 2, 'fallbacks': {s: dict(OFF) for s in keys}})


def test_patching_a_block_keeps_every_stored_entry():
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    stored = ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'design': {'mode': 'custom', 'chain': chain}}, True)
    block = ns.patch_slot_policy_block('default', copy.deepcopy(stored), {'advise': {'mode': 'custom', 'chain': chain}}, True)
    assert list(block['fallbacks']) == list(slots.BUILTIN_SLOTS)
    assert block['fallbacks']['design'] == stored['fallbacks']['design']
    assert block['fallbacks']['advise']['consent'] == ns.make_slot_consent('default', 'model-router', 'advise', chain)
    untouched = ns.patch_slot_policy_block('default', copy.deepcopy(stored), {'code-simple': {'mode': 'off', 'chain': []}}, False)
    assert untouched['fallbacks']['advise'] == OFF


# ---- the route gate --------------------------------------------------------------------------

class FakeService:
    def __init__(self, root):
        self.root = root
        routes = {s: {'provider': 'p', 'model': 'model-for-' + s, 'reasoning': 'high'} for s in slots.BUILTIN_SLOTS}
        self.config = {'enabled': True, 'slots': routes,
                       'slot_timeout_seconds': {s: 7200 for s in slots.BUILTIN_SLOTS}}
    def active_profile(self): return 'default'
    def routing_config(self, name): return self.config
    native_route_config = routing_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / 'config.yaml').write_text('{}')
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: tmp_path)
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: tmp_path)
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    return tmp_path, FakeService(tmp_path)


def test_advise_is_refused_outside_an_ask_advisor_call(env):
    home, service = env
    for provider in (nd.ModelRouterProvider(home, lambda: service), nd.ModelRouterAutoProvider(home, lambda: service)):
        task = {'purpose': 'advise', 'goal': 'g', **({'execution': 'model'} if provider.name.endswith('auto') else {})}
        with pytest.raises(DelegationRouteError, match='only through the ask_advisor tool'):
            provider.route_task(task, {})
    assert 'ask_advisor' in nd.ModelRouterProvider(home, lambda: service).task_parameters({})['purpose']['description']


def test_advise_routes_only_for_the_exact_in_flight_goal(env):
    home, service = env
    provider = nd.ModelRouterProvider(home, lambda: service)
    seen = {}
    def run(request, owner, kwargs):
        goal = request['tasks'][0]['goal']
        seen['route'] = provider.route_task({'purpose': 'advise', 'goal': goal, 'total_timeout_seconds': 300}, {})
        with pytest.raises(DelegationRouteError):
            provider.route_task({'purpose': 'advise', 'goal': goal + ' (another task)'}, {})
        return json.dumps({'error': 'stop here'})
    def run_and_copy(request, owner, kwargs):
        # A child thread runs in a context copied during the call; it must see the call close too.
        seen['goal'], seen['copied'] = request['tasks'][0]['goal'], contextvars.copy_context()
        return run(request, owner, kwargs)
    guard, _parent, _ = make_guard(home, run=run_and_copy)
    guard.tool({'question': 'Which?'}, session_id='parent-1')
    assert seen['route']['model'] == 'model-for-advise' and seen['route']['label'] == 'advise'
    # After the call the same goal is refused again, here and in a context copied during the call.
    assert not ag.advisor_call_active(home, seen['goal'])
    assert seen['copied'].run(ag.advisor_call_active, home, seen['goal']) is False
    with pytest.raises(DelegationRouteError):
        seen['copied'].run(provider.route_task, {'purpose': 'advise', 'goal': seen['goal']}, {})
    guard.ready = False
    assert not ag.advisor_call_active(home, 'anything')


# ---- the guard -------------------------------------------------------------------------------

def test_bound_session_may_only_read(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    guard.tool({'question': 'q'}, session_id='parent-1')
    for name in READ:
        assert guard.pre_tool_call(tool_name=name, args={}, session_id='child-1') is None
    for name in ('terminal', 'write_file', 'patch', 'execute_code', 'delegate_task', 'tool_call', 'browser_exec',
                 'mcp__hermes__terminal', 'memory', 'skill_manage', 'process_manage', ''):
        verdict = guard.pre_tool_call(tool_name=name, args={}, session_id='child-1')
        assert verdict['action'] == 'block' and 'read-only' in verdict['message']
    # Other sessions are untouched, including the parent's own writes.
    assert guard.pre_tool_call(tool_name='write_file', args={}, session_id='parent-1') is None
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='') is None


def test_the_advisor_child_cannot_be_continued_and_compaction_keeps_the_binding(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    guard.tool({'question': 'q'}, session_id='parent-1')
    verdict = guard.pre_tool_call(tool_name='delegate_task', args={'action': ' Continue ', 'subagent_id': 'sa-1'}, session_id='parent-1')
    assert verdict['action'] == 'block'
    assert guard.pre_tool_call(tool_name='delegate_task', args={'action': 'continue', 'subagent_id': 'other'}, session_id='parent-1') is None
    assert guard.pre_tool_call(tool_name='delegate_task', args={'action': 'steer', 'subagent_id': 'sa-1'}, session_id='parent-1') is None
    guard.on_post_compaction(session_id='child-1b', old_session_id='child-1')
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='child-1b')['action'] == 'block'
    guard.on_post_compaction(session_id='x2', old_session_id='unrelated')
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='x2') is None


def test_a_failing_check_blocks_instead_of_allowing(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    class Broken:
        def __enter__(self): raise RuntimeError('boom')
        def __exit__(self, *a): return False
    guard.bindings.lock = Broken()
    assert guard.pre_tool_call(tool_name='read_file', args={}, session_id='anything')['action'] == 'block'


def test_hooks_ignore_children_of_other_dispatches(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    guard.on_subagent_start(parent_session_id='parent-1', child_session_id='c9', child_subagent_id='s9', child_goal='g')
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='c9') is None


def test_children_of_other_dispatches_during_the_call_are_neither_bound_nor_counted(tmp_path):
    def run(request, owner, kwargs):
        goal = request['tasks'][0]['goal']
        # Another dispatch in the same process: other goal, or the same goal under another parent.
        guard.on_subagent_start(parent_session_id=owner.session_id, child_session_id='other-goal',
                                child_subagent_id='x1', child_goal='a different task')
        guard.on_subagent_start(parent_session_id='someone-else', child_session_id='other-parent',
                                child_subagent_id='x2', child_goal=goal)
        guard.on_subagent_start(parent_session_id=owner.session_id, child_session_id='child-1',
                                child_subagent_id='sa-1', child_goal=goal)
        return json.dumps({'results': [{'status': 'completed', 'summary': 'fine'}]})
    guard, _, _ = make_guard(tmp_path, run=run)
    # Not counted: the answer of this call stands.
    assert json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))['status'] == 'ok'
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='other-goal') is None
    # A child carrying the advisor marker is bound whoever started it: binding too much only blocks more.
    for session in ('other-parent', 'child-1'):
        assert guard.pre_tool_call(tool_name='terminal', args={}, session_id=session)['action'] == 'block'


def test_more_than_one_bound_child_discards_the_answer(tmp_path):
    def run(request, owner, kwargs):
        goal = request['tasks'][0]['goal']
        for index in (1, 2):
            guard.on_subagent_start(parent_session_id=owner.session_id, child_session_id=f'child-{index}',
                                    child_subagent_id=f'sa-{index}', child_goal=goal)
        return json.dumps({'results': [{'status': 'completed', 'summary': 'two answers?'}]})
    guard, _, _ = make_guard(tmp_path, run=run)
    reply = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
    assert reply['error'] == 'guard_unbound' and 'two answers' not in json.dumps(reply)
    # Both are still held read-only.
    for session in ('child-1', 'child-2'):
        assert guard.pre_tool_call(tool_name='write_file', args={}, session_id=session)['action'] == 'block'


# ---- the tool --------------------------------------------------------------------------------

def test_ask_advisor_dispatches_one_synchronous_advise_task_and_returns_the_answer(tmp_path):
    guard, parent, calls = make_guard(tmp_path)
    reply = json.loads(guard.tool({'question': '  Which index?  ', 'context': 'We tried B.'}, session_id='parent-1'))
    assert reply['status'] == 'ok' and 'do A' in reply['advice'] and reply['schema_valid'] is True
    assert reply['model'] == 'gpt-advisor' and 'not a verified fact' in reply['note']
    [request] = calls
    [task] = request['tasks']
    assert task['purpose'] == 'advise' and task['total_timeout_seconds'] == ag.ADVISE_TIMEOUT_SECONDS
    # The goal is fixed text with the marker; the question and the asker's context ride in context.
    assert ag.GOAL_MARKER.match(task['goal']) and 'Which index' not in task['goal']
    assert 'execution' not in task and 'Question:\nWhich index?' in task['context'] and 'We tried B.' in task['context']
    assert 'read-only' in task['context']
    # The host ignores a caller's max_iterations, so none is sent or promised.
    assert request == {'tasks': [task], 'output_schema': ag.OUTPUT_SCHEMA}


def test_auto_backend_names_model_execution(tmp_path):
    guard, _, calls = make_guard(tmp_path, backend='model-router-auto')
    assert json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))['status'] == 'ok'
    assert calls[0]['tasks'][0]['execution'] == 'model'


def test_same_model_is_skipped_without_dispatch(tmp_path):
    guard, _, calls = make_guard(tmp_path, route={'provider': 'OpenAI-Codex', 'model': 'GPT-MAIN', 'reasoning': 'high'})
    reply = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
    assert reply['status'] == 'skipped' and reply['reason'] == 'same_model' and calls == []


@pytest.mark.parametrize('args,error', [
    ({}, 'invalid_question'), ({'question': ''}, 'invalid_question'), ({'question': 'x' * 4001}, 'invalid_question'),
    ({'question': 'q', 'context': 5}, 'invalid_context'), ({'question': 'q', 'extra': 1}, 'invalid_params'), ('q', 'invalid_params'),
])
def test_invalid_arguments_are_refused(tmp_path, args, error):
    guard, _, calls = make_guard(tmp_path)
    assert json.loads(guard.tool(args, session_id='parent-1'))['error'] == error and calls == []


def test_refusals_without_a_bound_parent_or_routing(tmp_path):
    guard, _, calls = make_guard(tmp_path)
    assert json.loads(guard.tool({'question': 'q'}, session_id='someone-else'))['error'] == 'bound_parent_required'
    guard, _, calls2 = make_guard(tmp_path, backend='default')
    assert json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))['error'] == 'routing_backend_required'
    guard, _, calls3 = make_guard(tmp_path)
    guard.ready = False
    assert json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))['error'] == 'guard_unavailable'
    assert not guard.available()
    assert calls == calls2 == calls3 == []
    assert make_guard(tmp_path)[0].available() and not make_guard(tmp_path, enabled=False)[0].available()


def test_an_unbound_child_discards_the_answer(tmp_path):
    def run(request, owner, kwargs):
        guard.on_subagent_start(parent_session_id=owner.session_id, child_session_id=None,
                                child_subagent_id='sa', child_goal=request['tasks'][0]['goal'])
        return json.dumps({'results': [{'status': 'completed', 'summary': 'leak?'}]})
    guard, _, _ = make_guard(tmp_path, run=run)
    reply = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
    assert reply == {'status': 'refused', 'error': 'guard_unbound', 'message': reply['message']} and 'leak' not in json.dumps(reply)


def test_a_refused_route_reports_without_advice(tmp_path):
    run = lambda request, owner, kwargs: json.dumps({'results': [{'status': 'error', 'error': 'route refused', 'route': {'refused': True}}]})
    guard, _, _ = make_guard(tmp_path, run=run)
    reply = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
    assert reply['status'] == 'refused' and reply['error'] == 'dispatch_refused'


def test_nested_and_exception_paths_never_raise(tmp_path):
    def run(request, owner, kwargs):
        return guard.tool({'question': 'inner'}, session_id='parent-1')
    guard, _, _ = make_guard(tmp_path, run=run)
    outer = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
    assert outer['status'] == 'refused'  # the inner call was refused as nested, so the outer saw no results
    def boom(request, owner, kwargs): raise RuntimeError('x')
    guard, _, _ = make_guard(tmp_path, run=boom)
    assert json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))['error'] == 'advisor_unavailable'


def test_registration_puts_hooks_before_the_tool_and_disables_the_tool_without_them(tmp_path):
    order = []
    class Ctx:
        def __init__(self, fail): self.fail = fail
        def register_hook(self, name, fn):
            if self.fail and name == 'subagent_start':
                raise RuntimeError('no hook')
            order.append(name)
            return SimpleNamespace(dispose=lambda: order.append('dispose:' + name))
        def register_tool(self, **kw): order.append('tool'); self.tool = kw
    ctx = Ctx(False)
    guard = ag.register_advise_guard(ctx, tmp_path, routing_enabled=lambda: True)
    assert order == ['pre_tool_call', 'subagent_start', 'post_compaction', 'tool'] and guard.ready
    assert ctx.tool['name'] == 'ask_advisor' and ctx.tool['check_fn']() is True and ctx.tool['toolset'] == 'model_router'
    order.clear()
    ctx = Ctx(True)
    guard = ag.register_advise_guard(ctx, tmp_path, routing_enabled=lambda: True)
    assert not guard.ready and ctx.tool['check_fn']() is False and 'dispose:pre_tool_call' in order


def test_default_dispatch_runs_through_middleware_synchronously(tmp_path, monkeypatch):
    from hermes_cli import middleware
    from tools import delegate_tool as dt
    seen = {}
    def fake_delegate(**kwargs):
        seen.update(kwargs)
        return '{"results": []}'
    def fake_chain(tool_name, args, terminal, **context):
        seen['chain'] = (tool_name, context)
        return terminal(args)
    monkeypatch.setattr(dt, 'delegate_task', fake_delegate)
    monkeypatch.setattr(middleware, 'run_tool_execution_middleware', fake_chain)
    parent = SimpleNamespace(session_id='parent-1')
    ag._run_delegation({'tasks': [{'goal': 'g'}]}, parent, {'task_id': 't', 'conversation_id': 'c'})
    assert seen['background'] is False and seen['parent_agent'] is parent and seen['tasks'] == [{'goal': 'g'}]
    tool_name, context = seen['chain']
    assert tool_name == 'delegate_task' and context['session_id'] == 'parent-1' and context['task_id'] == 't'


def test_questions_with_template_like_tokens_pass_the_host_batch_check(tmp_path):
    from tools.delegate_tool_tasks import _normalize_task_list
    seen = []
    def run(request, owner, kwargs):
        tasks, error = _normalize_task_list(None, None, request['tasks'], request['output_schema'], '', 2 ** 31 - 1)
        seen.append(error)
        return json.dumps({'error': 'stop here'})
    guard, _, _ = make_guard(tmp_path, run=run)
    for question in ('Should it be GET /users/{user_id}/orders?', 'Render <my-button> inside <app-root>?',
                     'Log f"{file_path}" or the relative path?', 'Use {two words} or <SNAKE_CASE>?'):
        guard.tool({'question': question, 'context': '{user_id} <my-button>'}, session_id='parent-1')
    assert seen == [None] * 4


def test_a_result_without_a_bound_start_is_discarded_not_reported_as_refused(tmp_path):
    run = lambda request, owner, kwargs: json.dumps({'results': [{'status': 'completed', 'summary': 'unguarded answer'}]})
    guard, _, _ = make_guard(tmp_path, run=run)
    reply = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
    assert reply['error'] == 'guard_unbound' and 'unguarded' not in json.dumps(reply)


def test_depth_limit_is_reported_as_its_own_code(tmp_path):
    for raw in ({'error': 'Delegation depth limit reached. Raise delegation.max_spawn_depth in config.yaml'},
                {'results': [{'status': 'error', 'error': 'Raise delegation.max_spawn_depth', 'route': {'refused': True}}]}):
        guard, _, _ = make_guard(tmp_path, run=lambda request, owner, kwargs, raw=raw: json.dumps(raw))
        reply = json.loads(guard.tool({'question': 'q'}, session_id='parent-1'))
        assert reply['error'] == 'depth_limit' and 'config.yaml' not in reply['message']


def test_padded_ids_and_the_task_id_are_still_bound(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    guard.tool({'question': 'q'}, session_id='parent-1')
    assert guard.pre_tool_call(tool_name='delegate_task', args={'action': 'continue', 'subagent_id': ' sa-1 '}, session_id='parent-1')['action'] == 'block'
    # A rotated session whose compaction event was lost is still caught by the child's task id.
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='rotated', task_id='sa-1')['action'] == 'block'
    assert guard.pre_tool_call(tool_name='terminal', args={}, session_id='other', task_id='other') is None


def test_bindings_outlive_the_guard_and_a_fresh_guard_binds_marked_children(tmp_path):
    guard, _, _ = make_guard(tmp_path)
    guard.tool({'question': 'q'}, session_id='parent-1')
    # A plugin reload builds a new guard: the earlier child stays bound.
    fresh, _, _ = make_guard(tmp_path)
    assert fresh.pre_tool_call(tool_name='write_file', args={}, session_id='child-1')['action'] == 'block'
    assert fresh.pre_tool_call(tool_name='delegate_task', args={'action': 'continue', 'subagent_id': 'sa-1'}, session_id='p')['action'] == 'block'
    # With no call record at all, a child carrying the advisor marker is bound anyway.
    fresh.on_subagent_start(parent_session_id='whoever', child_session_id='late-child', child_subagent_id='sa-late',
                            child_goal=ag._goal('0123456789ab'))
    assert fresh.pre_tool_call(tool_name='terminal', args={}, session_id='late-child')['action'] == 'block'
    fresh.on_subagent_start(parent_session_id='whoever', child_session_id='plain', child_subagent_id='sa-plain',
                            child_goal='Advisor consultation please')
    assert fresh.pre_tool_call(tool_name='terminal', args={}, session_id='plain') is None
    # Other profiles keep their own bindings.
    other_home = tmp_path / 'other'
    other_home.mkdir()
    other, _, _ = make_guard(other_home)
    assert other.pre_tool_call(tool_name='terminal', args={}, session_id='child-1') is None


def test_the_route_gate_refuses_an_asker_other_than_the_calling_parent(env):
    home, service = env
    current = {}
    seen = {}
    def run(request, owner, kwargs):
        goal = request['tasks'][0]['goal']
        current['parent'] = SimpleNamespace(session_id='advisor-child')  # inside the child's own turn
        seen['child'] = ag.advisor_call_active(home, goal)
        current['parent'] = owner
        seen['asker'] = ag.advisor_call_active(home, goal)
        return json.dumps({'error': 'stop here'})
    parent = SimpleNamespace(session_id='parent-1', provider='openai-codex', model='gpt-main')
    current['parent'] = parent
    guard = ag.AdviseGuard(home, get_active_parent=lambda: current['parent'], dispatch_backend=lambda _p: 'model-router',
                           resolve_route=lambda: {'provider': 'p', 'model': 'm', 'reasoning': 'high'}, run_delegation=run)
    guard.ready = True
    guard.tool({'question': 'q'}, session_id='parent-1')
    assert seen == {'child': False, 'asker': True}
