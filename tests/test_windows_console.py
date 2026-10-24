"""No-network native Windows regression for a windowless parent's adapter seam."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import run_routed_agent as runner
from model_router import job_worker


@pytest.mark.skipif(os.name != 'nt', reason='Windows console allocation contract')
def test_real_scoped_adapter_has_no_console_from_windowless_parent(tmp_path):
    leaf = tmp_path / 'leaf.py'
    report = tmp_path / 'console.json'
    leaf.write_text('''import ctypes,json,sys
from pathlib import Path
k=ctypes.WinDLL('kernel32');u=ctypes.WinDLL('user32')
k.GetConsoleWindow.restype=ctypes.c_void_p
u.IsWindowVisible.argtypes=[ctypes.c_void_p]
h=k.GetConsoleWindow()
Path(sys.argv[sys.argv.index('--request')+1]).with_name('console.json').write_text(json.dumps({'attached':bool(h),'visible':bool(h and u.IsWindowVisible(h))}))
''', encoding='utf-8')
    driver = tmp_path / 'driver.py'
    repo = Path(__file__).resolve().parents[1]
    driver.write_text(f'''import sys,time
from pathlib import Path
sys.path.insert(0,{str(repo)!r})
from lib import run_routed_agent as r
r.SCOPED_AGENT_PATH=Path({str(leaf)!r})
a=r._invoke_scoped_adapter({{'home':{str(tmp_path)!r},'profile':'default'}},Path({str(tmp_path)!r}),Path({str(tmp_path)!r}),time.monotonic()+15)
assert a[0] is None and a[1] is False and a[3]==0
''', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-B', str(driver)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                               creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        assert process.wait(timeout=25) == 0
        assert json.loads(report.read_text(encoding='utf-8')) == {'attached': False, 'visible': False}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows taskkill launch contract')
@pytest.mark.parametrize('module', [job_worker, runner])
def test_owned_tree_cleanup_helper_does_not_create_a_console(monkeypatch, module):
    calls = []
    monkeypatch.setattr(module.shutil, 'which', lambda name: 'C:/Windows/System32/taskkill.exe')
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', fake_run)
    process = SimpleNamespace(pid=34567, wait=lambda timeout: 0, poll=lambda: 0)
    stop = module._terminate_process_tree if module is job_worker else module._stop_scoped_process_tree
    assert stop(process) is True
    command, kwargs = calls[0]
    assert command[1:] == ['/PID', '34567', '/T', '/F']
    assert kwargs['creationflags'] == subprocess.CREATE_NO_WINDOW
    assert kwargs['stdin'] == kwargs['stdout'] == kwargs['stderr'] == subprocess.DEVNULL
