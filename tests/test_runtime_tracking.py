"""Regression seam: a routed worker is visible in native background state."""
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import subprocess
import sys
import time

from model_router import routing
from test_routing import _make_router, _start, _load


def test_route_registers_the_actual_worker_and_snapshots_parent(tmp_path, monkeypatch):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    parent = "20260930_113515_240566"
    adopted = []
    class Runtime:
        parent_session_id = parent
        def track(self, process, **metadata):
            adopted.append((process, metadata))
            return "proc_test123"
    router.runtime = Runtime()
    result = _start(router, tmp_path)
    job = root / "profiles/claire/plugin-data/model-router/jobs" / result["job_id"]
    assert _load(job / "snapshot.json")["parent_session_id"] == parent
    assert len(adopted) == 1
    assert adopted[0][0].pid == 987654
    assert adopted[0][1] == {
        "job_id": result["job_id"],
        "purpose": "implementation",
        "cwd": str((tmp_path / "work").resolve()),
        "title": "기능 구현",
        "role": "LIGHTWEIGHT",
        "model": service.light["model"],
        "reasoning": service.light["reasoning"],
        "provider": service.light["provider"],
        "profile": "claire",
    }
    assert result["title"] == "기능 구현"
    assert result["process_id"] == "proc_test123"
    assert _load(job / "launch.json")["process_id"] == "proc_test123"
    # The child retains a file-backed log; adopting does not introduce inherited pipes.
    assert calls[0][1]["stdout"] is not subprocess.PIPE
    assert calls[0][1]["close_fds"] is True


def test_tracking_failure_never_relaunches_or_claims_worker_failed(tmp_path, monkeypatch):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    class Runtime:
        parent_session_id = "parent-session"
        def track(self, *args, **kwargs):
            raise RuntimeError("SECRET_EXCEPTION_CANARY")
    router.runtime = Runtime()
    result = _start(router, tmp_path)
    assert len(calls) == 1
    assert result["status"] == "running"
    assert result["tracking_error"] == "RuntimeError"
    assert "SECRET_EXCEPTION_CANARY" not in str(result)


def test_native_adoption_uses_task_local_context_and_no_fake_delegate_events(tmp_path):
    from model_router.runtime_tracking import capture_runtime
    current = ContextVar("route_test_env")
    get_env = lambda name, default="": current.get({}).get(name, default)
    adoptions, events, seeds = [], [], []
    class Registry:
        def adopt_local(self, process, **kwargs):
            adoptions.append((process, kwargs))
            return SimpleNamespace(id="proc_native", append_output=seeds.append)
    def launch(parent):
        current.set({"HERMES_SESSION_ID": parent, "HERMES_SESSION_KEY": "key-" + parent, "HERMES_UI_SESSION_ID": "ui-" + parent, "HERMES_SESSION_PROFILE": "claire"})
        runtime = capture_runtime(task_id="task-" + parent, get_env=get_env, registry=Registry(), emit=lambda *a: events.append(a) or True)
        return runtime.track(SimpleNamespace(pid=1), job_id="job-" + parent, purpose="mechanical", cwd=str(tmp_path))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(launch, ["parent-A", "parent-B"])) == ["proc_native", "proc_native"]
    assert {kw["session_key"] for _, kw in adoptions} == {"key-parent-A", "key-parent-B"}
    assert {kw["owner_task_id"] for _, kw in adoptions} == {"task-parent-A", "task-parent-B"}
    assert all(kw["notify_on_complete"] is False for _, kw in adoptions)
    assert all(kw["command"].startswith("서브 에이전트 작업: 테스트 및 검증 · Light · 미지정") for _, kw in adoptions)
    assert all("job-parent-" not in kw["command"] for _, kw in adoptions)
    assert len(seeds) == 2
    assert all("작업 ID: job-parent-" in seed and "작업 폴더:" in seed for seed in seeds)
    assert all(event[0] == "status.update" and event[1]["kind"] == "process" for event in events)


def test_unbound_cli_launch_stays_supported_without_desktop_fabrication():
    from model_router.runtime_tracking import capture_runtime
    assert capture_runtime(task_id="", get_env=lambda *args: "") is None


def test_real_registry_tracks_file_logged_worker_until_actual_exit(tmp_path, monkeypatch):
    from tools.process_registry import ProcessRegistry
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from gateway.session_context import scoped_current_session_id
    from model_router.runtime_tracking import capture_runtime
    token = set_hermes_home_override(str(tmp_path))
    registry = ProcessRegistry()
    events = []
    process = None
    try:
        with scoped_current_session_id("native-parent"):
            runtime = capture_runtime(task_id="test-owner", registry=registry, get_env=lambda key, default="": {"HERMES_SESSION_ID": "native-parent", "HERMES_SESSION_KEY": "native-key"}.get(key, default), emit=lambda *a: events.append(a) or True)
            with (tmp_path / "job.log").open("wb") as out:
                process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(0.6)"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True)
            pid = runtime.track(process, job_id="real-job", purpose="mechanical", cwd=str(tmp_path))
            row = registry.get(pid)
            assert row.pid == process.pid and row.session_key == "native-key"
            assert row.owner_task_id == "test-owner" and not row.exited
            assert row.parent_session_id == "native-parent"
            process.wait(timeout=5)
            row._reader_thread.join(timeout=5)
            assert row.exited and row.exit_code == 0
            assert registry.poll(pid)["status"] == "exited"
    finally:
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=5)
        reset_hermes_home_override(token)
