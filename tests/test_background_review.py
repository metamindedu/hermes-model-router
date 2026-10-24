"""Deterministic regressions for independent review H1/M1/M2/M3."""
from contextvars import Context
import json
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from model_router import background_output as bg, task_presentation
from test_background_output import setup, write


def test_final_flush_that_races_first_read_is_before_exit_summary(setup, monkeypatch):
    s = setup
    original = s.observer._activities
    calls = []
    def read():
        values = original()
        if not calls:
            calls.append(True)
            s.public.update(activity="마지막 원자적 기록", updated_at=104000)
            write(s.attempt / "public-progress.json", s.public)
            s.session.exited = True
            s.session.exit_code = 0
            s.session.exited_at = 104.0
        return values
    monkeypatch.setattr(s.observer, "_activities", read)
    assert not s.observer.tick()
    text = "".join(s.output)
    assert text.count("마지막 원자적 기록") == 1
    assert text.index("마지막 원자적 기록") < text.index("프로세스 종료를 확인했습니다.")


def test_partially_published_exit_never_freezes_an_outcome(setup):
    s = setup
    s.session.exited = True  # mark_exited exposes this before reason/code.
    assert s.session.exit_code is None
    s.observer.tick()
    s.session.exit_code, s.session.completion_reason = -15, "killed"
    assert not s.observer.tick()
    text = "".join(s.output)
    assert "프로세스 종료를 확인했습니다." in text
    assert "실행 실패" not in text and "정상 종료" not in text
    assert "종료 종류: Background의 현재 상태" in text


@pytest.mark.parametrize("exit_code", [0, 7])
def test_native_kill_reader_publication_race_does_not_mislabel(tmp_path, monkeypatch, exit_code):
    from tools.process_registry import ProcessRegistry
    from tools.process_registry_results import load_completed_results
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from gateway.session_context import scoped_current_session_id

    home = tmp_path.resolve()
    token = set_hermes_home_override(str(home))
    process = None
    try:
        registry = ProcessRegistry()
        signal_file = home / "release-child"
        script = "import pathlib,time,sys; p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(0.01)\nsys.exit(int(sys.argv[2]))"
        with scoped_current_session_id("parent-A"):
            process = subprocess.Popen([sys.executable, "-c", script, str(signal_file), str(exit_code)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            session = registry.adopt_local(process, command="test-task", cwd=str(home), task_id="owner-A", owner_task_id="owner-A", session_key="key-A", notify_on_complete=False)
            job_id = str(uuid4())
            identity = dict(job_id=job_id, profile="claire", parent_session_id="parent-A", ui_session_id="ui-A")
            directory = home / "plugin-data/model-router/jobs" / job_id
            write(directory / "snapshot.json", identity)
            write(directory / "launch.json", {"process_id": session.id, "worker_pid": process.pid})
            observer = bg.BackgroundOutput(session=session, registry=registry, process=process, home=home, **identity, session_key="key-A", owner_task_id="owner-A", emit=lambda *a: True, timeout=30)
            publication = []
            def coordinated_signal(row, process_id, consume):
                # Signal delivery is replaced ONLY at the OS seam to force the
                # reader-win order deterministically on Windows and POSIX.
                signal_file.write_text("exit")
                row._reader_thread.join(timeout=5)
                assert row.exited and row.exit_code == exit_code
                assert not observer.tick()
                publication.append(row.output_buffer)
                return None  # Native kill now corrects the reason to killed.
            monkeypatch.setattr(registry, "_signal_kill", coordinated_signal)
            receipt = registry.kill_process(session.id)
            assert receipt["status"] == "killed"
            assert session.completion_reason == "killed"
            assert publication and session.output_buffer == publication[0]
            assert "정상 종료" not in session.output_buffer and "실행 실패" not in session.output_buffer
            assert session.output_buffer.count("프로세스 종료를 확인했습니다.") == 1
            assert not observer.tick()
            retained = load_completed_results(session.id)[session.id]
            assert retained.completion_reason == "killed"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        reset_hermes_home_override(token)


def test_late_output_is_live_only_and_does_not_rewrite_native_receipt(setup, monkeypatch):
    from tools.process_registry import ProcessSession
    from tools.process_registry_results import save_completed_result, load_completed_results
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from gateway.session_context import scoped_current_session_id
    s = setup
    token = set_hermes_home_override(str(s.home))
    try:
        with scoped_current_session_id("parent-A"):
            row = ProcessSession(id=s.session.id, command="task", task_id="task-A", owner_task_id="task-A", session_key="key-A", parent_session_id="parent-A", started_at=100, exited=True, exit_code=0)
            save_completed_result(row)
            path = s.home / "logs/process-results" / (row.id + ".json")
            before = path.read_bytes()
            s.session.exited, s.session.exit_code = True, 0
            s.observer.tick()
            assert "프로세스 종료를 확인했습니다." in "".join(s.output)
            assert path.read_bytes() == before
            assert "프로세스 종료를 확인했습니다." not in load_completed_results(row.id)[row.id].output_buffer
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize("kind", ["token", "url", "control", "boundary"])
def test_real_sanitizer_on_public_artifact_to_output(setup, monkeypatch, kind):
    s = setup
    monkeypatch.setattr(bg, "safe_display", task_presentation.safe_display)
    secret = "a" * 40
    text = {
        "token": "token=ghp_" + secret,
        "url": "https://username:" + secret + "@example.invalid/path",
        "control": "private\x1b[2J\u202ehidden",
        "boundary": "X" * (bg.MAX_ACTIVITY_CHARS - 12) + " token=ghp_" + secret,
    }[kind]
    s.public["activity"] = text
    write(s.attempt / "public-progress.json", s.public)
    s.observer.tick()
    output = "".join(s.output)
    assert output
    assert secret not in output and ("ghp_" + secret) not in output
    assert "\x1b" not in output and "\u202e" not in output
    assert len(output) <= bg.MAX_ACTIVITY_CHARS + 10


def test_existing_native_output_sink_gets_late_summary_after_row_dismissal(setup):
    s = setup
    streamed = []
    s.registry.on_output = lambda session, chunk: streamed.append((session, chunk))
    # Simulate the existing native Stop UI discarding process-list snapshots.
    s.observer.emit = lambda *args: False
    s.observer.tick()
    s.session.exited, s.session.exit_code, s.session.completion_reason = True, -15, "killed"
    assert not s.observer.tick()
    assert streamed and all(session is s.session for session, _ in streamed)
    assert "".join(chunk for _, chunk in streamed) == "".join(s.output)
    assert "프로세스 종료를 확인했습니다." in streamed[-1][1]
    assert not s.observer.tick()


def test_native_output_sink_failure_is_nonfatal(setup):
    s = setup
    def failed_sink(*args):
        raise RuntimeError("SECRET_SINK_EXCEPTION")
    s.registry.on_output = failed_sink
    s.session.exited, s.session.exit_code = True, 0
    assert not s.observer.tick()
    assert "프로세스 종료를 확인했습니다." in "".join(s.output)
    assert "SECRET" not in "".join(s.output)


def test_actual_desktop_emit_preserves_bound_ui_not_later_focus(setup, monkeypatch):
    from gateway.session_context import set_session_vars
    from tools import desktop_ui
    s = setup
    received = []
    monkeypatch.setattr(desktop_ui, "_emit", lambda sid, event, payload: received.append((sid, event, payload)))
    s.kwargs["emit"] = desktop_ui.emit
    s.session.exited, s.session.exit_code = True, 0
    def spawn():
        set_session_vars(session_id="parent-A", session_key="key-A", profile="claire", ui_session_id="ui-A")
        thread = bg.start_background_output(**s.kwargs)
        set_session_vars(session_id="parent-B", session_key="key-B", profile="other", ui_session_id="ui-B")
        thread.join(timeout=3)
        assert not thread.is_alive()
    Context().run(spawn)
    assert received
    assert all(sid == "ui-A" and event == "status.update" and payload == {"kind": "process", "text": ""} for sid, event, payload in received)
