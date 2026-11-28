"""Partial section saves (`partial_save_schema: 1`): the service side of v0.15.0.

The page's real bodies are covered by tests/test_partial_save_contract.py; these tests pin the edge
cases: the strict marker, compare-and-set narrowed to the written slots, refusals that write nothing,
consent only for new authority, and the earlier (no-marker) bodies keeping their meaning.
"""
import copy
import json

import pytest

from model_router import native_service, native_settings as ns
from model_router.service import PARTIAL_SAVE_SCHEMA, ExternalChange, Service
from model_router.timeouts import read_timeouts, write_timeouts
from test_native_service import fixture, put_path  # noqa: F401 (pytest fixture)
from test_page_expectations import mapping
from test_service import find_profile, route, setup_home

DESIGN = {'follow': 'custom', 'custom': route('operator', 'designer', 'high')}
CHECKER = {'follow': 'custom', 'custom': route('operator', 'checker', 'low')}


def store(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    monkeypatch.setattr(Service, '_timeout_enforcement_available', lambda self, profile: True)
    service = Service(root=root, writer=cli.writer)
    service.initialize(['default', 'p1', 'p2'])
    return service, cli


def full_slot_save(service, name, slots):
    status = service.status()
    row = find_profile(status, name)
    body = {'expected_revision': status['revision'], 'profile': name, 'save_scope': 'routing',
            'models': copy.deepcopy(row['models']), 'model_targets': [],
            'routing': {**copy.deepcopy(row['routing']), 'slots': copy.deepcopy(slots)}, 'routing_targets': [name],
            'routing_profiles': ['default', 'p1', 'p2']}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'


def partial_slot_body(service, slots, targets=('p1', 'p2'), origin='p1'):
    """What the page sends: membership plus only the written slots, expectations narrowed to them."""
    status = service.status()
    expected = []
    for row in status['profiles']:
        frozen = mapping(row)['routing']
        expected.append({'profile': row['name'], 'routing': {'enabled': frozen['enabled'], 'skill_enabled': frozen['skill_enabled'],
                                                             'slots': {slot: (frozen['slots'] or {}).get(slot) for slot in slots}}})
    return {'partial_save_schema': 1, 'expected_revision': status['revision'], 'profile': origin, 'save_scope': 'routing',
            'models': copy.deepcopy(find_profile(status, origin)['models']), 'model_targets': [],
            'routing': {'enabled': True, 'slots': copy.deepcopy(slots)}, 'routing_targets': list(targets),
            'routing_profiles': ['default', 'p1', 'p2'], 'expected': expected}


def edit_store(service, name, slots):
    """A change made elsewhere at the same revision (another window, a hand edit)."""
    data = json.loads(service.store_path.read_text(encoding='utf-8'))
    data['profiles'][name]['routing']['slots'] = copy.deepcopy(slots)
    service.store_path.write_text(json.dumps(data), encoding='utf-8')


def test_status_advertises_the_partial_save_schema(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    assert service.status()['partial_save_schema'] == PARTIAL_SAVE_SCHEMA == 1


@pytest.mark.parametrize('marker', [2, 0, True, '1', 1.0, None, [1]])
def test_an_unknown_marker_is_refused_by_both_endpoints(tmp_path, monkeypatch, marker):
    service, _ = store(tmp_path, monkeypatch)
    body = partial_slot_body(service, {'design': DESIGN})
    body['partial_save_schema'] = marker
    with pytest.raises(ValueError, match='partial_save_schema must be 1'):
        service.preview(body)
    with pytest.raises(ValueError, match='partial_save_schema must be 1'):
        service.delegation_preview({'partial_save_schema': marker, 'expected_revision': 0, 'updates': []})
    assert not list((service.store_path.parent / 'plans').glob('*.json'))


def test_a_sibling_slot_changed_elsewhere_does_not_block_and_is_kept(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    full_slot_save(service, 'p2', {'verify-simple': CHECKER})
    body = partial_slot_body(service, {'design': DESIGN})
    elsewhere = {'verify-simple': {'follow': 'custom', 'custom': route('operator', 'changed-elsewhere', 'low')}}
    edit_store(service, 'p2', elsewhere)
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text(encoding='utf-8'))['profiles']
    assert stored['p2']['routing']['slots'] == {'design': DESIGN, **elsewhere}
    assert stored['p1']['routing']['slots'] == {'design': DESIGN}
    assert stored['default']['routing']['slots'] == {}, 'an untargeted profile keeps its own (empty) slots'


def test_a_submitted_slot_changed_elsewhere_refuses_with_a_structured_conflict(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    full_slot_save(service, 'p2', {'verify-simple': CHECKER})  # the store now holds slots
    body = partial_slot_body(service, {'design': DESIGN})
    edit_store(service, 'p2', {'verify-simple': CHECKER, 'design': {'follow': 'custom', 'custom': route('operator', 'theirs', 'high')}})
    before = service.store_path.read_bytes()
    with pytest.raises(ExternalChange) as caught:
        service.preview(body)
    assert (caught.value.profile, caught.value.field) == ('p2', 'routing')
    assert service.store_path.read_bytes() == before
    # The same change between preview and apply: the apply refuses and writes nothing.
    (tmp_path / 'again').mkdir()
    service, _ = store(tmp_path / 'again', monkeypatch)
    full_slot_save(service, 'p1', {'verify-simple': CHECKER})
    plan = service.preview(partial_slot_body(service, {'design': DESIGN}))
    edit_store(service, 'p1', {'design': CHECKER})
    before = service.store_path.read_bytes()
    with pytest.raises(ExternalChange):
        service.apply(plan['plan_id'])
    assert service.store_path.read_bytes() == before


def test_a_partial_routing_expectation_must_cover_every_written_slot(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    body = partial_slot_body(service, {'design': DESIGN, 'verify-simple': CHECKER})
    for item in body['expected']:
        item['routing']['slots'].pop('verify-simple')
    with pytest.raises(ValueError, match='expected must cover routing.slots of p1'):
        service.preview(body)
    # An unknown key in a narrowed expectation is refused as malformed.
    body = partial_slot_body(service, {'design': DESIGN})
    body['expected'][0]['routing']['extra'] = None
    with pytest.raises(ValueError, match='malformed'):
        service.preview(body)


def test_a_partial_routing_body_has_only_enabled_and_slots(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    for extra in ({'heavy': DESIGN}, {'fallback': {'enabled': False, 'heavy': None, 'light': None}}):
        body = partial_slot_body(service, {'design': DESIGN})
        body['routing'].update(extra)
        with pytest.raises(ValueError, match='routing must define enabled'):
            service.preview(body)
    # Without the marker a routing body is a full one: every slot it names replaces the stored map.
    legacy = partial_slot_body(service, {'design': DESIGN})
    legacy.pop('partial_save_schema')
    with pytest.raises(ValueError, match='malformed'):
        service.preview(copy.deepcopy(legacy))  # a narrowed expectation with null slots is partial-only
    for item in legacy['expected']:
        item['routing'] = mapping(find_profile(service.status(), item['profile']))['routing']
    assert service.apply(service.preview(legacy)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text(encoding='utf-8'))['profiles']
    assert stored['p1']['routing']['slots'] == stored['p2']['routing']['slots'] == {'design': DESIGN}


def test_an_empty_partial_slot_map_is_refused(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    body = partial_slot_body(service, {})
    with pytest.raises(ValueError, match='at least one slot'):
        service.preview(body)


def test_a_legacy_body_still_replaces_the_slot_map(tmp_path, monkeypatch):
    # Without the marker a slot map is the whole map (an empty one clears it), exactly as before.
    service, _ = store(tmp_path, monkeypatch)
    full_slot_save(service, 'p1', {'design': DESIGN, 'verify-simple': CHECKER})
    full_slot_save(service, 'p1', {'design': DESIGN})
    assert json.loads(service.store_path.read_text(encoding='utf-8'))['profiles']['p1']['routing']['slots'] == {'design': DESIGN}


def test_a_partial_timeout_patch_merges_per_target_and_is_strict_without_the_marker(tmp_path, monkeypatch):
    service, _ = store(tmp_path, monkeypatch)
    for name, values in (('p1', {'delegate_total_seconds': 60, 'slot_seconds': {'code-simple': 1800, 'verify-complex': 7200}}),
                         ('p2', {'delegate_total_seconds': 30, 'slot_seconds': {'code-simple': 4000}})):
        write_timeouts(service._profile_home(name), values, expected_digest='MISSING', expected_revision=0)
    status = service.status()
    row = find_profile(status, 'p1')
    body = {'expected_revision': status['revision'], 'profile': 'p1', 'save_scope': 'timeouts', 'models': copy.deepcopy(row['models']),
            'model_targets': [], 'routing': {'enabled': True}, 'routing_targets': [], 'routing_profiles': ['default', 'p1', 'p2'],
            'timeout_updates': [{'profile': 'p1', 'expected_revision': 1, 'slot_seconds': {'verify-complex': 900}},
                                {'profile': 'p2', 'expected_revision': 1, 'slot_seconds': {'verify-complex': 900}}]}
    legacy = copy.deepcopy(body)
    legacy['routing'] = copy.deepcopy(row['routing'])
    with pytest.raises(ValueError):
        service.preview(legacy)  # a patch is not a full timeout update
    body['partial_save_schema'] = 1
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    assert read_timeouts(service._profile_home('p1'))['slot_seconds'] == {'code-simple': 1800, 'verify-complex': 900}
    assert read_timeouts(service._profile_home('p2'))['slot_seconds'] == {'code-simple': 4000, 'verify-complex': 900}
    assert read_timeouts(service._profile_home('p2'))['delegate_total_seconds'] == 30
    # The per-target revision compare-and-set is unchanged.
    status = service.status()
    body.update(expected_revision=status['revision'], timeout_updates=[{'profile': 'p2', 'expected_revision': 1, 'delegate_total_seconds': 5}])
    with pytest.raises(Exception, match='timeout settings changed'):
        service.preview(body)
    # Unknown fields in a partial update are refused.
    body['timeout_updates'] = [{'profile': 'p2', 'expected_revision': 2, 'routed_total_seconds': 5}]
    with pytest.raises(ValueError):
        service.preview(body)


# ---- '/delegation-preview' ----

def native_update(service, name, **fields):
    return {'profile': name, 'expected_digest': native_service.status(service, name)['digest'], 'allow_profile_access': False, **fields}


def seed(service, name, key, value):
    path = service.root / 'config.yaml' if name == 'default' else service.root / 'profiles' / name / 'config.yaml'
    from model_router.yaml_compat import yaml
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    put_path(config, key, value)
    path.write_text(yaml.safe_dump(config), encoding='utf-8')


SPARE = {'mode': 'custom', 'chain': [{'provider': 'spare-service', 'model': 'design-spare'}]}


def test_a_slot_patch_keeps_every_other_slot_and_its_consent(fixture):
    service, calls, _ = fixture
    policy = {**ns.default_slot_policy(), 'verify-complex': {'mode': 'custom', 'chain': [{'provider': 'other', 'model': 'kept'}]}}
    stored = ns.build_slot_policy_block('p1', policy, True)
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router')
    seed(service, 'p1', ns.KEY_POLICY, stored)
    request = {'partial_save_schema': 1, 'expected_revision': 0,
               'updates': [native_update(service, 'p1', slot_policy_patch={'design': SPARE}, allow_additional_cost=True)]}
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    written = {key: value for profile, key, value in calls if profile == 'p1'}
    assert ns.KEY_BACKEND not in written, 'the method is not sent, so it is not written'
    block = written[ns.KEY_POLICY]
    assert block['fallbacks']['verify-complex'] == stored['fallbacks']['verify-complex']
    assert block['fallbacks']['design']['consent'] == ns.make_slot_consent('p1', 'model-router', 'design', SPARE['chain'])


def test_slot_patch_cost_confirmation_matches_the_submitted_slots(fixture):
    service, calls, _ = fixture
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router')
    custom = {'partial_save_schema': 1, 'expected_revision': 0,
              'updates': [native_update(service, 'p1', slot_policy_patch={'design': SPARE}, allow_additional_cost=False)]}
    with pytest.raises(ValueError, match='additional-cost'):
        service.delegation_preview(custom)
    off = {'partial_save_schema': 1, 'expected_revision': 0,
           'updates': [native_update(service, 'p1', slot_policy_patch={'design': {'mode': 'off', 'chain': []}}, allow_additional_cost=True)]}
    with pytest.raises(ValueError, match='cost confirmation applies only'):
        service.delegation_preview(off)
    missing = {'partial_save_schema': 1, 'expected_revision': 0, 'updates': [native_update(service, 'p1', slot_policy_patch={'design': SPARE})]}
    with pytest.raises(ValueError, match='update fields'):
        service.delegation_preview(missing)
    assert calls == []


def test_partial_delegation_forms_need_the_marker_and_something_to_write(fixture):
    service, calls, _ = fixture
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router')
    patch = native_update(service, 'p1', slot_policy_patch={'design': SPARE}, allow_additional_cost=True)
    with pytest.raises(ValueError, match='update fields'):
        service.delegation_preview({'expected_revision': 0, 'updates': [patch]})
    routes = native_update(service, 'p1', backend='model-router', profile_routes_patch={'remove': ['p2']})
    with pytest.raises(ValueError, match='update fields'):
        service.delegation_preview({'expected_revision': 0, 'updates': [routes]})
    with pytest.raises(ValueError, match='update fields'):
        service.delegation_preview({'partial_save_schema': 1, 'expected_revision': 0, 'updates': [native_update(service, 'p1')]})
    both = native_update(service, 'p1', profile_routes_patch={'remove': ['p2']}, profile_routes={'profiles': [], 'default': None})
    with pytest.raises(ValueError, match='update fields'):
        service.delegation_preview({'partial_save_schema': 1, 'expected_revision': 0, 'updates': [both]})
    unknown = native_update(service, 'p1', profile_routes_patch={'rename': {'p2': 'p3'}})
    with pytest.raises(ValueError, match='invalid profile routes patch'):
        service.delegation_preview({'partial_save_schema': 1, 'expected_revision': 0, 'updates': [unknown]})
    assert calls == []


def test_a_routes_patch_needs_consent_only_for_new_authority(fixture):
    service, calls, _ = fixture
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router-profiles')
    seed(service, 'p1', ns.KEY_PROFILES, {'schema': 1, 'profiles': [{'name': 'p2', 'description': 'own'}], 'default': 'p2'})
    add = {'partial_save_schema': 1, 'expected_revision': 0,
           'updates': [native_update(service, 'p1', profile_routes_patch={'add': [{'name': 'default', 'description': 'new'}]})]}
    with pytest.raises(ValueError):
        service.delegation_preview(copy.deepcopy(add))
    assert calls == []
    # A description edit and a removal add no authority.
    describe = {'partial_save_schema': 1, 'expected_revision': 0,
                'updates': [native_update(service, 'p1', profile_routes_patch={'descriptions': {'p2': 'edited', 'not-listed': 'ignored'}})]}
    assert service.apply(service.delegation_preview(describe)['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'p1')['profile_routes'] == {'profiles': [{'name': 'p2', 'description': 'edited'}], 'default': 'p2'}
    add['updates'][0] = native_update(service, 'p1', profile_routes_patch={'add': [{'name': 'default', 'description': 'new'}]}, allow_profile_access=True)
    assert service.apply(service.delegation_preview(add)['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'p1')['profile_routes']['profiles'] == [{'name': 'p2', 'description': 'edited'}, {'name': 'default', 'description': 'new'}]
    remove = {'partial_save_schema': 1, 'expected_revision': 0,
              'updates': [native_update(service, 'p1', profile_routes_patch={'remove': ['p2']})]}
    assert service.apply(service.delegation_preview(remove)['plan_id'])['status'] == 'applied'
    # The stored default left the list with its profile.
    assert native_service.status(service, 'p1')['profile_routes'] == {'profiles': [{'name': 'default', 'description': 'new'}], 'default': None}


def test_a_routes_patch_default_must_be_in_the_merged_list(fixture):
    service, calls, _ = fixture
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router-profiles')
    request = {'partial_save_schema': 1, 'expected_revision': 0,
               'updates': [native_update(service, 'p1', profile_routes_patch={'default': 'p2'}, allow_profile_access=True)]}
    with pytest.raises(ValueError):
        service.delegation_preview(request)
    assert calls == []


@pytest.mark.parametrize('patch', [{'add': []}, {'remove': []}, {'descriptions': {}}, {'add': [], 'remove': [], 'descriptions': {}}])
def test_a_routes_patch_without_any_operation_is_refused(fixture, patch):
    service, calls, _ = fixture
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router-profiles')
    request = {'partial_save_schema': 1, 'expected_revision': 0, 'updates': [native_update(service, 'p1', profile_routes_patch=patch)]}
    with pytest.raises(ValueError, match='changes nothing'):
        service.delegation_preview(request)
    assert calls == []


def test_an_omitted_method_must_be_a_supported_stored_one(fixture, monkeypatch):
    service, calls, _ = fixture
    # A slot spare-model patch on a target stored on a method without slot models is refused.
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router-profiles')
    request = {'partial_save_schema': 1, 'expected_revision': 0,
               'updates': [native_update(service, 'p1', slot_policy_patch={'design': SPARE}, allow_additional_cost=True)]}
    with pytest.raises(ValueError, match='slot-model delegation method'):
        service.delegation_preview(request)
    seed(service, 'p1', ns.KEY_BACKEND, 'default')
    request['updates'] = [native_update(service, 'p1', slot_policy_patch={'design': SPARE}, allow_additional_cost=True)]
    with pytest.raises(ValueError, match='slot-model delegation method'):
        service.delegation_preview(request)
    # A stored method this writer does not know is never kept silently.
    dto = native_service.status(service, 'p1')
    original = native_service.status
    monkeypatch.setattr(native_service, 'status', lambda svc, name: {**original(svc, name), 'backend': 'advanced-custom'} if name == 'p1' else original(svc, name))
    request['updates'] = [{'profile': 'p1', 'expected_digest': dto['digest'], 'allow_profile_access': False,
                           'profile_routes_patch': {'remove': ['p2']}}]
    with pytest.raises(ValueError, match='stored delegation method is not supported'):
        service.delegation_preview(request)
    assert calls == []


@pytest.mark.parametrize('shape', ['slot_policy'])
def test_a_full_policy_without_a_method_needs_a_slot_model_method(fixture, shape):
    service, calls, _ = fixture
    seed(service, 'p1', ns.KEY_BACKEND, 'model-router-profiles')
    value = {**ns.default_slot_policy(), 'design': SPARE}
    request = {'partial_save_schema': 1, 'expected_revision': 0,
               'updates': [native_update(service, 'p1', **{shape: value}, allow_additional_cost=True)]}
    with pytest.raises(ValueError, match='slot-model delegation method'):
        service.delegation_preview(request)
    assert calls == []
    # With the method sent explicitly the earlier rules are unchanged.
    explicit = {'partial_save_schema': 1, 'expected_revision': 0,
                'updates': [native_update(service, 'p1', backend='model-router', **{shape: value}, allow_additional_cost=True)]}
    assert service.apply(service.delegation_preview(explicit)['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'p1')['backend'] == 'model-router'
