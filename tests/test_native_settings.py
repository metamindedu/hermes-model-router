import copy

import pytest

from model_router import native_settings as ns
from model_router.slots import BUILTIN_SLOTS


def custom():
    value = ns.default_slot_policy()
    value['design'] = {'mode': 'custom', 'chain': [
        {'provider': 'openai', 'model': 'model-a'},
        {'provider': 'example', 'model': 'model-b'},
    ]}
    return value


def test_consent_binds_origin_backend_slot_and_order():
    policy = custom()
    chain = policy['design']['chain']
    consent = ns.make_slot_consent('default', 'model-router', 'design', chain)
    assert ns.slot_consent_matches('default', 'model-router', 'design', chain, consent)
    assert not ns.slot_consent_matches('other', 'model-router', 'design', chain, consent)
    assert not ns.slot_consent_matches('default', 'model-router-auto', 'design', chain, consent)
    assert not ns.slot_consent_matches('default', 'model-router', 'code-simple', chain, consent)
    assert not ns.slot_consent_matches('default', 'model-router', 'design', list(reversed(chain)), consent)
    assert not ns.slot_consent_matches('default', 'model-router', 'design', chain, {'allow_task_rerun': True})
    with pytest.raises(ValueError):
        ns.make_slot_consent('default', 'model-router-profiles', 'design', chain)
    for retired in ('heavy', 'light', 'custom:extra'):
        with pytest.raises(ValueError):
            ns.make_slot_consent('default', 'model-router', retired, chain)


def test_custom_requires_fresh_cost_approval_and_final_block_is_checked():
    with pytest.raises(ValueError):
        ns.build_slot_policy_block('default', custom(), False)
    block = ns.build_slot_policy_block('default', custom(), True)
    assert ns.validate_slot_policy_block('default', block) == custom()
    with pytest.raises(ValueError):
        ns.validate_slot_policy_block('other', block)
    block['fallbacks']['design']['chain'].reverse()
    with pytest.raises(ValueError):
        ns.validate_slot_policy_block('default', block)


def test_opt_out_is_explicit_and_has_no_consent():
    block = ns.build_slot_policy_block('default', ns.default_slot_policy(), False)
    assert set(block['fallbacks']) == set(BUILTIN_SLOTS)
    assert all(entry['consent'] is None for entry in block['fallbacks'].values())
    assert ns.validate_slot_policy_block('default', block) == ns.default_slot_policy()
    block['fallbacks']['design']['consent'] = {'allow_task_rerun': True}
    with pytest.raises(ValueError):
        ns.validate_slot_policy_block('default', block)


def test_only_the_slot_block_schema_is_read():
    assert ns.read_policy('default', None) == {'schema': 0, 'slot_policy': ns.default_slot_policy()}
    block = ns.build_slot_policy_block('default', custom(), True)
    assert ns.read_policy('default', block) == {'schema': 2, 'slot_policy': custom()}
    two_role = {'schema': 1, 'fallbacks': {'heavy': {'mode': 'off', 'chain': [], 'consent': None},
                                           'light': {'mode': 'off', 'chain': [], 'consent': None}}}
    with pytest.raises(ValueError):
        ns.read_policy('default', two_role)


@pytest.mark.parametrize('bad', [
    {'provider': ' openai', 'model': 'model'},
    {'provider': 'openai', 'model': '${TOKEN}'},
    {'provider': 'openai', 'model': 'model', 'api_key': 'secret'},
    {'provider': 'KEEP', 'model': 'model'},
])
def test_invalid_route_is_not_normalized_or_accepted(bad):
    value = custom()
    value['design']['chain'] = [bad]
    with pytest.raises(ValueError):
        ns.validate_policy(value)


def test_duplicate_and_advanced_policy_rejected():
    value = custom()
    value['design']['chain'].append(copy.deepcopy(value['design']['chain'][0]))
    with pytest.raises(ValueError):
        ns.validate_policy(value)
    value = custom()
    value['design']['consent'] = None
    with pytest.raises(ValueError):
        ns.validate_policy(value)
    value = custom()
    value['heavy'] = {'mode': 'off', 'chain': []}
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
                       'delegation.backends.model-router-profiles', 'delegation.backends.model-router-auto')
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
    # The provider's own validation accepts exactly the block the settings side builds.
    from model_router.native_delegation import validate_native_policy, make_slot_continuation_consent
    block = ns.build_slot_policy_block('default', custom(), True)
    assert validate_native_policy(block, 'default') == block
    assert block['fallbacks']['design']['consent'] == make_slot_continuation_consent(
        'default', 'design', custom()['design']['chain'])
    auto = ns.build_slot_policy_block('default', custom(), True, backend='model-router-auto')
    assert validate_native_policy(auto, 'default', backend='model-router-auto') == auto
    with pytest.raises(ValueError):
        validate_native_policy(auto, 'default')
