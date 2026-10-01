from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from model_router import public_progress


EXPECTED_FIELDS = {
    "schema",
    "job_id",
    "attempt_id",
    "profile",
    "parent_session_id",
    "session_id",
    "activity",
    "updated_at",
}


@pytest.fixture
def attempt() -> Any:
    base = Path(tempfile.mkdtemp(prefix="r", dir=tempfile.gettempdir()))
    home = base / "h"
    cwd = base / "w"
    home.mkdir()
    cwd.mkdir()
    job_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    attempt_dir = home / "plugin-data" / "model-router" / "jobs" / job_id / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True)
    request = {
        "schema": 1,
        "attempt_id": attempt_id,
        "job_id": job_id,
        "profile": "claire",
        "home": str(home.resolve()),
        "cwd": str(cwd.resolve()),
        "source": "subagent",
        "task_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "parent_session_id": "20260930_113515_240566",
        "route": {"provider": "requested-provider", "model": "requested/model", "reasoning": "medium"},
        "toolsets": ["filesystem"],
        "prompt": "PRIVATE_PROMPT_CANARY",
        "budget_seconds": 45,
    }
    request_path = attempt_dir / "attempt-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    try:
        yield {
            "base": base,
            "home": home,
            "attempt_dir": attempt_dir,
            "request": request,
            "request_path": request_path,
            "progress_path": attempt_dir / "public-progress.json",
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _read_progress(attempt: dict[str, Any]) -> tuple[dict[str, Any], str]:
    path = attempt["progress_path"]
    text = path.read_text(encoding="utf-8")
    return json.loads(text), text


def _identity_payload(attempt: dict[str, Any]) -> dict[str, Any]:
    request = attempt["request"]
    return {
        "schema": 1,
        "job_id": request["job_id"],
        "attempt_id": request["attempt_id"],
        "profile": request["profile"],
        "parent_session_id": request["parent_session_id"],
        "session_id": request["session_id"],
    }


def test_initial_progress_has_bounded_reader_compatible_schema(attempt):
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])

    payload, raw = _read_progress(attempt)

    assert writer.path == attempt["progress_path"]
    assert set(payload) == EXPECTED_FIELDS
    assert {key: payload[key] for key in _identity_payload(attempt)} == _identity_payload(attempt)
    assert payload["activity"] == public_progress.WAITING_ACTIVITY
    assert isinstance(payload["updated_at"], (int, float))
    assert not isinstance(payload["updated_at"], bool)
    assert math.isfinite(payload["updated_at"])
    assert len(raw.encode("utf-8")) <= public_progress.MAX_PROGRESS_BYTES
    assert "PRIVATE_PROMPT_CANARY" not in raw


def test_interim_is_force_redacted_before_any_output_truncation(attempt, monkeypatch):
    seen: list[tuple[str, int]] = []
    full_text = "visible prefix " + "x" * (public_progress.MAX_ACTIVITY_CHARS + 20) + " tail secret"

    def redact(value: str, limit: int) -> str:
        seen.append((value, limit))
        return "[fully redacted]"

    monkeypatch.setattr(public_progress, "safe_display", redact)
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    writer.interim(full_text)
    writer.flush()

    payload, _raw = _read_progress(attempt)
    assert seen == [(full_text, public_progress.MAX_ACTIVITY_CHARS - len("응답: "))]
    assert payload["activity"] == "응답: [fully redacted]"
    assert "tail secret" not in payload["activity"]


def test_overlong_or_control_bearing_interim_fails_closed(attempt, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(public_progress, "safe_display", lambda value, _limit: calls.append(value) or value)
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    writer.interim("OVERSIZE_SECRET_CANARY" + "x" * public_progress.MAX_INTERIM_INPUT_CHARS)
    writer.flush()
    payload, raw = _read_progress(attempt)
    assert payload["activity"] == public_progress.SAFE_FALLBACK_TEXT
    assert "OVERSIZE_SECRET_CANARY" not in raw
    assert calls == []

    writer.interim("visible text \u202e hidden-direction text")
    writer.flush()
    payload, raw = _read_progress(attempt)
    assert payload["activity"] == public_progress.SAFE_FALLBACK_TEXT
    assert "hidden-direction" not in raw


def test_sanitizer_failure_fails_closed_to_fixed_text(attempt, monkeypatch):
    def fail(_value: str, _limit: int) -> str:
        raise RuntimeError("SANITIZER_FAILURE_PRIVATE_CANARY")

    monkeypatch.setattr(public_progress, "safe_display", fail)
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    writer.interim("PRIVATE_ASSISTANT_TEXT_CANARY")
    writer.flush()

    payload, raw = _read_progress(attempt)
    assert payload["activity"] == public_progress.SAFE_FALLBACK_TEXT
    assert "PRIVATE_ASSISTANT_TEXT_CANARY" not in raw
    assert "SANITIZER_FAILURE_PRIVATE_CANARY" not in raw


def test_tool_activity_humanizes_name_and_discards_all_arguments(attempt, monkeypatch):
    monkeypatch.setattr(public_progress, "safe_display", lambda value, limit: value[:limit])
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    writer.tool_start("read_file", {"path": "C:/private/customer-record.json"}, "ARGUMENT_CANARY")
    writer.flush()

    payload, raw = _read_progress(attempt)
    assert payload["activity"] == "Read File 실행 중"
    assert "customer-record" not in raw
    assert "ARGUMENT_CANARY" not in raw

    writer.tool_start("../../private\u202e", {"secret": "OTHER_ARGUMENT_CANARY"})
    writer.flush()
    payload, raw = _read_progress(attempt)
    assert payload["activity"] == "도구 실행 중"
    assert "OTHER_ARGUMENT_CANARY" not in raw


def test_rate_limited_updates_coalesce_and_flush_latest_atomically(attempt, monkeypatch):
    now = [0.0]
    replacements: list[tuple[str, str]] = []
    sleep_calls: list[float] = []
    real_replace = os.replace
    monkeypatch.setattr(public_progress.time, "monotonic", lambda: now[0])

    def advance(seconds: float) -> None:
        sleep_calls.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(public_progress.time, "sleep", advance)

    def track_replace(source: Any, destination: Any) -> None:
        replacements.append((str(source), str(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(public_progress.os, "replace", track_replace)
    monkeypatch.setattr(public_progress, "safe_display", lambda value, limit: value[:limit])
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    assert len(replacements) == 1

    now[0] = 0.05
    writer.interim("superseded interim")
    writer.tool_start("read_file", {"path": "not displayed"})
    assert len(replacements) == 1

    now[0] = 0.05
    writer.flush()
    assert sleep_calls == pytest.approx([public_progress.MIN_WRITE_INTERVAL_SECONDS - 0.05])
    assert len(replacements) == 2
    payload, _raw = _read_progress(attempt)
    assert payload["activity"] == "Read File 실행 중"
    assert sorted(path.name for path in attempt["attempt_dir"].iterdir()) == [
        "attempt-request.json",
        "public-progress.json",
    ]


def test_pending_activity_flushes_latest_on_daemon_timer(attempt, monkeypatch):
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    committed = Event()
    original_commit = writer._commit

    def track_commit(activity: str, **kwargs: Any) -> None:
        original_commit(activity, **kwargs)
        if activity != public_progress.WAITING_ACTIVITY:
            committed.set()

    monkeypatch.setattr(writer, "_commit", track_commit)
    # Keep the first update inside the throttle window deterministically.
    writer._last_write_at = public_progress.time.monotonic() + 0.1
    started = public_progress.time.perf_counter()
    writer.interim("superseded interim")
    writer.tool_start("read_file", {"path": "PRIVATE_PATH_CANARY"}, "TOOL_ARGS_CANARY")
    scheduled = writer._timer

    assert scheduled is not None
    assert scheduled.daemon is True
    assert committed.wait(timeout=0.95)
    assert public_progress.time.perf_counter() - started < 1.0
    payload, raw = _read_progress(attempt)
    assert payload["activity"] == "Read File 실행 중"
    assert "PRIVATE_PATH_CANARY" not in raw
    assert "TOOL_ARGS_CANARY" not in raw
    writer.close()


def test_close_flushes_pending_and_invalidates_dispatched_timer(attempt, monkeypatch):
    timers: list[Any] = []

    class ManualTimer:
        def __init__(self, interval: float, function: Any, args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None):
            self.interval = interval
            self.function = function
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = False
            self.started = False
            self.cancelled = False
            timers.append(self)

        def start(self) -> None:
            self.started = True

        def cancel(self) -> None:
            self.cancelled = True

    monkeypatch.setattr(public_progress, "Timer", ManualTimer)
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    writer._last_write_at = public_progress.time.monotonic() + 0.1
    writer.interim("final coalesced activity")
    timer = writer._timer
    assert timer is not None and timer.started

    writes: list[tuple[str, str]] = []
    real_replace = os.replace

    def track_replace(source: Any, destination: Any) -> None:
        writes.append((str(source), str(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(public_progress.os, "replace", track_replace)
    callback_entered = Event()

    def invoke_dispatched_timer() -> None:
        callback_entered.set()
        timer.function(*timer.args, **timer.kwargs)

    writer._lock.acquire()
    callback = Thread(target=invoke_dispatched_timer, daemon=True)
    callback.start()
    try:
        assert callback_entered.wait(timeout=1.0)
        # A callback already dispatched but waiting on the lock must become stale.
        writer.close()
    finally:
        writer._lock.release()
    callback.join(timeout=1.0)

    assert not callback.is_alive()
    assert timer.cancelled
    payload, raw = _read_progress(attempt)
    assert payload["activity"] == "응답: final coalesced activity"
    assert len(writes) == 1

    timer.function(*timer.args, **timer.kwargs)
    writer.interim("post-close activity")
    assert attempt["progress_path"].read_text(encoding="utf-8") == raw
    assert len(writes) == 1


def test_trailing_timer_io_failure_is_nonfatal_and_clears_pending(attempt, monkeypatch):
    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    failed = Event()
    original_commit = writer._commit

    def track_commit(activity: str, **kwargs: Any) -> None:
        original_commit(activity, **kwargs)
        if activity != public_progress.WAITING_ACTIVITY:
            failed.set()

    def fail_replace(_source: Any, _destination: Any) -> None:
        raise OSError("WRITER_IO_PRIVATE_CANARY")

    monkeypatch.setattr(writer, "_commit", track_commit)
    monkeypatch.setattr(public_progress.os, "replace", fail_replace)
    writer._last_write_at = public_progress.time.monotonic() + 0.1
    writer.interim("safe trailing activity")

    assert failed.wait(timeout=0.95)
    assert writer._disabled is True
    assert writer._pending_activity is None
    assert "WRITER_IO_PRIVATE_CANARY" not in attempt["progress_path"].read_text(encoding="utf-8")
    writer.close()


def test_constructor_rejects_foreign_and_symlinked_request_paths(attempt, tmp_path):
    foreign = tmp_path / "attempt-request.json"
    foreign.write_text(json.dumps(attempt["request"]), encoding="utf-8")
    with pytest.raises(ValueError, match="validated attempt request"):
        public_progress.PublicProgress(attempt["request"], foreign)
    assert not (tmp_path / "public-progress.json").exists()

    outside = attempt["base"] / "outside-request.json"
    outside.write_text(json.dumps(attempt["request"]), encoding="utf-8")
    attempt["request_path"].unlink()
    try:
        attempt["request_path"].symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable in this test environment: {exc}")
    with pytest.raises(ValueError, match="validated attempt request"):
        public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    assert not attempt["progress_path"].exists()


def test_symlinked_progress_target_is_never_followed(attempt):
    outside = attempt["base"] / "outside-progress.json"
    outside.write_text("DO_NOT_OVERWRITE", encoding="utf-8")
    try:
        attempt["progress_path"].symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable in this test environment: {exc}")

    writer = public_progress.PublicProgress(attempt["request"], attempt["request_path"])
    writer.interim("PUBLIC_TEXT_CANARY")
    writer.flush()

    assert attempt["progress_path"].is_symlink()
    assert outside.read_text(encoding="utf-8") == "DO_NOT_OVERWRITE"
