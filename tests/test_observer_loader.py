"""Actual Hermes loader/hook seam with fake API transport (no provider calls)."""
import json
import sys
from pathlib import Path

import pytest

from model_router import attempt_observer, scoped_agent
from test_scoped_agent import attempt, _fake_dependencies

CORE = Path('C:/Users/ovpow/AppData/Local/hermes/hermes-agent')
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def loaded(attempt, monkeypatch):
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS', '1')
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    monkeypatch.setenv('HERMES_PROFILE', attempt['request']['profile'])
    (attempt['home'] / 'config.yaml').write_text('plugins:\n  enabled: [model-router]\n', encoding='utf-8')
    from hermes_cli import plugins
    from hermes_cli.plugins_manifest import parse_manifest_file
    manager = plugins.PluginManager(scope_key=str(attempt['home']))
    manifest = parse_manifest_file(REPO / 'plugin.yaml', REPO, 'user', '')
    assert manifest is not None
    manager._load_plugin(manifest)
    entry = manager._plugins['model-router']
    assert entry.enabled, entry.error
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: manager)
    observer = scoped_agent._resolve_registered_observer(attempt['home'], REPO)
    assert observer is not attempt_observer
    assert observer.__name__.startswith('hermes_plugins.model_router')
    yield manager, observer
    observer.reset_for_tests()
    manager.unload('model-router')


def test_other_profile_hook_cannot_record_this_attempt(attempt, loaded, monkeypatch):
    manager, observer = loaded
    from hermes_cli import plugins
    from hermes_cli.plugins_manifest import parse_manifest_file
    other_home = attempt['base'] / 'foreign'
    other_home.mkdir()
    (other_home / 'config.yaml').write_text('plugins:\n  enabled: [model-router]\n'.replace('\n', '\n'), encoding='utf-8')
    other = plugins.PluginManager(scope_key=str(other_home))
    manifest = parse_manifest_file(REPO / 'plugin.yaml', REPO, 'user', '')
    other._load_plugin(manifest)
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: other)
    foreign_observer = scoped_agent._resolve_registered_observer(other_home, REPO)
    assert foreign_observer is not observer
    monkeypatch.setenv('MODEL_ROUTER_ATTEMPT_REQUEST', str(attempt['request_path']))
    req = attempt['request']
    identity = dict(api_request_id='foreign-test', session_id=req['session_id'],
                    task_id=req['task_id'], provider=req['route']['provider'],
                    model=req['route']['model'], api_mode='chat_completions')
    try:
        other.invoke_hook('pre_api_request', **identity, request={'body': {'model': req['route']['model']}})
        other.invoke_hook('post_api_request', **identity, response_model=req['route']['model'], assistant_tool_call_count=0)
        assert foreign_observer.snapshot()['observed_routes'] == []
        assert observer.snapshot()['observed_routes'] == []
    finally:
        other.unload('model-router')


@pytest.mark.parametrize('outcome', ['success', 'exhausted', 'tool', 'partial'])
def test_actual_loader_and_adapter_share_observer(attempt, loaded, outcome):
    manager, observer = loaded
    request = attempt['request']
    def fake_transport(agent, prompt, task_id):
        identity = dict(api_request_id='fixture-api', session_id=request['session_id'],
                        task_id=task_id, provider=request['route']['provider'],
                        model=request['route']['model'], api_mode='chat_completions')
        manager.invoke_hook('pre_api_request', **identity, request={'body': {'model': request['route']['model']}})
        if outcome == 'exhausted':
            manager.invoke_hook('api_request_error', **identity,
                                error={'type': 'usage_limit_reached', 'code': 'usage_limit_reached', 'message': 'subscription usage limit'},
                                error_type='usage_limit_reached', error_code='usage_limit_reached', status_code=429,
                                reason='billing', retryable=False)
            return {'completed': False, 'failed': True, 'error': {'type': 'usage_limit_reached', 'code': 'usage_limit_reached', 'message': 'subscription usage limit'}, 'final_response': ''}
        if outcome == 'tool':
            agent.kwargs['tool_start_callback']('fake_tool', {})
        if outcome == 'partial':
            agent.kwargs['stream_delta_callback']('partial fixture text')
        manager.invoke_hook('post_api_request', **identity, response_model=request['route']['model'], assistant_tool_call_count=0)
        return {'completed': True, 'failed': False, 'partial': False, 'final_response': 'fixture response'}
    deps, stats = _fake_dependencies(attempt, on_run=fake_transport)
    prepare = deps['prepare_runtime']
    deps['observer'] = observer
    deps['prepare_runtime'] = lambda req: {**prepare(req), 'observer': observer}
    result = scoped_agent.run_attempt(request, dependencies=deps)
    assert result['evidence_complete'] is True
    assert len(result['observed_routes']) == 1
    assert result['closure_complete'] is True
    assert stats['close_calls'] == 1
    assert result['tool_seen'] is (outcome == 'tool')
    assert result['partial_output'] is (outcome == 'partial')
    assert result['exhaustion_confirmed'] is (outcome == 'exhausted')
    assert result['completed'] is (outcome != 'exhausted')
    # The former top-level observer has no events: no accidental global alias.
    assert attempt_observer.snapshot()['observed_routes'] == []


def test_registered_observer_rejects_foreign_profile_and_wrong_root(attempt, loaded):
    _manager, _observer = loaded
    other = attempt['base'] / 'other'
    other.mkdir()
    with pytest.raises(scoped_agent.AttemptError):
        scoped_agent._resolve_registered_observer(other, REPO)
    with pytest.raises(scoped_agent.AttemptError):
        scoped_agent._resolve_registered_observer(attempt['home'], other)


def test_strict_real_config_valid_snapshot_has_no_recovery(attempt, monkeypatch):
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    monkeypatch.setenv('HERMES_PROFILE', 'default')
    path = attempt['home'] / 'config.yaml'
    path.write_text('agent:\n  max_turns: 7\nsecurity:\n  redact_secrets: true\n', encoding='utf-8')
    effective, config, raw = scoped_agent._strict_profile_config(path)
    assert effective['agent']['max_turns'] == 7
    assert config['agent']['max_turns'] == 7
    assert raw == path.read_bytes()


def test_real_default_bootstrap_prepares_copied_plugin_without_provider_call(attempt, monkeypatch):
    import importlib.util
    import shutil
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS', '1')
    from hermes_cli import env_loader, runtime_provider, plugins, mcp_startup, profiles
    monkeypatch.setattr(profiles, '_get_default_hermes_home', lambda: attempt['home'])
    from tools import tirith_security
    destination = attempt['home'] / 'plugins/model-router'
    destination.mkdir(parents=True)
    for name in ('plugin.yaml', '__init__.py'):
        shutil.copy2(REPO / name, destination / name)
    shutil.copytree(REPO / 'model_router', destination / 'model_router', ignore=shutil.ignore_patterns('__pycache__'))
    (attempt['home'] / 'config.yaml').write_text(
        'plugins:\n  enabled: [model-router]\nagent:\n  max_turns: 7\nsecurity:\n  redact_secrets: true\n'.replace('\\n', '\n'), encoding='utf-8')
    # Bootstrap policy/readers/loader remain real. Only external setup edges are
    # replaced so this test cannot refresh auth, install tools or start MCPs.
    calls = []
    monkeypatch.setattr(env_loader, 'load_hermes_dotenv', lambda **kw: calls.append('env') or [])
    monkeypatch.setattr(tirith_security, 'ensure_installed', lambda **kw: calls.append('tirith'))
    monkeypatch.setattr(mcp_startup, 'ensure_mcp_discovery_before_agent_build', lambda **kw: calls.append('mcp'))
    def forbidden_provider(**kw):
        raise AssertionError('No provider resolution is allowed in preparation')
    monkeypatch.setattr(runtime_provider, 'resolve_runtime_provider', forbidden_provider)
    spec = importlib.util.spec_from_file_location('test_real_copied_adapter', destination / 'model_router/scoped_agent.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    request = {**attempt['request'], 'profile': 'default'}
    attempt['request_path'].write_text(json.dumps(request), encoding='utf-8')
    with module._attempt_environment(request, attempt['request_path']):
        prepared = module._default_prepare_runtime(request)
        assert prepared['agent_options']['max_iterations'] == 7
        assert prepared['observer'].__name__.startswith('hermes_plugins.model_router')
        assert Path(prepared['observer'].__file__).resolve().parent.parent == destination.resolve()
        assert prepared['resolve_runtime_provider'] is forbidden_provider
        assert calls[:3] == ['env', 'tirith', 'mcp']
        assert all(call == 'env' for call in calls[3:])
        plugins.get_plugin_manager().unload('model-router')


@pytest.mark.parametrize('broken', ['security: [', '- invalid-root'])
def test_strict_config_rejects_malformed_managed_policy(attempt, monkeypatch, broken):
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    managed = attempt['base'] / 'managed'
    managed.mkdir()
    (managed / 'config.yaml').write_text(broken, encoding='utf-8')
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    path = attempt['home'] / 'config.yaml'
    path.write_text('agent: {max_turns: 7}', encoding='utf-8')
    with pytest.raises(scoped_agent.AttemptError):
        scoped_agent._strict_profile_config(path)
