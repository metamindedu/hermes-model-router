"""Cooperatively stop over-budget native ``delegate_task`` children.

This observer owns only its timer and private timeout-cause evidence. Native
Hermes remains the source of ownership and lifecycle truth through
``delegate_task(action='list'/'stop')``.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
MAX_EVIDENCE_RECORDS = 128
MAX_EVIDENCE_BYTES = 64 * 1024
EVIDENCE_NAME = "native-watchdog.jsonl"

_ACTIVE_DISPATCH: contextvars.ContextVar["_DispatchBinding | None"] = contextvars.ContextVar(
    "model_router_native_watchdog_dispatch", default=None,
)


def _dispatch_backend(parent: Any) -> str:
    from agent.delegation_backends import pinned_backend
    from agent.delegation_registry import configured_backend
    from tools.delegate_tool_config import _load_config
    return pinned_backend(parent) or configured_backend(_load_config())


def _routed_policies(home: Path, args: Mapping[str, Any], backend: str = 'model-router', ordinary_total: int | float = 0) -> dict[str, tuple[str, int | float]]:
    """Preflight the native-normalized goals before *any* child can be built."""
    from .native_delegation import PURPOSE_ROLES, _origin, _timeout
    from .service import Service
    from tools.delegate_tool_tasks import _normalize_task_list
    service = Service()
    profile = _origin(home, service)
    config = service.routing_config(profile) if backend == 'model-router' else {}
    if backend == 'model-router' and config.get('enabled') is not True:
        raise ValueError('routing disabled')
    tasks, error = _normalize_task_list(args.get('goal'), args.get('context'), args.get('tasks'),
                                        args.get('output_schema'), '', 2**31 - 1)
    if error or not tasks:
        raise ValueError('invalid tasks')
    policies = {}
    for task in tasks:
        goal = task.get('goal')
        purpose = task.get('purpose')
        role = (PURPOSE_ROLES.get(purpose) if isinstance(purpose, str) else None) if backend == 'model-router' else 'profile'
        if not isinstance(goal, str):
            raise ValueError('invalid routed task')
        if role is None:
            # Native per-task validation/provider refusal owns this task. It
            # must not prevent valid siblings from being routed.
            continue
        budget = task.get('total_timeout_seconds', config.get(role + '_timeout_seconds') if backend == 'model-router' else ordinary_total)
        if not _timeout(budget):
            continue  # provider refuses it before a child can be constructed
        policy = (role, budget)
        if goal in policies and policies[goal] != policy:
            raise ValueError('ambiguous routed goal')
        policies[goal] = policy
    return policies


def verify_routed_binding(home: Path, goal: Any, role: str, budget: int | float) -> bool:
    """A route may proceed only in its verified, same-process native dispatch."""
    binding = _ACTIVE_DISPATCH.get()
    try:
        return bool(binding is not None and not binding.closed and not binding.watchdog.closed
                    and binding.routed_policies is not None and isinstance(goal, str)
                    and binding.routed_policies.get(goal) == (role, budget)
                    and _home_key(_canonical_home(home)) == binding.watchdog._home_key
                    and binding.watchdog._same_home()
                    and binding.watchdog.get_active_parent() is binding.parent_agent
                    and (budget == 0 or binding.watchdog._scheduler is not None))
    except Exception:
        return False


def _read_timeouts(home: Path) -> Mapping[str, Any]:
    """Read this profile's model-router settings without editing Hermes config."""
    from .timeouts import read_timeouts

    return read_timeouts(home)


def _get_hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


def _get_active_parent() -> Any:
    from agent.subagent_lifecycle import get_active_subagent_parent

    return get_active_subagent_parent()


def _delegate_task(**kwargs: Any) -> Any:
    from tools.delegate_tool import delegate_task

    return delegate_task(**kwargs)


def _valid_nonnegative_number(value: Any) -> bool:
    """JSON integers are finite regardless of size; floats must be finite."""
    if type(value) is int:
        return value >= 0
    return type(value) is float and math.isfinite(value) and value >= 0


def _safe_identifier(value: Any) -> str | None:
    """Accept an exact host ID; never trim, normalize, or synthesize identifiers."""
    if (not isinstance(value, str) or not value or len(value) > 256
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    return value


def _canonical_home(value: Any) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("profile home must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("profile home must be a directory")
    return resolved


def _home_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=True)))


def _response_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_owned_list(value: Any) -> dict[str, dict[str, Any]] | None:
    """Parse only the public native list contract; malformed results fail closed."""
    payload = _response_dict(value)
    if not payload or payload.get("action") != "list":
        return None
    count = payload.get("count")
    entries = payload.get("subagents")
    if type(count) is not int or count < 0 or not isinstance(entries, list) or count != len(entries):
        return None
    parsed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        subagent_id = _safe_identifier(entry.get("subagent_id"))
        status = entry.get("status")
        if subagent_id is None or not isinstance(status, str) or not status:
            return None
        if subagent_id in parsed:
            return None
        running_seconds = entry.get("running_seconds")
        if not _valid_nonnegative_number(running_seconds):
            running_seconds = None
        parsed[subagent_id] = {"status": status, "running_seconds": running_seconds}
    return parsed


def _deadline_after_observation(now: float, total: int | float, running: int | float) -> float:
    """Represent the fixed monotonic deadline, preserving arbitrarily long finite limits.

    A duration larger than the platform float range is valid but cannot elapse
    during this process's lifetime; infinity is its practical monotonic deadline,
    not a configuration cap or rejection.
    """
    try:
        remaining = total - running
        if remaining <= 0:
            return now
        return now + float(remaining)
    except (OverflowError, TypeError, ValueError):
        return math.inf


@dataclass
class _DispatchBinding:
    watchdog: "NativeWatchdog"
    parent_agent: Any
    parent_session_id: str
    total_seconds: int | float = 0
    routed_policies: dict[str, tuple[str, int | float]] | None = None
    context: contextvars.Context | None = None
    child_ids: set[str] = field(default_factory=set)
    closed: bool = False


@dataclass
class _ChildWatch:
    subagent_id: str
    child_session_id: str
    parent_agent: Any
    parent_session_id: str
    total_seconds: int | float
    control_context: contextvars.Context
    scope: _DispatchBinding
    registered: bool = False
    first_running_seconds: int | float | None = None
    deadline: float | None = None
    stop_attempted: bool = False
    stop_outcome: str | None = None
    scope_closed: bool = False

    @property
    def key(self) -> tuple[int, str]:
        return id(self.parent_agent), self.subagent_id


class _ThreadScheduler:
    """One daemon polling thread per loaded profile plugin, never one per child."""

    def __init__(self, callback: Callable[[], None], interval: float, context: contextvars.Context):
        self.callback = callback
        self.interval = interval
        self.context = context.copy()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        def run() -> None:
            while not self.stop_event.wait(self.interval):
                try:
                    self.callback()
                except Exception:
                    # The native tool path and native child are never affected by observer failure.
                    logger.debug("native watchdog poll failed", exc_info=True)

        self.thread = threading.Thread(
            target=self.context.run, args=(run,), name="model-router-native-watchdog", daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()


class NativeWatchdog:
    """Track exact children created inside ordinary native ``delegate_task`` calls."""

    def __init__(
        self,
        home: str | Path,
        total_seconds: int | float,
        *,
        get_hermes_home: Callable[[], Any] = _get_hermes_home,
        get_active_parent: Callable[[], Any] = _get_active_parent,
        delegate_task: Callable[..., Any] = _delegate_task,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        scheduler_factory: Callable[[Callable[[], None], float, contextvars.Context], Any] | None = None,
        poll_interval: float = POLL_SECONDS,
        read_timeouts_fn: Callable[[Path], Mapping[str, Any]] | None = None,
    ) -> None:
        if not _valid_nonnegative_number(total_seconds):
            raise ValueError("native watchdog requires a nonnegative finite total limit")
        if (type(poll_interval) not in (int, float) or not math.isfinite(poll_interval)
                or poll_interval <= 0):
            raise ValueError("poll interval must be positive and finite")
        self.home = _canonical_home(home)
        self._home_key = _home_key(self.home)
        self.total_seconds = total_seconds
        self.read_timeouts_fn = read_timeouts_fn
        self.get_hermes_home = get_hermes_home
        self.get_active_parent = get_active_parent
        self.delegate_task = delegate_task
        self.monotonic = monotonic
        self.wall_clock = wall_clock
        self.scheduler_factory = scheduler_factory or _ThreadScheduler
        self.poll_interval = float(poll_interval)
        self._lock = threading.RLock()
        self._control_lock = threading.Lock()
        self._evidence_lock = threading.Lock()
        self._children: dict[tuple[int, str], _ChildWatch] = {}
        self._pending_dispatches: set[int] = set()
        self._scheduler: Any = None
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def children(self) -> dict[str, _ChildWatch]:
        """Read-only-by-convention test/diagnostic snapshot keyed by native ID."""
        with self._lock:
            return {watch.subagent_id: watch for watch in self._children.values()}

    def _same_home(self) -> bool:
        try:
            return _home_key(_canonical_home(self.get_hermes_home())) == self._home_key
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def _spawn_action(self, args: Any) -> bool:
        if not isinstance(args, dict):
            return False
        action = args.get("action")
        if action is None or action == "":
            return True
        if not isinstance(action, str):
            return False
        return action.strip().lower() == "spawn"

    def middleware(self, **kwargs: Any) -> Any:
        """Wrap the real native call without changing its arguments or result."""
        next_call = kwargs.get("next_call")
        if not callable(next_call):
            raise TypeError("tool_execution middleware requires next_call")
        if kwargs.get("tool_name") != "delegate_task" or not self._spawn_action(kwargs.get("args")):
            return next_call()

        binding: _DispatchBinding | None = None
        token: contextvars.Token | None = None
        routed = False
        backend = ''
        try:
            parent = self.get_active_parent()
            try:
                backend = _dispatch_backend(parent)
                routed = backend in ('model-router', 'model-router-profiles')
            except Exception:
                # The provider itself refuses a missing binding, even if backend discovery fails.
                routed = False
            if not self.closed and self._same_home():
                total_seconds = self.total_seconds
                if self.read_timeouts_fn is not None:
                    settings = self.read_timeouts_fn(self.home)
                    total_seconds = settings.get("delegate_total_seconds") if isinstance(settings, Mapping) else None
                if not _valid_nonnegative_number(total_seconds):
                    raise ValueError("native total-runtime settings cannot be verified")
                parent_session_id = _safe_identifier(getattr(parent, "session_id", None))
                tool_session_id = _safe_identifier(kwargs.get("session_id"))
                if ((total_seconds > 0 or routed) and parent is not None and parent_session_id is not None
                        and tool_session_id == parent_session_id):
                    binding = _DispatchBinding(self, parent, parent_session_id, total_seconds=total_seconds)
                    if routed:
                        binding.routed_policies = _routed_policies(self.home, kwargs.get('args'), backend, total_seconds)
                    token = _ACTIVE_DISPATCH.set(binding)
                    binding.context = contextvars.copy_context()
                    if routed and any(budget > 0 for _role, budget in binding.routed_policies.values()):
                        with self._lock:
                            self._pending_dispatches.add(id(binding))
                        self._ensure_scheduler(binding.context)
                        if self._scheduler is None:
                            raise ValueError('watchdog scheduler unavailable')
        except Exception:
            # Instrumentation is fail-open; the exact original native call still runs once.
            logger.warning("native total-runtime observation unavailable; original delegation remains unchanged", exc_info=False)
            if token is not None:
                _ACTIVE_DISPATCH.reset(token)
                token = None
            if binding is not None:
                with self._lock:
                    self._pending_dispatches.discard(id(binding))
            binding = None

        if routed and binding is None:
            self._stop_scheduler_if_idle()
            return json.dumps({'error': 'Model Router delegation refused: watchdog binding or task policies could not be verified.'})
        if binding is None:
            return next_call()
        returned: Any = None
        try:
            returned = next_call()
            return returned
        finally:
            if token is not None:
                _ACTIVE_DISPATCH.reset(token)
            binding.closed = True
            with self._lock:
                self._pending_dispatches.discard(id(binding))
                for subagent_id in binding.child_ids:
                    watch = self._children.get((id(binding.parent_agent), subagent_id))
                    if watch is not None and watch.scope is binding:
                        watch.scope_closed = True
            payload = _response_dict(returned)
            # A native synchronous terminal result/preflight error cannot have
            # queued work left. Retire unobserved short-lived or refused builds;
            # retain dispatched or ambiguous work until native truth settles.
            if payload is not None and payload.get("status") != "dispatched" and (
                    isinstance(payload.get("results"), list) or "error" in payload):
                with self._lock:
                    for key, watch in list(self._children.items()):
                        if watch.scope is binding:
                            self._children.pop(key, None)
                self._stop_scheduler_if_idle()
            elif not binding.child_ids:
                self._stop_scheduler_if_idle()

    def on_subagent_start(self, **payload: Any) -> None:
        """Bind IDs from the real native build hook; registration/clock starts later."""
        binding = _ACTIVE_DISPATCH.get()
        if binding is None or binding.watchdog is not self or self.closed:
            return
        try:
            if (not self._same_home() or self.get_active_parent() is not binding.parent_agent
                    or _safe_identifier(getattr(binding.parent_agent, "session_id", None))
                    != binding.parent_session_id):
                return
        except Exception:
            return
        if _safe_identifier(payload.get("parent_session_id")) != binding.parent_session_id:
            return
        child_session_id = _safe_identifier(payload.get("child_session_id"))
        subagent_id = _safe_identifier(payload.get("child_subagent_id"))
        if child_session_id is None or subagent_id is None:
            return
        total_seconds = binding.total_seconds
        if binding.routed_policies is not None:
            goal = payload.get('child_goal')
            if not isinstance(goal, str) or goal not in binding.routed_policies:
                return
            total_seconds = binding.routed_policies[goal][1]
            if total_seconds == 0:
                return
        context = binding.context
        if context is None:
            context = contextvars.copy_context()
        watch = _ChildWatch(
            subagent_id=subagent_id,
            child_session_id=child_session_id,
            parent_agent=binding.parent_agent,
            parent_session_id=binding.parent_session_id,
            total_seconds=total_seconds,
            control_context=context.copy(),
            scope=binding,
        )
        with self._lock:
            if self._closed:
                return
            key = watch.key
            existing = self._children.get(key)
            if existing is not None:
                # Never merge a recycled native ID with a different child session.
                if existing.child_session_id != child_session_id:
                    return
                return
            self._children[key] = watch
            binding.child_ids.add(subagent_id)
        self._ensure_scheduler(context)

    def on_subagent_stop(self, **payload: Any) -> None:
        """Retire only the exact completed child under its exact parent session."""
        if self.closed or not self._same_home():
            return
        parent_session_id = _safe_identifier(payload.get("parent_session_id"))
        child_session_id = _safe_identifier(payload.get("child_session_id"))
        if parent_session_id is None or child_session_id is None:
            return
        with self._lock:
            for key, watch in list(self._children.items()):
                if (watch.parent_session_id == parent_session_id
                        and watch.child_session_id == child_session_id):
                    self._children.pop(key, None)
        self._stop_scheduler_if_idle()

    def _stop_scheduler_if_idle(self) -> None:
        with self._lock:
            if self._children or self._pending_dispatches or self._scheduler is None:
                return
            scheduler, self._scheduler = self._scheduler, None
        try:
            scheduler.stop()
        except Exception:
            logger.debug("idle native watchdog scheduler shutdown failed", exc_info=True)

    def _ensure_scheduler(self, context: contextvars.Context) -> None:
        with self._lock:
            if self._closed or self._scheduler is not None:
                return
            try:
                scheduler_context = context.copy()
                # A long-lived scheduler must not retain the dispatch binding
                # (and its whole parent agent) after the last child finishes.
                scheduler_context.run(_ACTIVE_DISPATCH.set, None)
                scheduler = self.scheduler_factory(self.poll_once, self.poll_interval, scheduler_context)
                self._scheduler = scheduler
                scheduler.start()
            except Exception:
                self._scheduler = None
                logger.debug("native watchdog scheduler could not start", exc_info=True)

    def _context_is_owned(self, watch: _ChildWatch) -> bool:
        try:
            if not self._same_home() or self.get_active_parent() is not watch.parent_agent:
                return False
            # The exact captured parent object/profile is authority. Its durable
            # session ID may legitimately rotate on compression; native list/stop
            # still verifies ownership of its spawn tree at the action boundary.
            return _safe_identifier(getattr(watch.parent_agent, "session_id", None)) is not None
        except Exception:
            return False

    def _call_control(self, watch: _ChildWatch, action: str) -> Any:
        """Invoke only the native owned control action in the captured profile context."""
        context = watch.control_context.copy()

        def invoke() -> Any:
            token = _ACTIVE_DISPATCH.set(None)
            try:
                if not self._context_is_owned(watch):
                    raise RuntimeError("native watchdog owner/profile binding changed")
                if action == "list":
                    return self.delegate_task(action="list", parent_agent=watch.parent_agent)
                if action == "stop":
                    return self.delegate_task(
                        action="stop", subagent_id=watch.subagent_id,
                        parent_agent=watch.parent_agent,
                    )
                raise ValueError("unsupported native delegate control action")
            finally:
                _ACTIVE_DISPATCH.reset(token)

        return context.run(invoke)

    def poll_once(self) -> None:
        """Poll each exact parent through native list; never read Hermes private registries."""
        with self._lock:
            if self._closed:
                return
            watches = list(self._children.values())
        groups: dict[int, tuple[Any, list[_ChildWatch]]] = {}
        for watch in watches:
            identity = id(watch.parent_agent)
            if identity not in groups:
                groups[identity] = (watch.parent_agent, [])
            groups[identity][1].append(watch)

        for _identity, (_parent, group) in groups.items():
            if not group:
                continue
            try:
                owned = _parse_owned_list(self._call_control(group[0], "list"))
            except Exception:
                owned = None
            if owned is None:
                continue
            try:
                now = float(self.monotonic())
                if not math.isfinite(now):
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            for watch in group:
                should_attempt = False
                with self._lock:
                    if self._closed or self._children.get(watch.key) is not watch:
                        continue
                    entry = owned.get(watch.subagent_id)
                    if entry is None:
                        if watch.registered:
                            self._children.pop(watch.key, None)
                        # Not yet registered means the native child may still be queued.
                        continue
                    watch.registered = True
                    if watch.deadline is None and entry.get("status") != "queued":
                        running = entry.get("running_seconds")
                        if _valid_nonnegative_number(running):
                            watch.first_running_seconds = running
                            watch.deadline = _deadline_after_observation(
                                now, watch.total_seconds, running,
                            )
                    should_attempt = (
                        entry.get("status") == "running"
                        and watch.deadline is not None
                        and now >= watch.deadline
                        and not watch.stop_attempted
                    )
                if should_attempt:
                    self._attempt_timeout_stop(watch)
        self._stop_scheduler_if_idle()

    def _attempt_timeout_stop(self, watch: _ChildWatch) -> None:
        """Re-list immediately before stop, then report only request acceptance."""
        with self._lock:
            if (self._closed or self._children.get(watch.key) is not watch
                    or watch.stop_attempted or watch.deadline is None):
                return
        try:
            latest = _parse_owned_list(self._call_control(watch, "list"))
        except Exception:
            latest = None
        if latest is None:
            return
        current = latest.get(watch.subagent_id)
        if current is None:
            with self._lock:
                if self._children.get(watch.key) is watch and watch.registered:
                    self._children.pop(watch.key, None)
            return
        if current.get("status") != "running":
            return

        with self._control_lock:
            with self._lock:
                if (self._closed or self._children.get(watch.key) is not watch
                        or watch.stop_attempted or watch.deadline is None):
                    return
                try:
                    now = float(self.monotonic())
                except (TypeError, ValueError, OverflowError):
                    return
                if not math.isfinite(now) or now < watch.deadline:
                    return
                # A response loss/race must not cause repeated interrupt requests.
                watch.stop_attempted = True
            try:
                response = self._call_control(watch, "stop")
                outcome = self._stop_request_outcome(response, watch.subagent_id)
            except Exception:
                outcome = "unknown"
            with self._lock:
                if self._children.get(watch.key) is watch:
                    watch.stop_outcome = outcome
            self._write_evidence({
                "parent_session_id": watch.parent_session_id,
                "child_session_id": watch.child_session_id,
                "child_subagent_id": watch.subagent_id,
                "total_seconds": watch.total_seconds,
                "running_seconds": watch.first_running_seconds,
                "request_outcome": outcome,
            })

    @staticmethod
    def _stop_request_outcome(response: Any, subagent_id: str) -> str:
        payload = _response_dict(response)
        if (payload and "error" not in payload and payload.get("action") == "stop"
                and payload.get("subagent_id") == subagent_id
                and payload.get("status") == "interrupt_requested"):
            return "accepted"
        if payload is not None and "error" in payload:
            return "rejected"
        return "unknown"

    def _evidence_path(self) -> Path:
        if self.home.is_symlink() or self.home.resolve(strict=True) != self.home:
            raise ValueError("unsafe profile home")
        current = self.home
        for part in ("plugin-data", "model-router"):
            parent = current
            current = parent / part
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            if current.is_symlink():
                raise ValueError("unsafe evidence directory")
            resolved = current.resolve(strict=True)
            if os.path.normcase(str(resolved.parent)) != os.path.normcase(str(parent.resolve(strict=True))):
                raise ValueError("evidence directory escaped profile home")
            current = resolved
        path = current / EVIDENCE_NAME
        if path.is_symlink():
            raise ValueError("unsafe evidence file")
        if path.exists():
            resolved = path.resolve(strict=True)
            if os.path.normcase(str(resolved.parent)) != os.path.normcase(str(current)):
                raise ValueError("evidence file escaped profile home")
        return path

    def _clean_evidence(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        parent_session_id = _safe_identifier(value.get("parent_session_id"))
        child_session_id = _safe_identifier(value.get("child_session_id"))
        subagent_id = _safe_identifier(value.get("child_subagent_id"))
        total = value.get("total_seconds")
        running = value.get("running_seconds")
        outcome = value.get("request_outcome")
        if (parent_session_id is None or child_session_id is None or subagent_id is None
                or not _valid_nonnegative_number(total)
                or (running is not None and not _valid_nonnegative_number(running))
                or not isinstance(outcome, str)
                or outcome not in {"accepted", "rejected", "unknown"}):
            return None
        try:
            timestamp = float(self.wall_clock())
            if not math.isfinite(timestamp):
                timestamp = 0.0
        except (TypeError, ValueError, OverflowError):
            timestamp = 0.0
        return {
            "schema": 1,
            "kind": "native_total_timeout_stop",
            "timestamp": timestamp,
            "parent_session_id": parent_session_id,
            "child_session_id": child_session_id,
            "child_subagent_id": subagent_id,
            "total_seconds": total,
            "running_seconds": running,
            "request_outcome": outcome,
        }

    def _write_evidence(self, value: Mapping[str, Any]) -> bool:
        """Atomically retain a bounded, prompt-free private JSONL timeout record."""
        row = self._clean_evidence(value)
        if row is None:
            return False
        with self._evidence_lock:
            temporary: Path | None = None
            try:
                path = self._evidence_path()
                rows: list[dict[str, Any]] = []
                if path.exists():
                    with path.open("rb") as stream:
                        raw = stream.read(MAX_EVIDENCE_BYTES + 1)
                    if len(raw) <= MAX_EVIDENCE_BYTES:
                        for line in raw.decode("utf-8", errors="strict").splitlines():
                            try:
                                prior = json.loads(line)
                            except (ValueError, json.JSONDecodeError):
                                continue
                            cleaned = self._clean_evidence(prior)
                            if (cleaned is not None and type(prior.get("schema")) is int
                                    and prior.get("schema") == 1
                                    and prior.get("kind") == "native_total_timeout_stop"):
                                # Preserve the original timestamp instead of restamping history.
                                cleaned["timestamp"] = prior.get("timestamp", cleaned["timestamp"])
                                if _valid_nonnegative_number(cleaned["timestamp"]):
                                    rows.append(cleaned)
                rows.append(row)
                encoded_rows: list[bytes] = []
                for item in rows[-MAX_EVIDENCE_RECORDS:]:
                    encoded_rows.append((json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                while encoded_rows and sum(map(len, encoded_rows)) > MAX_EVIDENCE_BYTES:
                    encoded_rows.pop(0)
                content = b"".join(encoded_rows)
                temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                if path.is_symlink():
                    raise ValueError("unsafe evidence file")
                os.replace(temporary, path)
                temporary = None
                return True
            except Exception:
                logger.debug("native watchdog timeout evidence could not be stored", exc_info=True)
                return False
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def close(self) -> None:
        """Stop this plugin's monitor and release its references; never stop children."""
        with self._control_lock:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                scheduler = self._scheduler
                self._scheduler = None
                self._children.clear()
            if scheduler is not None:
                try:
                    scheduler.stop()
                except Exception:
                    logger.debug("native watchdog scheduler shutdown failed", exc_info=True)


def register_native_watchdog(
    ctx: Any,
    home: str | Path,
    *,
    read_timeouts_fn: Callable[[Path], Mapping[str, Any]] | None = None,
    get_hermes_home_fn: Callable[[], Any] | None = None,
    get_active_parent_fn: Callable[[], Any] | None = None,
    delegate_task_fn: Callable[..., Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    scheduler_factory: Callable[[Callable[[], None], float, contextvars.Context], Any] | None = None,
) -> NativeWatchdog | None:
    """Register a dormant profile-local observer; snapshot limits on each spawn.

    A zero policy starts no watcher. Keeping the observer registered lets later
    UI saves affect NEW children without changing existing budgets or needing
    a process restart. This function never edits Hermes config.yaml.
    """
    try:
        profile_home = _canonical_home(home)
        reader = read_timeouts_fn or _read_timeouts
        try:
            settings = reader(profile_home)
            total_seconds = settings.get("delegate_total_seconds") if isinstance(settings, Mapping) else 0
            if not _valid_nonnegative_number(total_seconds):
                total_seconds = 0
        except Exception:
            total_seconds = 0
            logger.warning("native total-runtime settings unavailable at registration; they will be checked on spawn")
        watchdog = NativeWatchdog(
            profile_home,
            total_seconds,
            get_hermes_home=get_hermes_home_fn or _get_hermes_home,
            get_active_parent=get_active_parent_fn or _get_active_parent,
            delegate_task=delegate_task_fn or _delegate_task,
            monotonic=monotonic,
            wall_clock=wall_clock,
            scheduler_factory=scheduler_factory,
            read_timeouts_fn=reader,
        )
    except Exception:
        # An unavailable settings module or malformed profile must not mutate
        # native config or alter real delegate_task execution.
        logger.debug("native total watchdog is unavailable for this profile", exc_info=True)
        return None

    registrations: list[Any] = []
    try:
        registrations.append(ctx.register_middleware("tool_execution", watchdog.middleware))
        registrations.append(ctx.register_hook("subagent_start", watchdog.on_subagent_start))
        registrations.append(ctx.register_hook("subagent_stop", watchdog.on_subagent_stop))
        registrations.append(ctx.on_unload(watchdog.close))
    except Exception:
        watchdog.close()
        for registration in reversed(registrations):
            dispose = getattr(registration, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass
        return None
    return watchdog
