"""Valid conventional POSIX Python aliases retain their exact venv entry."""
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType, SimpleNamespace
import importlib.util
import pytest

from model_router import routing, scoped_agent
from test_worker_runtime_authority import adopted


@pytest.mark.parametrize('layout', ['conventional', 'managed'])
@pytest.mark.parametrize('entry', ['python', 'python3', f'python{sys.version_info.major}.{sys.version_info.minor}'])
def test_bound_posix_alias_matches_unchanged_child_authority(adopted, monkeypatch, layout, entry):
    f = adopted
    if layout == 'conventional':
        core = f.tmp / 'conventional-source'
        shutil.copytree(f.workspace, core)
        prefix = core / '.venv'
        prefix.mkdir()
    else:
        core, prefix = f.workspace, f.environment
    executable = prefix / 'bin' / entry
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b'fixture only; never executed')
    bootstrap = ModuleType('hermes_bootstrap')
    bootstrap.__file__ = str(core / 'hermes_bootstrap.py')
    bootstrap.__spec__ = importlib.util.spec_from_file_location('hermes_bootstrap', bootstrap.__file__)
    monkeypatch.setitem(sys.modules, 'hermes_bootstrap', bootstrap)
    monkeypatch.delitem(sys.modules, 'pm.environments', raising=False)
    monkeypatch.delitem(sys.modules, 'pm.environments_adopt', raising=False)
    monkeypatch.setattr(sys, 'prefix', str(prefix))
    monkeypatch.setattr(sys, 'executable', str(executable))
    # Test only the production POSIX branch on Windows, without changing the
    # global os module or pretending to have executed a POSIX interpreter.
    monkeypatch.setattr(routing, 'os', SimpleNamespace(name='posix'))
    work = f.tmp / 'work'
    work.mkdir()
    assert scoped_agent._trusted_core_root() == core.resolve()
    chosen_core, _, chosen_executable = routing._worker_runtime(work)
    assert chosen_core == core
    assert chosen_executable == str(executable)


@pytest.mark.parametrize('foreign', ['foreign_directory', 'non_python_name'])
def test_bound_posix_host_rejects_foreign_entry(adopted, monkeypatch, foreign):
    f = adopted
    bootstrap = ModuleType('hermes_bootstrap')
    bootstrap.__file__ = str(f.workspace / 'hermes_bootstrap.py')
    bootstrap.__spec__ = importlib.util.spec_from_file_location('hermes_bootstrap', bootstrap.__file__)
    monkeypatch.setitem(sys.modules, 'hermes_bootstrap', bootstrap)
    monkeypatch.setattr(sys, 'prefix', str(f.environment))
    executable = (f.tmp / 'foreign/bin/python3' if foreign == 'foreign_directory'
                  else f.environment / 'bin/not-python')
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b'fixture only')
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setattr(routing, 'os', SimpleNamespace(name='posix'))
    work = f.tmp / 'work'
    work.mkdir()
    with pytest.raises(routing.RoutingError): routing._worker_runtime(work)
    assert f.launches == []
