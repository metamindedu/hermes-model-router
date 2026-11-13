"""Deterministic canonical-protocol fixtures, not provider or production runs."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from model_router.profile_jobs import ProfileJobs, JobError, CLIENT_NAME, register_profile_jobs
from model_router.gateway_protocol_client import GatewayProtocolError


class Context:
    def __init__(self, home=None):
        self.home = home
        self.settings = None
        self.writes = 0
        self.events = []
        self.rpcs = {}
        self.hooks = {}
        self.tools = {}
    def get_config(self, key, default=None):
        assert key == 'profile_jobs'
        return copy.deepcopy(self.settings) if self.settings is not None else default
    def set_config(self, key, value):
        assert key == 'profile_jobs'
        self.settings = copy.deepcopy(value)
        assert self.home is not None, 'settings writer requires a raw fixture home'
        raw = {'plugins': {'entries': {'model-router': {'settings': {'profile_jobs': value}}}}}
        (self.home / 'config.yaml').write_text(json.dumps(raw), encoding='utf-8')
        self.writes += 1
    def emit_to_session(self, sid, name, payload):
        self.events.append((sid, name, copy.deepcopy(payload)))
        return True
    def register_rpc(self, name, handler):
        self.rpcs[name] = handler
        return SimpleNamespace(active=True)
    def register_hook(self, name, handler):
        self.hooks[name] = handler
        return SimpleNamespace(active=True)
    def on_unload(self, callback):
        self.unload = callback
        return SimpleNamespace(active=True)
    def register_tool(self, **kwargs):
        self.tools[kwargs['name']] = kwargs
        return SimpleNamespace(active=True)


class Gateway:
    def __init__(self):
        self.calls = []
        self.sessions = {}
        self.creates = {}
        self.inputs = {}
        self.lock = threading.RLock()
        self.fail = {}
        self.bad_receipt = None

        self.phase_check = None
        self.block_create = None
        self.connect_error = None
    def factory(self, **kwargs):
        if self.connect_error:
            raise self.connect_error
        return Client(self, kwargs['profile'])
    def receipt(self, sid):
        state = self.sessions[sid]
        value = {'admission_id': state['admission'], 'ref': {'profile_id': 'fixture-profile', 'session_id': sid},
            'sequence': 1, 'status': state['status'], 'outcome': state.get('outcome'), 'authority_epoch': 1,
            'execution_generation': 1 if state['status'] != 'queued' else None}
        if state['status'] == 'terminal':
            value['result'] = copy.deepcopy(state.get('result'))
        if self.bad_receipt:
            self.bad_receipt(value)
        return value
    def finish(self, sid, text='fixture result', outcome='completed', **extra):
        with self.lock:
            self.sessions[sid].update(status='terminal', outcome=outcome,
                result={'final_response': text, 'messages': ['PRIVATE_TOOL_BODY'], 'reasoning': 'PRIVATE_REASONING', **extra})
    def call(self, method, params):
        with self.lock:
            self.calls.append((method, copy.deepcopy(params)))
            if self.phase_check:
                self.phase_check(method, params)
            if method == 'session.create':
                assert set(params) == {'request_id', 'source', 'cwd', 'client'}
                assert params['source'] == 'tool' and params['client']['name'] == CLIENT_NAME
                sid = self.creates.setdefault(params['request_id'], 'target-' + params['request_id'])
                self.sessions.setdefault(sid, {'status': 'queued', 'admission': None, 'prompts': []})
                reply = {'session_id': sid, 'stored_session_id': sid}
            elif method == 'prompt.submit':
                sid = params['session_id']
                admission = self.inputs.setdefault(params['submission_id'], 'admission-' + params['submission_id'])
                self.sessions[sid].update(status='started', admission=admission)
                reply = self.receipt(sid)
            elif method == 'prompt.receipt':
                assert self.sessions[params['session_id']]['admission'] == params['admission_id']
                reply = self.receipt(params['session_id'])
            elif method == 'session.resume':
                assert params['omit_messages'] is True
                sid = params['session_id']
                reply = {'session_id': sid, 'stored_session_id': sid, 'execution_generation': 1,
                    'prompts': copy.deepcopy(self.sessions[sid]['prompts']), 'messages': [], 'open_requests': []}
            elif method == 'prompt.cancel':
                sid = params['session_id']
                assert params['admission_id'] == self.sessions[sid]['admission']
                self.finish(sid, '', 'cancelled')
                reply = self.receipt(sid)
            elif method == 'session.steer':
                assert params['execution_generation'] == 1
                reply = {'ref': {'profile_id': 'fixture-profile', 'session_id': params['session_id']}, 'execution_generation': 1}
            elif method in ('approval.respond', 'clarify.respond'):
                sid = params['session_id']
                assert params['execution_generation'] == 1
                assert any(p['prompt_id'] == params['prompt_id'] for p in self.sessions[sid]['prompts'])
                self.sessions[sid]['prompts'] = []
                reply = {'status': 'resolved', 'prompt_id': params['prompt_id']}
            else:
                raise AssertionError('unexpected canonical call ' + method)
            if method in self.fail:
                raise self.fail[method]
            return reply


class Client:
    profile_id = 'fixture-profile'
    instance_id = 'fixture-instance'
    authority_epoch = 1
    description = {'profile_id': profile_id, 'instance_id': instance_id, 'authority_epoch': 1,
        'capabilities': ['durable-admission-v1', 'event-replay-v1', 'session-client-v1', 'session-transcript-v1'],
        'session_create': {'sources': ['tool'], 'parameters': ['source', 'cwd', 'request_id', 'client']}}
    def __init__(self, gateway, profile):
        self.gateway, self.profile, self.closed = gateway, profile, False
    def call(self, method, params, timeout=10):
        if self.closed:
            raise GatewayProtocolError('closed')
        return self.gateway.call(method, params)
    def drain_events(self):
        return [{'method': 'transport.event_gap', 'params': {}}]
    def close(self):
        self.closed = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    worker = home / 'profiles/worker'
    worker.mkdir(parents=True)
    cwd = tmp_path / 'workspace'
    cwd.mkdir()
    (home / 'config.yaml').write_text('{}', encoding='utf-8')
    (worker / 'config.yaml').write_text('terminal:\n  cwd: ' + str(cwd).replace('\\', '/') + '\n', encoding='utf-8')
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda **kwargs: home)
    monkeypatch.setattr('hermes_cli.plugin_session.session_surface', lambda: 'cli')
    token = set_hermes_home_override(home)
    ctx, gateway = Context(home), Gateway()
    manager = ProfileJobs(ctx, home, client_factory=gateway.factory, alive=lambda: True, poll_seconds=.02)

    instances = [manager]
    yield SimpleNamespace(home=home, cwd=cwd, ctx=ctx, gateway=gateway, manager=manager, instances=instances)
    for instance in instances:
        instance.close()
        for thread in instance.threads.values():
            thread.join(timeout=3)
            assert not thread.is_alive()
    reset_hermes_home_override(token)


def grant(env):
    p = env.manager.policy
    return p.configure({'expected_revision': p.describe()['revision'], 'enabled': True,
        'targets': ['worker'], 'acknowledge_scope': True})


def args(request='request-1', **kwargs):
    return {'action': 'start', 'profile': 'worker', 'request_id': request, 'goal': 'PRIVATE_TASK_INPUT', 'context': 'PRIVATE_CONTEXT_INPUT', **kwargs}


def start(env, request='request-1'):
    grant(env)
    return env.manager.start(args(request), 'parent', 'parent')


def wait(env, jid, predicate=lambda j: j.get('admission_id') is not None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = env.manager.journal.read()['jobs'][jid]
        if predicate(record):
            return record
        time.sleep(.01)
    raise AssertionError('fixture condition not met')


def test_registration_and_empty_grants_are_inert(env):
    before = sorted(str(p.relative_to(env.home)) for p in env.home.rglob('*'))
    ctx = Context()
    manager = register_profile_jobs(ctx, env.home)
    assert manager is not None and manager.alive()
    assert not ctx.tools['profile_task']['check_fn']()
    assert sorted(str(p.relative_to(env.home)) for p in env.home.rglob('*')) == before
    assert not env.gateway.calls and ctx.writes == 0
    reply = json.loads(manager.tool(args(), session_id='parent', conversation_id='parent'))
    assert reply['status'] == 'refused' and not manager.journal.path.exists()
    assert not manager.threads
    manager.close()


def test_start_durable_before_every_effect_and_literal_profile_policy(env):
    def check(method, payload):
        rows = env.manager.journal.read()['jobs']
        assert len(rows) == 1
        record = next(iter(rows.values()))
        if method == 'session.create':
            assert record['create_id'] == payload['request_id'] and record['pending_operation'] == 'create'
        elif method == 'prompt.submit':
            assert record['target_session_id'] == payload['session_id']
            assert record['submission_id'] == payload['submission_id'] and record['pending_operation'] == 'submit'
    env.gateway.phase_check = check
    j = start(env); record = wait(env, j['id'])
    assert record['cwd'] == str(env.cwd).replace('\\', '/')
    assert record['gateway_profile_id'] == 'fixture-profile'
    for method, payload in env.gateway.calls:
        assert not (set(payload) & {'model', 'provider', 'toolsets', 'yolo', 'ignore_rules', 'api_key', 'editor'})
    state = env.manager.journal.path.read_text(encoding='utf-8')
    assert 'PRIVATE_TASK_INPUT' not in state and 'PRIVATE_CONTEXT_INPUT' not in state


def test_same_request_concurrent_starts_submit_once_and_mismatch_refuses(env):
    grant(env)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: env.manager.start(args(), 'parent', 'parent'), range(4)))
    assert len({j['id'] for j in jobs}) == 1
    wait(env, jobs[0]['id'])
    assert sum(m == 'session.create' for m, _ in env.gateway.calls) == 1
    assert sum(m == 'prompt.submit' for m, _ in env.gateway.calls) == 1
    with pytest.raises(JobError, match='request_id_conflict'):
        env.manager.start(args(goal='different'), 'parent', 'parent')


@pytest.mark.parametrize('method', ['session.create', 'prompt.submit'])
def test_lost_ack_is_unknown_never_resubmitted(env, method):
    env.gateway.fail[method] = GatewayProtocolError('rpc_timeout', ambiguous=True, sent=True)
    j = start(env); wait(env, j['id'], lambda r: r['status'] == 'unknown')
    prior = list(env.gateway.calls)
    duplicate = env.manager.start(args(), 'parent', 'parent')
    assert duplicate['id'] == j['id'] and duplicate['status'] == 'unknown'
    assert env.gateway.calls == prior
    assert sum(m == method for m, _ in prior) == 1


def test_bad_receipt_ref_is_not_adopted(env):
    env.gateway.bad_receipt = lambda value: value['ref'].update(session_id='foreign-parent')
    j = start(env); record = wait(env, j['id'], lambda r: r['status'] == 'unknown')
    assert record['admission_id'] is None
    assert sum(m == 'prompt.submit' for m, _ in env.gateway.calls) == 1


def test_visible_result_only_and_empty_is_authoritative(env):
    j = start(env); record = wait(env, j['id'])
    env.gateway.finish(record['target_session_id'], '')
    wait(env, j['id'], lambda r: r['status'] == 'completed')
    output = env.manager.result('parent', j['id'])
    assert output['result']['text'] == '' and output['job']['result_available']
    serialized = env.manager.journal.path.read_text(encoding='utf-8')
    assert 'PRIVATE_TOOL_BODY' not in serialized and 'PRIVATE_REASONING' not in serialized
    with pytest.raises(JobError, match='job_not_owned'):
        env.manager.result('another-parent', j['id'])


def test_readonly_listing_result_do_not_connect_or_launch(env):
    j = start(env); record = wait(env, j['id'])
    env.gateway.finish(record['target_session_id'])
    wait(env, j['id'], lambda r: r['status'] == 'completed')
    before = list(env.gateway.calls)
    assert env.manager.listing('parent')['jobs']
    assert env.manager.listing('foreign')['jobs'] == []
    assert env.manager.result('parent', j['id'])['result']['text'] == 'fixture result'
    assert env.gateway.calls == before


def test_revoke_blocks_new_start_steer_and_allow_but_exact_stop_survives(env):
    j = start(env); record = wait(env, j['id'])
    p = env.manager.policy
    p.configure({'expected_revision': p.describe()['revision'], 'enabled': False, 'targets': [], 'acknowledge_scope': True})
    before = sum(m in ('prompt.submit', 'session.steer') for m, _ in env.gateway.calls)
    with pytest.raises(PermissionError):
        env.manager.start(args('new-request'), 'parent', 'parent')
    with pytest.raises(JobError):
        env.manager.control('parent', {'job_id': j['id'], 'operation': 'steer', 'text': 'do not send'})
    assert before == sum(m in ('prompt.submit', 'session.steer') for m, _ in env.gateway.calls)
    output = env.manager.control('parent', {'job_id': j['id'], 'operation': 'stop'})
    assert output['status'] == 'cancelled'
    assert any(m == 'prompt.cancel' and p['admission_id'] == record['admission_id'] for m, p in env.gateway.calls)


def test_even_internal_human_flags_cannot_relay_approval_or_clarify(env):
    j = start(env); record = wait(env, j['id']); sid = record['target_session_id']
    env.gateway.sessions[sid]['prompts'] = [{'kind': 'approval', 'prompt_id': 'approval-current', 'execution_generation': 1,
        'description': 'Fixture operation', 'command': 'echo fixture', 'choices': ['once', 'session', 'always', 'deny']}]
    wait(env, j['id'], lambda r: r['status'] == 'approval_wait')
    body = {'job_id': j['id'], 'operation': 'approve', 'prompt_id': 'approval-current', 'choice': 'once'}
    with pytest.raises(JobError, match='operator_authority_unavailable'):
        env.manager.control('parent', body)
    with pytest.raises(JobError):
        env.manager.control('parent', {**body, 'choice': 'always'}, human=True)
    with pytest.raises(JobError):
        env.manager.control('parent', {**body, 'prompt_id': 'old-prompt'}, human=True)
    with pytest.raises(JobError, match='operator_authority_unavailable'):
        env.manager.control('parent', body, human=True)
    assert sum(m == 'approval.respond' for m, _ in env.gateway.calls) == 0
    env.gateway.sessions[sid]['prompts'] = [{'kind': 'clarify', 'prompt_id': 'clarify-current', 'execution_generation': 1,
        'question': 'Fixture question?', 'choices': ['one', 'two']}]
    wait(env, j['id'], lambda r: r['status'] == 'clarify_wait')
    with pytest.raises(JobError, match='operator_authority_unavailable'):
        env.manager.control('parent', {'job_id': j['id'], 'operation': 'clarify', 'prompt_id': 'clarify-current', 'answer': 'one'}, human=True)
    assert sum(m == 'clarify.respond' for m, _ in env.gateway.calls) == 0


@pytest.mark.parametrize('shape', ['long-command', 'long-description', 'structured-edit'])
def test_incomplete_approval_projection_stays_non_approvable_without_relay(env, shape):
    job = start(env); record = wait(env, job['id'])
    prompt = {'kind': 'approval', 'prompt_id': 'incomplete-approval', 'execution_generation': 1,
        'description': 'Review operation', 'command': 'fixture-only', 'choices': ['once', 'deny']}
    if shape == 'long-command':
        prompt['command'] = 'printf safe ' + 'x' * 8300 + '; rm -rf ./valuable-data'
    elif shape == 'long-description':
        prompt['description'] = 'x' * 8300
        prompt['command'] = 'rm -rf ./valuable-data'
    else:
        prompt['edit'] = {'path': 'settings.json', 'old_text': '{"guard":true}', 'new_text': '{"guard":false}'}
    env.gateway.sessions[record['target_session_id']]['prompts'] = [prompt]
    current = wait(env, job['id'], lambda r: r['status'] == 'approval_wait')
    assert current['pending_request']['choices'] == ['deny']
    assert len(current['pending_request']['text']) <= 8192
    assert '허용 차단' in current['pending_request']['text']
    assert env.manager.view(current)['can_approve'] is False
    with pytest.raises(JobError):
        env.manager.control('parent', {'job_id': job['id'], 'operation': 'approve',
            'prompt_id': prompt['prompt_id'], 'choice': 'once'}, human=True)
    assert all(m != 'approval.respond' for m, _ in env.gateway.calls)
    with pytest.raises(JobError, match='operator_authority_unavailable'):
        env.manager.control('parent', {'job_id': job['id'], 'operation': 'approve',
            'prompt_id': prompt['prompt_id'], 'choice': 'deny'}, human=True)
    assert sum(m == 'approval.respond' for m, _ in env.gateway.calls) == 0


def test_unknown_steer_is_not_replayed_and_cannot_be_sent_again(env):
    j = start(env); wait(env, j['id'])
    env.gateway.fail['session.steer'] = GatewayProtocolError('rpc_timeout', sent=True, ambiguous=True)
    with pytest.raises(JobError) as exc:
        env.manager.control('parent', {'job_id': j['id'], 'operation': 'steer', 'text': 'one intent'})
    assert exc.value.unknown
    env.gateway.fail.clear()
    with pytest.raises(JobError):
        env.manager.control('parent', {'job_id': j['id'], 'operation': 'steer', 'text': 'one intent'})
    assert sum(m == 'session.steer' for m, _ in env.gateway.calls) == 1


def test_source_restart_refresh_adopts_only_exact_existing_admission(env):
    j = start(env); record = wait(env, j['id'])
    env.manager.close()
    for thread in env.manager.threads.values(): thread.join(timeout=3)
    calls_before = [m for m, _ in env.gateway.calls if m in ('session.create', 'prompt.submit', 'prompt.cancel')]
    replacement = ProfileJobs(env.ctx, env.home, client_factory=env.gateway.factory, alive=lambda: True, poll_seconds=.02)
    env.instances.append(replacement)
    assert replacement.listing('parent')['jobs'][0]['status'] == 'unknown'
    output = replacement.control('parent', {'job_id': j['id'], 'operation': 'refresh'})
    assert output['status'] == 'running'
    assert [m for m, _ in env.gateway.calls if m in ('session.create', 'prompt.submit', 'prompt.cancel')] == calls_before
    env.gateway.finish(record['target_session_id'])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and replacement.journal.read()['jobs'][j['id']]['status'] != 'completed': time.sleep(.01)
    assert replacement.result('parent', j['id'])['result']['text'] == 'fixture result'


def test_tool_parent_binding_compaction_alias_and_recursive_denial(env, monkeypatch):
    grant(env)
    assert json.loads(env.manager.tool(args(), session_id='native-child', conversation_id='parent'))['status'] == 'refused'
    reply = json.loads(env.manager.tool(args(), session_id='parent', conversation_id='parent'))
    jid = reply['job']['id']; wait(env, jid)
    env.manager.compacted(old_session_id='parent', session_id='new-parent-segment')
    status = json.loads(env.manager.tool({'action': 'status'}, session_id='new-parent-segment', conversation_id='parent'))
    assert status['jobs'][0]['id'] == jid
    monkeypatch.setattr('hermes_cli.plugin_session.session_client', lambda: {'name': CLIENT_NAME})
    blocked = json.loads(env.manager.tool(args('another'), session_id='new-parent', conversation_id='new-parent'))
    assert blocked['error'] == 'recursive_profile_job_denied'


def test_rpc_literal_scope_assertions_and_no_agent_settings_actions(env):
    assert env.manager.rpc('list', {'session_id': 'foreign'}, session_id='parent')['status'] == 'refused'
    assert env.manager.rpc('describe', {'profile': 'worker'})['status'] == 'refused'
    reply = env.manager.tool({'action': 'configure', 'enabled': True}, session_id='parent', conversation_id='parent')
    assert json.loads(reply)['status'] == 'refused' and env.ctx.writes == 0


def test_native_plugin_context_registers_inert_real_public_handles(env):
    from hermes_cli.plugins import PluginManager, PluginContext
    from hermes_cli.plugins_manifest import parse_manifest_file
    source = Path(__file__).resolve().parents[1]
    manifest = parse_manifest_file(source / 'plugin.yaml', source, 'user', '')
    assert manifest is not None
    host = PluginManager(scope_key=str(env.home))
    ctx = PluginContext(manifest, host)
    before = (env.home / 'config.yaml').read_bytes()
    manager = None
    try:
        manager = register_profile_jobs(ctx, env.home)
        assert manager is not None and manager.alive()
        assert not manager.available() and not manager.journal.path.exists()
        assert manager.policy.describe()['policy']['enabled'] is False
        assert (env.home / 'config.yaml').read_bytes() == before
    finally:
        host.unload()
        if manager is not None:
            assert not manager.alive()


def test_workspace_exclusion_and_terminal_release(env):
    first = start(env); record = wait(env, first['id'])
    second = env.manager.start(args('second'), 'another-parent', 'another-parent')
    refused = wait(env, second['id'], lambda r: r['status'] == 'failed')
    assert refused['reason_code'] == 'workspace_busy'
    assert sum(m == 'session.create' for m, _ in env.gateway.calls) == 1
    env.gateway.finish(record['target_session_id'])
    wait(env, first['id'], lambda r: r['status'] == 'completed')
    env.manager.threads[first['id']].join(timeout=3)
    third = env.manager.start(args('third'), 'another-parent', 'another-parent')
    wait(env, third['id'])
    assert sum(m == 'prompt.submit' for m, _ in env.gateway.calls) == 2


def test_cancel_during_create_never_submits_and_releases_workspace(env):
    entered, proceed = threading.Event(), threading.Event()
    def check(method, payload):
        if method == 'session.create':
            entered.set()
            assert proceed.wait(3)
    env.gateway.phase_check = check
    j = start(env)
    try:
        assert entered.wait(3)
        reply = env.manager.control('parent', {'job_id': j['id'], 'operation': 'stop'})
        assert reply['status'] == 'stop_requested'
    finally:
        proceed.set()
    wait(env, j['id'], lambda r: r['status'] == 'cancelled')
    env.manager.threads[j['id']].join(timeout=3)
    assert all(m != 'prompt.submit' for m, _ in env.gateway.calls)
    assert json.loads(env.manager.workspaces.path.read_text())['claims'] == {}


def test_unknown_submission_keeps_workspace_claim(env):
    env.gateway.fail['prompt.submit'] = GatewayProtocolError('rpc_timeout', sent=True, ambiguous=True)
    j = start(env); wait(env, j['id'], lambda r: r['status'] == 'unknown')
    next_job = env.manager.start(args('new-intent'), 'other-parent', 'other-parent')
    refused = wait(env, next_job['id'], lambda r: r['status'] == 'failed')
    assert refused['reason_code'] == 'workspace_busy'
    assert len(json.loads(env.manager.workspaces.path.read_text())['claims']) == 1


def test_atomic_journal_read_write_contention_is_not_observer_failure(env):
    j = start(env); wait(env, j['id'])
    def reader(_):
        for _ in range(30):
            assert env.manager.journal.read()['jobs'][j['id']]['status'] not in ('failed', 'unknown')
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(reader, range(5)))


def test_native_plugin_rpc_capability_and_exact_local_session_owner_gate(env):
    import asyncio
    from gateway.session_authority import SessionAuthority
    from gateway.session_contract import SessionActor, SessionRef
    from gateway.session_plugin_rpc import call_plugin_rpc
    from gateway.config import Platform
    from hermes_state_runtime import RuntimeStoreError
    authority = object.__new__(SessionAuthority)
    authority.profile_id = str(env.home)
    authority.runner = None
    authority.sessions = {'parent': SimpleNamespace(source=SimpleNamespace(platform=Platform.LOCAL, user_id='owner'))}
    ref = SessionRef(str(env.home), 'parent')
    called = []
    def handler(params, *, session_id=None):
        called.append(session_id)
        return env.manager.rpc('list', params, session_id=session_id)
    for actor in (SessionActor('owner', str(env.home), frozenset(), 'fixture'),
                  SessionActor('other', str(env.home), frozenset({'session:control'}), 'fixture'),
                  SessionActor('owner', 'wrong-profile', frozenset({'session:control'}), 'fixture')):
        connection = SimpleNamespace(authority=authority, actor=actor)
        with pytest.raises(RuntimeStoreError):
            asyncio.run(call_plugin_rpc(connection, ref, 'plugin.model-router.profile_jobs.list', handler, {'session_id': 'parent'}))
    assert called == []
    actor = SessionActor('owner', str(env.home), frozenset({'session:control'}), 'fixture')
    reply = asyncio.run(call_plugin_rpc(SimpleNamespace(authority=authority, actor=actor), ref,
        'plugin.model-router.profile_jobs.list', handler, {'session_id': 'parent'}))
    assert reply['jobs'] == [] and called == ['parent']


def test_native_control_only_rpc_cannot_self_grant_or_relay_privileged_responses(env):
    import asyncio
    from gateway.session_authority import SessionAuthority
    from gateway.session_contract import SessionActor, SessionRef
    from gateway.session_plugin_rpc import call_plugin_rpc
    from gateway.config import Platform
    authority = object.__new__(SessionAuthority)
    authority.profile_id, authority.runner = str(env.home), None
    authority.sessions = {'parent': SimpleNamespace(source=SimpleNamespace(platform=Platform.LOCAL, user_id='owner'))}
    actor = SessionActor('owner', str(env.home), frozenset({'session:control'}), 'restricted-fixture')
    connection = SimpleNamespace(authority=authority, actor=actor, host_scoped=False)
    def call(operation, body, sid='parent'):
        return asyncio.run(call_plugin_rpc(connection, SessionRef(str(env.home), sid),
            'plugin.model-router.profile_jobs.' + operation,
            lambda params, session_id=None: env.manager.rpc(operation, params, session_id=session_id), body))
    description = call('describe', {})
    assert description['supported'] is True
    assert description['grant_management'] == {'transport': 'host_cli', 'rpc_writable': False}
    assert description['operator_controls_supported'] is False
    body = {'expected_revision': description['revision'], 'enabled': True,
        'targets': ['worker'], 'acknowledge_scope': True}
    for payload in (body, {**body, 'human': True, 'operator': True}):
        reply = call('configure', payload, None)
        assert reply['error'] == 'operator_authority_unavailable' and reply['no_effect'] is True
    assert env.ctx.writes == 0 and env.ctx.settings is None
    # Fixture-only trusted setup, deliberately NOT performed by the weak RPC.
    job = start(env); record = wait(env, job['id'])
    for kind, operation, extra in [('approval', 'approve', {'choice': 'once'}),
                                   ('approval', 'approve', {'choice': 'deny'}),
                                   ('clarify', 'clarify', {'answer': 'yes'})]:
        prompt_id = 'restricted-' + operation
        env.gateway.sessions[record['target_session_id']]['prompts'] = [{'kind': kind,
            'prompt_id': prompt_id, 'execution_generation': 1, 'description': 'Fixture only',
            'command': 'fixture-only', 'question': 'Fixture?', 'choices': ['once', 'deny'] if kind == 'approval' else []}]
        reply = call('control', {'session_id': 'parent', 'job_id': job['id'], 'operation': operation,
            'prompt_id': prompt_id, **extra})
        assert reply['error'] == 'operator_authority_unavailable' and reply['no_effect'] is True
    assert all(m not in ('approval.respond', 'clarify.respond') for m, _ in env.gateway.calls)


def test_native_tool_surface_policy_and_constructor_keep_target_context(env):
    # Real native policy and construction helper, replacing only AIAgent with a
    # kwargs recorder. This is not provider/memory-provider execution evidence.
    from gateway.session_policy import build_policy
    from gateway.session_execution import GatewaySessionAgentMixin
    from gateway.session_local import LocalSessionAdapter
    from gateway.session import SessionSource
    from gateway.config import Platform
    import hermes_constants
    target_home = env.home / 'profiles/worker'
    token = set_hermes_home_override(target_home)
    try:
        config = {'model': {'default': 'fixture-target-model', 'provider': 'fixture'},
            'platform_toolsets': {'cli': ['terminal', 'memory']}, 'agent': {'reasoning_effort': 'high'}}
        params = {'source': 'tool', 'cwd': str(env.cwd), 'request_id': 'fixture-create',
            'client': {'name': CLIENT_NAME, 'version': '0.8.0'}}
        policy = build_policy(params, config, profile_terminal=False)
        assert policy.platform == 'cli' and not policy.ignore_rules
        assert {'terminal', 'memory'} <= set(policy.toolsets)
        source = SessionSource(platform=Platform.LOCAL, chat_id='target-policy', user_id='owner', profile='worker')
        authority = SimpleNamespace(profile_id=str(target_home), sessions={}, _local_prefill={'target-policy': (None,)})
        adapter = LocalSessionAdapter(authority)
        adapter.register_source(source)
        adapter.policies[source.chat_id] = policy
        authority.sessions[source.chat_id] = SimpleNamespace(source=source)
        runner = SimpleNamespace(_adapter_for_source=lambda _: adapter, session_authority=authority,
            _service_tier=None, _session_db=None, _refresh_fallback_model=lambda: [{'provider': 'fixture', 'model': 'target-spare'}])
        authority.runner = runner
        recorded = {}
        def constructor(**kwargs):
            assert hermes_constants.get_hermes_home() == target_home
            recorded.update(kwargs)
            return 'fixture-agent'
        ctx = SimpleNamespace(source=source, AIAgent=constructor, user_config=config, enabled_toolsets=list(policy.toolsets),
            disabled_toolsets=[], session_id='target-policy', session_key='fixture-key')
        owner = SimpleNamespace(_runner=runner, _ctx=ctx)
        skip = GatewaySessionAgentMixin._skip_context_files(owner, 'cli')
        GatewaySessionAgentMixin._build_fresh_agent(owner, {'model': 'fixture-target-model', 'runtime': {}}, 'cli', '', 5, {}, {}, skip)
        assert recorded['skip_context_files'] is False and recorded['skip_memory'] is False and recorded['load_soul_identity'] is True
        assert recorded['enabled_toolsets'] == list(policy.toolsets)
        assert recorded['fallback_model'][0]['model'] == 'target-spare'
    finally:
        reset_hermes_home_override(token)


def test_job_manager_over_real_websocket_with_synthetic_owner(env, monkeypatch):
    from websockets.sync.server import serve
    from websockets.exceptions import ConnectionClosed
    from model_router import gateway_protocol_client as gp
    description = {**Client.description, 'capabilities': Client.description['capabilities'] + ['session-authority-v1']}
    def handler(ws):
        try:
            while True:
                request = json.loads(ws.recv())
                response = description if request['method'] == 'runtime.describe' else env.gateway.call(request['method'], request['params'])
                ws.send(json.dumps({'jsonrpc': '2.0', 'method': 'session.event', 'params': {'type': 'event_gap'}}))
                ws.send(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': response}))
        except ConnectionClosed:
            pass
    server = serve(handler, '127.0.0.1', 0, subprotocols=['hermes-gateway-v1'])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = 'http://127.0.0.1:' + str(server.socket.getsockname()[1])
    bootstrap = {'state': 'ready', 'client_code_sha': 'fixture-code', 'endpoint': {**description, 'runtime_protocol': 1,
        'api_origin': origin, 'supervisor': 'none', 'control_home': str(env.home), 'code_sha': 'fixture-code'},
        'url': origin.replace('http:', 'ws:') + '/api/ws', 'protocol': 'hermes-gateway-v1',
        'protocols': ['hermes-gateway-v1', 'hermes-gateway-ticket.fixture-only'], 'ticket': 'fixture-only'}
    def attach(argv, child_env, timeout):
        assert '--start' not in argv and '--recover' not in argv
        assert child_env['HERMES_HOME'] == str(env.home)
        return json.dumps(bootstrap).encode()
    monkeypatch.setattr(gp, '_run_attach', attach)
    env.manager.client_factory = gp.GatewayProtocolClient.connect
    try:
        j = start(env); record = wait(env, j['id'])
        assert record['gateway_profile_id'] == 'fixture-profile'
        env.manager.control('parent', {'job_id': j['id'], 'operation': 'steer', 'text': 'fixture-only steering'})
        env.gateway.finish(record['target_session_id'], 'actual fixture wire result')
        wait(env, j['id'], lambda r: r['status'] == 'completed')
        assert env.manager.result('parent', j['id'])['result']['text'] == 'actual fixture wire result'
        assert sum(m == 'prompt.submit' for m, _ in env.gateway.calls) == 1
        assert sum(m == 'session.steer' for m, _ in env.gateway.calls) == 1
    finally:
        env.manager.close()
        for observer in env.manager.threads.values(): observer.join(timeout=3)
        server.shutdown()
        thread.join(timeout=3)
        assert not thread.is_alive()
