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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
MAX_TIMEOUT_SECONDS = 900.0
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
        raise RoutingError("timeout must be a positive number of seconds")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise RoutingError("timeout must be a positive finite number of seconds")
    return min(timeout, MAX_TIMEOUT_SECONDS)


def _job_file(job_dir: Path, filename: str) -> Path:
    path = job_dir / filename
    if path.is_symlink() or path.resolve().parent != job_dir.resolve():
        raise RoutingError("job artifact path is not contained in its job directory")
    return path


def _pid_alive(pid: Any) -> bool:
    from .processes import is_process_alive
    return is_process_alive(pid)


class Router:
    """Start and inspect detached jobs for the active Hermes profile only."""

    def __init__(self, service: Any = None, *, runtime: Any = None):
        if service is None:
            try:
                from .service import Service
            except ImportError as exc:  # pragma: no cover - package assembly guard
                raise RuntimeError("model-router Service is not available") from exc
            service = Service()
        self.service = service
        self.runtime = runtime

    def start(
        self, purpose: str, prompt: str, cwd: str | Path, timeout: float = 600
    ) -> dict[str, Any]:
        if purpose not in ROUTING_PURPOSES:
            raise RoutingError(f"unsupported routing purpose: {purpose}")
        if not isinstance(prompt, str) or not prompt.strip():
            raise RoutingError("prompt must be a non-empty string")
        bounded_timeout = _bounded_timeout(timeout)
        if not isinstance(cwd, (str, Path)):
            raise RoutingError("working directory must be a path")
        working_dir = Path(cwd).expanduser().resolve()
        if not working_dir.is_dir():
            raise RoutingError("working directory does not exist")

        profile = _service_profile(self.service)
        _check_profile_drift(self.service, profile)
        config_method = getattr(self.service, "routing_config", None)
        if not callable(config_method):
            raise RoutingError("routing service does not expose routing configuration")
        config = _as_mapping(config_method(profile))
        if config.get("enabled") is not True:
            raise RoutingError("routing is disabled for the active profile")
        revision = config.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise RoutingError("active profile routing revision is invalid")
        primary = {
            "HEAVYWEIGHT": _safe_route(config.get("heavy"), "heavy"),
            "LIGHTWEIGHT": _safe_route(config.get("light"), "light"),
        }
        if primary["HEAVYWEIGHT"]["reasoning"] not in RUNNER_OPERATOR_EFFORTS or primary["LIGHTWEIGHT"]["reasoning"] not in RUNNER_OPERATOR_EFFORTS:
            raise RoutingError("selected primary reasoning effort is unsupported by the bundled route runner")
        if (
            primary["HEAVYWEIGHT"]["provider"],
            primary["HEAVYWEIGHT"]["model"],
        ) == (
            primary["LIGHTWEIGHT"]["provider"],
            primary["LIGHTWEIGHT"]["model"],
        ):
            raise RoutingError("enabled Heavy and Light routes must resolve to distinct models")
        fallback = _as_mapping(config.get("fallback"))
        configured_fallback_enabled = fallback.get("enabled")
        if not isinstance(configured_fallback_enabled, bool):
            raise RoutingError("fallback.enabled must be boolean")
        fallback_policy = config.get("fallback_policy")
        fallback_approved = _fallback_policy_is_approved(fallback_policy)
        fallback_enabled = configured_fallback_enabled and fallback_approved
        fallbacks: dict[str, dict[str, str] | None] = {}
        for role, key in (("HEAVYWEIGHT", "heavy"), ("LIGHTWEIGHT", "light")):
            value = fallback.get(key) if fallback_enabled else None
            fallbacks[role] = None if value is None else _safe_route(value, f"fallback.{key}")
        if fallback_enabled and any(fallbacks[role] is None for role in fallbacks):
            raise RoutingError("approved enabled fallback requires explicit Heavy and Light routes")
        for role, primary_route in primary.items():
            fallback_route = fallbacks[role]
            if fallback_route and (
                fallback_route["provider"], fallback_route["model"]
            ) == (primary_route["provider"], primary_route["model"]):
                raise RoutingError(f"fallback.{role} must differ from its primary route")

        home = _profile_home(self.service, profile)
        jobs_root = _jobs_root(home)
        job_id = str(uuid.uuid4())
        job_dir = jobs_root / job_id
        try:
            job_dir.mkdir(parents=True, exist_ok=False)
            if os.name != "nt":
                os.chmod(job_dir, 0o700)
        except OSError as exc:
            raise RoutingError("could not create the active profile job directory") from exc

        role, mode, verification_kind = ROUTING_PURPOSES[purpose]
        selected = primary[role]
        route_evidence = {
            "purpose_role": role,
            "requested": {name: dict(route) for name, route in primary.items()},
            "fallback_enabled": fallback_enabled,
            "fallback_policy": {
                "trigger": "subscription_exhaustion_before_tools",
                "max_retries": 1,
                "approved": fallback_approved,
            },
            "fallback": {
                name: (dict(route) if route is not None else None)
                for name, route in fallbacks.items()
            },
            "actual": None,
        }
        settings_digest = hashlib.sha256(
            json.dumps(
                {"revision": revision, "routes": route_evidence},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        snapshot = {
            "schema": 1,
            "job_id": job_id,
            "profile": profile,
            "settings_revision": revision,
            "purpose": purpose,
            "route_class": role,
            "runner_mode": mode,
            "parent_session_id": self.runtime.parent_session_id if self.runtime is not None else None,
            "verification_kind": verification_kind,
            "cwd": str(working_dir),
            "timeout_seconds": bounded_timeout,
            "created_at": _utc_now(),
            "settings_digest": settings_digest,
            "model_provider_evidence": route_evidence,
        }
        cache = _build_job_cache(primary, fallbacks, fallback_enabled)
        snapshot_path = _job_file(job_dir, "snapshot.json")
        prompt_path = _job_file(job_dir, "prompt.txt")
        cache_path = _job_file(job_dir, "routing-cache.json")
        log_path = _job_file(job_dir, "job.log")
        _write_json(snapshot_path, snapshot, exclusive=True)
        with prompt_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(prompt)
        if os.name != "nt":
            os.chmod(prompt_path, 0o600)
        _write_json(cache_path, cache, exclusive=True)
        with log_path.open("xb"):
            pass
        if os.name != "nt":
            os.chmod(log_path, 0o600)

        hermes_cli = shutil.which("hermes")
        if not hermes_cli:
            _write_json(
                _job_file(job_dir, "state.json"),
                {"status": "failed", "error_type": "HermesLauncherNotFound", "finished_at": _utc_now()},
                exclusive=True,
            )
            return {
                "job_id": job_id,
                "status": "failed",
                "profile": profile,
                "purpose": purpose,
                "settings_revision": revision,
                "route_class": role,
                "error_type": "HermesLauncherNotFound",
            }
        hermes_path = Path(hermes_cli).resolve()
        if not hermes_path.is_file():
            _write_json(
                _job_file(job_dir, "state.json"),
                {"status": "failed", "error_type": "HermesLauncherNotFound", "finished_at": _utc_now()},
                exclusive=True,
            )
            return {
                "job_id": job_id,
                "status": "failed",
                "profile": profile,
                "purpose": purpose,
                "settings_revision": revision,
                "route_class": role,
                "error_type": "HermesLauncherNotFound",
            }

        from tools.environments.local import served_profile_child_env
        import hermes_bootstrap
        from pm.environments import site_packages
        from pm.environments_adopt import running_environment
        child_env = served_profile_child_env(target_home=home, inherit_credentials=True)
        # The native helper intentionally strips Hermes-owned Python paths for
        # arbitrary terminal children. This child uses THIS exact interpreter
        # and runs Hermes: restore only the already-loaded host code/generation,
        # never the inherited/project PYTHONPATH or another selected generation.
        core_root = Path(hermes_bootstrap.__file__).resolve(strict=True).parent
        runtime_paths = [str(core_root)]
        environment = running_environment(core_root)
        if environment is not None:
            runtime_paths.append(str(site_packages(environment).resolve(strict=True)))
        child_env["PYTHONPATH"] = os.pathsep.join(runtime_paths)
        child_env["HERMES_HOME"] = str(home)
        child_env["HERMES_PROFILE"] = profile
        command = [
            sys.executable,
            str(WORKER_PATH),
            "--job-dir",
            str(job_dir),
            "--runner",
            str(RUNNER_PATH),
            "--python",
            sys.executable,
            "--hermes-exe",
            str(hermes_path),
            "--profile",
            profile,
            "--purpose",
            purpose,
            "--cwd",
            str(working_dir),
            "--timeout",
            f"{bounded_timeout:g}",
        ]
        launch_path = _job_file(job_dir, "launch.json")
        _write_json(
            launch_path,
            {"worker_pid": None, "launched_at": _utc_now()},
            exclusive=True,
        )
        creation: dict[str, Any] = {
            "cwd": str(job_dir),
            "env": child_env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        # The worker itself gets no inherited pipes or console. It owns the
        # single job log and the helper's subprocess appends to that file.
        with log_path.open("ab") as log_handle:
            creation["stdout"] = log_handle
            creation["stderr"] = subprocess.STDOUT
            if os.name == "nt":
                creation["creationflags"] = (
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
            else:
                creation["start_new_session"] = True
            try:
                process = subprocess.Popen(command, **creation)
            except OSError as exc:
                _write_json(
                    _job_file(job_dir, "state.json"),
                    {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "finished_at": _utc_now(),
                    },
                    exclusive=True,
                )
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "profile": profile,
                    "purpose": purpose,
                    "settings_revision": revision,
                    "route_class": role,
                    "error_type": type(exc).__name__,
                }
        tracking = {}
        if self.runtime is not None:
            try:
                tracking["process_id"] = self.runtime.track(
                    process, job_id=job_id, purpose=purpose, cwd=str(working_dir)
                )
            except Exception as exc:
                # Already running: never retry the spawn or report a job failure
                # just because native observation could not be established.
                tracking["tracking_error"] = type(exc).__name__
                from .runtime_tracking import DesktopSeedUnavailable
                if isinstance(exc, DesktopSeedUnavailable):
                    tracking["process_id"] = exc.process_id
                    tracking["ui_seeded"] = False
        try:
            _write_json(
                launch_path,
                {"worker_pid": process.pid, "launched_at": _utc_now(), **tracking},
            )
        except OSError:
            # The worker records its own PID in state.json as soon as it starts;
            # avoid returning an ambiguous failure after the process was spawned.
            pass
        return {
            "job_id": job_id,
            "status": "running",
            "profile": profile,
            "purpose": purpose,
            "settings_revision": revision,
            "route_class": role,
            "requested_model": selected["model"],
            "requested_provider": selected["provider"],
            **tracking,
        }

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
        output: dict[str, Any] = {
            "job_id": job_id,
            "profile": profile,
            "purpose": snapshot.get("purpose"),
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
