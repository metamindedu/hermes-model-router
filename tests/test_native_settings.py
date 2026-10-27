import copy

import pytest

from model_router import native_settings as ns


def custom():
    value = ns.default_policy()
    value['heavy'] = {'mode': 'custom', 'chain': [
        {'provider': 'openai', 'model': 'model-a'},
        {'provider': 'example', 'model': 'model-b'},
    ]}
    return value


def test_consent_binds_origin_backend_role_and_order_and_not_legacy():
    policy = custom()
    chain = policy['heavy']['chain']
    consent = ns.make_consent('default', 'model-router', 'heavy', chain)
    assert ns.consent_matches('default', 'model-router', 'heavy', chain, consent)
    assert not ns.consent_matches('other', 'model-router', 'heavy', chain, consent)
    assert not ns.consent_matches('default', 'model-router-profiles', 'heavy', chain, consent)
    assert not ns.consent_matches('default', 'model-router', 'light', chain, consent)
    assert not ns.consent_matches('default', 'model-router', 'heavy', list(reversed(chain)), consent)
    assert not ns.consent_matches('default', 'model-router', 'heavy', chain, {'allow_task_rerun': True})


def test_custom_requires_fresh_cost_approval_and_final_block_is_checked():
    with pytest.raises(ValueError):
        ns.build_policy_block('default', custom(), False)
    block = ns.build_policy_block('default', custom(), True)
    assert ns.validate_policy_block('default', block) == custom()
    with pytest.raises(ValueError):
        ns.validate_policy_block('other', block)
    block['fallbacks']['heavy']['chain'].reverse()
    with pytest.raises(ValueError):
        ns.validate_policy_block('default', block)


def test_opt_out_is_explicit_and_has_no_consent():
    block = ns.build_policy_block('default', ns.default_policy(), False)
    assert all(entry['consent'] is None for entry in block['fallbacks'].values())
    assert ns.validate_policy_block('default', block) == ns.default_policy()
    block['fallbacks']['heavy']['consent'] = {'allow_task_rerun': True}
    with pytest.raises(ValueError):
        ns.validate_policy_block('default', block)


@pytest.mark.parametrize('bad', [
    {'provider': ' openai', 'model': 'model'},
    {'provider': 'openai', 'model': '${TOKEN}'},
    {'provider': 'openai', 'model': 'model', 'api_key': 'secret'},
    {'provider': 'KEEP', 'model': 'model'},
])
def test_invalid_route_is_not_normalized_or_accepted(bad):
    value = custom()
    value['heavy']['chain'] = [bad]
    with pytest.raises(ValueError):
        ns.validate_policy(value)


def test_duplicate_and_advanced_policy_rejected():
    value = custom()
    value['heavy']['chain'].append(copy.deepcopy(value['heavy']['chain'][0]))
    with pytest.raises(ValueError):
        ns.validate_policy(value)
    value = custom()
    value['heavy']['consent'] = None
    with pytest.raises(ValueError):
        ns.validate_policy(value)


def test_profile_routes_require_exact_existing_unique_names_and_allowlisted_default():
    routes = {'profiles': [{'name': 'default', 'description': 'General'},
                           {'name': 'claire', 'description': 'Coding'}], 'default': 'claire'}
    assert ns.validate_profiles(routes, {'default', 'claire'}) == routes
    for invalid in ('Claire', '../claire', 'missing'):
        bad = copy.deepcopy(routes)
        bad['profiles'][1]['name'] = invalid
        with pytest.raises(ValueError):
            ns.validate_profiles(bad, {'default', 'claire'})
    bad = copy.deepcopy(routes)
    bad['default'] = 'missing'
    with pytest.raises(ValueError):
        ns.validate_profiles(bad, {'default', 'claire'})
    bad = copy.deepcopy(routes)
    bad['profiles'].append(copy.deepcopy(bad['profiles'][0]))
    with pytest.raises(ValueError):
        ns.validate_profiles(bad, {'default', 'claire'})


def test_only_owned_keys_are_identified():
    from model_router.config_writer import ALLOWED_KEYS
    assert ns.KEYS == ('delegation.backend', 'delegation.backends.model-router',
                       'delegation.backends.model-router-profiles')
    assert 'delegation.backends' not in ns.KEYS
    assert set(ns.KEYS) <= ALLOWED_KEYS
    assert 'delegation.backends' not in ALLOWED_KEYS
    assert 'delegation.backends.some-other-plugin' not in ALLOWED_KEYS


def test_effective_reader_uses_only_owned_keys(monkeypatch, tmp_path):
    from model_router import effective_config
    seen = []
    sentinel = object()
    def reader(home, keys, *, helpers=None):
        seen.append((home, keys, helpers))
        return sentinel
    monkeypatch.setattr(effective_config, 'read_key_scoped', reader)
    assert effective_config.read_native_delegation_settings(tmp_path) is sentinel
    assert seen == [(tmp_path, ns.KEYS, None)]


def test_runtime_consent_interoperability():
    # The provider workstream's current public pure validation interface.
    from model_router.native_delegation import validate_native_policy, make_continuation_consent
    block = ns.build_policy_block('default', custom(), True)
    assert validate_native_policy(block, 'default') == block
    assert block['fallbacks']['heavy']['consent'] == make_continuation_consent(
        'default', 'heavy', custom()['heavy']['chain'])
