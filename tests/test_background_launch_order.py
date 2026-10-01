"""Observer must not open launch metadata before Windows atomic publication."""
from types import SimpleNamespace
import os
import pytest

from model_router import background_output as bg, routing
from model_router.runtime_tracking import RouteRuntime
from test_routing import _make_router, _start, _load


def test_launch_publication_precedes_background_reader(tmp_path, monkeypatch):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    observed = []
    session = SimpleNamespace(id='proc_order', append_output=lambda text: None, process=None, pid=987654, owner_task_id='owner-A', session_key='key-A', parent_session_id='parent-A')
    def adopt(process, **kwargs):
        session.process = process
        return session
    registry = SimpleNamespace(adopt_local=adopt, get=lambda _: session)
    router.runtime = RouteRuntime('parent-A', 'key-A', 'owner-A', registry, lambda *a: True, 'ui-A')
    monkeypatch.setattr(bg, 'start_background_output', lambda **kwargs: observed.append(kwargs))
    original = routing._write_json
    def windows_replace(path, data, *, exclusive=False):
        if path.name == 'launch.json' and not exclusive and observed:
            raise PermissionError('simulated Windows sharing violation: observer holds launch.json')
        return original(path, data, exclusive=exclusive)
    monkeypatch.setattr(routing, '_write_json', windows_replace)
    result = _start(router, tmp_path)
    job = root / 'profiles/claire/plugin-data/model-router/jobs' / result['job_id']
    assert _load(job / 'launch.json')['worker_pid'] == 987654
    assert _load(job / 'launch.json')['process_id'] == 'proc_order'
    assert len(observed) == 1
    assert len(calls) == 1  # Never relaunch the already running worker.


def test_windows_open_reader_blocks_atomic_launch_replace(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows sharing contract")
    target = tmp_path / "launch.json"
    routing._write_json(target, {"worker_pid": None}, exclusive=True)
    with target.open("rb"):
        with pytest.raises(PermissionError):
            routing._write_json(target, {"worker_pid": 321})
    assert _load(target)["worker_pid"] is None
    routing._write_json(target, {"worker_pid": 321})
    assert _load(target)["worker_pid"] == 321


def test_failed_launch_write_does_not_start_observer_or_repeat_worker(tmp_path, monkeypatch):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    observed = []
    router.runtime = SimpleNamespace(parent_session_id="parent-A", ui_session_id="ui-A", track=lambda *a, **k: "proc_order", observe=lambda *a, **k: observed.append(True))
    original = routing._write_json
    def failure(path, data, *, exclusive=False):
        if path.name == "launch.json" and not exclusive:
            raise PermissionError("private exception not public")
        return original(path, data, exclusive=exclusive)
    monkeypatch.setattr(routing, "_write_json", failure)
    result = _start(router, tmp_path)
    assert result["status"] == "running"
    assert result["activity_tracking_error"] is True
    assert observed == [] and len(calls) == 1
    assert "private exception" not in str(result)
