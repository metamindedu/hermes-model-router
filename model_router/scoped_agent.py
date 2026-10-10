"""Run one isolated, profile-bound Hermes AIAgent attempt.

The child uses Hermes' own AIAgent/runtime-provider APIs, but supplies an explicit
empty native fallback chain. It is not a HermesCLI wrapper and never mutates config.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib
import importlib.util
import io
import json
import math
import os
import re
import sys
import types
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = 1
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_PROMPT_CHARS = 8 * 1024 * 1024
MAX_RESPONSE_CHARS = 48_000
MAX_ERROR_CHARS = 600

PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
PARENT_SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
PROVIDER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
REASONING = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
REQUEST_FIELDS_V1 = frozenset({
    "schema", "attempt_id", "job_id", "profile", "home", "cwd", "source", "task_id",
    "session_id", "parent_session_id", "route", "toolsets", "prompt", "budget_seconds",
})
REQUEST_FIELDS_V2 = REQUEST_FIELDS_V1 | {"fast_snapshot"}
FAST_SNAPSHOT_FIELDS = frozenset({
    "schema", "profile", "origin_session_id", "parent_session_id", "mode", "expires_at",
})
RESULT_FIELDS = frozenset({
    "schema", "attempt_id", "job_id", "session_id", "task_id", "requested_route", "completed",
    "error", "final_response", "tool_seen", "partial_output", "evidence_complete",
    "closure_complete", "observed_routes", "exhaustion_confirmed", "exit_code",
})


class AttemptError(ValueError):
    """Safe internal error with a stable result kind."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _clean_text(value: Any, label: str, *, maximum: int = 300, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value):
        raise AttemptError("initialization_error", f"invalid {label}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise AttemptError("initialization_error", f"invalid {label}")
    return value


def _no_symlink_path(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    if current.is_symlink():
        return False
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _validate_fast_snapshot_shape(value: Any, *, profile: str, parent_session_id: Any) -> dict[str, Any]:
    """Apply the shared schema's primitive/identity rules before plugin discovery."""
    if not isinstance(value, dict) or set(value) != FAST_SNAPSHOT_FIELDS:
        raise AttemptError("initialization_error", "Fast snapshot fields do not match schema 1")
    if type(value.get("schema")) is not int or value["schema"] != 1:
        raise AttemptError("initialization_error", "unsupported Fast snapshot schema")
    if value.get("profile") != profile or not isinstance(parent_session_id, str):
        raise AttemptError("initialization_error", "Fast snapshot profile or parent is invalid")
    if value.get("parent_session_id") != parent_session_id or PARENT_SESSION_ID_RE.fullmatch(parent_session_id) is None:
        raise AttemptError("initialization_error", "Fast snapshot parent does not match the immutable job")
    origin = value.get("origin_session_id")
    if not isinstance(origin, str) or PARENT_SESSION_ID_RE.fullmatch(origin) is None:
        raise AttemptError("initialization_error", "Fast snapshot origin is invalid")
    mode = value.get("mode")
    if not isinstance(mode, str) or mode not in {"normal", "priority", "ultrafast", "auto", "cold"}:
        raise AttemptError("initialization_error", "Fast snapshot mode is invalid")
    expires_at = value.get("expires_at")
    if mode in {"auto", "cold"}:
        try:
            finite_expiry = math.isfinite(float(expires_at))
        except (OverflowError, TypeError, ValueError):
            finite_expiry = False
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
            or not finite_expiry
            or expires_at < 0
        ):
            raise AttemptError("initialization_error", "bounded Fast snapshot expiry is invalid")
    elif expires_at is not None:
        raise AttemptError("initialization_error", "static Fast snapshot must not have an expiry")
    return dict(value)


def _validate_attempt_fast_provenance(
    request: dict[str, Any], *, home: Path, attempt_dir: Path
) -> dict[str, Any]:
    job_root = home / "plugin-data" / "model-router" / "jobs"
    job_dir = job_root / request["job_id"]
    snapshot_path = job_dir / "snapshot.json"
    if (
        snapshot_path.is_symlink()
        or not snapshot_path.is_file()
        or snapshot_path.resolve(strict=True).parent != job_dir.resolve(strict=True)
        or not _no_symlink_path(snapshot_path, home)
        or attempt_dir.parent.parent.resolve(strict=True) != job_dir.resolve(strict=True)
        or snapshot_path.stat().st_size > 1024 * 1024
    ):
        raise AttemptError("initialization_error", "Fast job snapshot path is invalid")
    try:
        job_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AttemptError("initialization_error", "Fast job snapshot is unreadable") from exc
    if (
        not isinstance(job_snapshot, dict)
        or type(job_snapshot.get("schema")) is not int
        or job_snapshot["schema"] != 1
        or job_snapshot.get("job_id") != request["job_id"]
        or job_snapshot.get("profile") != request["profile"]
        or "fast_snapshot" not in job_snapshot
        or job_snapshot.get("fast_snapshot") != request.get("fast_snapshot")
    ):
        raise AttemptError("initialization_error", "attempt Fast snapshot differs from immutable job provenance")
    return _validate_fast_snapshot_shape(
        request.get("fast_snapshot"),
        profile=request["profile"],
        parent_session_id=job_snapshot.get("parent_session_id"),
    )


def _validate_legacy_attempt_job_binding(
    request: dict[str, Any], *, home: Path, attempt_dir: Path,
) -> None:
    """Reject schema downgrade when a linked job snapshot records Fast intent.

    Truly old attempts with no job snapshot remain readable. If the linked file
    exists, however, it must be a valid same-job/profile schema-1 snapshot and
    must not carry the additive Fast provenance field.
    """
    job_dir = home / "plugin-data" / "model-router" / "jobs" / request["job_id"]
    snapshot_path = job_dir / "snapshot.json"
    if snapshot_path.is_symlink():
        raise AttemptError("initialization_error", "legacy job snapshot must not be linked")
    if not snapshot_path.exists():
        return
    if (
        not snapshot_path.is_file()
        or snapshot_path.resolve(strict=True).parent != job_dir.resolve(strict=True)
        or not _no_symlink_path(snapshot_path, home)
        or attempt_dir.parent.parent.resolve(strict=True) != job_dir.resolve(strict=True)
        or snapshot_path.stat().st_size > 1024 * 1024
    ):
        raise AttemptError("initialization_error", "legacy job snapshot path is invalid")
    try:
        job_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AttemptError("initialization_error", "legacy job snapshot is unreadable") from exc
    if (
        not isinstance(job_snapshot, dict)
        or type(job_snapshot.get("schema")) is not int
        or job_snapshot.get("schema") != 1
        or job_snapshot.get("job_id") != request["job_id"]
        or job_snapshot.get("profile") != request["profile"]
    ):
        raise AttemptError("initialization_error", "legacy job snapshot identity is invalid")
    if "fast_snapshot" in job_snapshot:
        raise AttemptError("initialization_error", "Fast job cannot use a schema-1 attempt")


def _validate_request(request: Any, request_path: Path | None = None) -> tuple[dict[str, Any], Path, Path]:
    if not isinstance(request, dict):
        raise AttemptError("initialization_error", "request must contain an object")
    schema = request.get("schema")
    if type(schema) is not int or schema not in {1, 2}:
        raise AttemptError("initialization_error", "unsupported request schema")
    expected_fields = REQUEST_FIELDS_V1 if schema == 1 else REQUEST_FIELDS_V2
    if set(request) != expected_fields:
        raise AttemptError("initialization_error", f"request fields do not match schema {schema}")
    if schema == 1 and "fast_snapshot" in request:
        raise AttemptError("initialization_error", "schema 1 cannot claim Fast inheritance")
    if not _canonical_uuid(request.get("attempt_id")) or not _canonical_uuid(request.get("job_id")):
        raise AttemptError("initialization_error", "attempt and job IDs must be canonical UUIDs")
    profile = request.get("profile")
    if not isinstance(profile, str) or PROFILE_RE.fullmatch(profile) is None:
        raise AttemptError("initialization_error", "invalid profile")
    home_raw = request.get("home")
    cwd_raw = request.get("cwd")
    if not isinstance(home_raw, str) or not isinstance(cwd_raw, str):
        raise AttemptError("initialization_error", "home and cwd must be paths")
    home_input, cwd_input = Path(home_raw).expanduser(), Path(cwd_raw).expanduser()
    if not home_input.is_absolute() or not cwd_input.is_absolute():
        raise AttemptError("initialization_error", "home and cwd must be absolute paths")
    try:
        home = home_input.resolve(strict=True)
        cwd = cwd_input.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AttemptError("initialization_error", "home or cwd does not resolve") from exc
    if not home.is_dir() or not cwd.is_dir() or home_input.is_symlink():
        raise AttemptError("initialization_error", "home or cwd is not a safe directory")

    source = _clean_text(request.get("source"), "source", maximum=64)
    if source != "subagent":
        raise AttemptError("initialization_error", "source must be subagent")
    task_id = _clean_text(request.get("task_id"), "task_id", maximum=128)
    session_id = _clean_text(request.get("session_id"), "session_id", maximum=128)
    if not _canonical_uuid(task_id) or not _canonical_uuid(session_id):
        raise AttemptError("initialization_error", "task_id and session_id must be canonical UUIDs")
    parent_session_id = request.get("parent_session_id")
    if parent_session_id is not None:
        parent_session_id = _clean_text(parent_session_id, "parent_session_id", maximum=128)
        if PARENT_SESSION_ID_RE.fullmatch(parent_session_id) is None:
            raise AttemptError("initialization_error", "invalid parent_session_id")
    route = request.get("route")
    if not isinstance(route, dict) or set(route) != {"provider", "model", "reasoning"}:
        raise AttemptError("initialization_error", "route fields do not match schema 1")
    provider, model, reasoning = route.get("provider"), route.get("model"), route.get("reasoning")
    if not isinstance(provider, str) or PROVIDER_RE.fullmatch(provider) is None:
        raise AttemptError("initialization_error", "invalid route provider")
    if not isinstance(model, str) or MODEL_RE.fullmatch(model) is None:
        raise AttemptError("initialization_error", "invalid route model")
    if not isinstance(reasoning, str) or reasoning not in REASONING:
        raise AttemptError("initialization_error", "unsupported route reasoning")
    toolsets = request.get("toolsets")
    if not isinstance(toolsets, list) or any(
        not isinstance(item, str) or not item or len(item) > 128
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in item)
        for item in toolsets
    ):
        raise AttemptError("initialization_error", "toolsets must be a list of safe names")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise AttemptError("initialization_error", "prompt must be non-empty and within the size limit")
    budget = request.get("budget_seconds")
    if isinstance(budget, bool) or not isinstance(budget, (int, float)):
        raise AttemptError("initialization_error", "budget_seconds must be numeric")
    budget = float(budget)
    if not math.isfinite(budget) or budget < 0:
        raise AttemptError("initialization_error", "budget_seconds is outside the supported bound")

    attempt_dir = home / "plugin-data" / "model-router" / "jobs" / request["job_id"] / "attempts" / request["attempt_id"]
    expected_request = attempt_dir / "attempt-request.json"
    expected_result = attempt_dir / "attempt-result.json"
    if request_path is None:
        request_path = expected_request
    raw_request_path = request_path.expanduser()
    if raw_request_path.is_symlink():
        raise AttemptError("initialization_error", "request artifact must not be a symlink")
    try:
        request_path = raw_request_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AttemptError("initialization_error", "request artifact does not resolve") from exc
    if request_path != expected_request.resolve(strict=True) or not request_path.is_file():
        raise AttemptError("initialization_error", "request artifact is outside its attempt directory")
    if not _no_symlink_path(request_path, home):
        raise AttemptError("initialization_error", "request artifact path contains a symlink")
    try:
        if request_path.stat().st_size > MAX_REQUEST_BYTES:
            raise AttemptError("initialization_error", "request artifact exceeds the size limit")
        on_disk = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise AttemptError("initialization_error", "request artifact is unreadable") from exc
    if on_disk != request:
        raise AttemptError("initialization_error", "request object differs from its bound artifact")
    validated_fast_snapshot = None
    if schema == 2:
        validated_fast_snapshot = _validate_attempt_fast_provenance(
            request, home=home, attempt_dir=attempt_dir
        )
    else:
        _validate_legacy_attempt_job_binding(request, home=home, attempt_dir=attempt_dir)
    if expected_result.is_symlink() or not _no_symlink_path(attempt_dir, home):
        raise AttemptError("initialization_error", "result path contains a symlink")
    # Keep normalized paths only in memory; the request artifact remains the source of truth.
    normalized = dict(request)
    normalized["home"] = str(home)
    normalized["cwd"] = str(cwd)
    normalized["budget_seconds"] = budget
    normalized["route"] = dict(route)
    normalized["toolsets"] = list(toolsets)
    if validated_fast_snapshot is not None:
        normalized["fast_snapshot"] = validated_fast_snapshot
    return normalized, request_path, expected_result


_INHERITED_CHAT_ROUTING_ENV = (
    "HERMES_UI_SESSION_ID", "HERMES_SESSION_CHAT_ID", "HERMES_SESSION_CHAT_TYPE",
    "HERMES_SESSION_CHAT_NAME", "HERMES_SESSION_THREAD_ID", "HERMES_SESSION_USER_ID",
    "HERMES_SESSION_USER_ID_ALT", "HERMES_SESSION_USER_NAME", "HERMES_SESSION_SCOPE_ID",
    "HERMES_SESSION_KEY", "HERMES_SESSION_MESSAGE_ID", "HERMES_SESSION_PARENT_CHAT_ID",
)


def _bind_subagent_session_environment(request: dict[str, Any]) -> None:
    """Make the routed AIAgent a distinct child, never a continuation of Desktop routing."""
    for key in _INHERITED_CHAT_ROUTING_ENV:
        os.environ.pop(key, None)
    os.environ["HERMES_PLATFORM"] = "subagent"
    os.environ["HERMES_SESSION_PLATFORM"] = "subagent"
    os.environ["HERMES_SESSION_SOURCE"] = "subagent"
    os.environ["HERMES_SESSION_SOURCE_EXPLICIT"] = "1"
    os.environ["HERMES_SESSION_ID"] = request["session_id"]


@contextlib.contextmanager
def _attempt_environment(request: dict[str, Any], request_path: Path):
    """Bind one headless automation session without inheriting a permissive CLI bypass."""
    keys = (
        "HERMES_HOME", "HERMES_PROFILE", "HERMES_PROFILE_NAME", "HERMES_SESSION_PROFILE",
        "HERMES_SESSION_SOURCE", "HERMES_SESSION_SOURCE_EXPLICIT", "HERMES_SINGLE_QUERY_SESSION",
        "HERMES_SESSION_ID", "HERMES_PLATFORM", "HERMES_SESSION_PLATFORM",
        *_INHERITED_CHAT_ROUTING_ENV,
        "MODEL_ROUTER_ATTEMPT_REQUEST", "HERMES_YOLO_MODE", "HERMES_INTERACTIVE",
    )
    saved = {key: os.environ.get(key) for key in keys}
    old_cwd = Path.cwd()
    try:
        os.environ["HERMES_HOME"] = request["home"]
        os.environ["HERMES_PROFILE"] = request["profile"]
        os.environ["HERMES_PROFILE_NAME"] = request["profile"]
        os.environ["HERMES_SESSION_PROFILE"] = request["profile"]
        os.environ["HERMES_SINGLE_QUERY_SESSION"] = "1"
        os.environ["MODEL_ROUTER_ATTEMPT_REQUEST"] = str(request_path)
        _bind_subagent_session_environment(request)
        # Never inherit an interactive-session bypass or make a human prompt appear available.
        os.environ.pop("HERMES_YOLO_MODE", None)
        os.environ.pop("HERMES_INTERACTIVE", None)
        os.chdir(request["cwd"])
        yield
    finally:
        with contextlib.suppress(OSError):
            os.chdir(old_cwd)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _safe_redact(text: Any, dependencies: Any) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    redact = _dependency(dependencies, "redact")
    try:
        if callable(redact):
            value = redact(text)
        else:
            from agent.redact import redact_sensitive_text
            value = redact_sensitive_text(text, force=True)
        return str(value or "")[:MAX_RESPONSE_CHARS]
    except Exception:
        return "[redacted: sanitization unavailable]"


def _dependency(dependencies: Any, name: str, default: Any = None) -> Any:
    if dependencies is None:
        return default
    if isinstance(dependencies, dict):
        return dependencies.get(name, default)
    return getattr(dependencies, name, default)


def _without_stale_fast_options(value: Any) -> Any:
    """Remove profile-paid Fast hints while preserving unrelated runtime overrides."""
    if not isinstance(value, dict):
        return value
    cleaned = copy.deepcopy(value)
    for key in ("service_tier", "speed"):
        cleaned.pop(key, None)
    extra_body = cleaned.get("extra_body")
    if isinstance(extra_body, dict):
        for key in ("service_tier", "speed"):
            extra_body.pop(key, None)
    return cleaned


def _active_fast_binding_matches(module: types.ModuleType, request: dict[str, Any]) -> bool:
    """Do not run a managed attempt if the verified controller did not bind it."""
    try:
        binding_var = getattr(module, "_ROUTED_FAST", None)
        home_key = getattr(module, "_home_key", None)
        current = binding_var.get() if callable(getattr(binding_var, "get", None)) else None
        expected_home = Path(request["home"]).resolve(strict=True)
        return (
            current is not None
            and callable(home_key)
            and current.profile == request["profile"]
            and current.home_key == home_key(expected_home)
            and current.session_id == request["session_id"]
            and current.snapshot == request["fast_snapshot"]
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _public_progress_class() -> Any:
    """Load this plugin's writer while supporting the runner's direct-file import."""
    if __package__:
        from .public_progress import PublicProgress

        return PublicProgress

    plugin_root = Path(__file__).resolve(strict=True).parents[1]
    package_root = (plugin_root / "model_router").resolve(strict=True)
    expected_init = (package_root / "__init__.py").resolve(strict=True)
    if Path(__file__).resolve(strict=True) != (package_root / "scoped_agent.py").resolve(strict=True):
        raise ImportError("scoped agent is outside its trusted model-router package")

    package_name = "_model_router_direct_" + uuid.uuid5(uuid.NAMESPACE_URL, str(package_root)).hex[:16]
    package = sys.modules.get(package_name)
    if package is None:
        spec = importlib.util.spec_from_file_location(
            package_name,
            expected_init,
            submodule_search_locations=[str(package_root)],
        )
        if spec is None or spec.loader is None:
            raise ImportError("trusted model-router package could not be loaded")
        package = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = package
        try:
            spec.loader.exec_module(package)
        except Exception:
            for name in tuple(sys.modules):
                if name == package_name or name.startswith(package_name + "."):
                    sys.modules.pop(name, None)
            raise

    if (
        Path(getattr(package, "__file__", "")).resolve(strict=True) != expected_init
        or [Path(item).resolve(strict=True) for item in getattr(package, "__path__", ())] != [package_root]
    ):
        raise ImportError("model-router package namespace is not bound to this plugin root")

    progress_module = importlib.import_module(package_name + ".public_progress")
    expected_progress = (package_root / "public_progress.py").resolve(strict=True)
    if Path(getattr(progress_module, "__file__", "")).resolve(strict=True) != expected_progress:
        raise ImportError("public progress writer is outside this plugin root")
    writer = getattr(progress_module, "PublicProgress", None)
    if not callable(writer):
        raise ImportError("trusted public progress writer is unavailable")
    return writer


def _trusted_core_root() -> Path:
    """Find the runtime's Hermes source root without trusting cwd or project modules."""
    plugin_root = Path(__file__).resolve().parents[1]
    current = Path.cwd().resolve()
    candidates: list[Path] = []
    executable = Path(sys.executable).resolve()
    candidates.extend(executable.parents)
    for raw in tuple(sys.path):
        if not raw:
            continue
        try:
            path = Path(raw).expanduser().resolve()
            if path == current or path == plugin_root or current in path.parents or plugin_root in path.parents:
                continue
        except (OSError, RuntimeError):
            continue
        candidates.append(path)
    for candidate in candidates:
        root = candidate if candidate.is_dir() else candidate.parent
        if all((root / member).is_file() for member in (
            "hermes_bootstrap.py", "run_agent.py", "agent/agent_init.py", "hermes_cli/runtime_provider.py",
        )):
            resolved = root.resolve(strict=True)
            if resolved != current and current not in resolved.parents and resolved != plugin_root and plugin_root not in resolved.parents:
                return resolved
    saved_path = list(sys.path)
    try:
        sys.path[:] = [item for item in sys.path if item and Path(item).resolve() not in {current, plugin_root}]
        spec = importlib.util.find_spec("hermes_bootstrap")
        origin = Path(spec.origin).resolve(strict=True) if spec and spec.origin else None
        if origin is not None:
            root = origin.parent
            if all((root / member).is_file() for member in (
                "run_agent.py", "agent/agent_init.py", "hermes_cli/runtime_provider.py",
            )) and root != current and root != plugin_root and plugin_root not in root.parents:
                return root
    except (ImportError, OSError, RuntimeError, ValueError):
        pass
    finally:
        sys.path[:] = saved_path
    raise AttemptError("initialization_error", "trusted Hermes import origin could not be verified")


def _strict_profile_config(config_path: Path) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Load one validated current config snapshot; never promote Hermes recovery data to policy."""
    try:
        from utils import fast_safe_load
        from hermes_cli import config as core_config
        from hermes_cli.config_effective import load_user_config_effective
        from hermes_cli.config_read_errors import FailedConfigRead

        config_path = config_path.resolve(strict=True)
        if not config_path.is_file():
            raise AttemptError("initialization_error", "profile config is not a regular file")
        raw_bytes = config_path.read_bytes()
        if not raw_bytes:
            raise AttemptError("initialization_error", "profile config is empty")
        raw = fast_safe_load(io.StringIO(raw_bytes.decode("utf-8-sig")))
        if isinstance(raw, FailedConfigRead) or not isinstance(raw, Mapping):
            raise AttemptError("initialization_error", "profile config is not a readable mapping")
        raw = dict(raw)
        from hermes_cli import managed_scope
        managed_dir = managed_scope.get_managed_dir()
        managed_path = Path(managed_dir) / "config.yaml" if managed_dir is not None else None
        managed_bytes = None
        if managed_path is not None:
            try:
                managed_bytes = managed_path.read_bytes()
            except FileNotFoundError:
                pass
            if managed_bytes is not None:
                managed_raw = fast_safe_load(io.StringIO(managed_bytes.decode("utf-8-sig")))
                if managed_raw is not None and not isinstance(managed_raw, Mapping):
                    raise AttemptError("initialization_error", "managed config is not a mapping")

        # Hermes' strict effective reader is still useful for managed overlays and env expansion,
        # but its result must agree with the exact raw bytes read above (not a cache/LKG snapshot).
        effective = load_user_config_effective(config_path, fail_closed=True)
        if isinstance(effective, FailedConfigRead) or not isinstance(effective, dict):
            raise AttemptError("initialization_error", "effective profile config is invalid")
        from hermes_cli import config_effective
        expected_effective = config_effective._effective(raw)
        if not isinstance(expected_effective, dict) or effective != expected_effective:
            raise AttemptError("initialization_error", "effective profile config changed during validation")

        # Read the normal default-merged runtime config once, but refuse Hermes' dict-subclass
        # recovery marker and any value not derivable from the exact raw snapshot.
        if Path(core_config.get_config_path()).resolve(strict=True) != config_path:
            raise AttemptError("initialization_error", "active profile config path changed during validation")
        config = core_config.load_config_readonly()
        if isinstance(config, FailedConfigRead) or not isinstance(config, dict):
            raise AttemptError("initialization_error", "profile config read failed closed")

        user_config = copy.deepcopy(raw)
        if "max_turns" in user_config:
            agent_user_config = dict(user_config.get("agent") or {})
            if agent_user_config.get("max_turns") is None:
                agent_user_config["max_turns"] = user_config["max_turns"]
            user_config["agent"] = agent_user_config
            user_config.pop("max_turns", None)
        expected = core_config._deep_merge(copy.deepcopy(core_config.DEFAULT_CONFIG), user_config)
        expected = core_config._canonicalize_config(expected)
        expected = core_config._expand_env_vars(expected)
        expected, _managed_config = core_config._merge_managed_overlay(expected)
        if not isinstance(expected, dict) or config != expected:
            raise AttemptError("initialization_error", "runtime config differs from the current profile config")

        issues = core_config.validate_config_structure(config)
        if any(getattr(issue, "severity", None) == "error" for issue in issues):
            raise AttemptError("initialization_error", "profile config failed structural validation")
        if config_path.read_bytes() != raw_bytes:
            raise AttemptError("initialization_error", "profile config changed during validation")
        if managed_scope.get_managed_dir() != managed_dir:
            raise AttemptError("initialization_error", "managed config scope changed during validation")
        if managed_path is not None:
            try:
                managed_after = managed_path.read_bytes()
            except FileNotFoundError:
                managed_after = None
            if managed_after != managed_bytes:
                raise AttemptError("initialization_error", "managed config changed during validation")
        return effective, config, raw_bytes
    except AttemptError:
        raise
    except Exception as exc:
        raise AttemptError("initialization_error", "profile config is missing, unreadable, or invalid") from exc


def _resolve_registered_observer(profile_home: Path, plugin_root: Path) -> types.ModuleType:
    """Return only the observer module captured by this profile's actually registered hooks."""
    try:
        from hermes_cli.plugins import get_plugin_manager

        profile_home = profile_home.resolve(strict=True)
        plugin_root = plugin_root.resolve(strict=True)
        manager = get_plugin_manager()
        manager_home = Path(manager.home_path).resolve(strict=True)
        if manager_home != profile_home:
            raise AttemptError("initialization_error", "plugin registry belongs to a different Hermes profile")
        loaded = manager._plugins.get("model-router")
        package = getattr(loaded, "module", None)
        if (
            loaded is None or not loaded.enabled or loaded.error or not isinstance(package, types.ModuleType)
            or getattr(package, "__name__", "") not in sys.modules
            or sys.modules.get(package.__name__) is not package
        ):
            raise AttemptError("initialization_error", "model-router directory plugin is not registered")
        expected_package = (plugin_root / "__init__.py").resolve(strict=True)
        if Path(getattr(package, "__file__", "")).resolve(strict=True) != expected_package:
            raise AttemptError("initialization_error", "registered model-router plugin root is not trusted")
        package_paths = [Path(item).resolve(strict=True) for item in getattr(package, "__path__", ())]
        if package_paths != [plugin_root]:
            raise AttemptError("initialization_error", "registered model-router plugin path is ambiguous")

        prefix = "hermes_plugins.model_router"
        package_name = package.__name__
        if package_name != prefix and re.fullmatch(rf"{re.escape(prefix)}__home_[0-9a-f]{{12}}", package_name) is None:
            raise AttemptError("initialization_error", "registered plugin namespace is not profile-scoped")
        expected_observer_name = f"{package_name}.model_router.attempt_observer"
        bound_observer: types.ModuleType | None = None
        for event_name in ("pre_api_request", "post_api_request", "api_request_error", "pre_tool_call", "post_tool_call"):
            callbacks = manager._hooks.get(event_name)
            if not isinstance(callbacks, list):
                raise AttemptError("initialization_error", "required model-router lifecycle hook is missing")
            owned = [callback for callback in callbacks if getattr(callback, "__module__", None) == package_name]
            if len(owned) != 1:
                raise AttemptError("initialization_error", "model-router lifecycle hook is missing or ambiguous")
            callback = owned[0]
            code = getattr(callback, "__code__", None)
            closure = getattr(callback, "__closure__", None)
            if code is None or closure is None or len(code.co_freevars) != len(closure):
                raise AttemptError("initialization_error", "registered observer hook binding is invalid")
            captured = dict(zip(code.co_freevars, (cell.cell_contents for cell in closure)))
            record_event = captured.get("record_event")
            hook_home = captured.get("home")
            if (
                captured.get("event_name") != event_name
                or not callable(record_event)
                or not isinstance(hook_home, Path)
                or hook_home.resolve(strict=True) != profile_home
            ):
                raise AttemptError("initialization_error", "registered observer hook binding is untrusted")
            observer_name = getattr(record_event, "__module__", "")
            observer = sys.modules.get(observer_name)
            origin = getattr(getattr(observer, "__spec__", None), "origin", None)
            if (
                observer_name != expected_observer_name
                or not isinstance(observer, types.ModuleType)
                or getattr(observer, "record_event", None) is not record_event
                or getattr(record_event, "__globals__", None) is not observer.__dict__
                or not origin
                or Path(origin).resolve(strict=True) != (plugin_root / "model_router" / "attempt_observer.py").resolve(strict=True)
            ):
                raise AttemptError("initialization_error", "registered observer module root is not trusted")
            if bound_observer is not None and bound_observer is not observer:
                raise AttemptError("initialization_error", "registered lifecycle hooks use different observers")
            bound_observer = observer
        if bound_observer is None:
            raise AttemptError("initialization_error", "registered observer could not be resolved")
        return bound_observer
    except AttemptError:
        raise
    except Exception as exc:
        raise AttemptError("initialization_error", "profile-scoped observer registration could not be verified") from exc


def _resolve_registered_fast_inheritance(
    profile_home: Path, plugin_root: Path, observer: types.ModuleType, profile: str
) -> types.ModuleType:
    """Resolve Fast binding only from this profile's already registered plugin namespace."""
    try:
        from hermes_cli.plugins import get_plugin_manager

        profile_home = profile_home.resolve(strict=True)
        plugin_root = plugin_root.resolve(strict=True)
        manager = get_plugin_manager()
        if Path(manager.home_path).resolve(strict=True) != profile_home:
            raise AttemptError("initialization_error", "Fast controller belongs to a different Hermes profile")
        loaded = manager._plugins.get("model-router")
        package = getattr(loaded, "module", None)
        if (
            loaded is None or not loaded.enabled or loaded.error
            or not isinstance(package, types.ModuleType)
            or sys.modules.get(getattr(package, "__name__", "")) is not package
        ):
            raise AttemptError("initialization_error", "registered Fast controller is unavailable")
        expected_init = (plugin_root / "__init__.py").resolve(strict=True)
        if (
            Path(getattr(package, "__file__", "")).resolve(strict=True) != expected_init
            or [Path(item).resolve(strict=True) for item in getattr(package, "__path__", ())]
            != [plugin_root]
        ):
            raise AttemptError("initialization_error", "registered Fast plugin root is not trusted")
        package_name = package.__name__
        if observer.__name__ != f"{package_name}.model_router.attempt_observer":
            raise AttemptError("initialization_error", "Fast and observer modules do not share a registered namespace")
        expected_origin = (plugin_root / "model_router" / "fast_inheritance.py").resolve(strict=True)
        candidates = [
            (f"{package_name}.model_router.fast_inheritance", expected_origin),
        ]
        registered = []
        for name, origin_path in candidates:
            module = sys.modules.get(name)
            if module is None:
                continue
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if (
                not isinstance(module, types.ModuleType)
                or not origin
                or Path(origin).resolve(strict=True) != origin_path
            ):
                raise AttemptError("initialization_error", "registered Fast module origin is untrusted")
            registered.append(module)
        if len(registered) != 1:
            raise AttemptError("initialization_error", "registered Fast module is missing or ambiguous")
        module = registered[0]
        for name in ("validate_fast_snapshot", "bind_routed_fast_snapshot"):
            function = getattr(module, name, None)
            implementation = getattr(function, "__wrapped__", function)
            if (
                not callable(function)
                or getattr(function, "__module__", None) != module.__name__
                or getattr(implementation, "__module__", None) != module.__name__
                or getattr(implementation, "__globals__", None) is not module.__dict__
            ):
                raise AttemptError("initialization_error", "registered Fast module interface is invalid")
        controller_getter = getattr(module, "_registered_controller", None)
        controller = controller_getter(profile_home, profile) if callable(controller_getter) else None
        if (
            controller is None
            or type(controller).__module__ != module.__name__
            or getattr(controller, "profile", None) != profile
            or Path(getattr(controller, "home", "")).resolve(strict=True) != profile_home
            or getattr(controller, "closed", True) is True
        ):
            raise AttemptError("initialization_error", "registered Fast controller does not own this profile home")
        return module
    except AttemptError:
        raise
    except Exception as exc:
        raise AttemptError("initialization_error", "registered Fast binding could not be verified") from exc


def _default_prepare_runtime(request: dict[str, Any]) -> dict[str, Any]:
    """Hermes-supported profile/bootstrap/config/runtime setup for the live adapter."""
    core_root = _trusted_core_root()
    plugin_root = Path(__file__).resolve().parents[1]
    if str(core_root) not in sys.path:
        sys.path.insert(0, str(core_root))
    if str(plugin_root) not in sys.path:
        sys.path.insert(0, str(plugin_root))
    bootstrap = importlib.import_module("hermes_bootstrap")
    bootstrap_origin = Path(bootstrap.__file__).resolve(strict=True)
    if bootstrap_origin.parent != core_root:
        raise AttemptError("initialization_error", "Hermes bootstrap origin changed during resolution")
    bootstrap.harden_import_path(str(core_root))
    # The plugin root is trusted and must remain importable after Hermes removes cwd entries.
    if str(plugin_root) not in sys.path:
        sys.path.insert(1, str(plugin_root))

    from hermes_cli.profiles import get_profile_dir, profile_exists
    if request["profile"] != "default" and not profile_exists(request["profile"]):
        raise AttemptError("initialization_error", "requested profile is not an existing Hermes profile")
    if Path(get_profile_dir(request["profile"])).resolve(strict=True) != Path(request["home"]).resolve(strict=True):
        raise AttemptError("initialization_error", "profile and Hermes home do not match")

    from hermes_cli.env_loader import load_hermes_dotenv
    load_hermes_dotenv(hermes_home=request["home"], project_env=core_root / ".env")
    # A profile dotenv or a parent launcher must not turn this headless child into YOLO mode.
    os.environ.pop("HERMES_YOLO_MODE", None)
    os.environ.pop("HERMES_INTERACTIVE", None)
    _bind_subagent_session_environment(request)

    config_path = Path(request["home"]) / "config.yaml"
    effective_config, config, config_snapshot = _strict_profile_config(config_path)
    if "HERMES_REDACT_SECRETS" not in os.environ:
        security = effective_config.get("security")
        if isinstance(security, dict) and security.get("redact_secrets") is not None:
            os.environ["HERMES_REDACT_SECRETS"] = str(security["redact_secrets"]).lower()

    try:
        from hermes_logging import setup_logging
        setup_logging(mode="cli")
    except Exception:
        pass
    from hermes_cli.config import apply_terminal_config_to_env, resolve_turn_limit
    try:
        apply_terminal_config_to_env(env=os.environ, config=config)
        if config_path.read_bytes() != config_snapshot:
            raise AttemptError("initialization_error", "profile config changed during runtime preparation")
    except AttemptError:
        raise
    except Exception as exc:
        raise AttemptError("initialization_error", "profile config could not be applied safely") from exc

    # Match normal CLI startup: ensure Tirith readiness, discover profile plugins, and
    # complete the finite one-shot MCP snapshot before AIAgent captures its tools.
    from tools.tirith_security import ensure_installed
    ensure_installed(log_failures=False)
    from hermes_cli.plugins import discover_plugins
    discover_plugins()
    observer_module = _resolve_registered_observer(Path(request["home"]), plugin_root)
    fast_inheritance_module = None
    if request.get("schema") == 2:
        fast_inheritance_module = _resolve_registered_fast_inheritance(
            Path(request["home"]), plugin_root, observer_module, request["profile"]
        )
        validated_fast = fast_inheritance_module.validate_fast_snapshot(
            request["fast_snapshot"],
            profile=request["profile"],
            parent_session_id=request["fast_snapshot"]["parent_session_id"],
        )
        if validated_fast != request["fast_snapshot"]:
            raise AttemptError("initialization_error", "registered Fast validator changed the immutable intent")
    from hermes_cli.mcp_startup import ensure_mcp_discovery_before_agent_build
    ensure_mcp_discovery_before_agent_build(logger=__import__("logging").getLogger(__name__), single_query=True)

    from hermes_cli.runtime_provider import resolve_runtime_provider

    from agent.skill_utils import parse_config_string_list
    from hermes_constants import parse_reasoning_effort, resolve_reasoning_config
    from hermes_state_registry import acquire, release
    from hermes_cli.personality import resolve_ephemeral_system_prompt
    from hermes_cli.cli_config_load import _parse_service_tier_config
    from run_agent import AIAgent

    agent_cfg = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    disabled_toolsets = parse_config_string_list(agent_cfg.get("disabled_toolsets"))
    max_turns = next((value for value in (agent_cfg.get("max_turns"), config.get("max_turns")) if value is not None), 500)
    max_iterations = resolve_turn_limit(max_turns)
    checkpoint_cfg = config.get("checkpoints", {})
    checkpoint_cfg = {"enabled": checkpoint_cfg} if isinstance(checkpoint_cfg, bool) else checkpoint_cfg
    if not isinstance(checkpoint_cfg, dict):
        checkpoint_cfg = {}
    reasoning_config = resolve_reasoning_config(config, request["route"]["model"])
    route_reasoning = parse_reasoning_effort(request["route"]["reasoning"])
    if route_reasoning is None:
        raise AttemptError("initialization_error", "route reasoning could not be resolved")
    service_tier = _parse_service_tier_config(agent_cfg.get("service_tier", ""))
    toolsets = request["toolsets"]
    if not toolsets:
        # An explicit empty request means no tools, not CLI's default toolset set.
        enabled_toolsets = []
    else:
        enabled_toolsets = list(toolsets)
    return {
        "config": config,
        "AIAgent": AIAgent,
        "resolve_runtime_provider": resolve_runtime_provider,
        "acquire_session_db": acquire,
        "release_session_db": release,
        "agent_options": {
            "max_iterations": max_iterations,
            "enabled_toolsets": enabled_toolsets,
            "disabled_toolsets": disabled_toolsets,
            "reasoning_config": route_reasoning or reasoning_config,
            "service_tier": service_tier,
            "ephemeral_system_prompt": resolve_ephemeral_system_prompt(config) or None,
            "checkpoints_enabled": bool(checkpoint_cfg.get("enabled", False)),
            "checkpoint_max_snapshots": checkpoint_cfg.get("max_snapshots", 20),
            "checkpoint_max_total_size_mb": checkpoint_cfg.get("max_total_size_mb", 500),
            "checkpoint_max_file_size_mb": checkpoint_cfg.get("max_file_size_mb", 10),
            "pass_session_id": bool(agent_cfg.get("pass_session_id", False)),
        },
        "plugin_root": plugin_root,
        "core_root": core_root,
        "observer": observer_module,
        "fast_inheritance": fast_inheritance_module,
    }


def _empty_result(request: dict[str, Any], *, kind: str, message: str, dependencies: Any) -> dict[str, Any]:
    route = request.get("route") if isinstance(request, dict) else None
    if (
        not isinstance(route, dict)
        or set(route) != {"provider", "model", "reasoning"}
        or not isinstance(route.get("provider"), str)
        or PROVIDER_RE.fullmatch(route["provider"]) is None
        or not isinstance(route.get("model"), str)
        or MODEL_RE.fullmatch(route["model"]) is None
        or not isinstance(route.get("reasoning"), str)
        or route["reasoning"] not in REASONING
    ):
        route = {"provider": "", "model": "", "reasoning": ""}
    def identity(name: str) -> str:
        value = request.get(name) if isinstance(request, dict) else None
        return value if isinstance(value, str) and len(value) <= 128 and not any(ord(c) < 32 for c in value) else ""
    return {
        "schema": SCHEMA,
        "attempt_id": identity("attempt_id"),
        "job_id": identity("job_id"),
        "session_id": identity("session_id"),
        "task_id": identity("task_id"),
        "requested_route": dict(route),
        "completed": False,
        "error": {"kind": kind, "message": _safe_redact(message, dependencies)[:MAX_ERROR_CHARS]},
        "final_response": "",
        "tool_seen": False,
        "partial_output": False,
        "evidence_complete": False,
        "closure_complete": False,
        "observed_routes": [],
        "exhaustion_confirmed": False,
        "exit_code": 1,
    }


def _tool_calls_seen(value: Any) -> bool:
    if isinstance(value, dict):
        calls = value.get("tool_calls")
        if isinstance(calls, list) and calls:
            return True
        return any(_tool_calls_seen(item) for key, item in value.items() if key in {"messages", "assistant_message"})
    if isinstance(value, list):
        return any(_tool_calls_seen(item) for item in value)
    return False


def _observed_route_matches(route: Any, provider: str, model: str) -> bool:
    """Keep the selected route exact; resolve only the installed Codex picker alias on the wire."""
    if not isinstance(route, dict) or route.get("provider") != provider or route.get("model") != model:
        return False
    wire_models = {model}
    if provider == "openai-codex" and route.get("api_mode") == "codex_responses":
        try:
            from agent.model_metadata import is_codex_context_variant, strip_codex_context_variant_suffix
            if is_codex_context_variant(model):
                wire_models.add(strip_codex_context_variant_suffix(model))
        except ImportError:
            pass  # Unavailable canonical metadata must fail closed, never guess a suffix.
    return all(route.get(key) is None or route.get(key) in wire_models
               for key in ("request_model", "response_model"))


def _result_error_kind(result: dict[str, Any], observer_snapshot: dict[str, Any], expected_provider: str, expected_model: str) -> tuple[str | None, str | None]:
    if result.get("interrupted") is True:
        return "interrupted", "attempt was interrupted"
    if result.get("timed_out") is True or result.get("failure_reason") in {"timeout", "run_budget_exhausted"}:
        return "timeout", "attempt exceeded its runtime budget"
    if observer_snapshot.get("evidence_complete") is not True:
        return "evidence_missing", "main-loop API observation is incomplete"
    observed = observer_snapshot.get("observed_routes")
    if not isinstance(observed, list) or not observed:
        return "evidence_missing", "no main-loop API route was observed"
    for route in observed:
        if not _observed_route_matches(route, expected_provider, expected_model):
            return "route_mismatch", "observed main-loop route differs from the requested route"
    if observer_snapshot.get("exhaustion_confirmed") is True:
        return "subscription_exhaustion", "Hermes classified a terminal billing/quota response"
    if result.get("failed") is True or result.get("completed") is not True or result.get("partial") is True:
        return "provider_error", "Hermes did not complete the requested turn"
    return None, None


def run_attempt(request: dict, dependencies: Any = None) -> dict[str, Any]:
    """Run one isolated Hermes attempt and return the frozen schema-1 result envelope."""
    source_request = request
    try:
        request, request_path, _result_path = _validate_request(request)
    except AttemptError as exc:
        safe_request = request if isinstance(request, dict) else {}
        return _empty_result(safe_request, kind=exc.kind, message=str(exc), dependencies=dependencies)
    except Exception:
        safe_request = request if isinstance(request, dict) else {}
        return _empty_result(safe_request, kind="initialization_error", message="request validation failed", dependencies=dependencies)

    public_progress = None
    try:
        public_progress = _public_progress_class()(source_request, request_path)
    except Exception:
        # Public progress is observational only; a writer setup failure cannot
        # prevent the validated attempt or its evidence hooks from running.
        public_progress = None

    observer = _dependency(dependencies, "observer")
    agent = None
    session_db = None
    release_db = None
    closure_complete = True
    run_result: dict[str, Any] = {}
    final_response = ""
    error_kind: str | None = None
    error_message: str | None = None
    evidence: dict[str, Any] = {}
    with _attempt_environment(request, request_path):
        try:
            prepare = _dependency(dependencies, "prepare_runtime") or _default_prepare_runtime
            prepared = prepare(request)
            if not isinstance(prepared, dict):
                raise AttemptError("initialization_error", "runtime preparation returned an invalid result")
            if observer is None:
                observer = prepared.get("observer")
            if observer is None:
                raise AttemptError("initialization_error", "profile-scoped observer is unavailable")
            fast_module = None
            fast_binding = None
            if request.get("schema") == 2:
                fast_module = _resolve_registered_fast_inheritance(
                    Path(request["home"]), Path(__file__).resolve().parents[1], observer,
                    request["profile"],
                )
                prepared_fast = prepared.get("fast_inheritance")
                if prepared_fast is not None and prepared_fast is not fast_module:
                    raise AttemptError("initialization_error", "runtime Fast module differs from registered controller")
                validated_fast = fast_module.validate_fast_snapshot(
                    request["fast_snapshot"],
                    profile=request["profile"],
                    parent_session_id=request["fast_snapshot"]["parent_session_id"],
                )
                if validated_fast != request["fast_snapshot"]:
                    raise AttemptError("initialization_error", "Fast attempt differs from immutable job provenance")
                fast_binding = fast_module.bind_routed_fast_snapshot(
                    request["fast_snapshot"],
                    session_id=request["session_id"],
                    home=Path(request["home"]).resolve(strict=True),
                )
                if not callable(getattr(fast_binding, "__enter__", None)) or not callable(
                    getattr(fast_binding, "__exit__", None)
                ):
                    raise AttemptError("initialization_error", "registered Fast binding is not a context manager")
            reset = getattr(observer, "reset_for_tests", None)
            if callable(reset):
                reset()
            resolver = prepared.get("resolve_runtime_provider")
            agent_type = prepared.get("AIAgent")
            acquire_db = prepared.get("acquire_session_db")
            release_db = prepared.get("release_session_db")
            if not all(callable(value) for value in (resolver, agent_type, acquire_db, release_db)):
                raise AttemptError("initialization_error", "supported Hermes runtime dependencies are incomplete")
            runtime = resolver(requested=request["route"]["provider"], target_model=request["route"]["model"])
            if not isinstance(runtime, dict):
                raise AttemptError("initialization_error", "Hermes runtime provider resolution failed")
            runtime_provider = runtime.get("provider")
            if not isinstance(runtime_provider, str) or not runtime_provider:
                raise AttemptError("initialization_error", "Hermes did not resolve a provider identity")
            api_mode = runtime.get("api_mode")
            if api_mode == "codex_app_server":
                raise AttemptError("initialization_error", "codex_app_server has no main-loop pre/post API hook evidence")
            if api_mode not in {None, "chat_completions", "anthropic_messages", "codex_responses", "bedrock_converse"}:
                raise AttemptError("initialization_error", "unsupported provider transport for main-loop API observation")
            session_db = acquire_db()
            if session_db is None:
                raise AttemptError("initialization_error", "Hermes session store could not be acquired")
            options = dict(prepared.get("agent_options") or {})

            def interim_assistant_callback(text: Any, **_kw: Any) -> None:
                if isinstance(text, str) and text:
                    observer.mark_partial_output()
                    if public_progress is not None:
                        try:
                            public_progress.interim(text)
                        except Exception:
                            pass

            def tool_start_callback(_call_id: Any, function_name: Any = None, _display_args: Any = None) -> None:
                observer.mark_tool_seen()
                if public_progress is not None:
                    try:
                        public_progress.tool_start(function_name)
                    except Exception:
                        pass

            options.update({
                "api_key": runtime.get("api_key"),
                "base_url": runtime.get("base_url"),
                "provider": runtime.get("provider"),
                "requested_provider": runtime.get("requested_provider") or request["route"]["provider"],
                "api_mode": runtime.get("api_mode"),
                "model": request["route"]["model"],
                "credential_pool": runtime.get("credential_pool"),
                "request_overrides": (
                    _without_stale_fast_options(runtime.get("request_overrides"))
                    if request.get("schema") == 2 else runtime.get("request_overrides")
                ),
                "fallback_model": [],
                "session_id": request["session_id"],
                "parent_session_id": request["parent_session_id"],
                "session_db": session_db,
                "platform": "subagent",
                "cwd": request["cwd"],
                "run_budget_seconds": request["budget_seconds"],
                "quiet_mode": True,
                "tool_progress_mode": "off",
                "skip_context_files": False,
                "load_soul_identity": True,
                "skip_memory": False,
                "skip_background_review": True,
                "stream_delta_callback": lambda text: observer.mark_partial_output() if isinstance(text, str) and text else None,
                "interim_assistant_callback": interim_assistant_callback,
                "tool_start_callback": tool_start_callback,
            })
            if request.get("schema") == 2:
                # The inherited snapshot, never profile paid tier config, is the sole
                # managed Fast authority. The request middleware binds it per turn.
                options["service_tier"] = None
            agent = agent_type(**options)
            # Match native delegate_tool before the first lazy session-row write.
            # source=subagent alone does not exclude a child from resume traversal.
            if request["parent_session_id"]:
                initial_config = getattr(agent, "_session_init_model_config", None)
                if not isinstance(initial_config, dict):
                    raise AttemptError("initialization_error", "Hermes cannot persist delegated session identity")
                initial_config["_delegate_from"] = request["parent_session_id"]
            runner = getattr(agent, "run_conversation", None)
            if not callable(runner):
                raise AttemptError("initialization_error", "Hermes AIAgent does not expose run_conversation")
            if fast_binding is not None:
                with fast_binding:
                    if fast_module is None or not _active_fast_binding_matches(fast_module, request):
                        raise AttemptError("initialization_error", "registered Fast controller did not bind this routed session")
                    run_result = runner(request["prompt"], task_id=request["task_id"])
            else:
                run_result = runner(request["prompt"], task_id=request["task_id"])
            if not isinstance(run_result, dict):
                raise AttemptError("provider_error", "Hermes returned an invalid turn result")
            final_response = run_result.get("final_response") or ""
            if _tool_calls_seen(run_result):
                observer.mark_tool_seen()
        except AttemptError as exc:
            error_kind, error_message = exc.kind, str(exc)
        except (KeyboardInterrupt, InterruptedError):
            error_kind, error_message = "interrupted", "attempt was interrupted"
        except TimeoutError:
            error_kind, error_message = "timeout", "attempt exceeded its runtime budget"
        except Exception as exc:
            error_kind, error_message = "provider_error", _safe_redact(str(exc), dependencies)
        finally:
            if agent is not None:
                try:
                    agent.close()
                except Exception:
                    closure_complete = False
            if session_db is not None:
                try:
                    release_db(session_db)
                except Exception:
                    closure_complete = False
            if public_progress is not None:
                try:
                    public_progress.close()
                except Exception:
                    pass
        try:
            evidence = observer.snapshot() if observer is not None else {}
        except Exception:
            evidence = {}

        evidence = evidence if isinstance(evidence, dict) else {}
        tool_seen = bool(evidence.get("tool_seen"))
        partial_output = bool(evidence.get("partial_output"))
        observed_routes = evidence.get("observed_routes")
        if not isinstance(observed_routes, list):
            observed_routes = []
        evidence_complete = evidence.get("evidence_complete") is True
        exhaustion_confirmed = (
            evidence.get("exhaustion_confirmed") is True
            and not tool_seen
            and not partial_output
            and closure_complete
        )
        completed = (
            error_kind is None
            and run_result.get("completed") is True
            and run_result.get("failed") is not True
            and run_result.get("partial") is not True
            and run_result.get("interrupted") is not True
        )
        detected_kind, detected_message = _result_error_kind(
            run_result, evidence, request["route"]["provider"], request["route"]["model"]
        )
        if detected_kind == "route_mismatch":
            evidence_complete = False
        if error_kind is None and detected_kind is not None:
            error_kind, error_message = detected_kind, detected_message
            completed = False
        if not closure_complete:
            error_kind, error_message, completed = "initialization_error", "agent or session-store closure was incomplete", False
            exhaustion_confirmed = False
        if not evidence_complete:
            completed = False
            if error_kind is None:
                error_kind, error_message = "evidence_missing", "main-loop API observation is incomplete"
        if error_kind == "subscription_exhaustion":
            completed = False
        if error_kind is not None:
            final_response = _safe_redact(final_response, dependencies)
            message = _safe_redact(error_message or "attempt failed", dependencies)[:MAX_ERROR_CHARS]
            error = {"kind": error_kind, "message": message}
        else:
            final_response = _safe_redact(final_response, dependencies)
            error = None
        exit_code = 0 if completed and closure_complete and evidence_complete and error is None else (130 if error_kind == "interrupted" else 1)
        response_routes = []
        for route in observed_routes[:64]:
            if not isinstance(route, dict) or set(route) != {"provider", "model", "api_mode", "request_model", "response_model"}:
                continue
            response_routes.append({
                "provider": str(route["provider"])[:300],
                "model": str(route["model"])[:300],
                "api_mode": str(route["api_mode"])[:80],
                "request_model": route["request_model"] if isinstance(route["request_model"], str) else None,
                "response_model": route["response_model"] if isinstance(route["response_model"], str) else None,
            })
        return {
            "schema": SCHEMA,
            "attempt_id": request["attempt_id"],
            "job_id": request["job_id"],
            "session_id": request["session_id"],
            "task_id": request["task_id"],
            "requested_route": dict(request["route"]),
            "completed": bool(completed),
            "error": error,
            "final_response": final_response,
            "tool_seen": tool_seen,
            "partial_output": partial_output,
            "evidence_complete": evidence_complete,
            "closure_complete": closure_complete,
            "observed_routes": response_routes,
            "exhaustion_confirmed": exhaustion_confirmed,
            "exit_code": exit_code,
        }


def _atomic_json(path: Path, result: dict[str, Any]) -> None:
    if set(result) != RESULT_FIELDS:
        raise ValueError("result envelope fields do not match schema 1")
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request_path = Path(args.request).expanduser()
    result_path = Path(args.result).expanduser()
    try:
        if not request_path.is_absolute() or request_path.name != "attempt-request.json":
            raise AttemptError("initialization_error", "request path is not the fixed attempt request")
        if not result_path.is_absolute() or result_path.name != "attempt-result.json":
            raise AttemptError("initialization_error", "result path is not the fixed attempt result")
        if request_path.parent != result_path.parent or result_path.is_symlink():
            raise AttemptError("initialization_error", "request and result paths are not sibling attempt artifacts")
        raw = request_path.read_bytes()
        if len(raw) > MAX_REQUEST_BYTES:
            raise AttemptError("initialization_error", "request artifact exceeds the size limit")
        request = json.loads(raw.decode("utf-8"))
        _validated, _expected_request, expected_result = _validate_request(request, request_path)
        if result_path.resolve(strict=False) != expected_result.resolve(strict=False):
            raise AttemptError("initialization_error", "result path is outside the validated attempt directory")
        result = run_attempt(request)
        _atomic_json(expected_result, result)
        return result["exit_code"]
    except AttemptError:
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
