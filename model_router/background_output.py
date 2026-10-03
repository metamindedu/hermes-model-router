"""Observational, bounded public activity in an already adopted native task.

Never owns/reaps/kills the worker. Native ProcessRegistry is the sole lifecycle
source. No new UI, global lookup, raw logs, transcripts or answer bodies.
"""
from __future__ import annotations

from contextvars import copy_context
import json
import math
from pathlib import Path
from threading import Thread
import time
from uuid import UUID

from .task_presentation import safe_display

POLL_SECONDS = 0.5
MAX_PUBLIC_BYTES = 4096
MAX_REQUEST_BYTES = 524288
MAX_ACTIVITY_CHARS = 400
MAX_LINES = 256
MAX_OUTPUT_CHARS = 64000


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _bound(path: Path, home: Path):
    relative = path.relative_to(home)
    current = home
    if home.is_symlink() or home.resolve(strict=True) != home:
        raise ValueError("unsafe background output home")
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or current.resolve().parent != current.parent:
            raise ValueError("unsafe background output path")
    return path


def _read(path: Path, home: Path, maximum: int):
    try:
        _bound(path, home)
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, RuntimeError):
        return None


def elapsed(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


class BackgroundOutput:
    """A task-bound observer; all dependencies can be exercised without a model."""

    def __init__(self, *, session, registry, process, home, job_id, profile,
                 parent_session_id, session_key, owner_task_id, ui_session_id,
                 emit, timeout, clock=time.time, monotonic=time.monotonic):
        self.home = Path(home)
        if not self.home.is_absolute() or not _uuid(job_id):
            raise ValueError("exact background job binding required")
        _bound(self.home, self.home)
        self.directory = _bound(self.home / "plugin-data/model-router/jobs" / job_id, self.home)
        self.identity = {"job_id": job_id, "profile": profile,
                         "parent_session_id": parent_session_id, "ui_session_id": ui_session_id}
        self.session, self.registry, self.process = session, registry, process
        self.process_id = session.id
        self.session_key, self.owner_task_id = session_key, owner_task_id
        self.emit, self.clock, self.monotonic = emit, clock, monotonic
        if not _number(timeout) or timeout < 0:
            raise ValueError("bounded background observation required")
        self.deadline = monotonic() + timeout + 30 if timeout > 0 else None
        self.started = session.started_at
        if not _number(self.started) or self.started <= 0 or not self._owned():
            raise ValueError("native background owner mismatch")
        self.last = {}
        self.lines = 0
        self.characters = 0
        self.omitted = False
        self.closed = False
        snapshot = _read(self.directory / "snapshot.json", self.home, 16384)
        if not snapshot or any(snapshot.get(k) != v for k, v in self.identity.items()):
            raise ValueError("background snapshot owner mismatch")

    def _owned(self):
        return (self.registry.get(self.process_id) is self.session
                and self.session.process is self.process
                and self.session.pid == self.process.pid
                and self.session.session_key == self.session_key
                and self.session.owner_task_id == self.owner_task_id
                and self.session.parent_session_id == self.identity["parent_session_id"])

    def _notify(self):
        try:
            # The thread runs under the spawning ContextVars. No global/current
            # foreground session fallback and no fabricated delegate event.
            self.emit("status.update", {"kind": "process", "process_id": self.process_id})
        except Exception:
            pass  # Native poll still reconciles this real process and its output.

    def _append(self, text, *, final=False):
        if not self._owned():
            self.closed = True
            return False
        if not final and (self.lines >= MAX_LINES or self.characters + len(text) > MAX_OUTPUT_CHARS):
            if not self.omitted:
                self.omitted = True
                self.session.append_output("활동 기록 한도에 도달했습니다. 종료 요약은 별도로 표시합니다.\n")
                self._notify()
            return False
        self.session.append_output(text)
        # Use the registry's existing native output sink as well as its snapshot.
        # A native Stop dismisses the Background row, so snapshot-only refreshes
        # no longer update an already-open read-only terminal after cancellation.
        # This is the same real session/output as the buffer, not a delegate event.
        sink = getattr(self.registry, "on_output", None)
        if callable(sink) and self._owned():
            try:
                sink(self.session, text)
            except Exception:
                pass
        self.lines += 1
        self.characters += len(text)
        self._notify()
        return True

    def _activities(self):
        # launch.json is written AFTER adoption. Until exact readback exists,
        # wait; do not infer bindings from nearby job names or process IDs.
        launch = _read(self.directory / "launch.json", self.home, 4096)
        if not launch or launch.get("process_id") != self.process_id or launch.get("worker_pid") != self.process.pid:
            return []
        snapshot = _read(self.directory / "snapshot.json", self.home, 16384)
        if not snapshot or any(snapshot.get(k) != v for k, v in self.identity.items()):
            return []
        attempts = self.directory / "attempts"
        try:
            _bound(attempts, self.home)
            entries = []
            # Router allows primary + at most one approved fallback. Refuse an
            # unexpected directory set rather than select a guessed latest job.
            for entry in attempts.iterdir():
                if len(entries) == 2 or not _uuid(entry.name):
                    return []
                _bound(entry, self.home)
                entries.append(entry)
        except (OSError, ValueError, RuntimeError):
            return []
        values = []
        for entry in entries:
            value = _read(entry / "public-progress.json", self.home, MAX_PUBLIC_BYTES)
            if not value or set(value) != {"schema", "job_id", "attempt_id", "profile", "parent_session_id", "session_id", "activity", "updated_at"}:
                continue
            if (type(value.get("schema")) is not int or value["schema"] != 1
                    or value.get("attempt_id") != entry.name or not _uuid(value.get("session_id"))
                    or any(value.get(k) != v for k, v in self.identity.items() if k != "ui_session_id")):
                continue
            request = _read(entry / "attempt-request.json", self.home, MAX_REQUEST_BYTES)
            # Only the identity projection is used. No prompt/route/error/answer
            # string from request/evidence can enter the native output.
            if not request or any(request.get(k) != value[k] for k in ("job_id", "attempt_id", "profile", "parent_session_id", "session_id")):
                continue
            if request.get("source") != "subagent" or not isinstance(request.get("home"), str):
                continue
            try:
                if Path(request["home"]).resolve(strict=True) != self.home:
                    continue
            except (OSError, ValueError, RuntimeError):
                continue
            stamp = value.get("updated_at")
            activity = value.get("activity")
            if not _number(stamp) or not self.started - 5 <= stamp / 1000 <= self.clock() + 5:
                continue
            if not isinstance(activity, str) or len(activity) > 1536:
                continue
            # Redact the WHOLE activity before truncation; revalidate controls at
            # the last public-output boundary even though the writer sanitizes.
            text = safe_display(activity, MAX_ACTIVITY_CHARS)
            values.append((stamp, entry.name, text))
        return sorted(values)

    def _flush_activities(self):
        for stamp, attempt, text in self._activities():
            previous = self.last.get(attempt)
            if previous and (stamp <= previous[0] or text == previous[1]):
                continue
            self.last[attempt] = (stamp, text)
            self._append(f"[{elapsed(stamp / 1000 - self.started)}] {text}\n")

    def tick(self):
        if self.closed:
            return False
        if not self._owned():
            self.closed = True
            return False
        self._flush_activities()
        if self.session.exited:
            # Exit metadata is NOT immutable: native kill can correct a reader's
            # exit reason later. Report only the stable exit observation, never
            # freeze a guessed success/failure/stop verdict or overwrite receipts.
            # Re-read AFTER observing exit to include a last writer flush that
            # raced the ordinary poll above.
            self._flush_activities()
            ended = self.session.exited_at
            if not _number(ended) or ended < self.started:
                ended = self.clock()
            total = elapsed(ended - self.started)
            self._append(f"[{total}] 프로세스 종료를 확인했습니다.\n종료 확인 시 소요 시간: {total}\n종료 종류: Background의 현재 상태를 확인하세요.\n작업 결과: 별도 결과 확인 (실행 종료는 검수 통과를 뜻하지 않습니다.)\n", final=True)
            self.closed = True
            return False
        if self.deadline is not None and self.monotonic() >= self.deadline:
            self._append("활동 관찰 시간이 끝났습니다. 실제 실행 상태는 Background에서 확인하세요.\n", final=True)
            self.closed = True
            return False
        return True

    def run(self):
        try:
            while self.tick():
                time.sleep(POLL_SECONDS)
        except Exception:
            # Observation cannot affect worker execution or leak exception text.
            if not self.closed:
                try:
                    self._append("활동 기록을 더 이상 확인할 수 없습니다. 실제 실행 상태는 Background에서 확인하세요.\n", final=True)
                except Exception:
                    pass
            self.closed = True


def start_background_output(**kwargs):
    observer = BackgroundOutput(**kwargs)
    context = copy_context()
    thread = Thread(target=context.run, args=(observer.run,),
                    name=f"routed-output-{observer.process_id}", daemon=True)
    thread.start()
    return thread
