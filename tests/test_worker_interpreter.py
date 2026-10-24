"""A PM-adopted base host must not discard the loaded venv at spawn."""
from pathlib import Path

import pytest
import hermes_bootstrap
from pm.environments import venv_command, site_packages
from pm.environments_adopt import running_environment

from model_router import routing
from test_routing import _make_router, _start


def test_native_base_host_binding_survives_two_hops(tmp_path):
    import json
    import os
    import subprocess
    import sys
    parent_core = os.environ.get('MODEL_ROUTER_TEST_PARENT_CORE')
    if not parent_core:
        pytest.skip('set MODEL_ROUTER_TEST_PARENT_CORE for the native PM source-host probe')
        return
    plugin = Path(__file__).resolve().parents[1]
    scoped = plugin / 'model_router/scoped_agent.py'
    probe = f'''import sys,json,importlib.util
s=importlib.util.spec_from_file_location('binding_probe',{str(scoped)!r})
m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
print(json.dumps({{'prefix':sys.prefix,'base':sys.base_prefix,'core':str(m._trusted_core_root())}}))
'''
    child = f'''import subprocess,sys,json
first=json.loads(subprocess.check_output([sys.executable,'-B','-c',{probe!r}],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
second=json.loads(subprocess.check_output([sys.executable,'-B','-c',{probe!r}],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
print(json.dumps([first,second]))
'''
    program = f'''import sys,pathlib,subprocess,json,os
sys.path[:0]=[{parent_core!r},{str(Path(sys.prefix) / ('Lib/site-packages' if os.name == 'nt' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'))!r},{str(plugin)!r}]
import hermes_bootstrap,pm.environments
assert 'pm.environments_adopt' not in sys.modules, 'probe must preserve cold helper state'
from model_router import routing
core,paths,exe=routing._worker_runtime(pathlib.Path({str(tmp_path)!r}))
env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join(paths)
results=json.loads(subprocess.check_output([exe,'-B','-c',{child!r}],env=env,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
print(json.dumps({{'exe':exe,'core':str(core),'results':results}}))
'''
    env = {k:v for k,v in os.environ.items() if k.upper() in {
        'PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','USERPROFILE','LOCALAPPDATA','APPDATA','HOME'}}
    home = tmp_path / 'home'
    home.mkdir()
    env.update(HERMES_HOME=str(home), TMPDIR=str(tmp_path), TEMP=str(tmp_path), TMP=str(tmp_path),
               PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([getattr(sys, '_base_executable', sys.executable), '-B', '-c', program], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr[-3000:]
    actual = json.loads(result.stdout)
    prefix = Path(actual['exe']).parent.parent
    for hop in actual['results']:
        assert Path(hop['prefix']) == prefix
        assert hop['prefix'] != hop['base']
        assert Path(hop['core']) == Path(actual['core']) == prefix.parent / 'workspace'

