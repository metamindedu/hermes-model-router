"""Cold source-host binding: no optional import or provider execution."""
import builtins
import sys
import pytest
from model_router import routing
from test_worker_runtime_authority import adopted
from test_worker_runtime_authority import test_bad_authority_never_spawns_or_creates_job as _bad_authority


def test_cold_base_host_uses_unique_native_membership_without_importing_helper(adopted, monkeypatch):
    f = adopted
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == 'pm.environments_adopt':
            raise AssertionError('optional helper must not be imported')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    work = f.tmp / 'cold-work'
    work.mkdir()
    core, paths, executable = routing._worker_runtime(work)
    assert core == f.workspace
    assert paths == [str(f.workspace), str(f.packages)]
    assert executable == str(f.executable)
    assert 'pm.environments_adopt' not in sys.modules
    assert f.launches == []


@pytest.mark.parametrize('corrupt', [
    'bootstrap_spec', 'pm_spec', 'pm_function', 'foreign_install',
    'ambiguous_generation', 'empty_command', 'multi_command', 'relative_executable',
    'missing_executable', 'wrong_executable', 'missing_cfg', 'missing_marker', 'missing_lock',
    'redirect_flag', 'cwd_workspace', 'directory_executable', 'unrelated_venv', 'missing_workspace_bootstrap',
])
def test_cold_path_keeps_existing_authority_rejections(adopted, monkeypatch, corrupt):
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    _bad_authority(adopted, monkeypatch, corrupt)


@pytest.mark.parametrize('state', ['no-membership', 'adopt-none', 'reverse-partial', 'foreign-adopt'])
def test_cold_path_does_not_repair_missing_or_foreign_authority(adopted, monkeypatch, state):
    f = adopted
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    if state == 'no-membership':
        monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != str(f.packages)])
    elif state == 'adopt-none':
        monkeypatch.setitem(sys.modules, 'pm.environments_adopt', None)
    elif state == 'reverse-partial':
        monkeypatch.delitem(sys.modules, 'pm.environments', raising=False)
        monkeypatch.setitem(sys.modules, 'pm.environments_adopt', f.adoption)
    else:
        f.adoption.__spec__.origin = str(f.tmp / 'foreign.py')
        monkeypatch.setitem(sys.modules, 'pm.environments_adopt', f.adoption)
    work = f.tmp / 'reject-work'
    work.mkdir()
    with pytest.raises(routing.RoutingError):
        routing._worker_runtime(work)
    assert f.launches == []


def test_cold_loaded_old_is_not_replaced_by_unimported_new(adopted, monkeypatch):
    f = adopted
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    f.pm.site_packages(f.state / 'environments/new/venv').mkdir(parents=True)
    monkeypatch.setenv('HERMES_PYTHON', str(f.base_python))
    monkeypatch.setenv('HERMES_SOURCE_ROOT', str(f.tmp / 'foreign'))
    work = f.tmp / 'cold-old-work'
    work.mkdir()
    assert routing._worker_runtime(work)[2] == str(f.executable)
