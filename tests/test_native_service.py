"""Fake-home transactional settings tests; no provider requests or live writes."""
import copy
import json
from pathlib import Path

import pytest

from model_router import effective_config, native_service, native_settings as ns
from model_router.service import Service, RevisionConflict, ServiceError
from model_router.yaml_compat import yaml


def get_path(config, key):
    for part in key.split('.'):
        config = config.get(part) if isinstance(config, dict) else None
    return config


def put_path(config, key, value):
    parts = key.split('.')
    for part in parts[:-1]:
        config = config.setdefault(part, {})
    config[parts[-1]] = copy.deepcopy(value)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / 'home'
    calls = []
    for name in ('default', 'p1', 'p2'):
        home = root if name == 'default' else root / 'profiles' / name
        home.mkdir(parents=True)
        (home / 'config.yaml').write_text(yaml.safe_dump({
            'model': {'provider': 'fixture', 'default': 'main'},
            'agent': {'reasoning_effort': 'high'},
            'delegation': {'model': 'light', 'provider': 'fixture', 'backends': {'unrelated': {'keep': True}}},
            'plugins': {'enabled': ['model-router']},
            'skills': {'disabled': []}, 'unrelated': {'preserve': name},
        }), encoding='utf-8')
    def writer(profile, key, value):
        calls.append((profile, key, copy.deepcopy(value)))
        home = root if profile == 'default' else root / 'profiles' / profile
        path = home / 'config.yaml'
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        put_path(config, key, value)
        path.write_text(yaml.safe_dump(config), encoding='utf-8')
    service = Service(root=root, writer=writer)
    # General settings transactions use current installed capability fixtures;
    # detector tests separately install exact legacy/current package bytes.
    source = Path(__file__).resolve().parents[1] / 'model_router'
    for name in ('default', 'p1', 'p2'):
        directory = service._profile_home(name) / 'plugins/model-router/model_router'
        directory.mkdir(parents=True, exist_ok=True)
        for module in ('native_delegation', 'native_watchdog', 'native_settings', 'native_service', 'config_writer', 'role_metadata'):
            (directory / (module + '.py')).write_bytes((source / (module + '.py')).read_bytes())
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: root)
    monkeypatch.setattr(service, '_native_delegation_code_signature', lambda profile: 'fixture-code')
    monkeypatch.setattr(service, 'routing_config', lambda profile: {'enabled': True})
    return service, calls, writer


def body(service, profile='default', backend='model-router', profiles=None):
    dto = native_service.status(service, profile)
    assert dto['editable'], dto
    return {'expected_revision': 0, 'updates': [{
        'profile': profile, 'expected_digest': dto['digest'], 'backend': backend,
        'policy': ns.default_policy(), 'profile_routes': profiles or {'profiles': [], 'default': None},
        'allow_additional_cost': False, 'allow_profile_access': False,
    }]}


def test_status_is_readonly_and_legacy_fallback_consent_is_not_imported(fixture):
    service, calls, _ = fixture
    path = service.root / 'config.yaml'
    before = path.read_bytes()
    dto = native_service.status(service, 'default')
    assert dto['backend'] == 'default'
    assert dto['policy'] == ns.default_policy()
    assert dto['profile_routes'] == {'profiles': [], 'default': None}
    assert before == path.read_bytes() and calls == []
    assert not service.store_path.exists()


def test_apply_writes_only_exact_owned_keys_and_backend_last(fixture):
    service, calls, _ = fixture
    before_other = (service.root / 'profiles/p1/config.yaml').read_bytes()
    plan = service.delegation_preview(body(service))
    assert calls == []
    receipt = service.apply(plan['plan_id'])
    assert receipt['status'] == 'applied'
    assert [row[1] for row in calls] == [ns.KEY_POLICY, ns.KEY_PROFILES, ns.KEY_BACKEND]
    config = yaml.safe_load((service.root / 'config.yaml').read_text())
    assert get_path(config, ns.KEY_BACKEND) == 'model-router'
    assert config['delegation']['model'] == 'light'
    assert config['delegation']['backends']['unrelated'] == {'keep': True}
    assert config['unrelated'] == {'preserve': 'default'}
    assert before_other == (service.root / 'profiles/p1/config.yaml').read_bytes()
    assert not service.store_path.exists()
    with pytest.raises(ServiceError): service.apply(plan['plan_id'])


def test_profile_grant_requires_permission_and_revocation_is_exact(fixture):
    service, calls, _ = fixture
    routes = {'profiles': [{'name': 'p1', 'description': 'evidence'}], 'default': 'p1'}
    request = body(service, backend='model-router-profiles', profiles=routes)
    with pytest.raises(ValueError, match='explicit permission'): service.delegation_preview(request)
    assert calls == []
    request['updates'][0]['allow_profile_access'] = True
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    request = body(service, backend='model-router-profiles')
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'default')['profile_routes'] == {'profiles': [], 'default': None}


def test_profile_grant_rejects_same_name_resolved_by_core_in_foreign_root(fixture, monkeypatch):
    service, calls, _ = fixture
    foreign = service.root/'foreign-core-root'
    target = foreign/'profiles/p1'
    target.mkdir(parents=True)
    (target/'config.yaml').write_text('{}', encoding='utf-8')
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: foreign)
    request = body(service, backend='model-router-profiles', profiles={'profiles': [{'name': 'p1', 'description': ''}], 'default': 'p1'})
    request['updates'][0]['allow_profile_access'] = True
    with pytest.raises(ValueError, match='native profile resolution'): service.delegation_preview(request)
    assert calls == []


def test_custom_continuation_needs_fresh_bound_cost_consent(fixture):
    service, calls, _ = fixture
    request = body(service)
    request['updates'][0]['policy']['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'fixture', 'model': 'backup'}]}
    with pytest.raises(ValueError, match='additional-cost'): service.delegation_preview(request)
    request['updates'][0]['allow_additional_cost'] = True
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    config = yaml.safe_load((service.root / 'config.yaml').read_text())
    block = get_path(config, ns.KEY_POLICY)
    assert ns.validate_policy_block('default', block)['heavy']['mode'] == 'custom'
    with pytest.raises(ValueError): ns.validate_policy_block('p1', block)
    assert get_path(config, 'delegation.fallback_providers') is None


def test_config_race_consumes_plan_before_any_write(fixture):
    service, calls, writer = fixture
    plan = service.delegation_preview(body(service))
    writer('default', ns.KEY_BACKEND, 'unrelated')
    calls.clear()
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert calls == []
    with pytest.raises(ServiceError): service.apply(plan['plan_id'])


def test_missing_target_or_changed_capability_refuses_even_noop(fixture, monkeypatch):
    service, calls, _ = fixture
    assert service.apply(service.delegation_preview(body(service))['plan_id'])['status'] == 'applied'
    calls.clear()
    plan = service.delegation_preview(body(service))
    monkeypatch.setattr(service, '_native_delegation_code_signature', lambda profile: 'changed-code')
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert calls == []


def test_target_revocation_between_preview_and_apply_refuses(fixture):
    service, calls, _ = fixture
    request = body(service, backend='model-router-profiles', profiles={'profiles': [{'name': 'p1', 'description': ''}], 'default': None})
    request['updates'][0]['allow_profile_access'] = True
    plan = service.delegation_preview(request)
    (service.root / 'profiles/p1/config.yaml').unlink()
    with pytest.raises(ValueError): service.apply(plan['plan_id'])
    assert calls == []


def test_ambiguous_writer_readback_is_partial_not_retried(fixture, monkeypatch):
    service, calls, writer = fixture
    attempts = []
    def bad(profile, key, value):
        attempts.append((profile, key))
        if len(attempts) == 2: raise OSError('transport lost')
        writer(profile, key, value)
    monkeypatch.setattr(service, 'writer', bad)
    receipt = service.apply(service.delegation_preview(body(service))['plan_id'])
    assert receipt['status'] == 'partial' and len(attempts) == 2
    assert receipt['applied'] == [{'profile': 'default', 'key': ns.KEY_POLICY}]
    assert get_path(yaml.safe_load((service.root / 'config.yaml').read_text()), ns.KEY_BACKEND) is None


def test_wrong_owner_cannot_consume_plan(fixture, monkeypatch):
    service, calls, _ = fixture
    plan = service.delegation_preview(body(service))
    monkeypatch.setattr(service, 'active_profile', lambda: 'p2')
    with pytest.raises(ServiceError, match='another profile'): service.apply(plan['plan_id'])
    assert calls == []
    monkeypatch.setattr(service, 'active_profile', lambda: 'default')
    assert service.apply(plan['plan_id'])['status'] == 'applied'


def test_noop_and_expiry_keep_the_same_one_shot_boundary(fixture, monkeypatch):
    service, calls, _ = fixture
    assert service.apply(service.delegation_preview(body(service))['plan_id'])['status'] == 'applied'
    calls.clear()
    plan = service.delegation_preview(body(service))
    assert plan['changes'] == []
    assert service.apply(plan['plan_id'])['status'] == 'no_change'
    assert calls == []
    plan = service.delegation_preview(body(service))
    monkeypatch.setattr('model_router.service.time.time', lambda: plan['expires_at'] + 1)
    with pytest.raises(ServiceError, match='expired'): service.apply(plan['plan_id'])
    assert calls == []
    with pytest.raises(ServiceError, match='consumed'): service.apply(plan['plan_id'])


def test_noop_final_capability_loss_never_reports_no_change(fixture, monkeypatch):
    service, calls, _ = fixture
    service.apply(service.delegation_preview(body(service))['plan_id'])
    calls.clear()
    plan = service.delegation_preview(body(service))
    count = [0]
    def signature(profile):
        count[0] += 1
        return 'fixture-code' if count[0] <= 2 else 'changed-code'
    monkeypatch.setattr(service, '_native_delegation_code_signature', signature)
    receipt = service.apply(plan['plan_id'])
    assert receipt['status'] == 'partial' and calls == []


def test_deleted_profile_metadata_can_be_explicitly_revoked(fixture):
    service, calls, _ = fixture
    request = body(service, backend='model-router-profiles', profiles={'profiles': [{'name': 'p1', 'description': 'evidence'}], 'default': 'p1'})
    request['updates'][0]['allow_profile_access'] = True
    service.apply(service.delegation_preview(request)['plan_id'])
    (service.root / 'profiles/p1/config.yaml').unlink()
    dto = native_service.status(service, 'default')
    assert dto['editable'] and dto['profile_routes']['default'] == 'p1'
    request = body(service, backend='model-router-profiles')
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'default')['profile_routes'] == {'profiles': [], 'default': None}


def test_advanced_owned_declarations_never_leak_to_the_dto(fixture):
    service, calls, writer = fixture
    writer('default', ns.KEY_POLICY, {'api_key': 'PRIVATE_FIXTURE_MARKER', 'unexpected': True})
    dto = native_service.status(service, 'default')
    assert dto['editable'] is False
    assert 'PRIVATE_FIXTURE_MARKER' not in json.dumps(dto)


def test_native_semantic_accessor_refuses_canonical_model_drift(fixture, monkeypatch):
    service, _, _ = fixture
    monkeypatch.setattr(service, 'routing_config', lambda profile: {'revision': 7})
    monkeypatch.setattr(service, '_load_store', lambda: {'revision': 7, 'profiles': {'default': {'models': {'main': 'stored'}}}})
    monkeypatch.setattr(service, '_actual_models', lambda profile: {'main': 'external-change'})
    with pytest.raises(RevisionConflict, match='model drift'): service.native_route_config('default')


def test_real_supported_config_writer_in_an_isolated_installed_home(tmp_path, monkeypatch):
    import shutil
    root = Path(__file__).resolve().parents[1]
    home = tmp_path / 'installed-home'
    shutil.copytree(root, home / 'plugins/model-router',
        ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__', '.hermes-catalog.json'))
    (home / 'config.yaml').write_text(json.dumps({
        'model': {'provider': 'openrouter', 'default': 'offline-fixture'},
        'plugins': {'enabled': ['model-router']},
        'unrelated': {'keep': 'exact-fixture'},
    }), encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.delenv('HERMES_PROFILE', raising=False)
    service = Service(root=home)
    dto = native_service.status(service, 'default')
    assert dto['supported'] and dto['editable'], dto
    request = body(service)
    receipt = service.apply(service.delegation_preview(request)['plan_id'])
    assert receipt['status'] == 'applied', receipt
    after = yaml.safe_load((home / 'config.yaml').read_text())
    assert after['delegation']['backend'] == 'model-router'
    assert after['unrelated'] == {'keep': 'exact-fixture'}
    assert not service.store_path.exists()


def test_managed_overlay_is_sanitized_readonly(fixture, monkeypatch):
    service, calls, _ = fixture
    snapshot = effective_config.make_key_snapshot(keys=ns.KEYS,
        raw={key: None for key in ns.KEYS}, effective={key: None for key in ns.KEYS},
        managed_keys=(ns.KEY_BACKEND,), managed_signature='fixture')
    monkeypatch.setattr(service, '_read_native_delegation_snapshot', lambda profile: snapshot)
    dto = native_service.status(service, 'default')
    assert dto['editable'] is False and dto['backend'] == 'unavailable'
    assert calls == []
