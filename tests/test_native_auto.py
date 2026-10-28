"""Unified native routing: isolated homes, no provider requests."""
import copy
import json

import pytest
from agent.delegation_provider import DelegationRouteError
from model_router import native_delegation as nd, native_settings as ns
from test_native_delegation import env


@pytest.fixture
def automatic(env, monkeypatch):
    home, service = env
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    target = home / 'profiles' / 'claire'
    target.mkdir(parents=True)
    (target / 'config.yaml').write_text('{}')
    config = {'backends': {'model-router-profiles': {'schema': 1, 'profiles': [
        {'name': 'claire', 'description': 'Specialist fixture'}], 'default': 'claire'}}}
    return nd.ModelRouterAutoProvider(home, lambda: service), config, service


def test_schema_is_deterministic_and_empty_allowlist_does_not_offer_profile(automatic):
    provider, config, _ = automatic
    params = provider.task_parameters(config)
    assert params['execution']['enum'] == ['model', 'profile']
    assert params['profile']['enum'] == ['claire']
    assert params == provider.task_parameters(copy.deepcopy(config))
    assert 'provider' not in params and 'model' not in params
    empty = provider.task_parameters({})
    assert empty['execution']['enum'] == ['model'] and 'profile' not in empty


@pytest.mark.parametrize('purpose,role', list(nd.PURPOSE_ROLES.items()))
def test_model_uses_origin_role_and_never_profile(automatic, purpose, role):
    provider, config, _ = automatic
    route = provider.route_task({'execution': 'model', 'purpose': purpose, 'goal': 'specific model task'}, config)
    assert route['model'] == role and route['label'] == 'model:' + role
    assert route['fallback_providers'] == [] and 'profile' not in route


def test_profile_is_pure_and_never_resolves_roles_or_default_on_omission(automatic):
    provider, config, service = automatic
    service.native_route_config = lambda name: pytest.fail('profile route read a model role')
    route = provider.route_task({'execution': 'profile', 'profile': 'claire', 'goal': 'specific profile task'}, config)
    assert route == {'profile': 'claire', 'label': 'profile:claire'}
    with pytest.raises(DelegationRouteError):
        provider.route_task({'execution': 'profile', 'goal': 'never silently use a default'}, config)


@pytest.mark.parametrize('selectors', [
    {}, {'execution': None}, {'execution': []}, {'execution': {}}, {'execution': 'MODEL'},
    {'execution': 'model'}, {'execution': 'model', 'purpose': 'plan', 'profile': 'claire'},
    {'execution': 'profile', 'profile': 'claire', 'purpose': 'independent-review'},
    {'execution': 'profile', 'profile': 'missing'}, {'execution': 'profile', 'profile': '../claire'},
])
def test_missing_invalid_or_contradictory_selectors_refuse(automatic, selectors):
    provider, config, _ = automatic
    with pytest.raises(DelegationRouteError):
        provider.route_task({'goal': 'must not run the wrong route', **selectors}, config)


def test_model_off_is_not_silent_profile_fallback_and_grants_are_rechecked(automatic):
    provider, config, service = automatic
    service.config['enabled'] = False
    with pytest.raises(DelegationRouteError):
        provider.route_task({'execution': 'model', 'purpose': 'plan', 'goal': 'model off'}, config)
    task = {'execution': 'profile', 'profile': 'claire', 'goal': 'explicit approved profile'}
    assert provider.route_task(task, config)['profile'] == 'claire'
    with pytest.raises(DelegationRouteError): provider.route_task(task, {})
    (service.root / 'profiles/claire/config.yaml').unlink()
    with pytest.raises(DelegationRouteError): provider.route_task(task, config)


def test_auto_continuation_has_separate_backend_consent(automatic):
    provider, config, _ = automatic
    policy = ns.default_policy()
    policy['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'p', 'model': 'backup'}]}
    old = ns.build_policy_block('default', policy, True)
    config['backends']['model-router'] = old
    task = {'execution': 'model', 'purpose': 'plan', 'goal': 'fresh consent scope'}
    assert provider.route_task(task, config)['fallback_providers'] == []
    config['backends']['model-router-auto'] = old
    with pytest.raises(DelegationRouteError): provider.route_task(task, config)
    block = ns.build_policy_block('default', policy, True, backend='model-router-auto')
    config['backends']['model-router-auto'] = block
    assert provider.route_task(task, config)['fallback_providers'] == policy['heavy']['chain']
    assert ns.validate_policy_block('default', block, backend='model-router-auto') == policy
    assert not ns.consent_matches('default', 'model-router-auto', 'heavy', policy['heavy']['chain'], old['fallbacks']['heavy']['consent'])


@pytest.mark.parametrize('execution,selectors', [('model', {'purpose': 'plan'}), ('profile', {'profile': 'claire'})])
@pytest.mark.parametrize('budget', [True, -1, float('nan'), float('inf'), '2'])
def test_invalid_budgets_refuse_in_both_branches(automatic, execution, selectors, budget):
    provider, config, _ = automatic
    with pytest.raises(DelegationRouteError):
        provider.route_task({'execution': execution, 'goal': 'invalid budget', 'total_timeout_seconds': budget, **selectors}, config)
