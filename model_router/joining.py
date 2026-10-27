"""Owned same-turn joins: no notifier, native consumption or observation marks."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
from typing import Any, cast

from .runtime_tracking import SESSION_TOKEN

PROCESS_TOKEN = re.compile(r"proc_[A-Za-z0-9_-]{1,120}\Z")


class JoinError(ValueError):
    """A job cannot be safely joined by this caller."""


def owner_binding(runtime: Any, profile: str, home: Path) -> dict[str, Any]:
    if runtime is None:
        raise JoinError("join requires a bound current-session runtime")
    parent = getattr(runtime, 'parent_session_id', None)
    key = getattr(runtime, 'session_key', None)
    owner = getattr(runtime, 'task_id', None)
    if (not isinstance(parent, str) or SESSION_TOKEN.fullmatch(parent) is None
            or not isinstance(key, str) or not 0 < len(key) <= 512
            or not isinstance(owner, str) or not 0 < len(owner) <= 128
            or any(ord(c) < 32 for c in key + owner)):
        raise JoinError("join requires exact parent, session key and task ownership")
    registry = getattr(runtime, 'registry', None)
    if not callable(getattr(registry, 'get', None)):
        raise JoinError("native owned join tracking is unavailable")
    return dict(schema=1, profile=profile, home=str(home.resolve()),
                parent_session_id=parent, session_key=key, owner_task_id=owner)


def read_record(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise JoinError("join record must not be a symlink")
    try:
        with path.open('rb') as handle:
            raw = handle.read(262145)
        if len(raw) > 262144:
            raise JoinError("join record exceeds its supported size")
        value = json.loads(raw)
    except (OSError, UnicodeError, ValueError):
        raise JoinError("join ownership or launch record is unavailable") from None
    if not isinstance(value, dict):
        raise JoinError("join record is not an object")
    return value


def _incarnation(process_id: Any, worker_pid: Any, started_at: Any) -> None:
    if (not isinstance(process_id, str) or PROCESS_TOKEN.fullmatch(process_id) is None
            or type(worker_pid) is not int or worker_pid <= 0
            or type(started_at) not in (float, int)):
        raise JoinError("join requires an exact native process incarnation")
    try:
        valid_start = math.isfinite(started_at) and started_at > 0
    except (OverflowError, ValueError):
        valid_start = False
    if not valid_start:
        raise JoinError("join native process start time is invalid")


def owned_process(runtime: Any, owner: dict[str, Any], process_id: Any,
                  worker_pid: Any, started_at: Any):
    _incarnation(process_id, worker_pid, started_at)
    session = runtime.registry.get(process_id)
    if session is None:
        return None
    if (getattr(session, 'id', None) != process_id
            or type(getattr(session, 'pid', None)) is not int or session.pid != worker_pid
            or type(getattr(session, 'started_at', None)) not in (float, int)
            or session.started_at != started_at
            or getattr(session, 'parent_session_id', None) != owner['parent_session_id']
            or getattr(session, 'session_key', None) != owner['session_key']
            or getattr(session, 'owner_task_id', None) != owner['owner_task_id']
            or getattr(session, 'task_id', None) != owner['owner_task_id']
            or getattr(session, 'notify_on_complete', None) is not False):
        raise JoinError("native process no longer matches the silent job owner/incarnation")
    return session


def capture_process_start(runtime: Any, owner: dict[str, Any], process_id: str, worker_pid: int) -> float:
    session = runtime.registry.get(process_id)
    if session is None:
        raise JoinError("native join tracking is unavailable after adoption")
    started_at = getattr(session, 'started_at', None)
    if owned_process(runtime, owner, process_id, worker_pid, started_at) is None:
        raise JoinError("native join tracking disappeared after adoption")
    return cast(float, started_at)


def _interrupted() -> bool:
    from tools.interrupt import consume_yield, is_interrupted
    return bool(is_interrupted() or consume_yield(threading.current_thread().ident))


def validate_wait_timeout(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise JoinError("wait_timeout must be a positive integer number of seconds")
    try:
        seconds = float(value)
    except OverflowError:
        raise JoinError("wait_timeout is outside the supported numeric range") from None
    if not math.isfinite(seconds):
        raise JoinError("wait_timeout is outside the supported numeric range")
    return seconds


def effective_wait_window(requested: int | None) -> float:
    """Support native sequential-barrier dispatch, not custom concurrent batches.

    This bounds local waiting, not arbitrary upstream middleware delays. Native
    executor cancellation remains authoritative. Never change the job deadline.
    """
    from agent.tool_dispatch_helpers import _batch_admission
    descriptor = SimpleNamespace(function=SimpleNamespace(name='coding_route', arguments='{"action":"join"}'))
    if _batch_admission(descriptor, None) is not None:
        raise JoinError("join requires native sequential-barrier dispatch")
    desired = validate_wait_timeout(requested)
    try:
        native_window = int(os.getenv('TERMINAL_TIMEOUT', '180'))
    except ValueError:
        native_window = 180  # The same invalid-value behavior as native wait.
    if native_window <= 0:
        raise JoinError("native wait window must be positive")
    from agent.tool_executor import _resolve_concurrent_tool_timeout, _resolve_sequential_tool_timeout
    windows = [float(native_window)]
    if desired is not None:
        windows.append(desired)
    for limit in (_resolve_concurrent_tool_timeout(), _resolve_sequential_tool_timeout()):
        if limit is not None:
            if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
                raise JoinError("native executor wait budget is unavailable")
            windows.append(limit * 0.8)  # Leave time for dispatch/result serialization.
    return min(windows)


def native_outcome(session: Any) -> dict[str, Any]:
    code = getattr(session, 'exit_code', None)
    reason = getattr(session, 'completion_reason', None)
    return {'native_exit_code': code if type(code) is int else None,
            'native_completion_reason': reason if isinstance(reason, str) and reason in
            {'exited','killed','timeout'} else 'unknown'}


def _pause(seconds: float) -> None:
    threading.Event().wait(seconds)


def wait_owned(runtime: Any, owner: dict[str, Any], launch: dict[str, Any], *,
               wait_timeout: int | None = None, entered_at: float | None = None) -> dict[str, Any]:
    window = effective_wait_window(wait_timeout)
    deadline = (time.monotonic() if entered_at is None else entered_at) + window
    process_id, pid, started = (launch.get(k) for k in ('process_id','worker_pid','process_started_at'))
    _incarnation(process_id, pid, started)
    while True:
        try:
            session = owned_process(runtime, owner, process_id, pid, started)
        except JoinError:
            raise
        except Exception as exc:
            return {'join_status':'unavailable', 'native_status':'error', 'result_collected':False,
                    'error_type':type(exc).__name__}
        if session is None:
            return {'join_status':'unavailable', 'native_status':'not_found', 'result_collected':False}
        if _interrupted():
            return {'join_status':'interrupted', 'native_status':'interrupted', 'result_collected':False}
        if getattr(session, 'exited', None) is True:
            return {'join_status':'joined', 'native_status':'exited', 'result_collected':True,
                    'native_consumption':'not_requested', **native_outcome(session)}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {'join_status':'pending', 'native_status':'running', 'result_collected':False,
                    'wait_window_seconds':window}
        # Only the caller sleeps. No acknowledgement, observation marks, private
        # locks, process control, background thread or notification queue.
        _pause(min(0.2, remaining))


def reconcile_terminal(runtime: Any, owner: dict[str, Any], launch: dict[str, Any],
                       prior: dict[str, Any]) -> dict[str, Any]:
    """Recheck CURRENT owner/termination after artifacts, not immutable future fate."""
    session = owned_process(runtime, owner, launch.get('process_id'), launch.get('worker_pid'),
                            launch.get('process_started_at'))
    if session is None or getattr(session, 'exited', None) is not True:
        return {'join_status':'unavailable', 'native_status':'not_found', 'result_collected':False}
    if _interrupted():
        return {'join_status':'interrupted', 'native_status':'interrupted', 'result_collected':False}
    current = native_outcome(session)
    changed = any(prior.get(k) != v for k,v in current.items())
    return {**prior, **current, 'native_snapshot_changed':changed}
