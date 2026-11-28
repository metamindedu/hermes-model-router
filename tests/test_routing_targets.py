"""Exact slot-routing copy scope is separate from enable membership."""
import copy
import json

import pytest

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


def custom(model, reasoning='high'):
    return {'follow': 'custom', 'custom': route('operator', model, reasoning)}


def test_all_targets_save_slot_routing_to_every_selected_profile(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['default', 'p1', 'p2']
    body['routing']['slots'] = {'design': custom('bulk-design'), 'code-simple': custom('bulk-coder', 'low')}
    before = copy.deepcopy(cli.values)
    preview = service.preview(body)
    assert {r['profile'] for r in preview['changes'] if r['field'] == 'routing'} == set(body['routing_targets'])
    assert Service(service.root, writer=cli.writer).apply(preview['plan_id'])['status'] == 'applied'
    for name in body['routing_targets']:
        effective = Service(service.root, writer=cli.writer).routing_config(name)
        assert effective['slots']['design'] == body['routing']['slots']['design']['custom']
        assert effective['slots']['code-simple'] == body['routing']['slots']['code-simple']['custom']
    assert cli.values == before


@pytest.mark.parametrize('targets', [[], ['p2']])
def test_explicit_targets_preserve_source_and_unselected_routes(tmp_path, monkeypatch, targets):
    service, cli, body = setup(tmp_path, monkeypatch)
    original = json.loads(service.store_path.read_text())['profiles']
    body['routing_targets'] = targets
    body['routing']['slots'] = {'design': custom('only-selected')}
    receipt = service.apply(service.preview(body)['plan_id'])
    assert receipt['status'] in ('applied', 'no_change')
    after = json.loads(service.store_path.read_text())['profiles']
    for name in original:
        if name in targets:
            assert after[name]['routing']['slots'] == body['routing']['slots']
        else:
            assert after[name]['routing'] == original[name]['routing']
        for key in ('models', 'native_fallback', 'delegation_fallback', 'fallback_consent'):
            assert after[name][key] == original[name][key]


def test_a_body_without_targets_edits_the_loaded_profile_only(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing']['slots'] = {'design': custom('loaded-only', 'medium')}
    service.apply(service.preview(body)['plan_id'])
    assert service.routing_config('p1')['slots']['design'] == body['routing']['slots']['design']['custom']
    assert service.routing_config('p2')['slots']['design']['model'] == 'main-model2'


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
    body['routing']['slots'] = {'design': {'follow': 'main', 'custom': None}}
    service.apply(service.preview(body)['plan_id'])
    for name, suffix in [('default', '0'), ('p1', '1'), ('p2', '2')]:
        result = service.routing_config(name)
        # A slot following the main model resolves to each target's own main model.
        assert result['slots']['design']['model'] == 'main-model' + suffix
        assert result['slots']['code-simple']['model'] == 'main-model' + suffix
        assert result['enabled'] == (name == 'p1')


def test_stale_bulk_plan_rejected(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['default', 'p2']
    body['routing']['slots'] = {'design': custom('bulk-design')}
    plan = service.preview(body)
    other = copy.deepcopy(body)
    other['routing_targets'] = ['p1']
    other['routing']['slots']['design']['custom']['model'] = 'other-change'
    service.apply(service.preview(other)['plan_id'])
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])
    assert service.store_path.read_bytes() == before


def test_same_model_slot_routes_copy_only_selected_target(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['p2']
    same = route('operator', 'same-target-only-route', 'high')
    body['routing']['slots'] = {'design': {'follow': 'custom', 'custom': copy.deepcopy(same)},
                                'verify-complex': {'follow': 'custom', 'custom': copy.deepcopy(same)}}
    before_bytes = service.store_path.read_bytes()
    before = json.loads(before_bytes)['profiles']
    cli_before = copy.deepcopy(cli.values)
    plan = service.preview(body)
    assert service.store_path.read_bytes() == before_bytes
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    after = json.loads(service.store_path.read_bytes())['profiles']
    config = service.routing_config('p2')
    assert config['slots']['design'] == config['slots']['verify-complex'] == same
    for name in before:
        if name != 'p2':
            assert after[name] == before[name]
        else:
            for key in ('models', 'native_fallback', 'delegation_fallback', 'fallback_consent'):
                assert after[name][key] == before[name][key]
            assert after[name]['routing']['enabled'] == before[name]['routing']['enabled']
    assert cli.values == cli_before


def test_bulk_routing_plan_is_one_shot(tmp_path, monkeypatch):
    service, _cli, body = setup(tmp_path, monkeypatch)
    body['routing_targets'] = ['p2']
    body['routing']['slots'] = {'design': custom('one-shot-design')}
    preview = service.preview(body)
    assert service.apply(preview['plan_id'])['status'] == 'applied'
    with pytest.raises(ServiceError, match='consumed'):
        service.apply(preview['plan_id'])
