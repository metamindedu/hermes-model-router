"""Cross-language contract: the page's partial section-save bodies against the real service.

tests/fixtures/partial_save_contract.json is generated from the desktop builders by
tests/test_partial_save_contract_desktop.mjs (which fails when it is stale). Each body is fed through
the real preview and apply against a temporary home; no live home, no provider calls.
"""
import copy
import json
from pathlib import Path

import pytest

from model_router import native_service, native_settings as ns
from model_router.service import Service
from model_router.timeouts import read_timeouts, write_timeouts
from model_router.yaml_compat import yaml
from test_native_service import fixture, get_path, put_path  # noqa: F401 (pytest fixture)
from test_service import find_profile, setup_home

FIXTURE = Path(__file__).with_name('fixtures') / 'partial_save_contract.json'
CONTRACT = json.loads(FIXTURE.read_text(encoding='utf-8'))
NATIVE = [case for case in CONTRACT['cases'] if case['kind'] == 'native']
STORE = [case for case in CONTRACT['cases'] if case['kind'] == 'store']
DTO_FIELDS = ('schema', 'supported', 'editable', 'backend', 'policy', 'auto_policy', 'slot_policy', 'auto_slot_policy',
              'policy_schema', 'auto_policy_schema', 'slot_policy_supported', 'auto_supported', 'profile_routes')
MISSING = object()
SPLIT_FIELDS = ('delegate_total_seconds', 'routed_light_total_seconds', 'routed_heavy_total_seconds')

# What each target's allow-list must be after the save (the merge rules, written out independently).
EXPECTED_ROUTES = {
    'profiles-routes-patch': {
        'default': {'profiles': [{'name': 'p1', 'description': 'source description'}, {'name': 'p2', 'description': 'reviewer'}], 'default': 'p2'},
        # Already listed: keeps its own entry; takes the new default.
        'p1': {'profiles': [{'name': 'p2', 'description': 'p1 own description'}], 'default': 'p2'},
        # The automatic method keeps its own (hidden) default.
        'p2': {'profiles': [{'name': 'p1', 'description': 'p2 own'}, {'name': 'p2', 'description': 'reviewer'}], 'default': None},
    },
    'profiles-routes-remove-and-describe': {
        'default': {'profiles': [{'name': 'p2', 'description': 'edited b'}], 'default': 'p2'},
        'p1': {'profiles': [{'name': 'p2', 'description': 'edited b'}], 'default': 'p2'},
    },
}


def _path(service, name):
    return service.root / 'config.yaml' if name == 'default' else service.root / 'profiles' / name / 'config.yaml'


def _raw(config, key):
    for part in key.split('.'):
        if not isinstance(config, dict) or part not in config:
            return MISSING
        config = config[part]
    return config


def _seed_native(service, name, seed):
    path = _path(service, name)
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    put_path(config, ns.KEY_BACKEND, seed['backend'])
    if seed.get('routes') is not None:
        put_path(config, ns.KEY_PROFILES, {'schema': 1, **seed['routes']})
    if seed.get('twoRole'):
        put_path(config, ns.KEY_POLICY, ns.build_policy_block(name, ns.default_policy(), False, backend='model-router'))
    elif seed.get('slot'):
        policy = ns.default_slot_policy()
        custom = {} if seed['slot'] == 'off' else seed['slot']
        for slot, model in custom.items():
            policy[slot] = {'mode': 'custom', 'chain': [{'provider': 'spare-service', 'model': model}]}
        put_path(config, ns.KEY_POLICY, ns.build_slot_policy_block(name, policy, bool(custom), backend='model-router'))
    path.write_text(yaml.safe_dump(config), encoding='utf-8')


def test_the_contract_fixture_is_the_generated_one():
    assert CONTRACT['schema'] == 1 and CONTRACT['generated_by'] == 'tests/test_partial_save_contract_desktop.mjs'
    assert {case['name'] for case in CONTRACT['cases']} >= {
        'native-slot-spare-patch', 'native-slot-spare-off-patch', 'native-method-only', 'native-copy-all',
        'profiles-routes-patch', 'profiles-routes-remove-and-describe', 'slot-merge', 'slot-legacy-collision',
        'slot-copy-all', 'timeout-one-field', 'timeout-copy-all'}
    assert all(case['body']['partial_save_schema'] == 1 for case in CONTRACT['cases'])


@pytest.mark.parametrize('case', NATIVE, ids=[case['name'] for case in NATIVE])
def test_a_partial_delegation_body_writes_only_what_it_names(fixture, case):
    service, calls, _ = fixture
    for name, seed in case['seeds'].items():
        _seed_native(service, name, seed)
    for name, expected in case['dtos'].items():
        actual = native_service.status(service, name)
        for key in DTO_FIELDS:
            assert actual[key] == expected[key], (case['name'], name, key)
    raw_before = {name: _path(service, name).read_bytes() for name in case['seeds']}
    before = {name: yaml.safe_load(raw.decode('utf-8')) for name, raw in raw_before.items()}

    body = copy.deepcopy(case['body'])
    for update in body['updates']:
        assert update['expected_digest'] == f"digest:{update['profile']}"
        update['expected_digest'] = native_service.status(service, update['profile'])['digest']
    receipt = service.apply(service.delegation_preview(body)['plan_id'])
    assert receipt['status'] in ('applied', 'no_change'), receipt

    updates = {update['profile']: update for update in body['updates']}
    for name in case['seeds']:
        if name not in updates:
            # Untargeted, or named by the page as skipped: not one byte changes.
            assert _path(service, name).read_bytes() == raw_before[name], (case['name'], name)
            continue
        update, old = updates[name], before[name]
        after = yaml.safe_load(_path(service, name).read_text(encoding='utf-8'))
        # The method is written only when sent; otherwise the stored value (or its absence) stays.
        assert _raw(after, ns.KEY_BACKEND) == (update['backend'] if 'backend' in update else _raw(old, ns.KEY_BACKEND))
        backend = get_path(after, ns.KEY_BACKEND)
        written = ns.KEY_AUTO_POLICY if backend == 'model-router-auto' else ns.KEY_POLICY
        for key in (ns.KEY_POLICY, ns.KEY_AUTO_POLICY):
            if key == written and ({'slot_policy', 'slot_policy_patch'} & set(update)):
                continue
            assert _raw(after, key) == _raw(old, key), (case['name'], name, key)
        if 'slot_policy_patch' in update:
            stored_old = _raw(old, written)
            base = (ns.build_slot_policy_block(name, ns.default_slot_policy(), False, backend='model-router')
                    if stored_old is MISSING else stored_old)
            block = _raw(after, written)
            for slot, entry in block['fallbacks'].items():
                if slot in update['slot_policy_patch']:
                    assert {'mode': entry['mode'], 'chain': entry['chain']} == update['slot_policy_patch'][slot]
                    assert (entry['consent'] is None) == (entry['mode'] == 'off')
                else:
                    # Every other slot keeps its stored entry exactly, consent included.
                    assert entry == base['fallbacks'][slot], (case['name'], name, slot)
        if 'slot_policy' in update:
            dto = native_service.status(service, name)
            assert dto['auto_slot_policy' if backend == 'model-router-auto' else 'slot_policy'] == update['slot_policy']
        if 'profile_routes_patch' in update:
            assert _raw(after, ns.KEY_PROFILES) == {'schema': 1, **EXPECTED_ROUTES[case['name']][name]}, (case['name'], name)
        elif 'profile_routes' not in update:
            assert _raw(after, ns.KEY_PROFILES) == _raw(old, ns.KEY_PROFILES), (case['name'], name)
        assert after['delegation']['backends']['unrelated'] == {'keep': True}
        assert {key: value for key, value in after.items() if key != 'delegation'} == {key: value for key, value in old.items() if key != 'delegation'}
    for name in case['skipped']:
        assert name not in updates
    for name in case.get('partly_skipped', []):
        # Named for one part only (for example a default it cannot take); its other changes were checked above.
        assert name in updates and 'default' not in updates[name].get('profile_routes_patch', {}), (case['name'], name)


def _store_setup(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    monkeypatch.setattr(Service, '_timeout_enforcement_available', lambda self, profile: True)
    monkeypatch.setattr(Service, '_timeout_role_enforcement_available', lambda self, profile: True)
    service = Service(root=root, writer=cli.writer)
    service.initialize(['default', 'p1', 'p2'])
    return service, cli


def _seed_slots(service, name, slots):
    status = service.status()
    row = find_profile(status, name)
    body = {'expected_revision': status['revision'], 'profile': name, 'save_scope': 'routing',
            'models': copy.deepcopy(row['models']), 'model_targets': [],
            'routing': {**copy.deepcopy(row['routing']), 'slots': copy.deepcopy(slots)}, 'routing_targets': [name],
            'routing_profiles': [item['name'] for item in status['profiles'] if item['routing']['enabled']]}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'


@pytest.mark.parametrize('case', STORE, ids=[case['name'] for case in STORE])
def test_a_partial_store_body_writes_only_what_it_names(tmp_path, monkeypatch, case):
    service, cli = _store_setup(tmp_path, monkeypatch)
    timeouts_case = case['body']['save_scope'] == 'timeouts'
    for name, seed in case['seeds'].items():
        if timeouts_case:
            if seed['schema'] == 2:
                write_timeouts(service._profile_home(name), {key: seed[key] for key in SPLIT_FIELDS}, expected_digest='MISSING', expected_revision=0)
        else:
            _seed_slots(service, name, seed)
    status = service.status()
    # The page built this body from these rows; the real service must report the same.
    for row in status['profiles']:
        assert row['routing']['enabled'] is True and row['drift'] == []
        if timeouts_case:
            seed = case['seeds'][row['name']]
            assert {key: row['timeouts'].get(key) for key in seed if key != 'warnings'} == {key: value for key, value in seed.items() if key != 'warnings'}
        else:
            assert row['routing'].get('slots') == case['seeds'].get(row['name']), row['name']
    store_before = json.loads(service.store_path.read_text(encoding='utf-8'))['profiles']
    timeouts_before = {name: read_timeouts(service._profile_home(name)) for name in ('default', 'p1', 'p2')}
    body = copy.deepcopy(case['body'])
    body['expected_revision'] = status['revision']
    # The placeholder models stand for the loaded baseline the page sends; a routing- or timeout-scope
    # save does not write them.
    body['models'] = copy.deepcopy(find_profile(status, body['profile'])['models'])
    receipt = service.apply(service.preview(body)['plan_id'])
    assert receipt['status'] in ('applied', 'no_change'), receipt
    after = json.loads(service.store_path.read_text(encoding='utf-8'))['profiles']
    if timeouts_case:
        targets = {update['profile']: update for update in body['timeout_updates']}
        for name in ('default', 'p1', 'p2'):
            current = read_timeouts(service._profile_home(name))
            if name not in targets:
                assert current == timeouts_before[name]
                continue
            sent = {key: value for key, value in targets[name].items() if key in SPLIT_FIELDS}
            assert current['schema'] == 2 and current['revision'] == timeouts_before[name]['revision'] + (1 if sent else 0)
            assert {key: current[key] for key in SPLIT_FIELDS} == {**{key: timeouts_before[name][key] for key in SPLIT_FIELDS}, **sent}
        assert after == store_before, 'a timeout save writes no model or routing state'
        return
    for name in ('default', 'p1', 'p2'):
        if name not in body['routing_targets']:
            assert after[name] == store_before[name], name
            continue
        # Heavy/Light are not sent: each target keeps its own.
        assert after[name]['routing']['heavy'] == store_before[name]['routing']['heavy']
        assert after[name]['routing']['light'] == store_before[name]['routing']['light']
        stored_old = store_before[name]['routing'].get('slots') or {}
        merged = after[name]['routing'].get('slots') or {}
        assert merged == case['merged'][name], name
        for slot in stored_old:
            if slot not in body['routing']['slots'] or slot in case['skips'][name]:
                assert merged[slot] == stored_old[slot], (name, slot)
        for slot in set(merged) - set(stored_old):
            assert slot in body['routing']['slots'], (name, slot, 'absent stays absent')
