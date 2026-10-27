"""Explicit setup owns only the backend leaf; no production writes or provider calls."""
import copy
import json
import pytest
from model_router import native_service as native, native_settings as ns, effective_config
from model_router.service import RevisionConflict, ServiceError
from model_router.yaml_compat import yaml
from test_native_service import fixture


@pytest.fixture
def setup_fixture(fixture, monkeypatch):
    service, calls, writer = fixture
    monkeypatch.setattr(native, '_initial_package_code', lambda *args: 'fixture-complete-package')
    for name in ('default', 'p1', 'p2'):
        folder = service._profile_home(name) / 'plugins'
        folder.mkdir(exist_ok=True)
        (folder / '.install-metadata.json').write_text(json.dumps({'model-router': {
            'revision': 'b' * 40, 'source': 'https://github.com/metamindedu/hermes-model-router', 'pinned': True}}), encoding='utf-8')
    ready = {'schema': 1, 'state': 'ready', 'files': 'complete', 'python': 'enabled',
             'base_supported': True, 'split_supported': True, 'explicit_opt_out': False,
             'managed_selection': False, 'version': '0.6.0', 'identity': 'a' * 64}
    monkeypatch.setattr('model_router.installation.profile_readiness', lambda *args: copy.deepcopy(ready))
    monkeypatch.setattr(service, 'native_route_config', lambda profile: {'enabled': True,
        'heavy': {'provider': 'fixture', 'model': 'heavy', 'reasoning': 'high'},
        'light': {'provider': 'fixture', 'model': 'light', 'reasoning': 'high'}})
    return service, calls, writer, ready


def config(service, name='default'):
    return yaml.safe_load((service._profile_home(name) / 'config.yaml').read_text(encoding='utf-8'))


def write_config(service, value, name='default'):
    (service._profile_home(name) / 'config.yaml').write_text(yaml.safe_dump(value), encoding='utf-8')


def request(service, names=('default',)):
    from model_router.installation import _root_identity
    return {'expected_revision': 0, 'expected_root_identity': _root_identity(service.root),
            'updates': [{'profile': name, 'expected_digest': native.initial_setup_status(service, name)['digest']} for name in names]}


def test_initial_status_preview_are_readonly_and_plan_contains_no_raw_values(setup_fixture):
    service, calls, _, _ = setup_fixture
    value = config(service); value['unrelated']['secret'] = 'sentinel-private-never-in-plan'; write_config(service, value)
    before = (service.root / 'config.yaml').read_bytes()
    dto = native.initial_setup_status(service, 'default')
    assert dto['action'] == 'select_backend' and dto['eligible'] and dto['backend_unset']
    plan = service.initial_setup_preview(request(service))
    assert calls == [] and (service.root / 'config.yaml').read_bytes() == before
    assert not service.store_path.exists()
    saved = (service.store_path.parent / 'plans' / (plan['plan_id'] + '.json')).read_text()
    assert 'sentinel-private-never-in-plan' not in saved
    assert plan['changes'] == [{'profile': 'default', 'field': ns.KEY_BACKEND, 'before': None, 'after': 'model-router'}]


def test_initial_apply_owns_only_backend_and_preserves_opaque_inactive_blocks(setup_fixture):
    service, calls, _, _ = setup_fixture
    value = config(service)
    value['delegation']['backends']['model-router-profiles'] = {'unrecognized': {'preserve': 'opaque'}}
    write_config(service, value)
    before = copy.deepcopy(value)
    result = service.apply(service.initial_setup_preview(request(service))['plan_id'])
    assert result['status'] == 'applied'
    assert calls == [('default', ns.KEY_BACKEND, 'model-router')]
    before['delegation']['backend'] = 'model-router'
    assert config(service) == before
    assert ns.KEY_POLICY.split('.')[-1] not in config(service)['delegation']['backends']
    assert not service.store_path.exists()


@pytest.mark.parametrize('backend', ['default', 'model_map', 'model-router-profiles', None, '', False])
def test_initial_preserves_any_present_backend_including_null(setup_fixture, backend):
    service, calls, _, _ = setup_fixture
    value = config(service); value['delegation']['backend'] = backend; write_config(service, value)
    dto = native.initial_setup_status(service, 'default')
    assert dto['eligible'] is False and dto['backend_unset'] is False
    with pytest.raises(ValueError): service.initial_setup_preview(request(service))
    assert calls == []


@pytest.mark.parametrize('setting', ['plugin', 'bare_skill', 'namespaced_skill', 'canonical'])
def test_initial_preserves_explicit_optouts(setup_fixture, monkeypatch, setting):
    service, calls, _, ready = setup_fixture
    value = config(service)
    if setting == 'plugin': value['plugins']['disabled'] = ['model-router']
    elif setting == 'bare_skill': value['skills']['disabled'] = ['adaptive-coding-orchestration']
    elif setting == 'namespaced_skill': value['skills']['disabled'] = ['model-router:adaptive-coding-orchestration']
    else: ready['explicit_opt_out'] = True
    write_config(service, value)
    assert native.initial_setup_status(service, 'default')['eligible'] is False
    assert calls == []


def test_initial_never_activates_dormant_paid_continuation(setup_fixture):
    service, calls, _, _ = setup_fixture
    value = config(service)
    policy = ns.default_policy(); policy['heavy'] = {'mode': 'custom', 'chain': [{'provider': 'fixture', 'model': 'paid'}]}
    value['delegation']['backends']['model-router'] = ns.build_policy_block('default', policy, True)
    write_config(service, value)
    assert native.initial_setup_status(service, 'default')['eligible'] is False
    with pytest.raises(ValueError): service.initial_setup_preview(request(service))
    assert calls == []


def test_initial_already_selected_is_no_write(setup_fixture):
    service, calls, _, _ = setup_fixture
    value = config(service); value['delegation']['backend'] = 'model-router'; write_config(service, value)
    assert native.initial_setup_status(service, 'default')['action'] == 'complete'
    assert calls == []


def test_initial_detects_unrelated_config_race_and_consumes_token(setup_fixture):
    service, calls, _, _ = setup_fixture
    plan = service.initial_setup_preview(request(service, ('default', 'p1')))
    value = config(service, 'p1'); value['unrelated']['changed'] = True; write_config(service, value, 'p1')
    with pytest.raises(RevisionConflict): service.apply(plan['plan_id'])
    assert calls == []
    with pytest.raises(ServiceError): service.apply(plan['plan_id'])


def test_initial_intent_allows_only_package_selection_delta(setup_fixture):
    service, _, _, _ = setup_fixture
    before = native.initial_setup_status(service, 'default')['intent_digest']
    value = config(service); value['plugins']['enabled'] = ['other-plugin']; write_config(service, value)
    changed = native.initial_setup_status(service, 'default')['intent_digest']
    assert before != changed
    value['plugins']['enabled'].append('model-router'); write_config(service, value)
    assert native.initial_setup_status(service, 'default')['intent_digest'] == changed


def test_initial_raw_presence_is_distinct_from_null(setup_fixture):
    service, _, _, _ = setup_fixture
    snapshot = effective_config.read_key_scoped(service.root, ns.KEYS)
    assert snapshot.raw(ns.KEY_BACKEND) is None and not snapshot.raw_present(ns.KEY_BACKEND)
    value = config(service); value['delegation']['backend'] = None; write_config(service, value)
    after = effective_config.read_key_scoped(service.root, ns.KEYS)
    assert after.raw(ns.KEY_BACKEND) is None and after.raw_present(ns.KEY_BACKEND)
    assert after.cas_digest != snapshot.cas_digest


def test_initial_inexact_writer_readback_is_partial_not_retry(setup_fixture, monkeypatch):
    service, calls, writer, _ = setup_fixture
    def bad(profile, key, value):
        writer(profile, key, value)
        cfg = config(service, profile); cfg['unrelated']['changed'] = True; write_config(service, cfg, profile)
    monkeypatch.setattr(service, 'writer', bad)
    result = service.apply(service.initial_setup_preview(request(service))['plan_id'])
    assert result['status'] == 'partial' and len(calls) == 1


def test_initial_missing_package_with_python_off_is_preserved(setup_fixture):
    service, _, _, ready = setup_fixture
    ready.update(state='missing', files='missing', python='not_enabled')
    value = config(service); value['plugins']['disabled'] = ['model-router']; write_config(service, value)
    assert native.initial_setup_status(service, 'default')['action'] == 'preserved'


@pytest.mark.parametrize('change', ['backend_selected_elsewhere', 'code_loss', 'foreign_root', 'source_metadata'])
def test_initial_stale_authority_never_becomes_noop_success(setup_fixture, monkeypatch, change):
    service, calls, _, _ = setup_fixture
    plan = service.initial_setup_preview(request(service))
    if change == 'backend_selected_elsewhere':
        value = config(service); value['delegation']['backend'] = 'model-router'; write_config(service, value)
    elif change == 'code_loss': monkeypatch.setattr(service, '_native_delegation_code_signature', lambda name: None)
    elif change == 'foreign_root': monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: service.root / 'foreign')
    else:
        path = service.root / 'plugins/.install-metadata.json'
        value = json.loads(path.read_text()); value['model-router']['revision'] = 'c' * 40; path.write_text(json.dumps(value))
    with pytest.raises((RevisionConflict, ValueError)): service.apply(plan['plan_id'])
    assert calls == []


def test_initial_managed_state_and_invalid_routes_are_manual(setup_fixture, monkeypatch):
    service, calls, _, ready = setup_fixture
    ready['managed_selection'] = True
    assert native.initial_setup_status(service, 'default')['eligible'] is False
    ready['managed_selection'] = False
    monkeypatch.setattr(service, 'native_route_config', lambda name: {'enabled': True, 'heavy': {}, 'light': {}})
    assert native.initial_setup_status(service, 'default')['eligible'] is False
    assert calls == []


@pytest.mark.parametrize('container', ['absent', 'empty', 'null'])
def test_initial_delegation_container_presence_is_preserved(setup_fixture, container):
    service, calls, _, _ = setup_fixture
    value = config(service)
    if container == 'absent': value.pop('delegation')
    else: value['delegation'] = {} if container == 'empty' else None
    write_config(service, value)
    if container == 'null':
        assert native.initial_setup_status(service, 'default')['eligible'] is False
        assert calls == []; return
    before = copy.deepcopy(value)
    receipt = service.apply(service.initial_setup_preview(request(service))['plan_id'])
    assert receipt['status'] == 'applied'
    before.setdefault('delegation', {})['backend'] = 'model-router'
    assert config(service) == before


def test_initial_real_native_writer_preserves_every_other_value(setup_fixture, monkeypatch):
    import os
    from pathlib import Path
    service, _, _, _ = setup_fixture
    launcher = Path(os.environ.get('HERMES_TEST_CLI', ''))
    if not launcher.is_file(): pytest.skip('explicit genuine Hermes CLI unavailable')
    monkeypatch.setattr(service, 'writer', None)
    monkeypatch.setattr(service, '_cli_path', lambda: str(launcher))
    before = config(service)
    receipt = service.apply(service.initial_setup_preview(request(service))['plan_id'])
    assert receipt['status'] == 'applied', receipt
    before['delegation']['backend'] = 'model-router'
    assert config(service) == before
