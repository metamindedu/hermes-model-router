"""Operator-added (custom) task slots: definitions, storage, routing and display. Fake homes only."""
import copy
import json
from pathlib import Path

import pytest
from agent.delegation_provider import DelegationRouteError

from model_router import execution_roster, native_delegation as nd, native_settings as ns, native_watchdog, slots
from model_router.service import STORE_SCHEMA, RevisionConflict, Service, ServiceError
from test_service import find_profile, route, make_models
from test_slots import setup, FakeService, env  # noqa: F401 (pytest fixture)

THREE_D = {'id': 'custom:3d-graphics', 'label': '3D·그래픽', 'description': 'Blender Python·Three.js 코드와 렌더 결과 검수'}
WRITING = {'id': 'custom:ko-writing', 'label': '한국어 글쓰기', 'description': '자연스러운 한국어 원고 작성과 윤문'}


def define(service, definitions):
    status = service.status()
    preview = service.custom_slots_preview({'expected_revision': status['revision'], 'custom_slots': copy.deepcopy(definitions)})
    return preview, service.apply(preview['plan_id'])


# ---- definitions --------------------------------------------------------------------------------

def test_definitions_are_validated_strictly():
    assert slots.validate_custom_slots([THREE_D, WRITING]) == [THREE_D, WRITING]
    assert slots.validate_custom_slots([]) == []
    five = [{**THREE_D, 'id': f'custom:slot-{n}', 'label': f'L{n}'} for n in range(5)]
    bad = [
        five,
        [{**THREE_D, 'id': '3d-graphics'}],
        [{**THREE_D, 'id': 'custom:a'}],
        [{**THREE_D, 'id': 'custom:-dash'}],
        [{**THREE_D, 'id': 'custom:Upper'}],
        [{**THREE_D, 'id': 'custom:' + 'x' * 33}],
        [THREE_D, {**WRITING, 'id': THREE_D['id']}],
        [THREE_D, {**WRITING, 'label': '3d·그래픽'.upper()}],
        [{**THREE_D, 'label': ''}],
        [{**THREE_D, 'label': 'x' * 25}],
        [{**THREE_D, 'label': ' padded'}],
        [{**THREE_D, 'description': 'two\nlines'}],
        [{**THREE_D, 'description': 'x' * 121}],
        [{**THREE_D, 'description': 'hidden\u202edirection'}],
        [{**THREE_D, 'label': 'del\x7fchar'}],
        [{**THREE_D, 'label': 'next\x85line'}],
        [{**THREE_D, 'label': 'c1\x9bcontrol'}],
        [{**THREE_D, 'description': 'arabic\u061cmark'}],
        [{**THREE_D, 'description': 'zero\u200bwidth'}],
        [{**THREE_D, 'description': 'joiner\u2060word'}],
        [{**THREE_D, 'description': 'tag\U000e0041char'}],
        [{**THREE_D, 'description': 'mongolian\u180esep'}],
        [{**THREE_D, 'description': 'anchor\ufff9char'}],
        [{**THREE_D, 'description': 'line\u2028separator'}],
        [{**THREE_D, 'label': 'para\u2029separator'}],
        [{**THREE_D, 'label': 'lone\ud800surrogate'}],
        [{**THREE_D, 'label': '\U0001f469\u200d\U0001f4bb 코딩'}],
        [{**THREE_D, 'tier': 'heavy'}],
        [{**THREE_D, 'extra': 1}],
        [{k: v for k, v in THREE_D.items() if k != 'description'}],
        {'custom:3d': THREE_D},
    ]
    for value in bad:
        with pytest.raises(ValueError):
            slots.validate_custom_slots(value)
    assert slots.validate_custom_slots([{**THREE_D, 'id': 'custom:' + 'x' * 32}])


def test_slot_tables_add_custom_slots_after_the_builtins():
    defs = [THREE_D, WRITING]
    assert slots.slot_ids(defs) == (*slots.BUILTIN_SLOTS, THREE_D['id'], WRITING['id'])
    assert list(slots.purpose_slots(defs))[:len(slots.PURPOSE_SLOTS)] == list(slots.PURPOSE_SLOTS)
    assert slots.purpose_slots(defs)[THREE_D['id']] == THREE_D['id'] and slots.purpose_slots(defs)[WRITING['id']] == WRITING['id']
    declaration = {'follow': 'custom', 'custom': route('p', 'm', 'high')}
    # Syntactic check without the definitions, exact check with them.
    assert slots.validate_slots({THREE_D['id']: declaration}, lambda r: r) == {THREE_D['id']: declaration}
    with pytest.raises(ValueError):
        slots.validate_slots({THREE_D['id']: declaration}, lambda r: r, custom_ids=[WRITING['id']])
    with pytest.raises(ValueError):
        slots.validate_slots({'custom-3d': declaration}, lambda r: r)


# ---- storage ------------------------------------------------------------------------------------

def test_defining_and_removing_custom_slots_keeps_the_one_store_schema(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = copy.deepcopy(cli.values)
    preview, receipt = define(service, [THREE_D, WRITING])
    assert receipt['status'] == 'applied'
    assert [c['field'] for c in preview['changes']] == ['custom_slots']
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA and stored['custom_slots'] == [THREE_D, WRITING]
    status = service.status()
    assert status['slot_capabilities']['custom_slots'] == [THREE_D, WRITING]
    assert status['slot_capabilities']['custom_slot_limit'] == 4 and status['slot_capabilities']['custom_slots_supported'] is True
    row = find_profile(status, 'p1')
    models = make_models('1')
    # A never-set custom slot shows and runs on the main model for two hours, like a built-in one.
    assert row['slots']['declarations'][THREE_D['id']] == {'follow': 'main', 'custom': None}
    assert row['slots']['declarations'][WRITING['id']] == {'follow': 'main', 'custom': None}
    config = service.routing_config('p1')
    assert config['slots'][THREE_D['id']] == models['main'] and config['slots'][WRITING['id']] == models['main']
    assert config['purpose_slots'][THREE_D['id']] == THREE_D['id']
    assert config['slot_timeout_seconds'][THREE_D['id']] == config['slot_timeout_seconds'][WRITING['id']] == 7200
    assert cli.values == before  # definitions are plugin settings, never profile config writes
    # Same definitions again: nothing to change.
    preview, receipt = define(service, [THREE_D, WRITING])
    assert preview['changes'] == [] and receipt['status'] == 'no_change'
    preview, receipt = define(service, [])
    assert receipt['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA and stored['custom_slots'] == []


def test_a_custom_slot_model_is_saved_per_profile_and_removed_with_its_definition(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    declaration = {'follow': 'custom', 'custom': route('operator', 'blender-coder', 'high')}
    body['routing']['slots'] = {THREE_D['id']: declaration}
    with pytest.raises(ValueError, match='not defined'):
        service.preview(body)
    define(service, [THREE_D, WRITING])
    body['expected_revision'] = service.status()['revision']
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA and stored['profiles']['p1']['routing']['slots'] == {THREE_D['id']: declaration}
    assert service.routing_config('p1')['slots'][THREE_D['id']] == declaration['custom']
    assert service.routing_config('p2')['slots'][THREE_D['id']] == make_models('2')['main']
    row = find_profile(service.status(), 'p1')
    assert row['slots']['stored'] == [THREE_D['id']]
    # A partial save names only the custom slot.
    status = service.status()
    partial = {**copy.deepcopy(body), 'expected_revision': status['revision'], 'partial_save_schema': 1,
               'routing': {'enabled': True, 'slots': {WRITING['id']: {'follow': 'custom', 'custom': route('operator', 'writer', 'low')}}}}
    assert service.apply(service.preview(partial)['plan_id'])['status'] == 'applied'
    kept = json.loads(service.store_path.read_text())['profiles']['p1']['routing']['slots']
    assert list(kept) == [THREE_D['id'], WRITING['id']] and kept[THREE_D['id']] == declaration
    # Removing a definition removes its declaration from every profile in the same write.
    preview, receipt = define(service, [WRITING])
    assert {(c['profile'], c['field']) for c in preview['changes']} == {('*', 'custom_slots'), ('p1', 'routing.slots')}
    assert receipt['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert stored['custom_slots'] == [WRITING] and list(stored['profiles']['p1']['routing']['slots']) == [WRITING['id']]
    preview, receipt = define(service, [])
    stored = json.loads(service.store_path.read_text())
    assert stored['profiles']['p1']['routing']['slots'] == {} and stored['schema'] == STORE_SCHEMA


def test_built_in_slots_keep_working_beside_custom_ones(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    body['expected_revision'] = service.status()['revision']
    body['routing']['slots'] = {'design': {'follow': 'custom', 'custom': route('operator', 'planner', 'high')}}
    assert service.apply(service.preview(body)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA and stored['custom_slots'] == [THREE_D]
    define(service, [])
    stored = json.loads(service.store_path.read_text())
    assert stored['custom_slots'] == [] and stored['profiles']['p1']['routing']['slots'] == body['routing']['slots']


def test_the_store_refuses_inconsistent_custom_data(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    good = json.loads(service.store_path.read_text())
    declaration = {'follow': 'main', 'custom': None}
    cases = []
    case = copy.deepcopy(good); case['custom_slots'] = [{**THREE_D, 'tier': 'heavy'}]; cases.append(case)
    case = copy.deepcopy(good); case['schema'] = 4; cases.append(case)  # the v0.17 custom schema
    case = copy.deepcopy(good); del case['custom_slots']; cases.append(case)
    case = copy.deepcopy(good); case['profiles']['p1']['routing']['slots'] = {WRITING['id']: declaration}; cases.append(case)
    empty = copy.deepcopy(good); empty['custom_slots'] = []
    empty['profiles']['p1']['routing']['slots'] = {THREE_D['id']: declaration}; cases.append(empty)
    for broken in cases:
        service.store_path.write_text(json.dumps(broken), encoding='utf-8')
        with pytest.raises(ServiceError):
            Service(service.root, writer=cli.writer).status()


def test_custom_slots_preview_is_bounded_and_gated(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    revision = service.status()['revision']
    before = service.store_path.read_bytes()
    for bad in ({'custom_slots': [THREE_D]}, {'expected_revision': revision, 'custom_slots': [THREE_D], 'extra': 1},
                {'expected_revision': True, 'custom_slots': [THREE_D]}, {'expected_revision': revision, 'custom_slots': [{**THREE_D, 'tier': 'heavy'}]}):
        with pytest.raises((ValueError, ServiceError)):
            service.custom_slots_preview(bad)
    with pytest.raises(RevisionConflict):
        service.custom_slots_preview({'expected_revision': revision + 5, 'custom_slots': [THREE_D]})
    # An installed package that cannot read the new slots blocks a new definition, not a removal.
    package = service._profile_home('p2') / 'plugins' / 'model-router'
    (package / 'model_router').mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')
    with pytest.raises(ValueError, match='every installed profile'):
        service.custom_slots_preview({'expected_revision': revision, 'custom_slots': [THREE_D]})
    assert service.store_path.read_bytes() == before
    (package / 'model_router' / 'slots.py').write_bytes(Path(slots.__file__).read_bytes())
    plan = service.custom_slots_preview({'expected_revision': revision, 'custom_slots': [THREE_D]})['plan_id']
    # An older package appearing between preview and apply stops the apply.
    (package / 'model_router' / 'slots.py').write_text('# old', encoding='utf-8')
    with pytest.raises(RevisionConflict):
        service.apply(plan)
    assert service.store_path.read_bytes() == before
    (package / 'model_router' / 'slots.py').write_bytes(Path(slots.__file__).read_bytes())
    plan = service.custom_slots_preview({'expected_revision': revision, 'custom_slots': [THREE_D]})['plan_id']
    # A store changed after the preview stops the apply.
    other = service.custom_slots_preview({'expected_revision': revision, 'custom_slots': [WRITING]})['plan_id']
    assert service.apply(other)['status'] == 'applied'
    with pytest.raises(RevisionConflict):
        service.apply(plan)
    assert json.loads(service.store_path.read_text())['custom_slots'] == [WRITING]
    (package / 'model_router' / 'slots.py').write_text('# old', encoding='utf-8')
    # Removing every definition stays possible while an older package is installed.
    assert define(service, [])[1]['status'] == 'applied'


# ---- routing -------------------------------------------------------------------------------------

def custom_env(env, definitions=(THREE_D, WRITING)):
    home, service = env
    defs = list(definitions)
    service.config['slots'] = {**service.config['slots'], **{d['id']: {'provider': 'p', 'model': 'model-for-' + d['id'], 'reasoning': 'high'} for d in defs}}
    service.config['purpose_slots'] = slots.purpose_slots(defs)
    service.config['slot_timeout_seconds'] = {**service.config['slot_timeout_seconds'], THREE_D['id']: 10800, WRITING['id']: 600}
    service._load_store = lambda: {'custom_slots': defs, 'profiles': {}, 'revision': 1, 'schema': STORE_SCHEMA}
    return home, service


def test_a_custom_purpose_runs_on_its_slot_with_its_own_limit(env, monkeypatch):
    home, service = custom_env(env)
    seen = []
    monkeypatch.setattr('model_router.native_watchdog.verify_routed_binding', lambda home, goal, slot, budget: seen.append((slot, budget)) or True)
    provider = nd.ModelRouterProvider(home, lambda: service)
    parameters = provider.task_parameters({})['purpose']
    assert parameters['enum'] == [*slots.PURPOSE_SLOTS, THREE_D['id'], WRITING['id']]
    hints = json.loads(parameters['description'].split('instructions: ', 1)[1])
    assert hints == [{'purpose': THREE_D['id'], 'label': THREE_D['label'], 'scope': THREE_D['description']},
                     {'purpose': WRITING['id'], 'label': WRITING['label'], 'scope': WRITING['description']}]
    assert 'untrusted descriptive data' in parameters['description']
    for definition, budget in ((THREE_D, 10800), (WRITING, 600)):
        result = provider.route_task({'purpose': definition['id'], 'goal': 'goal'}, {})
        assert result == {'provider': 'p', 'model': 'model-for-' + definition['id'], 'reasoning_effort': 'high',
                          'label': definition['id'], 'fallback_providers': []}
        assert seen[-1] == (definition['id'], budget)
        auto = nd.ModelRouterAutoProvider(home, lambda: service)
        assert definition['id'] in auto.task_parameters({})['purpose']['enum']
        assert auto.route_task({'execution': 'model', 'purpose': definition['id'], 'goal': 'g'}, {})['label'] == 'model:' + definition['id']


def test_an_undefined_or_malformed_custom_purpose_is_refused(env, monkeypatch):
    home, service = custom_env(env, [THREE_D])
    provider = nd.ModelRouterProvider(home, lambda: service)
    for purpose in ('custom:ko-writing', 'custom-3d', 'custom:', None):
        with pytest.raises(DelegationRouteError):
            provider.route_task({'purpose': purpose, 'goal': 'g'}, {})
    with pytest.raises(DelegationRouteError):
        nd.ModelRouterAutoProvider(home, lambda: service).route_task({'execution': 'model', 'purpose': 'custom-3d', 'goal': 'g'}, {})
    # Without readable definitions the enum carries the built-ins only.
    del service._load_store
    assert provider.task_parameters({})['purpose']['enum'] == list(slots.PURPOSE_SLOTS)


def test_custom_slots_have_no_spare_models(env, monkeypatch):
    home, service = custom_env(env)
    provider = nd.ModelRouterProvider(home, lambda: service)
    chain = [{'provider': 'other', 'model': 'spare/v1'}]
    block = ns.build_slot_policy_block('default', {slot: {'mode': 'custom', 'chain': chain} for slot in slots.BUILTIN_SLOTS}, True)
    assert set(block['fallbacks']) == set(slots.BUILTIN_SLOTS)
    for definition in (THREE_D, WRITING):
        assert provider.route_task({'purpose': definition['id'], 'goal': 'g'}, {'backends': {'model-router': block}})['fallback_providers'] == []
    # A per-slot block naming a custom slot is never valid.
    with pytest.raises(ValueError):
        ns.make_slot_consent('default', 'model-router', THREE_D['id'], chain)


def test_the_watchdog_preflight_knows_custom_purpose_limits(env, monkeypatch):
    home, service = custom_env(env)
    monkeypatch.setattr('model_router.service.Service', lambda *a, **k: service)
    monkeypatch.setattr(nd, '_origin', lambda home, service: 'default')
    goals = ['Build the Blender product scene and check the rendered frames for artifacts',
             'Write the Korean landing page copy from the approved outline in docs/outline.md',
             'Do the work of an operator slot that is not defined on this profile at all']
    args = {'tasks': [{'goal': goals[0], 'purpose': THREE_D['id']}, {'goal': goals[1], 'purpose': WRITING['id']},
                      {'goal': goals[2], 'purpose': 'custom:other'}]}
    policies = native_watchdog._routed_policies(home, args)
    assert policies == {goals[0]: (THREE_D['id'], 10800), goals[1]: (WRITING['id'], 600)}


def test_the_status_line_names_a_custom_slot_by_its_label(tmp_path, monkeypatch):
    custom = {THREE_D['id']: THREE_D['label']}
    assert execution_roster._requested({'purpose': THREE_D['id']}, custom) == {
        'kind': 'model', 'profile': None, 'purpose': THREE_D['id'], 'slot': THREE_D['id'], 'slot_label': THREE_D['label']}
    assert execution_roster._requested({'purpose': THREE_D['id']}, {})['kind'] == 'unknown'
    assert execution_roster._requested({'purpose': THREE_D['id'], 'profile': 'x'}, custom)['kind'] == 'unknown'
    assert execution_roster._requested({'purpose': THREE_D['id'], 'execution': 'profile'}, custom)['kind'] == 'unknown'
    assert execution_roster._requested({'purpose': 'plan'}, custom)['slot'] == 'design'


# ---- paths a mutation run found untested ------------------------------------------------------------

def test_initialize_keeps_the_definitions(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    # A profile missing from the store makes initialize write the file.
    data = json.loads(service.store_path.read_text())
    del data['profiles']['p2']
    service.store_path.write_text(json.dumps(data), encoding='utf-8')
    service.initialize(['default', 'p1', 'p2'])
    stored = json.loads(service.store_path.read_text())
    assert stored['schema'] == STORE_SCHEMA and stored['custom_slots'] == [THREE_D]


def test_a_partial_save_with_page_expectations_writes_a_custom_slot(tmp_path, monkeypatch):
    from test_page_expectations import mapping
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    status = service.status()
    declaration = {'follow': 'custom', 'custom': route('operator', 'blender-coder', 'high')}
    expected = []
    for row in status['profiles']:
        frozen = mapping(row)['routing']
        expected.append({'profile': row['name'], 'routing': {'enabled': frozen['enabled'], 'skill_enabled': frozen['skill_enabled'],
                                                             'slots': {THREE_D['id']: (frozen['slots'] or {}).get(THREE_D['id'])}}})
    partial = {'partial_save_schema': 1, 'expected_revision': status['revision'], 'profile': 'p1', 'save_scope': 'routing',
               'models': copy.deepcopy(find_profile(status, 'p1')['models']), 'model_targets': [],
               'routing': {'enabled': True, 'slots': {THREE_D['id']: declaration}}, 'routing_targets': ['p1', 'p2'],
               'routing_profiles': ['default', 'p1', 'p2'], 'expected': expected}
    assert service.apply(service.preview(partial)['plan_id'])['status'] == 'applied'
    stored = json.loads(service.store_path.read_text())['profiles']
    assert stored['p1']['routing']['slots'] == {THREE_D['id']: declaration} == stored['p2']['routing']['slots']


def test_a_store_rewritten_at_the_same_revision_stops_a_definition_apply(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    plan = service.custom_slots_preview({'expected_revision': service.status()['revision'], 'custom_slots': [THREE_D]})['plan_id']
    data = json.loads(service.store_path.read_text())
    service.store_path.write_text(json.dumps(data, indent=3), encoding='utf-8')  # same revision, other bytes
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan)
    assert service.store_path.read_bytes() == before


def test_a_definition_save_leaves_untouched_profile_entries_byte_for_byte(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    data = json.loads(service.store_path.read_text())
    # A key the loader adds in memory but this save never changes: the entry is kept as stored.
    data['profiles']['p2']['models']['title'] = data['profiles']['p2']['models']['main']
    service.store_path.write_text(json.dumps(data), encoding='utf-8')
    raw_p2 = copy.deepcopy(data['profiles']['p2'])
    define(service, [{**THREE_D, 'label': '3D 작업'}])
    assert json.loads(service.store_path.read_text())['profiles']['p2'] == raw_p2


def test_resubmitting_the_same_definitions_is_not_blocked_by_an_older_package(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    package = service._profile_home('p2') / 'plugins' / 'model-router'
    (package / 'model_router').mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')
    (package / 'model_router' / 'slots.py').write_text('# old', encoding='utf-8')
    preview, receipt = define(service, [THREE_D])
    assert preview['changes'] == [] and receipt['status'] == 'no_change'
    with pytest.raises(ValueError, match='every installed profile'):
        service.custom_slots_preview({'expected_revision': service.status()['revision'], 'custom_slots': [THREE_D, WRITING]})


def test_an_inconsistent_plan_or_readback_writes_nothing_or_reports(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    plan_id = service.custom_slots_preview({'expected_revision': service.status()['revision'], 'custom_slots': [THREE_D, WRITING]})['plan_id']
    plan_path = service.store_path.parent / 'plans' / (plan_id + '.json')
    plan = json.loads(plan_path.read_text())
    plan['after']['p1']['routing']['slots'] = {'custom:undefined': {'follow': 'main', 'custom': None}}
    plan_path.write_text(json.dumps(plan), encoding='utf-8')
    service._plans.pop(plan_id, None)
    before = service.store_path.read_bytes()
    with pytest.raises(ServiceError, match='inconsistent'):
        service.apply(plan_id)
    assert service.store_path.read_bytes() == before
    plan_id = service.custom_slots_preview({'expected_revision': service.status()['revision'], 'custom_slots': [WRITING]})['plan_id']
    real = service._load_store
    def stale_readback():
        value = real()
        return {**value, 'custom_slots': [THREE_D]} if value and value.get('custom_slots') == [WRITING] else value
    monkeypatch.setattr(service, '_load_store', stale_readback)
    with pytest.raises(ServiceError, match='readback'):
        service.apply(plan_id)
    monkeypatch.setattr(service, '_load_store', real)
    plan_id = service.custom_slots_preview({'expected_revision': service.status()['revision'], 'custom_slots': [THREE_D]})['plan_id']
    def wrong_revision():
        value = real()
        return {**value, 'revision': value['revision'] + 7} if value and value.get('custom_slots') == [THREE_D] else value
    monkeypatch.setattr(service, '_load_store', wrong_revision)
    with pytest.raises(ServiceError, match='readback'):
        service.apply(plan_id)


def test_a_no_change_plan_is_refused_after_the_store_changed_at_the_same_revision(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    plan = service.custom_slots_preview({'expected_revision': service.status()['revision'], 'custom_slots': [THREE_D]})
    assert plan['changes'] == []
    data = json.loads(service.store_path.read_text(encoding='utf-8'))
    data['custom_slots'] = [WRITING]  # other definitions, same revision
    service.store_path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])


def test_the_roster_reads_custom_labels_from_the_store_on_a_delegate_call(tmp_path, monkeypatch):
    import hermes_constants
    from test_execution_roster import Context
    from model_router import service as service_module
    from model_router.execution_roster import register_execution_roster
    service, cli, body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    monkeypatch.setattr(service_module, 'Service', lambda *a, **k: service)
    home = tmp_path / 'profiles' / 'observer'
    home.mkdir(parents=True)
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home)
    roster = register_execution_roster(Context(), home)
    roster.pre(tool_name='delegate_task', args={'tasks': [{'goal': 'scene', 'purpose': THREE_D['id']}, {'goal': 'x', 'purpose': 'custom:gone'}]},
               session_id='s', conversation_id='r', tool_call_id='c')
    requested = [row['requested'] for row in roster.rows.values()]
    assert requested[0]['slot_label'] == THREE_D['label'] and requested[0]['slot'] == THREE_D['id'] and 'role' not in requested[0]
    assert requested[1]['kind'] == 'unknown'


# ---- runtime limits of custom slots --------------------------------------------------------------

def _limits(service, name, values):
    from model_router.timeouts import read_timeouts, timeout_digest, write_timeouts
    home = service._profile_home(name)
    state = read_timeouts(home)
    write_timeouts(home, {"delegate_total_seconds": 30, "slot_seconds": values},
                   expected_digest=timeout_digest(home), expected_revision=state["revision"])


def _own(service, name):
    from model_router.timeouts import read_timeouts
    return read_timeouts(service._profile_home(name))["slot_seconds"]


def test_removing_a_custom_slot_removes_its_limit_and_a_new_definition_starts_on_the_default(tmp_path, monkeypatch):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D, WRITING])
    _limits(service, "p1", {"design": 900, THREE_D["id"]: 600, WRITING["id"]: 300})
    _limits(service, "p2", {THREE_D["id"]: 1200})
    preview, receipt = define(service, [WRITING])
    assert receipt["status"] == "applied"
    rows = {(c["profile"], c["field"]): c for c in preview["changes"]}
    assert rows[("p1", "timeouts.slot_seconds")]["before"] == {THREE_D["id"]: 600}
    assert rows[("p2", "timeouts.slot_seconds")]["before"] == {THREE_D["id"]: 1200}
    # Only the removed slot's limit goes; every other limit and the ordinary limit stay.
    assert _own(service, "p1") == {"design": 900, WRITING["id"]: 300} and _own(service, "p2") == {}
    from model_router.timeouts import read_timeouts
    assert read_timeouts(service._profile_home("p1"))["delegate_total_seconds"] == 30
    define(service, [WRITING, THREE_D])
    assert service.routing_config("p2")["slot_timeout_seconds"][THREE_D["id"]] == 7200


def test_a_leftover_limit_is_dropped_before_an_id_is_defined_again(tmp_path, monkeypatch):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    _limits(service, "p1", {THREE_D["id"]: 600, "code-simple": 60})  # left over from an earlier failure
    preview, receipt = define(service, [THREE_D])
    assert receipt["status"] == "applied"
    assert {(c["profile"], c["field"]) for c in preview["changes"]} >= {("p1", "timeouts.slot_seconds")}
    assert _own(service, "p1") == {"code-simple": 60}
    assert service.routing_config("p1")["slot_timeout_seconds"][THREE_D["id"]] == 7200


def test_a_failed_limit_removal_after_the_definition_save_is_partial(tmp_path, monkeypatch):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D, WRITING])
    _limits(service, "p1", {THREE_D["id"]: 600})
    preview = service.custom_slots_preview({"expected_revision": service.status()["revision"], "custom_slots": [WRITING]})
    from model_router import timeouts
    original = timeouts.write_timeouts
    monkeypatch.setattr(timeouts, "write_timeouts", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("write failed")))
    receipt = service.apply(preview["plan_id"])
    assert receipt["status"] == "partial" and receipt["remaining"] == [{"profile": "p1", "key": "timeouts.slot_seconds"}]
    assert json.loads(service.store_path.read_text())["custom_slots"] == [WRITING]
    assert _own(service, "p1") == {THREE_D["id"]: 600}
    monkeypatch.setattr(timeouts, "write_timeouts", original)
    define(service, [WRITING, THREE_D])
    assert _own(service, "p1") == {}


def test_a_changed_limit_before_a_definition_save_writes_nothing(tmp_path, monkeypatch):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    _limits(service, "p1", {THREE_D["id"]: 600})
    preview = service.custom_slots_preview({"expected_revision": service.status()["revision"], "custom_slots": [THREE_D]})
    _limits(service, "p1", {THREE_D["id"]: 900})
    with pytest.raises(RevisionConflict):
        service.apply(preview["plan_id"])
    assert json.loads(service.store_path.read_text())["custom_slots"] == []
    assert _own(service, "p1") == {THREE_D["id"]: 900}


def test_an_unreadable_timeouts_file_is_left_alone(tmp_path, monkeypatch):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [THREE_D])
    path = service._profile_home("p1") / "plugin-data" / "model-router" / "timeouts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": 2}', encoding="utf-8")
    preview, receipt = define(service, [])
    assert receipt["status"] == "applied" and not any(c["profile"] == "p1" and c["field"].startswith("timeouts") for c in preview["changes"])
    assert path.read_text(encoding="utf-8") == '{"schema": 2}'


@pytest.mark.parametrize("adding", [True, False])
@pytest.mark.parametrize("with_existing_file", [True, False])
def test_a_first_limit_saved_after_preview_refuses_add_or_remove(tmp_path, monkeypatch, adding, with_existing_file):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [WRITING] if adding else [WRITING, THREE_D])
    if with_existing_file:
        _limits(service, "p1", {"design": 600})
    body = {"expected_revision": service.status()["revision"], "custom_slots": [WRITING, THREE_D] if adding else [WRITING]}
    plan = service.custom_slots_preview(body)
    store_before = service.store_path.read_bytes()
    _limits(service, "p1", {THREE_D["id"]: 0, "design": 600})
    # Apply from a fresh instance, so the persisted plan's absence fence is exercised.
    with pytest.raises(RevisionConflict, match="timeout settings of p1 changed"):
        Service(root=service.root, writer=service.writer).apply(plan["plan_id"])
    assert service.store_path.read_bytes() == store_before
    assert _own(service, "p1") == {THREE_D["id"]: 0, "design": 600}


def test_cleanup_only_receipt_names_actual_timeout_writes_and_keeps_shared_revision(tmp_path, monkeypatch):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [WRITING])
    _limits(service, "p1", {THREE_D["id"]: 0, WRITING["id"]: 300})
    before = service.store_path.read_bytes()
    revision = service.status()["revision"]
    _, receipt = define(service, [WRITING])
    assert receipt["status"] == "applied" and receipt["revision"] == revision
    assert receipt["applied"] == [{"profile": "p1", "key": "timeouts.slot_seconds"}]
    assert service.store_path.read_bytes() == before
    assert _own(service, "p1") == {WRITING["id"]: 300}


@pytest.mark.parametrize("adding", [True, False])
def test_recovered_timeout_file_requires_a_new_preview(tmp_path, monkeypatch, adding):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [WRITING] if adding else [WRITING, THREE_D])
    path = service._profile_home("p1") / "plugin-data/model-router/timeouts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema":2}', encoding="utf-8")
    plan = service.custom_slots_preview({"expected_revision": service.status()["revision"],
        "custom_slots": [WRITING, THREE_D] if adding else [WRITING]})
    before = service.store_path.read_bytes()
    path.write_text(json.dumps({"schema": 3, "revision": 1, "delegate_total_seconds": 0,
        "slot_seconds": {THREE_D["id"]: 0}}), encoding="utf-8")
    with pytest.raises(RevisionConflict, match="became readable"):
        service.apply(plan["plan_id"])
    assert service.store_path.read_bytes() == before and _own(service, "p1")[THREE_D["id"]] == 0


@pytest.mark.parametrize("phase", ["after_collection", "before_replace"])
def test_new_profile_during_custom_slot_save_is_not_missed(tmp_path, monkeypatch, phase):
    service, _cli, _body = setup(tmp_path, monkeypatch)
    define(service, [WRITING])
    before = service.store_path.read_bytes()

    def add_profile():
        home = service.root / "profiles/new-profile"
        (home / "plugin-data/model-router").mkdir(parents=True)
        (home / "config.yaml").write_text("{}", encoding="utf-8")
        (home / "plugin-data/model-router/timeouts.json").write_text(json.dumps({"schema": 3,
            "revision": 1, "delegate_total_seconds": 0, "slot_seconds": {THREE_D["id"]: 0}}), encoding="utf-8")

    if phase == "after_collection":
        collect = service._custom_limit_cleanup
        def collect_then_add(*args):
            result = collect(*args)
            add_profile()
            return result
        monkeypatch.setattr(service, "_custom_limit_cleanup", collect_then_add)
    plan = service.custom_slots_preview({"expected_revision": service.status()["revision"], "custom_slots": [WRITING, THREE_D]})
    if phase == "before_replace":
        import model_router.service as mod
        atomic = mod._atomic_write
        def interleave(path, payload, before_replace=None):
            if path == service.store_path:
                add_profile()
            return atomic(path, payload, before_replace=before_replace)
        monkeypatch.setattr(mod, "_atomic_write", interleave)
    with pytest.raises(RevisionConflict, match="profile inventory changed"):
        service.apply(plan["plan_id"])
    assert service.store_path.read_bytes() == before
    assert _own(service, "new-profile")[THREE_D["id"]] == 0
