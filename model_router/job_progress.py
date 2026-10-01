"""Bounded public metadata for exactly one profile/durable/runtime parent pair.

This reader never returns prompts, transcripts, result answers, tool arguments or
job logs. ProcessRegistry remains the UI's lifecycle authority. Old/unbound jobs
are not backfilled or guessed from titles. Index entries do not authorize work.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import time
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from . import task_presentation

SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
PROCESS = re.compile(r"proc_[A-Za-z0-9_-]{1,96}\Z")
MAX_ROWS = 16
MAX_INDEX = 512
MAX_PUBLIC_BYTES = 4096


def _session(value):
    if not isinstance(value, str) or SESSION.fullmatch(value) is None:
        raise ValueError("exact parent session identity required")
    return value


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _local(path: Path, parent: Path) -> Path:
    if path.is_symlink() or path.resolve().parent != parent.resolve():
        raise ValueError("progress path escapes its owner")
    return path


def _read(path: Path, parent: Path, maximum: int = MAX_PUBLIC_BYTES):
    try:
        _local(path, parent)
        if path.stat().st_size > maximum:
            return None
        # Bound the read even if a concurrent writer changes the file size.
        with path.open("rb") as handle:
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            return None
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError, RuntimeError):
        return None


def _index_root(home: Path, parent: str, ui: str) -> Path:
    owner = hashlib.sha256(json.dumps([_session(parent), _session(ui)], separators=(",", ":")).encode()).hexdigest()[:32]
    current = home.resolve()
    for part in ("plugin-data", "model-router", "progress-index", owner):
        current = _local(current / part, current)
    return current


def _index_document(target: Path, profile: str, parent: str, ui: str):
    value = _read(target / "index.json", target, 1_048_576)
    if not value or any(value.get(k) != v for k, v in {
        "schema": 1, "profile": profile, "parent_session_id": parent, "ui_session_id": ui,
    }.items()):
        return None
    rows = value.get("jobs")
    if (not isinstance(rows, list) or len(rows) > MAX_INDEX
            or not isinstance(value.get("has_more"), bool)):
        return None
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not _uuid(row.get("job_id"))
                or not isinstance(row.get("process_id"), str)
                or not PROCESS.fullmatch(row["process_id"]) or row["job_id"] in seen):
            return None
        seen.add(row["job_id"])
    return value


def index_job(home: Path, snapshot: dict[str, Any], launch: dict[str, Any]) -> None:
    """Maintain one bounded atomic newest-first index under a process lock.

    Index data is presentation only; a failure never relaunches an adopted job.
    No directory-enumeration slice may permanently exclude newly registered work.
    """
    parent, ui = snapshot.get("parent_session_id"), snapshot.get("ui_session_id")
    if not parent or not ui or not _uuid(snapshot.get("job_id")):
        return
    process_id = launch.get("process_id")
    if not isinstance(process_id, str) or not PROCESS.fullmatch(process_id):
        return
    target = _index_root(home, parent, ui)
    target.mkdir(parents=True, exist_ok=True)
    from .service import _FileLock
    from uuid import uuid4
    final = _local(target / "index.json", target)
    lock = _local(target / ".index.lock", target)
    with _FileLock(lock, timeout=1.0):
        _index_root(home, parent, ui)
        if final.exists():
            prior = _index_document(target, snapshot["profile"], parent, ui)
            if prior is None:
                raise ValueError("progress index is invalid; refusing overwrite")
        else:
            prior = {"jobs": [], "has_more": False}
        rows = [{"job_id": snapshot["job_id"], "process_id": process_id}] + [
            row for row in prior["jobs"] if row["job_id"] != snapshot["job_id"]
        ]
        payload = {
            "schema": 1, "profile": snapshot["profile"],
            "parent_session_id": parent, "ui_session_id": ui,
            "jobs": rows[:MAX_INDEX], "has_more": prior["has_more"] or len(rows) > MAX_INDEX,
        }
        temporary = _local(target / (".t-" + uuid4().hex[:16]), target)
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            _index_root(home, parent, ui)
            _local(final, target)
            os.replace(temporary, final)
        finally:
            temporary.unlink(missing_ok=True)


def _milliseconds(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return int(stamp.timestamp() * 1000)
    except (ValueError, OverflowError, OSError):
        return None


def progress_for_parent(service, body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) != {"parent_session_id", "ui_session_id"}:
        raise ValueError("progress requires exact durable and runtime parent identities")
    parent, ui = _session(body["parent_session_id"]), _session(body["ui_session_id"])
    from .routing import _service_profile, _profile_home, _jobs_root, _pid_alive
    profile = _service_profile(service)
    home = _profile_home(service, profile)
    root = _jobs_root(home)
    index = _index_root(home, parent, ui)
    result = {"schema": 1, "profile": profile, "parent_session_id": parent,
              "ui_session_id": ui, "jobs": [], "has_more": False}
    if not index.is_dir():
        return result
    document = _index_document(index, profile, parent, ui)
    if document is None:
        return result
    entries = document["jobs"]
    result["has_more"] = document["has_more"]
    for binding in entries:
        job_id = binding["job_id"]
        process_id = binding["process_id"]
        try:
            directory = _local(root / job_id, root)
        except (ValueError, OSError, RuntimeError):
            continue
        snapshot = _read(directory / "snapshot.json", directory, 16384)
        launch = _read(directory / "launch.json", directory)
        if not snapshot or not launch or launch.get("process_id") != process_id:
            continue
        if any(snapshot.get(k) != v for k, v in {
            "profile": profile, "parent_session_id": parent,
            "ui_session_id": ui, "job_id": job_id,
        }.items()):
            continue
        state = _read(directory / "state.json", directory) or {}
        started = _milliseconds(state.get("started_at")) or _milliseconds(launch.get("launched_at"))
        if started is None:
            continue
        finished = _milliseconds(state.get("finished_at"))
        if _pid_alive(launch.get("worker_pid")):
            status = "running"
            finished = None
        elif state.get("status") == "failed":
            status = "failed"
        elif state.get("status") == "finished" and state.get("worker_exit_code") == 0 and state.get("runner_exit_code") == 0:
            status = "completed"  # Execution ended; not semantic GO or route identity proof.
        else:
            status = "unverified"
        if status != "running" and finished is not None and finished < time.time() * 1000 - 15000:
            continue
        activity = "응답 대기 중" if status == "running" else "실행 종료 · 결과 확인 필요"
        attempts = directory / "attempts"
        latest = []
        try:
            _local(attempts, directory)
            if attempts.is_dir():
                for attempt in itertools.islice(attempts.iterdir(), 4):
                    if not _uuid(attempt.name):
                        continue
                    _local(attempt, attempts)
                    public = _read(attempt / "public-progress.json", attempt)
                    if not public or any(public.get(k) != v for k, v in {
                        "job_id": job_id, "attempt_id": attempt.name,
                        "profile": profile, "parent_session_id": parent,
                    }.items()):
                        continue
                    # A public progress artifact has no authority over lifecycle/route.
                    updated = public.get("updated_at")
                    if public.get("schema") == 1 and isinstance(updated, (int, float)) and not isinstance(updated, bool) and math.isfinite(updated):
                        latest.append((updated, public.get("activity")))
        except (OSError, ValueError, RuntimeError):
            latest = []
        if latest:
            activity = task_presentation.safe_display(max(latest, key=lambda row: row[0])[1], 180)
        role = snapshot.get("route_class")
        routes = snapshot.get("model_provider_evidence")
        requested = routes.get("requested") if isinstance(routes, dict) else None
        selected = requested.get(role) if isinstance(requested, dict) and isinstance(role, str) else None
        model = selected.get("model") if isinstance(selected, dict) else None
        try:
            title = task_presentation.validate_title(snapshot.get("title"), snapshot.get("purpose", ""))
        except (ValueError, TypeError):
            continue
        result["jobs"].append({
            "job_id": job_id, "process_id": process_id,
            "title": title,
            "role": task_presentation.role_label(role), "model": task_presentation.safe_display(model or "미지정", 128),
            "status": status, "started_at": started, "finished_at": finished,
            "activity": activity,
        })
        if len(result["jobs"]) >= MAX_ROWS:
            result["has_more"] = len(entries) > len(result["jobs"]) or result["has_more"]
            break
    return result
