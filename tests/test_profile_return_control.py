"""Coordinator state tests with an explicitly inert channel/process witness.

Crypto/ACL/helper and real-owner proof are separate; this harness does not
manufacture evidence for either. Actual plugin journal/controller remain real.
"""
import copy
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from tests.test_profile_jobs import env, grant, args, wait
from model_router.profile_return_control import ReturnCoordinator


class MemoryChannel:
    def __init__(self, home, return_id):
        self.path = Path(home) / return_id
        self.records = {}
        self.mutex = threading.RLock()
        self.fail_activated = False
    @classmethod
    def create(cls, home, return_id):
        return cls(home, return_id)
    def lock(self):
        return self.mutex
    def read(self, name):
        return copy.deepcopy(self.records.get(name))
    def write(self, name, value, exclusive=False):
        if self.fail_activated and name == 'activated':
            raise OSError('fixture local write failure')
        if exclusive and name in self.records:
            raise ValueError('fixture existing record')
        self.records[name] = copy.deepcopy(value)
    def verify_ready(self, challenge, ready):
        return bool(challenge and ready == {'fixture_ready': challenge['challenge']})
    def close(self):
        pass


def meta(call='prepare-call', api='api-1', **overrides):
    return {'task_id': 'trusted-task', 'turn_id': 'trusted-turn', 'api_request_id': api,
            'tool_call_id': call, 'session_id': 'parent', 'conversation_id': 'parent', **overrides}


@pytest.fixture
def controller(env):
    grant(env)
    witness = {'session_id': 'proc-fixture', 'owner_task_id': 'trusted-task', 'status': 'running',
               'started_at': '2026-11-14T00:00:00+09:00', 'notify_on_complete': True}
    reads = []
    def dispatch(name, body, **kwargs):
        assert name == 'process_manage' and body == {'action': 'list'}
        assert kwargs == {'task_id': 'trusted-task'}
        reads.append(True)
        return json.dumps({'processes': [witness]})
    env.ctx.dispatch_tool = dispatch
    co = ReturnCoordinator(env.manager, channel_type=MemoryChannel,
                           command_factory=lambda home, rid: 'fixture-helper-' + rid)
    co.handles = [SimpleNamespace(active=True) for _ in range(3)]
    env.manager.return_controller = co
    return env, co, witness, reads


def invoke(env, body, kw):
    """Native shape: full IDs on middleware/hooks, three on the handler."""
    from model_router.profile_jobs import JobError
    co = env.manager.return_controller
    co.pre(**(kw | {'tool_name': 'profile_task', 'args': body}))
    actual_handler_kwargs = {key: kw[key] for key in ('task_id', 'session_id', 'conversation_id') if key in kw}
    downstream = lambda payload: env.manager.tool(payload, **actual_handler_kwargs)
    try:
        raw = co.middleware('profile_task', body, downstream, **kw)
    except JobError:
        # Native middleware fails open before next_call; the missing bound
        # request context must still make the product handler fail closed.
        raw = downstream(body)
    co.post(**(kw | {'tool_name': 'profile_task', 'args': body, 'status': 'ok', 'result': raw}))
    return json.loads(raw)


def prepare(controller, **extra):
    env, co, _, _ = controller
    body = args() | {'action': 'prepare', 'wait_seconds': 300, **extra}
    reply = invoke(env, body, meta())
    assert 'return_id' in reply, reply
    return body, reply, co.channels[reply['return_id']]


def launch(co, reply):
    kw = meta('terminal-call', 'api-2') | {'tool_name': 'terminal', 'args': reply['terminal']}
    assert co.pre(**kw) is None
    co.post(**(kw | {'status': 'ok', 'result': json.dumps({'session_id': 'proc-fixture', 'notify_on_complete': True})}))


def witness_and_ready(controller, channel):
    _, co, witness, _ = controller
    co.post(**(meta('list-call', 'api-3') | {'tool_name': 'process_manage', 'args': {'action': 'list'},
        'status': 'ok', 'result': json.dumps({'processes': [witness]})}))
    challenge = channel.read('challenge')
    assert challenge
    channel.write('ready', {'fixture_ready': challenge['challenge']})


def activate(env, reply, **kw):
    return invoke(env, args() | {'return_id': reply['return_id']}, meta('activate-call', 'api-4', **kw))


def test_prepare_has_no_target_effect_and_full_normal_witness_is_required(controller):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    assert not env.gateway.calls and not env.manager.threads
    assert reply['completion_scope'] == 'parent_session_lifetime'
    assert reply['terminal']['persist_on_release'] is False
    launch(co, reply)
    # A fabricated ready object cannot replace the normal process-list hook.
    channel.write('ready', {'fixture_ready': 'not-a-normal-witness'})
    refused = activate(env, reply)
    assert refused['status'] == 'refused' and refused['error'] == 'return_not_ready'
    assert not reads and not env.gateway.calls
    witness_and_ready(controller, channel)
    accepted = activate(env, reply)
    assert accepted['return_state'] == 'submitted' and accepted['terminal'] is None
    wait(env, reply['job']['id'])
    assert len(reads) == 1
    assert sum(method == 'prompt.submit' for method, _ in env.gateway.calls) == 1
    again = activate(env, reply)
    assert again['return_state'] == 'submitted' and len(reads) == 1
    assert sum(method == 'prompt.submit' for method, _ in env.gateway.calls) == 1
    assert not any(secret in json.dumps(accepted) for secret in ('PRIVATE_TASK_INPUT', 'PRIVATE_CONTEXT_INPUT', channel.read('challenge')['challenge']))


def test_prepare_idempotent_only_in_same_unlaunched_task_turn(controller):
    env, _, _, _ = controller
    body, first, _ = prepare(controller)
    same = invoke(env, body, meta('retry-call', 'another-api'))
    assert same['return_id'] == first['return_id']
    foreign = invoke(env, body, meta('retry-call', task_id='another-task'))
    assert foreign['status'] == 'refused' and foreign['error'] == 'return_source_changed'
    assert not env.gateway.calls


@pytest.mark.parametrize('change', [{'task_id': 'another-task'}, {'turn_id': 'another-turn'}])
def test_other_task_or_turn_cannot_activate(controller, change):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    launch(co, reply)
    witness_and_ready(controller, channel)
    refused = activate(env, reply, **change)
    assert refused['error'] == 'return_source_changed' and not reads and not env.gateway.calls


def test_unrelated_child_hook_does_not_poison_own_parent_generation(controller):
    env, co, _, _ = controller
    _, reply, channel = prepare(controller)
    blocked = co.pre(**(meta('child-call', session_id='child', conversation_id='parent') | {'tool_name': 'terminal', 'args': reply['terminal']}))
    assert blocked['action'] == 'block'
    assert co.healthy and channel.read('state')['phase'] == 'issued'
    launch(co, reply)
    witness_and_ready(controller, channel)
    assert activate(env, reply)['return_state'] == 'submitted'


@pytest.mark.parametrize('notify', [False, None])
def test_notify_refusal_prevents_admission(controller, notify):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    kw = meta('terminal-call', 'api-2') | {'tool_name': 'terminal', 'args': reply['terminal']}
    co.pre(**kw)
    result = {'session_id': 'proc-fixture'}
    if notify is not None:
        result['notify_on_complete'] = notify
    co.post(**(kw | {'status': 'ok', 'result': json.dumps(result)}))
    assert channel.read('state')['phase'] == 'invalid'
    assert activate(env, reply)['error'] == 'return_not_ready'
    assert not reads and not env.gateway.calls


def test_duplicate_helper_launch_invalidates_unconsumed_generation(controller):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    launch(co, reply)
    block = co.pre(**(meta('duplicate-call', 'api-3') | {'tool_name': 'terminal', 'args': reply['terminal']}))
    assert block['action'] == 'block' and channel.read('state')['phase'] == 'invalid'
    assert activate(env, reply)['error'] == 'return_not_ready'
    assert not reads and not env.gateway.calls


def test_native_birth_witness_is_exact_string_not_a_pid_heuristic(controller):
    env, co, witness, _ = controller
    _, reply, channel = prepare(controller)
    launch(co, reply)
    witness_and_ready(controller, channel)
    witness['started_at'] = '2026-11-14T00:00:01+09:00'
    assert activate(env, reply)['error'] == 'return_native_witness_changed'
    assert not env.gateway.calls


def test_expired_readiness_is_not_renewed_from_wall_clock_state(controller, monkeypatch):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    launch(co, reply)
    witness_and_ready(controller, channel)
    deadline = co.leases[reply['return_id']][0]
    monkeypatch.setattr('model_router.profile_return_control.time',
        SimpleNamespace(time=time.time, monotonic=lambda: deadline + 1))
    assert activate(env, reply)['error'] == 'return_readiness_expired'
    assert not reads and not env.gateway.calls


def test_lost_activation_flag_ack_never_replays_target(controller):
    env, co, _, _ = controller
    _, reply, channel = prepare(controller)
    launch(co, reply)
    witness_and_ready(controller, channel)
    channel.fail_activated = True
    unknown = activate(env, reply)
    assert unknown['status'] == 'unknown' and unknown['error'] == 'return_activation_unknown'
    wait(env, reply['job']['id'])
    again = activate(env, reply)
    assert again['error'] == 'return_activation_unknown'
    assert sum(method == 'session.create' for method, _ in env.gateway.calls) == 1
    assert sum(method == 'prompt.submit' for method, _ in env.gateway.calls) == 1


@pytest.mark.parametrize('field', ['task_id', 'turn_id', 'api_request_id', 'tool_call_id'])
def test_prompt_ids_do_not_replace_missing_framework_binding(controller, field):
    env, _, _, _ = controller
    kw = meta()
    kw.pop(field)
    denied = invoke(env, args() | {'action': 'prepare', 'wait_seconds': 300}, kw)
    assert denied['error'] == 'return_framework_binding_required'
    assert not env.manager.journal.path.exists() and not env.gateway.calls


def test_handler_cannot_supply_full_ids_without_normal_middleware(controller):
    env, _, _, _ = controller
    denied = json.loads(env.manager.tool(args() | {'action': 'prepare', 'wait_seconds': 300}, **meta()))
    assert denied['error'] == 'return_framework_binding_required'
    assert not env.manager.journal.path.exists() and not env.gateway.calls


def test_middleware_context_is_one_use_and_never_leaks_after_next(controller):
    env, co, _, _ = controller
    body = args() | {'action': 'prepare', 'wait_seconds': 300}
    kw = {k: meta()[k] for k in ('task_id', 'session_id', 'conversation_id')}
    replies = []
    def downstream(payload):
        replies.append(json.loads(env.manager.tool(payload, **kw)))
        replies.append(json.loads(env.manager.tool(payload, **kw)))
        return json.dumps(replies[0])
    co.middleware('profile_task', body, downstream, **meta())
    assert 'return_id' in replies[0]
    assert replies[1]['error'] == 'return_framework_binding_required'
    assert co.request_context.get() is None and not env.gateway.calls


def test_tampered_ready_and_terminal_args_do_not_admit(controller):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    changed = reply['terminal'] | {'notify': False}
    blocked = co.pre(**(meta('tampered-launch') | {'tool_name': 'terminal', 'args': changed}))
    assert blocked['action'] == 'block' and channel.read('state')['phase'] == 'issued'
    launch(co, reply)
    witness_and_ready(controller, channel)
    channel.write('ready', {'fixture_ready': 'wrong-generation-proof'})
    assert activate(env, reply)['error'] == 'return_not_ready'
    assert not reads and not env.gateway.calls


def test_corrupt_state_job_reference_is_refused_before_read_or_target(controller):
    env, co, _, reads = controller
    _, reply, channel = prepare(controller)
    state = channel.read('state')
    state['job_id'] = 'f' * 32
    channel.write('state', state)
    refused = activate(env, reply)
    assert refused['status'] == 'refused'
    assert not reads and not env.gateway.calls


def test_close_attempts_all_channel_and_hook_cleanup(controller):
    _, co, _, _ = controller
    _, _, channel = prepare(controller)
    disposed = []
    def broken_close():
        raise OSError('fixture cleanup failure')
    channel.close = broken_close
    co.handles = [SimpleNamespace(active=True, dispose=lambda: disposed.append(1)),
                  SimpleNamespace(active=True, dispose=lambda: disposed.append(2))]
    co.close()
    assert co.closed and not co.healthy and disposed == [1, 2]


def test_persistence_boolean_does_not_create_operator_consent(controller):
    env, _, _, _ = controller
    body = args() | {'action': 'prepare', 'wait_seconds': 300, 'persist_on_release': True}
    denied = invoke(env, body, meta())
    assert denied['error'] == 'return_persistence_consent_required'
    assert not env.manager.journal.path.exists() and not env.gateway.calls
