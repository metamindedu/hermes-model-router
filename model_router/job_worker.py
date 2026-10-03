"""Detached job worker for the model-router backend.

The worker owns runner invocation and terminal-state artifacts. It uses only
fixed local Python/runner/CLI paths supplied by Router.start and never a shell.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PURPOSES = {
    "implementation": ("LIGHTWEIGHT", "implementation", "none"),
    "mechanical": ("LIGHTWEIGHT", "mechanical", "mechanical"),
    "preliminary-review": ("LIGHTWEIGHT", "review", "none"),
    "plan": ("HEAVYWEIGHT", "plan", "none"),
    "semantic-final": ("HEAVYWEIGHT", "review", "semantic-final"),
    "independent-review": ("HEAVYWEIGHT", "review", "independent-review"),
}
PROFILE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, body: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _job_file(job_dir: Path, name: str) -> Path:
    root = job_dir.resolve()
    path = job_dir / name
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError("job artifact is outside its job directory")
    return path


def _validated_job_dir(value: Path, profile: str) -> Path:
    if PROFILE_TOKEN.fullmatch(profile) is None or profile in {".", ".."}:
        raise ValueError("invalid profile name")
    raw = value.expanduser()
    if raw.is_symlink():
        raise ValueError("job directory must not be a symbolic link")
    home_value = os.environ.get("HERMES_HOME")
    if not home_value:
        raise ValueError("profile home is unavailable")
    home = Path(home_value).expanduser().resolve()
    if profile != "default" and (home.name != profile or home.parent.name != "profiles"):
        raise ValueError("worker profile does not match its Hermes home")
    if profile == "default" and home.parent.name == "profiles":
        raise ValueError("default profile home is not the Hermes base")
    jobs = home / "plugin-data" / "model-router" / "jobs"
    current = home
    for part in ("plugin-data", "model-router", "jobs"):
        current = current / part
        if current.is_symlink() or current.resolve().parent != current.parent.resolve():
            raise ValueError("profile job root escapes the Hermes home")
    resolved = raw.resolve()
    if not resolved.is_dir() or resolved.parent != jobs.resolve():
        raise ValueError("job directory is outside the active profile")
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("job artifact must not be a symbolic link")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("job artifact must contain an object")
    return value


def build_runner_command(
    *,
    python: str,
    runner: Path,
    hermes_exe: Path,
    profile: str,
    purpose: str,
    cwd: Path,
    timeout: float,
    job_dir: Path,
    snapshot: dict[str, Any],
) -> list[str]:
    if purpose not in PURPOSES:
        raise ValueError("unsupported routing purpose")
    role, mode, verification_kind = PURPOSES[purpose]
    command = [
        python,
        str(runner),
        "--route-class",
        role,
        "--mode",
        mode,
        "--verification-kind",
        verification_kind,
        "--prompt-file",
        str(_job_file(job_dir, "prompt.txt")),
        "--cache",
        str(_job_file(job_dir, "routing-cache.json")),
        "--profile",
        profile,
        "--purpose",
        purpose,
        "--cwd",
        str(cwd),
        "--timeout",
        repr(float(timeout)),
        "--output",
        str(_job_file(job_dir, "runner-result.json")),
        "--job-dir",
        str(job_dir),
        "--scoped-attempts",
        "--hermes-exe",
        str(hermes_exe),
    ]
    evidence = snapshot.get("model_provider_evidence")
    policy = evidence.get("fallback_policy") if isinstance(evidence, dict) else None
    approved = (
        isinstance(policy, dict)
        and policy.get("trigger") == "subscription_exhaustion_before_tools"
        and type(policy.get("max_retries")) is int
        and policy.get("max_retries") == 1
        and policy.get("approved") is True
    )
    if not isinstance(evidence, dict) or evidence.get("fallback_enabled") is not True or not approved:
        command.append("--no-fallback")
    return command


def _terminate_process_tree(process: subprocess.Popen[Any]) -> bool:
    """Stop only this worker-owned runner tree and verify that it closed."""
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if not taskkill:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
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
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
        return killed.returncode == 0 and process.poll() is not None

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


def run_job(
    *,
    job_dir: Path,
    runner: Path,
    python: str,
    hermes_exe: Path,
    profile: str,
    purpose: str,
    cwd: Path,
    timeout: float,
) -> int:
    job_dir = _validated_job_dir(job_dir, profile)
    if purpose not in PURPOSES:
        raise ValueError("unsupported routing purpose")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout is outside the supported bound")
    expected_runner = (Path(__file__).resolve().parents[1] / "lib" / "run_routed_agent.py").resolve()
    if runner.resolve() != expected_runner or not runner.is_file():
        raise ValueError("runner path does not match the bundled runner")
    if Path(python).resolve() != Path(sys.executable).resolve():
        raise ValueError("Python path does not match the worker interpreter")
    configured_cli = shutil.which("hermes")
    if not configured_cli or Path(configured_cli).resolve() != hermes_exe.resolve() or not hermes_exe.is_file():
        raise ValueError("Hermes launcher does not match the resolved local CLI")
    if not cwd.is_dir():
        raise ValueError("working directory does not exist")

    snapshot = _read_json(_job_file(job_dir, "snapshot.json"))
    job_id = job_dir.name
    if str(uuid.UUID(job_id)) != job_id:
        raise ValueError("job directory name is not a canonical UUID")
    if (
        snapshot.get("job_id") != job_id
        or snapshot.get("profile") != profile
        or snapshot.get("purpose") != purpose
        or snapshot.get("cwd") != str(cwd.resolve())
        or ("timeout_seconds" in snapshot and snapshot["timeout_seconds"] != timeout)
    ):
        raise ValueError("immutable job snapshot does not match worker arguments")

    started_at = _utc_now()
    state_path = _job_file(job_dir, "state.json")
    _atomic_json(
        state_path,
        {
            "status": "running",
            "worker_pid": os.getpid(),
            "started_at": started_at,
        },
    )
    try:
        command = build_runner_command(
            python=python,
            runner=runner,
            hermes_exe=hermes_exe,
            profile=profile,
            purpose=purpose,
            cwd=cwd.resolve(),
            timeout=timeout,
            job_dir=job_dir,
            snapshot=snapshot,
        )
        log_path = _job_file(job_dir, "job.log")
        creation: dict[str, Any] = {
            "cwd": str(job_dir),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            creation["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            creation["start_new_session"] = True
        with log_path.open("ab"):
            process = subprocess.Popen(command, **creation)
        try:
            # Slicing only the OS wait avoids Windows millisecond overflow for
            # large valid budgets; the single overall deadline never resets.
            worker_deadline = time.monotonic() + timeout + 5.0 if timeout > 0 else None
            while True:
                remaining = max(0.0, worker_deadline - time.monotonic()) if worker_deadline is not None else None
                try:
                    runner_code = process.wait(timeout=min(remaining, 86400.0) if remaining is not None else None)
                    break
                except subprocess.TimeoutExpired:
                    if remaining is None or remaining <= 86400.0 or time.monotonic() >= worker_deadline:
                        raise
        except subprocess.TimeoutExpired:
            cleanup_verified = _terminate_process_tree(process)
            _atomic_json(
                state_path,
                {
                    "status": "failed",
                    "worker_pid": os.getpid(),
                    "error_type": "RunnerTimeout",
                    "timed_out": True,
                    "cleanup_verified": cleanup_verified,
                    "process_tree_closed": True if cleanup_verified else None,
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                },
            )
            return 124
        result_path = _job_file(job_dir, "runner-result.json")
        try:
            result = _read_json(result_path)
        except (OSError, json.JSONDecodeError, ValueError):
            result = None
        finished_at = _utc_now()
        if result is None:
            _atomic_json(
                state_path,
                {
                    "status": "failed" if runner_code != 0 else "unverified",
                    "worker_pid": os.getpid(),
                    "runner_exit_code": runner_code,
                    "error_type": "MissingRunnerArtifact",
                    "timed_out": False,
                    "cleanup_verified": None,
                    "process_tree_closed": None,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
            )
        else:
            runner_exit_code = result.get("exit_code")
            terminal = "failed" if runner_code != 0 or runner_exit_code != 0 else "finished"
            _atomic_json(
                state_path,
                {
                    "status": terminal,
                    "worker_pid": os.getpid(),
                    "worker_exit_code": runner_code,
                    "runner_exit_code": runner_exit_code,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
            )
        return runner_code
    except BaseException as exc:
        _atomic_json(
            state_path,
            {
                "status": "failed",
                "worker_pid": os.getpid(),
                "error_type": type(exc).__name__,
                "timed_out": False,
                "cleanup_verified": None,
                "process_tree_closed": None,
                "started_at": started_at,
                "finished_at": _utc_now(),
            },
        )
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--hermes-exe", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--purpose", choices=sorted(PURPOSES), required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run_job(
            job_dir=args.job_dir,
            runner=args.runner,
            python=args.python,
            hermes_exe=args.hermes_exe,
            profile=args.profile,
            purpose=args.purpose,
            cwd=args.cwd,
            timeout=args.timeout,
        )
    except BaseException as exc:
        try:
            job_dir = _validated_job_dir(args.job_dir, args.profile)
            if job_dir.is_dir():
                _atomic_json(
                    _job_file(job_dir, "state.json"),
                    {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "finished_at": _utc_now(),
                    },
                )
        except BaseException:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
