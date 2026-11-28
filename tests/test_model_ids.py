"""Model IDs that end in a bracketed variant tag, as Hermes provider catalogs declare them."""
import re

import pytest

from model_router import execution_roster, native_delegation, native_settings, service as service_module
from model_router.service import Service
from test_service import setup_home, find_profile

ACCEPTED = ['claude-opus-5-5[1m]', 'claude-opus-5[1m]', 'vendor/model:tag[beta.2]', 'm[x_y-z]']
REFUSED = ['[1m]', 'model[]', 'model[1m]x', 'model[1m][2m]', 'model[1 m]', 'model]', 'model[', 'model[1m', 'model[/x]',
           'model[' + 'a' * 33 + ']', 'model[1m]\n']
PATTERNS = {
    'service.MODEL_RE': service_module.MODEL_RE,
    'native_delegation._MODEL': native_delegation._MODEL,
    'native_settings._MODEL': native_settings._MODEL,
    'execution_roster._MODEL': execution_roster._MODEL,
}


@pytest.mark.parametrize('name', sorted(PATTERNS))
def test_every_model_pattern_takes_one_trailing_variant_tag_and_nothing_looser(name):
    pattern = PATTERNS[name]
    for model in ACCEPTED:
        assert pattern.fullmatch(model), (name, model)
    for model in REFUSED:
        assert pattern.fullmatch(model) is None, (name, model)


def test_a_profile_whose_main_model_has_a_variant_tag_routes_purposes(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    cli.values['default']['model.default'] = 'claude-opus-5-5[1m]'
    service = Service(root=root, writer=cli.writer)
    service.initialize(['default', 'p1', 'p2'])
    row = find_profile(service.status(), 'default')
    assert row['models']['main']['model'] == 'claude-opus-5-5[1m]'
    config = service.native_route_config('default')
    # A never-set slot runs on the main model.
    assert config['slots']['design']['model'] == 'claude-opus-5-5[1m]'
    assert native_delegation.safe_route(config['slots']['design'], 'design')['model'] == 'claude-opus-5-5[1m]'
    # A spare model with a variant tag is accepted by the per-slot policy as well.
    policy = native_settings.validate_policy({slot: {'mode': 'custom', 'chain': [{'provider': 'claude-subscription', 'model': 'claude-opus-5[1m]'}]}
                                              for slot in native_settings.BUILTIN_SLOTS})
    assert all(entry['chain'][0]['model'] == 'claude-opus-5[1m]' for entry in policy.values())
