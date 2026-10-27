"""Profile-bound, opt-in routed coding jobs.

The router snapshots operator-selected routes and starts one detached worker.
It never edits Hermes configuration and never treats route evidence as a
semantic review result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

from . import task_presentation
from .timeouts import DEFAULT_ROUTED_TOTAL_SECONDS

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PLUGIN_ROOT / "lib" / "run_routed_agent.py"
WORKER_PATH = Path(__file__).with_name("job_worker.py")
TEMPLATE_CACHE_PATH = PLUGIN_ROOT / "lib" / "template-cache.json"
PROFILE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
PROVIDER_TOKEN = PROFILE_TOKEN
MODEL_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
ROUTING_PURPOSES = {
    "implementation": ("LIGHTWEIGHT", "implementation", "none"),
    "mechanical": ("LIGHTWEIGHT", "mechanical", "mechanical"),
    "preliminary-review": ("LIGHTWEIGHT", "review", "none"),
    "plan": ("HEAVYWEIGHT", "plan", "none"),
    "semantic-final": ("HEAVYWEIGHT", "review", "semantic-final"),
    "independent-review": ("HEAVYWEIGHT", "review", "independent-review"),
}
ROUTED_ROLE_TIMEOUTS_SUPPORTED = True

RUNNER_OPERATOR_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}


class RoutingError(ValueError):
    """A routed job could not be safely prepared or read."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump()
        if isinstance(result, dict):
            return result
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return attrs
    names = (
        "current_profile",
        "profiles",
        "revision",
        "name",
        "drift",
        "enabled",
        "heavy",
        "light",
        "fallback",
        "provider",
        "model",
        "reasoning",
        "timeout_seconds",
        "light_timeout_seconds",
        "heavy_timeout_seconds",
    )
    result = {name: getattr(value, name) for name in names if hasattr(value, name)}
    return result


def _safe_profile_name(value: Any) -> str:
    if not isinstance(value, str) or PROFILE_TOKEN.fullmatch(value) is None or value in {".", ".."}:
        raise RoutingError("active profile name is invalid")
    return value


def _safe_route(value: Any, label: str) -> dict[str, str]:
    route = _as_mapping(value)
    if set(route) != {"provider", "model", "reasoning"}:
        raise RoutingError(f"{label} must contain exactly provider, model, and reasoning")
    provider = route.get("provider")
    model = route.get("model")
    reasoning = route.get("reasoning")
    if (
        not isinstance(provider, str)
        or not provider
        or provider != provider.strip()
        or provider.casefold() == "keep"
        or PROVIDER_TOKEN.fullmatch(provider) is None
    ):
        raise RoutingError(f"{label}.provider is not a safe literal token")
    if (
        not isinstance(model, str)
        or not model
        or model != model.strip()
        or model.casefold() == "keep"
        or MODEL_TOKEN.fullmatch(model) is None
    ):
        raise RoutingError(f"{label}.model is not a safe literal token")
    if (
        not isinstance(reasoning, str)
        or not reasoning
        or reasoning != reasoning.strip()
        or PROFILE_TOKEN.fullmatch(reasoning) is None
    ):
        raise RoutingError(f"{label}.reasoning is not a safe literal token")
    return {"provider": provider, "model": model, "reasoning": reasoning}


def _route_for_runner(route: dict[str, str]) -> dict[str, str]:
    return {
        "provider": route["provider"],
        "model_id": route["model"],
        "reasoning_effort": route["reasoning"],
    }


def _write_json(path: Path, data: dict[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        if os.name != "nt":
            os.chmod(path, 0o600)
        return
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _base_from_root(value: Any) -> Path:
    path = Path(value).expanduser()
    if path.name == "settings.json" and path.parent.name == "model-router":
        path = path.parent.parent.parent
    elif path.name == "model-router" and path.parent.name == "plugin-data":
        path = path.parent.parent
    elif path.name == "plugin-data":
        path = path.parent
    elif path.name == "profiles":
        path = path.parent
    elif path.parent.name == "profiles":
        # A profile-scoped home is already the requested home when the name
        # matches; otherwise its containing Hermes base is the safe anchor.
        path = path.parent.parent
    return path.resolve()


def _profile_home(service: Any, profile: str) -> Path:
    """Resolve only the configured Hermes base or the bound active profile."""
    root: Any = None
    for attr in ("base", "hermes_base", "home", "root"):
        candidate = getattr(service, attr, None)
        if candidate is not None:
            root = candidate
            break
    if root is not None:
        base = _base_from_root(root)
    else:
        env_home = os.environ.get("HERMES_HOME")
        if env_home:
            active_home = Path(env_home).expanduser().resolve()
            if profile == "default":
                if active_home.parent.name == "profiles":
                    base = active_home.parent.parent
                else:
                    base = active_home
            elif active_home.name == profile and active_home.parent.name == "profiles":
                base = active_home.parent.parent
            elif active_home.parent.name == "profiles":
                base = active_home.parent.parent
            else:
                base = active_home
        else:
            local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
            base = (local / "hermes").resolve()

    if profile == "default":
        home = base
    else:
        home = base / "profiles" / profile
    resolved = home.resolve()
    if profile != "default":
        expected_parent = (base / "profiles").resolve()
        if resolved.parent != expected_parent or resolved.name != profile:
            raise RoutingError("active profile resolves outside its Hermes profile directory")
    return resolved


def _jobs_root(home: Path) -> Path:
    """Reject profile job roots redirected by pre-existing symlinks."""
    current = home
    for part in ("plugin-data", "model-router", "jobs"):
        current = current / part
        if current.is_symlink():
            raise RoutingError("profile job directory must not contain symlinks")
        if current.resolve().parent != current.parent.resolve():
            raise RoutingError("profile job directory resolves outside the active profile")
    if not current.resolve().is_relative_to(home.resolve()):
        raise RoutingError("profile job directory resolves outside the active profile")
    return current


def _service_profile(service: Any) -> str:
    value = getattr(service, "active_profile", None)
    value = value() if callable(value) else value
    return _safe_profile_name(value)


def _check_profile_drift(service: Any, profile: str) -> None:
    status_method = getattr(service, "status", None)
    if not callable(status_method):
        raise RoutingError("routing service does not expose profile status")
    status = _as_mapping(status_method())
    current = status.get("current_profile")
    if current != profile:
        raise RoutingError("active profile changed while preparing the routed job")
    profiles = status.get("profiles")
    if not isinstance(profiles, (list, tuple)):
        raise RoutingError("routing service did not provide profile drift status")
    selected = None
    for item in profiles:
        info = _as_mapping(item)
        if info.get("name") == profile:
            selected = info
            break
    if selected is None:
        raise RoutingError("active profile is not available in routing status")
    drift = selected.get("drift")
    if not isinstance(drift, (list, tuple)):
        raise RoutingError("active profile drift status is invalid")
    if any(not isinstance(item, str) for item in drift):
        raise RoutingError("active profile drift status is invalid")
    model_drift = [
        item
        for item in drift
        if isinstance(item, str)
        and (item == "actual_models_unavailable" or item.startswith("models."))
    ]
    if model_drift:
        raise RoutingError("routed job denied because the active profile has model drift")


def _fallback_policy_is_approved(value: Any) -> bool:
    policy = _as_mapping(value)
    return (
        policy.get("trigger") == "subscription_exhaustion_before_tools"
        and type(policy.get("max_retries")) is int
        and policy.get("max_retries") == 1
        and policy.get("approved") is True
    )


def _build_job_cache(
    primary: dict[str, dict[str, str]],
    fallbacks: dict[str, dict[str, str] | None],
    fallback_enabled: bool,
) -> dict[str, Any]:
    try:
        cache = json.loads(TEMPLATE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoutingError("cannot load the bundled routing cache") from exc
    if not isinstance(cache, dict) or not isinstance(cache.get("models"), list):
        raise RoutingError("bundled routing cache has an invalid shape")

    cache["operator_routes"] = {
        role: _route_for_runner(primary[role])
        for role in ("HEAVYWEIGHT", "LIGHTWEIGHT")
    }
    cache["operator_route_source"] = "desktop-model-router"
    cache["fallback_routes"] = {}
    by_key = {
        entry.get("key"): entry
        for entry in cache["models"]
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    }
    if fallback_enabled:
        for role in ("HEAVYWEIGHT", "LIGHTWEIGHT"):
            route = fallbacks[role]
            if route is None:
                continue
            key = f"{route['provider']}/{route['model']}"
            cache["models"] = [
                item
                for item in cache["models"]
                if not (isinstance(item, dict) and item.get("key") == key)
            ]
            cache["models"].append(
                {
                    "key": key,
                    "provider": route["provider"],
                    "model_id": route["model"],
                    "role": role,
                    "status": "active",
                    "reasoning_effort": route["reasoning"],
                }
            )
            cache["fallback_routes"][role] = key
    return cache


def _bounded_timeout(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RoutingError("timeout must be a nonnegative number of seconds")
    try:
        timeout = float(value)
    except (OverflowError, ValueError) as exc:
        raise RoutingError("timeout must be a nonnegative finite number of seconds") from exc
    if not math.isfinite(timeout) or timeout < 0:
        raise RoutingError("timeout must be a nonnegative finite number of seconds")
    return timeout


def _job_file(job_dir: Path, filename: str) -> Path:
    path = job_dir / filename
    if path.is_symlink() or path.resolve().parent != job_dir.resolve():
        raise RoutingError("job artifact path is not contained in its job directory")
    return path


def _pid_alive(pid: Any) -> bool:
    from .processes import is_process_alive
    return is_process_alive(pid)


def _validate_routed_fast_snapshot(value: Any, *, profile: str, runtime: Any) -> dict[str, Any] | None:
    """Bind an internal Fast snapshot to this host's exact profile and parent."""
    if value is None:
        return None
    if runtime is None:
        raise RoutingError("Fast inheritance requires an active host runtime")
    parent_session_id = getattr(runtime, "parent_session_id", None)
    if not isinstance(parent_session_id, str) or not parent_session_id:
        raise RoutingError("Fast inheritance requires the exact active parent session")
    try:
        from .fast_inheritance import validate_fast_snapshot
    except (ImportError, AttributeError) as exc:
        raise RoutingError("Fast inheritance is unavailable for this registered plugin") from exc
    try:
        validated = validate_fast_snapshot(
            value, profile=profile, parent_session_id=parent_session_id
        )
    except (TypeError, ValueError) as exc:
        raise RoutingError("Fast snapshot does not match the active profile and parent") from exc
    if not isinstance(validated, dict) or validated != value:
        raise RoutingError("Fast snapshot validation did not preserve the exact intent")
    return validated


def _worker_runtime(working_dir: Path) -> tuple[Path, list[str], str]:
    """Preflight one already-loaded native runtime; never search for a new one."""
    def reject() -> NoReturn:
        raise RoutingError("trusted worker interpreter binding is unavailable")

    def plain_path(value, *, directory=False):
        if not isinstance(value, (str, Path)) or not value:
            reject()
        path = Path(value)
        if not path.is_absolute():
            reject()
        for part in (path, *path.parents):
            junction = getattr(part, "is_junction", None)
            if (part.is_symlink() or (callable(junction) and junction())
                    or part.resolve(strict=False) != part.absolute()):
                reject()
        if not (path.is_dir() if directory else path.is_file()):
            reject()
        return path

    try:
        bootstrap = sys.modules.get("hermes_bootstrap")
        bootstrap_file = plain_path(getattr(bootstrap, "__file__", None))
        if plain_path(getattr(getattr(bootstrap, "__spec__", None), "origin", None)) != bootstrap_file:
            reject()
        core = plain_path(bootstrap_file.parent, directory=True)
        for member in ("run_agent.py", "agent/agent_init.py", "hermes_cli/runtime_provider.py"):
            plain_path(core / member)

        def checked_worker_core(candidate):
            candidate = plain_path(candidate, directory=True)
            for other in (working_dir, PLUGIN_ROOT.resolve(strict=True)):
                if candidate == other or candidate in other.parents or other in candidate.parents:
                    reject()
            for member in ("hermes_bootstrap.py", "run_agent.py", "agent/agent_init.py",
                           "hermes_cli/runtime_provider.py"):
                plain_path(candidate / member)
            return candidate

        prefix = plain_path(sys.prefix, directory=True)
        base = plain_path(sys.base_prefix, directory=True)
        bound_host = prefix != base
        if bound_host:
            owner = (prefix.parent / "workspace" if prefix.name.casefold() == "venv"
                     and prefix.parent.parent.name.casefold() == "environments" else prefix.parent)
            if prefix.name.casefold() not in {".venv", "venv"} or plain_path(owner, directory=True) != core:
                reject()
            executable = Path(sys.executable)
            bin_dir = prefix / ("Scripts" if os.name == "nt" else "bin")
            entries = ({"python.exe"} if os.name == "nt" else {
                "python", f"python{sys.version_info.major}",
                f"python{sys.version_info.major}.{sys.version_info.minor}",
                f"python{sys.version_info.major}.{sys.version_info.minor}{getattr(sys, 'abiflags', '')}",
            })
            entry_name = executable.name.casefold() if os.name == "nt" else executable.name
            if (not executable.is_absolute() or executable.parent != bin_dir
                    or entry_name not in entries or not executable.is_file()):
                reject()
            # Preserve an existing POSIX venv executable symlink, not its base
            # target. This path needs no PM-adoption authority to remain valid.
        pm_modules = ("pm.environments", "pm.environments_adopt")
        cold_pm = (not bound_host and pm_modules[0] in sys.modules
                   and pm_modules[1] not in sys.modules)
        if not all(name in sys.modules for name in pm_modules) and not cold_pm:
            if bound_host or not any(name in sys.modules for name in pm_modules):
                return checked_worker_core(core), [str(core)], sys.executable
            reject()

        # Authorize native PM functions only from the source already running in
        # this host. Do not import a replacement module from cwd or PYTHONPATH.
        functions = {}
        for name, relative, members in (
            ("pm.environments", "pm/environments.py", ("site_packages", "venv_command", "venv_python", "install_state_dir")),
            ("pm.environments_adopt", "pm/environments_adopt.py", ("running_environment",)),
        ):
            if cold_pm and name == "pm.environments_adopt":
                continue  # Do not import an optional helper or change host state.
            module = sys.modules.get(name)
            expected = plain_path(core / relative)
            if (plain_path(getattr(module, "__file__", None)) != expected
                    or plain_path(getattr(getattr(module, "__spec__", None), "origin", None)) != expected):
                reject()
            for member in members:
                function = getattr(module, member, None)
                if (not callable(function) or getattr(function, "__module__", None) != name
                        or getattr(function, "__globals__", None) is not module.__dict__):
                    reject()
                functions[member] = function

        def loaded_memberships(generations):
            memberships = set()
            for candidate in generations.glob("*/venv"):
                candidate_packages = functions["site_packages"](candidate)
                for item in sys.path:
                    if item and Path(item).resolve(strict=False) == candidate_packages.resolve(strict=False):
                        # Check raw spellings; an alias must not hide a link.
                        plain_path(Path(item), directory=True)
                        plain_path(candidate_packages, directory=True)
                        memberships.add(plain_path(candidate, directory=True))
            return memberships

        if cold_pm:
            # The normal bootstrap loads environments, not necessarily adopt.
            # Reuse the existing imported-generation proof under the verified
            # native install root. No selected-new/PATH search or module load.
            generations = plain_path(functions["install_state_dir"](core) / "environments", directory=True)
            memberships = loaded_memberships(generations)
            if len(memberships) != 1:
                reject()
            environment = next(iter(memberships))
        else:
            environment = functions["running_environment"](core)
        runtime_paths = [str(core)]
        if environment is not None:
            runtime_paths.append(str(functions["site_packages"](environment).resolve(strict=True)))
        if bound_host:
            return checked_worker_core(core), runtime_paths, sys.executable
        if environment is None:
            # No native PM generation: preserve the existing launch behavior.
            # The unchanged child trust gate still refuses an unbound runtime.
            return checked_worker_core(core), runtime_paths, sys.executable

        environment = plain_path(environment, directory=True)
        if (environment.name.casefold() != "venv"
                or environment.parent.parent.name.casefold() != "environments"):
            reject()
        plain_path(environment / "pyvenv.cfg")
        packages = plain_path(functions["site_packages"](environment), directory=True)
        generations = plain_path(functions["install_state_dir"](core) / "environments", directory=True)
        if environment.parent.parent != generations:
            reject()
        memberships = loaded_memberships(generations)
        if memberships != {environment}:
            reject()
        native = functions["venv_command"](core, environment)
        if not isinstance(native, (list, tuple)) or len(native) != 1:
            reject()  # Never flatten sealed store-Python/-S/entry/site-packages argv.
        executable = plain_path(native[0])
        if executable != functions["venv_python"](environment):
            reject()
        # Native PM owns this generation under the parent's install. Its build
        # snapshot is the interpreter-owned child source, not the parent checkout.
        worker_core = checked_worker_core(environment.parent / "workspace")
        plain_path(worker_core / "pyproject.toml")
        plain_path(worker_core / "uv.lock")
        return worker_core, [str(worker_core), str(packages)], native[0]
    except RoutingError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
        reject()


class Router:
    """Start and inspect detached jobs for the active Hermes profile only."""

    def __init__(self, service: Any = None, *, runtime: Any = None, fast_snapshot: Any = None):
        if service is None:
            try:
                from .service import Service
            except ImportError as exc:  # pragma: no cover - package assembly guard
                raise RuntimeError("model-router Service is not available") from exc
            service = Service()
        self.service = service
        self.runtime = runtime
        self.fast_snapshot = _validate_routed_fast_snapshot(
            fast_snapshot, profile=_service_profile(service), runtime=runtime
        )

    def start(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Retired public entry point: stale callers must never launch a process."""
        return {
            "error": "start_retired",
            "status": "retired",
            "message": "Use native delegate_task with an explicitly selected model-router backend.",
        }

    def join(self, job_id: str, *, wait_timeout: int | None = None) -> dict[str, Any]:
        """Explicitly await a silent owned job, without starting or waking any turn."""
        entered_at = time.monotonic()
        from .joining import JoinError, owner_binding, read_record, validate_wait_timeout, wait_owned, reconcile_terminal
        validate_wait_timeout(wait_timeout)
        profile = _service_profile(self.service)
        home = _profile_home(self.service, profile)
        owner = owner_binding(self.runtime, profile, home)
        if not isinstance(job_id, str):
            raise JoinError("job_id must be a canonical UUID")
        try:
            canonical = str(uuid.UUID(job_id))
        except ValueError:
            raise JoinError("job_id must be a canonical UUID") from None
        if canonical != job_id:
            raise JoinError("job_id must be a canonical UUID")
        root = _jobs_root(home)
        directory = root / job_id
        if directory.is_symlink() or directory.resolve().parent != root.resolve():
            raise JoinError("join job directory is outside the active profile")
        snapshot = read_record(_job_file(directory, "snapshot.json"))
        stored_owner = snapshot.get("join_owner")
        if (snapshot.get("job_id") != job_id or snapshot.get("profile") != profile
                or snapshot.get("parent_session_id") != owner["parent_session_id"]
                or snapshot.get("completion_mode") != "join"
                or not isinstance(stored_owner, dict)
                or type(stored_owner.get("schema")) is not int or stored_owner != owner):
            raise JoinError("job is not a join-mode job of this exact profile/session owner")
        launch = read_record(_job_file(directory, "launch.json"))
        if launch.get("join_available") is not True:
            raise JoinError("durable join binding was not published")
        outcome = wait_owned(self.runtime, owner, launch, wait_timeout=wait_timeout, entered_at=entered_at)
        if outcome["join_status"] == "joined":
            # Silent jobs need no native acknowledgement. Read the artifact,
            # then reconcile current ownership/termination before returning it.
            output = self.status(job_id)
            outcome = reconcile_terminal(self.runtime, owner, launch, outcome)
            if outcome["join_status"] != "joined":
                return {"job_id": job_id, "profile": profile, "status": "unverified",
                        "route_verified": False, "completion_mode": "join", **outcome}
            if output.get("status") == "completed" and (
                    outcome.get("native_exit_code") != 0
                    or outcome.get("native_completion_reason") != "exited"
                    or outcome.get("native_snapshot_changed") is True):
                output["status"] = "unverified"
                output["route_verified"] = False
                output["join_warning"] = "native termination does not confirm the runner result"
        else:
            output = {"job_id": job_id, "profile": profile, "route_verified": False,
                      "status": "running" if outcome["join_status"] == "pending" else "unverified"}
        return {**output, "completion_mode": "join", **outcome}

    def status(self, job_id: str) -> dict[str, Any]:
        if not isinstance(job_id, str):
            raise RoutingError("job_id must be a UUID")
        try:
            parsed = uuid.UUID(job_id)
        except (ValueError, AttributeError) as exc:
            raise RoutingError("job_id must be a UUID") from exc
        if str(parsed) != job_id:
            raise RoutingError("job_id must be a canonical UUID")
        profile = _service_profile(self.service)
        home = _profile_home(self.service, profile)
        job_dir = home / "plugin-data" / "model-router" / "jobs" / job_id
        if job_dir.is_symlink():
            raise RoutingError("job directory is not a safe profile-local directory")
        _jobs_root(home)
        job_dir = job_dir.resolve()
        expected_parent = _jobs_root(home).resolve()
        if job_dir.parent != expected_parent:
            raise RoutingError("job directory resolves outside the active profile")

        def read_json(name: str) -> dict[str, Any] | None:
            path = _job_file(job_dir, name)
            if not path.is_file():
                return None
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None

        snapshot = read_json("snapshot.json")
        if snapshot is None or snapshot.get("job_id") != job_id or snapshot.get("profile") != profile:
            return {"job_id": job_id, "status": "unverified", "profile": profile}
        state = read_json("state.json") or {}
        launch = read_json("launch.json") or {}
        result = read_json("runner-result.json")
        route_evidence = snapshot.get("model_provider_evidence")
        if not isinstance(route_evidence, dict):
            route_evidence = {}
        snapshot_purpose = snapshot.get("purpose")
        if not isinstance(snapshot_purpose, str):
            snapshot_purpose = ""
        try:
            display_title = task_presentation.validate_title(snapshot.get("title"), snapshot_purpose)
        except ValueError:
            display_title = task_presentation.validate_title(None, snapshot_purpose)
        output: dict[str, Any] = {
            "job_id": job_id,
            "profile": profile,
            "purpose": snapshot.get("purpose"),
            "title": display_title,
            "settings_revision": snapshot.get("settings_revision"),
            "route_class": snapshot.get("route_class"),
            "model_provider_evidence": route_evidence,
            "route_verified": False,
        }
        if result is not None:
            code = result.get("exit_code")
            process_code = result.get("process_exit_code")
            evidence = result.get("session_evidence")
            if not isinstance(evidence, dict):
                evidence = {}
            effective_provider = result.get("effective_provider")
            effective_model = result.get("effective_model")
            actual_provider = evidence.get("provider", result.get("actual_provider"))
            actual_model = evidence.get("model", result.get("actual_model"))
            role = snapshot.get("route_class")
            allowed: list[dict[str, str]] = []
            requested = route_evidence.get("requested")
            if isinstance(requested, dict) and isinstance(requested.get(role), dict):
                allowed.append(requested[role])
            fallback = route_evidence.get("fallback")
            if (
                route_evidence.get("fallback_enabled") is True
                and isinstance(fallback, dict)
                and isinstance(fallback.get(role), dict)
            ):
                allowed.append(fallback[role])
            effective_allowed = any(
                route.get("provider") == effective_provider and route.get("model") == effective_model
                for route in allowed
            )
            verified = (
                evidence.get("status") == "verified"
                and result.get("config_unchanged") is True
                and effective_allowed
                and actual_provider == effective_provider
                and actual_model == effective_model
            )
            if result.get("execution_mode") == "scoped_sdk":
                verified = (
                    verified
                    and result.get("completed") is True
                    and result.get("closure_complete") is True
                    and result.get("evidence_complete") is True
                )
            route_evidence = dict(route_evidence)
            route_evidence["actual"] = {
                "provider": actual_provider,
                "model": actual_model,
                "evidence_status": evidence.get("status", "unverified"),
                "config_unchanged": result.get("config_unchanged"),
            }
            output["model_provider_evidence"] = route_evidence
            output["route_verified"] = bool(verified and code == 0 and process_code == 0)
            answer_text = result.get("final_response", result.get("stdout"))
            if not isinstance(answer_text, str):
                answer_text = ""
            output["answer"] = answer_text[:48000]
            output["answer_truncated"] = len(answer_text) > 48000
            output["artifact_path"] = str(_job_file(job_dir, "runner-result.json"))
            output["verification_kind"] = snapshot.get("verification_kind")
            output["verification_status"] = result.get("verification_status")
            output["effective_model"] = effective_model
            output["effective_provider"] = effective_provider
            output["actual_model"] = actual_model
            output["actual_provider"] = actual_provider
            output["fallback_used"] = result.get("fallback_used") is True
            if "fallback_reason" in result:
                output["fallback_reason"] = result.get("fallback_reason")
            if isinstance(result.get("attempts"), list):
                output["attempts"] = result["attempts"]
            for evidence_field in (
                "timed_out", "timeout_stage", "process_tree_closed", "cleanup_verified", "terminal_attempt_id"
            ):
                if evidence_field in result:
                    output[evidence_field] = result[evidence_field]
            output["exit_code"] = code
            if isinstance(code, int) and not isinstance(code, bool) and code != 0:
                output["status"] = "failed"
            elif isinstance(code, int) and not isinstance(code, bool) and code == 0 and process_code == 0 and verified:
                output["status"] = "completed"
            elif isinstance(process_code, int) and not isinstance(process_code, bool) and process_code != 0:
                output["status"] = "failed"
            else:
                output["status"] = "unverified"
            output["started_at"] = result.get("started_at")
            output["finished_at"] = result.get("finished_at")
            return output

        if state.get("status") == "failed":
            output["status"] = "failed"
            output["error_type"] = state.get("error_type")
            output["finished_at"] = state.get("finished_at")
            output["timed_out"] = state.get("timed_out")
            output["process_tree_closed"] = state.get("process_tree_closed")
            output["cleanup_verified"] = state.get("cleanup_verified")
            return output
        pid = launch.get("worker_pid") or state.get("worker_pid")
        if _pid_alive(pid):
            output["status"] = "running"
        elif state.get("status") == "running":
            # A worker that vanished before producing the runner artifact is
            # not promoted to a fabricated success or a definite task failure.
            output["status"] = "unverified"
        else:
            output["status"] = "unverified"
        output["started_at"] = state.get("started_at") or launch.get("launched_at")
        output["finished_at"] = state.get("finished_at")
        return output
