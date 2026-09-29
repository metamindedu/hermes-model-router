#!/usr/bin/env python3
"""Run one explicitly routed Hermes process without mutating global config.

This helper is intentionally blocking. The caller may run it through Hermes'
`terminal` tool with background=true and notify_on_complete=true.

When the primary run fails with a detected subscription usage-limit failure,
the helper continues once (unless `--no-fallback`) on the route class's
declared fallback route from the canonical cache and records both routes in
the artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = SKILL_ROOT / "references" / "model-routing-cache.json"
SCOPED_AGENT_PATH = SKILL_ROOT / "model_router" / "scoped_agent.py"
ROUTE_CLASSES = {"LIGHTWEIGHT", "HEAVYWEIGHT"}
MODES = {"review", "plan", "implementation", "mechanical"}
PURPOSES = {
    "implementation", "mechanical", "preliminary-review", "plan", "semantic-final", "independent-review"
}
VERIFICATION_KINDS = {"none", "mechanical", "semantic-final", "independent-review"}
FALLBACK_REASONS = {
    "not_needed",
    "not_exhaustion",
    "not_declared",
    "route_unresolvable",
    "disabled",
    "exhaustion",
}


def _validate_operator_routes(routes: Any) -> None:
    """Validate operator intent using the shared cache contract."""
    validator_path = Path(__file__).with_name("routing_cache.py")
    spec = importlib.util.spec_from_file_location(
        "adaptive_coding_orchestration_routing_cache", validator_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load operator route validator: {validator_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError(f"cannot load operator route validator: {exc}") from exc
    validator = getattr(module, "validate_operator_routes", None)
    if not callable(validator):
        raise ValueError("routing_cache.py does not define validate_operator_routes")
    try:
        validator(routes)
    except ValueError as exc:
        raise ValueError(f"invalid operator_routes: {exc}") from exc


def resolve_route(cache_path: Path, route_class: str) -> dict[str, Any]:
    normalized = route_class.strip().upper()
    if normalized not in ROUTE_CLASSES:
        raise ValueError(f"unsupported route class: {route_class}")
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read route cache: {exc}") from exc
    if "operator_routes" in data:
        operator_routes = data["operator_routes"]
        _validate_operator_routes(operator_routes)
        if not isinstance(operator_routes, dict):
            raise ValueError("invalid operator_routes: must be an object")
        route = operator_routes.get(normalized)
        if not isinstance(route, dict):
            raise ValueError(f"operator_routes has no {normalized} route")
        if not all(field in route for field in ("provider", "model_id", "reasoning_effort")):
            raise ValueError(f"invalid operator_routes.{normalized}: missing route fields")
        return {
            "provider": route["provider"],
            "model_id": route["model_id"],
            "reasoning_effort": route["reasoning_effort"],
            "role": normalized,
            "status": "active",
        }
    routes = data.get("default_routes") or {}
    key = routes.get(normalized)
    models = {
        item.get("key"): item
        for item in data.get("models", [])
        if isinstance(item, dict) and item.get("key")
    }
    model = models.get(key)
    if not model:
        raise ValueError(f"route class {normalized} has no configured model")
    if model.get("status") != "active":
        raise ValueError(f"route class {normalized} points to a non-active model")
    if model.get("role") != normalized:
        raise ValueError(f"route class {normalized} points to role {model.get('role')}")
    provider = str(model.get("provider") or "").strip()
    model_id = str(model.get("model_id") or "").strip()
    if not provider or not model_id:
        raise ValueError(f"route class {normalized} is missing provider/model_id")
    return dict(model)


def resolve_fallback(cache_path: Path, route_class: str) -> dict[str, Any] | None:
    """Return the declared fallback route for a class.

    Returns None when no fallback is declared; raises ValueError when a
    declared fallback exists but is not usable as configured.
    """
    normalized = route_class.strip().upper()
    if normalized not in ROUTE_CLASSES:
        raise ValueError(f"unsupported route class: {route_class}")
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read route cache: {exc}") from exc
    fallbacks = data.get("fallback_routes")
    if not isinstance(fallbacks, dict):
        return None
    key = fallbacks.get(normalized)
    if not key:
        return None
    models = {
        item.get("key"): item
        for item in data.get("models", [])
        if isinstance(item, dict) and item.get("key")
    }
    model = models.get(key)
    if not model:
        raise ValueError(f"fallback for {normalized} points to unknown model")
    if model.get("status") != "active":
        raise ValueError(f"fallback for {normalized} is not active")
    if model.get("role") != normalized:
        raise ValueError(f"fallback for {normalized} has role {model.get('role')}")
    provider = str(model.get("provider") or "").strip()
    model_id = str(model.get("model_id") or "").strip()
    if not provider or not model_id:
        raise ValueError(f"fallback for {normalized} is missing provider/model_id")
    return dict(model)


def compose_prompt(
    task: str, route_class: str, mode: str, cwd: str, note: str | None = None
) -> str:
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    common = [
        f"You are an explicitly routed {route_class} coding agent.",
        "Do not call delegate_task or spawn another agent.",
        "Do not modify Hermes configuration, credentials, profiles, or core source.",
        f"Workspace: {cwd}",
    ]
    if note:
        common.append(note)
    if mode == "review":
        common.extend(
            [
                "Treat the implementation as untrusted and review it independently.",
                "Do not modify files. Find and explain problems before proposing changes.",
                "Return: findings ordered by severity, evidence, rationale, recommended direction, and required tests.",
            ]
        )
    elif mode == "plan":
        common.extend(
            [
                "Analyze requirements and architecture. Do not modify the user's main worktree.",
                "If an isolated worktree is provided, changes there are exploratory and must not be published.",
                "Return a concrete plan, assumptions, risks, and verification strategy.",
            ]
        )
    elif mode == "mechanical":
        common.extend(
            [
                "Focus on mechanical execution: tests, lint, typecheck, build, logs, and straightforward fixes.",
                "Stop and report when semantic ambiguity, architecture risk, security risk, or repeated similar failure appears.",
            ]
        )
    else:
        common.extend(
            [
                "Implement only the scoped task and verify it with the requested tests.",
                "Preserve unrelated user changes and do not commit, push, deploy, or publish.",
            ]
        )
    common.extend(["", "Task:", task.strip()])
    return "\n".join(common)


def default_toolsets(mode: str) -> str:
    """Toolsets a routed child gets when the caller does not override ``--toolsets``.

    A review reads the workspace it is asked to review, so it needs file tools. The ``safe``
    group is web/vision/image_gen only, which made a workspace review fail closed with no way
    to reach the files.
    """
    return "file" if mode == "review" else "file,terminal,code_execution"


def resolve_hermes_command(value: str | None = None) -> list[str]:
    configured = (value or os.environ.get("HERMES_CLI") or "").strip()
    if configured:
        path = Path(configured)
        if path.suffix.lower() == ".py":
            return [sys.executable, str(path)]
        return [configured]
    found = shutil.which("hermes")
    if not found:
        raise ValueError("hermes CLI was not found on PATH")
    return [found]


def build_command(
    *,
    hermes_command: list[str],
    route: dict[str, Any],
    prompt: str,
    profile: str | None,
    toolsets: str | None,
    worktree: bool,
    source: str | None = None,
) -> list[str]:
    command = list(hermes_command)
    if profile:
        command.extend(["--profile", profile])
    if worktree:
        command.append("--worktree")
    command.extend(["chat", "-q", prompt, "-m", str(route["model_id"])])
    provider = str(route.get("provider") or "").strip()
    if provider:
        command.extend(["--provider", provider])
    reasoning_effort = route.get("reasoning_effort")
    if reasoning_effort:
        command.extend(["--reasoning", str(reasoning_effort)])
    if toolsets:
        command.extend(["-t", toolsets])
    if source:
        command.extend(["--source", source])
    command.append("-Q")
    return command


_REDACTION_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(
        r'''(?ix)
        ( ["']? (?:api[_-]?key|token|secret|password|credential) ["']?
          \s* [=:] \s* ["']? )
        [^"'\s,;}]+
        '''
    ),
    re.compile(r"(?i)\b(?:sk|rk|pk)-(?:proj-)?[A-Za-z0-9_-]{12,}\b"),
)


def redact_text(text: str) -> str:
    redacted = text
    for index, pattern in enumerate(_REDACTION_PATTERNS):
        replacement = r"\1[REDACTED]" if index < 2 else "[REDACTED]"
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _sha256_if_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_config_paths(profile: str | None) -> list[Path]:
    candidates: list[Path] = []
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        candidates.append(Path(env_home) / "config.yaml")
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "hermes"
    if profile and profile != "default":
        candidates.append(local / "profiles" / profile / "config.yaml")
    else:
        candidates.append(local / "config.yaml")
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate.absolute())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _candidate_state_dbs(profile: str | None) -> list[Path]:
    paths = [path.with_name("state.db") for path in _candidate_config_paths(profile)]
    return [path for path in paths if path.is_file()]


def find_session_evidence(
    *,
    profile: str | None,
    source: str,
    started_epoch: float,
    requested_model: str,
    requested_provider: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for db_path in _candidate_state_dbs(profile):
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2)
            try:
                result = conn.execute(
                    "SELECT id, model, billing_provider, started_at FROM sessions "
                    "WHERE source=? AND started_at>=? ORDER BY started_at DESC",
                    (source, started_epoch - 2.0),
                ).fetchall()
            finally:
                conn.close()
            for session_id, model, provider, row_started in result:
                rows.append(
                    {
                        "session_id": session_id,
                        "model": model,
                        "provider": provider,
                        "started_at": row_started,
                        "db_path": str(db_path),
                    }
                )
        except (OSError, sqlite3.Error):
            continue
    exact = [
        row
        for row in rows
        if row.get("model") == requested_model
        and (requested_provider is None or row.get("provider") == requested_provider)
    ]
    if len(exact) == 1:
        return {"status": "verified", **exact[0]}
    if exact:
        return {"status": "ambiguous", "matches": len(exact)}
    if len(rows) == 1:
        return {"status": "unverified", "matches": 0, **rows[0]}
    return {"status": "unverified", "matches": 0}


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def run_child_process(
    command: list[str], *, cwd: str, env: dict[str, str], timeout: float
) -> tuple[int, str, str]:
    """Run one routed child, returning (exit_code, stdout, stderr), secrets redacted."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout if timeout > 0 else None,
            check=False,
        )
        return (
            completed.returncode,
            redact_text(completed.stdout or ""),
            redact_text(completed.stderr or ""),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = redact_text((exc.stdout or "") if isinstance(exc.stdout, str) else "")
        stderr = redact_text((exc.stderr or "") if isinstance(exc.stderr, str) else "")
        stderr += f"\nrouted process timed out after {timeout:g}s"
        return 124, stdout, stderr


def _read_task(args: argparse.Namespace) -> str:
    if bool(args.prompt) == bool(args.prompt_file):
        raise ValueError("provide exactly one of --prompt or --prompt-file")
    if args.prompt:
        return args.prompt
    return args.prompt_file.read_text(encoding="utf-8")


_RESULT_FIELDS = {
    "schema",
    "attempt_id",
    "job_id",
    "session_id",
    "task_id",
    "requested_route",
    "completed",
    "error",
    "final_response",
    "tool_seen",
    "partial_output",
    "evidence_complete",
    "closure_complete",
    "observed_routes",
    "exhaustion_confirmed",
    "exit_code",
}
_OBSERVED_ROUTE_FIELDS = {
    "provider", "model", "api_mode", "request_model", "response_model"
}


def _uuid_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _runner_route(route: dict[str, Any]) -> dict[str, str]:
    provider = route.get("provider")
    model = route.get("model_id")
    reasoning = route.get("reasoning_effort") or "none"
    if not all(isinstance(item, str) and item for item in (provider, model, reasoning)):
        raise ValueError("resolved route is missing provider, model, or reasoning")
    return {"provider": provider, "model": model, "reasoning": reasoning}


def _approved_snapshot_fallback(snapshot: dict[str, Any]) -> bool:
    evidence = snapshot.get("model_provider_evidence")
    if not isinstance(evidence, dict) or evidence.get("fallback_enabled") is not True:
        return False
    policy = evidence.get("fallback_policy")
    return (
        isinstance(policy, dict)
        and policy.get("trigger") == "subscription_exhaustion_before_tools"
        and type(policy.get("max_retries")) is int
        and policy.get("max_retries") == 1
        and policy.get("approved") is True
    )


def _scoped_home(profile: str) -> Path:
    if not isinstance(profile, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", profile) is None:
        raise ValueError("invalid profile")
    raw = os.environ.get("HERMES_HOME")
    if not raw:
        raise ValueError("profile home is unavailable")
    home = Path(raw).expanduser().resolve()
    if profile == "default":
        if home.parent.name == "profiles":
            raise ValueError("default profile does not match Hermes home")
    elif home.name != profile or home.parent.name != "profiles":
        raise ValueError("profile does not match Hermes home")
    return home


def _scoped_job_context(
    job_dir: Path, profile: str, purpose: str, route_class: str, cwd: Path
) -> tuple[Path, dict[str, Any]]:
    home = _scoped_home(profile)
    current = home
    for part in ("plugin-data", "model-router", "jobs"):
        current = current / part
        if current.is_symlink() or current.resolve().parent != current.parent.resolve():
            raise ValueError("profile job root escapes Hermes home")
    raw_job = job_dir.expanduser()
    if raw_job.is_symlink():
        raise ValueError("job directory must not be a symbolic link")
    resolved_job = raw_job.resolve()
    if resolved_job.parent != current.resolve() or not _uuid_text(resolved_job.name):
        raise ValueError("job directory is outside the active profile")
    snapshot_path = resolved_job / "snapshot.json"
    if snapshot_path.is_symlink() or snapshot_path.resolve().parent != resolved_job:
        raise ValueError("job snapshot is outside its job directory")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError("job snapshot must contain an object")
    if (
        snapshot.get("job_id") != resolved_job.name
        or snapshot.get("profile") != profile
        or snapshot.get("purpose") != purpose
        or snapshot.get("route_class") != route_class
        or snapshot.get("cwd") != str(cwd.resolve())
    ):
        raise ValueError("job snapshot does not match scoped runner arguments")
    return resolved_job, snapshot


def _validate_adapter_result(
    value: Any,
    *,
    request: dict[str, Any],
    process_code: int,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RESULT_FIELDS:
        raise ValueError("scoped adapter result has an invalid shape")
    if (
        type(value.get("schema")) is not int
        or value["schema"] != 1
        or value.get("attempt_id") != request["attempt_id"]
        or value.get("job_id") != request["job_id"]
        or value.get("session_id") != request["session_id"]
        or value.get("task_id") != request["task_id"]
        or not _uuid_text(value.get("attempt_id"))
        or not _uuid_text(value.get("job_id"))
        or not _uuid_text(value.get("session_id"))
        or not _uuid_text(value.get("task_id"))
    ):
        raise ValueError("scoped adapter result identifiers do not match its request")
    if value.get("requested_route") != request["route"]:
        raise ValueError("scoped adapter result route does not match its request")
    for name in ("completed", "tool_seen", "partial_output", "evidence_complete", "closure_complete", "exhaustion_confirmed"):
        if type(value.get(name)) is not bool:
            raise ValueError(f"scoped adapter result field {name} must be boolean")
    if type(value.get("exit_code")) is not int:
        raise ValueError("scoped adapter exit_code must be an integer")
    if process_code != value["exit_code"]:
        raise ValueError("scoped adapter process/result exit codes do not match")
    if not isinstance(value.get("final_response"), str):
        raise ValueError("scoped adapter final_response must be text")
    error = value.get("error")
    if error is not None and (
        not isinstance(error, dict)
        or set(error) != {"kind", "message"}
        or not isinstance(error.get("kind"), str)
        or not isinstance(error.get("message"), str)
    ):
        raise ValueError("scoped adapter error has an invalid shape")
    routes = value.get("observed_routes")
    if not isinstance(routes, list):
        raise ValueError("scoped adapter observed_routes must be a list")
    expected = request["route"]
    matching_routes = bool(routes)
    for route in routes:
        if not isinstance(route, dict) or set(route) != _OBSERVED_ROUTE_FIELDS:
            raise ValueError("scoped adapter route evidence has an invalid shape")
        if (
            not isinstance(route.get("provider"), str)
            or not isinstance(route.get("model"), str)
            or not isinstance(route.get("api_mode"), str)
            or not route["api_mode"]
            or any(route.get(name) is not None and not isinstance(route.get(name), str)
                   for name in ("request_model", "response_model"))
        ):
            raise ValueError("scoped adapter route evidence is malformed")
        matching_routes = matching_routes and (
            route["provider"] == expected["provider"]
            and route["model"] == expected["model"]
            and route.get("request_model") in (None, expected["model"])
            and route.get("response_model") in (None, expected["model"])
        )
    value = dict(value)
    value["_routes_match"] = matching_routes and value["evidence_complete"] is True
    value["_terminal_consistent"] = (
        (value["completed"] is True and error is None and value["exit_code"] == 0)
        or (value["completed"] is False and error is not None and value["exit_code"] != 0)
    )
    return value


def _attempt_summary(result: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    error = result.get("error")
    safe_error = None
    if isinstance(error, dict):
        safe_error = {
            "kind": error["kind"][:100],
            "message": redact_text(error["message"][:2000]),
        }
    return {
        "attempt_id": request["attempt_id"],
        "session_id": request["session_id"],
        "task_id": request["task_id"],
        "requested_route": dict(request["route"]),
        "completed": result["completed"],
        "error": safe_error,
        "final_response": result["final_response"][:100000],
        "tool_seen": result["tool_seen"],
        "partial_output": result["partial_output"],
        "evidence_complete": result["evidence_complete"],
        "closure_complete": result["closure_complete"],
        "observed_routes": result["observed_routes"],
        "exit_code": result["exit_code"],
        "routes_match": result["_routes_match"],
        "terminal_consistent": result["_terminal_consistent"],
        "exhaustion_confirmed": result["exhaustion_confirmed"],
        "timed_out": False,
        "process_tree_closed": None,
        "cleanup_verified": None,
        "process_exit_code": result.get("_process_code"),
    }


def _unavailable_attempt_summary(
    request: dict[str, Any],
    *,
    error_kind: str,
    timed_out: bool,
    cleanup_verified: bool | None,
    process_code: int | None,
) -> dict[str, Any]:
    message = (
        "scoped attempt exceeded its shared deadline"
        if timed_out
        else "scoped adapter exited without a valid result artifact"
    )
    return {
        "attempt_id": request["attempt_id"],
        "session_id": request["session_id"],
        "task_id": request["task_id"],
        "requested_route": dict(request["route"]),
        "completed": False,
        "error": {"kind": error_kind, "message": message},
        "final_response": "",
        "tool_seen": None,
        "partial_output": None,
        "evidence_complete": False,
        "closure_complete": False,
        "observed_routes": [],
        "exit_code": process_code,
        "routes_match": False,
        "terminal_consistent": False,
        "exhaustion_confirmed": None,
        "timed_out": timed_out,
        "process_tree_closed": True if cleanup_verified is True else None,
        "cleanup_verified": cleanup_verified,
        "process_exit_code": process_code,
    }


def _scoped_unavailable_artifact(
    *,
    route_class: str,
    mode: str,
    verification_kind: str,
    profile: str,
    cwd: Path,
    primary_route: dict[str, str],
    terminal_request: dict[str, Any],
    terminal_summary: dict[str, Any],
    attempts: list[dict[str, Any]],
    fallback_used: bool,
    fallback_reason: str,
    fallback_route: dict[str, str] | None,
    config_unchanged: bool,
    started_at: str,
) -> tuple[dict[str, Any], int]:
    timed_out = terminal_summary["timed_out"] is True
    process_code = terminal_summary["process_exit_code"]
    error = terminal_summary["error"]
    exit_code = 124 if timed_out else 1
    verification_status = "not_requested" if verification_kind == "none" else "unmet"
    artifact = {
        "execution_mode": "scoped_sdk",
        "route_class": route_class,
        "mode": mode,
        "verification_kind": verification_kind,
        "verification_status": verification_status,
        "verification_scope": "route_only",
        "requested_model": primary_route["model"],
        "requested_provider": primary_route["provider"],
        "requested_reasoning_effort": primary_route["reasoning"],
        "effective_model": terminal_request["route"]["model"],
        "effective_provider": terminal_request["route"]["provider"],
        "effective_reasoning_effort": terminal_request["route"]["reasoning"],
        "actual_model": None,
        "actual_provider": None,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "fallback_route": (
            {"provider": fallback_route["provider"], "model_id": fallback_route["model"]}
            if fallback_route is not None else None
        ),
        "primary_exit_code": attempts[0].get("process_exit_code") if attempts else None,
        "primary_stdout": attempts[0].get("final_response") if attempts else None,
        "primary_stderr": (
            attempts[0].get("error", {}).get("message")
            if attempts and isinstance(attempts[0].get("error"), dict) else None
        ),
        "profile": profile,
        "requested_cwd": str(cwd),
        "source": "model-router-coding-route",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exit_code": exit_code,
        "process_exit_code": exit_code,
        "config_unchanged": config_unchanged,
        "session_evidence": {
            "status": "unverified",
            "session_id": terminal_request["session_id"],
            "task_id": terminal_request["task_id"],
            "provider": None,
            "model": None,
        },
        "stdout": "",
        "stderr": error["message"],
        "final_response": "",
        "error": error,
        "completed": False,
        "tool_seen": None,
        "partial_output": None,
        "evidence_complete": False,
        "closure_complete": False,
        "route_verified": False,
        "timed_out": timed_out,
        "timeout_stage": "fallback" if timed_out and fallback_used else "primary" if timed_out else None,
        "process_tree_closed": terminal_summary["process_tree_closed"],
        "cleanup_verified": terminal_summary["cleanup_verified"],
        "terminal_attempt_id": terminal_request["attempt_id"],
        "adapter_exit_code": process_code,
        "observed_routes": [],
        "attempts": attempts,
    }
    return artifact, exit_code


def _write_scoped_artifact(output_path: Path, job_dir: Path, artifact: dict[str, Any]) -> None:
    if output_path.is_symlink() or output_path.resolve().parent != job_dir.resolve():
        raise ValueError("runner artifact is outside its job directory")
    _atomic_write_json(output_path, artifact)


def _stop_scoped_process_tree(process: subprocess.Popen[Any]) -> bool:
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if not taskkill:
            try:
                process.kill()
            except OSError:
                pass
            return False
        try:
            killed = subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            process.wait(timeout=2)
            return killed.returncode == 0 and process.poll() is not None
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, 0)
    except (OSError, ProcessLookupError):
        return process.poll() is not None
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return False
    try:
        os.killpg(process.pid, 0)
    except (OSError, ProcessLookupError):
        return process.poll() is not None
    return False


def _invoke_scoped_adapter(
    request: dict[str, Any], attempt_dir: Path, cwd: Path, deadline: float
) -> tuple[dict[str, Any] | None, bool, bool | None, int | None]:
    request_path = attempt_dir / "attempt-request.json"
    result_path = attempt_dir / "attempt-result.json"
    if request_path.is_symlink() or result_path.is_symlink():
        raise ValueError("scoped attempt artifact must not be a symbolic link")
    request_budget = deadline - time.monotonic()
    if request_budget <= 0:
        return None, True, None, None
    request["budget_seconds"] = request_budget
    _atomic_write_json(request_path, request)
    env = dict(os.environ)
    env["MODEL_ROUTER_ATTEMPT_REQUEST"] = str(request_path)
    env["HERMES_SINGLE_QUERY_SESSION"] = "1"
    command = [
        sys.executable,
        "-B",
        str(SCOPED_AGENT_PATH),
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    creation: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        creation["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        creation["start_new_session"] = True
    process = subprocess.Popen(command, **creation)
    wait_budget = deadline - time.monotonic()
    if wait_budget <= 0:
        cleanup_verified = _stop_scoped_process_tree(process)
        return None, True, cleanup_verified, None
    try:
        process_code = process.wait(timeout=wait_budget)
    except subprocess.TimeoutExpired:
        cleanup_verified = _stop_scoped_process_tree(process)
        return None, True, cleanup_verified, None
    if result_path.is_symlink() or not result_path.is_file():
        return None, False, None, process_code
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, False, None, process_code
    return _validate_adapter_result(payload, request=request, process_code=process_code), False, None, process_code


def _scoped_attempt(
    *,
    job_dir: Path,
    home: Path,
    job_id: str,
    profile: str,
    cwd: Path,
    route: dict[str, str],
    route_class: str,
    mode: str,
    task: str,
    toolsets: list[str],
    attempt_deadline: float,
    parent_session_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool, int | None, bool | None]:
    attempt_id = str(uuid.uuid4())
    attempt_dir = job_dir / "attempts" / attempt_id
    attempts_root = job_dir / "attempts"
    if attempts_root.is_symlink() or attempts_root.resolve().parent != job_dir.resolve():
        raise ValueError("attempt root escapes its job directory")
    attempts_root.mkdir(parents=True, exist_ok=True)
    if attempt_dir.is_symlink() or attempt_dir.resolve().parent != attempts_root.resolve():
        raise ValueError("attempt directory escapes its job")
    attempt_dir.mkdir(parents=False, exist_ok=False)
    if os.name != "nt":
        os.chmod(attempt_dir, 0o700)
    request = {
        "schema": 1,
        "attempt_id": attempt_id,
        "job_id": job_id,
        "profile": profile,
        "home": str(home),
        "cwd": str(cwd),
        "source": "model-router-coding-route",
        "task_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "parent_session_id": parent_session_id,
        "route": dict(route),
        "toolsets": list(toolsets),
        "prompt": compose_prompt(
            task,
            route_class,
            mode,
            str(cwd),
            note=(
                "Start a fresh routed task attempt. Do not resume or import another session."
                if parent_session_id is None
                else "This is a fresh one-time fallback task after a structured subscription exhaustion. "
                     "Do not import or continue the prior conversation; use only this task prompt."
            ),
        ),
    }
    result, timed_out, cleanup_verified, process_code = _invoke_scoped_adapter(
        request, attempt_dir, cwd, attempt_deadline
    )
    if result is None:
        return None, request, timed_out, process_code, cleanup_verified
    result["_process_closed"] = process_code is not None
    result["_process_code"] = process_code
    return result, request, False, process_code, cleanup_verified


def _scoped_failure_artifact(
    *, args: argparse.Namespace, route_class: str, mode: str, verification_kind: str,
    profile: str, cwd: Path, route: dict[str, str], result: dict[str, Any],
    request: dict[str, Any], attempts: list[dict[str, Any]], fallback_used: bool,
    fallback_reason: str, fallback_route: dict[str, str] | None,
    primary_exit_code: int, started_at: str, config_unchanged: bool,
) -> tuple[dict[str, Any], int]:
    observed = result["observed_routes"]
    actual = observed[-1] if observed else {}
    successful = (
        result["completed"] is True
        and result["error"] is None
        and result["exit_code"] == 0
        and result["closure_complete"] is True
        and result["evidence_complete"] is True
        and result["_routes_match"] is True
        and result["_terminal_consistent"] is True
        and result["_process_closed"] is True
        and config_unchanged
    )
    route_verified = successful
    verification_status = (
        "not_requested" if verification_kind == "none"
        else "route_verified" if route_verified
        else "unmet"
    )
    exit_code = result["exit_code"] if result["exit_code"] != 0 else (0 if successful else 1)
    if verification_status == "unmet" and exit_code == 0:
        exit_code = 1
    error = result.get("error")
    safe_error = None
    if isinstance(error, dict):
        safe_error = {
            "kind": error["kind"][:100],
            "message": redact_text(error["message"][:2000]),
        }
    final_response = result["final_response"][:100000]
    evidence_status = "verified" if successful else "unverified"
    artifact = {
        "execution_mode": "scoped_sdk",
        "route_class": route_class,
        "mode": mode,
        "verification_kind": verification_kind,
        "verification_status": verification_status,
        "verification_scope": "route_only",
        "requested_model": route["model"],
        "requested_provider": route["provider"],
        "requested_reasoning_effort": route["reasoning"],
        "effective_model": request["route"]["model"],
        "effective_provider": request["route"]["provider"],
        "effective_reasoning_effort": request["route"]["reasoning"],
        "actual_model": actual.get("model"),
        "actual_provider": actual.get("provider"),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "fallback_route": (
            {"provider": fallback_route["provider"], "model_id": fallback_route["model"]}
            if fallback_route is not None else None
        ),
        "primary_exit_code": primary_exit_code,
        "primary_stdout": attempts[0].get("final_response"),
        "primary_stderr": attempts[0].get("error", {}).get("message") if attempts and attempts[0].get("error") else None,
        "profile": profile,
        "requested_cwd": str(cwd),
        "source": request["source"],
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exit_code": exit_code,
        "process_exit_code": exit_code,
        "config_unchanged": config_unchanged,
        "session_evidence": {
            "status": evidence_status,
            "session_id": request["session_id"],
            "task_id": request["task_id"],
            "provider": actual.get("provider"),
            "model": actual.get("model"),
        },
        "stdout": final_response,
        "stderr": safe_error["message"] if safe_error else "",
        "final_response": final_response,
        "error": safe_error,
        "completed": result["completed"],
        "tool_seen": result["tool_seen"],
        "partial_output": result["partial_output"],
        "evidence_complete": result["evidence_complete"] and result["_routes_match"],
        "closure_complete": result["closure_complete"] and result["_process_closed"],
        "observed_routes": observed,
        "attempts": attempts,
    }
    return artifact, exit_code


def run_scoped_attempts(args: argparse.Namespace) -> int:
    task = _read_task(args)
    verification_kind = args.verification_kind or (
        "independent-review" if args.mode == "review" else "none"
    )
    if verification_kind in {"semantic-final", "independent-review"} and args.route_class != "HEAVYWEIGHT":
        raise ValueError(f"verification kind {verification_kind} requires HEAVYWEIGHT")
    if args.profile is None or args.job_dir is None or args.output is None or args.purpose is None:
        raise ValueError("scoped execution requires --profile, --purpose, --job-dir, and --output")
    if not isinstance(args.timeout, (int, float)) or args.timeout <= 0 or not math.isfinite(args.timeout):
        raise ValueError("scoped execution requires a positive finite timeout")
    cwd = args.cwd.resolve()
    if not cwd.is_dir():
        raise ValueError("working directory does not exist")
    job_dir, snapshot = _scoped_job_context(
        args.job_dir, args.profile, args.purpose, args.route_class, cwd
    )
    home = _scoped_home(args.profile)
    route_raw = resolve_route(args.cache, args.route_class)
    primary_route = _runner_route(route_raw)
    snapshot_evidence = snapshot.get("model_provider_evidence")
    snapshot_requested = snapshot_evidence.get("requested") if isinstance(snapshot_evidence, dict) else None
    if not isinstance(snapshot_requested, dict) or snapshot_requested.get(args.route_class) != primary_route:
        raise ValueError("resolved primary route does not match the immutable job snapshot")
    fallback_enabled = (
        not args.no_fallback
        and isinstance(snapshot_evidence, dict)
        and snapshot_evidence.get("fallback_enabled") is True
        and _approved_snapshot_fallback(snapshot)
    )
    fallback_route: dict[str, str] | None = None
    fallback_reason = "disabled" if args.no_fallback or not fallback_enabled else "not_needed"
    if fallback_enabled:
        try:
            raw_fallback = resolve_fallback(args.cache, args.route_class)
            fallback_route = _runner_route(raw_fallback) if raw_fallback else None
        except (ValueError, TypeError):
            fallback_reason = "route_unresolvable"
        else:
            snapshot_fallbacks = snapshot_evidence.get("fallback") if isinstance(snapshot_evidence, dict) else None
            expected_fallback = (
                snapshot_fallbacks.get(args.route_class)
                if isinstance(snapshot_fallbacks, dict)
                else None
            )
            if fallback_route is None:
                fallback_reason = "not_declared"
            elif fallback_route != expected_fallback:
                fallback_route = None
                fallback_reason = "route_unresolvable"
            elif (fallback_route["provider"], fallback_route["model"]) == (primary_route["provider"], primary_route["model"]):
                fallback_route = None
                fallback_reason = "route_unresolvable"
            else:
                fallback_reason = "not_needed"

    raw_toolsets = args.toolsets if args.toolsets is not None else default_toolsets(args.mode)
    toolsets = [item.strip() for item in raw_toolsets.split(",") if item.strip()]
    if not toolsets:
        raise ValueError("scoped execution requires at least one toolset")
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started_epoch = time.monotonic()
    deadline = started_epoch + float(args.timeout)
    reserve = min(float(args.timeout) / 2.0, max(0.25, min(30.0, float(args.timeout) * 0.1)))
    config_path = home / "config.yaml"
    before_config = _sha256_if_file(config_path)
    if before_config is None:
        raise ValueError("active profile config snapshot is unavailable")
    primary_deadline = deadline - reserve
    if primary_deadline <= time.monotonic():
        raise ValueError("common execution deadline is insufficient for a primary attempt")
    primary_result, primary_request, primary_timed_out, primary_process_code, primary_cleanup_verified = _scoped_attempt(
        job_dir=job_dir, home=home, job_id=job_dir.name, profile=args.profile,
        cwd=cwd, route=primary_route, route_class=args.route_class, mode=args.mode,
        task=task, toolsets=toolsets, attempt_deadline=primary_deadline, parent_session_id=None,
    )
    if primary_request is None:
        raise RuntimeError("primary scoped attempt did not produce a request record")
    if primary_timed_out or primary_result is None:
        error_kind = (
            "timeout" if primary_timed_out
            else "adapter_crash" if primary_process_code not in (None, 0)
            else "result_missing"
        )
        terminal_summary = _unavailable_attempt_summary(
            primary_request,
            error_kind=error_kind,
            timed_out=primary_timed_out,
            cleanup_verified=primary_cleanup_verified,
            process_code=primary_process_code,
        )
        attempts = [terminal_summary]
        config_unchanged = before_config == _sha256_if_file(config_path)
        artifact, exit_code = _scoped_unavailable_artifact(
            route_class=args.route_class,
            mode=args.mode,
            verification_kind=verification_kind,
            profile=args.profile,
            cwd=cwd,
            primary_route=primary_route,
            terminal_request=primary_request,
            terminal_summary=terminal_summary,
            attempts=attempts,
            fallback_used=False,
            fallback_reason="not_exhaustion",
            fallback_route=None,
            config_unchanged=config_unchanged,
            started_at=started_at,
        )
        _write_scoped_artifact(args.output, job_dir, artifact)
        print(json.dumps({
            "artifact": str(args.output),
            "execution_mode": "scoped_sdk",
            "verification_status": artifact["verification_status"],
            "fallback_used": False,
            "fallback_reason": artifact["fallback_reason"],
            "exit_code": exit_code,
        }))
        return exit_code
    attempts = [_attempt_summary(primary_result, primary_request)]
    primary_error = primary_result.get("error")
    is_exhaustion = (
        primary_result["completed"] is False
        and isinstance(primary_error, dict)
        and primary_error.get("kind") == "subscription_exhaustion"
        and primary_result["exhaustion_confirmed"] is True
        and primary_result["tool_seen"] is False
        and primary_result["partial_output"] is False
        and primary_result["evidence_complete"] is True
        and primary_result["closure_complete"] is True
        and primary_result["_routes_match"] is True
        and primary_result["_terminal_consistent"] is True
        and primary_result["_process_closed"] is True
        and primary_result["exit_code"] != 0
    )
    selected_result = primary_result
    selected_request = primary_request
    fallback_used = False
    if primary_result["completed"] is True:
        fallback_reason = "not_needed"
    elif not is_exhaustion:
        fallback_reason = "not_exhaustion" if primary_error is None or primary_error.get("kind") != "subscription_exhaustion" else "unsafe_evidence"
    elif not fallback_enabled or fallback_route is None:
        fallback_reason = "disabled" if not fallback_enabled else fallback_reason
    elif _sha256_if_file(config_path) != before_config:
        fallback_reason = "config_changed"
    else:
        remaining = deadline - time.monotonic()
        if remaining < reserve:
            fallback_reason = "insufficient_deadline"
        else:
            fallback_used = True
            fallback_reason = "exhaustion"
            fallback_result, fallback_request, fallback_timed_out, fallback_process_code, fallback_cleanup_verified = _scoped_attempt(
                job_dir=job_dir, home=home, job_id=job_dir.name, profile=args.profile,
                cwd=cwd, route=fallback_route, route_class=args.route_class, mode=args.mode,
                task=task, toolsets=toolsets, attempt_deadline=deadline,
                parent_session_id=primary_request["session_id"],
            )
            if fallback_request is None:
                raise RuntimeError("fallback scoped attempt did not produce a request record")
            if fallback_timed_out or fallback_result is None:
                error_kind = (
                    "timeout" if fallback_timed_out
                    else "adapter_crash" if fallback_process_code not in (None, 0)
                    else "result_missing"
                )
                terminal_summary = _unavailable_attempt_summary(
                    fallback_request,
                    error_kind=error_kind,
                    timed_out=fallback_timed_out,
                    cleanup_verified=fallback_cleanup_verified,
                    process_code=fallback_process_code,
                )
                attempts.append(terminal_summary)
                config_unchanged = before_config == _sha256_if_file(config_path)
                artifact, exit_code = _scoped_unavailable_artifact(
                    route_class=args.route_class,
                    mode=args.mode,
                    verification_kind=verification_kind,
                    profile=args.profile,
                    cwd=cwd,
                    primary_route=primary_route,
                    terminal_request=fallback_request,
                    terminal_summary=terminal_summary,
                    attempts=attempts,
                    fallback_used=True,
                    fallback_reason="exhaustion",
                    fallback_route=fallback_route,
                    config_unchanged=config_unchanged,
                    started_at=started_at,
                )
                _write_scoped_artifact(args.output, job_dir, artifact)
                print(json.dumps({
                    "artifact": str(args.output),
                    "execution_mode": "scoped_sdk",
                    "verification_status": artifact["verification_status"],
                    "fallback_used": True,
                    "fallback_reason": artifact["fallback_reason"],
                    "exit_code": exit_code,
                }))
                return exit_code
            attempts.append(_attempt_summary(fallback_result, fallback_request))
            selected_result = fallback_result
            selected_request = fallback_request

    config_unchanged = before_config == _sha256_if_file(config_path)
    artifact, exit_code = _scoped_failure_artifact(
        args=args, route_class=args.route_class, mode=args.mode,
        verification_kind=verification_kind, profile=args.profile, cwd=cwd,
        route=primary_route, result=selected_result, request=selected_request,
        attempts=attempts, fallback_used=fallback_used, fallback_reason=fallback_reason,
        fallback_route=fallback_route if fallback_used else None,
        primary_exit_code=primary_result["exit_code"], started_at=started_at,
        config_unchanged=config_unchanged,
    )
    output_path = args.output
    _write_scoped_artifact(output_path, job_dir, artifact)
    print(json.dumps({
        "artifact": str(output_path),
        "execution_mode": "scoped_sdk",
        "verification_status": artifact["verification_status"],
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "exit_code": exit_code,
    }))
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-class", choices=sorted(ROUTE_CLASSES), required=True)
    parser.add_argument("--mode", choices=sorted(MODES), default="review")
    parser.add_argument("--verification-kind", choices=sorted(VERIFICATION_KINDS))
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--profile")
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--purpose", choices=sorted(PURPOSES))
    parser.add_argument("--scoped-attempts", action="store_true")
    parser.add_argument("--legacy-chat", action="store_true")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--toolsets")
    parser.add_argument("--worktree", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=0.0)
    parser.add_argument("--hermes-exe")
    parser.add_argument("--no-fallback", action="store_true")
    return parser


def _legacy_main(args: argparse.Namespace) -> int:
    try:
        task = _read_task(args)
        route = resolve_route(args.cache, args.route_class)
        verification_kind = args.verification_kind or (
            "independent-review" if args.mode == "review" else "none"
        )
        if (
            verification_kind in {"semantic-final", "independent-review"}
            and args.route_class != "HEAVYWEIGHT"
        ):
            raise ValueError(
                f"verification kind {verification_kind} requires HEAVYWEIGHT; "
                f"received {args.route_class}"
            )
        cwd = args.cwd.resolve()
        if not cwd.is_dir():
            raise ValueError(f"working directory does not exist: {cwd}")
        toolsets = args.toolsets
        if toolsets is None:
            toolsets = default_toolsets(args.mode)
        prompt = compose_prompt(task, args.route_class, args.mode, str(cwd))
        source = f"adaptive-coding-orchestration:{secrets.token_hex(8)}"
        command = build_command(
            hermes_command=resolve_hermes_command(args.hermes_exe),
            route=route,
            prompt=prompt,
            profile=args.profile,
            toolsets=toolsets,
            worktree=args.worktree,
            source=source,
        )

        config_paths = _candidate_config_paths(args.profile)
        before_hashes = {str(path): _sha256_if_file(path) for path in config_paths}
        started_epoch = time.time()
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        child_env = dict(os.environ)
        # Hermes terminal/file tools resolve their session workspace from
        # TERMINAL_CWD when present.  Pin it for this child process so a stale
        # value loaded from the parent profile's .env cannot override --cwd.
        child_env["TERMINAL_CWD"] = str(cwd)
        exit_code, stdout, stderr = run_child_process(
            command, cwd=str(cwd), env=child_env, timeout=args.timeout
        )
        primary_exit_code = exit_code
        primary_stdout: str | None = None
        primary_stderr: str | None = None
        effective_route = route
        fallback_route: dict[str, Any] | None = None
        fallback_used = False
        fallback_reason = "not_needed" if exit_code == 0 else "disabled"

        after_hashes = {str(path): _sha256_if_file(path) for path in config_paths}
        config_unchanged = before_hashes == after_hashes
        evidence = find_session_evidence(
            profile=args.profile,
            source=source,
            started_epoch=started_epoch,
            requested_model=str(effective_route["model_id"]),
            requested_provider=str(effective_route["provider"]),
        )
        route_verified = (
            exit_code == 0
            and config_unchanged
            and evidence.get("status") == "verified"
        )
        verification_status = (
            "not_requested"
            if verification_kind == "none"
            else "route_verified"
            if route_verified
            else "unmet"
        )
        runner_exit_code = exit_code
        if verification_status == "unmet" and runner_exit_code == 0:
            runner_exit_code = 1
        result = {
            "execution_mode": "legacy_chat",
            "route_class": args.route_class,
            "mode": args.mode,
            "verification_kind": verification_kind,
            "verification_status": verification_status,
            "verification_scope": "route_only",
            "requested_model": route["model_id"],
            "requested_provider": route["provider"],
            "requested_reasoning_effort": route.get("reasoning_effort"),
            "effective_model": effective_route["model_id"],
            "effective_provider": effective_route["provider"],
            "effective_reasoning_effort": effective_route.get("reasoning_effort"),
            "actual_model": evidence.get("model"),
            "actual_provider": evidence.get("provider"),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "fallback_route": (
                {
                    "provider": str(fallback_route["provider"]),
                    "model_id": str(fallback_route["model_id"]),
                }
                if fallback_route is not None
                else None
            ),
            "primary_exit_code": primary_exit_code,
            "primary_stdout": primary_stdout,
            "primary_stderr": primary_stderr,
            "profile": args.profile or os.environ.get("HERMES_PROFILE") or "default",
            "requested_cwd": str(cwd),
            "source": source,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "exit_code": runner_exit_code,
            "process_exit_code": exit_code,
            "config_unchanged": config_unchanged,
            "session_evidence": evidence,
            "stdout": stdout,
            "stderr": stderr,
        }
        output_path = args.output
        if output_path is None:
            output_path = Path(tempfile.gettempdir()) / f"hermes-routed-{source.rsplit(':', 1)[1]}.json"
        _atomic_write_json(output_path, result)
        if stdout:
            print(stdout, end="" if stdout.endswith("\n") else "\n")
        if stderr:
            print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
        print(
            json.dumps(
                {
                    "artifact": str(output_path),
                    "session_evidence": evidence,
                    "config_unchanged": config_unchanged,
                    "effective_model": effective_route["model_id"],
                    "actual_model": evidence.get("model"),
                    "actual_provider": evidence.get("provider"),
                    "verification_kind": verification_kind,
                    "verification_status": verification_status,
                    "exit_code": runner_exit_code,
                    "fallback_used": fallback_used,
                    "fallback_reason": fallback_reason,
                }
            )
        )
        return runner_exit_code
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"run_routed_agent: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.scoped_attempts == args.legacy_chat:
        print(
            "run_routed_agent: choose exactly one of --scoped-attempts or --legacy-chat",
            file=sys.stderr,
        )
        return 2
    if args.scoped_attempts:
        try:
            return run_scoped_attempts(args)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"run_routed_agent: scoped execution failed ({type(exc).__name__})", file=sys.stderr)
            return 2
    return _legacy_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
