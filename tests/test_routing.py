from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from model_router import job_worker, routing


HEAVY = {"provider": "heavy-provider", "model": "heavy/model:one", "reasoning": "high"}
LIGHT = {"provider": "light-provider", "model": "light/model:one", "reasoning": "low"}
FALLBACK_HEAVY = {"provider": "backup-heavy", "model": "backup/heavy", "reasoning": "medium"}
FALLBACK_LIGHT = {"provider": "backup-light", "model": "backup/light", "reasoning": "none"}


class FakeProcess:
    pid = 987654


class FakeService:
    def __init__(self, root: Path, profile: str = "claire"):
        self.root = root
        self.profile = profile
        self.enabled = True
        self.drift: list[str] = []
        self.fallback_enabled = False
        self.fallback_approved = True
        self.heavy_fallback = FALLBACK_HEAVY
        self.light_fallback = FALLBACK_LIGHT
        self.heavy = dict(HEAVY)
        self.light = dict(LIGHT)
        self.routing_calls: list[str] = []

    def active_profile(self) -> str:
        return self.profile

    def status(self) -> dict[str, Any]:
        profiles = [
            {"name": name, "drift": self.drift if name == self.profile else []}
            for name in (self.profile, "other-profile")
        ]
        return {"current_profile": self.profile, "profiles": profiles}

    def routing_config(self, profile: str) -> dict[str, Any]:
        self.routing_calls.append(profile)
        assert profile == self.profile
        return {
            "enabled": self.enabled,
            "heavy": dict(self.heavy),
            "light": dict(self.light),
            "fallback": {
                "enabled": self.fallback_enabled,
                "heavy": dict(self.heavy_fallback) if self.heavy_fallback is not None else None,
                "light": dict(self.light_fallback) if self.light_fallback is not None else None,
            },
            "fallback_policy": {
                "trigger": "subscription_exhaustion_before_tools",
                "max_retries": 1,
                "approved": self.fallback_approved,
            },
            "revision": 17,
        }


def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cli = tmp_path / "hermes.exe"
    cli.write_bytes(b"fake executable marker")
    monkeypatch.setattr(routing.shutil, "which", lambda name: str(cli) if name == "hermes" else None)
    return cli


def _make_router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str = "claire"):
    # Native helper import performs version discovery; do it before patching the
    # shared subprocess.Popen module so the fake runner cannot intercept Git.
    from tools.environments.local import served_profile_child_env  # noqa: F401
    # Unit fixtures test spawning, never source-update maintenance/relaunch.
    # A new native bootstrap may otherwise run Git through fake Popen.
    import hermes_cli.venv_sync
    monkeypatch.setattr(hermes_cli.venv_sync, "prepare_launch", lambda *a, **k: None)
    import hermes_bootstrap  # noqa: F401
    root = tmp_path / "hermes"
    root.mkdir()
    service = FakeService(root, profile)
    service.root.joinpath("profiles", profile).mkdir(parents=True)
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(command, **kwargs):
        popen_calls.append((list(command), kwargs))
        return FakeProcess()

    monkeypatch.setattr(routing.subprocess, "Popen", fake_popen)
    _fake_cli(tmp_path, monkeypatch)
    router = routing.Router(service)
    return router, service, root, popen_calls


def _start(router: routing.Router, tmp_path: Path, purpose: str = "implementation"):
    cwd = tmp_path / "work"
    cwd.mkdir(exist_ok=True)
    return router.start(purpose, "Change one function; keep this exact prompt.", cwd, timeout=600)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_start_snapshots_active_profile_routes_and_uses_detached_no_pipe_worker(tmp_path, monkeypatch):
    router, service, root, popen_calls = _make_router(tmp_path, monkeypatch)
    result = _start(router, tmp_path)

    assert result["status"] == "running"
    assert result["profile"] == "claire"
    assert result["requested_model"] == LIGHT["model"]
    assert service.routing_calls == ["claire"]
    assert len(popen_calls) == 1
    command, kwargs = popen_calls[0]
    assert command[0] == sys.executable
    assert command[1] == str(routing.WORKER_PATH)
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is not subprocess.PIPE
    assert kwargs["stderr"] is not subprocess.PIPE
    assert kwargs["close_fds"] is True
    if os.name == "nt":
        assert kwargs["creationflags"] & subprocess.DETACHED_PROCESS
        assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert kwargs["env"]["HERMES_PROFILE"] == "claire"
    assert kwargs["env"]["HERMES_HOME"] == str(root / "profiles" / "claire")

    job_dir = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs" / result["job_id"]
    snapshot = _load(job_dir / "snapshot.json")
    cache = _load(job_dir / "routing-cache.json")
    assert (job_dir / "prompt.txt").read_text(encoding="utf-8") == "Change one function; keep this exact prompt."
    assert snapshot["settings_revision"] == 17
    assert snapshot["model_provider_evidence"]["requested"]["LIGHTWEIGHT"] == LIGHT
    assert snapshot["model_provider_evidence"]["actual"] is None
    assert cache["operator_routes"]["HEAVYWEIGHT"] == {
        "provider": HEAVY["provider"],
        "model_id": HEAVY["model"],
        "reasoning_effort": HEAVY["reasoning"],
    }
    assert cache["operator_routes"]["LIGHTWEIGHT"]["provider"] == LIGHT["provider"]
    assert cache["fallback_routes"] == {}
    assert "--profile" in command and command[command.index("--profile") + 1] == "claire"
    assert "Change one function" not in " ".join(command)


def test_enabled_fallback_is_explicit_in_job_cache(tmp_path, monkeypatch):
    router, service, root, _ = _make_router(tmp_path, monkeypatch)
    service.fallback_enabled = True
    result = _start(router, tmp_path, "plan")
    job_dir = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs" / result["job_id"]
    cache = _load(job_dir / "routing-cache.json")
    snapshot = _load(job_dir / "snapshot.json")

    assert cache["fallback_routes"] == {
        "HEAVYWEIGHT": "backup-heavy/backup/heavy",
        "LIGHTWEIGHT": "backup-light/backup/light",
    }
    routes = {item["key"]: item for item in cache["models"]}
    assert routes["backup-heavy/backup/heavy"]["role"] == "HEAVYWEIGHT"
    assert routes["backup-heavy/backup/heavy"]["reasoning_effort"] == "medium"
    assert snapshot["model_provider_evidence"]["fallback_enabled"] is True
    assert result["route_class"] == "HEAVYWEIGHT"


def test_enabled_fallback_without_current_approval_is_not_snapshotted(tmp_path, monkeypatch):
    router, service, root, popen_calls = _make_router(tmp_path, monkeypatch)
    service.fallback_enabled = True
    service.fallback_approved = False
    result = _start(router, tmp_path, "plan")
    job_dir = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs" / result["job_id"]
    cache = _load(job_dir / "routing-cache.json")
    snapshot = _load(job_dir / "snapshot.json")
    # The runner command is built inside the detached worker, so the approval
    # gate is asserted on the runner builder itself, not on the worker spawn.
    runner_command = job_worker.build_runner_command(
        python=sys.executable,
        runner=job_worker.Path(__file__).resolve().parents[1] / "lib" / "run_routed_agent.py",
        hermes_exe=job_worker.Path(popen_calls[0][0][popen_calls[0][0].index("--hermes-exe") + 1]),
        profile="claire",
        purpose="plan",
        cwd=tmp_path / "work",
        timeout=600,
        job_dir=job_dir,
        snapshot=snapshot,
    )
    assert "--no-fallback" in runner_command
    assert cache["fallback_routes"] == {}
    assert snapshot["model_provider_evidence"]["fallback_enabled"] is False
    assert snapshot["model_provider_evidence"]["fallback_policy"]["approved"] is False


def test_disabled_routing_denies_before_job_or_child_creation(tmp_path, monkeypatch):
    router, service, root, popen_calls = _make_router(tmp_path, monkeypatch)
    service.enabled = False
    with pytest.raises(routing.RoutingError, match="routing is disabled"):
        _start(router, tmp_path)
    assert popen_calls == []
    assert not (root / "profiles" / "claire" / "plugin-data").exists()


def test_model_drift_denies_before_child_creation(tmp_path, monkeypatch):
    router, service, _root, popen_calls = _make_router(tmp_path, monkeypatch)
    service.drift = ["models.main"]
    with pytest.raises(routing.RoutingError, match="model drift"):
        _start(router, tmp_path)
    assert popen_calls == []


def test_mismatched_status_profile_is_rejected(tmp_path, monkeypatch):
    router, service, _root, popen_calls = _make_router(tmp_path, monkeypatch)
    service.status = lambda: {
        "current_profile": "other-profile",
        "profiles": [{"name": "claire", "drift": []}],
    }
    with pytest.raises(routing.RoutingError, match="active profile changed"):
        _start(router, tmp_path)
    assert popen_calls == []


@pytest.mark.parametrize(
    "bad_route",
    [
        {"provider": "heavy-provider", "model": "heavy/model:one", "reasoning": "enabled"},
        {"provider": "light-provider", "model": "light/model:one", "reasoning": "disabled"},
    ],
)
def test_runner_incompatible_primary_effort_fails_before_job_creation(tmp_path, monkeypatch, bad_route):
    router, service, root, popen_calls = _make_router(tmp_path, monkeypatch)
    if bad_route["provider"] == "heavy-provider":
        service.heavy = bad_route
    else:
        service.light = bad_route
    with pytest.raises(routing.RoutingError, match="unsupported by the bundled route runner"):
        _start(router, tmp_path)
    assert popen_calls == []
    assert not (root / "profiles" / "claire" / "plugin-data").exists()


def test_identical_enabled_routes_fail_before_job_creation(tmp_path, monkeypatch):
    router, service, root, popen_calls = _make_router(tmp_path, monkeypatch)
    service.light = dict(HEAVY)
    with pytest.raises(routing.RoutingError, match="distinct models"):
        _start(router, tmp_path)
    assert popen_calls == []
    assert not (root / "profiles" / "claire" / "plugin-data").exists()


def test_skill_only_drift_does_not_masquerade_as_model_drift(tmp_path, monkeypatch):
    router, service, _root, popen_calls = _make_router(tmp_path, monkeypatch)
    service.drift = ["skills.disabled"]
    result = _start(router, tmp_path)
    assert result["status"] == "running"
    assert popen_calls


@pytest.mark.parametrize(
    ("purpose", "route_class", "mode", "verification"),
    [
        ("implementation", "LIGHTWEIGHT", "implementation", "none"),
        ("mechanical", "LIGHTWEIGHT", "mechanical", "mechanical"),
        ("preliminary-review", "LIGHTWEIGHT", "review", "none"),
        ("plan", "HEAVYWEIGHT", "plan", "none"),
        ("semantic-final", "HEAVYWEIGHT", "review", "semantic-final"),
        ("independent-review", "HEAVYWEIGHT", "review", "independent-review"),
    ],
)
def test_purpose_routes_to_frozen_role_and_verification(purpose, route_class, mode, verification):
    command = job_worker.build_runner_command(
        python=sys.executable,
        runner=routing.RUNNER_PATH,
        hermes_exe=Path("C:/fake/hermes.exe"),
        profile="claire",
        purpose=purpose,
        cwd=Path("C:/work"),
        timeout=600,
        job_dir=Path("C:/jobs/01234567-89ab-cdef-0123-456789abcdef"),
        snapshot={"model_provider_evidence": {"fallback_enabled": False}},
    )
    assert command[command.index("--route-class") + 1] == route_class
    assert command[command.index("--mode") + 1] == mode
    assert command[command.index("--verification-kind") + 1] == verification
    assert ("--no-fallback" in command) is True


def test_final_review_never_uses_lightweight_route():
    assert routing.ROUTING_PURPOSES["semantic-final"][0] == "HEAVYWEIGHT"
    assert routing.ROUTING_PURPOSES["independent-review"][0] == "HEAVYWEIGHT"
    assert routing.ROUTING_PURPOSES["preliminary-review"][0] == "LIGHTWEIGHT"


@pytest.mark.parametrize(
    ("purpose", "route_class", "expected_timeout"),
    [
        ("implementation", "LIGHTWEIGHT", 1800),
        ("mechanical", "LIGHTWEIGHT", 1800),
        ("preliminary-review", "LIGHTWEIGHT", 1800),
        ("plan", "HEAVYWEIGHT", 7200),
        ("semantic-final", "HEAVYWEIGHT", 7200),
        ("independent-review", "HEAVYWEIGHT", 7200),
    ],
)
def test_omitted_timeout_uses_the_purpose_role_budget(
    tmp_path, monkeypatch, purpose, route_class, expected_timeout
):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    original = service.routing_config
    service.routing_config = lambda profile: {
        **original(profile),
        "light_timeout_seconds": 1800,
        "heavy_timeout_seconds": 7200,
        # A conflicting legacy value must not override either role budget.
        "timeout_seconds": 123,
    }
    cwd = tmp_path / "work"
    cwd.mkdir()

    result = router.start(purpose, "select the purpose role budget", cwd)

    job_dir = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs" / result["job_id"]
    snapshot = _load(job_dir / "snapshot.json")
    argv_timeout = calls[0][0][calls[0][0].index("--timeout") + 1]
    assert routing.ROUTED_ROLE_TIMEOUTS_SUPPORTED is True
    assert result["route_class"] == route_class
    assert snapshot["route_class"] == route_class
    assert snapshot["timeout_seconds"] == expected_timeout
    assert snapshot["timeout_source"] == "profile"
    assert argv_timeout == repr(float(expected_timeout))


@pytest.mark.parametrize(
    ("purpose", "role_timeout_field", "other_timeout_field"),
    [
        ("implementation", "light_timeout_seconds", "heavy_timeout_seconds"),
        ("plan", "heavy_timeout_seconds", "light_timeout_seconds"),
    ],
)
def test_zero_role_budget_applies_independently(
    tmp_path, monkeypatch, purpose, role_timeout_field, other_timeout_field
):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    original = service.routing_config
    budgets = {role_timeout_field: 0, other_timeout_field: 1800}
    service.routing_config = lambda profile: {
        **original(profile),
        **budgets,
        "timeout_seconds": 7200,
    }
    cwd = tmp_path / "work"
    cwd.mkdir()

    result = router.start(purpose, "zero one role without changing the other", cwd)

    snapshot = _load(
        root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs"
        / result["job_id"] / "snapshot.json"
    )
    assert snapshot["timeout_seconds"] == 0
    assert calls[0][0][calls[0][0].index("--timeout") + 1] == "0.0"


@pytest.mark.parametrize("role_timeout_field,purpose", [
    ("light_timeout_seconds", "implementation"),
    ("heavy_timeout_seconds", "plan"),
])
@pytest.mark.parametrize("invalid_budget", [None, True, float("nan"), -1])
def test_invalid_present_role_budget_never_falls_back_but_call_override_wins(
    tmp_path, monkeypatch, role_timeout_field, purpose, invalid_budget
):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    original = service.routing_config
    service.routing_config = lambda profile: {
        **original(profile),
        role_timeout_field: invalid_budget,
        "timeout_seconds": 7200,
    }
    cwd = tmp_path / "work"
    cwd.mkdir()

    with pytest.raises(routing.RoutingError, match="timeout must be"):
        router.start(purpose, "invalid role budget is fail closed", cwd)
    assert calls == []
    assert not (root / "profiles" / "claire" / "plugin-data").exists()

    result = router.start(purpose, "explicit zero overrides the profile", cwd, timeout=0)
    snapshot = _load(
        root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs"
        / result["job_id"] / "snapshot.json"
    )
    assert snapshot["timeout_seconds"] == 0
    assert snapshot["timeout_source"] == "call"
    assert calls[0][0][calls[0][0].index("--timeout") + 1] == "0.0"


@pytest.mark.parametrize(("legacy_timeout", "expected_timeout"), [(5432, 5432), (None, 3600)])
def test_legacy_timeout_config_is_used_only_when_role_fields_are_absent(
    tmp_path, monkeypatch, legacy_timeout, expected_timeout
):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    original = service.routing_config

    def old_service_config(profile):
        config = original(profile)
        config.pop("light_timeout_seconds", None)
        config.pop("heavy_timeout_seconds", None)
        if legacy_timeout is None:
            config.pop("timeout_seconds", None)
        else:
            config["timeout_seconds"] = legacy_timeout
        return config

    service.routing_config = old_service_config
    cwd = tmp_path / "work"
    cwd.mkdir()

    result = router.start("implementation", "old service DTO compatibility", cwd)

    snapshot = _load(
        root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs"
        / result["job_id"] / "snapshot.json"
    )
    assert snapshot["timeout_seconds"] == expected_timeout
    assert snapshot["timeout_source"] == "profile"
    assert calls[0][0][calls[0][0].index("--timeout") + 1] == repr(float(expected_timeout))


def test_timeout_is_not_capped_and_invalid_inputs_are_rejected(tmp_path, monkeypatch):
    router, _service, _root, calls = _make_router(tmp_path, monkeypatch)
    cwd = tmp_path / "work"
    cwd.mkdir()
    assert router.start("mechanical", "run tests", cwd, timeout=7200)["status"] == "running"
    worker_command = calls[0][0]
    assert float(worker_command[worker_command.index("--timeout") + 1]) == 7200
    assert routing._bounded_timeout(7200) == 7200
    assert routing._bounded_timeout(0) == 0
    for value in (-1, float("inf"), float("nan"), True, "60"):
        with pytest.raises(routing.RoutingError):
            routing._bounded_timeout(value)
    with pytest.raises(routing.RoutingError, match="timeout must be"):
        router.start("mechanical", "reject an invalid explicit override", cwd, timeout=-1)
    with pytest.raises(routing.RoutingError, match="unsupported routing purpose"):
        router.start("final-review-light", "task", cwd)


@pytest.mark.parametrize("override,configured,expected", [(None, 3600, 3600), (None, 7200, 7200), (None, 0, 0), (0, 3600, 0), (1200, 7200, 1200)])
def test_routed_total_limit_is_snapshotted_separately_from_native_limit(tmp_path, monkeypatch, override, configured, expected):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    original = service.routing_config

    def legacy_service_config(profile):
        config = original(profile)
        config.pop("light_timeout_seconds", None)
        config.pop("heavy_timeout_seconds", None)
        config.update(timeout_seconds=configured, delegate_timeout_seconds=30)
        return config

    # This fixture intentionally removes role fields to verify the old scalar DTO.
    service.routing_config = legacy_service_config
    result = router.start("plan", "bounded read-only fixture", tmp_path, timeout=override)
    directory = root / "profiles/claire/plugin-data/model-router/jobs" / result["job_id"]
    snapshot = _load(directory / "snapshot.json")
    assert snapshot["timeout_seconds"] == expected
    assert float(calls[0][0][calls[0][0].index("--timeout") + 1]) == expected
    assert snapshot["timeout_source"] == ("profile" if override is None else "call")


def test_start_failure_is_recorded_and_not_reported_as_running(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    root.mkdir()
    root.joinpath("profiles", "claire").mkdir(parents=True)
    service = FakeService(root)
    _fake_cli(tmp_path, monkeypatch)

    def failing_popen(*_args, **_kwargs):
        raise OSError("fake spawn failure")

    monkeypatch.setattr(routing.subprocess, "Popen", failing_popen)
    router = routing.Router(service)
    cwd = tmp_path / "work"
    cwd.mkdir()
    result = router.start("implementation", "task", cwd)
    assert result["status"] == "failed"
    assert result["error_type"] == "OSError"
    assert router.status(result["job_id"])["status"] == "failed"
    jobs = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs"
    job_dirs = list(jobs.iterdir())
    assert len(job_dirs) == 1
    assert _load(job_dirs[0] / "state.json")["status"] == "failed"


def _seed_result_job(
    root: Path,
    profile: str,
    *,
    result: dict[str, Any] | None,
    state=None,
    launch=None,
    fallback_enabled: bool = False,
):
    job_id = str(uuid.uuid4())
    job_dir = root / "profiles" / profile / "plugin-data" / "model-router" / "jobs" / job_id
    job_dir.mkdir(parents=True)
    snapshot = {
        "job_id": job_id,
        "profile": profile,
        "purpose": "plan",
        "settings_revision": 12,
        "route_class": "HEAVYWEIGHT",
        "verification_kind": "none",
        "model_provider_evidence": {
            "purpose_role": "HEAVYWEIGHT",
            "requested": {"HEAVYWEIGHT": HEAVY, "LIGHTWEIGHT": LIGHT},
            "fallback_enabled": fallback_enabled,
            "fallback": {
                "HEAVYWEIGHT": FALLBACK_HEAVY if fallback_enabled else None,
                "LIGHTWEIGHT": FALLBACK_LIGHT if fallback_enabled else None,
            },
            "actual": None,
        },
    }
    (job_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    if result is not None:
        (job_dir / "runner-result.json").write_text(json.dumps(result), encoding="utf-8")
    if state is not None:
        (job_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    if launch is not None:
        (job_dir / "launch.json").write_text(json.dumps(launch), encoding="utf-8")
    return job_id, job_dir


def _verified_runner_result(code=0, *, evidence_status="verified", actual_provider=None, actual_model=None):
    actual_provider = HEAVY["provider"] if actual_provider is None else actual_provider
    actual_model = HEAVY["model"] if actual_model is None else actual_model
    return {
        "exit_code": code,
        "process_exit_code": code,
        "effective_provider": HEAVY["provider"],
        "effective_model": HEAVY["model"],
        "actual_provider": actual_provider,
        "actual_model": actual_model,
        "route_verified": evidence_status == "verified" and code == 0,
        "verification_status": "not_requested",
        "config_unchanged": True,
        "session_evidence": {"status": evidence_status, "provider": actual_provider, "model": actual_model},
        "started_at": "2026-09-29T00:00:00Z",
        "finished_at": "2026-09-29T00:00:01Z",
    }


def test_status_uses_actual_provider_model_evidence_and_not_semantic_go(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(root, "claire", result=_verified_runner_result())
    result = router.status(job_id)
    assert result["status"] == "completed"
    assert result["route_verified"] is True
    assert result["effective_provider"] == HEAVY["provider"]
    assert result["actual_model"] == HEAVY["model"]
    assert "semantic_go" not in result
    assert result["model_provider_evidence"]["actual"]["evidence_status"] == "verified"


def test_status_marks_success_without_matching_session_evidence_unverified(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(root, "claire", result=_verified_runner_result(evidence_status="unverified"))
    result = router.status(job_id)
    assert result["status"] == "unverified"
    assert result["route_verified"] is False


def test_status_rejects_actual_provider_outside_the_snapshot(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(
        root,
        "claire",
        result=_verified_runner_result(actual_provider="unexpected-provider"),
    )
    result = router.status(job_id)
    assert result["status"] == "unverified"
    assert result["route_verified"] is False


def test_status_marks_nonzero_runner_failed(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(root, "claire", result=_verified_runner_result(code=2))
    assert router.status(job_id)["status"] == "failed"


def _scoped_timeout_result(*, cleanup_verified: bool, fallback_timeout: bool) -> dict[str, Any]:
    terminal_route = FALLBACK_HEAVY if fallback_timeout else HEAVY
    terminal_attempt = {
        "attempt_id": str(uuid.uuid4()),
        "requested_route": terminal_route,
        "completed": False,
        "error": {"kind": "timeout", "message": "scoped attempt exceeded its shared deadline"},
        "timed_out": True,
        "process_tree_closed": True if cleanup_verified else None,
        "cleanup_verified": cleanup_verified,
        "evidence_complete": False,
        "closure_complete": False,
        "exhaustion_confirmed": None,
    }
    attempts = []
    if fallback_timeout:
        attempts.append({
            "attempt_id": str(uuid.uuid4()),
            "requested_route": HEAVY,
            "completed": False,
            "error": {"kind": "subscription_exhaustion", "message": "structured exhaustion"},
            "timed_out": False,
            "process_tree_closed": None,
            "exhaustion_confirmed": True,
        })
    attempts.append(terminal_attempt)
    return {
        "execution_mode": "scoped_sdk",
        "exit_code": 124,
        "process_exit_code": 124,
        "effective_provider": terminal_route["provider"],
        "effective_model": terminal_route["model"],
        "actual_provider": None,
        "actual_model": None,
        "route_verified": False,
        "verification_status": "not_requested",
        "config_unchanged": True,
        "session_evidence": {"status": "unverified", "provider": None, "model": None},
        "completed": False,
        "closure_complete": False,
        "evidence_complete": False,
        "timed_out": True,
        "process_tree_closed": True if cleanup_verified else None,
        "cleanup_verified": cleanup_verified,
        "timeout_stage": "fallback" if fallback_timeout else "primary",
        "fallback_used": fallback_timeout,
        "fallback_reason": "exhaustion" if fallback_timeout else "not_exhaustion",
        "attempts": attempts,
    }


@pytest.mark.parametrize("cleanup_verified", [True, False])
def test_status_exposes_primary_timeout_cleanup_without_verifying_route(
    tmp_path, monkeypatch, cleanup_verified
):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(
        root,
        "claire",
        result=_scoped_timeout_result(cleanup_verified=cleanup_verified, fallback_timeout=False),
    )

    result = router.status(job_id)
    assert result["status"] == "failed"
    assert result["route_verified"] is False
    assert result["timed_out"] is True
    assert result["cleanup_verified"] is cleanup_verified
    assert result["process_tree_closed"] is (True if cleanup_verified else None)
    assert result["attempts"][0]["error"]["kind"] == "timeout"
    assert result["timeout_stage"] == "primary"
    assert result["attempts"][0]["process_tree_closed"] is (True if cleanup_verified else None)


@pytest.mark.parametrize("cleanup_verified", [True, False])
def test_status_preserves_primary_exhaustion_when_fallback_times_out(
    tmp_path, monkeypatch, cleanup_verified
):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(
        root,
        "claire",
        result=_scoped_timeout_result(cleanup_verified=cleanup_verified, fallback_timeout=True),
        fallback_enabled=True,
    )

    result = router.status(job_id)
    assert result["status"] == "failed"
    assert result["route_verified"] is False
    assert result["timed_out"] is True
    assert result["fallback_used"] is True
    assert result["timeout_stage"] == "fallback"
    assert result["fallback_reason"] == "exhaustion"
    assert result["cleanup_verified"] is cleanup_verified
    assert result["process_tree_closed"] is (True if cleanup_verified else None)
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["exhaustion_confirmed"] is True
    assert result["attempts"][0]["error"]["kind"] == "subscription_exhaustion"
    assert result["attempts"][1]["error"]["kind"] == "timeout"


def test_status_keeps_runner_crash_or_missing_artifact_unverified(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(
        root,
        "claire",
        result=None,
        state={
            "status": "failed",
            "error_type": "MissingRunnerArtifact",
            "timed_out": False,
            "cleanup_verified": None,
            "process_tree_closed": None,
        },
    )

    result = router.status(job_id)
    assert result["status"] == "failed"
    assert result["route_verified"] is False
    assert result["error_type"] == "MissingRunnerArtifact"
    assert result["timed_out"] is False
    assert result["cleanup_verified"] is None
    assert result["process_tree_closed"] is None


def test_status_reports_running_only_when_worker_pid_is_live(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(root, "claire", result=None, state={"status": "running"}, launch={"worker_pid": 777})
    monkeypatch.setattr(routing, "_pid_alive", lambda pid: pid == 777)
    assert router.status(job_id)["status"] == "running"
    monkeypatch.setattr(routing, "_pid_alive", lambda _pid: False)
    assert router.status(job_id)["status"] == "unverified"


def test_status_does_not_search_another_profile(tmp_path, monkeypatch):
    router, service, root, _ = _make_router(tmp_path, monkeypatch)
    job_id, _ = _seed_result_job(root, "claire", result=_verified_runner_result())
    service.profile = "other-profile"
    result = router.status(job_id)
    assert result["status"] == "unverified"
    assert result["profile"] == "other-profile"
    assert "actual_model" not in result


def test_status_rejects_noncanonical_job_identifiers(tmp_path, monkeypatch):
    router, *_ = _make_router(tmp_path, monkeypatch)
    with pytest.raises(routing.RoutingError, match="canonical UUID"):
        router.status(str(uuid.uuid4()).upper())
    with pytest.raises(routing.RoutingError, match="UUID"):
        router.status("../../outside")


def test_symlinked_profile_jobs_root_is_rejected(tmp_path, monkeypatch):
    router, _service, root, _ = _make_router(tmp_path, monkeypatch)
    home = root / "profiles" / "claire"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (home / "plugin-data").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable on this Windows host: {exc}")
    with pytest.raises(routing.RoutingError, match="symlinks|outside"):
        _start(router, tmp_path)


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize("total_seconds", [0, 3600, 7200, 1000001, 3600.123, 1e100])
def test_timeout_roundtrips_router_worker_runner_without_precision_loss(tmp_path, monkeypatch, total_seconds, configured):
    from lib import run_routed_agent as runner
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    native_config = service.routing_config
    service.routing_config = lambda profile: {
        **native_config(profile),
        "light_timeout_seconds": total_seconds if configured else 7777,
        "heavy_timeout_seconds": 8888,
        "timeout_seconds": 3333,
    }
    cwd = tmp_path / "work"
    cwd.mkdir()
    kwargs = {} if configured else {"timeout": total_seconds}
    result = router.start("implementation", "offline precision fixture", cwd, **kwargs)
    assert result["status"] == "running"
    worker_args = job_worker._parser().parse_args(calls[0][0][2:])
    assert worker_args.timeout == total_seconds
    snapshot = _load(worker_args.job_dir / "snapshot.json")
    assert snapshot["timeout_seconds"] == worker_args.timeout
    assert calls[0][0][calls[0][0].index("--timeout") + 1] == repr(float(total_seconds))
    assert snapshot["timeout_source"] == ("profile" if configured else "call")
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles/claire"))
    class Process:
        pid = 12345
        returncode = 0
        def wait(self, timeout=None):
            assert (timeout is None) == (total_seconds == 0)
            return 0
        def poll(self): return 0
    def fake_runner(command, **kwargs):
        parsed = runner._build_parser().parse_args(command[2:])
        assert parsed.timeout == total_seconds
        Path(parsed.output).write_text(json.dumps(_verified_runner_result()), encoding="utf-8")
        return Process()
    monkeypatch.setattr(job_worker.subprocess, "Popen", fake_runner)
    assert job_worker.run_job(**vars(worker_args)) == 0


@pytest.mark.parametrize("total_seconds", [600, 0, 7200, 1e100])
def test_worker_invokes_only_fake_runner_subprocess_and_writes_terminal_state(tmp_path, monkeypatch, total_seconds):
    root = tmp_path / "profile"
    job_id = str(uuid.uuid4())
    job_dir = root / "plugin-data" / "model-router" / "jobs" / job_id
    job_dir.mkdir(parents=True)
    cwd = tmp_path / "work"
    cwd.mkdir()
    cli = tmp_path / "hermes.exe"
    cli.write_bytes(b"fake executable marker")
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setattr(job_worker.shutil, "which", lambda name: str(cli) if name == "hermes" else None)
    snapshot = {
        "job_id": job_id,
        "profile": "default",
        "purpose": "independent-review",
        "cwd": str(cwd.resolve()),
        "model_provider_evidence": {"fallback_enabled": False},
    }
    (job_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (job_dir / "prompt.txt").write_text("review prompt", encoding="utf-8")
    (job_dir / "routing-cache.json").write_text("{}", encoding="utf-8")
    (job_dir / "job.log").write_bytes(b"")
    calls = []

    class FakeRunnerProcess:
        pid = 12345
        returncode = None

        def wait(self, timeout=None):
            if total_seconds > 0:
                assert 0 < timeout <= min(total_seconds + 5, 86400)
            else:
                assert timeout is None
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    def fake_popen(command, **kwargs):
        calls.append((list(command), kwargs))
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(json.dumps(_verified_runner_result()), encoding="utf-8")
        return FakeRunnerProcess()

    monkeypatch.setattr(job_worker.subprocess, "Popen", fake_popen)
    code = job_worker.run_job(
        job_dir=job_dir,
        runner=routing.RUNNER_PATH,
        python=sys.executable,
        hermes_exe=cli,
        profile="default",
        purpose="independent-review",
        cwd=cwd,
        timeout=total_seconds,
    )
    assert code == 0
    command, kwargs = calls[0]
    assert command[command.index("--route-class") + 1] == "HEAVYWEIGHT"
    assert command[command.index("--verification-kind") + 1] == "independent-review"
    assert "--no-fallback" in command
    assert "--scoped-attempts" in command
    assert command[command.index("--job-dir") + 1] == str(job_dir)
    assert "chat" not in command
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    if os.name == "nt":
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
        assert not kwargs["creationflags"] & subprocess.DETACHED_PROCESS
    state = _load(job_dir / "state.json")
    assert state["status"] == "finished"
    assert state["runner_exit_code"] == 0


def test_worker_records_runner_crash_without_fabricating_result(tmp_path, monkeypatch):
    root = tmp_path / "profile"
    job_id = str(uuid.uuid4())
    job_dir = root / "plugin-data" / "model-router" / "jobs" / job_id
    job_dir.mkdir(parents=True)
    cwd = tmp_path / "work"
    cwd.mkdir()
    cli = tmp_path / "hermes.exe"
    cli.write_bytes(b"fake executable marker")
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setattr(job_worker.shutil, "which", lambda name: str(cli) if name == "hermes" else None)
    snapshot = {
        "job_id": job_id,
        "profile": "default",
        "purpose": "implementation",
        "cwd": str(cwd.resolve()),
        "model_provider_evidence": {"fallback_enabled": False},
    }
    (job_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (job_dir / "prompt.txt").write_text("task", encoding="utf-8")
    (job_dir / "routing-cache.json").write_text("{}", encoding="utf-8")
    (job_dir / "job.log").write_bytes(b"")

    def crash(*_args, **_kwargs):
        raise OSError("fake runner crash")

    monkeypatch.setattr(job_worker.subprocess, "Popen", crash)
    code = job_worker.run_job(
        job_dir=job_dir,
        runner=routing.RUNNER_PATH,
        python=sys.executable,
        hermes_exe=cli,
        profile="default",
        purpose="implementation",
        cwd=cwd,
        timeout=600,
    )
    assert code == 1
    assert not (job_dir / "runner-result.json").exists()
    assert _load(job_dir / "state.json")["status"] == "failed"
    assert _load(job_dir / "state.json")["error_type"] == "OSError"


def _fast_snapshot(profile: str = "claire", parent: str = "parent-session") -> dict[str, Any]:
    return {
        "schema": 1,
        "profile": profile,
        "origin_session_id": parent,
        "parent_session_id": parent,
        "mode": "priority",
        "expires_at": None,
    }


def test_worker_rejects_forged_fast_snapshot_before_runner_process(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    home = root / "profiles" / "claire"
    job_id = str(uuid.uuid4())
    job_dir = home / "plugin-data" / "model-router" / "jobs" / job_id
    cwd = tmp_path / "work"
    job_dir.mkdir(parents=True)
    cwd.mkdir()
    cli = tmp_path / "hermes.exe"
    cli.write_bytes(b"fake executable marker")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(job_worker.shutil, "which", lambda name: str(cli) if name == "hermes" else None)
    snapshot = {
        "schema": 1,
        "job_id": job_id,
        "profile": "claire",
        "purpose": "implementation",
        "cwd": str(cwd.resolve()),
        "parent_session_id": "parent-A",
        "fast_snapshot": _fast_snapshot(parent="parent-B"),
    }
    (job_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    spawned: list[bool] = []
    monkeypatch.setattr(job_worker.subprocess, "Popen", lambda *_a, **_k: spawned.append(True))

    with pytest.raises(ValueError, match="Fast job snapshot is invalid"):
        job_worker.run_job(
            job_dir=job_dir,
            runner=routing.RUNNER_PATH,
            python=sys.executable,
            hermes_exe=cli,
            profile="claire",
            purpose="implementation",
            cwd=cwd,
            timeout=60,
        )
    assert spawned == []
    assert not (job_dir / "state.json").exists()


def test_router_rejects_fast_snapshot_without_actual_runtime(tmp_path):
    service = FakeService(tmp_path / "hermes")
    with pytest.raises(routing.RoutingError, match="active host runtime"):
        routing.Router(service, fast_snapshot=_fast_snapshot())


def test_router_persists_only_validated_parent_fast_snapshot(tmp_path, monkeypatch):
    _router, service, root, _popen_calls = _make_router(tmp_path, monkeypatch)
    runtime = type("Runtime", (), {"parent_session_id": "parent-session", "ui_session_id": "ui-session"})()
    router = routing.Router(service, runtime=runtime, fast_snapshot=_fast_snapshot())
    result = _start(router, tmp_path)
    job_dir = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs" / result["job_id"]
    snapshot = _load(job_dir / "snapshot.json")
    assert snapshot["schema"] == 1
    assert snapshot["fast_snapshot"] == _fast_snapshot()
    assert "fast_snapshot" not in result


@pytest.mark.parametrize(
    "profile,parent",
    [("other", "parent-session"), ("claire", "different-parent")],
)
def test_router_rejects_forged_fast_profile_or_parent(tmp_path, profile, parent):
    service = FakeService(tmp_path / "hermes")
    runtime = type("Runtime", (), {"parent_session_id": "parent-session"})()
    with pytest.raises(routing.RoutingError, match="active profile and parent"):
        routing.Router(service, runtime=runtime, fast_snapshot=_fast_snapshot(profile, parent))
