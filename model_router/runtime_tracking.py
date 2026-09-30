"""Connect a real routed Popen to Hermes' native background process tracker.

No delegate records/events are forged, no extra monitor process is spawned, and
no model config or notification-delivery contract changes. The worker still owns
its file-backed log and evidence; native adoption merely waits on that Popen.
"""
from __future__ import annotations

from contextvars import copy_context
from dataclasses import dataclass
import os
import re
from typing import Any, Callable

SESSION_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class DesktopSeedUnavailable(RuntimeError):
    """Adoption succeeded, but native UI seeding failed (never relaunch)."""
    def __init__(self, process_id: str):
        super().__init__("native desktop process seed unavailable")
        self.process_id = process_id


@dataclass(frozen=True)
class RouteRuntime:
    parent_session_id: str
    session_key: str
    task_id: str
    registry: Any
    emit: Callable

    def track(self, process, *, job_id: str, purpose: str, cwd: str) -> str:
        session = self.registry.adopt_local(
            process,
            command=f"model-router {purpose} ({job_id})",
            cwd=cwd,
            task_id=self.task_id,
            owner_task_id=self.task_id,
            session_key=self.session_key,
            # Keep coding_route's existing bounded status/result contract. Do not
            # inject a second completion model turn or forward private job logs.
            notify_on_complete=False,
        )
        # coding_route is not terminal: core's tool.complete handler does not
        # seed process.list for it. This native desktop-tool bridge seeds the
        # existing background rail; thereafter core's normal 5s reconciliation
        # and stop controls own it. Failure to paint cannot undo a launched job.
        try:
            seeded = self.emit("status.update", {"kind": "process", "process_id": session.id})
        except Exception:
            raise DesktopSeedUnavailable(session.id) from None
        if seeded is not True:
            raise DesktopSeedUnavailable(session.id)
        return session.id


def capture_runtime(*, task_id: str = "", expected_profile: str = "", get_env=None, registry=None, emit=None):
    """Use bound ContextVars, not stale process-global chat identity.

    A standalone CLI without a task binding stays unbound. Missing bindings in
    a session-serving process fail before spawn. get_env is an offline test seam.
    """
    if get_env is None:
        from gateway.session_context import session_context_engaged
        values = {var.name: value for var, value in copy_context().items()
                  if var.name.startswith("HERMES_SESSION_") or var.name == "HERMES_UI_SESSION_ID"}
        get_env = lambda name, default="": values.get(name, default) if isinstance(values.get(name, default), str) else default
        if not get_env("HERMES_SESSION_ID"):
            desktop_hint = os.environ.get("HERMES_UI_SESSION_ID") or os.environ.get("HERMES_SESSION_PLATFORM") == "desktop"
            if session_context_engaged() or desktop_hint:
                raise ValueError("routing requires a bound current-session context")
            return None
    parent = get_env("HERMES_SESSION_ID", "")
    key = get_env("HERMES_SESSION_KEY", "")
    platform = get_env("HERMES_SESSION_PLATFORM", "") or get_env("HERMES_SESSION_SOURCE", "")
    ui_session = get_env("HERMES_UI_SESSION_ID", "")
    profile = get_env("HERMES_SESSION_PROFILE", "")
    if ui_session or platform == "desktop":
        if not parent or not key or not profile or not ui_session:
            raise ValueError("incomplete desktop routing context")
    if not parent:
        if key:
            raise ValueError("incomplete routing parent context")
        return None
    if expected_profile and profile != expected_profile:
        raise ValueError("routing profile does not match current-session context")
    if not isinstance(parent, str) or SESSION_TOKEN.fullmatch(parent) is None:
        raise ValueError("invalid host parent session identity")
    key = key or parent
    if not isinstance(key, str) or not key or len(key) > 512 or any(ord(c) < 32 for c in key):
        raise ValueError("invalid host session key")
    owner = task_id or parent
    if not isinstance(owner, str) or not owner or len(owner) > 128 or any(ord(c) < 32 for c in owner):
        raise ValueError("invalid host task identity")
    if registry is None:
        from tools.process_registry import process_registry
        registry = process_registry
    if not callable(getattr(registry, "adopt_local", None)):
        raise RuntimeError("Hermes background process adoption is unavailable")
    if emit is None:
        from tools.desktop_ui import emit
    return RouteRuntime(parent, key, owner, registry, emit)
