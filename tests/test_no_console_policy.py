"""Windows noninteractive launch flags, without spawning visible processes."""
import os
import subprocess
from types import SimpleNamespace
import pytest
from lib import run_routed_agent as runner
from model_router.service import Service
from test_routing import _make_router, _start

pytestmark=pytest.mark.skipif(os.name!='nt',reason='native Windows launch flags')

def test_router_worker_is_windowless_not_detached(tmp_path,monkeypatch):
    router,service,home,calls=_make_router(tmp_path,monkeypatch)
    _start(router,tmp_path)
    flags=calls[0][1]['creationflags']
    assert flags & subprocess.CREATE_NO_WINDOW
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert not flags & (subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_CONSOLE)

def test_legacy_runner_launch_is_windowless(monkeypatch):
    seen={}
    def run(*a,**kw): seen.update(kw);return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(runner.subprocess,'run',run)
    runner.run_child_process(['fixture'],cwd='fixture',env={},timeout=1)
    assert seen.get('creationflags',0)&subprocess.CREATE_NO_WINDOW

def test_settings_fallback_cli_is_windowless(monkeypatch):
    seen={}
    def run(*a,**kw): seen.update(kw);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess,'run',run)
    service=object.__new__(Service)
    service.writer=None
    monkeypatch.setattr(service,'_command',lambda *a:['fixture'])
    monkeypatch.setattr(service,'_env',lambda *a:{})
    service._write_key('default','fixture','value')
    assert seen.get('creationflags',0)&subprocess.CREATE_NO_WINDOW
