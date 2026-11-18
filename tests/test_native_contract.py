"""Cross-language contract: the page's /delegation-preview bodies against the real writer.

tests/fixtures/native_delegation_contract.json is generated from the desktop builders by
tests/test_native_contract_desktop.mjs (which fails when it is stale). Each body is fed through the
real native_service preview and apply against a temporary config; no live home, no provider calls.
"""
import copy
import json
from pathlib import Path

import pytest

from model_router import native_service, native_settings as ns
from model_router.yaml_compat import yaml
from test_native_service import fixture, get_path, put_path  # noqa: F401 (pytest fixture)

FIXTURE = Path(__file__).with_name('fixtures') / 'native_delegation_contract.json'
CONTRACT = json.loads(FIXTURE.read_text(encoding='utf-8'))
CASES = CONTRACT['cases']
DTO_FIELDS = ('schema', 'supported', 'editable', 'backend', 'policy', 'auto_policy', 'slot_policy', 'auto_slot_policy',
              'policy_schema', 'auto_policy_schema', 'slot_policy_supported', 'auto_supported', 'profile_routes', 'warnings')
MISSING = object()


def _path(service, name):
    return service.root / 'config.yaml' if name == 'default' else service.root / 'profiles' / name / 'config.yaml'


def _raw(config, key):
    """The stored value at a dotted key, or MISSING when the key is absent (not just None)."""
    for part in key.split('.'):
        if not isinstance(config, dict) or part not in config:
            return MISSING
        config = config[part]
    return config


def _seed(service, name, seed):
    path = _path(service, name)
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    put_path(config, ns.KEY_BACKEND, seed['backend'])
    if seed.get('routes') is not None:
        put_path(config, ns.KEY_PROFILES, {'schema': 1, **seed['routes']})
    if seed.get('slot') == 'off':
        put_path(config, ns.KEY_POLICY, ns.build_slot_policy_block(name, ns.default_slot_policy(), False, backend='model-router'))
    if seed.get('autoSlot') == 'off':
        put_path(config, ns.KEY_AUTO_POLICY, ns.build_slot_policy_block(name, ns.default_slot_policy(), False, backend='model-router-auto'))
    path.write_text(yaml.safe_dump(config), encoding='utf-8')


def test_the_contract_fixture_is_the_generated_one():
    assert CONTRACT['schema'] == 1 and CONTRACT['generated_by'] == 'tests/test_native_contract_desktop.mjs'
    assert {case['name'] for case in CASES} >= {
        'backend-only-method-change', 'model-save-with-slot-cards', 'model-save-auto-source', 'model-save-without-slot-cards',
        'profile-save-profile-source', 'profile-save-auto-source', 'deleted-specialist-method-change'}


@pytest.mark.parametrize('case', CASES, ids=[case['name'] for case in CASES])
def test_a_page_body_is_accepted_and_leaves_every_omitted_part_as_stored(fixture, case):
    service, calls, _ = fixture
    for name, seed in case['seeds'].items():
        _seed(service, name, seed)
    # The page built this body from these status DTOs; the real service must report the same.
    for name, expected in case['dtos'].items():
        actual = native_service.status(service, name)
        for key in DTO_FIELDS:
            assert actual[key] == expected[key], (case['name'], name, key)
        assert actual['role_intro_inheritance']['supported'] == expected['role_intro_inheritance']['supported']
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
            assert _path(service, name).read_bytes() == raw_before[name], (case['name'], name)
            continue
        update, old = updates[name], before[name]
        after = yaml.safe_load(_path(service, name).read_text(encoding='utf-8'))
        assert get_path(after, ns.KEY_BACKEND) == update['backend']
        if 'profile_routes' in update:
            assert _raw(after, ns.KEY_PROFILES) == {'schema': 1, **update['profile_routes']}
        else:
            # Left out: kept exactly as stored, an absent block stays absent, a stale one stays stale.
            assert _raw(after, ns.KEY_PROFILES) == _raw(old, ns.KEY_PROFILES), (case['name'], name)
        written = ns.KEY_AUTO_POLICY if update['backend'] == 'model-router-auto' else ns.KEY_POLICY
        for key in (ns.KEY_POLICY, ns.KEY_AUTO_POLICY):
            if key == written and 'slot_policy' in update:
                continue
            assert _raw(after, key) == _raw(old, key), (case['name'], name, key)
        if 'slot_policy' in update:
            dto = native_service.status(service, name)
            assert dto['auto_slot_policy' if update['backend'] == 'model-router-auto' else 'slot_policy'] == update['slot_policy']
        assert after['delegation']['backends']['unrelated'] == {'keep': True}
        assert {key: value for key, value in after.items() if key != 'delegation'} == {key: value for key, value in old.items() if key != 'delegation'}
