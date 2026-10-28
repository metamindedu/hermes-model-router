"""First preparation chooses auto only; no install/register-time writes or grants."""
import copy
import json
import pytest
from model_router import native_service as native, native_settings as ns
from model_router.service import RevisionConflict
from test_initial_setup import setup_fixture, config, write_config, request
from test_native_service import fixture


def test_initial_default_is_auto_and_owns_only_absent_backend(setup_fixture):
    service, calls, _, _ = setup_fixture
    before = config(service)
    dto = native.initial_setup_status(service, 'default')
    assert dto['default_backend'] == 'model-router-auto' and dto['action'] == 'select_backend'
    plan = service.initial_setup_preview(request(service))
    assert plan['default_backend'] == 'model-router-auto'
    assert plan['changes'][0]['after'] == 'model-router-auto'
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    expected = copy.deepcopy(before); expected['delegation']['backend'] = 'model-router-auto'
    assert config(service) == expected
    assert calls == [('default', ns.KEY_BACKEND, 'model-router-auto')]
    assert native.initial_setup_status(service, 'default')['action'] == 'complete'


@pytest.mark.parametrize('backend', ['model-router', 'model-router-auto', 'default', 'model-router-profiles'])
def test_any_existing_mode_is_never_migrated_by_new_default(setup_fixture, backend):
    service, calls, _, _ = setup_fixture
    value = config(service); value['delegation']['backend'] = backend; write_config(service, value)
    before = config(service)
    assert native.initial_setup_status(service, 'default')['eligible'] is False
    with pytest.raises(ValueError): service.initial_setup_preview(request(service))
    assert not calls and config(service) == before


@pytest.mark.parametrize('kind', ['paid', 'profiles', 'opaque_profiles', 'opaque_model_policy'])
def test_initial_does_not_activate_dormant_auto_cost_or_profile_authority(setup_fixture, kind):
    service, calls, _, _ = setup_fixture
    value = config(service)
    if kind == 'paid':
        policy = ns.default_policy(); policy['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'fixture', 'model': 'spare'}]}
        value['delegation']['backends']['model-router-auto'] = ns.build_policy_block('default', policy, True, backend='model-router-auto')
    elif kind == 'profiles':
        value['delegation']['backends']['model-router-profiles'] = {'schema': 1, 'profiles': [{'name': 'p1', 'description': ''}], 'default': None}
    elif kind == 'opaque_profiles': value['delegation']['backends']['model-router-profiles'] = {'unrecognized': 'preserve'}
    else: value['delegation']['backends']['model-router'] = {'unrecognized': 'preserve'}
    write_config(service, value)
    assert not native.initial_setup_status(service, 'default')['eligible']
    with pytest.raises(ValueError): service.initial_setup_preview(request(service))
    assert not calls


def test_unrelated_old_model_only_cost_policy_remains_inactive_and_preserved(setup_fixture):
    service, calls, _, _ = setup_fixture
    value = config(service)
    policy = ns.default_policy(); policy['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'fixture', 'model': 'old-spare'}]}
    value['delegation']['backends']['model-router'] = ns.build_policy_block('default', policy, True)
    write_config(service, value)
    before = copy.deepcopy(value)
    assert service.apply(service.initial_setup_preview(request(service))['plan_id'])['status'] == 'applied'
    before['delegation']['backend'] = 'model-router-auto'
    assert config(service) == before and len(calls) == 1


def test_source_or_target_auto_capability_loss_refuses_setup(setup_fixture, monkeypatch):
    service, calls, _, _ = setup_fixture
    plan = service.initial_setup_preview(request(service))
    monkeypatch.setattr(native, '_auto_code_signature', lambda *args: None)
    assert not native.initial_setup_status(service, 'default')['eligible']
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert not calls


def test_old_initial_plan_cannot_be_reinterpreted_as_auto(setup_fixture):
    service, calls, _, _ = setup_fixture
    plan = service.initial_setup_preview(request(service))
    path = service.store_path.parent / 'plans' / (plan['plan_id'] + '.json')
    saved = json.loads(path.read_text()); saved.pop('default_backend', None)
    path.write_text(json.dumps(saved))
    with pytest.raises(RevisionConflict, match='default'): service.apply(plan['plan_id'])
    assert not calls


@pytest.mark.parametrize('side', ['source', 'target'])
def test_each_profile_feature_capability_is_required_before_initial_write(setup_fixture, monkeypatch, side):
    service, calls, _, _ = setup_fixture
    plan = service.initial_setup_preview(request(service, ('p1',)))
    real = native._auto_code_signature
    missing = 'default' if side == 'source' else 'p1'
    monkeypatch.setattr(native, '_auto_code_signature', lambda s, profile, code: None if profile == missing else real(s, profile, code))
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert not calls


def test_feature_loss_after_backend_write_is_partial_not_completed(setup_fixture):
    service, calls, writer, _ = setup_fixture
    plan = service.initial_setup_preview(request(service))
    def changed(profile, key, value):
        writer(profile, key, value)
        path = service._profile_home(profile) / 'plugins/model-router/model_router/config_writer.py'
        path.write_text(path.read_text().replace('AUTO_ROUTING_SUPPORTED = True', 'AUTO_ROUTING_SUPPORTED = False'))
    service.writer = changed
    assert service.apply(plan['plan_id'])['status'] == 'partial'
    assert len(calls) == 1 and config(service)['delegation']['backend'] == 'model-router-auto'
