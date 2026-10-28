"""Transactional auto-mode settings: fake homes, no live writes."""
import copy
import pytest
from model_router import native_service, native_settings as ns
from model_router.service import RevisionConflict
from test_native_service import fixture, body, get_path


def test_auto_save_owns_only_auto_policy_and_explicit_profile_grants(fixture):
    service, calls, _ = fixture
    routes = {'profiles': [{'name': 'p1', 'description': 'Specialist'}], 'default': None}
    request = body(service, backend='model-router-auto', profiles=routes)
    with pytest.raises(ValueError, match='explicit permission'):
        service.delegation_preview(request)
    assert not calls
    request['updates'][0]['allow_profile_access'] = True
    plan = service.delegation_preview(request)
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    assert [r[1] for r in calls] == [ns.KEY_AUTO_POLICY, ns.KEY_PROFILES, ns.KEY_BACKEND]
    dto = native_service.status(service, 'default')
    assert dto['auto_supported'] is True and dto['backend'] == 'model-router-auto'
    assert dto['auto_policy'] == ns.default_policy() and dto['policy'] == ns.default_policy()
    assert not any(key == ns.KEY_POLICY for _, key, _ in calls)


def test_auto_chain_requires_own_consent_and_preserves_legacy_policy(fixture):
    service, calls, writer = fixture
    base = ns.default_policy()
    base['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'p', 'model': 'legacy-spare'}]}
    original = ns.build_policy_block('default', base, True)
    writer('default', ns.KEY_POLICY, original)
    calls.clear()
    request = body(service, backend='model-router-auto')
    request['updates'][0]['policy']['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'p', 'model': 'auto-spare'}]}
    with pytest.raises(ValueError, match='confirmation'):
        service.delegation_preview(request)
    assert not calls
    request['updates'][0]['allow_additional_cost'] = True
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    dto = native_service.status(service, 'default')
    assert dto['policy'] == base
    assert dto['auto_policy']['heavy']['chain'][0]['model'] == 'auto-spare'
    assert all(key != ns.KEY_POLICY for _, key, _ in calls)
    raw = service._read_native_delegation_snapshot('default')
    assert raw.raw(ns.KEY_POLICY) == original
    auto = raw.raw(ns.KEY_AUTO_POLICY)
    assert ns.validate_policy_block('default', auto, backend='model-router-auto') == dto['auto_policy']
    with pytest.raises(ValueError): ns.validate_policy_block('default', auto)


def test_other_modes_preserve_auto_policy_and_auto_save_rechecks_opt_out(fixture, monkeypatch):
    service, calls, writer = fixture
    auto = ns.build_policy_block('default', ns.default_policy(), False, backend='model-router-auto')
    writer('default', ns.KEY_AUTO_POLICY, auto)
    calls.clear()
    assert service.apply(service.delegation_preview(body(service))['plan_id'])['status'] == 'applied'
    assert service._read_native_delegation_snapshot('default').raw(ns.KEY_AUTO_POLICY) == auto
    assert all(key != ns.KEY_AUTO_POLICY for _, key, _ in calls)
    plan = service.delegation_preview(body(service, backend='model-router-auto'))
    calls.clear()
    monkeypatch.setattr(service, 'routing_config', lambda p: {'enabled': False})
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert not calls
    with pytest.raises(ValueError, match='opt-out'):
        service.delegation_preview(body(service, backend='model-router-auto'))


def test_auto_policy_is_part_of_frozen_cas_even_when_another_mode_is_saved(fixture):
    service, calls, writer = fixture
    plan = service.delegation_preview(body(service))
    writer('default', ns.KEY_AUTO_POLICY, ns.build_policy_block('default', ns.default_policy(), False, backend='model-router-auto'))
    calls.clear()
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert not calls
