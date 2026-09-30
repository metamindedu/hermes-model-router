from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import types
import uuid
from pathlib import Path
from typing import Any, Callable

import pytest

from model_router import attempt_observer, scoped_agent


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


@pytest.fixture
def attempt() -> Any:
    # Keep the long <home>/plugin-data/.../attempts/<uuid> path under a short root.
    base = Path(tempfile.mkdtemp(prefix="r", dir=tempfile.gettempdir()))
    home = base / "h"
    cwd = base / "w"
    home.mkdir()
    cwd.mkdir()
    job_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    attempt_dir = home / "plugin-data" / "model-router" / "jobs" / job_id / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True)
    request = {
        "schema": 1,
        "attempt_id": attempt_id,
        "job_id": job_id,
        "profile": "claire",
        "home": str(home.resolve()),
        "cwd": str(cwd.resolve()),
        "source": "subagent",
        "task_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "parent_session_id": None,
        "route": {"provider": "requested-provider", "model": "requested/model", "reasoning": "medium"},
        "toolsets": ["filesystem"],
        "prompt": "PROMPT_PRIVATE_CANARY",
        "budget_seconds": 45,
    }
    request_path = attempt_dir / "attempt-request.json"
    result_path = attempt_dir / "attempt-result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    fixture_data = {
        "base": base,
        "home": home,
        "cwd": cwd,
        "attempt_dir": attempt_dir,
        "request": request,
        "request_path": request_path,
        "result_path": result_path,
    }
    attempt_observer.reset_for_tests()
    try:
        yield fixture_data
    finally:
        attempt_observer.reset_for_tests()
        shutil.rmtree(base, ignore_errors=True)


def _emit_api_events(
    attempt: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    between_events: Callable[[], None] | None = None,
) -> None:
    request = attempt["request"]
    actual_provider = provider or request["route"]["provider"]
    actual_model = model or request["route"]["model"]
    identity = {
        "api_request_id": "fake-api-request-1",
        "session_id": session_id or request["session_id"],
        "task_id": task_id or request["task_id"],
        "provider": actual_provider,
        "model": actual_model,
        "api_mode": "chat_completions",
    }
    attempt_observer.record_event(
        "pre_api_request",
        **identity,
        request={
            "body": {
                "model": actual_model,
                "prompt": "HOOK_PROMPT_CANARY",
                "headers": {"Authorization": "HOOK_KEY_CANARY"},
            }
        },
        prompt="HOOK_PROMPT_CANARY",
        tool_arguments="HOOK_TOOL_ARGUMENT_CANARY",
        config={"secret": "HOOK_CONFIG_CANARY"},
        endpoint="https://HOOK_ENDPOINT_CANARY.invalid",
        base_url="https://HOOK_BASE_URL_CANARY.invalid",
        ignored_unknown_field=object(),
    )
    if between_events is not None:
        between_events()
    attempt_observer.record_event(
        "post_api_request",
        **identity,
        response_model=actual_model,
        response={"model": actual_model, "body": "HOOK_RESPONSE_CANARY"},
        assistant_tool_call_count=0,
        prompt="HOOK_PROMPT_CANARY",
        tool_arguments="HOOK_TOOL_ARGUMENT_CANARY",
        ignored_unknown_field=object(),
    )


def _fake_dependencies(
    attempt: dict[str, Any],
    *,
    on_run: Callable[[Any, str, str], dict[str, Any]] | None = None,
    observed_provider: str | None = None,
    observed_model: str | None = None,
    close_error: Exception | None = None,
    release_error: Exception | None = None,
    redact: Callable[[str], str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stats: dict[str, Any] = {
        "constructor_kwargs": [],
        "close_calls": 0,
        "acquire_calls": 0,
        "release_calls": 0,
        "db": object(),
    }

    class FakeAgent:
        def __init__(self, **kwargs: Any):
            stats["constructor_kwargs"].append(kwargs)
            self.kwargs = kwargs

        def run_conversation(self, prompt: str, *, task_id: str) -> dict[str, Any]:
            if on_run is not None:
                return on_run(self, prompt, task_id)
            _emit_api_events(
                attempt,
                provider=observed_provider,
                model=observed_model,
            )
            return {"completed": True, "failed": False, "partial": False, "final_response": "safe answer"}

        def close(self) -> None:
            stats["close_calls"] += 1
            if close_error is not None:
                raise close_error

    def resolve_runtime_provider(*, requested: str, target_model: str) -> dict[str, Any]:
        assert requested == attempt["request"]["route"]["provider"]
        assert target_model == attempt["request"]["route"]["model"]
        return {
            "provider": requested,
            "requested_provider": requested,
            "api_mode": "chat_completions",
            "api_key": "RUNTIME_API_KEY_CANARY",
            "base_url": "https://RUNTIME_BASE_URL_CANARY.invalid",
            "credential_pool": None,
            "request_overrides": {"profile_config_secret": "RUNTIME_CONFIG_CANARY"},
        }

    def acquire_session_db() -> object:
        stats["acquire_calls"] += 1
        return stats["db"]

    def release_session_db(db: object) -> None:
        assert db is stats["db"]
        stats["release_calls"] += 1
        if release_error is not None:
            raise release_error

    def prepare_runtime(_request: dict[str, Any]) -> dict[str, Any]:
        return {
            "AIAgent": FakeAgent,
            "resolve_runtime_provider": resolve_runtime_provider,
            "acquire_session_db": acquire_session_db,
            "release_session_db": release_session_db,
            "agent_options": {
                "max_iterations": 7,
                "fallback_model": ["PROFILE_LEGACY_FALLBACK_CANARY"],
            },
            "config": {
                "agent": {
                    "fallback_providers": ["PROFILE_NATIVE_FALLBACK_CANARY"],
                    "private_setting": "PROFILE_CONFIG_CANARY",
                }
            },
            "observer": attempt_observer,
        }

    dependencies = {
        "prepare_runtime": prepare_runtime,
        "observer": attempt_observer,
        "redact": redact or (lambda text: text),
    }
    return dependencies, stats


def _run_through_main(
    attempt: dict[str, Any],
    dependencies: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    real_run_attempt = scoped_agent.run_attempt
    monkeypatch.setattr(
        scoped_agent,
        "run_attempt",
        lambda request: real_run_attempt(request, dependencies=dependencies),
    )
    return scoped_agent.main(
        ["--request", str(attempt["request_path"]), "--result", str(attempt["result_path"])]
    )


def test_request_and_result_artifacts_are_bound_to_the_attempt_directory(attempt):
    normalized, request_path, result_path = scoped_agent._validate_request(
        attempt["request"], attempt["request_path"]
    )

    assert normalized["home"] == str(attempt["home"].resolve())
    assert request_path == attempt["attempt_dir"] / "attempt-request.json"
    assert result_path == attempt["attempt_dir"] / "attempt-result.json"
    assert request_path.parent == result_path.parent == attempt["attempt_dir"]
    assert request_path.is_relative_to(attempt["home"] / "plugin-data" / "model-router" / "jobs")


def test_request_path_escape_and_foreign_job_are_rejected(attempt, tmp_path):
    assert attempt["home"].exists()
    assert attempt["cwd"].exists()
    assert Path(attempt["request"]["home"]).resolve(strict=True) == attempt["home"].resolve()
    assert Path(attempt["request"]["cwd"]).resolve(strict=True) == attempt["cwd"].resolve()
    copied_request = tmp_path / "attempt-request.json"
    copied_request.write_text(json.dumps(attempt["request"]), encoding="utf-8")
    with pytest.raises(scoped_agent.AttemptError, match="outside its attempt directory"):
        scoped_agent._validate_request(attempt["request"], copied_request)

    foreign_job_request = dict(attempt["request"], job_id=str(uuid.uuid4()))
    result = scoped_agent.run_attempt(foreign_job_request, dependencies={"redact": lambda text: text})
    assert result["completed"] is False
    assert result["error"]["kind"] == "initialization_error"
    assert result["observed_routes"] == []

    traversal_request = dict(attempt["request"], job_id="../outside")
    result = scoped_agent.run_attempt(traversal_request, dependencies={"redact": lambda text: text})
    assert result["completed"] is False
    assert result["error"]["kind"] == "initialization_error"


def test_native_parent_session_token_is_accepted_but_unsafe_parent_is_rejected(attempt):
    native_parent_id = "20260930_113515_240566"
    native_request = dict(attempt["request"], parent_session_id=native_parent_id)
    attempt["request_path"].write_text(json.dumps(native_request), encoding="utf-8")

    normalized, _request_path, _result_path = scoped_agent._validate_request(
        native_request, attempt["request_path"]
    )
    assert normalized["parent_session_id"] == native_parent_id

    for unsafe_parent_id in ("../outside", "parent\nsource", "x" * 129):
        unsafe_request = dict(native_request, parent_session_id=unsafe_parent_id)
        with pytest.raises(scoped_agent.AttemptError, match="parent_session_id"):
            scoped_agent._validate_request(unsafe_request, attempt["request_path"])


def test_child_agent_uses_subagent_identity_and_drops_desktop_chat_routing(attempt, monkeypatch):
    inherited_routing = {
        "HERMES_UI_SESSION_ID": "desktop-ui-session",
        "HERMES_SESSION_PLATFORM": "desktop",
        "HERMES_SESSION_CHAT_ID": "desktop-chat",
        "HERMES_SESSION_CHAT_TYPE": "group",
        "HERMES_SESSION_CHAT_NAME": "desktop-room",
        "HERMES_SESSION_THREAD_ID": "desktop-thread",
        "HERMES_SESSION_USER_ID": "desktop-user",
        "HERMES_SESSION_USER_NAME": "desktop-user-name",
        "HERMES_SESSION_SCOPE_ID": "desktop-scope",
        "HERMES_SESSION_KEY": "desktop-key",
        "HERMES_SESSION_MESSAGE_ID": "desktop-message",
        "HERMES_SESSION_PARENT_CHAT_ID": "desktop-parent-chat",
    }
    for key, value in inherited_routing.items():
        monkeypatch.setenv(key, value)
    observed_env: dict[str, str | None] = {}

    def on_run(agent: Any, _prompt: str, _task_id: str) -> dict[str, Any]:
        _emit_api_events(attempt)
        observed_env.update({key: os.environ.get(key) for key in inherited_routing})
        observed_env["HERMES_SESSION_SOURCE"] = os.environ.get("HERMES_SESSION_SOURCE")
        observed_env["HERMES_SESSION_SOURCE_EXPLICIT"] = os.environ.get("HERMES_SESSION_SOURCE_EXPLICIT")
        observed_env["HERMES_PLATFORM"] = os.environ.get("HERMES_PLATFORM")
        observed_env["HERMES_SESSION_ID"] = os.environ.get("HERMES_SESSION_ID")
        return {"completed": True, "failed": False, "partial": False, "final_response": "safe answer"}

    dependencies, stats = _fake_dependencies(attempt, on_run=on_run)
    result = scoped_agent.run_attempt(attempt["request"], dependencies=dependencies)

    assert result["completed"] is True
    kwargs = stats["constructor_kwargs"][0]
    assert kwargs["platform"] == "subagent"
    assert attempt["request"]["source"] == "subagent"
    assert observed_env["HERMES_SESSION_SOURCE"] == "subagent"
    assert observed_env["HERMES_SESSION_SOURCE_EXPLICIT"] == "1"
    assert observed_env["HERMES_PLATFORM"] == "subagent"
    assert observed_env["HERMES_SESSION_ID"] == attempt["request"]["session_id"]
    assert observed_env["HERMES_SESSION_PLATFORM"] == "subagent"
    assert all(observed_env[key] is None for key in inherited_routing if key != "HERMES_SESSION_PLATFORM")


def test_main_rejects_result_artifact_outside_the_attempt_directory(attempt, monkeypatch):
    outside_result = attempt["base"] / "escape" / "attempt-result.json"
    outside_result.parent.mkdir()
    monkeypatch.setattr(scoped_agent, "run_attempt", lambda _request: pytest.fail("must reject before running"))

    status = scoped_agent.main(
        ["--request", str(attempt["request_path"]), "--result", str(outside_result)]
    )

    assert status == 1
    assert not outside_result.exists()


def test_main_rejects_symlinked_request_and_result_artifacts(attempt, monkeypatch):
    outside_request = attempt["base"] / "outside-request.json"
    outside_request.write_text(json.dumps(attempt["request"]), encoding="utf-8")
    attempt["request_path"].unlink()
    try:
        attempt["request_path"].symlink_to(outside_request)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable in this test environment: {exc}")

    monkeypatch.setattr(scoped_agent, "run_attempt", lambda _request: pytest.fail("must reject symlink"))
    request_status = scoped_agent.main(
        ["--request", str(attempt["request_path"]), "--result", str(attempt["result_path"])]
    )
    assert request_status == 1
    assert not attempt["result_path"].exists()

    attempt["request_path"].unlink()
    attempt["request_path"].write_text(json.dumps(attempt["request"]), encoding="utf-8")
    outside_result = attempt["base"] / "outside-result.json"
    outside_result.write_text("{}", encoding="utf-8")
    try:
        attempt["result_path"].symlink_to(outside_result)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable in this test environment: {exc}")
    result_status = scoped_agent.main(
        ["--request", str(attempt["request_path"]), "--result", str(attempt["result_path"])]
    )
    assert result_status == 1
    assert outside_result.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize(
    "payload",
    [
        "{malformed json",
        json.dumps({"schema": 2, "not": "the frozen request schema"}),
    ],
    ids=["malformed-json", "unknown-schema"],
)
def test_main_rejects_malformed_or_unknown_schema_without_writing_result(attempt, monkeypatch, payload):
    attempt["request_path"].write_text(payload, encoding="utf-8")
    monkeypatch.setattr(scoped_agent, "run_attempt", lambda _request: pytest.fail("must reject invalid request"))

    status = scoped_agent.main(
        ["--request", str(attempt["request_path"]), "--result", str(attempt["result_path"])]
    )

    assert status == 1
    assert not attempt["result_path"].exists()


def test_profile_home_mismatch_fails_closed_before_loading_profile_config(attempt, monkeypatch):
    other_home = attempt["base"] / "other-profile-home"
    other_home.mkdir()
    fake_core = attempt["base"] / "fake-hermes-core"
    fake_core.mkdir()
    bootstrap_path = fake_core / "hermes_bootstrap.py"
    bootstrap_path.write_text("# fake import origin\n", encoding="utf-8")
    bootstrap = types.SimpleNamespace(
        __file__=str(bootstrap_path),
        harden_import_path=lambda _root: None,
    )
    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "hermes_bootstrap":
            return bootstrap
        return real_import_module(name, package)

    fake_cli = types.ModuleType("hermes_cli")
    fake_cli.__path__ = []  # type: ignore[attr-defined]
    profiles = types.ModuleType("hermes_cli.profiles")
    profiles.profile_exists = lambda _profile: True  # type: ignore[attr-defined]
    profiles.get_profile_dir = lambda _profile: str(other_home)  # type: ignore[attr-defined]
    fake_cli.profiles = profiles  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.profiles", profiles)
    monkeypatch.setattr(scoped_agent, "_trusted_core_root", lambda: fake_core)
    monkeypatch.setattr(scoped_agent.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(scoped_agent.sys, "path", list(sys.path))

    with pytest.raises(scoped_agent.AttemptError, match="profile and Hermes home do not match"):
        scoped_agent._default_prepare_runtime(attempt["request"])


@pytest.mark.parametrize(
    "case",
    ["missing", "unreadable", "malformed", "non-mapping", "last-known-good", "failed-config-read"],
)
def test_invalid_or_recovered_profile_config_stops_before_tools_or_provider(attempt, monkeypatch, case):
    # Offline fixture: importing the genuine bootstrap must not launch the PM
    # updater or re-exec pytest after run_attempt changes to its fake workspace.
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    core_root = Path("C:/Users/ovpow/AppData/Local/hermes/hermes-agent").resolve(strict=True)
    if str(core_root) not in sys.path:
        sys.path.insert(0, str(core_root))
    from hermes_cli import config as core_config
    from hermes_cli.config_read_errors import FailedConfigRead
    from hermes_cli import plugins
    from hermes_cli import runtime_provider
    from tools import tirith_security

    home = attempt["home"]
    from hermes_cli import profiles
    monkeypatch.setattr(profiles, "_get_default_hermes_home", lambda: home)
    config_path = home / "config.yaml"
    if case == "missing":
        pass
    elif case == "unreadable":
        config_path.write_text("security: {}\n", encoding="utf-8")
        original_read_bytes = Path.read_bytes

        def denied_read(path: Path) -> bytes:
            if path == config_path:
                raise PermissionError("fake unreadable config")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", denied_read)
    elif case == "malformed":
        config_path.write_text("security: [\n", encoding="utf-8")
    elif case == "non-mapping":
        config_path.write_text("- not-a-config-mapping\n", encoding="utf-8")
    else:
        config_path.write_text("agent:\n  max_turns: 7\n", encoding="utf-8")
        if case == "last-known-good":
            monkeypatch.setattr(core_config, "load_config_readonly", lambda: {})
        else:
            monkeypatch.setattr(
                core_config,
                "load_config_readonly",
                lambda: FailedConfigRead(error=OSError("fake read failure")),
            )

    request = dict(attempt["request"], profile="default")
    attempt["request_path"].write_text(json.dumps(request), encoding="utf-8")
    counters = {"tools": 0, "plugins": 0, "provider": 0}

    def ensure_tools(**_kwargs: Any) -> None:
        counters["tools"] += 1

    def discover(**_kwargs: Any) -> None:
        counters["plugins"] += 1

    def resolve(**_kwargs: Any) -> dict[str, Any]:
        counters["provider"] += 1
        return {}

    monkeypatch.setattr(tirith_security, "ensure_installed", ensure_tools)
    monkeypatch.setattr(plugins, "discover_plugins", discover)
    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", resolve)

    result = scoped_agent.run_attempt(request)

    assert result["completed"] is False
    assert result["error"]["kind"] == "initialization_error"
    assert counters == {"tools": 0, "plugins": 0, "provider": 0}


def test_empty_fallback_chain_is_explicit_and_result_artifact_is_allowlisted(attempt, monkeypatch):
    tool_argument = "TOOL_ARGUMENT_PRIVATE_CANARY"
    config_value = "PROFILE_CONFIG_PRIVATE_CANARY"
    api_key = "API_KEY_PRIVATE_CANARY"
    endpoint = "https://PRIVATE_ENDPOINT.invalid"
    base_url = "https://PRIVATE_BASE_URL.invalid"

    def redact(text: str) -> str:
        for secret in (
            attempt["request"]["prompt"],
            tool_argument,
            config_value,
            api_key,
            endpoint,
            base_url,
            "RUNTIME_API_KEY_CANARY",
            "RUNTIME_BASE_URL_CANARY",
            "RUNTIME_CONFIG_CANARY",
            "PROFILE_LEGACY_FALLBACK_CANARY",
            "PROFILE_NATIVE_FALLBACK_CANARY",
        ):
            text = text.replace(secret, "[redacted]")
        return text

    def on_run(agent: Any, _prompt: str, _task_id: str) -> dict[str, Any]:
        _emit_api_events(
            attempt,
            provider="requested-provider",
            model="requested/model",
            between_events=lambda: agent.kwargs["tool_start_callback"](
                "shell", {"command": tool_argument}
            ),
        )
        agent.kwargs["stream_delta_callback"](tool_argument)
        return {
            "completed": True,
            "failed": False,
            "partial": False,
            "final_response": "safe answer",
            "messages": [{"tool_calls": [{"arguments": tool_argument}]}],
            "private_config": config_value,
            "api_key": api_key,
            "endpoint": endpoint,
            "base_url": base_url,
        }

    dependencies, stats = _fake_dependencies(attempt, on_run=on_run, redact=redact)
    status = _run_through_main(attempt, dependencies, monkeypatch)
    artifact_text = attempt["result_path"].read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)

    assert status == 0
    assert set(artifact) == _RESULT_FIELDS
    assert artifact["completed"] is True
    assert artifact["error"] is None
    assert artifact["tool_seen"] is True
    assert artifact["partial_output"] is True
    assert artifact["evidence_complete"] is True
    assert artifact["closure_complete"] is True
    assert artifact["exhaustion_confirmed"] is False
    assert artifact["exit_code"] == 0
    assert artifact["observed_routes"] == [
        {
            "provider": "requested-provider",
            "model": "requested/model",
            "api_mode": "chat_completions",
            "request_model": "requested/model",
            "response_model": "requested/model",
        }
    ]
    assert len(stats["constructor_kwargs"]) == 1
    constructor_kwargs = stats["constructor_kwargs"][0]
    assert "fallback_model" in constructor_kwargs
    assert constructor_kwargs["fallback_model"] == []
    assert "fallback_providers" not in constructor_kwargs
    assert "config" not in constructor_kwargs
    assert stats["close_calls"] == stats["release_calls"] == 1
    assert set(path.name for path in attempt["attempt_dir"].iterdir()) == {
        "attempt-request.json",
        "attempt-result.json",
    }
    for private_value in (
        attempt["request"]["prompt"],
        tool_argument,
        config_value,
        api_key,
        endpoint,
        base_url,
        "HOOK_PROMPT_CANARY",
        "HOOK_KEY_CANARY",
        "HOOK_TOOL_ARGUMENT_CANARY",
        "HOOK_CONFIG_CANARY",
        "HOOK_ENDPOINT_CANARY",
        "HOOK_BASE_URL_CANARY",
        "HOOK_RESPONSE_CANARY",
        "RUNTIME_API_KEY_CANARY",
        "RUNTIME_BASE_URL_CANARY",
        "RUNTIME_CONFIG_CANARY",
        "PROFILE_LEGACY_FALLBACK_CANARY",
        "PROFILE_NATIVE_FALLBACK_CANARY",
    ):
        assert private_value not in artifact_text


def test_error_message_is_redacted_and_bounded_in_the_written_result(attempt, monkeypatch):
    private_values = (
        attempt["request"]["prompt"],
        "ERROR_API_KEY_CANARY",
        "ERROR_ENDPOINT_CANARY",
        "ERROR_TOOL_ARGUMENT_CANARY",
        "ERROR_CONFIG_CANARY",
    )

    def redact(text: str) -> str:
        for secret in private_values:
            text = text.replace(secret, "[redacted]")
        return text

    def on_run(_agent: Any, _prompt: str, _task_id: str) -> dict[str, Any]:
        _emit_api_events(attempt)
        raise RuntimeError("failure " + " ".join(private_values) + "x" * 1200)

    dependencies, _stats = _fake_dependencies(attempt, on_run=on_run, redact=redact)
    status = _run_through_main(attempt, dependencies, monkeypatch)
    artifact_text = attempt["result_path"].read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)

    assert status == 1
    assert set(artifact) == _RESULT_FIELDS
    assert artifact["completed"] is False
    assert set(artifact["error"]) == {"kind", "message"}
    assert artifact["error"]["kind"] == "provider_error"
    assert "[redacted]" in artifact["error"]["message"]
    assert len(artifact["error"]["message"]) <= scoped_agent.MAX_ERROR_CHARS
    for private_value in private_values:
        assert private_value not in artifact_text


def test_observed_route_comes_from_api_hooks_and_mismatch_is_unverified(attempt):
    dependencies, _stats = _fake_dependencies(
        attempt,
        observed_provider="actual-hook-provider",
        observed_model="actual/hook-model",
    )

    result = scoped_agent.run_attempt(attempt["request"], dependencies=dependencies)

    assert result["requested_route"] == attempt["request"]["route"]
    assert result["observed_routes"] == [
        {
            "provider": "actual-hook-provider",
            "model": "actual/hook-model",
            "api_mode": "chat_completions",
            "request_model": "actual/hook-model",
            "response_model": "actual/hook-model",
        }
    ]
    assert result["completed"] is False
    assert result["error"]["kind"] == "route_mismatch"
    # The observer did capture a route, but it is not the requested one, so the
    # attempt's evidence is not usable identity evidence: it stays incomplete and
    # the attempt can never be promoted to verified or trigger an outer retry.
    assert result["evidence_complete"] is False
    assert result["exhaustion_confirmed"] is False


def test_runtime_requested_flags_without_api_hook_events_are_not_route_evidence(attempt):
    def no_hooks(_agent: Any, _prompt: str, _task_id: str) -> dict[str, Any]:
        return {"completed": True, "failed": False, "partial": False, "final_response": "answer"}

    dependencies, _stats = _fake_dependencies(attempt, on_run=no_hooks)
    result = scoped_agent.run_attempt(attempt["request"], dependencies=dependencies)

    assert result["observed_routes"] == []
    assert result["evidence_complete"] is False
    assert result["completed"] is False
    assert result["error"]["kind"] == "evidence_missing"


def test_answer_text_containing_usage_limit_does_not_confirm_exhaustion(attempt):
    def quota_wording(agent: Any, _prompt: str, _task_id: str) -> dict[str, Any]:
        _emit_api_events(attempt)
        agent.kwargs["stream_delta_callback"]("Your subscription usage limit has been reached")
        return {
            "completed": True,
            "failed": False,
            "partial": False,
            "final_response": "Your subscription usage limit has been reached",
        }

    dependencies, _stats = _fake_dependencies(attempt, on_run=quota_wording)
    result = scoped_agent.run_attempt(attempt["request"], dependencies=dependencies)

    assert result["completed"] is True
    assert result["final_response"] == "Your subscription usage limit has been reached"
    assert result["exhaustion_confirmed"] is False
    assert result["error"] is None


@pytest.mark.parametrize("outcome", ["failed-result", "raised-exception"])
def test_agent_and_session_db_are_closed_once_after_failure_or_exception(attempt, outcome):
    def on_run(_agent: Any, _prompt: str, _task_id: str) -> dict[str, Any]:
        _emit_api_events(attempt)
        if outcome == "raised-exception":
            raise RuntimeError("fake provider exception")
        return {"completed": False, "failed": True, "partial": False, "final_response": ""}

    dependencies, stats = _fake_dependencies(attempt, on_run=on_run)
    result = scoped_agent.run_attempt(attempt["request"], dependencies=dependencies)

    assert result["completed"] is False
    assert stats["acquire_calls"] == 1
    assert stats["close_calls"] == 1
    assert stats["release_calls"] == 1
    assert result["closure_complete"] is True


@pytest.mark.parametrize("closure_failure", ["agent-close", "db-release"])
def test_closure_failure_is_reported_and_never_claimed_as_success(attempt, closure_failure):
    close_error = RuntimeError("fake close failure") if closure_failure == "agent-close" else None
    release_error = RuntimeError("fake release failure") if closure_failure == "db-release" else None
    dependencies, stats = _fake_dependencies(
        attempt,
        close_error=close_error,
        release_error=release_error,
    )

    result = scoped_agent.run_attempt(attempt["request"], dependencies=dependencies)

    assert result["completed"] is False
    assert result["closure_complete"] is False
    assert result["error"]["kind"] == "initialization_error"
    assert "closure was incomplete" in result["error"]["message"]
    assert result["exhaustion_confirmed"] is False
    assert stats["close_calls"] == 1
    assert stats["release_calls"] == 1


def test_observer_is_inert_without_environment_binding_and_ignores_unknown_fields(monkeypatch):
    attempt_observer.reset_for_tests()
    monkeypatch.delenv("MODEL_ROUTER_ATTEMPT_REQUEST", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)

    attempt_observer.record_event("pre_api_request", prompt="PRIVATE", new_field=object())
    attempt_observer.record_event("future_unknown_event", nested=object())

    assert attempt_observer.snapshot() == {
        "tool_seen": False,
        "partial_output": False,
        "evidence_complete": False,
        "observed_routes": [],
        "exhaustion_confirmed": False,
    }


@pytest.mark.parametrize("mismatch", ["home", "profile", "job"])
def test_observer_is_inert_for_wrong_home_profile_or_job(attempt, monkeypatch, mismatch):
    attempt_observer.reset_for_tests()
    monkeypatch.setenv("MODEL_ROUTER_ATTEMPT_REQUEST", str(attempt["request_path"]))
    monkeypatch.setenv("HERMES_HOME", str(attempt["home"]))
    monkeypatch.setenv("HERMES_PROFILE", attempt["request"]["profile"])
    if mismatch == "home":
        other_home = attempt["base"] / "other-home"
        other_home.mkdir()
        monkeypatch.setenv("HERMES_HOME", str(other_home))
    elif mismatch == "profile":
        monkeypatch.setenv("HERMES_PROFILE", "different-profile")
    else:
        wrong_job_request = dict(attempt["request"], job_id=str(uuid.uuid4()))
        attempt["request_path"].write_text(json.dumps(wrong_job_request), encoding="utf-8")

    _emit_api_events(attempt)

    assert attempt_observer.snapshot()["evidence_complete"] is False
    assert attempt_observer.snapshot()["observed_routes"] == []


def test_observer_rejects_events_from_a_foreign_attempt_and_binds_events_to_its_directory(attempt, monkeypatch):
    attempt_observer.reset_for_tests()
    monkeypatch.setenv("MODEL_ROUTER_ATTEMPT_REQUEST", str(attempt["request_path"]))
    monkeypatch.setenv("HERMES_HOME", str(attempt["home"]))
    monkeypatch.setenv("HERMES_PROFILE", attempt["request"]["profile"])

    _emit_api_events(
        attempt,
        session_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
    )
    rejected = attempt_observer.snapshot()
    assert rejected["observed_routes"] == []
    assert rejected["evidence_complete"] is False

    _emit_api_events(attempt)
    accepted = attempt_observer.snapshot()
    assert accepted["evidence_complete"] is True
    assert len(accepted["observed_routes"]) == 1
    assert attempt_observer._state is not None
    assert attempt_observer._state.request_path == attempt["request_path"]
    assert attempt_observer._state.request_path.parent == attempt["attempt_dir"]
    serialized_evidence = json.dumps(accepted)
    for private_value in (
        "HOOK_PROMPT_CANARY",
        "HOOK_KEY_CANARY",
        "HOOK_TOOL_ARGUMENT_CANARY",
        "HOOK_CONFIG_CANARY",
        "HOOK_ENDPOINT_CANARY",
        "HOOK_BASE_URL_CANARY",
        "HOOK_RESPONSE_CANARY",
    ):
        assert private_value not in serialized_evidence
