"""Deterministic PM authority checks; no model or real worker execution."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import pytest
from model_router import routing
from test_routing import _make_router, _start

_REAL_POPEN = subprocess.Popen


@pytest.fixture
def adopted(tmp_path, monkeypatch):
    router, service, home, launches = _make_router(tmp_path, monkeypatch)
    import tools.environments.local
    monkeypatch.setattr(tools.environments.local, 'served_profile_child_env', lambda **kw: {'PATH': ''})
    source, state, base = (tmp_path / n for n in ('source', 'install', 'base-python'))
    environment = state / 'environments/loaded/venv'
    workspace = environment.parent / 'workspace'
    exe_relative = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    packages_relative = 'Lib/site-packages' if os.name == 'nt' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    for root in (source, workspace):
        for member in ('hermes_bootstrap.py', 'run_agent.py', 'agent/agent_init.py',
                       'hermes_cli/runtime_provider.py', 'pyproject.toml', 'uv.lock'):
            p = root / member
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# fixture\n')
    packages = environment / packages_relative
    packages.mkdir(parents=True)
    (environment / 'pyvenv.cfg').write_text('home = fixture\n')
    executable = environment / exe_relative
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b'fixture; never executed')
    base.mkdir()
    base_python = base / 'python.exe'
    base_python.write_bytes(b'fixture; never executed')
    def native_module(name, relative, code, values=None):
        file = source / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(code)
        module = ModuleType(name)
        module.__file__ = str(file)
        module.__spec__ = importlib.util.spec_from_file_location(name, file)
        module.__dict__.update(values or {})
        exec(compile(code, str(file), 'exec'), module.__dict__)
        monkeypatch.setitem(sys.modules, name, module)
        return module
    bootstrap = native_module('hermes_bootstrap', 'hermes_bootstrap.py', '# fixture\n')
    pm = native_module('pm.environments', 'pm/environments.py', '''
def site_packages(env): return env / packages_relative
def venv_python(env): return env / exe_relative
def venv_command(core, env): return command if command is not None else [str(venv_python(env))]
def install_state_dir(core): return state
''', {'packages_relative': packages_relative, 'exe_relative': exe_relative, 'state': state, 'command': None})
    adoption = native_module('pm.environments_adopt', 'pm/environments_adopt.py',
        'def running_environment(core): return environment\n', {'environment': environment})
    monkeypatch.setattr(sys, 'prefix', str(base))
    monkeypatch.setattr(sys, 'base_prefix', str(base))
    monkeypatch.setattr(sys, 'executable', str(base_python))
    monkeypatch.syspath_prepend(str(packages))
    return SimpleNamespace(router=router, service=service, home=home, launches=launches, source=source,
        state=state, environment=environment, workspace=workspace, executable=executable,
        packages=packages, base_python=base_python, pm=pm, adoption=adoption, bootstrap=bootstrap, tmp=tmp_path)


def test_adopted_host_uses_loaded_interpreter_and_its_own_snapshot(adopted):
    f = adopted
    result = _start(f.router, f.tmp, 'independent-review')
    assert result['status'] == 'running' and len(f.launches) == 1
    command, options = f.launches[0]
    assert command[0] == command[command.index('--python') + 1] == str(f.executable)
    assert options['env']['PYTHONPATH'].split(os.pathsep) == [str(f.workspace), str(f.packages)]
    assert f.source != f.workspace


@pytest.mark.parametrize('corrupt', ['bootstrap_spec', 'pm_spec', 'pm_function', 'foreign_install',
    'ambiguous_generation', 'empty_command', 'multi_command', 'relative_executable',
    'missing_executable', 'wrong_executable', 'missing_cfg', 'missing_marker', 'missing_lock',
    'redirect_flag', 'cwd_workspace', 'directory_executable', 'unrelated_venv', 'missing_workspace_bootstrap'])
def test_bad_authority_never_spawns_or_creates_job(adopted, monkeypatch, corrupt):
    f = adopted
    if corrupt == 'bootstrap_spec': f.bootstrap.__spec__.origin = str(f.source / 'other.py')
    elif corrupt == 'pm_spec': f.pm.__spec__.origin = str(f.tmp / 'foreign.py')
    elif corrupt == 'pm_function': f.pm.venv_command = lambda *a: [str(f.executable)]
    elif corrupt == 'foreign_install': f.pm.state = f.tmp / 'foreign'
    elif corrupt == 'ambiguous_generation':
        packages = f.pm.site_packages(f.state / 'environments/selected-new/venv')
        packages.mkdir(parents=True)
        monkeypatch.syspath_prepend(str(packages))
    elif corrupt == 'empty_command': f.pm.command = []
    elif corrupt == 'multi_command': f.pm.command = [str(f.base_python), '-S', 'entry.py']
    elif corrupt == 'relative_executable': f.pm.command = ['python.exe']
    elif corrupt == 'missing_executable': f.executable.unlink()
    elif corrupt == 'wrong_executable': f.pm.command = [str(f.base_python)]
    elif corrupt == 'missing_cfg': (f.environment / 'pyvenv.cfg').unlink()
    elif corrupt == 'missing_marker': (f.workspace / 'agent/agent_init.py').unlink()
    elif corrupt == 'missing_lock': (f.workspace / 'uv.lock').unlink()
    elif corrupt == 'missing_workspace_bootstrap': (f.workspace / 'hermes_bootstrap.py').unlink()
    elif corrupt == 'directory_executable':
        f.executable.unlink()
        f.executable.mkdir()
    elif corrupt == 'unrelated_venv':
        other = f.tmp / 'other/.venv'
        other.mkdir(parents=True)
        monkeypatch.setattr(sys, 'prefix', str(other))
    elif corrupt == 'redirect_flag':
        original = getattr(type(f.environment), 'is_junction', lambda _: False)
        monkeypatch.setattr(type(f.environment), 'is_junction',
            lambda p: p == f.environment or original(p), raising=False)
    if corrupt == 'cwd_workspace':
        with pytest.raises(routing.RoutingError): f.router.start('mechanical', 'fixture', f.workspace)
    else:
        with pytest.raises(routing.RoutingError): _start(f.router, f.tmp)
    assert f.launches == [] and not list(f.home.rglob('snapshot.json'))


def test_loaded_old_wins_over_unimported_selected_new(adopted, monkeypatch):
    f = adopted
    f.pm.site_packages(f.state / 'environments/selected-new/venv').mkdir(parents=True)
    monkeypatch.setenv('HERMES_PYTHON', str(f.base_python))
    monkeypatch.setenv('HERMES_SOURCE_ROOT', str(f.tmp / 'foreign'))
    _start(f.router, f.tmp)
    assert f.launches[0][0][0] == str(f.executable)


def test_existing_valid_venv_requires_no_pm_adoption_module(adopted, monkeypatch):
    f = adopted
    bootstrap = ModuleType('hermes_bootstrap')
    bootstrap.__file__ = str(f.workspace / 'hermes_bootstrap.py')
    bootstrap.__spec__ = importlib.util.spec_from_file_location('hermes_bootstrap', bootstrap.__file__)
    monkeypatch.setitem(sys.modules, 'hermes_bootstrap', bootstrap)
    monkeypatch.delitem(sys.modules, 'pm.environments', raising=False)
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    monkeypatch.setattr(sys, 'prefix', str(f.environment))
    monkeypatch.setattr(sys, 'executable', str(f.executable))
    work = f.tmp / 'work'
    work.mkdir()
    core, paths, executable = routing._worker_runtime(work)
    assert core == f.workspace and paths == [str(f.workspace)] and executable == str(f.executable)


def test_no_pm_generation_preserves_existing_launch_behavior(adopted):
    f = adopted
    f.adoption.environment = None
    work = f.tmp / 'work'
    work.mkdir()
    core, paths, executable = routing._worker_runtime(work)
    assert core == f.source and paths == [str(f.source)] and executable == str(f.base_python)


def test_imported_directory_alias_cannot_hide_a_redirect(adopted, monkeypatch):
    from test_observer_loader import _create_directory_redirect
    f = adopted
    alias = f.tmp / 'packages-alias'
    with monkeypatch.context() as native:
        native.setattr(subprocess, 'Popen', _REAL_POPEN)
        _create_directory_redirect(alias, f.packages)
    monkeypatch.setattr(sys, 'path', [str(alias), *[p for p in sys.path if p != str(f.packages)]])
    # Exercise resolve-based refusal even if a runtime lacks junction detection.
    monkeypatch.setattr(type(alias), 'is_junction', lambda _: False, raising=False)
    with pytest.raises(routing.RoutingError): _start(f.router, f.tmp)
    assert f.launches == []


def test_adopted_heavy_default_and_explicit_zero_keep_the_same_budgets(adopted):
    import json
    f = adopted
    original = f.service.routing_config
    f.service.routing_config = lambda p: dict(original(p), heavy_timeout_seconds=10800, light_timeout_seconds=5400)
    work = f.tmp / 'work'
    work.mkdir()
    for timeout, expected in ((None, 10800), (0, 0)):
        result = f.router.start('independent-review', 'fixture', work, timeout=timeout)
        command = f.launches[-1][0]
        assert float(command[command.index('--timeout') + 1]) == expected
        snapshot = next(f.home.rglob(result['job_id'] + '/snapshot.json'))
        assert json.loads(snapshot.read_text())['timeout_seconds'] == expected


@pytest.mark.skipif(os.name == 'nt', reason='POSIX conventional interpreter symlink contract')
def test_existing_posix_venv_symlink_is_not_resolved_to_base(adopted, monkeypatch):
    f = adopted
    bootstrap = ModuleType('hermes_bootstrap')
    bootstrap.__file__ = str(f.workspace / 'hermes_bootstrap.py')
    bootstrap.__spec__ = importlib.util.spec_from_file_location('hermes_bootstrap', bootstrap.__file__)
    monkeypatch.setitem(sys.modules, 'hermes_bootstrap', bootstrap)
    monkeypatch.delitem(sys.modules, 'pm.environments', raising=False)
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    f.executable.unlink()
    f.executable.symlink_to(f.base_python)
    monkeypatch.setattr(sys, 'prefix', str(f.environment))
    monkeypatch.setattr(sys, 'executable', str(f.executable))
    work = f.tmp / 'work'
    work.mkdir()
    assert routing._worker_runtime(work)[2] == str(f.executable)
