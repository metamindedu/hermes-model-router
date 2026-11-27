"""Task slots: per-slot primary models and spare models. Fake homes only."""
import copy
import json
from types import SimpleNamespace

import pytest
from agent.delegation_provider import DelegationRouteError

from model_router import execution_roster, native_delegation as nd, native_service, native_settings as ns, slots, task_presentation
from model_router.service import SCHEMA, SLOT_SCHEMA, Service, ServiceError
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
    assert set(slots.SLOT_TIERS) == set(slots.BUILTIN_SLOTS) == set(slots.PURPOSE_SLOTS.values())
    # Existing purposes keep their position and tier; the new one is appended.
    assert list(slots.PURPOSE_SLOTS)[:6] == ['implementation', 'mechanical', 'preliminary-review', 'plan', 'semantic-final', 'independent-review']
    assert {p: slots.PURPOSE_ROLES[p] for p in list(slots.PURPOSE_SLOTS)[:6]} == {
        'implementation': 'light', 'mechanical': 'light', 'preliminary-review': 'light',
        'plan': 'heavy', 'semantic-final': 'heavy', 'independent-review': 'heavy'}
    assert slots.PURPOSE_SLOTS['computer-use'] == 'computer-use' and slots.PURPOSE_ROLES['computer-use'] == 'light'
    assert list(slots.PURPOSE_SLOTS)[-1] == 'advise' and slots.PURPOSE_SLOTS['advise'] == 'advise' and slots.PURPOSE_ROLES['advise'] == 'heavy'
    assert slots.ADVISOR_PURPOSES == {'advise'} and slots.LEGACY_SLOT_SETS == (frozenset(slots.BUILTIN_SLOTS[:6]),)
    assert nd.PURPOSE_ROLES == slots.PURPOSE_ROLES == execution_roster._PURPOSES
    assert set(task_presentation.PURPOSE_LABELS) == set(task_presentation.PURPOSE_DEFAULTS) == set(slots.PURPOSE_SLOTS)
    assert ns.BUILTIN_SLOTS is slots.BUILTIN_SLOTS


def test_untouched_install_resolves_every_slot_through_its_tier(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == SCHEMA and all('slots' not in entry['routing'] for entry in stored['profiles'].values())
    config = service.routing_config('p1')
    models = make_models('1')
    assert config['slots'] == {slot: models['main' if tier == 'heavy' else 'delegation'] for slot, tier in slots.SLOT_TIERS.items()}
    row = find_profile(service.status(), 'p1')
    assert row['slots']['stored'] == []
    assert row['slots']['declarations'] == {slot: {'follow': 'main' if tier == 'heavy' else 'delegation', 'custom': None}
                                            for slot, tier in slots.SLOT_TIERS.items()}
    # A tier that already uses a separate model is what its never-set slots show and run on.
    body['routing']['heavy'] = {'follow': 'custom', 'custom': route('operator', 'old-heavy', 'high')}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    assert service.routing_config('p1')['slots']['design'] == route('operator', 'old-heavy', 'high')
    assert find_profile(service.status(), 'p1')['slots']['declarations']['verify-complex'] == body['routing']['heavy']
    assert json.loads(service.store_path.read_text())['schema'] == SCHEMA


def test_each_slot_saves_its_own_model_and_only_for_selected_targets(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = copy.deepcopy(cli.values)
    declared = {
        'design': {'follow': 'main', 'custom': None},
        'code-complex': {'follow': 'custom', 'custom': route('operator', 'strong-coder', 'high')},
        'code-simple': {'follow': 'delegation', 'custom': None},
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
    assert stored['schema'] == SLOT_SCHEMA
    assert stored['profiles']['p1']['routing']['slots'] == declared
    assert 'slots' not in stored['profiles']['p2']['routing'] and 'slots' not in stored['profiles']['default']['routing']
    config = Service(service.root, writer=cli.writer).routing_config('p1')
    models = make_models('1')
    assert config['slots'] == {'design': models['main'], 'code-complex': declared['code-complex']['custom'],
                               'code-simple': models['delegation'], 'verify-simple': declared['verify-simple']['custom'],
                               'verify-complex': declared['verify-complex']['custom'], 'computer-use': declared['computer-use']['custom'],
                               'advise': declared['advise']['custom']}
    # The tier pair is untouched and other profiles still resolve through it.
    assert config['heavy'] == models['main'] and config['light'] == models['delegation']
    assert Service(service.root, writer=cli.writer).routing_config('p2')['slots']['design'] == make_models('2')['main']
    row = find_profile(service.status(), 'p1')
    assert row['slots']['stored'] == list(slots.BUILTIN_SLOTS) and row['slots']['declarations'] == declared
    assert cli.values == before  # slot models are plugin settings, never profile config writes


def test_a_client_without_slots_leaves_stored_slots_alone_and_an_empty_map_clears_them(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    body['routing']['slots'] = {'design': {'follow': 'custom', 'custom': route('operator', 'planner', 'high')}}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    status = service.status()
    legacy = {**body, 'expected_revision': status['revision'], 'routing': copy.deepcopy(find_profile(status, 'p1')['routing'])}
    legacy['routing'].pop('slots')
    legacy['routing']['light'] = {'follow': 'custom', 'custom': route('operator', 'old-page-light', 'low')}
    assert service.apply(service.preview(legacy)['plan_id'])['status'] == 'applied'
    kept = json.loads(service.store_path.read_text())['profiles']['p1']['routing']
    assert kept['slots'] == body['routing']['slots'] and kept['light'] == legacy['routing']['light']
    status = service.status()
    cleared = {**legacy, 'expected_revision': status['revision'], 'routing': {**copy.deepcopy(kept), 'slots': {}}}
    assert service.apply(service.preview(cleared)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert 'slots' not in stored['profiles']['p1']['routing'] and stored['schema'] == SCHEMA


@pytest.mark.parametrize('bad', [
    {'unknown-slot': {'follow': 'main', 'custom': None}},
    {'design': {'follow': 'heavy', 'custom': None}},
    {'design': {'follow': 'custom', 'custom': None}},
    {'design': {'follow': 'main', 'custom': {'provider': 'operator', 'model': 'm', 'reasoning': 'high'}}},
    {'design': {'follow': 'custom', 'custom': {'provider': 'operator', 'model': 'm'}}},
    {'design': {'follow': 'custom'}},
    ['design'],
])
def test_invalid_slot_declarations_are_refused_before_any_plan(tmp_path, monkeypatch, bad):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = service.store_path.read_bytes()
    body['routing']['slots'] = bad
    with pytest.raises((ValueError, ServiceError)):
        service.preview(body)
    assert service.store_path.read_bytes() == before


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
    assert json.loads(service.store_path.read_text())['schema'] == SCHEMA


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
                'routing': {key: value for key, value in copy.deepcopy(row['routing']).items() if key != 'slots'},
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
    assert 'slots' not in stored['profiles']['p1']['routing'] and stored['profiles']['p2']['routing']['slots'] == {'design': planner}
    assert stored['schema'] == SLOT_SCHEMA
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


def test_store_schema_and_slot_key_must_agree(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    data = json.loads(service.store_path.read_text())
    for schema, slot_map in ((SLOT_SCHEMA, None), (SCHEMA, {'design': {'follow': 'main', 'custom': None}}), (SLOT_SCHEMA, {})):
        broken = copy.deepcopy(data)
        broken['schema'] = schema
        if slot_map is not None:
            broken['profiles']['p1']['routing']['slots'] = slot_map
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
    config = {'enabled': True, 'heavy': {'provider': 'p', 'model': 'heavy', 'reasoning': 'high'},
              'light': {'provider': 'p', 'model': 'light', 'reasoning': 'low'}, 'slots': slot_routes,
              'heavy_timeout_seconds': 10800, 'light_timeout_seconds': 600}
    return tmp_path, FakeService(config, tmp_path)


@pytest.mark.parametrize('purpose,slot', list(slots.PURPOSE_SLOTS.items()))
def test_purpose_runs_on_its_slot_model_with_its_tier_label_and_limit(env, monkeypatch, purpose, slot):
    home, service = env
    # advise routes only inside an in-flight ask_advisor call (test_advise_guard covers that gate).
    monkeypatch.setattr('model_router.advise_guard.advisor_call_active', lambda home, goal: True)
    seen = []
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda home, goal, role, budget: seen.append((role, budget)) or True)
    provider = nd.ModelRouterProvider(home, lambda: service)
    assert purpose in provider.task_parameters({})['purpose']['enum']
    result = provider.route_task({'purpose': purpose, 'goal': 'goal'}, {})
    tier = slots.SLOT_TIERS[slot]
    assert result == {'provider': 'p', 'model': 'model-for-' + slot, 'reasoning_effort': 'medium', 'label': tier, 'fallback_providers': []}
    assert seen == [(tier, 10800 if tier == 'heavy' else 600)]
    auto = nd.ModelRouterAutoProvider(home, lambda: service)
    assert auto.route_task({'execution': 'model', 'purpose': purpose, 'goal': 'goal'}, {})['label'] == 'model:' + tier


def test_spare_models_apply_per_slot_and_a_two_role_block_applies_by_tier(env, monkeypatch):
    home, service = env
    monkeypatch.setattr('model_router.advise_guard.advisor_call_active', lambda home, goal: True)
    provider = nd.ModelRouterProvider(home, lambda: service)
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    block = ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'code-complex': {'mode': 'custom', 'chain': chain}}, True)
    assert block['schema'] == 2 and set(block['fallbacks']) == set(slots.BUILTIN_SLOTS)
    config = {'backends': {'model-router': block}}
    assert provider.route_task({'purpose': 'implementation', 'goal': 'g'}, config)['fallback_providers'] == chain
    for purpose in ('mechanical', 'preliminary-review', 'plan', 'semantic-final', 'independent-review', 'computer-use'):
        assert provider.route_task({'purpose': purpose, 'goal': 'g'}, config)['fallback_providers'] == []
    legacy = ns.build_policy_block('default', {'heavy': {'mode': 'custom', 'chain': chain}, 'light': {'mode': 'off', 'chain': []}}, True)
    config = {'backends': {'model-router': legacy}}
    for purpose, slot in slots.PURPOSE_SLOTS.items():
        expected = chain if slots.SLOT_TIERS[slot] == 'heavy' else []
        assert provider.route_task({'purpose': purpose, 'goal': 'g'}, config)['fallback_providers'] == expected


def test_slot_consent_is_bound_to_slot_backend_profile_and_chain(env):
    home, service = env
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    consent = ns.make_slot_consent('default', 'model-router', 'design', chain)
    assert consent == nd.make_slot_continuation_consent('default', 'design', chain)
    assert consent != ns.make_slot_consent('default', 'model-router', 'verify-complex', chain)
    assert consent != ns.make_slot_consent('default', 'model-router-auto', 'design', chain)
    assert consent != ns.make_slot_consent('p1', 'model-router', 'design', chain)
    assert consent != ns.make_consent('default', 'model-router', 'heavy', chain)
    provider = nd.ModelRouterProvider(home, lambda: service)
    off = {'mode': 'off', 'chain': [], 'consent': None}
    def block(entry, slot='design'):
        return {'schema': 2, 'fallbacks': {**{s: dict(off) for s in slots.BUILTIN_SLOTS}, slot: entry}}
    good = block({'mode': 'custom', 'chain': chain, 'consent': consent})
    assert provider.route_task({'purpose': 'plan', 'goal': 'g'}, {'backends': {'model-router': good}})['fallback_providers'] == chain
    refused = [
        block({'mode': 'custom', 'chain': chain, 'consent': ns.make_consent('default', 'model-router', 'heavy', chain)}),  # a role consent
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


def test_read_policy_shows_both_shapes_without_rewriting():
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    assert ns.read_policy('default', None) == {'schema': 0, 'policy': ns.default_policy(), 'slot_policy': ns.default_slot_policy()}
    legacy = ns.build_policy_block('default', {'heavy': {'mode': 'custom', 'chain': chain}, 'light': {'mode': 'off', 'chain': []}}, True)
    view = ns.read_policy('default', copy.deepcopy(legacy))
    assert view['schema'] == 1 and view['policy']['heavy'] == {'mode': 'custom', 'chain': chain}
    assert view['slot_policy'] == {slot: {'mode': 'custom', 'chain': chain} if tier == 'heavy' else {'mode': 'off', 'chain': []}
                                   for slot, tier in slots.SLOT_TIERS.items()}
    per_slot = ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'computer-use': {'mode': 'custom', 'chain': chain}}, True)
    view = ns.read_policy('default', per_slot)
    assert view['schema'] == 2 and view['policy'] == ns.default_policy()
    assert view['slot_policy']['computer-use'] == {'mode': 'custom', 'chain': chain}
    with pytest.raises(ValueError, match='additional-cost'):
        ns.build_slot_policy_block('default', {**ns.default_slot_policy(), 'design': {'mode': 'custom', 'chain': chain}}, False)
    with pytest.raises(ValueError):
        ns.build_slot_policy_block('default', {'heavy': {'mode': 'off', 'chain': []}, 'light': {'mode': 'off', 'chain': []}}, True)


def test_native_settings_save_per_slot_spare_models_and_refuse_a_two_role_overwrite(fixture):
    service, calls, _ = fixture
    dto = native_service.status(service, 'default')
    assert dto['policy_schema'] == 0 and dto['slot_policy'] == ns.default_slot_policy() and dto['slot_policy_supported'] is True
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    request = native_body(service)
    update = request['updates'][0]
    update.pop('policy')
    update['slot_policy'] = {**ns.default_slot_policy(), 'verify-complex': {'mode': 'custom', 'chain': chain}}
    with pytest.raises(ValueError, match='additional-cost'):
        service.delegation_preview(copy.deepcopy(request))
    update['allow_additional_cost'] = True
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    written = dict((key, value) for profile, key, value in calls)[ns.KEY_POLICY]
    assert written == ns.build_slot_policy_block('default', update['slot_policy'], True)
    dto = native_service.status(service, 'default')
    assert dto['policy_schema'] == 2 and dto['auto_policy_schema'] == 0
    assert dto['slot_policy']['verify-complex'] == {'mode': 'custom', 'chain': chain} and dto['policy'] == ns.default_policy()
    # An older page's two-role policy cannot silently drop the per-slot spare models.
    legacy = native_body(service)
    with pytest.raises(ValueError, match='per task slot'):
        service.delegation_preview(legacy)
    both = native_body(service)
    both['updates'][0]['slot_policy'] = ns.default_slot_policy()
    with pytest.raises(ValueError, match='update fields'):
        service.delegation_preview(both)


def test_two_role_block_stays_as_stored_until_a_slot_save(fixture):
    service, calls, _ = fixture
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    request = native_body(service)
    request['updates'][0].update(policy={'heavy': {'mode': 'custom', 'chain': chain}, 'light': {'mode': 'off', 'chain': []}}, allow_additional_cost=True)
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    dto = native_service.status(service, 'default')
    assert dto['policy_schema'] == 1 and dto['policy']['heavy'] == {'mode': 'custom', 'chain': chain}
    assert dto['slot_policy']['design'] == dto['slot_policy']['verify-complex'] == {'mode': 'custom', 'chain': chain}
    assert dto['slot_policy']['code-complex'] == {'mode': 'off', 'chain': []}
    calls.clear()
    assert native_service.status(service, 'default') == dto and calls == []  # reading never migrates
    # Another two-role save is still accepted while the stored block has two roles.
    again = native_body(service)
    again['updates'][0].update(policy=ns.default_policy())
    assert service.apply(service.delegation_preview(again)['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'default')['policy_schema'] == 1


def test_slot_policy_needs_a_slot_capable_package(fixture, monkeypatch):
    service, calls, _ = fixture
    monkeypatch.setattr(service, '_slot_capable', lambda profile: False)
    assert native_service.status(service, 'default')['slot_policy_supported'] is False
    request = native_body(service)
    request['updates'][0].pop('policy')
    request['updates'][0]['slot_policy'] = ns.default_slot_policy()
    with pytest.raises(ValueError, match='task slots are unsupported'):
        service.delegation_preview(request)
    assert calls == []


def test_a_copy_keeps_another_profile_stored_slot_that_follows_the_delegation_model(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    # p2 stores an earlier setting: its code-simple slot follows its own delegation model.
    status = service.status()
    own = find_profile(status, 'p2')
    legacy = {'code-simple': {'follow': 'delegation', 'custom': None}, 'design': {'follow': 'main', 'custom': None}}
    p2_body = {**copy.deepcopy(body), 'profile': 'p2', 'models': copy.deepcopy(own['models']),
               'routing': {**copy.deepcopy(own['routing']), 'slots': copy.deepcopy(legacy)}, 'routing_targets': ['p2']}
    assert service.apply(service.preview(p2_body)['plan_id'])['status'] == 'applied'
    # p1 copies its slots (code-simple on the main model) to p1 and p2.
    copied = {'code-simple': {'follow': 'main', 'custom': None},
              'design': {'follow': 'custom', 'custom': route('operator', 'designer', 'high')}}
    body['expected_revision'] = service.status()['revision']
    body['routing']['slots'] = copy.deepcopy(copied)
    body['routing_targets'] = ['p1', 'p2']
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())['profiles']
    assert stored['p1']['routing']['slots'] == copied
    # The legacy slot of the receiving profile is kept exactly; the rest is copied.
    assert stored['p2']['routing']['slots'] == {'code-simple': legacy['code-simple'], 'design': copied['design']}
    assert Service(service.root, writer=cli.writer).routing_config('p2')['slots']['code-simple'] == make_models('2')['delegation']
