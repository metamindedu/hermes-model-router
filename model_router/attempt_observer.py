"""Fail-closed, per-attempt observer for Hermes lifecycle hooks.

Only scalar route identity is retained. Prompts, tool arguments, request bodies,
responses, errors, secrets, and endpoints are never copied to observer state.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_EVENTS = frozenset({"pre_api_request", "post_api_request", "api_request_error"})
TOOL_EVENTS = frozenset({"pre_tool_call", "post_tool_call"})
_ALLOWED_EVENTS = API_EVENTS | TOOL_EVENTS
_PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


@dataclass
class _State:
    request_path: Path
    identity: tuple[str, str, str, str, str]
    route: dict[str, str]
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    routes: list[dict[str, Any]] = field(default_factory=list)
    tool_seen: bool = False
    partial_output: bool = False
    invalid: bool = False
    exhaustion_confirmed: bool = False
    last_api_outcome: str | None = None
    api_count: int = 0


_lock = threading.RLock()
_state: _State | None = None


def _canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _safe_text(value: Any, *, maximum: int = 300) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if value != value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value


def _no_symlink_component(path: Path, stop: Path) -> bool:
    """Reject linked artifact components from *path* up to and including *stop*."""
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


def _load_verified_state() -> _State | None:
    """Verify the environment-bound request and artifact path; return None on any ambiguity."""
    global _state
    raw = os.environ.get("MODEL_ROUTER_ATTEMPT_REQUEST")
    if not raw:
        return None
    try:
        request_path = Path(raw).expanduser()
        if not request_path.is_absolute() or request_path.name != "attempt-request.json":
            return None
        home_text = _safe_text(os.environ.get("HERMES_HOME"), maximum=4096)
        profile = _safe_text(os.environ.get("HERMES_PROFILE"), maximum=64)
        if not home_text or not profile or _PROFILE_RE.fullmatch(profile) is None:
            return None
        home = Path(home_text).resolve(strict=True)
        request_path = request_path.resolve(strict=True)
        data = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {
            "schema", "attempt_id", "job_id", "profile", "home", "cwd", "source",
            "task_id", "session_id", "parent_session_id", "route", "toolsets",
            "prompt", "budget_seconds",
        }:
            return None
        if (
            data.get("schema") != 1
            or isinstance(data.get("schema"), bool)
            or not _canonical_uuid(data.get("attempt_id"))
            or not _canonical_uuid(data.get("job_id"))
            or data.get("profile") != profile
            or Path(str(data.get("home", ""))).expanduser().resolve(strict=True) != home
            or _safe_text(data.get("task_id"), maximum=128) is None
            or _safe_text(data.get("session_id"), maximum=128) is None
        ):
            return None
        route = data.get("route")
        if not isinstance(route, dict) or set(route) != {"provider", "model", "reasoning"}:
            return None
        provider = _safe_text(route.get("provider"))
        model = _safe_text(route.get("model"))
        reasoning = _safe_text(route.get("reasoning"), maximum=80)
        if not provider or not model or not reasoning:
            return None
        job_root = home / "plugin-data" / "model-router" / "jobs"
        expected_dir = job_root / data["job_id"] / "attempts" / data["attempt_id"]
        if request_path.parent != expected_dir.resolve(strict=True):
            return None
        if not _no_symlink_component(request_path, home):
            return None
        if (
            os.path.normcase(str(home)) != os.path.normcase(str(Path(home_text).resolve(strict=True)))
            or os.path.normcase(str(Path(os.environ["HERMES_HOME"]).resolve(strict=True)))
            != os.path.normcase(str(home))
        ):
            return None
        identity = (profile, data["job_id"], data["attempt_id"], data["session_id"], data["task_id"])
        with _lock:
            if _state is None or _state.request_path != request_path or _state.identity != identity:
                _state = _State(request_path=request_path, identity=identity,
                                route={"provider": provider, "model": model, "reasoning": reasoning})
            return _state
    except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError, KeyError):
        return None


def _event_identity_matches(state: _State, payload: dict[str, Any]) -> bool:
    session_id = _safe_text(payload.get("session_id"), maximum=128)
    task_id = _safe_text(payload.get("task_id"), maximum=128)
    return session_id == state.identity[3] and task_id == state.identity[4]


def _request_model(payload: dict[str, Any]) -> str | None:
    request = payload.get("request")
    if not isinstance(request, dict):
        return None
    body = request.get("body")
    if not isinstance(body, dict):
        return None
    value = body.get("model")
    return _safe_text(value)


def _api_identity(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    provider = _safe_text(payload.get("provider"))
    model = _safe_text(payload.get("model"))
    api_mode = _safe_text(payload.get("api_mode"), maximum=80)
    if not provider or not model or not api_mode:
        return None
    return provider, model, api_mode


def record_event(event_name: str, **payload: Any) -> None:
    """Record one of the five approved Hermes lifecycle events; always safe to call.

    Unknown events, ordinary payloads, auxiliary traffic, unbound or mismatched
    identities are inert. Payload objects are inspected transiently and never retained.
    """
    if event_name not in _ALLOWED_EVENTS or not isinstance(payload, dict):
        return
    state = _load_verified_state()
    if state is None:
        return
    try:
        if event_name in TOOL_EVENTS:
            if _event_identity_matches(state, payload):
                with _lock:
                    state.tool_seen = True
            return
        # Main-loop API events have no aux_task field; explicitly discard any additive
        # payload that identifies an auxiliary request.
        if payload.get("aux_task"):
            return
        if not _event_identity_matches(state, payload):
            return
        request_id = _safe_text(payload.get("api_request_id"), maximum=128)
        api_identity = _api_identity(payload)
        if request_id is None or api_identity is None:
            with _lock:
                state.invalid = True
            return
        provider, model, api_mode = api_identity
        identity_tuple = (provider, model, api_mode)
        with _lock:
            if event_name == "pre_api_request":
                if request_id in state.pending:
                    state.invalid = True
                    return
                state.pending[request_id] = {
                    "provider": provider,
                    "model": model,
                    "api_mode": api_mode,
                    "request_model": _request_model(payload),
                }
                return
            pending = state.pending.pop(request_id, None)
            if pending is None:
                state.invalid = True
                return
            if (pending["provider"], pending["model"], pending["api_mode"]) != identity_tuple:
                state.invalid = True
                return
            response_model = None
            if event_name == "post_api_request":
                response_model = _safe_text(payload.get("response_model"))
                if response_model is None:
                    response = payload.get("response")
                    if isinstance(response, dict):
                        response_model = _safe_text(response.get("model"))
                if response_model is not None and payload.get("response_model") not in (None, response_model):
                    state.invalid = True
                    return
                if payload.get("assistant_tool_call_count", 0) not in (0, None):
                    count = payload.get("assistant_tool_call_count")
                    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                        state.tool_seen = True
                state.last_api_outcome = "success"
                state.exhaustion_confirmed = False
            else:
                reason = payload.get("reason")
                retryable = payload.get("retryable")
                status = payload.get("status_code")
                state.last_api_outcome = "error"
                # Hermes' structured FailoverReason.billing is the only accepted signal;
                # the assistant's quota wording is never used. Exclude HTTP 400 because
                # Hermes also marks an ambiguous Anthropic content-filter shape as billing.
                state.exhaustion_confirmed = (
                    reason == "billing"
                    and retryable is False
                    and isinstance(status, int)
                    and not isinstance(status, bool)
                    and status in {402, 403, 404, 429}
                )
            record = {
                "provider": pending["provider"],
                "model": pending["model"],
                "api_mode": pending["api_mode"],
                "request_model": pending["request_model"],
                "response_model": response_model,
            }
            state.routes.append(record)
            state.api_count += 1
    except Exception:
        # Hooks are observability only. Preserve the failure for final evidence without
        # surfacing payload or exception text to the caller.
        with _lock:
            state.invalid = True


def mark_tool_seen() -> None:
    """Sticky callback for AIAgent.tool_start_callback; never accepts tool data."""
    state = _load_verified_state()
    if state is not None:
        with _lock:
            state.tool_seen = True


def mark_partial_output() -> None:
    """Sticky callback for non-empty assistant deltas; text is intentionally not accepted."""
    state = _load_verified_state()
    if state is not None:
        with _lock:
            state.partial_output = True


def snapshot() -> dict[str, Any]:
    """Return a copy of the allowlisted per-attempt evidence envelope."""
    state = _load_verified_state()
    if state is None:
        return {
            "tool_seen": False,
            "partial_output": False,
            "evidence_complete": False,
            "observed_routes": [],
            "exhaustion_confirmed": False,
        }
    with _lock:
        complete = bool(state.api_count and not state.pending and not state.invalid)
        return {
            "tool_seen": bool(state.tool_seen),
            "partial_output": bool(state.partial_output),
            "evidence_complete": complete,
            "observed_routes": [dict(route) for route in state.routes],
            "exhaustion_confirmed": bool(
                complete and state.last_api_outcome == "error" and state.exhaustion_confirmed
            ),
        }


def reset_for_tests() -> None:
    """Clear process-local evidence between isolated unit tests."""
    global _state
    with _lock:
        _state = None
