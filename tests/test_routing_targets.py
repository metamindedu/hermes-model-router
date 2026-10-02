"""Exact primary routing-copy scope is separate from enable membership."""
import copy
import json

import pytest

from model_router import effective_config
from model_router.service import Service, RevisionConflict, ServiceError
from test_service import setup_home, find_profile, route


def setup(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(['default', 'p1', 'p2'])
    status = service.status()
    current = find_profile(status, 'p1')
    body = {'expected_revision': status['revision'], 'profile': 'p1',
            'models': copy.deepcopy(current['models']), 'model_targets': [],
            'routing': copy.deepcopy(current['routing']),
            'routing_profiles': ['default', 'p1', 'p2']}
    cli.calls.clear()
    return service, cli, body


def test_all_targets_save_primary_routing_to_every_selected_profile(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['default', 'p1', 'p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'bulk-heavy', 'high')}
    body['routing']['light'] = {'follow': 'custom', 'custom': route('operator', 'bulk-light', 'low')}
    before = copy.deepcopy(cli.values)
    preview = service.preview(body)
    assert {r['profile'] for r in preview['changes'] if r['field'] == 'routing'} == set(body['routing_targets'])
    assert Service(service.root, writer=cli.writer).apply(preview['plan_id'])['status'] == 'applied'
    for name in body['routing_targets']:
        effective = Service(service.root, writer=cli.writer).routing_config(name)
        assert effective['heavy'] == body['routing']['heavy']['custom']
        assert effective['light'] == body['routing']['light']['custom']
    assert cli.values == before


@pytest.mark.parametrize('targets', [[], ['p2']])
def test_explicit_targets_preserve_source_and_unselected_routes(tmp_path, monkeypatch, targets):
    service, cli, body = setup(tmp_path, monkeypatch)
    original = json.loads(service.store_path.read_text())['profiles']
    body['routing_targets'] = targets
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'only-selected', 'high')}
    receipt = service.apply(service.preview(body)['plan_id'])
    assert receipt['status'] in ('applied', 'no_change')
    after = json.loads(service.store_path.read_text())['profiles']
    for name in original:
        if name in targets:
            assert after[name]['routing']['heavy'] == body['routing']['heavy']
        else:
            assert after[name]['routing'] == original[name]['routing']
        for key in ('models', 'native_fallback', 'delegation_fallback', 'fallback_consent'):
            if key in original[name]: assert after[name][key] == original[name][key]
        assert after[name]['routing']['fallback'] == original[name]['routing']['fallback']


def test_legacy_body_still_edits_loaded_profile_only(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'legacy-heavy')}
    service.apply(service.preview(body)['plan_id'])
    assert service.routing_config('p1')['heavy'] == body['routing']['heavy']['custom']
    assert service.routing_config('p2')['heavy']['model'] == 'heavy2'


@pytest.mark.parametrize('targets', [None, 'p1', ['p1', 'p1'], ['not-found'], [True]])
def test_malformed_routing_targets_fail_before_writes(tmp_path, monkeypatch, targets):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = service.store_path.read_bytes()
    body['routing_targets'] = targets
    with pytest.raises((ValueError, TypeError)):
        service.preview(body)
    assert service.store_path.read_bytes() == before
    assert cli.calls == []


def test_follow_resolves_per_target_and_copy_does_not_enable_target(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['default', 'p1', 'p2']
    body['routing_profiles'] = ['p1']
    service.apply(service.preview(body)['plan_id'])
    for name, suffix in [('default', '0'), ('p1', '1'), ('p2', '2')]:
        result = service.routing_config(name)
        assert result['heavy']['model'] == 'heavy' + suffix
        assert result['light']['model'] == 'light' + suffix
        assert result['enabled'] == (name == 'p1')


def test_stale_bulk_plan_rejected(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['default', 'p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'bulk-heavy')}
    plan = service.preview(body)
    other = copy.deepcopy(body)
    other['routing_targets'] = ['p1']
    other['routing']['heavy']['custom']['model'] = 'other-change'
    service.apply(service.preview(other)['plan_id'])
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])
    assert service.store_path.read_bytes() == before


def routing_fallback(heavy, light):
    return {'enabled': True, 'heavy': heavy, 'light': light}


def approve_routing_fallback(service, profile_name, heavy_model, light_model):
    fallback = routing_fallback(route('spare-heavy', heavy_model, 'high'), route('spare-light', light_model, 'low'))
    preview = service.fallback_preview({
        'expected_revision': service.status()['revision'],
        'updates': [{'profile': profile_name, 'routing_fallback': fallback}],
        'confirmations': [{'profile': profile_name, 'scope': 'routing',
                           'allow_additional_cost': True, 'allow_task_rerun': True}],
    })
    assert service.apply(preview['plan_id'])['status'] == 'applied'
    return fallback


@pytest.mark.parametrize('targets', [[], ['p2']])
def test_source_fallback_cannot_be_changed_when_source_is_not_a_routing_target(tmp_path, monkeypatch, targets):
    service, _cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = targets
    body['routing']['fallback'] = routing_fallback(route('spare', 'smuggled-heavy'), route('spare', 'smuggled-light'))
    before = service.store_path.read_bytes()
    with pytest.raises(ValueError, match='fallback_preview'):
        service.preview(body)
    assert service.store_path.read_bytes() == before
    assert not list((service.store_path.parent / 'plans').glob('*.json'))


def test_non_source_retained_fallback_conflict_rejected_without_plan(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    retained = approve_routing_fallback(service, 'p2', 'retained-heavy', 'retained-light')
    body['expected_revision'] = service.status()['revision']
    body['routing_targets'] = ['p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': copy.deepcopy(retained['heavy'])}
    before = service.store_path.read_bytes(), copy.deepcopy(cli.values)
    with pytest.raises(ValueError, match='final primary'):
        service.preview(body)
    assert (service.store_path.read_bytes(), cli.values) == before
    assert not list((service.store_path.parent / 'plans').glob('*.json'))


def test_combined_unrelated_native_update_still_checks_non_source_retained_fallback(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)

    def native_snapshot(_service, profile_name):
        raw = {
            'fallback_providers': copy.deepcopy(cli.values[profile_name].get('fallback_providers', [])),
            'fallback_model': copy.deepcopy(cli.values[profile_name].get('fallback_model', [])),
        }
        return effective_config.make_snapshot(raw=raw, effective=raw)

    monkeypatch.setattr(Service, '_read_native_snapshot', native_snapshot)
    retained = approve_routing_fallback(service, 'p2', 'retained-heavy', 'retained-light')
    body['expected_revision'] = service.status()['revision']
    body['routing_targets'] = ['p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': copy.deepcopy(retained['heavy'])}
    body['fallback_updates'] = [{'profile': 'default', 'native_fallback': {
        'enabled': True, 'chain': [{'provider': 'native-spare', 'model': 'independent'}],
    }}]
    body['fallback_confirmations'] = [{'profile': 'default', 'scope': 'native',
                                       'allow_additional_cost': True, 'allow_task_rerun': False}]
    before = service.store_path.read_bytes(), copy.deepcopy(cli.values)
    with pytest.raises(ValueError, match='final primary'):
        service.preview(body)
    assert (service.store_path.read_bytes(), cli.values) == before
    assert not list((service.store_path.parent / 'plans').glob('*.json'))


def test_combined_primary_and_new_routing_fallback_can_use_old_primary(tmp_path, monkeypatch):
    service, _cli, body = setup(tmp_path, monkeypatch)
    target_before = json.loads(service.store_path.read_text())['profiles']['p2']
    old_primary = copy.deepcopy(target_before['models']['main'])
    body['routing_targets'] = ['p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'new-p2-primary', 'high')}
    body['fallback_updates'] = [{'profile': 'p2', 'routing_fallback': routing_fallback(
        old_primary, route('spare-light', 'new-fallback-light', 'low'),
    )}]
    body['fallback_confirmations'] = [{'profile': 'p2', 'scope': 'routing',
                                       'allow_additional_cost': True, 'allow_task_rerun': True}]
    preview = service.preview(body)
    assert len(list((service.store_path.parent / 'plans').glob('*.json'))) == 1
    receipt = service.apply(preview['plan_id'])
    assert receipt['status'] == 'applied'
    effective = service.routing_config('p2')
    assert effective['heavy'] == body['routing']['heavy']['custom']
    assert effective['fallback'] == body['fallback_updates'][0]['routing_fallback']


def test_copy_preserves_distinct_target_fallbacks_and_consents(tmp_path, monkeypatch):
    service, _cli, body = setup(tmp_path, monkeypatch)
    approve_routing_fallback(service, 'default', 'default-heavy', 'default-light')
    approve_routing_fallback(service, 'p2', 'p2-heavy', 'p2-light')
    body['expected_revision'] = service.status()['revision']
    before = json.loads(service.store_path.read_text())['profiles']
    assert before['default']['routing']['fallback'] != before['p2']['routing']['fallback']
    assert before['default']['fallback_consent']['routing'] != before['p2']['fallback_consent']['routing']

    body['routing_targets'] = ['default', 'p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'copied-heavy', 'high')}
    body['routing']['light'] = {'follow': 'custom', 'custom': route('operator', 'copied-light', 'low')}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    after = json.loads(service.store_path.read_text())['profiles']
    for profile_name in body['routing_targets']:
        assert after[profile_name]['routing']['fallback'] == before[profile_name]['routing']['fallback']
        assert after[profile_name]['fallback_consent'] == before[profile_name]['fallback_consent']
    assert after['default']['routing']['fallback'] != after['p2']['routing']['fallback']
    assert after['default']['fallback_consent']['routing'] != after['p2']['fallback_consent']['routing']


def test_target_only_heavy_light_collision_emits_no_plan(tmp_path, monkeypatch):
    service, _cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['p2']
    same = route('operator', 'same-target-only-route', 'high')
    body['routing']['heavy'] = {'follow': 'custom', 'custom': copy.deepcopy(same)}
    body['routing']['light'] = {'follow': 'custom', 'custom': copy.deepcopy(same)}
    before = service.store_path.read_bytes()
    with pytest.raises(ValueError, match='distinct'):
        service.preview(body)
    assert service.store_path.read_bytes() == before
    assert not list((service.store_path.parent / 'plans').glob('*.json'))


def test_bulk_routing_plan_is_one_shot(tmp_path, monkeypatch):
    service, _cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['p2']
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'one-shot-heavy', 'high')}
    preview = service.preview(body)
    assert service.apply(preview['plan_id'])['status'] == 'applied'
    with pytest.raises(ServiceError, match='consumed'):
        service.apply(preview['plan_id'])
