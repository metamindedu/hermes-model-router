from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

import pytest

from lib import run_routed_agent as runner


HEAVY = {"provider": "primary-heavy", "model": "primary/heavy", "reasoning": "high"}
LIGHT = {"provider": "primary-light", "model": "primary/light", "reasoning": "low"}
HEAVY_BACKUP = {"provider": "backup-heavy", "model": "backup/heavy", "reasoning": "medium"}
LIGHT_BACKUP = {"provider": "backup-light", "model": "backup/light", "reasoning": "none"}
POLICY = {
    "trigger": "subscription_exhaustion_before_tools",
    "max_retries": 1,
    "approved": True,
}


def _entry(key: str, route: dict[str, str], role: str) -> dict[str, Any]:
    return {
        "key": key,
        "provider": route["provider"],
        "model_id": route["model"],
        "reasoning_effort": route["reasoning"],
        "role": role,
        "status": "active",
    }


def _short_home() -> Path:
    """Fake Hermes base with a deliberately short prefix.

    The scoped attempt artifacts live at
    ``<home>/plugin-data/model-router/jobs/<uuid>/attempts/<uuid>``. A pytest
    ``tmp_path`` root under a deep scratch tree pushes that past the Windows
    260-character path limit, which is an environment limit, not a product
    defect — so the fake home is created on a short temporary root instead.
    """
    base = Path(tempfile.mkdtemp(prefix="mrh", dir=tempfile.gettempdir()))
    atexit.register(shutil.rmtree, base, True)
    (base / "profiles" / "claire").mkdir(parents=True)
    return base


def _fixture(
    tmp_path: Path,
    *,
    approved: bool = True,
    role: str = "HEAVYWEIGHT",
    parent_session_id: str | None = None,
) -> dict[str, Any]:
    base = _short_home()
    home = base / "profiles" / "claire"
    job_id = str(uuid.uuid4())
    job_dir = home / "plugin-data" / "model-router" / "jobs" / job_id
    cwd = tmp_path / "workspace"
    job_dir.mkdir(parents=True)
    cwd.mkdir(exist_ok=True)
    config_path = home / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("private_config_value: never-copy-this\n", encoding="utf-8")
    primary = HEAVY if role == "HEAVYWEIGHT" else LIGHT
    other = LIGHT if role == "HEAVYWEIGHT" else HEAVY
    backup = HEAVY_BACKUP if role == "HEAVYWEIGHT" else LIGHT_BACKUP
    other_backup = LIGHT_BACKUP if role == "HEAVYWEIGHT" else HEAVY_BACKUP
    role_evidence = {"HEAVYWEIGHT": dict(HEAVY), "LIGHTWEIGHT": dict(LIGHT)}
    fallback_evidence = {"HEAVYWEIGHT": dict(HEAVY_BACKUP), "LIGHTWEIGHT": dict(LIGHT_BACKUP)}
    snapshot = {
        "schema": 1,
        "job_id": job_id,
        "profile": "claire",
        "purpose": "plan" if role == "HEAVYWEIGHT" else "implementation",
        "route_class": role,
        "cwd": str(cwd.resolve()),
        "parent_session_id": parent_session_id,
        "model_provider_evidence": {
            "purpose_role": role,
            "requested": role_evidence,
            "fallback_enabled": approved,
            "fallback_policy": {**POLICY, "approved": approved},
            "fallback": fallback_evidence if approved else {"HEAVYWEIGHT": None, "LIGHTWEIGHT": None},
            "actual": None,
        },
    }
    (job_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (job_dir / "prompt.txt").write_text("Implement the bounded change.", encoding="utf-8")
    cache_path = job_dir / "routing-cache.json"
    cache = {
        "models": [
            _entry("heavy-primary", HEAVY, "HEAVYWEIGHT"),
            _entry("light-primary", LIGHT, "LIGHTWEIGHT"),
            _entry("heavy-backup", HEAVY_BACKUP, "HEAVYWEIGHT"),
            _entry("light-backup", LIGHT_BACKUP, "LIGHTWEIGHT"),
        ],
        "default_routes": {"HEAVYWEIGHT": "heavy-primary", "LIGHTWEIGHT": "light-primary"},
        "fallback_routes": {"HEAVYWEIGHT": "heavy-backup", "LIGHTWEIGHT": "light-backup"},
    }
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return {
        "home": home,
        "job_id": job_id,
        "job_dir": job_dir,
        "cwd": cwd,
        "config_path": config_path,
        "cache_path": cache_path,
        "role": role,
        "primary": primary,
        "other": other,
        "backup": backup,
        "other_backup": other_backup,
    }


def _args(fixture: dict[str, Any], *, timeout: float = 60, no_fallback: bool = False) -> Any:
    role = fixture["role"]
    return runner.argparse.Namespace(
        route_class=role,
        mode="plan" if role == "HEAVYWEIGHT" else "implementation",
        verification_kind="none",
        prompt=None,
        prompt_file=fixture["job_dir"] / "prompt.txt",
        cache=fixture["cache_path"],
        profile="claire",
        job_dir=fixture["job_dir"],
        purpose="plan" if role == "HEAVYWEIGHT" else "implementation",
        cwd=fixture["cwd"],
        toolsets=None,
        worktree=False,
        output=fixture["job_dir"] / "runner-result.json",
        timeout=timeout,
        hermes_exe=None,
        no_fallback=no_fallback,
        scoped_attempts=True,
        legacy_chat=False,
    )


def _observed(route: dict[str, str], *, provider: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    actual_provider = provider or route["provider"]
    actual_model = model or route["model"]
    return [{
        "provider": actual_provider,
        "model": actual_model,
        "api_mode": "openai-compatible",
        "request_model": actual_model,
        "response_model": actual_model,
    }]


def _result(
    request: dict[str, Any],
    *,
    completed: bool,
    error: dict[str, str] | None = None,
    final_response: str = "",
    tool_seen: bool = False,
    partial_output: bool = False,
    evidence_complete: bool = True,
    closure_complete: bool = True,
    exhaustion_confirmed: bool = False,
    exit_code: int | None = None,
    observed_routes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    code = (0 if completed else 1) if exit_code is None else exit_code
    return {
        "schema": 1,
        "attempt_id": request["attempt_id"],
        "job_id": request["job_id"],
        "session_id": request["session_id"],
        "task_id": request["task_id"],
        "requested_route": dict(request["route"]),
        "completed": completed,
        "error": error,
        "final_response": final_response,
        "tool_seen": tool_seen,
        "partial_output": partial_output,
        "evidence_complete": evidence_complete,
        "closure_complete": closure_complete,
        "observed_routes": observed_routes if observed_routes is not None else _observed(request["route"]),
        "exhaustion_confirmed": exhaustion_confirmed,
        "exit_code": code,
    }


def _install_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[Callable[[dict[str, Any]], dict[str, Any]] | None],
    *,
    on_call: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    commands: list[list[str]] = []
    requests: list[dict[str, Any]] = []

    class FakeProcess:
        def __init__(self, code: int):
            self.pid = 98761 + len(commands)
            self.returncode: int | None = None
            self.code = code

        def wait(self, timeout: float | None = None) -> int:
            if requests[-1]["budget_seconds"] == 0:
                assert timeout is None
            else:
                assert timeout is not None and timeout > 0
            self.returncode = self.code
            return self.code

        def poll(self) -> int | None:
            return self.returncode

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        commands.append(list(command))
        assert command[0] == runner.sys.executable
        assert command[1] == "-B"
        assert command[2] == str(runner.SCOPED_AGENT_PATH)
        assert "chat" not in command
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["close_fds"] is True
        if runner.os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
            assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
            assert not kwargs["creationflags"] & subprocess.DETACHED_PROCESS
        request_path = Path(command[command.index("--request") + 1])
        result_path = Path(command[command.index("--result") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        requests.append(request)
        assert Path(kwargs["env"]["MODEL_ROUTER_ATTEMPT_REQUEST"]) == request_path
        assert kwargs["env"]["HERMES_SINGLE_QUERY_SESSION"] == "1"
        assert kwargs["env"]["HERMES_SESSION_SOURCE"] == "subagent"
        assert kwargs["env"]["HERMES_SESSION_SOURCE_EXPLICIT"] == "1"
        assert kwargs["env"]["HERMES_SESSION_PLATFORM"] == "subagent"
        assert kwargs["env"]["HERMES_PLATFORM"] == "subagent"
        for key in (
            "HERMES_UI_SESSION_ID",
            "HERMES_SESSION_CHAT_ID",
            "HERMES_SESSION_CHAT_TYPE",
            "HERMES_SESSION_CHAT_NAME",
            "HERMES_SESSION_THREAD_ID",
            "HERMES_SESSION_USER_ID",
            "HERMES_SESSION_USER_NAME",
            "HERMES_SESSION_SCOPE_ID",
            "HERMES_SESSION_KEY",
            "HERMES_SESSION_MESSAGE_ID",
            "HERMES_SESSION_PARENT_CHAT_ID",
        ):
            assert key not in kwargs["env"]
        assert request["source"] == "subagent"
        assert request_path.parent == result_path.parent
        assert request_path.parent.parent.name == "attempts"
        assert request_path.parent.name == request["attempt_id"]
        if on_call:
            on_call(request)
        outcome = outcomes.pop(0)
        if outcome is None:
            return FakeProcess(1)
        payload = outcome(request)
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        return FakeProcess(payload["exit_code"])

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    return commands, requests


def test_platform_wait_slices_do_not_restart_overall_deadline(monkeypatch):
    now = [0.0]
    waits = []
    monkeypatch.setattr(runner.time, "monotonic", lambda: now[0])
    class Process:
        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) < 3:
                now[0] += timeout
                raise subprocess.TimeoutExpired("fixture", timeout)
            return 0
    assert runner._wait_scoped_process(Process(), 200000) == 0
    assert waits == [86400, 86400, 200000 - 2 * 86400]


def test_real_platform_wait_accepts_arbitrarily_long_finite_budget():
    import time
    process = subprocess.Popen([runner.sys.executable, "-c", "import time; time.sleep(.05)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert runner._wait_scoped_process(process, time.monotonic() + 1e100) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def _exhaustion(request: dict[str, Any]) -> dict[str, Any]:
    return _result(
        request,
        completed=False,
        error={"kind": "subscription_exhaustion", "message": "subscription exhausted"},
        exhaustion_confirmed=True,
        exit_code=1,
    )


@pytest.mark.parametrize("total_seconds", [60, 0, 7200])
def test_approved_exhaustion_runs_one_fresh_same_role_sdk_attempt(tmp_path, monkeypatch, total_seconds):
    primary_parent_id = "20260930_113515_240566"
    fixture = _fixture(tmp_path, parent_session_id=primary_parent_id)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    commands, requests = _install_fake_adapter(
        monkeypatch,
        [
            _exhaustion,
            lambda request: _result(request, completed=True, final_response="answer from fallback"),
        ],
    )

    assert runner.run_scoped_attempts(_args(fixture, timeout=total_seconds)) == 0
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))

    assert len(commands) == 2
    if total_seconds == 0:
        assert all(request["budget_seconds"] == 0 for request in requests)
    elif total_seconds > 900:
        assert all(900 < request["budget_seconds"] <= total_seconds for request in requests)
    assert artifact["execution_mode"] == "scoped_sdk"
    assert artifact["fallback_used"] is True
    assert artifact["fallback_reason"] == "exhaustion"
    assert artifact["effective_provider"] == HEAVY_BACKUP["provider"]
    assert artifact["effective_model"] == HEAVY_BACKUP["model"]
    assert artifact["actual_provider"] == HEAVY_BACKUP["provider"]
    assert artifact["actual_model"] == HEAVY_BACKUP["model"]
    assert artifact["stdout"] == "answer from fallback"
    assert artifact["session_evidence"]["status"] == "verified"
    assert len(artifact["attempts"]) == 2
    assert requests[0]["route"] == HEAVY
    assert requests[1]["route"] == HEAVY_BACKUP
    assert requests[0]["attempt_id"] != requests[1]["attempt_id"]
    assert requests[0]["session_id"] != requests[1]["session_id"]
    assert requests[0]["task_id"] != requests[1]["task_id"]
    assert requests[0]["source"] == requests[1]["source"] == "subagent"
    assert requests[0]["parent_session_id"] == primary_parent_id
    assert requests[1]["parent_session_id"] == requests[0]["session_id"]
    assert "Start a fresh routed task attempt." in requests[0]["prompt"]
    assert "one-time fallback task" not in requests[0]["prompt"]
    assert "one-time fallback task" in requests[1]["prompt"]
    assert "Start a fresh routed task attempt." not in requests[1]["prompt"]
    assert all(request["toolsets"] for request in requests)
    assert "private_config_value" not in json.dumps(artifact)
    assert not list((fixture["job_dir"] / "attempts").rglob("config.yaml"))


def test_fast_intent_is_immutable_across_primary_fallback_attempt_lineage(tmp_path, monkeypatch):
    original_parent = "native-parent-A"
    fixture = _fixture(tmp_path, parent_session_id=original_parent)
    fast_snapshot = {
        "schema": 1,
        "profile": "claire",
        "origin_session_id": "fast-origin-A",
        "parent_session_id": original_parent,
        "mode": "auto",
        "expires_at": 2_000_000_000.0,
    }
    job_snapshot_path = fixture["job_dir"] / "snapshot.json"
    job_snapshot = json.loads(job_snapshot_path.read_text(encoding="utf-8"))
    job_snapshot["fast_snapshot"] = fast_snapshot
    job_snapshot_path.write_text(json.dumps(job_snapshot), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    _commands, requests = _install_fake_adapter(
        monkeypatch,
        [
            _exhaustion,
            lambda request: _result(request, completed=True, final_response="fallback answer"),
        ],
    )

    assert runner.run_scoped_attempts(_args(fixture)) == 0
    assert len(requests) == 2
    assert [request["schema"] for request in requests] == [2, 2]
    assert all(request["fast_snapshot"] == fast_snapshot for request in requests)
    assert all("service_tier" not in request and "speed" not in request for request in requests)
    assert requests[0]["parent_session_id"] == original_parent
    assert requests[1]["parent_session_id"] == requests[0]["session_id"]
    assert all(request["fast_snapshot"]["parent_session_id"] == original_parent for request in requests)
    for request in requests:
        attempt_dir = fixture["job_dir"] / "attempts" / request["attempt_id"]
        validated, _request_path, _result_path = __import__(
            "model_router.scoped_agent", fromlist=["_validate_request"]
        )._validate_request(request, attempt_dir / "attempt-request.json")
        assert validated["fast_snapshot"] == fast_snapshot


def test_historical_snapshot_without_parent_session_id_keeps_standalone_primary(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    snapshot_path = fixture["job_dir"] / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot.pop("parent_session_id")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    _commands, requests = _install_fake_adapter(
        monkeypatch,
        [lambda request: _result(request, completed=True, final_response="standalone answer")],
    )

    assert runner.run_scoped_attempts(_args(fixture)) == 0
    assert len(requests) == 1
    assert requests[0]["parent_session_id"] is None


def test_only_structured_exhaustion_not_answer_text_triggers_fallback(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    commands, _ = _install_fake_adapter(
        monkeypatch,
        [lambda request: _result(
            request,
            completed=False,
            error={"kind": "provider_error", "message": "temporary provider error"},
            final_response="Your usage limit has been reached",
            exit_code=1,
        )],
    )

    assert runner.run_scoped_attempts(_args(fixture)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["fallback_used"] is False
    assert artifact["fallback_reason"] == "not_exhaustion"
    assert artifact["stdout"] == "Your usage limit has been reached"


@pytest.mark.parametrize(
    "changes",
    [
        {"tool_seen": True},
        {"partial_output": True},
        {"evidence_complete": False},
        {"closure_complete": False},
        {"observed_routes": _observed(HEAVY, provider="other-provider")},
    ],
)
def test_unsafe_or_incomplete_exhaustion_evidence_never_retries(tmp_path, monkeypatch, changes):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))

    def unsafe(request: dict[str, Any]) -> dict[str, Any]:
        return _result(
            request,
            completed=False,
            error={"kind": "subscription_exhaustion", "message": "exhaustion"},
            exhaustion_confirmed=True,
            exit_code=1,
            **changes,
        )

    commands, _ = _install_fake_adapter(monkeypatch, [unsafe])
    assert runner.run_scoped_attempts(_args(fixture)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["fallback_used"] is False
    assert artifact["fallback_reason"] == "unsafe_evidence"


def test_missing_approval_blocks_fallback_even_with_cached_route(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, approved=False)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    commands, _ = _install_fake_adapter(monkeypatch, [_exhaustion])

    assert runner.run_scoped_attempts(_args(fixture)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["fallback_used"] is False
    assert artifact["fallback_reason"] == "disabled"


def test_profile_config_change_after_primary_blocks_fallback(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))

    def mutate_config(_request: dict[str, Any]) -> None:
        fixture["config_path"].write_text("changed: true\n", encoding="utf-8")

    commands, _ = _install_fake_adapter(monkeypatch, [_exhaustion], on_call=mutate_config)
    assert runner.run_scoped_attempts(_args(fixture)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["fallback_used"] is False
    assert artifact["fallback_reason"] == "config_changed"
    assert artifact["config_unchanged"] is False


def test_malformed_result_does_not_fallback_or_fabricate_runner_artifact(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))

    def malformed(request: dict[str, Any]) -> dict[str, Any]:
        payload = _exhaustion(request)
        payload["stdout"] = "subscription usage limit reached"
        return payload

    commands, _ = _install_fake_adapter(monkeypatch, [malformed])
    with pytest.raises(ValueError, match="invalid shape"):
        runner.run_scoped_attempts(_args(fixture))
    assert len(commands) == 1
    assert not (fixture["job_dir"] / "runner-result.json").exists()


@pytest.mark.parametrize("cleanup_verified", [True, False])
def test_primary_timeout_records_terminal_artifact_without_retry(tmp_path, monkeypatch, cleanup_verified):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    calls: list[list[str]] = []

    class TimedOutProcess:
        pid = 56789
        returncode = None

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired("scoped-agent", timeout)

        def poll(self) -> int | None:
            return self.returncode

    def fake_popen(command: list[str], **_kwargs: Any) -> TimedOutProcess:
        calls.append(list(command))
        return TimedOutProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner, "_stop_scoped_process_tree", lambda _process: cleanup_verified)
    assert runner.run_scoped_attempts(_args(fixture)) == 124
    assert len(calls) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert artifact["timed_out"] is True
    assert artifact["completed"] is False
    assert artifact["route_verified"] is False
    assert artifact["closure_complete"] is False
    assert artifact["cleanup_verified"] is cleanup_verified
    assert artifact["process_tree_closed"] is (True if cleanup_verified else None)
    assert artifact["attempts"][0]["error"]["kind"] == "timeout"
    assert artifact["attempts"][0]["exhaustion_confirmed"] is None
    assert artifact["fallback_used"] is False


@pytest.mark.parametrize("cleanup_verified", [True, False])
def test_fallback_timeout_preserves_primary_exhaustion_and_cleanup(
    tmp_path, monkeypatch, cleanup_verified
):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    calls: list[list[str]] = []

    class FinishedProcess:
        def __init__(self, code: int):
            self.pid = 67890
            self.returncode: int | None = None
            self.code = code

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None and timeout > 0
            self.returncode = self.code
            return self.code

    class TimedOutProcess:
        pid = 67891
        returncode = None

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired("scoped-agent", timeout)

        def poll(self) -> int | None:
            return self.returncode

    def fake_popen(command: list[str], **_kwargs: Any) -> Any:
        calls.append(list(command))
        request_path = Path(command[command.index("--request") + 1])
        result_path = Path(command[command.index("--result") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if len(calls) == 1:
            result_path.write_text(json.dumps(_exhaustion(request)), encoding="utf-8")
            return FinishedProcess(1)
        return TimedOutProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner, "_stop_scoped_process_tree", lambda _process: cleanup_verified)

    assert runner.run_scoped_attempts(_args(fixture)) == 124
    assert len(calls) == 2
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert artifact["route_verified"] is False
    assert artifact["timed_out"] is True
    assert artifact["fallback_used"] is True
    assert artifact["fallback_reason"] == "exhaustion"
    assert artifact["cleanup_verified"] is cleanup_verified
    assert artifact["process_tree_closed"] is (True if cleanup_verified else None)
    assert artifact["completed"] is False
    assert artifact["closure_complete"] is False
    assert len(artifact["attempts"]) == 2
    primary, fallback = artifact["attempts"]
    assert primary["error"]["kind"] == "subscription_exhaustion"
    assert primary["exhaustion_confirmed"] is True
    assert primary["timed_out"] is False
    assert fallback["error"]["kind"] == "timeout"
    assert fallback["timed_out"] is True
    assert fallback["process_tree_closed"] is (True if cleanup_verified else None)


def test_adapter_crash_without_result_writes_unverified_terminal_artifact(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    commands, _ = _install_fake_adapter(monkeypatch, [None])

    assert runner.run_scoped_attempts(_args(fixture)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["route_verified"] is False
    assert artifact["completed"] is False
    assert artifact["timed_out"] is False
    assert artifact["error"]["kind"] == "adapter_crash"
    assert artifact["cleanup_verified"] is None
    assert artifact["process_tree_closed"] is None
    assert artifact["attempts"][0]["process_exit_code"] == 1
    assert artifact["fallback_used"] is False


def test_common_deadline_reserve_blocks_late_fallback(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, approved=True)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    commands, _ = _install_fake_adapter(monkeypatch, [_exhaustion])
    # Dispatch, reserve, request/write, pre-wait and OS-wait sampling all
    # precede the late fallback decision; the new platform-safe wait samples
    # the same shared deadline once more, without resetting it.
    ticks = iter([0.0, 0.0, 0.0, 0.0, 0.0, 9.5])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))

    assert runner.run_scoped_attempts(_args(fixture, timeout=10)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["fallback_used"] is False
    assert artifact["fallback_reason"] == "insufficient_deadline"


def test_wrong_role_fallback_is_not_selected(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, approved=True)
    monkeypatch.setenv("HERMES_HOME", str(fixture["home"]))
    cache = json.loads(fixture["cache_path"].read_text(encoding="utf-8"))
    cache["models"] = [
        item for item in cache["models"] if item["key"] != "heavy-backup"
    ] + [_entry("heavy-backup", LIGHT_BACKUP, "LIGHTWEIGHT")]
    fixture["cache_path"].write_text(json.dumps(cache), encoding="utf-8")
    commands, _ = _install_fake_adapter(monkeypatch, [_exhaustion])

    assert runner.run_scoped_attempts(_args(fixture)) == 1
    artifact = json.loads((fixture["job_dir"] / "runner-result.json").read_text(encoding="utf-8"))
    assert len(commands) == 1
    assert artifact["fallback_used"] is False
    assert artifact["fallback_reason"] == "route_unresolvable"
