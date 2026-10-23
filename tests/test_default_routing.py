"""Fresh package defaults are on; stored and explicit skill opt-outs survive."""
import copy

import pytest

from model_router.service import Service, SKILL_NAME
from test_integration import make_home, writer


def install_marker(root):
    package = root / 'plugins/model-router'
    package.mkdir(parents=True)
    (package / 'plugin.yaml').write_text('name: model-router\n', encoding='utf-8')


def test_fresh_installed_profile_defaults_on_without_writing_settings(tmp_path):
    root = make_home(tmp_path)
    install_marker(root)
    config = root / 'config.yaml'
    before = config.read_bytes()
    service = Service(root)
    row = service.status()['profiles'][0]
    assert row['routing']['enabled'] is True
    assert service.routing_config('default')['enabled'] is True
    assert row['drift'] == []
    assert row['routing']['fallback']['enabled'] is False
    assert config.read_bytes() == before
    assert not (root / 'plugin-data').exists()


def test_uninstalled_profiles_do_not_gain_routing_from_another_profile(tmp_path):
    root = make_home(tmp_path)
    install_marker(root)
    other = root / 'profiles/plain'
    other.mkdir(parents=True)
    (other / 'config.yaml').write_bytes((root / 'config.yaml').read_bytes())
    service = Service(root)
    rows = {r['name']: r for r in service.status()['profiles']}
    assert rows['default']['routing']['enabled'] is True
    assert rows['plain']['routing']['enabled'] is False
    assert service.routing_config('plain')['enabled'] is False
    assert not (other / 'plugin-data').exists()


def test_existing_canonical_off_survives_the_new_default(tmp_path):
    root = make_home(tmp_path)
    install_marker(root)
    service = Service(root, writer(root))
    service.initialize([])  # Explicit previous choice, not an absent default.
    before = (root / 'config.yaml').read_bytes()
    stored = service.store_path.read_bytes()
    reopened = Service(root)
    assert reopened.status()['profiles'][0]['routing']['enabled'] is False
    assert reopened.routing_config('default')['enabled'] is False
    assert service.store_path.read_bytes() == stored
    assert (root / 'config.yaml').read_bytes() == before


@pytest.mark.parametrize('skill_id', [SKILL_NAME, 'model-router:' + SKILL_NAME])
def test_explicit_skill_disable_without_store_survives_the_new_default(tmp_path, skill_id):
    root = make_home(tmp_path)
    install_marker(root)
    write = writer(root)
    write('default', 'skills.disabled', [skill_id, 'unrelated'])
    service = Service(root)
    assert service.status()['profiles'][0]['routing']['enabled'] is False
    assert service.routing_config('default')['enabled'] is False
    assert not service.store_path.exists()


def test_fresh_install_can_save_identical_models_then_explicitly_opt_out(tmp_path):
    root = make_home(tmp_path)
    install_marker(root)
    write = writer(root)
    write('default', 'delegation.model', 'heavy-test')
    service = Service(root, write)
    status = service.status()
    row = status['profiles'][0]
    body = {
        'expected_revision': status['revision'], 'profile': 'default',
        'models': copy.deepcopy(row['models']), 'model_targets': ['default'],
        'routing': copy.deepcopy(row['routing']), 'routing_profiles': ['default'],
        'routing_targets': [],
    }
    assert row['routing']['enabled'] is True
    body['models']['title']['model'] = 'changed-title-only'
    receipt = service.apply(service.preview(body)['plan_id'])
    assert receipt['status'] == 'applied'
    config = service.routing_config('default')
    assert config['enabled'] is True
    assert (config['heavy']['provider'], config['heavy']['model']) == (config['light']['provider'], config['light']['model'])
    fresh = service.status()
    body.update(expected_revision=fresh['revision'], models=fresh['profiles'][0]['models'])
    body['routing']['enabled'] = False
    body['routing_profiles'] = []
    receipt = service.apply(service.preview(body)['plan_id'])
    assert receipt['status'] == 'applied'
    assert Service(root).routing_config('default')['enabled'] is False
    assert 'unrelated' not in Service(root)._read_disabled('default')
