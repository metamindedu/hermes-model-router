"""Actual native actor/dispatcher/response guards with synthetic stores and I/O."""
import asyncio
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest


def authority_fixture(profile='synthetic-worker'):
    from gateway.session_authority import SessionAuthority
    from gateway.config import Platform
    authority = object.__new__(SessionAuthority)
    authority.profile_id, authority.instance_id, authority.runner = profile, 'synthetic-instance', None
    authority.events, authority.sessions = {}, {}
    authority.sessions['parent'] = SimpleNamespace(source=SimpleNamespace(platform=Platform.LOCAL, user_id='owner'))
    return authority


def test_candidate_native_registry_rejects_weak_actor_grants_responses_and_cli(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.plugins import get_plugin_manager, get_plugin_command_handler
    from gateway.session_controls import AuthorityConnection
    from gateway.session_contract import SessionActor
    source = Path(__file__).resolve().parents[1]
    home = tmp_path / 'home'; home.mkdir()
    shutil.copytree(source, home / 'plugins/model-router', ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__', '.hermes-catalog.json'))
    config = home / 'config.yaml'
    config.write_text('{"plugins":{"enabled":["model-router"]},"model":{"provider":"openrouter","default":"offline-fixture"}}', encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    token = set_hermes_home_override(home)
    manager = get_plugin_manager()
    try:
        manager.discover_and_load()
        assert manager._plugins['model-router'].enabled and not manager._plugins['model-router'].error
        assert get_plugin_command_handler('model-router') is None
        authority = authority_fixture(str(home))
        connection = AuthorityConnection(authority, SimpleNamespace(), {'user_id': 'owner', 'profile_id': str(home), 'capabilities': ['session:control']})
        connection.actor = SessionActor('owner', str(home), frozenset({'session:control'}), 'synthetic-weak-transport')
        before = config.read_bytes()
        def call(method, params):
            return asyncio.run(connection.dispatch({'jsonrpc': '2.0', 'id': 'native-fixture', 'method': method, 'params': params}))
        description = call('plugin.model-router.profile_jobs.describe', {'session_id': 'parent'})['result']
        assert description['grant_management']['rpc_writable'] is False
        configured = call('plugin.model-router.profile_jobs.configure', {'session_id': 'parent',
            'expected_revision': description['revision'], 'enabled': True, 'targets': ['worker'],
            'acknowledge_scope': True, 'operator': True, 'human': True})
        assert configured['result']['error'] == 'operator_authority_unavailable'
        for operation, fields in [('approve', {'choice': 'once'}), ('approve', {'choice': 'deny'}), ('clarify', {'answer': 'synthetic answer'})]:
            reply = call('plugin.model-router.profile_jobs.control', {'session_id': 'parent', 'job_id': 'synthetic-job',
                'operation': operation, 'prompt_id': 'synthetic-prompt', **fields})
            assert reply['result']['error'] == 'operator_authority_unavailable' and reply['result']['no_effect'] is True
        for method in ['cli.exec', 'plugin.model-router.profile-jobs-configure', 'plugin.model-router.operator_configure']:
            reply = call(method, {'argv': ['model-router', 'profile-jobs-configure']})
            assert reply['error']['code'] == -32601 and reply['error']['data']['reason'] == 'unknown_method'
        assert config.read_bytes() == before
        assert not (home / 'plugin-data/model-router/full-profile-jobs.json').exists()
    finally:
        manager.unload()
        reset_hermes_home_override(token)


@pytest.mark.parametrize('kind,capability', [('approval', 'session:approve'), ('clarify', 'session:respond')])
def test_real_native_response_needs_capability_subscription_profile_generation_and_prompt(kind, capability):
    from gateway.session_contract import SessionActor, SessionRef, SessionHandle
    from gateway.session_pending_controls import PendingControls
    from hermes_state_runtime import RuntimeStoreError
    authority = authority_fixture()
    events = SimpleNamespace(lock=threading.RLock(), publish=lambda *args, **kwargs: None)
    controls = PendingControls(events)
    calls = []
    prompt_id = 'synthetic-' + kind
    controls.pending[prompt_id] = (None, {'kind': kind, 'prompt_id': prompt_id, 'execution_generation': 9, 'choices': ['once', 'deny']})
    controls.remote_responders[prompt_id] = lambda *args: calls.append(args)
    live = authority.sessions['parent']
    live.event_stream, live.controls, live.subscribers = events, controls, {}
    # Only the storage-derived handle is substituted. Native authorize,
    # check_approval_generation, subscription and PendingControls all execute.
    authority._handle = lambda ref: SessionHandle(ref, authority.instance_id, 1, 1, 9, 'running')
    ref = SessionRef(authority.profile_id, 'parent')
    strong = SessionActor('owner', authority.profile_id, frozenset({capability}), 'strong-native-viewer')
    weak = SessionActor('owner', authority.profile_id, frozenset({'session:control'}), 'weak-native-viewer')
    reply = {'choice': 'once'} if kind == 'approval' else {'answer': 'synthetic answer'}
    def respond(actor, generation=9, pid=prompt_id, target=ref):
        return asyncio.run(authority.respond(actor, target, generation, pid, reply, kind=kind))
    live.subscribers['weak'] = weak
    with pytest.raises(RuntimeStoreError): respond(weak)
    with pytest.raises(RuntimeStoreError): respond(strong)
    live.subscribers['strong'] = strong
    for generation in [8, True]:
        with pytest.raises(RuntimeStoreError): respond(strong, generation=generation)
    with pytest.raises(RuntimeStoreError): respond(strong, target=SessionRef('foreign-profile', 'parent'))
    with pytest.raises(RuntimeStoreError): respond(strong, pid='')
    assert respond(strong, pid='different-prompt')['status'] == 'already_resolved'
    assert calls == []
    assert respond(strong)['status'] == 'resolved'
    assert calls == [(kind, prompt_id, reply['choice' if kind == 'approval' else 'answer'])]
