"""Task slots: per-slot primary models, runtime limits and spare models. Fake homes only."""
import copy
import json
from types import SimpleNamespace

import pytest
from agent.delegation_provider import DelegationRouteError

from model_router import execution_roster, native_delegation as nd, native_service, native_settings as ns, slots
from model_router.service import STORE_SCHEMA, Service, ServiceError
from test_service import setup_home, find_profile, route, make_models
from test_native_service import fixture, body as native_body  # noqa: F401 (pytest fixture)


def setup(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(['default', 'p1', 'p2'])
    status = service.status()
    current = find_profile(status, 'p1')
    body = {'expected_revision': status['revision'], 'profile': 'p1', 'save_scope': 'routing',
            'models': copy.deepcopy(current['models']), 'model_targets': [],
            'routing': copy.deepcopy(current['routing']), 'routing_targets': ['p1'],
            'routing_profiles': ['default', 'p1', 'p2']}
    cli.calls.clear()
    return service, cli, body


def test_slot_table_is_consistent_everywhere():
    assert slots.BUILTIN_SLOTS == ('design', 'code-complex', 'code-simple', 'verify-simple', 'verify-complex', 'computer-use', 'advise')
    assert set(slots.PURPOSE_SLOTS.values()) == set(slots.BUILTIN_SLOTS)
    # Existing purposes keep their position; new ones are appended.
    assert list(slots.PURPOSE_SLOTS) == ['implementation', 'mechanical', 'preliminary-review', 'plan', 'semantic-final',
                                         'independent-review', 'computer-use', 'advise']
    assert slots.ADVISOR_PURPOSES == {'advise'}
    assert slots.FOLLOWS == ('main', 'custom') and slots.DEFAULT_FOLLOW == 'main'
    assert slots.DEFAULT_SLOT_SECONDS == 7200
    assert nd.PURPOSE_SLOTS is slots.PURPOSE_SLOTS and ns.BUILTIN_SLOTS is slots.BUILTIN_SLOTS
    # No tier vocabulary survives anywhere in the slot model.
    for name in ('SLOT_TIERS', 'PURPOSE_ROLES', 'TIERS', 'TIER_FOLLOWS', 'LEGACY_SLOT_SETS', 'complete_slot_keys', 'slot_tiers', 'purpose_roles'):
        assert not hasattr(slots, name) and not hasattr(nd, name)


def test_untouched_install_runs_every_slot_on_the_main_model_for_two_hours(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA and stored['custom_slots'] == []
    assert all(entry['routing'] == {'enabled': True, 'slots': {}} for entry in stored['profiles'].values())
    config = service.routing_config('p1')
    models = make_models('1')
    assert config['slots'] == {slot: models['main'] for slot in slots.BUILTIN_SLOTS}
    assert config['slot_timeout_seconds'] == {slot: 7200 for slot in slots.BUILTIN_SLOTS}
    assert not {'heavy', 'light', 'fallback', 'slot_tiers', 'purpose_roles', 'heavy_timeout_seconds', 'light_timeout_seconds',
                'timeout_seconds', 'fallback_policy'} & set(config)
    row = find_profile(service.status(), 'p1')
    assert row['routing'] == {'enabled': True, 'slots': {}}
    assert row['slots']['stored'] == []
    assert row['slots']['declarations'] == {slot: {'follow': 'main', 'custom': None} for slot in slots.BUILTIN_SLOTS}
    assert set(row['fallbacks']) == {'native', 'delegation'}
    assert row['timeouts']['slot_seconds'] == {} and row['timeouts']['default_slot_seconds'] == 7200


def test_each_slot_saves_its_own_model_and_only_for_selected_targets(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = copy.deepcopy(cli.values)
    declared = {
        'design': {'follow': 'main', 'custom': None},
        'code-complex': {'follow': 'custom', 'custom': route('operator', 'strong-coder', 'high')},
        'verify-simple': {'follow': 'custom', 'custom': route('other', 'quick-check', 'low')},
        'verify-complex': {'follow': 'custom', 'custom': route('other', 'reviewer', 'xhigh')},
        'computer-use': {'follow': 'custom', 'custom': route('operator', 'screen-model', 'medium')},
        'advise': {'follow': 'custom', 'custom': route('other', 'advisor', 'high')},
    }
    body['routing']['slots'] = copy.deepcopy(declared)
    preview = service.preview(body)
    assert {change['profile'] for change in preview['changes'] if change['field'] == 'routing'} == {'p1'}
    assert service.apply(preview['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA
    assert stored['profiles']['p1']['routing']['slots'] == declared
    assert stored['profiles']['p2']['routing']['slots'] == {} and stored['profiles']['default']['routing']['slots'] == {}
    config = Service(service.root, writer=cli.writer).routing_config('p1')
    models = make_models('1')
    assert config['slots'] == {'design': models['main'], 'code-complex': declared['code-complex']['custom'],
                               'code-simple': models['main'], 'verify-simple': declared['verify-simple']['custom'],
                               'verify-complex': declared['verify-complex']['custom'], 'computer-use': declared['computer-use']['custom'],
                               'advise': declared['advise']['custom']}
    assert Service(service.root, writer=cli.writer).routing_config('p2')['slots']['design'] == make_models('2')['main']
    row = find_profile(service.status(), 'p1')
    assert row['slots']['stored'] == [slot for slot in slots.BUILTIN_SLOTS if slot != 'code-simple']
    assert row['slots']['declarations'] == {**declared, 'code-simple': {'follow': 'main', 'custom': None}}
    assert cli.values == before  # slot models are plugin settings, never profile config writes


def test_a_full_save_replaces_every_slot_and_an_empty_map_clears_them(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing']['slots'] = {'design': {'follow': 'custom', 'custom': route('operator', 'planner', 'high')},
                                'advise': {'follow': 'custom', 'custom': route('operator', 'advisor', 'max')}}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    status = service.status()
    again = {**body, 'expected_revision': status['revision'],
             'routing': {'enabled': True, 'slots': {'advise': body['routing']['slots']['advise']}}}
    assert service.apply(service.preview(again)['plan_id'])['status'] == 'applied'
    assert json.loads(service.store_path.read_text())['profiles']['p1']['routing']['slots'] == {'advise': body['routing']['slots']['advise']}
    cleared = {**body, 'expected_revision': service.status()['revision'], 'routing': {'enabled': True, 'slots': {}}}
    assert service.apply(service.preview(cleared)['plan_id'])['status'] == 'applied'
    assert json.loads(service.store_path.read_text())['profiles']['p1']['routing'] == {'enabled': True, 'slots': {}}


@pytest.mark.parametrize('bad', [
    {'unknown-slot': {'follow': 'main', 'custom': None}},
    {'design': {'follow': 'heavy', 'custom': None}},
    {'design': {'follow': 'delegation', 'custom': None}},
    {'design': {'follow': 'custom', 'custom': None}},
    {'design': {'follow': 'main', 'custom': {'provider': 'operator', 'model': 'm', 'reasoning': 'high'}}},
    {'design': {'follow': 'custom', 'custom': {'provider': 'operator', 'model': 'm'}}},
    {'design': {'follow': 'custom'}},
    {'custom:undefined': {'follow': 'main', 'custom': None}},
    ['design'],
])
def test_invalid_slot_declarations_are_refused_before_any_plan(tmp_path, monkeypatch, bad):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = service.store_path.read_bytes()
    body['routing']['slots'] = bad
    with pytest.raises((ValueError, ServiceError)):
        service.preview(body)
    assert service.store_path.read_bytes() == before


@pytest.mark.parametrize('routing', [
    {'enabled': True},
    {'enabled': True, 'slots': {}, 'heavy': {'follow': 'main', 'custom': None}},
    {'enabled': True, 'slots': {}, 'fallback': {'enabled': False, 'heavy': None, 'light': None}},
])
def test_a_full_routing_save_has_exactly_enabled_and_slots(tmp_path, monkeypatch, routing):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing'] = routing
    with pytest.raises(ValueError):
        service.preview(body)


def test_slots_wait_until_every_installed_profile_can_read_them(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    package = service._profile_home('p2') / 'plugins' / 'model-router'
    (package / 'model_router').mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')  # an older package without slots.py
    status = service.status()
    assert status['slot_capabilities']['blocking_profiles'] == ['p2']
    assert find_profile(status, 'p2')['slots']['capable'] is False and find_profile(status, 'p1')['slots']['capable'] is True
    body['expected_revision'] = status['revision']
    body['routing']['slots'] = {'design': {'follow': 'custom', 'custom': route('operator', 'planner', 'high')}}
    with pytest.raises((ValueError, ServiceError), match='every installed profile'):
        service.preview(body)
    from pathlib import Path
    (package / 'model_router' / 'slots.py').write_bytes(Path(slots.__file__).read_bytes())
    assert service.status()['slot_capabilities']['blocking_profiles'] == []
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'


def test_an_older_package_appearing_after_preview_stops_the_apply_but_not_a_clear(tmp_path, monkeypatch):
    from model_router.service import RevisionConflict
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing']['slots'] = {'design': {'follow': 'custom', 'custom': route('operator', 'planner', 'high')}}
    plan = service.preview(body)['plan_id']
    package = service._profile_home('p2') / 'plugins' / 'model-router'
    (package / 'model_router').mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict, match='every installed profile'):
        service.apply(plan)
    assert service.store_path.read_bytes() == before and cli.calls == []
    # With slots already stored, a save that leaves them as they are, or clears them, is not blocked.
    from pathlib import Path
    (package / 'model_router' / 'slots.py').write_bytes(Path(slots.__file__).read_bytes())
    body['expected_revision'] = service.status()['revision']
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    (package / 'model_router' / 'slots.py').unlink()
    status = service.status()
    assert status['slot_capabilities']['blocking_profiles'] == ['p2']
    clear = dict(body, expected_revision=status['revision'], routing=dict(find_profile(status, 'p1')['routing'], slots={}))
    assert service.apply(service.preview(clear)['plan_id'])['status'] == 'applied'
    assert json.loads(service.store_path.read_text())['profiles']['p1']['routing']['slots'] == {}


def test_apply_gate_stops_only_added_or_changed_slots(tmp_path, monkeypatch):
    from pathlib import Path
    from model_router.service import RevisionConflict
    service, cli, body = setup(tmp_path, monkeypatch)
    planner = {'follow': 'custom', 'custom': route('operator', 'planner', 'high')}
    body['routing']['slots'] = {'design': planner}
    body['routing_targets'] = ['p1', 'p2']
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    package = service._profile_home('default') / 'plugins' / 'model-router'
    (package / 'model_router').mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')  # an older package appears
    status = service.status()
    assert status['slot_capabilities']['blocking_profiles'] == ['default']
    row = find_profile(status, 'p1')

    def scoped(scope, **changes):
        return {'expected_revision': service.status()['revision'], 'profile': 'p1', 'save_scope': scope,
                'models': copy.deepcopy(row['models']), 'model_targets': [], 'routing_targets': [],
                'routing': {'enabled': row['routing']['enabled']},
                'routing_profiles': ['default', 'p1', 'p2'], **changes}

    # A save that leaves stored slots as they are keeps working while the older package is present.
    edited = copy.deepcopy(row['models']); edited['title'] = route('operator', 'new-title', 'none')
    assert service.apply(service.preview(scoped('models', models=edited, model_targets=['p1']))['plan_id'])['status'] == 'applied'
    assert json.loads(service.store_path.read_text())['profiles']['p2']['routing']['slots'] == {'design': planner}
    # Clearing one profile while another keeps its slots removes data only: not stopped at apply.
    clear = scoped('routing', routing_targets=['p1'])
    clear['routing']['slots'] = {}
    assert service.apply(service.preview(clear)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert stored['profiles']['p1']['routing']['slots'] == {} and stored['profiles']['p2']['routing']['slots'] == {'design': planner}
    assert stored['schema'] == STORE_SCHEMA
    # Changing a slot is stopped at apply when the older package appears after the preview.
    (package / 'model_router' / 'slots.py').write_bytes(Path(slots.__file__).read_bytes())
    change = scoped('routing', routing_targets=['p2'])
    change['profile'] = 'p2'
    change['models'] = copy.deepcopy(find_profile(service.status(), 'p2')['models'])
    change['routing']['slots'] = {'design': {'follow': 'main', 'custom': None}}
    plan = service.preview(change)['plan_id']
    (package / 'model_router' / 'slots.py').unlink()
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict, match='every installed profile'):
        service.apply(plan)
    assert service.store_path.read_bytes() == before


def test_a_plan_reply_too_large_for_one_cli_reply_keeps_profile_and_field(tmp_path, monkeypatch):
    from model_router.service import cli_reply, CLI_REPLY_BUDGET
    names = ['default'] + ['profile-%02d' % index for index in range(1, 11)]
    root, cli = setup_home(tmp_path, monkeypatch, profiles=tuple(names))
    service = Service(root=root, writer=cli.writer)
    service.initialize(names)
    status = service.status()
    row = find_profile(status, 'default')
    long = 'x' * 130
    models = {role: route('operator', 'vendor/%s-%s' % (role, long), 'high') for role in row['models']}
    routing = copy.deepcopy(row['routing'])
    routing['slots'] = {slot: {'follow': 'custom', 'custom': route('operator', 'vendor/%s-%s' % (slot, long), 'high')} for slot in slots.BUILTIN_SLOTS}
    plan = service.preview({'expected_revision': status['revision'], 'profile': 'default', 'models': models, 'model_targets': names,
                            'routing': routing, 'routing_targets': names, 'routing_profiles': names})
    full = 'MODEL_ROUTER_JSON:' + json.dumps(plan, ensure_ascii=False, separators=(',', ':'))
    assert len(full) > 48000, 'the fixture must be larger than one Hermes CLI reply'
    line = cli_reply(plan)
    assert len(line) <= CLI_REPLY_BUDGET + len('MODEL_ROUTER_JSON:') < 48000
    sent = json.loads(line.split(':', 1)[1])
    assert sent['changes_compacted'] is True and sent['plan_id'] == plan['plan_id'] and sent['expires_at'] == plan['expires_at']
    assert sent['changes'] == [{'profile': change['profile'], 'field': change['field']} for change in plan['changes']]
    # The stored plan is complete: applying it writes every value.
    assert service.apply(sent['plan_id'])['status'] == 'applied'
    assert all(find_profile(service.status(), name)['models'] == models for name in names)
    # A reply that fits, and any reply without a change list, is printed unchanged.
    small = {'plan_id': 'p', 'changes': plan['changes'][:2], 'warnings': []}
    assert cli_reply(small) == 'MODEL_ROUTER_JSON:' + json.dumps(small, ensure_ascii=False, separators=(',', ':'))
    big_status = service.status()
    assert cli_reply(big_status) == 'MODEL_ROUTER_JSON:' + json.dumps(big_status, ensure_ascii=False, separators=(',', ':'))


def test_paged_status_bounds_each_reply_and_names_what_is_left(tmp_path, monkeypatch):
    names = ['default'] + ['profile-%02d' % index for index in range(1, 24)]
    root, cli = setup_home(tmp_path, monkeypatch, profiles=tuple(names))
    service = Service(root=root, writer=cli.writer)
    service.initialize(names)
    cli.calls.clear()
    full = service.status()
    assert 'pending_profiles' not in full and 'profile_names' not in full
    assert [row['name'] for row in full['profiles']] == names
    size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    assert size(full) > 48000, 'the fixture must be larger than one Hermes CLI reply'
    pages = [service.status(paged=True)]
    while pages[-1]['pending_profiles']:
        assert len(pages) < len(names)
        pages.append(service.status(paged=True, profiles=pages[-1]['pending_profiles']))
    assert len(pages) > 1
    for page in pages:
        assert size(page) <= Service.STATUS_PAGE_BUDGET < 48000 and page['profiles']
        assert page['profile_names'] == names and page['revision'] == full['revision']
        assert {key: value for key, value in page.items() if key not in ('profiles', 'pending_profiles', 'profile_names')} == \
            {key: value for key, value in full.items() if key != 'profiles'}
    assert [row for page in pages for row in page['profiles']] == full['profiles']
    # One row is always returned, even when it alone is over the budget.
    monkeypatch.setattr(Service, 'STATUS_PAGE_BUDGET', 1)
    tiny = service.status(paged=True)
    assert [row['name'] for row in tiny['profiles']] == names[:1] and tiny['pending_profiles'] == names[1:]
    assert [row['name'] for row in service.status(paged=True, profiles=names[5:7])['profiles']] == names[5:6]
    with pytest.raises(ValueError):
        service.status(profiles=names[:1])
    for bad in ([], [names[1], names[1]], ['unknown-profile'], names[1], [1]):
        with pytest.raises(ValueError):
            service.status(paged=True, profiles=bad)
    assert cli.calls == []


def test_only_the_current_store_schema_is_read(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    data = json.loads(service.store_path.read_text())
    entry = data['profiles']['p1']
    broken_entries = [
        {**entry, 'routing': {**entry['routing'], 'heavy': {'follow': 'main', 'custom': None}}},
        {**entry, 'routing': {'enabled': True}},
        {**entry, 'routing': {'enabled': True, 'slots': {'design': {'follow': 'delegation', 'custom': None}}}},
        {**entry, 'fallback_consent': {'native': None, 'routing': None, 'delegation': None}},
        {key: value for key, value in entry.items() if key != 'delegation_fallback'},
    ]
    variants = [{**data, 'schema': schema} for schema in (1, 2, 3, 4, 6, True)]
    variants.append({key: value for key, value in data.items() if key != 'custom_slots'})
    variants += [{**data, 'profiles': {**data['profiles'], 'p1': item}} for item in broken_entries]
    for broken in variants:
        service.store_path.write_text(json.dumps(broken), encoding='utf-8')
        with pytest.raises(ServiceError):
            Service(service.root, writer=cli.writer).status()


class FakeService:
    def __init__(self, config, root):
        self.config = config
        self.root = root
    def active_profile(self): return 'default'
    def routing_config(self, name): return self.config
    native_route_config = routing_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / 'config.yaml').write_text('{}')
    monkeypatch.setattr('hermes_constants.get_hermes_home', lambda: tmp_path)
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: tmp_path)
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda *args: True)
    slot_routes = {slot: {'provider': 'p', 'model': 'model-for-' + slot, 'reasoning': 'medium'} for slot in slots.BUILTIN_SLOTS}
    limits = {slot: 600 + index for index, slot in enumerate(slots.BUILTIN_SLOTS)}
    config = {'enabled': True, 'slots': slot_routes, 'slot_timeout_seconds': limits}
    return tmp_path, FakeService(config, tmp_path)


@pytest.mark.parametrize('purpose,slot', list(slots.PURPOSE_SLOTS.items()))
def test_purpose_runs_on_its_slot_model_with_its_slot_label_and_limit(env, monkeypatch, purpose, slot):
    home, service = env
    # advise routes only inside an in-flight ask_advisor call (test_advise_guard covers that gate).
    monkeypatch.setattr('model_router.advise_guard.advisor_call_active', lambda home, goal: True)
    seen = []
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda home, goal, bound, budget: seen.append((bound, budget)) or True)
    provider = nd.ModelRouterProvider(home, lambda: service)
    assert purpose in provider.task_parameters({})['purpose']['enum']
    result = provider.route_task({'purpose': purpose, 'goal': 'goal'}, {})
    assert result == {'provider': 'p', 'model': 'model-for-' + slot, 'reasoning_effort': 'medium', 'label': slot, 'fallback_providers': []}
    assert seen == [(slot, service.config['slot_timeout_seconds'][slot])]
    # An explicit per-task limit wins over the slot limit.
    seen.clear()
    provider.route_task({'purpose': purpose, 'goal': 'goal', 'total_timeout_seconds': 30}, {})
    assert seen == [(slot, 30)]
    auto = nd.ModelRouterAutoProvider(home, lambda: service)
    assert auto.route_task({'execution': 'model', 'purpose': purpose, 'goal': 'goal'}, {})['label'] == 'model:' + slot


def test_spare_models_apply_per_slot_only(env, monkeypatch):
    home, service = env
    monkeypatch.setattr('model_router.advise_guard.advisor_call_active', lambda home, goal: True)
    provider = nd.ModelRouterProvider(home, lambda: service)
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    block = ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'code-complex': {'mode': 'custom', 'chain': chain}}, True)
    assert block['schema'] == 2 and set(block['fallbacks']) == set(slots.BUILTIN_SLOTS)
    config = {'backends': {'model-router': block}}
    assert provider.route_task({'purpose': 'implementation', 'goal': 'g'}, config)['fallback_providers'] == chain
    for purpose in ('mechanical', 'preliminary-review', 'plan', 'semantic-final', 'independent-review', 'computer-use', 'advise'):
        assert provider.route_task({'purpose': purpose, 'goal': 'g'}, config)['fallback_providers'] == []
    # A block missing a slot (an earlier release's key set) is refused, not completed.
    short = copy.deepcopy(block)
    short['fallbacks'].pop('advise')
    with pytest.raises(DelegationRouteError):
        provider.route_task({'purpose': 'plan', 'goal': 'g'}, {'backends': {'model-router': short}})
    with pytest.raises(ValueError):
        ns.read_policy('default', short)


def test_read_policy_shows_the_per_slot_form_only():
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    assert ns.read_policy('default', None) == {'schema': 0, 'slot_policy': ns.default_slot_policy()}
    per_slot = ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'computer-use': {'mode': 'custom', 'chain': chain}}, True)
    view = ns.read_policy('default', per_slot)
    assert view == {'schema': 2, 'slot_policy': {**ns.default_slot_policy(), 'computer-use': {'mode': 'custom', 'chain': chain}}}
    with pytest.raises(ValueError, match='additional-cost'):
        ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'design': {'mode': 'custom', 'chain': chain}}, False)
    with pytest.raises(ValueError):
        ns.build_slot_policy_block('default', {'heavy': {'mode': 'off', 'chain': []}, 'light': {'mode': 'off', 'chain': []}}, True)
    with pytest.raises(ValueError):
        ns.read_policy('default', {'schema': 1, 'fallbacks': {'heavy': {'mode': 'off', 'chain': [], 'consent': None},
                                                              'light': {'mode': 'off', 'chain': [], 'consent': None}}})
    assert not hasattr(ns, 'ROLES') and not hasattr(ns, 'build_policy_block') and not hasattr(ns, 'make_consent')


def test_native_settings_save_per_slot_spare_models_only(fixture):
    service, calls, _ = fixture
    dto = native_service.status(service, 'default')
    assert dto['policy_schema'] == 0 and dto['slot_policy'] == ns.default_slot_policy() and dto['slot_policy_supported'] is True
    assert 'policy' not in dto and 'auto_policy' not in dto
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    request = native_body(service)
    update = request['updates'][0]
    update['slot_policy'] = {**ns.default_slot_policy(), 'verify-complex': {'mode': 'custom', 'chain': chain}}
    with pytest.raises(ValueError, match='additional-cost'):
        service.delegation_preview(copy.deepcopy(request))
    update['allow_additional_cost'] = True
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    written = dict((key, value) for profile, key, value in calls)[ns.KEY_POLICY]
    assert written == ns.build_slot_policy_block('default', update['slot_policy'], True)
    dto = native_service.status(service, 'default')
    assert dto['policy_schema'] == 2 and dto['auto_policy_schema'] == 0
    assert dto['slot_policy']['verify-complex'] == {'mode': 'custom', 'chain': chain}
    # A two-role policy field is not part of the wire any more.
    legacy = native_body(service)
    legacy['updates'][0]['policy'] = {'heavy': {'mode': 'off', 'chain': []}, 'light': {'mode': 'off', 'chain': []}}
    with pytest.raises(ValueError):
        service.delegation_preview(legacy)


def test_slot_consent_is_bound_to_slot_backend_profile_and_chain(env):
    home, service = env
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    consent = ns.make_slot_consent('default', 'model-router', 'design', chain)
    assert consent == nd.make_slot_continuation_consent('default', 'design', chain)
    assert consent != ns.make_slot_consent('default', 'model-router', 'verify-complex', chain)
    assert consent != ns.make_slot_consent('default', 'model-router-auto', 'design', chain)
    assert consent != ns.make_slot_consent('p1', 'model-router', 'design', chain)
    provider = nd.ModelRouterProvider(home, lambda: service)
    off = {'mode': 'off', 'chain': [], 'consent': None}
    def block(entry, slot='design'):
        return {'schema': 2, 'fallbacks': {**{s: dict(off) for s in slots.BUILTIN_SLOTS}, slot: entry}}
    good = block({'mode': 'custom', 'chain': chain, 'consent': consent})
    assert provider.route_task({'purpose': 'plan', 'goal': 'g'}, {'backends': {'model-router': good}})['fallback_providers'] == chain
    refused = [
        block({'mode': 'custom', 'chain': chain, 'consent': ns.make_slot_consent('default', 'model-router', 'verify-complex', chain)}),
        block({'mode': 'custom', 'chain': chain, 'consent': consent}, slot='verify-complex'),  # moved to another slot
        block({'mode': 'custom', 'chain': [{'provider': 'other', 'model': 'changed'}], 'consent': consent}),
        block({'mode': 'custom', 'chain': [], 'consent': consent}),
        block({'mode': 'off', 'chain': [], 'consent': consent}),
        {'schema': 2, 'fallbacks': {'heavy': dict(off), 'light': dict(off)}},
        {'schema': 1, 'fallbacks': {s: dict(off) for s in slots.BUILTIN_SLOTS}},
        {'schema': 3, 'fallbacks': {s: dict(off) for s in slots.BUILTIN_SLOTS}},
    ]
    for policy in refused:
        # A broken block refuses every task, including slots it does not name: never run without the promised policy.
        with pytest.raises(DelegationRouteError):
            provider.route_task({'purpose': 'plan', 'goal': 'g'}, {'backends': {'model-router': policy}})
        with pytest.raises(ValueError):
            ns.read_policy('default', policy)
    # The same block under the automatic backend needs its own consent.
    with pytest.raises(DelegationRouteError):
        nd.ModelRouterAutoProvider(home, lambda: service).route_task({'execution': 'model', 'purpose': 'plan', 'goal': 'g'}, {'backends': {'model-router-auto': good}})


def test_slot_policy_needs_a_slot_capable_package(fixture, monkeypatch):
    service, calls, _ = fixture
    monkeypatch.setattr(service, '_slot_capable', lambda profile: False)
    assert native_service.status(service, 'default')['slot_policy_supported'] is False
    request = native_body(service)
    request['updates'][0]['slot_policy'] = ns.default_slot_policy()
    with pytest.raises(ValueError, match='task slots are unsupported'):
        service.delegation_preview(request)
    assert calls == []
