"""Native managed-overlay and interleaving regressions against real Hermes readers."""
import copy
import json
from pathlib import Path

import pytest
import yaml

from model_router.service import Service, ServiceError, RevisionConflict
from test_integration import make_home, writer

CHAIN = [{"provider": "xiaomi", "model": "mimo-test"}]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend('C:/Users/ovpow/AppData/Local/hermes/hermes-agent')
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS', '1')
    root = make_home(tmp_path)
    managed = tmp_path / 'managed'
    managed.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(root))
    monkeypatch.setenv('HERMES_PROFILE', 'default')
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    service = Service(root, writer(root))
    service.initialize(['default'])
    return service, root / 'config.yaml', managed / 'config.yaml'


def dto(service):
    return next(p for p in service.status()['profiles'] if p['name'] == 'default')['fallbacks']['native']


def off(service):
    return {'expected_revision': service.status()['revision'],
            'updates': [{'profile': 'default', 'native_fallback': {'enabled': False, 'chain': []}}],
            'confirmations': []}


def set_key(path, key, value):
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    data[key] = value
    path.write_text(yaml.safe_dump(data), encoding='utf-8')


@pytest.mark.parametrize('key', ['fallback_providers', 'fallback_model'])
def test_raw_off_managed_on_is_readonly_and_never_reports_applied(world, key):
    service, path, managed = world
    set_key(path, 'fallback_providers', [])
    set_key(path, 'fallback_model', [])
    managed.write_text(yaml.safe_dump({key: CHAIN}), encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    status = dto(service)
    assert status['enabled'] is True
    assert status['actual_chain'] == CHAIN
    assert status['editable'] is False
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(off(service))
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_managed_advanced_fields_never_leak_or_get_adopted(world):
    service, path, managed = world
    managed.write_text(yaml.safe_dump({'fallback_providers': [{'provider': 'custom', 'model': 'test', 'api_key': 'ONLY_FAKE_SECRET', 'base_url': 'https://fixture.invalid'}]}), encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes(), managed.read_bytes()
    status = dto(service)
    assert status['editable'] is False
    assert 'ONLY_FAKE_SECRET' not in json.dumps(status)
    assert 'fixture.invalid' not in json.dumps(status)
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(off(service))
    assert before == (path.read_bytes(), service.store_path.read_bytes(), managed.read_bytes())


def test_overlay_added_after_preview_invalidates_plan_before_canonical_write(world):
    service, path, managed = world
    plan = service.fallback_preview(off(service))
    managed.write_text(yaml.safe_dump({'fallback_providers': CHAIN}), encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])
    assert before == (path.read_bytes(), service.store_path.read_bytes())


@pytest.mark.parametrize('key', ['fallback_providers', 'fallback_model'])
@pytest.mark.parametrize('replacement', [
    [{'provider': 'custom', 'model': 'test', 'api_key': 'ONLY_FAKE_SECRET', 'base_url': 'https://fixture.invalid'}],
    'malformed',
    [{'provider': 'custom', 'model': f'item-{n}'} for n in range(6)],
])
def test_eligibility_to_cas_race_cannot_adopt_external_native_edit(world, monkeypatch, key, replacement):
    service, path, _managed = world
    proposal = off(service)
    original = service._native_status
    changed = False
    def interleaved(profile, entry, snapshot=None):
        nonlocal changed
        result = original(profile, entry, snapshot)
        if snapshot is not None and not changed:
            changed = True
            set_key(path, key, copy.deepcopy(replacement))
        return result
    monkeypatch.setattr(service, '_native_status', interleaved)
    before_store = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.fallback_preview(proposal)
    assert changed
    assert yaml.safe_load(path.read_text(encoding='utf-8'))[key] == replacement
    assert service.store_path.read_bytes() == before_store


@pytest.mark.parametrize('managed_mapping', [CHAIN[0], {'provider': 'xiaomi'}, {'model': 'managed-test'}])
@pytest.mark.parametrize('modern_too', [False, True])
def test_legacy_mapping_managed_leaf_is_readonly_before_any_mutation(world, managed_mapping, modern_too):
    service, path, managed = world
    set_key(path, 'fallback_model', CHAIN[0])
    if modern_too:
        set_key(path, 'fallback_providers', [{'provider': 'deepseek', 'model': 'flash-test'}])
    managed.write_text(yaml.safe_dump({'fallback_model': managed_mapping}), encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    assert dto(service)['editable'] is False
    for desired in [{'enabled': False, 'chain': []}, {'enabled': True, 'chain': [{'provider': 'other', 'model': 'different'}]}]:
        proposal = off(service)
        proposal['updates'][0]['native_fallback'] = desired
        proposal['confirmations'] = [{'profile': 'default', 'scope': 'native', 'allow_additional_cost': True, 'allow_task_rerun': False}]
        with pytest.raises((ServiceError, ValueError)):
            service.fallback_preview(proposal)
    assert before == (path.read_bytes(), service.store_path.read_bytes())


@pytest.mark.parametrize('invalid_root', ['- not-a-mapping\n', 'some-scalar\n'])
def test_nonmapping_root_disables_both_editors_without_changing_canonical_state(world, invalid_root):
    service, path, _managed = world
    proposal = off(service)
    path.write_text(invalid_root, encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    status = service.status()['profiles'][0]['fallbacks']
    assert status['native']['editable'] is False
    assert status['delegation']['editable'] is False
    for scope, desired in [('native_fallback', {'enabled': False, 'chain': []}), ('delegation_fallback', {'mode': 'off', 'chain': []})]:
        proposal['updates'] = [{'profile': 'default', scope: desired}]
        with pytest.raises((ServiceError, ValueError)):
            service.fallback_preview(proposal)
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_nonmapping_root_after_preview_is_conflict_and_preserves_settings(world):
    service, path, _managed = world
    plan = service.fallback_preview(off(service))
    path.write_text('- root-became-a-list\n', encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])
    assert before == (path.read_bytes(), service.store_path.read_bytes())
