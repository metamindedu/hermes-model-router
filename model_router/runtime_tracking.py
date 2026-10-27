"""Connect routed Popen jobs to native Background and Desktop completion wakes.

No delegate records/events are forged. The real worker owns its file-backed
result/state before exit; native adoption owns completion delivery. Bound
Desktop and validated default local turns opt in; other surfaces retain their contract.
"""
from __future__ import annotations

from contextlib import contextmanager
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
    ui_session_id: str = ""
    local_completion_wake: bool = False

    def track(
        self,
        process,
        *,
        job_id: str,
        purpose: str,
        cwd: str,
        title: str | None = None,
        role: str | None = None,
        model: str = "미지정",
        provider: str = "미지정",
        profile: str = "default",
        reasoning: str | None = None,
        completion_mode: str = "notify",
    ) -> str:
        from . import task_presentation

        if completion_mode not in ("notify", "join"):
            raise ValueError("completion_mode must be notify or join")
        display_title = task_presentation.validate_title(title, purpose)
        display_role = role or task_presentation.default_role(purpose)
        command = task_presentation.native_command(display_title, display_role, model, purpose)
        cwd_basename = os.path.basename(os.path.normpath(cwd)) if isinstance(cwd, str) else "미지정"
        seed = task_presentation.terminal_seed(
            title=display_title,
            purpose=purpose,
            role=display_role,
            model=model,
            provider=provider,
            profile=profile,
            job_id=job_id,
            cwd_basename=cwd_basename,
            reasoning=reasoning,
        )
        # Seed via the native API BEFORE its reader starts. A very fast exit
        # must still carry the exact job ID, never private worker stdout.
        session = self.registry.adopt_local(
            process,
            command=command,
            cwd=cwd,
            task_id=self.task_id,
            owner_task_id=self.task_id,
            session_key=self.session_key,
            output_so_far=seed,
            # Desktop's native owner/Stop/opt-out/dedup gates own the wake.
            # A completion only asks the parent to read the file-backed result.
            notify_on_complete=(completion_mode == "notify") and (bool(self.ui_session_id) or self.local_completion_wake),
        )
        process_id = str(getattr(session, "id", ""))
        # Ownership has already transferred. A display failure must never cause
        # a relaunch or suppress the independently owned completion event.
        try:
            seeded = self.emit("status.update", {"kind": "process", "text": ""})
        except Exception:
            raise DesktopSeedUnavailable(process_id) from None
        if seeded is not True:
            raise DesktopSeedUnavailable(process_id)
        return process_id

    def observe(self, process, *, process_id, home, job_id, profile, timeout):
        """Start only AFTER Router publishes the exact launch metadata.

        Starting a reader before os.replace can cause a Windows sharing
        violation and strand launch.json at worker_pid=null forever.
        """
        session = self.registry.get(process_id)
        if (session is None or session.process is not process
                or session.pid != process.pid or session.owner_task_id != self.task_id
                or session.session_key != self.session_key
                or session.parent_session_id != self.parent_session_id):
            return None
        try:
            from .background_output import start_background_output
            return start_background_output(
                session=session, registry=self.registry, process=process,
                home=home, job_id=job_id, profile=profile,
                parent_session_id=self.parent_session_id, session_key=self.session_key,
                owner_task_id=self.task_id, ui_session_id=self.ui_session_id,
                emit=self.emit, timeout=timeout,
            )
        except Exception:
            # Observation may fail; the real process remains adopted. Never
            # relaunch it, change lifecycle, or forward raw exception text.
            if session is not None:
                try:
                    session.append_output("활동 기록 연결을 확인할 수 없습니다. 실제 실행 상태는 Background에서 확인하세요.\n")
                except Exception:
                    pass
            return None


@contextmanager
def route_session_context(*, session_id: str = "", expected_profile: str = ""):
    """Bind a cached messaging turn's dispatcher ID for this launch only.

    The host supplies session_id as a handler kwarg, never as model arguments.
    Gateway cached turns may bind the lane/profile but leave SESSION_ID empty.
    Require that existing task-local lane; never borrow process-global identity
    or repair an incomplete Desktop context. Native adoption and its observer
    must see the same scoped ID as capture_runtime, then restore it on exit.
    """
    from gateway.session_context import NON_MESSAGING_SESSION_SURFACES, scoped_current_session_id

    values = {var.name: value for var, value in copy_context().items()
              if var.name.startswith("HERMES_SESSION_") or var.name == "HERMES_UI_SESSION_ID"}
    parent = values.get("HERMES_SESSION_ID", "")
    if session_id and (not isinstance(session_id, str) or SESSION_TOKEN.fullmatch(session_id) is None):
        raise ValueError("invalid dispatcher session identity")
    if parent:
        if session_id and parent != session_id:
            raise ValueError("dispatcher session does not match current-session context")
        yield
        return
    if not session_id:
        yield  # capture_runtime retains its existing unbound/fail-closed rules.
        return
    surfaces = (values.get("HERMES_SESSION_PLATFORM", ""), values.get("HERMES_SESSION_SOURCE", ""))
    key = values.get("HERMES_SESSION_KEY", "")
    profile = values.get("HERMES_SESSION_PROFILE", "")
    if (not any(surfaces) or any(not isinstance(s, str) for s in surfaces)
            or any(s and s in NON_MESSAGING_SESSION_SURFACES for s in surfaces)
            or values.get("HERMES_UI_SESSION_ID")
            or not isinstance(key, str) or not key or len(key) > 512
            or any(ord(c) < 32 for c in key)
            or not expected_profile or profile != expected_profile):
        raise ValueError("routing requires a bound messaging lane and matching profile")
    with scoped_current_session_id(session_id):
        yield


def capture_runtime(*, task_id: str = "", expected_profile: str = "", get_env=None, registry=None, emit=None):
    """Use bound ContextVars, not stale process-global chat identity.

    A standalone CLI without a task binding stays unbound. Missing bindings in
    a session-serving process fail before spawn. get_env is an offline test seam.
    """
    if get_env is None:
        from gateway.session_context import session_context_engaged
        values = {var.name: value for var, value in copy_context().items()
                  if var.name.startswith("HERMES_SESSION_") or var.name == "HERMES_UI_SESSION_ID"}
        def read_env(name: str, default: Any = "") -> Any:
            value = values.get(name, default)
            return value if isinstance(value, str) else default
        get_env = read_env
        if not get_env("HERMES_SESSION_ID"):
            desktop_hint = os.environ.get("HERMES_UI_SESSION_ID") or os.environ.get("HERMES_SESSION_PLATFORM") == "desktop"
            if session_context_engaged() or desktop_hint:
                raise ValueError("routing requires a bound current-session context")
            return None
    parent = get_env("HERMES_SESSION_ID", "")
    key = get_env("HERMES_SESSION_KEY", "")
    platform = get_env("HERMES_SESSION_PLATFORM", "") or get_env("HERMES_SESSION_SOURCE", "")
    ui_session = get_env("HERMES_UI_SESSION_ID", "")
    # A bound local launch-authority turn spells its unnamed profile as "".
    # Keep that distinct from a missing/non-string field, and admit it only for
    # the default package's exact observed local context. Never rewrite the host
    # bindings or use process-global profile/session identity as a fallback.
    profile = get_env("HERMES_SESSION_PROFILE", None)
    local_default = (
        expected_profile == "default" and profile == ""
        and get_env("HERMES_SESSION_PLATFORM", None) == "local"
        and get_env("HERMES_SESSION_SOURCE", None) == ""
        and get_env("HERMES_UI_SESSION_ID", None) == ""
        and isinstance(parent, str) and SESSION_TOKEN.fullmatch(parent) is not None
        and isinstance(key, str) and 0 < len(key) <= 512
        and not any(ord(c) < 32 for c in key)
    )
    if ui_session or platform == "desktop":
        if not parent or not key or not profile or not ui_session:
            raise ValueError("incomplete desktop routing context")
    if not parent:
        if key:
            raise ValueError("incomplete routing parent context")
        return None
    if expected_profile and profile != expected_profile and not local_default:
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
    return RouteRuntime(parent, key, owner, registry, emit, ui_session_id=ui_session,
                        local_completion_wake=local_default)
