"""Bounded, fail-closed public activity for one validated routed attempt.

This artifact is intentionally separate from logs and attempt evidence. It stores
only the validated attempt identity and the latest sanitized display activity.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from threading import RLock, Timer
from typing import Any

from .task_presentation import SAFE_FALLBACK_TEXT, safe_display

SCHEMA = 1
MAX_PROGRESS_BYTES = 4096
MAX_INTERIM_INPUT_CHARS = 16_384
MAX_ACTIVITY_CHARS = 1536
MIN_WRITE_INTERVAL_SECONDS = 0.2
WAITING_ACTIVITY = "응답 대기 중"
TOOL_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")


def _has_disallowed_controls(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)


def _no_symlink_component(path: Path, stop: Path) -> bool:
    try:
        relative = path.relative_to(stop)
    except ValueError:
        return False
    current = stop
    if current.is_symlink():
        return False
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _humanize_tool_name(name: Any) -> str:
    """Humanize only a bounded ASCII tool identifier; never inspect its arguments."""
    if not isinstance(name, str) or TOOL_NAME_RE.fullmatch(name) is None:
        return "도구"
    parts = re.split(r"[_.:-]+", name)
    if not parts or any(not part for part in parts):
        return "도구"
    return " ".join(part[:1].upper() + part[1:].lower() for part in parts)


class PublicProgress:
    """Atomically maintain one small public-progress.json for a validated attempt."""

    def __init__(self, request: dict[str, Any], request_path: str | Path):
        # Reuse scoped_agent's complete request/artifact validation. A progress
        # writer cannot be pointed at a caller-selected path or a different job.
        from .scoped_agent import _validate_request

        try:
            bound, fixed_request_path, result_path = _validate_request(request, Path(request_path))
        except Exception as exc:
            raise ValueError("public progress requires a validated attempt request") from exc

        self._home = Path(bound["home"])
        self._request_path = fixed_request_path
        self._attempt_dir = result_path.parent
        self._path = self._attempt_dir / "public-progress.json"
        self._identity = {
            "schema": SCHEMA,
            "job_id": bound["job_id"],
            "attempt_id": bound["attempt_id"],
            "profile": bound["profile"],
            "parent_session_id": bound["parent_session_id"],
            "session_id": bound["session_id"],
        }
        self._lock = RLock()
        self._disabled = False
        self._closed = False
        self._last_write_at: float | None = None
        self._pending_activity: str | None = None
        self._timer: Timer | None = None
        self._timer_generation = 0
        self._write_activity(WAITING_ACTIVITY, force=True)

    @property
    def path(self) -> Path:
        """The fixed attempt-local public progress artifact path."""
        return self._path

    def interim(self, text: Any) -> None:
        """Publish one completed, visible interim assistant message, never deltas."""
        activity = self._sanitize_interim(text)
        self._write_activity(activity)

    def tool_start(self, name: Any, *args: Any, **kwargs: Any) -> None:
        """Publish only a validated, humanized tool name; arguments are discarded."""
        del args, kwargs
        label = _humanize_tool_name(name)
        candidate = f"{label} 실행 중"
        activity = self._safe_display(candidate, MAX_ACTIVITY_CHARS)
        if activity == SAFE_FALLBACK_TEXT:
            activity = SAFE_FALLBACK_TEXT
        self._write_activity(activity)

    def flush(self) -> None:
        """Write the latest coalesced activity without inventing a terminal state."""
        with self._lock:
            self._flush_pending_locked()

    def close(self) -> None:
        """Flush final activity and prevent all later timer or callback writes."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._flush_pending_locked()

    def _remaining_interval(self, now: float) -> float:
        if self._last_write_at is None:
            return 0.0
        elapsed = now - self._last_write_at
        return max(0.0, min(MIN_WRITE_INTERVAL_SECONDS, MIN_WRITE_INTERVAL_SECONDS - elapsed))

    def _cancel_timer_locked(self) -> None:
        self._timer_generation += 1
        timer, self._timer = self._timer, None
        if timer is not None:
            with contextlib.suppress(Exception):
                timer.cancel()

    def _schedule_timer_locked(self, delay: float) -> None:
        if self._disabled or self._closed or self._timer is not None or self._pending_activity is None:
            return
        generation = self._timer_generation + 1
        timer: Timer | None = None
        try:
            timer = Timer(max(0.0, min(MIN_WRITE_INTERVAL_SECONDS, delay)), self._flush_pending, args=(generation,))
            timer.daemon = True
            self._timer = timer
            self._timer_generation = generation
            timer.start()
        except Exception:
            if timer is not None:
                with contextlib.suppress(Exception):
                    timer.cancel()
            self._timer = None
            self._timer_generation = generation + 1
            self._pending_activity = None
            self._disabled = True

    def _flush_pending(self, generation: int) -> None:
        with self._lock:
            if generation != self._timer_generation:
                return
            self._timer = None
            if self._disabled or self._closed or self._pending_activity is None:
                return
            try:
                now = time.monotonic()
            except Exception:
                # The timer has already waited the bounded interval; without a
                # usable clock, do not strand the latest activity indefinitely.
                remaining = 0.0
            else:
                remaining = self._remaining_interval(now)
            if remaining > 0:
                self._schedule_timer_locked(remaining)
                return
            activity = self._pending_activity
            self._pending_activity = None
            self._commit(activity)

    def _flush_pending_locked(self) -> None:
        self._cancel_timer_locked()
        if self._disabled or self._pending_activity is None:
            self._pending_activity = None
            return
        activity = self._pending_activity
        self._pending_activity = None
        if self._last_write_at is not None:
            try:
                remaining = self._remaining_interval(time.monotonic())
                if remaining:
                    time.sleep(remaining)
            except Exception:
                # A failed throttle clock must not lose the final activity or
                # affect the routed attempt; the write itself remains bounded.
                pass
        self._commit(activity)

    def _safe_display(self, text: str, limit: int) -> str:
        try:
            result = safe_display(text, limit)
            if not isinstance(result, str) or _has_disallowed_controls(result):
                return SAFE_FALLBACK_TEXT
            return result[:limit] or SAFE_FALLBACK_TEXT
        except Exception:
            return SAFE_FALLBACK_TEXT

    def _sanitize_interim(self, text: Any) -> str:
        # Reject, rather than truncate, overlong input: sensitive material near a
        # truncation boundary must not be split before Hermes' full-text redactor.
        if not isinstance(text, str) or len(text) > MAX_INTERIM_INPUT_CHARS:
            return SAFE_FALLBACK_TEXT
        # This includes C0/C1 controls, bidi/format characters, and surrogates.
        # Fail closed for the whole message instead of trying to repair its meaning.
        if _has_disallowed_controls(text):
            return SAFE_FALLBACK_TEXT
        cleaned = self._safe_display(text, MAX_ACTIVITY_CHARS - len("응답: "))
        if cleaned == SAFE_FALLBACK_TEXT:
            return SAFE_FALLBACK_TEXT
        activity = f"응답: {cleaned}"
        if _has_disallowed_controls(activity):
            return SAFE_FALLBACK_TEXT
        return activity[:MAX_ACTIVITY_CHARS]

    def _write_activity(self, activity: str, *, force: bool = False) -> None:
        with self._lock:
            if self._disabled or self._closed:
                return
            safe_activity = activity if isinstance(activity, str) else SAFE_FALLBACK_TEXT
            if _has_disallowed_controls(safe_activity):
                safe_activity = SAFE_FALLBACK_TEXT
            safe_activity = safe_activity[:MAX_ACTIVITY_CHARS] or SAFE_FALLBACK_TEXT
            try:
                now = time.monotonic()
            except Exception:
                now = 0.0
            if (
                not force
                and self._last_write_at is not None
                and now - self._last_write_at < MIN_WRITE_INTERVAL_SECONDS
            ):
                self._pending_activity = safe_activity
                self._schedule_timer_locked(self._remaining_interval(now))
                return
            self._pending_activity = None
            self._cancel_timer_locked()
            self._commit(safe_activity, monotonic_now=now)

    def _directory_is_bound(self) -> bool:
        if not _no_symlink_component(self._attempt_dir, self._home):
            return False
        if self._attempt_dir.resolve(strict=True) != self._request_path.parent:
            return False
        if self._request_path.is_symlink() or not self._request_path.is_file():
            return False
        if self._path.is_symlink():
            return False
        return True

    def _commit(self, activity: str, *, monotonic_now: float | None = None) -> None:
        if self._disabled:
            return
        temporary: Path | None = None
        try:
            if not self._directory_is_bound():
                self._disabled = True
                return
            updated_at = time.time() * 1000.0
            if not math.isfinite(updated_at):
                updated_at = 0.0
            payload = {
                **self._identity,
                "activity": activity,
                "updated_at": updated_at,
            }
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) + 1 > MAX_PROGRESS_BYTES:
                payload["activity"] = SAFE_FALLBACK_TEXT
                encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) + 1 > MAX_PROGRESS_BYTES:
                self._disabled = True
                return

            temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.write(b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            # Recheck immediately before replacement. os.replace replaces a
            # symlink at the leaf; it does not follow it, and parents are bound.
            if not self._directory_is_bound():
                self._disabled = True
                return
            os.replace(temporary, self._path)
            self._last_write_at = time.monotonic() if monotonic_now is None else monotonic_now
        except Exception:
            # Progress is observational only: filesystem/sanitizer failures must
            # never affect the model call or attempt evidence.
            self._disabled = True
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink()
