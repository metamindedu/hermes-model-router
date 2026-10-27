import json
from types import SimpleNamespace

import pytest
from agent.delegation_provider import DelegationProvider, DelegationRouteError
from model_router import native_delegation as nd


class Service:
    def __init__(self, root):
        self.root = root
        self.config = {'enabled': True, 'heavy': {'provider': 'p', 'model': 'heavy', 'reasoning': 'high'},
                       'light': {'provider': 'p', 'model': 'light', 'reasoning': 'low'},
                       'heavy_timeout_seconds': 10800, 'light_timeout_seconds': .5}
    def active_profile(self): return 'default'
    def routing_config(self, name):
        assert name == 'default'
        return self.config
    native_route_config = routing_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / 'config.yaml').write_text('{}')
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: tmp_path)
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: tmp_path)
    service = Service(tmp_path)
    return tmp_path, service


def test_real_classes_registration_and_deterministic_schema(env):
    home, service = env
    captured = []
    providers = nd.register_native_delegation(SimpleNamespace(register_delegation_provider=captured.append), home)
    assert captured == list(providers)
    assert all(isinstance(p, DelegationProvider) for p in providers)
    assert [p.name for p in providers] == ['model-router', 'model-router-profiles']
    p = nd.ModelRouterProvider(home, lambda: service)
    assert p.task_parameters({}) == p.task_parameters({'api_key': 'SECRET'})
    assert list(p.task_parameters({})['purpose']['enum']) == list(nd.PURPOSE_ROLES)


def test_actual_core_plugin_registration(env):
    from pathlib import Path
    from hermes_cli.plugins import PluginContext, PluginManager
    from hermes_cli.plugins_manifest import parse_manifest_file
    from agent.delegation_registry import get_provider
    home, _ = env
    root = Path(__file__).resolve().parents[1]
    manager = PluginManager(scope_key=str(home))
    ctx = PluginContext(parse_manifest_file(root / 'plugin.yaml', root, 'user', ''), manager)
    try:
        providers = nd.register_native_delegation(ctx, home)
        assert get_provider('model-router') is providers[0]
        assert get_provider('model-router-profiles') is providers[1]
    finally:
        manager.unload('model-router')


@pytest.mark.parametrize('purpose,role', list(nd.PURPOSE_ROLES.items()))
def test_purpose_routes_and_explicit_continuation(env, monkeypatch, purpose, role):
    home, service = env
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    p = nd.ModelRouterProvider(home, lambda: service)
    task = {'purpose': purpose, 'goal': 'goal'}
    result = p.route_task(task, {'fallback_providers': [{'provider': 'inherited', 'model': 'bad'}]})
    assert result == {'provider': 'p', 'model': role, 'reasoning_effort': 'high' if role == 'heavy' else 'low', 'label': role, 'fallback_providers': []}
    chain = [{'provider': 'other', 'model': 'm/v1'}]
    policy = {'schema': 1, 'fallbacks': {r: {'mode': 'off', 'chain': [], 'consent': None} for r in ('heavy', 'light')}}
    policy['fallbacks'][role] = {'mode': 'custom', 'chain': chain, 'consent': nd.make_continuation_consent('default', role, chain)}
    assert p.route_task(task, {'backends': {'model-router': policy}})['fallback_providers'] == chain
    policy['fallbacks'][role]['consent'] = {'allow_task_rerun': True}
    with pytest.raises(DelegationRouteError): p.route_task(task, {'backends': {'model-router': policy}})


def test_consent_binds_exact_scope_and_validation():
    chain = [{'provider': 'p', 'model': 'm'}]
    consent = nd.make_continuation_consent('default', 'heavy', chain)
    assert nd.validate_continuation_consent('default', 'heavy', chain, consent)
    assert not nd.validate_continuation_consent('claire', 'heavy', chain, consent)
    assert not nd.validate_continuation_consent('default', 'light', chain, consent)
    assert not nd.validate_continuation_consent('default', 'heavy', [{'provider': 'p', 'model': 'm2'}], consent)
    with pytest.raises(ValueError): nd.make_continuation_consent('default', 'heavy', [{'provider': 'p', 'model': 'https://private'}])


def test_routes_refuse_without_binding_invalid_and_disabled(env, monkeypatch):
    home, service = env
    p = nd.ModelRouterProvider(home, lambda: service)
    for task in ({'purpose': 'plan', 'goal': 'g'}, {'purpose': 'bogus', 'goal': 'g'}):
        with pytest.raises(DelegationRouteError, match='refused'): p.route_task(task, {})
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    for value in (True, -1, float('nan'), float('inf'), '1'):
        with pytest.raises(DelegationRouteError): p.route_task({'purpose': 'plan', 'goal': 'g', 'total_timeout_seconds': value}, {})
    service.config['enabled'] = False
    with pytest.raises(DelegationRouteError): p.route_task({'purpose': 'plan', 'goal': 'g'}, {})


def test_profile_allowlist_exact_inventory_and_default(env, monkeypatch):
    home, service = env
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    directory = home / 'profiles' / 'claire'
    directory.mkdir(parents=True)
    (directory / 'config.yaml').write_text('{}')
    provider = nd.ModelRouterProfilesProvider(home, lambda: service)
    settings = {'schema': 1, 'profiles': [{'name': 'claire', 'description': 'private description'}], 'default': 'claire'}
    config = {'backends': {'model-router-profiles': settings}}
    assert provider.task_parameters(config)['profile']['enum'] == ['claire']
    assert provider.route_task({}, config) == {'profile': 'claire', 'label': 'claire'}
    assert provider.route_task({}, {}) == {}
    with pytest.raises(DelegationRouteError): provider.route_task({'profile': ' claire'}, config)
    (directory / 'config.yaml').unlink()
    with pytest.raises(DelegationRouteError): provider.route_task({}, config)
    assert 'private description' in json.dumps(provider.task_parameters(config))


def test_same_named_profile_in_foreign_native_root_is_refused(env, monkeypatch):
    home, service = env
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    for base in (home, home/'foreign-root'):
        target = base/'profiles/claire'
        target.mkdir(parents=True)
        (target/'config.yaml').write_text('{}', encoding='utf-8')
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: home/'foreign-root')
    provider = nd.ModelRouterProfilesProvider(home, lambda: service)
    cfg = {'backends': {'model-router-profiles': {'schema': 1, 'profiles': [{'name': 'claire', 'description': ''}], 'default': 'claire'}}}
    with pytest.raises(DelegationRouteError): provider.route_task({}, cfg)


def test_profile_validation_strict():
    good = {'schema': 1, 'profiles': [{'name': 'one', 'description': ''}], 'default': None}
    assert nd.validate_profile_settings(good) == good
    for invalid in ({**good, 'schema': True}, {**good, 'default': 'other'}, {**good, 'profiles': good['profiles'] * 2}, {**good, 'extra': 1}):
        with pytest.raises(ValueError): nd.validate_profile_settings(invalid)


def test_settings_worker_consent_interoperability():
    from model_router import native_settings
    chain = [{'provider': 'provider', 'model': 'model/v1'}]
    policy = {'heavy': {'mode': 'custom', 'chain': chain}, 'light': {'mode': 'off', 'chain': []}}
    block = native_settings.build_policy_block('default', policy, True)
    assert nd.validate_native_policy(block, 'default') == block
    assert block['fallbacks']['heavy']['consent'] == nd.make_continuation_consent('default', 'heavy', chain)
    assert native_settings.consent_matches('default', 'model-router', 'heavy', chain, block['fallbacks']['heavy']['consent'])
    block['fallbacks']['heavy']['consent']['additional_cost'] = 1
    with pytest.raises(ValueError): nd.validate_native_policy(block, 'default')
