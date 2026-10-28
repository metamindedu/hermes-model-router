from pathlib import Path
import os
import pytest

from model_router import role_metadata as rm
from model_router import native_delegation as nd


class FixtureService:
    def __init__(self, root): self.root = root
    def _profile_home(self, name): return self.root if name == 'default' else self.root / 'profiles' / name


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    home = tmp_path / 'profiles' / 'worker'
    home.mkdir(parents=True)
    import importlib
    monkeypatch.setattr(nd, '_inventory', lambda service, name: name == 'worker')
    monkeypatch.setattr(importlib.import_module('model_router.native_delegation'), '_inventory', lambda service, name: name == 'worker')
    return FixtureService(tmp_path), home


def test_metadata_native_projection_and_missing(fixture):
    service, home = fixture
    assert rm.resolve(service, 'worker')['state'] == 'missing'
    (home / 'profile.yaml').write_text('description: "  analysis\\nrole  "\ndescription_auto: true\n', encoding='utf-8')
    dto = rm.resolve(service, 'worker')
    assert dto['state'] == 'available' and dto['description_auto'] is True
    assert dto['default_description'] == 'analysis role'
    assert len(dto['digest']) == 64
    (home / 'profile.yaml').write_text('description: [not, text]\n', encoding='utf-8')
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'


def test_metadata_alias_oversize_and_hardlink_fail_closed(fixture):
    service, home = fixture
    path = home / 'profile.yaml'
    path.write_text('a: &x hello\ndescription: *x\n', encoding='utf-8')
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'
    path.write_text('x' * 32769, encoding='utf-8')
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'
    path.write_text('description: private\n', encoding='utf-8')
    try:
        os.link(path, home / 'linked-copy')
    except OSError:
        pytest.skip('hard links unavailable')
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'


def test_hints_are_allowlisted_and_overrides_remain(fixture, monkeypatch):
    service, home = fixture
    (home / 'profile.yaml').write_text('description: native\n', encoding='utf-8')
    assert rm.resolve(service, 'worker')['default_description'] == 'native'
    monkeypatch.setattr(nd, '_origin', lambda *_: 'default')
    provider = nd.ModelRouterProfilesProvider(service.root, lambda: service)
    def schema(desc):
        return provider.task_parameters({'backends': {'model-router-profiles': {'schema': 1, 'profiles': [{'name': 'worker', 'description': desc}], 'default': None}}})['profile']
    assert 'native' in schema('')['description']
    assert 'custom' in schema('custom')['description'] and 'native' not in schema('custom')['description']
    assert 'native' not in schema('   ')['description']
    assert schema('')['enum'] == ['worker']
    assert 'untrusted' in schema('')['description']
    assert 'fixture-credential' not in schema('API_KEY = fixture-credential')['description']


def test_plain_native_metadata_semantics_match(fixture):
    from hermes_cli.profiles import read_profile_meta
    service, home = fixture
    (home / 'profile.yaml').write_text('description: "  Evidence analyst  "\ndescription_auto: true\n', encoding='utf-8')
    native = read_profile_meta(home)
    dto = rm.resolve(service, 'worker')
    assert dto['default_description'] == native['description']
    assert dto['description_auto'] == native['description_auto']


def test_invalid_identifier_does_not_read_outside_fixture(fixture):
    service, _ = fixture
    for name in ('../worker', 'keep', 'worker/other', 'worker:stream', 'C:/worker'):
        dto = rm.resolve(service, name)
        assert dto['state'] == 'unavailable' and not dto['default_description']


def test_metadata_native_safe_parser_when_pyyaml_absent(fixture, monkeypatch):
    import builtins
    service, home = fixture
    path = home / 'profile.yaml'
    path.write_text('description: analyst\ndescription_auto: true\n', encoding='utf-8')
    original_import = builtins.__import__
    def without_pyyaml(name, *args, **kwargs):
        if name == 'yaml':
            raise ModuleNotFoundError("No module named 'yaml'", name='yaml')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_pyyaml)
    assert rm.resolve(service, 'worker')['default_description'] == 'analyst'
    path.write_text('x: &id hi\ndescription: *id\n', encoding='utf-8')
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'
