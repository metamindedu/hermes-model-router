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
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = SKILL_ROOT / "references" / "model-routing-cache.json"
ROUTE_CLASSES = {"LIGHTWEIGHT", "HEAVYWEIGHT"}
MODES = {"review", "plan", "implementation", "mechanical"}
VERIFICATION_KINDS = {"none", "mechanical", "semantic-final", "independent-review"}
FALLBACK_REASONS = {
    "not_needed",
    "not_exhaustion",
    "not_declared",
    "route_unresolvable",
    "disabled",
    "exhaustion",
}
# Conservative subscription usage-limit signatures; extend only with observed
# message families so unrelated provider errors never trigger a paid fallback.
EXHAUSTION_PATTERNS = (
    re.compile(r"(?i)you'?ve\s+(?:hit|reached)\s+your\s+usage\s+limit"),
    re.compile(
        r"(?i)(?:hit|reached|exceeded)\s+(?:your\s+|the\s+)?"
        r"(?:usage\s+limits?|workspace\s+spend\s+cap)"
    ),
    re.compile(r"(?i)usage\s+limits?\s+(?:have\s+been\s+|has\s+been\s+|were\s+)?reached"),
    re.compile(r"(?i)usage[_\s-]limit[_\s-](?:reached|exceeded)"),
)


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


def detect_exhaustion(stdout: str, stderr: str) -> bool:
    """Detect a subscription usage-limit failure conservatively."""
    haystack = f"{stdout}\n{stderr}"
    return any(pattern.search(haystack) for pattern in EXHAUSTION_PATTERNS)


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-class", choices=sorted(ROUTE_CLASSES), required=True)
    parser.add_argument("--mode", choices=sorted(MODES), default="review")
    parser.add_argument("--verification-kind", choices=sorted(VERIFICATION_KINDS))
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--profile")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--toolsets")
    parser.add_argument("--worktree", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=0.0)
    parser.add_argument("--hermes-exe")
    parser.add_argument("--no-fallback", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
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
        fallback_reason = "not_needed" if exit_code == 0 else "not_exhaustion"

        if exit_code != 0:
            if not detect_exhaustion(stdout, stderr):
                fallback_reason = "not_exhaustion"
            elif args.no_fallback:
                fallback_reason = "disabled"
            else:
                try:
                    fallback_route = resolve_fallback(args.cache, args.route_class)
                except ValueError:
                    fallback_reason = "route_unresolvable"
                else:
                    if fallback_route is None:
                        fallback_reason = "not_declared"
                    else:
                        fallback_reason = "exhaustion"
                        fallback_used = True
                        primary_stdout = stdout
                        primary_stderr = stderr
                        fallback_command = build_command(
                            hermes_command=resolve_hermes_command(args.hermes_exe),
                            route=fallback_route,
                            prompt=compose_prompt(
                                task,
                                args.route_class,
                                args.mode,
                                str(cwd),
                                note=(
                                    "Route note: the primary subscription route reported a "
                                    "usage-limit exhaustion; this run continues once on the "
                                    "cache-declared fallback route."
                                ),
                            ),
                            profile=args.profile,
                            toolsets=toolsets,
                            worktree=args.worktree,
                            source=source,
                        )
                        exit_code, stdout, stderr = run_child_process(
                            fallback_command, cwd=str(cwd), env=child_env, timeout=args.timeout
                        )
                        effective_route = fallback_route

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


if __name__ == "__main__":
    raise SystemExit(main())
