from __future__ import annotations

import argparse
import importlib
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lib import run_routed_agent as runner
from model_router import scoped_agent
from test_routing import _make_router

CORE = Path("C:/Users/ovpow/AppData/Local/hermes/hermes-agent")
REPO = Path(__file__).resolve().parents[1]


def _route_result(request: dict[str, Any]) -> dict[str, Any]:
    route = request["route"]
    model = route["model"]
    return {
        "schema": 1,
        "attempt_id": request["attempt_id"],
        "job_id": request["job_id"],
        "session_id": request["session_id"],
        "task_id": request["task_id"],
        "requested_route": dict(route),
        "completed": True,
        "error": None,
        "final_response": "routed pipeline fixture result",
        "tool_seen": False,
        "partial_output": False,
        "evidence_complete": True,
        "closure_complete": True,
        "observed_routes": [{
            "provider": route["provider"],
            "model": model,
            "api_mode": "chat_completions",
            "request_model": model,
            "response_model": model,
        }],
        "exhaustion_confirmed": False,
        "exit_code": 0,
    }


@pytest.fixture
def loaded_fast_controller(tmp_path, monkeypatch):
    """Load the real plugin namespace and bind only fake-home controller state."""
    base = Path(tempfile.mkdtemp(prefix="mfb", dir=tempfile.gettempdir()))
    _unused_router, service, root, spawn_calls = _make_router(base, monkeypatch)
    home = root / "profiles" / "claire"
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    monkeypatch.syspath_prepend(str(CORE))
    from hermes_cli import plugins, profiles
    from hermes_cli.plugins_manifest import parse_manifest_file
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    base = root
    home = root / "profiles" / "claire"
    # Model the real named-profile layout instead of faking controller registration
    # or forcing its private profile/home gates to succeed.
    monkeypatch.setattr(profiles, '_get_default_hermes_home', lambda: root)
    token = set_hermes_home_override(home)
    (home / "config.yaml").write_text(
        "plugins:\n  enabled: [model-router]\n", encoding="utf-8"
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "claire")
    manager = plugins.PluginManager(scope_key=str(home))
    manifest = parse_manifest_file(REPO / "plugin.yaml", REPO, "user", "")
    assert manifest is not None
    manager._load_plugin(manifest)
    entry = manager._plugins["model-router"]
    assert entry.enabled, entry.error
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: manager)

    observer = scoped_agent._resolve_registered_observer(home, REPO)
    package_name = observer.__name__.removesuffix(".model_router.attempt_observer")
    fast_module = importlib.import_module(package_name + ".model_router.fast_inheritance")
    controller = fast_module._registered_controller(home, "claire")
    assert controller is not None, 'Actual directory-plugin registration must create the named-profile controller'
    assert controller._scope_is_current()
    try:
        yield manager, observer, fast_module, controller, home, service, root, spawn_calls
    finally:
        observer.reset_for_tests()
        controller.close()
        manager.unload("model-router")
        reset_hermes_home_override(token)
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.parametrize(("mode", "expected_tier"), [("priority", "priority"), ("normal", None)])
def test_routed_snapshot_schema_to_registered_native_request_middleware(
    tmp_path, monkeypatch, loaded_fast_controller, mode, expected_tier
):
    manager, observer, fast_module, controller, home, service, root, _spawn_calls = loaded_fast_controller
    from model_router import routing

    service.light = {"provider": "openai", "model": "gpt-5.2", "reasoning": "low"}
    service.heavy = {"provider": "openai-codex", "model": "gpt-5.3", "reasoning": "high"}
    parent_session_id = "native-parent-A"
    fast_snapshot = {
        "schema": 1,
        "profile": "claire",
        "origin_session_id": "fast-origin-A",
        "parent_session_id": parent_session_id,
        "mode": mode,
        "expires_at": None,
    }
    runtime = SimpleNamespace(parent_session_id=parent_session_id, ui_session_id="ui-session-A")
    router = routing.Router(service, runtime=runtime, fast_snapshot=fast_snapshot)
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    started = router.start(
        "implementation", "Implement the bounded fixture change.", cwd,
        timeout=60, title="Fast routed pipeline fixture",
    )
    job_dir = root / "profiles" / "claire" / "plugin-data" / "model-router" / "jobs" / started["job_id"]
    job_snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert job_snapshot["schema"] == 1
    assert job_snapshot["fast_snapshot"] == fast_snapshot
    assert "fast_snapshot" not in started
    home = root / "profiles" / "claire"
    (home / "config.yaml").write_text(
        "plugins:\n  enabled: [model-router]\nagent:\n  service_tier: priority\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "claire")

    requests: list[dict[str, Any]] = []

    class AdapterProcess:
        def __init__(self, command, **_kwargs):
            request_path = Path(command[command.index("--request") + 1])
            result_path = Path(command[command.index("--result") + 1])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            requests.append(request)
            result_path.write_text(json.dumps(_route_result(request)), encoding="utf-8")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", AdapterProcess)
    args = argparse.Namespace(
        route_class="LIGHTWEIGHT", mode="implementation", verification_kind="none",
        prompt=None, prompt_file=job_dir / "prompt.txt", cache=job_dir / "routing-cache.json",
        profile="claire", job_dir=job_dir, purpose="implementation", cwd=cwd,
        toolsets=None, worktree=False, output=job_dir / "runner-result.json", timeout=60.0,
        hermes_exe=None, no_fallback=False, scoped_attempts=True, legacy_chat=False,
    )
    assert runner.run_scoped_attempts(args) == 0
    assert len(requests) == 1
    assert requests[0]["schema"] == 2
    assert requests[0]["fast_snapshot"] == job_snapshot["fast_snapshot"] == fast_snapshot
    request_path = job_dir / "attempts" / requests[0]["attempt_id"] / "attempt-request.json"
    persisted_request = json.loads(request_path.read_text(encoding="utf-8"))
    assert persisted_request == requests[0]
    assert persisted_request["parent_session_id"] == parent_session_id

    monkeypatch.setattr(fast_module, "_native_resolver", lambda **_kwargs: {"service_tier": "priority"})
    monkeypatch.setattr(fast_module, "_get_active_parent", lambda: SimpleNamespace(session_id=requests[0]["session_id"]))
    observed_requests: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"close": 0, "release": 0, "options": None}
    api_mode = "chat_completions"

    class FakeAgent:
        def __init__(self, **kwargs):
            stats["options"] = kwargs
            self.kwargs = kwargs
            self._session_init_model_config = {}

        def run_conversation(self, prompt, *, task_id):
            provider_request = {
                "model": requests[0]["route"]["model"],
                "service_tier": "stale-profile-tier",
                "speed": "stale-profile-speed",
                "extra_body": {
                    "service_tier": "stale-extra-tier",
                    "speed": "stale-extra-speed",
                    "keep": "preserve-extra",
                },
                "keep": "preserve-top-level",
            }
            results = manager.invoke_middleware(
                "llm_request",
                _payload_key="request",
                request=provider_request,
                original_request=provider_request,
                session_id=requests[0]["session_id"],
                model=requests[0]["route"]["model"],
                provider="openai",
                base_url="https://api.openai.com/v1",
                api_mode=api_mode,
            )
            fast_results = [item for item in results if item.get("source") == "model-router-fast-inheritance"]
            assert len(fast_results) == 1
            observed_requests.append(fast_results[0]["request"])
            identity = {
                "api_request_id": "mock-api-request-A",
                "session_id": requests[0]["session_id"],
                "task_id": task_id,
                "provider": "openai",
                "model": requests[0]["route"]["model"],
                "api_mode": api_mode,
            }
            manager.invoke_hook(
                "pre_api_request", **identity,
                request={"body": {"model": requests[0]["route"]["model"]}},
            )
            manager.invoke_hook(
                "post_api_request", **identity,
                response_model=requests[0]["route"]["model"],
                assistant_tool_call_count=0,
            )
            return {"completed": True, "failed": False, "partial": False, "final_response": "mock result"}

        def close(self):
            stats["close"] += 1

    def resolve_runtime_provider(*, requested, target_model):
        assert requested == "openai" and target_model == "gpt-5.2"
        return {
            "provider": "openai",
            "requested_provider": "openai",
            "api_mode": api_mode,
            "base_url": "https://api.openai.com/v1",
            "api_key": "mock-only-no-network",
            "credential_pool": None,
            "request_overrides": {
                "service_tier": "stale-profile-tier",
                "speed": "stale-profile-speed",
                "extra_body": {
                    "service_tier": "stale-extra-tier",
                    "speed": "stale-extra-speed",
                    "keep": "preserve-extra",
                },
                "keep": "preserve-override",
            },
        }

    db = object()
    dependencies = {
        "prepare_runtime": lambda _request: {
            "observer": observer,
            "fast_inheritance": fast_module,
            "AIAgent": FakeAgent,
            "resolve_runtime_provider": resolve_runtime_provider,
            "acquire_session_db": lambda: db,
            "release_session_db": lambda value: stats.update(release=stats["release"] + 1),
            "agent_options": {"service_tier": "profile-config-tier", "max_iterations": 3},
        },
        "observer": observer,
        "redact": lambda value: value,
    }
    result = scoped_agent.run_attempt(persisted_request, dependencies=dependencies)

    assert result["completed"] is True, result.get("error")
    assert result["evidence_complete"] is True
    assert stats["close"] == stats["release"] == 1
    assert stats["options"]["service_tier"] is None
    assert stats["options"]["fallback_model"] == []
    overrides = stats["options"]["request_overrides"]
    assert "service_tier" not in overrides and "speed" not in overrides
    assert overrides["extra_body"] == {"keep": "preserve-extra"}
    assert overrides["keep"] == "preserve-override"
    expected_request = {
        "model": "gpt-5.2",
        "extra_body": {"keep": "preserve-extra"},
        "keep": "preserve-top-level",
    }
    if expected_tier is not None:
        expected_request["service_tier"] = expected_tier
    assert observed_requests == [expected_request]
    assert "fast_snapshot" not in result
    assert "service_tier" not in json.dumps(result)
