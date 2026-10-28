"""Installed capability is distinct from general native support; no foreign imports."""
from pathlib import Path
import subprocess
import pytest
from model_router import native_service, native_settings as ns
from model_router.service import RevisionConflict
from test_native_service import fixture, body

ROOT = Path(__file__).resolve().parents[1]
BASE = '0459f842e0c682a68a1e6112d58886c243850846'
FILES = ['__init__.py', 'plugin.yaml', 'model_router/native_delegation.py',
         'model_router/native_watchdog.py', 'model_router/native_settings.py',
         'model_router/native_service.py', 'model_router/service.py', 'model_router/config_writer.py']


def package(service, name='p1', legacy=False):
    root = service._profile_home(name) / 'plugins/model-router'
    for relative in FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git', 'show', BASE + ':' + relative], cwd=ROOT)
                           if legacy else (ROOT / relative).read_bytes())
    return root


def test_real_legacy_package_remains_editable_but_cannot_select_auto(fixture, monkeypatch):
    service, calls, _ = fixture
    package(service, legacy=True)
    monkeypatch.setattr(service, '_native_delegation_code_signature', lambda p: native_service._code_signature(service, p))
    dto = native_service.status(service, 'p1')
    assert dto['supported'] is True and dto['editable'] is True
    assert dto['auto_supported'] is False
    with pytest.raises(ValueError, match='automatic'):
        service.delegation_preview(body(service, profile='p1', backend='model-router-auto'))
    assert not calls
    assert service.apply(service.delegation_preview(body(service, profile='p1'))['plan_id'])['status'] == 'applied'


def test_real_current_package_advertises_and_saves_auto(fixture, monkeypatch):
    service, calls, _ = fixture
    package(service)
    monkeypatch.setattr(service, '_native_delegation_code_signature', lambda p: native_service._code_signature(service, p))
    dto = native_service.status(service, 'p1')
    assert dto['supported'] and dto['auto_supported']
    plan = service.delegation_preview(body(service, profile='p1', backend='model-router-auto'))
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    assert native_service.status(service, 'p1')['backend'] == 'model-router-auto'
    assert calls


@pytest.mark.parametrize('module', ['native_delegation', 'native_watchdog', 'native_settings', 'native_service', 'config_writer'])
def test_partial_feature_upgrade_remains_legacy_editable(fixture, module):
    service, calls, _ = fixture
    root = package(service)
    target = root / 'model_router' / (module + '.py')
    target.write_bytes(subprocess.check_output(['git', 'show', BASE + ':model_router/' + module + '.py'], cwd=ROOT))
    assert native_service.status(service, 'p1')['auto_supported'] is False
    with pytest.raises(ValueError, match='automatic'):
        service.delegation_preview(body(service, profile='p1', backend='model-router-auto'))
    assert not calls


def test_feature_loss_after_preview_refuses_before_any_write_even_with_same_general_signature(fixture):
    service, calls, _ = fixture
    root = package(service)
    plan = service.delegation_preview(body(service, profile='p1', backend='model-router-auto'))
    path = root / 'model_router/native_watchdog.py'
    path.write_text(path.read_text().replace('AUTO_ROUTING_SUPPORTED = True', 'AUTO_ROUTING_SUPPORTED = False'))
    with pytest.raises(RevisionConflict, match='automatic'):
        service.apply(plan['plan_id'])
    assert not calls


def test_feature_loss_during_write_is_partial_not_applied(fixture):
    service, calls, writer = fixture
    root = package(service)
    plan = service.delegation_preview(body(service, profile='p1', backend='model-router-auto'))
    def changing_writer(profile, key, value):
        writer(profile, key, value)
        path = root / 'model_router/config_writer.py'
        path.write_text(path.read_text().replace('AUTO_ROUTING_SUPPORTED = True', 'AUTO_ROUTING_SUPPORTED = False'))
    service.writer = changing_writer
    result = service.apply(plan['plan_id'])
    assert result['status'] == 'partial'
    assert len(result['applied']) == 1 and result['remaining']


def test_noop_revalidates_feature_at_final_boundary(fixture, monkeypatch):
    service, calls, _ = fixture
    package(service)
    request = lambda: body(service, profile='p1', backend='model-router-auto')
    assert service.apply(service.delegation_preview(request())['plan_id'])['status'] == 'applied'
    plan = service.delegation_preview(request())
    assert plan['changes'] == []
    calls.clear()
    real = native_service._auto_code_signature
    seen = []
    def disappearing(*args):
        seen.append(1)
        return real(*args) if len(seen) == 1 else None
    monkeypatch.setattr(native_service, '_auto_code_signature', disappearing)
    result = service.apply(plan['plan_id'])
    assert result['status'] == 'partial' and not calls and len(seen) == 2


@pytest.mark.parametrize('shadow', ['native_delegation.pyd', 'native_watchdog.pyc', 'native_settings.cp314-win_amd64.pyd', 'config_writer'])
def test_shadowed_modules_are_not_imported_or_declared_capable(fixture, shadow):
    service, calls, _ = fixture
    root = package(service) / 'model_router'
    target = root / shadow
    if '.' in shadow:
        target.write_bytes(b'not an executable module; must never be imported')
    else:
        target.mkdir()
        (target / '__init__.py').write_text('raise AssertionError("must never import a foreign package")')
    assert native_service.status(service, 'p1')['auto_supported'] is False
    assert not calls
