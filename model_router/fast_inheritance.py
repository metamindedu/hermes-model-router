"""Profile-scoped inheritance of the live session's native Fast intent.

Only primitive Fast intent and exact native session identifiers are retained.
This module observes plugin middleware/hooks; it never edits Hermes agent state,
provider credentials, settings, or lifecycle records.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
import inspect
import math
import os
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit
import weakref

SCHEMA = 1
_PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SNAPSHOT_KEYS = frozenset({
    "schema", "profile", "origin_session_id", "parent_session_id", "mode", "expires_at",
})
_MODES = frozenset({"normal", "priority", "ultrafast", "auto", "cold"})
_BOUNDED_MODES = frozenset({"auto", "cold"})
_STATIC_MODES = frozenset({"normal", "priority", "ultrafast"})
_OPENAI_PROVIDERS = frozenset({"openai", "openai-api", "openai-codex"})
_API_MODES = frozenset({"chat_completions", "codex_responses"})
_FAST_FIELDS = frozenset({"service_tier", "speed"})

# These limits bound stale asynchronous children without imposing a Fast window
# or a task-runtime limit. Expired snapshots still retain their original expiry.
BINDING_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_CHILD_BINDINGS = 1024


@dataclass(frozen=True)
class _DispatchBinding:
    controller: "FastInheritanceController"
    kind: str
    profile: str
    home_key: str
    parent_session_id: str
    parent_identity: int
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class _ChildBinding:
    profile: str
    home_key: str
    parent_session_id: str
    child_session_id: str
    child_subagent_id: str
    snapshot: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class _RoutedBinding:
    profile: str
    home_key: str
    session_id: str
    snapshot: dict[str, Any]


_ACTIVE_DISPATCH: contextvars.ContextVar[_DispatchBinding | None] = contextvars.ContextVar(
    "model_router_fast_inheritance_dispatch", default=None,
)
_ROUTED_FAST: contextvars.ContextVar[_RoutedBinding | None] = contextvars.ContextVar(
    "model_router_fast_inheritance_routed", default=None,
)
_REGISTERED_CONTROLLERS: weakref.WeakSet["FastInheritanceController"] = weakref.WeakSet()
_REGISTERED_LOCK = threading.RLock()


def _safe_identifier(value: Any) -> str | None:
    """Accept an exact native token; never trim, repair, or synthesize identifiers."""
    return value if type(value) is str and _ID_RE.fullmatch(value) is not None else None


def _valid_profile(value: Any) -> str | None:
    return value if type(value) is str and _PROFILE_RE.fullmatch(value) is not None else None


def _finite_nonnegative(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value)) and value >= 0
    except (OverflowError, TypeError, ValueError):
        return False


def _get_hermes_home() -> Any:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


def _get_active_parent() -> Any:
    from agent.subagent_lifecycle import get_active_subagent_parent

    return get_active_subagent_parent()


def _canonical_home(value: Any) -> Path:
    try:
        supplied = Path(value).expanduser()
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("profile home is invalid") from exc
    if not supplied.is_absolute() or supplied.is_symlink():
        raise ValueError("profile home must be an absolute unlinked directory")
    try:
        resolved = supplied.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("profile home cannot be resolved") from exc
    if not resolved.is_dir() or resolved != supplied:
        raise ValueError("profile home must be a canonical directory")
    return resolved


def _home_key(home: Path) -> str:
    return os.path.normcase(str(home))


def _same_home(left: Any, right: Path) -> bool:
    try:
        return _home_key(_canonical_home(left)) == _home_key(right)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def validate_fast_snapshot(
    value: Any, *, profile: str | None = None, parent_session_id: str | None = None,
) -> dict[str, Any] | None:
    """Validate the frozen primitive protocol and return a fresh exact-key dict.

    ``None`` means no verified Fast observation (unavailable/legacy), not an
    explicit normal mode. A valid ``mode='normal'`` is an affirmative off.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Fast snapshot must be a mapping or None")
    try:
        if set(value.keys()) != _SNAPSHOT_KEYS:
            raise ValueError("Fast snapshot fields are invalid")
    except (TypeError, ValueError) as exc:
        raise ValueError("Fast snapshot fields are invalid") from exc

    schema = value.get("schema")
    snapshot_profile = value.get("profile")
    origin = _safe_identifier(value.get("origin_session_id"))
    parent = _safe_identifier(value.get("parent_session_id"))
    mode = value.get("mode")
    expiry = value.get("expires_at")
    if type(schema) is not int or schema != SCHEMA:
        raise ValueError("Fast snapshot schema is unsupported")
    if _valid_profile(snapshot_profile) is None:
        raise ValueError("Fast snapshot profile is invalid")
    if origin is None or parent is None:
        raise ValueError("Fast snapshot session identity is invalid")
    if type(mode) is not str or mode not in _MODES:
        raise ValueError("Fast snapshot mode is invalid")
    if mode in _STATIC_MODES:
        if expiry is not None:
            raise ValueError("static Fast snapshot cannot carry an expiry")
    elif not _finite_nonnegative(expiry):
        raise ValueError("bounded Fast snapshot expiry is invalid")

    if profile is not None:
        if _valid_profile(profile) is None or snapshot_profile != profile:
            raise ValueError("Fast snapshot profile does not match")
    if parent_session_id is not None:
        expected_parent = _safe_identifier(parent_session_id)
        if expected_parent is None or parent != expected_parent:
            raise ValueError("Fast snapshot parent does not match")
    return {
        "schema": schema,
        "profile": snapshot_profile,
        "origin_session_id": origin,
        "parent_session_id": parent,
        "mode": mode,
        "expires_at": expiry,
    }


def capture_fast_snapshot(
    parent_agent: Any, *, profile: str, parent_session_id: str,
    inherited_snapshot: Mapping[str, Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, Any] | None:
    """Capture live parent Fast intent without touching agent state or request overrides."""
    clean_profile = _valid_profile(profile)
    expected_parent = _safe_identifier(parent_session_id)
    if clean_profile is None or expected_parent is None or parent_agent is None:
        return None
    try:
        actual_parent = _get_active_parent()
        actual_id = _safe_identifier(getattr(actual_parent, "session_id", None))
        if actual_parent is not parent_agent or actual_id != expected_parent:
            return None
    except Exception:
        return None

    if inherited_snapshot is not None:
        try:
            inherited = validate_fast_snapshot(inherited_snapshot, profile=clean_profile)
        except (TypeError, ValueError):
            return None
        if inherited is not None:
            inherited["parent_session_id"] = expected_parent
            return inherited

    try:
        if not hasattr(parent_agent, "service_tier"):
            return None
        raw_mode = getattr(parent_agent, "service_tier")
    except Exception:
        return None
    if raw_mode is None:
        mode = "normal"
        expiry = None
    elif type(raw_mode) is str and raw_mode in {"", "normal"}:
        mode = "normal"
        expiry = None
    elif type(raw_mode) is str and raw_mode in _MODES:
        mode = raw_mode
        expiry = None
        if mode in _BOUNDED_MODES:
            try:
                until = getattr(parent_agent, "_fast_until")  # scalar compatibility read only
                if not _finite_number(until):
                    return None
                mono_now = monotonic()
                wall_now = wall_clock()
                if not _finite_number(mono_now) or not _finite_number(wall_now):
                    return None
                remaining = float(until) - float(mono_now)
                # Preserve an inactive deadline as expired; never grant a fresh window.
                expiry = max(0.0, float(wall_now) + remaining)
                if not math.isfinite(expiry):
                    return None
            except Exception:
                return None
    else:
        # Unknown native state is unavailable, not an implicit normal/off choice.
        return None

    return {
        "schema": SCHEMA,
        "profile": clean_profile,
        "origin_session_id": expected_parent,
        "parent_session_id": expected_parent,
        "mode": mode,
        "expires_at": expiry,
    }


def _finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _first_party_route(provider: str, base_url: str) -> bool:
    """Reject proxy/custom hosts before asking Hermes' native Fast resolver."""
    if provider not in _OPENAI_PROVIDERS:
        return False
    if not base_url:
        return False
    try:
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
            return False
        if parsed.port not in (None, 443):
            return False
    except (TypeError, ValueError):
        return False
    if provider == "openai-codex":
        return host == "chatgpt.com"
    return host == "api.openai.com"


def _native_resolver(**kwargs: Any) -> Any:
    from hermes_cli.models import resolve_fast_mode_overrides

    return resolve_fast_mode_overrides(**kwargs)


def apply_fast_snapshot(
    request: Mapping[str, Any], snapshot: Mapping[str, Any] | None, *,
    model: str | None, provider: str | None, base_url: str | None, api_mode: str | None,
    wall_clock: Callable[[], float] = time.time,
    resolver: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return clean provider kwargs, changing only inherited Fast request fields.

    Unavailable snapshots are inert. A valid managed snapshot first removes
    inherited stale paid ``service_tier``/``speed`` fields; only an eligible,
    unexpired OpenAI first-party route receives a native-resolver-approved tier.
    """
    if not isinstance(request, Mapping):
        raise ValueError("LLM request must be a mapping")
    result = dict(request)
    if snapshot is None:
        return result
    clean_snapshot = validate_fast_snapshot(snapshot)
    assert clean_snapshot is not None

    for key in _FAST_FIELDS:
        result.pop(key, None)
    extra_body = result.get("extra_body")
    if isinstance(extra_body, Mapping):
        clean_body = dict(extra_body)
        for key in _FAST_FIELDS:
            clean_body.pop(key, None)
        result["extra_body"] = clean_body

    mode = clean_snapshot["mode"]
    if mode == "normal":
        return result
    if mode in _BOUNDED_MODES:
        try:
            now = wall_clock()
            if not _finite_number(now) or float(now) >= float(clean_snapshot["expires_at"]):
                return result
        except Exception:
            return result

    provider_name = provider.lower() if isinstance(provider, str) else ""
    base = base_url if isinstance(base_url, str) else ""
    if (provider_name not in _OPENAI_PROVIDERS or api_mode not in _API_MODES
            or not isinstance(model, str) or not model
            or not _first_party_route(provider_name, base)):
        return result
    if provider_name == "openai-codex" and api_mode != "codex_responses":
        return result

    resolve = resolver or _native_resolver
    tier_arg = "ultrafast" if mode == "ultrafast" else None
    try:
        resolved = resolve(model_id=model, provider=provider_name, base_url=base or None, tier=tier_arg)
    except Exception:
        return result
    expected_tier = "ultrafast" if mode == "ultrafast" else "priority"
    if not isinstance(resolved, Mapping) or resolved.get("service_tier") != expected_tier:
        # In particular, no Ultrafast -> Priority downgrade.
        return result
    result["service_tier"] = expected_tier
    return result


class FastInheritanceController:
    """One profile-local controller holding only bounded primitive child bindings."""

    def __init__(self, home: Path, profile: str) -> None:
        self.home = home
        self.home_key = _home_key(home)
        self.profile = profile
        self._lock = threading.RLock()
        self._children: OrderedDict[str, _ChildBinding] = OrderedDict()
        self._registrations: list[Any] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _now(self) -> float:
        return time.monotonic()

    def _current_profile(self) -> str | None:
        try:
            from hermes_cli.profiles import get_active_profile_name

            return get_active_profile_name()
        except Exception:
            return None

    def _scope_is_current(self) -> bool:
        with self._lock:
            if self._closed:
                return False
        try:
            return (
                _same_home(_get_hermes_home(), self.home)
                and self._current_profile() == self.profile
            )
        except Exception:
            return False

    def _active_agent(self, expected_session: str) -> Any | None:
        try:
            parent = _get_active_parent()
            if _safe_identifier(getattr(parent, "session_id", None)) != expected_session:
                return None
            return parent
        except Exception:
            return None

    def _prune_locked(self, now: float) -> None:
        for session_id, binding in list(self._children.items()):
            if now < binding.created_at or now - binding.created_at > BINDING_TTL_SECONDS:
                self._children.pop(session_id, None)
        while len(self._children) > MAX_CHILD_BINDINGS:
            self._children.popitem(last=False)

    def _read_child_snapshot(self, session_id: str) -> dict[str, Any] | None:
        try:
            now = float(self._now())
            if not math.isfinite(now):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        with self._lock:
            if self._closed:
                return None
            self._prune_locked(now)
            binding = self._children.get(session_id)
            if (binding is None or binding.profile != self.profile or binding.home_key != self.home_key
                    or binding.child_session_id != session_id):
                return None
            try:
                return validate_fast_snapshot(binding.snapshot, profile=self.profile)
            except (TypeError, ValueError):
                self._children.pop(session_id, None)
                return None

    def _inherited_for_parent(self, parent_session_id: str) -> dict[str, Any] | None:
        routed = _ROUTED_FAST.get()
        if (routed is not None and routed.home_key == self.home_key
                and routed.profile == self.profile and routed.session_id == parent_session_id):
            try:
                return validate_fast_snapshot(routed.snapshot, profile=self.profile)
            except (TypeError, ValueError):
                return None
        # A nested native child may inherit an outer routed ContextVar. Its
        # exact native generation hook is stronger identity for this session.
        return self._read_child_snapshot(parent_session_id)

    def _capture_dispatch(self, session_id: Any) -> tuple[str, int, dict[str, Any]] | None:
        if not self._scope_is_current():
            return None
        dispatch_session = _safe_identifier(session_id)
        parent = self._active_agent(dispatch_session) if dispatch_session is not None else None
        if dispatch_session is None or parent is None:
            return None
        inherited = self._inherited_for_parent(dispatch_session)
        snapshot = capture_fast_snapshot(
            parent,
            profile=self.profile,
            parent_session_id=dispatch_session,
            inherited_snapshot=inherited,
        )
        if snapshot is None:
            return None
        try:
            clean = validate_fast_snapshot(snapshot, profile=self.profile, parent_session_id=dispatch_session)
        except (TypeError, ValueError):
            return None
        if clean is None:
            return None
        return dispatch_session, id(parent), clean

    @staticmethod
    def _dispatch_kind(tool_name: Any, args: Any) -> str | None:
        if not isinstance(args, dict):
            return None
        if tool_name == "coding_route" and args.get("action") == "start":
            return "route"
        if tool_name != "delegate_task":
            return None
        action = args.get("action")
        if action is None or action == "":
            return "native"
        if isinstance(action, str) and action.strip().lower() == "spawn":
            return "native"
        return None

    def tool_execution_middleware(self, **kwargs: Any) -> Any:
        """Scope route/native dispatch authority and call downstream exactly once."""
        next_call = kwargs.get("next_call")
        if not callable(next_call):
            raise TypeError("tool_execution middleware requires next_call")
        kind = self._dispatch_kind(kwargs.get("tool_name"), kwargs.get("args"))
        captured = self._capture_dispatch(kwargs.get("session_id")) if kind is not None else None
        if captured is None:
            return next_call()

        parent_session_id, parent_identity, snapshot = captured
        binding = _DispatchBinding(
            controller=self,
            kind=kind,
            profile=self.profile,
            home_key=self.home_key,
            parent_session_id=parent_session_id,
            parent_identity=parent_identity,
            snapshot=dict(snapshot),
        )
        token = _ACTIVE_DISPATCH.set(binding)
        try:
            result = next_call()
        except BaseException:
            _ACTIVE_DISPATCH.reset(token)
            raise
        if inspect.isawaitable(result):
            _ACTIVE_DISPATCH.reset(token)

            async def await_downstream() -> Any:
                async_token = _ACTIVE_DISPATCH.set(binding)
                try:
                    return await result
                finally:
                    _ACTIVE_DISPATCH.reset(async_token)

            return await_downstream()
        _ACTIVE_DISPATCH.reset(token)
        return result

    def capture_for_route(self, session_id: str, profile: str) -> dict[str, Any] | None:
        """Return a fresh snapshot only inside this controller's exact route-start dispatch."""
        binding = _ACTIVE_DISPATCH.get()
        if (binding is None or binding.controller is not self or binding.kind != "route"
                or binding.home_key != self.home_key or binding.profile != self.profile
                or not self._scope_is_current()):
            return None
        if (_safe_identifier(session_id) != binding.parent_session_id
                or _valid_profile(profile) != self.profile):
            return None
        parent = self._active_agent(binding.parent_session_id)
        if parent is None or id(parent) != binding.parent_identity:
            return None
        try:
            clean = validate_fast_snapshot(
                binding.snapshot, profile=self.profile, parent_session_id=binding.parent_session_id,
            )
        except (TypeError, ValueError):
            return None
        return dict(clean) if clean is not None else None

    def on_subagent_start(self, **payload: Any) -> None:
        """Bind the primitive snapshot to exact IDs from the native child-generation hook."""
        binding = _ACTIVE_DISPATCH.get()
        if (binding is None or binding.controller is not self or binding.kind != "native"
                or binding.home_key != self.home_key or binding.profile != self.profile
                or not self._scope_is_current()):
            return
        parent_session_id = _safe_identifier(payload.get("parent_session_id"))
        child_session_id = _safe_identifier(payload.get("child_session_id"))
        child_subagent_id = _safe_identifier(payload.get("child_subagent_id"))
        if (parent_session_id != binding.parent_session_id or child_session_id is None
                or child_subagent_id is None):
            return
        parent = self._active_agent(binding.parent_session_id)
        if parent is None or id(parent) != binding.parent_identity:
            return
        try:
            snapshot = validate_fast_snapshot(
                binding.snapshot, profile=self.profile, parent_session_id=parent_session_id,
            )
            now = float(self._now())
            if snapshot is None or not math.isfinite(now):
                return
        except (TypeError, ValueError, OverflowError):
            return
        child = _ChildBinding(
            profile=self.profile,
            home_key=self.home_key,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            child_subagent_id=child_subagent_id,
            snapshot=snapshot,
            created_at=now,
        )
        with self._lock:
            if self._closed:
                return
            self._prune_locked(now)
            existing = self._children.get(child_session_id)
            if existing is not None:
                # Do not merge a recycled session token or a different native child.
                if (existing.parent_session_id == parent_session_id
                        and existing.child_subagent_id == child_subagent_id):
                    return
                return
            self._children[child_session_id] = child
            self._children.move_to_end(child_session_id)
            self._prune_locked(now)

    def on_subagent_stop(self, **payload: Any) -> None:
        """Retire only entries matched by the hook's exact parent and child session IDs."""
        if not self._scope_is_current():
            return
        parent_session_id = _safe_identifier(payload.get("parent_session_id"))
        child_session_id = _safe_identifier(payload.get("child_session_id"))
        if parent_session_id is None or child_session_id is None:
            return
        with self._lock:
            binding = self._children.get(child_session_id)
            if (binding is not None and binding.parent_session_id == parent_session_id
                    and binding.child_session_id == child_session_id
                    and binding.profile == self.profile and binding.home_key == self.home_key):
                self._children.pop(child_session_id, None)

    def llm_request_middleware(self, **kwargs: Any) -> dict[str, Any] | None:
        """Apply only to a registered native child or exact routed child request."""
        if (kwargs.get("aux_task") not in (None, "") or kwargs.get("auxiliary") is True
                or kwargs.get("call_role") == "auxiliary"):
            return None
        if not self._scope_is_current():
            return None
        session_id = _safe_identifier(kwargs.get("session_id"))
        if session_id is None or self._active_agent(session_id) is None:
            return None

        routed = _ROUTED_FAST.get()
        if (routed is not None and routed.profile == self.profile
                and routed.home_key == self.home_key and routed.session_id == session_id):
            snapshot = routed.snapshot
        else:
            # A native child can run with an outer routed ContextVar copied
            # from its parent; only its own exact child binding may authorize it.
            snapshot = self._read_child_snapshot(session_id)
        if snapshot is None:
            return None
        request = kwargs.get("request")
        if not isinstance(request, Mapping):
            return None
        try:
            updated = apply_fast_snapshot(
                request,
                snapshot,
                model=kwargs.get("model"),
                provider=kwargs.get("provider"),
                base_url=kwargs.get("base_url"),
                api_mode=kwargs.get("api_mode"),
            )
        except (TypeError, ValueError):
            return None
        return {"request": updated, "source": "model-router-fast-inheritance"}

    def close(self) -> None:
        """Dispose plugin-owned primitive state without touching native children."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._children.clear()
            registrations, self._registrations = self._registrations, []
        for registration in reversed(registrations):
            dispose = getattr(registration, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass
        with _REGISTERED_LOCK:
            _REGISTERED_CONTROLLERS.discard(self)


def register_fast_inheritance(ctx: Any, home: str | Path) -> FastInheritanceController | None:
    """Register profile-local native middleware and lifecycle observers; never reads TOTAL settings."""
    try:
        profile = _valid_profile(getattr(ctx, "profile_name", None))
        profile_home = _canonical_home(home)
        if profile is None or not _same_home(_get_hermes_home(), profile_home):
            return None
        controller = FastInheritanceController(profile_home, profile)
    except Exception:
        return None

    registrations: list[Any] = []
    controller._registrations = registrations
    try:
        registrations.append(ctx.register_middleware("tool_execution", controller.tool_execution_middleware))
        registrations.append(ctx.register_hook("subagent_start", controller.on_subagent_start))
        registrations.append(ctx.register_hook("subagent_stop", controller.on_subagent_stop))
        registrations.append(ctx.register_middleware("llm_request", controller.llm_request_middleware))
        registrations.append(ctx.on_unload(controller.close))
        if any(not callable(getattr(registration, "dispose", None)) for registration in registrations):
            raise RuntimeError("Fast inheritance registration handle is unavailable")
    except Exception:
        controller.close()
        for registration in reversed(registrations):
            dispose = getattr(registration, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass
        return None
    with _REGISTERED_LOCK:
        _REGISTERED_CONTROLLERS.add(controller)
    return controller


def _registered_controller(home: Path, profile: str) -> FastInheritanceController | None:
    key = _home_key(home)
    with _REGISTERED_LOCK:
        matches = [
            controller for controller in _REGISTERED_CONTROLLERS
            if not controller.closed and controller.home_key == key and controller.profile == profile
        ]
    return matches[0] if len(matches) == 1 else None


@contextmanager
def bind_routed_fast_snapshot(
    snapshot: Mapping[str, Any] | None, *, session_id: str, home: str | Path,
) -> Iterator[None]:
    """Bind route intent on this exact registered module instance and child session context."""
    token: contextvars.Token[_RoutedBinding | None] | None = None
    if snapshot is not None:
        clean = validate_fast_snapshot(snapshot)
        if clean is None:
            raise ValueError("routed Fast snapshot is unavailable")
        supplied_home = _canonical_home(home)
        session = _safe_identifier(session_id)
        if session is None:
            raise ValueError("routed Fast child session identity is invalid")
        if not _same_home(_get_hermes_home(), supplied_home):
            raise ValueError("routed Fast profile home does not match the active profile")
        controller = _registered_controller(supplied_home, clean["profile"])
        if controller is None or not controller._scope_is_current():
            raise ValueError("routed Fast snapshot has no exact registered profile controller")
        token = _ROUTED_FAST.set(_RoutedBinding(
            profile=clean["profile"],
            home_key=controller.home_key,
            session_id=session,
            snapshot=clean,
        ))
    try:
        yield
    finally:
        if token is not None:
            _ROUTED_FAST.reset(token)
