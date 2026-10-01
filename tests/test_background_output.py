from contextvars import ContextVar
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from model_router import background_output as bg


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Use a deterministic redactor with privacy canaries; real redactor/direct
    # launch are covered by PublicProgress and native-runtime integration tests.
    monkeypatch.setattr(bg, "safe_display", lambda text, limit: "[REDACTED]" if any(c in text for c in ("SECRET", "\x1b", "\u202e", "\n", "\r")) else text[:limit])
    home = tmp_path.resolve()
    job_id, attempt_id, child_id = str(uuid4()), str(uuid4()), str(uuid4())
    directory = home / "plugin-data/model-router/jobs" / job_id
    output, events = [], []
    process = SimpleNamespace(pid=321)
    session = SimpleNamespace(id="proc_bound", process=process, pid=321, session_key="key-A", owner_task_id="task-A", parent_session_id="parent-A", started_at=100.0, exited=False, exited_at=0.0, exit_code=None, completion_reason="exited", append_output=output.append)
    registry = SimpleNamespace(get=lambda identifier: session if identifier == session.id else None)
    identity = {"job_id": job_id, "profile": "claire", "parent_session_id": "parent-A", "ui_session_id": "ui-A"}
    write(directory / "snapshot.json", identity)
    write(directory / "launch.json", {"process_id": session.id, "worker_pid": process.pid})
    request = {"job_id": job_id, "attempt_id": attempt_id, "profile": "claire", "parent_session_id": "parent-A", "session_id": child_id, "home": str(home), "source": "subagent", "prompt": "SECRET_REQUEST_NEVER_PUBLIC"}
    attempt = directory / "attempts" / attempt_id
    write(attempt / "attempt-request.json", request)
    public = {k: request[k] for k in ("job_id", "attempt_id", "profile", "parent_session_id", "session_id")}
    public.update(schema=1, activity="Read File 실행 중", updated_at=101000)
    write(attempt / "public-progress.json", public)
    now = [105.0]
    kwargs = dict(session=session, registry=registry, process=process, home=home, **identity, session_key="key-A", owner_task_id="task-A", emit=lambda *args: events.append(args) or True, timeout=30, clock=lambda: now[0], monotonic=lambda: now[0])
    observer = bg.BackgroundOutput(**kwargs)
    return SimpleNamespace(home=home, directory=directory, attempt=attempt, public=public, request=request, output=output, events=events, session=session, registry=registry, observer=observer, kwargs=kwargs, now=now)


def test_real_changes_only_and_frozen_exactly_once_summary(setup):
    s = setup
    assert s.observer.tick()
    assert s.observer.tick()
    assert s.output == ["[00:01] Read File 실행 중\n"]
    s.public.update(updated_at=103000, activity="응답: 검증 중입니다.")
    write(s.attempt / "public-progress.json", s.public)
    assert s.observer.tick()
    s.session.exited, s.session.exit_code, s.session.exited_at = True, 0, 104.0
    # A last atomic writer update is consumed even after the native exit.
    s.public.update(updated_at=104000, activity="마지막 활동")
    write(s.attempt / "public-progress.json", s.public)
    assert not s.observer.tick()
    s.now[0] = 300
    assert not s.observer.tick()
    text = "".join(s.output)
    assert text.count("프로세스 종료를 확인했습니다.") == 1
    assert "[00:04] 마지막 활동" in text
    assert "종료 확인 시 소요 시간: 00:04" in text
    assert "검수 통과를 뜻하지 않습니다" in text
    assert "SECRET" not in text
    assert all(event == ("status.update", {"kind": "process", "process_id": "proc_bound"}) for event in s.events)


@pytest.mark.parametrize("field,bad", [("job_id", str(uuid4())), ("profile", "other"), ("parent_session_id", "parent-B"), ("attempt_id", str(uuid4())), ("session_id", str(uuid4())), ("schema", True), ("updated_at", float("nan")), ("updated_at", 999999999), ("activity", 4)])
def test_foreign_or_invalid_public_does_not_leak(setup, field, bad):
    s = setup
    s.public[field] = bad
    write(s.attempt / "public-progress.json", s.public)
    assert s.observer.tick()
    assert s.output == []


@pytest.mark.parametrize("name,field,bad", [("launch.json", "process_id", "proc_foreign"), ("launch.json", "worker_pid", 999), ("snapshot.json", "ui_session_id", "ui-B"), ("snapshot.json", "profile", "other")])
def test_binding_readback_required(setup, name, field, bad):
    s = setup
    value = json.loads((s.directory / name).read_text())
    value[field] = bad
    write(s.directory / name, value)
    assert s.observer.tick()
    assert not s.output


def test_native_owner_change_stops_without_write_or_kill(setup):
    s = setup
    s.session.owner_task_id = "foreign"
    assert not s.observer.tick()
    assert not s.output
    assert not s.session.exited


def test_registry_replacement_cannot_receive_output(setup):
    s = setup
    s.registry.get = lambda _: SimpleNamespace(**vars(s.session))
    assert not s.observer.tick()
    assert not s.output


@pytest.mark.parametrize("activity", ["SECRET_TOKEN_123", "visible\x1b[2Jhidden", "forged\nresult", "\u202esecret"])
def test_final_boundary_redacts_whole_activity(setup, activity):
    s = setup
    s.public["activity"] = activity
    write(s.attempt / "public-progress.json", s.public)
    s.observer.tick()
    assert s.output == ["[00:01] [REDACTED]\n"]


def test_oversized_and_symlink_files_fail_closed(setup):
    s = setup
    (s.attempt / "public-progress.json").write_text("x" * (bg.MAX_PUBLIC_BYTES + 1))
    assert s.observer.tick() and not s.output
    original = s.attempt / "public-progress.json"
    original.unlink()
    elsewhere = s.home / "elsewhere.json"
    write(elsewhere, s.public)
    try:
        original.symlink_to(elsewhere)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    assert s.observer.tick() and not s.output


@pytest.mark.parametrize("reason,code,label", [("killed", -9, "중지"), ("exited", 1, "실행 실패"), ("lost", 0, "종료 상태 확인 필요"), ("exited", None, "종료 상태 확인 필요")])
def test_native_terminal_reason_only(setup, reason, code, label):
    s = setup
    # Private result content must NEVER be consulted or copied.
    write(s.directory / "runner-result.json", {"completed": True, "final_response": "SECRET_FULL_ANSWER_GO"})
    s.session.exited, s.session.exit_code, s.session.completion_reason = True, code, reason
    assert not s.observer.tick()
    assert "프로세스 종료를 확인했습니다." in "".join(s.output)
    assert "Background의 현재 상태" in "".join(s.output)
    assert f"실행 결과: {label}" not in "".join(s.output)
    assert "SECRET" not in "".join(s.output)


def test_activity_cap_keeps_final_summary_and_no_repeated_notice(setup, monkeypatch):
    s = setup
    monkeypatch.setattr(bg, "MAX_LINES", 1)
    s.observer.tick()
    s.public.update(activity="두번째", updated_at=102000)
    write(s.attempt / "public-progress.json", s.public)
    s.observer.tick()
    s.public.update(activity="세번째", updated_at=103000)
    write(s.attempt / "public-progress.json", s.public)
    s.observer.tick()
    s.session.exited, s.session.exit_code = True, 0
    s.observer.tick()
    text = "".join(s.output)
    assert text.count("활동 기록 한도") == 1
    assert "두번째" not in text and "세번째" not in text
    assert "프로세스 종료를 확인했습니다." in text


def test_observation_deadline_does_not_claim_task_exit(setup):
    s = setup
    s.now[0] = 200
    assert not s.observer.tick()
    assert "관찰 시간이 끝났습니다" in "".join(s.output)
    assert "실행 결과:" not in "".join(s.output)
    assert not s.session.exited


def test_emit_failure_does_not_affect_native_lifecycle(setup):
    s = setup
    s.observer.emit = lambda *args: (_ for _ in ()).throw(RuntimeError("SECRET_EMIT_ERROR"))
    s.session.exited, s.session.exit_code = True, 0
    assert not s.observer.tick()
    assert "프로세스 종료를 확인했습니다." in "".join(s.output)
    assert "SECRET" not in "".join(s.output)


def test_thread_preserves_spawning_context_and_stops(setup):
    s = setup
    current = ContextVar("test-bound-ui", default="WRONG")
    current.set("ui-A")
    seen = []
    s.kwargs["emit"] = lambda *args: seen.append(current.get())
    s.session.exited, s.session.exit_code = True, 0
    thread = bg.start_background_output(**s.kwargs)
    current.set("ui-B")
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert seen and set(seen) == {"ui-A"}


def test_two_attempts_and_repeated_latest_snapshot_do_not_spam(setup):
    s = setup
    s.observer.tick()
    second = s.directory / "attempts" / str(uuid4())
    request = dict(s.request, attempt_id=second.name, session_id=str(uuid4()))
    public = dict(s.public, attempt_id=second.name, session_id=request["session_id"], updated_at=103000, activity="다음 시도 활동")
    write(second / "attempt-request.json", request)
    write(second / "public-progress.json", public)
    s.observer.tick()
    s.observer.tick()
    assert len(s.output) == 2
    assert "다음 시도 활동" in s.output[-1]


def test_real_registry_output_and_final_flush_without_wait_or_kill_ownership(tmp_path):
    import subprocess
    import sys
    import time
    from tools.process_registry import ProcessRegistry
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from gateway.session_context import scoped_current_session_id
    from model_router.runtime_tracking import RouteRuntime
    from agent.redact import redact_sensitive_text

    home = tmp_path.resolve()
    token = set_hermes_home_override(str(home))
    registry, process = ProcessRegistry(), None
    seen = []
    try:
        job_id, attempt_id, child_id = str(uuid4()), str(uuid4()), str(uuid4())
        directory = home / "plugin-data/model-router/jobs" / job_id
        write(directory / "snapshot.json", {"job_id": job_id, "profile": "claire", "parent_session_id": "native-parent", "ui_session_id": "ui-A"})
        with scoped_current_session_id("native-parent"):
            with (home / "private.log").open("wb") as handle:
                process = subprocess.Popen([sys.executable, "-c", "import time; print('PRIVATE_LOG_CANARY', flush=True); time.sleep(1.5)"], stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT, close_fds=True)
            runtime = RouteRuntime("native-parent", "native-key", "owner-A", registry, lambda *args: seen.append(args) or True, "ui-A")
            process_id = runtime.track(process, job_id=job_id, profile="claire", purpose="mechanical", cwd=str(home))
            write(directory / "launch.json", {"process_id": process_id, "worker_pid": process.pid})
            runtime.observe(process, process_id=process_id, home=home, timeout=30, job_id=job_id, profile="claire")
            row = registry.get(process_id)
            attempt = directory / "attempts" / attempt_id
            request = {"job_id": job_id, "attempt_id": attempt_id, "session_id": child_id, "profile": "claire", "parent_session_id": "native-parent", "home": str(home), "source": "subagent"}
            write(attempt / "attempt-request.json", request)
            public = {k: request[k] for k in ("job_id", "attempt_id", "session_id", "profile", "parent_session_id")}
            public.update(schema=1, updated_at=time.time() * 1000, activity="Read File 실행 중")
            write(attempt / "public-progress.json", public)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and "프로세스 종료를 확인했습니다." not in row.output_buffer:
                time.sleep(0.05)
            assert row.exited and row.exit_code == 0
            assert "Read File 실행 중" in row.output_buffer
            assert "프로세스 종료를 확인했습니다." in row.output_buffer
            assert "PRIVATE_LOG_CANARY" not in row.output_buffer
            assert row.output_buffer.count("종료 확인 시 소요 시간:") == 1
            assert all(e == ("status.update", {"kind": "process", "process_id": process_id}) for e in seen)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        reset_hermes_home_override(token)


def test_runtime_wires_only_its_adopted_session(setup, monkeypatch):
    from model_router.runtime_tracking import RouteRuntime
    s = setup
    captured = []
    monkeypatch.setattr(bg, "start_background_output", lambda **kwargs: captured.append(kwargs))
    s.registry.adopt_local = lambda process, **kwargs: s.session
    runtime = RouteRuntime("parent-A", "key-A", "task-A", s.registry, lambda *a: True, "ui-A")
    result = runtime.track(s.session.process, job_id=s.kwargs["job_id"], purpose="mechanical", cwd=str(s.home), profile="claire")
    assert result == s.session.id
    assert captured == []
    runtime.observe(s.session.process, process_id=result, home=s.home, timeout=30, job_id=s.kwargs["job_id"], profile="claire")
    assert len(captured) == 1
    assert captured[0]["session"] is s.session
    assert captured[0]["home"] == s.home
    assert captured[0]["parent_session_id"] == "parent-A"
    assert captured[0]["ui_session_id"] == "ui-A"
