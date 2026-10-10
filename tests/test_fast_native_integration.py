"""Native plugin-loader/middleware and OpenAI SDK wire tests; no live sockets or auth."""
from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from openai import OpenAI



CORE = Path("C:/Users/ovpow/AppData/Local/hermes/hermes-agent")
REPO = Path(__file__).resolve().parents[1]
SCRATCH = Path("C:/Users/ovpow/AppData/Local/hermes/profiles/claire/cache/scratch")


@pytest.fixture
def native_plugin(monkeypatch):
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "1")
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli import plugins
    from hermes_cli.plugins_manifest import parse_manifest_file

    home = SCRATCH / f"mfr-fast-native-{uuid4().hex}"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: [model-router]\n", encoding="utf-8")
    token = set_hermes_home_override(str(home))
    manager = plugins.PluginManager(scope_key=str(home))
    manifest = parse_manifest_file(REPO / "plugin.yaml", REPO, "user", "")
    assert manifest is not None
    manager._load_plugin(manifest)
    entry = manager._plugins["model-router"]
    assert entry.enabled, entry.error
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)
    package = entry.module
    fast_module = importlib.import_module(f"{package.__name__}.model_router.fast_inheritance")
    assert fast_module.__name__ != "model_router.fast_inheritance"
    assert fast_module.__name__.startswith("hermes_plugins.model_router")
    callback = next(
        cb for cb in manager._middleware.get("llm_request", [])
        if getattr(cb, "__module__", None) == fast_module.__name__
    )
    controller = callback.__self__
    assert type(controller).__module__ == fast_module.__name__
    try:
        yield SimpleNamespace(home=home.resolve(), manager=manager, fast=fast_module, controller=controller)
    finally:
        manager.unload("model-router")
        assert not manager._middleware.get("tool_execution")
        assert not manager._middleware.get("llm_request")
        assert not manager._hooks.get("subagent_start")
        assert not manager._hooks.get("subagent_stop")
        reset_hermes_home_override(token)
        shutil.rmtree(home, ignore_errors=True)


def _spawn_through_native_middleware(runtime, parent, *, child_session, subagent_id):
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli import middleware

    def native_child_build(_args):
        runtime.manager.invoke_hook(
            "subagent_start", parent_session_id=parent.session_id,
            child_session_id=child_session, child_subagent_id=subagent_id,
            child_role="leaf", child_goal="PRIVATE_CHILD_GOAL_DO_NOT_RETAIN",
        )
        return {"status": "dispatched", "child": child_session}

    with bind_subagent_parent(parent):
        return middleware.run_tool_execution_middleware(
            "delegate_task", {"goal": "PRIVATE_CHILD_GOAL_DO_NOT_RETAIN"}, native_child_build,
            session_id=parent.session_id,
        )


def _managed_request(runtime, *, session, model, provider, base_url, api_mode, payload):
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli.middleware import apply_llm_request_middleware

    # The request hook must see the current child agent identity, not merely a
    # matching session_id supplied by a caller.
    child_agent = SimpleNamespace(session_id=session, service_tier=None, _fast_until=0.0)
    with bind_subagent_parent(child_agent):
        return apply_llm_request_middleware(
            payload, session_id=session, model=model, provider=provider, base_url=base_url,
            api_mode=api_mode, api_call_count=1,
        ).payload


def test_actual_loader_tool_dispatch_hooks_and_async_nested_child_inheritance(native_plugin):
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli import middleware

    runtime = native_plugin
    parent = SimpleNamespace(session_id="native-root", service_tier="priority", _fast_until=0.0)
    assert _spawn_through_native_middleware(
        runtime, parent, child_session="native-child-a", subagent_id="native-id-a",
    )["status"] == "dispatched"
    assert _spawn_through_native_middleware(
        runtime, parent, child_session="native-child-b", subagent_id="native-id-b",
    )["status"] == "dispatched"

    request = {"model": "gpt-6-astra", "messages": [], "service_tier": "stale", "extra_body": {"speed": "fast", "keep": 1}}
    inherited_a = _managed_request(
        runtime, session="native-child-a", model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", payload=request,
    )
    inherited_b = _managed_request(
        runtime, session="native-child-b", model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", payload=request,
    )
    assert inherited_a["service_tier"] == inherited_b["service_tier"] == "priority"
    assert "speed" not in inherited_a["extra_body"] and inherited_a["extra_body"]["keep"] == 1

    nested_parent = SimpleNamespace(session_id="native-child-a", service_tier=None, _fast_until=0.0)

    async def native_async_build(_args):
        await asyncio.sleep(0)
        runtime.manager.invoke_hook(
            "subagent_start", parent_session_id="native-child-a", child_session_id="native-grandchild",
            child_subagent_id="native-grandchild-id", child_role="leaf",
            child_goal="PRIVATE_NESTED_GOAL_DO_NOT_RETAIN",
        )
        return "async-dispatched"

    with bind_subagent_parent(nested_parent):
        async_result = middleware.run_tool_execution_middleware(
            "delegate_task", {"action": "spawn"}, native_async_build,
            session_id="native-child-a",
        )
        assert asyncio.run(async_result) == "async-dispatched"

    nested = _managed_request(
        runtime, session="native-grandchild", model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", payload=request,
    )
    assert nested["service_tier"] == "priority"

    # Actual route-start tool middleware exposes a dispatch-scoped snapshot only.
    fast_tool_callback = next(
        cb for cb in runtime.manager._middleware["tool_execution"]
        if getattr(cb, "__module__", None) == runtime.fast.__name__
    )
    captured = []
    with bind_subagent_parent(parent):
        value = middleware.run_tool_execution_middleware(
            "coding_route", {"action": "start"},
            lambda _args: captured.append(runtime.controller.capture_for_route("native-root", "custom")) or "route-start",
            session_id="native-root",
        )
    assert value == "route-start" and captured[0]["mode"] == "priority"
    assert runtime.controller.capture_for_route("native-root", "custom") is None
    assert fast_tool_callback is not None

    runtime.manager.invoke_hook("subagent_stop", parent_session_id="native-root", child_session_id="native-child-a")
    after_stop = _managed_request(
        runtime, session="native-child-a", model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", payload=request,
    )
    assert after_stop["service_tier"] == "stale"  # exact stop retires management; no synthetic cleanup
    still_owned = _managed_request(
        runtime, session="native-child-b", model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", payload=request,
    )
    assert still_owned["service_tier"] == "priority"
    runtime.manager.invoke_hook("subagent_stop", parent_session_id="native-root", child_session_id="native-child-b")
    runtime.manager.invoke_hook("subagent_stop", parent_session_id="native-child-a", child_session_id="native-grandchild")


def test_real_delegate_task_child_builder_emits_fast_hooks_with_total_zero(native_plugin, monkeypatch):
    import threading
    from uuid import uuid4

    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli import middleware
    from model_router.timeouts import read_timeouts
    from tools import delegate_tool as native
    import run_agent

    runtime = native_plugin
    monkeypatch.setenv("HERMES_HOME", str(runtime.home))
    assert read_timeouts(runtime.home)["delegate_total_seconds"] == 0

    class Parent:
        model = "gpt-6-astra"
        provider = "openai-api"
        requested_provider = "openai-api"
        base_url = "https://api.openai.com/v1"
        api_key = None
        api_mode = "chat_completions"
        service_tier = "priority"
        enabled_toolsets = []
        disabled_toolsets = []
        request_overrides = {}
        _fallback_chain = []
        _delegate_depth = 0
        _interrupt_requested = False
        _session_db = None
        session_db = None
        tool_progress_callback = None

        def __init__(self):
            self.session_id = "real-native-parent"
            self._active_children = []
            self._active_children_lock = threading.Lock()

        def _touch_activity(self, _description):
            pass

    class OfflineNativeChild:
        instances = []

        def __init__(self, **kwargs):
            self.session_id = "real-native-child-" + uuid4().hex
            self.model = kwargs["model"]
            self.provider = kwargs["provider"]
            self.base_url = kwargs["base_url"]
            self.api_mode = kwargs["api_mode"]
            self.service_tier = None
            self.tool_progress_callback = kwargs.get("tool_progress_callback")
            self._session_init_model_config = {}
            self._interrupt_requested = False
            self._hard_interrupt_requested = threading.Event()
            self._credential_pool = None
            self.messages = []
            self.session_api_calls = 0
            self.request_body = None
            type(self).instances.append(self)

        def run_conversation(self, *args, **kwargs):
            from agent.subagent_lifecycle import bind_subagent_parent
            from hermes_cli.middleware import apply_llm_request_middleware

            with bind_subagent_parent(self):
                self.request_body = apply_llm_request_middleware(
                    {"model": self.model, "messages": [], "service_tier": "stale"},
                    session_id=self.session_id, model=self.model, provider=self.provider,
                    base_url=self.base_url, api_mode=self.api_mode, api_call_count=1,
                ).payload
            return {"completed": True, "failed": False, "interrupted": False,
                    "final_response": "offline native child fixture", "messages": []}

        def interrupt(self, *args, **kwargs):
            self._interrupt_requested = True
            self._hard_interrupt_requested.set()

        def get_activity_summary(self):
            return {"api_call_count": 0, "current_tool": None, "last_activity_ts": 1.0, "max_iterations": 3}

        def close(self):
            pass

    config = {
        "max_iterations": 3,
        "max_spawn_depth": 2,
        "max_concurrent_children": 2,
        "child_timeout_seconds": 0,
        "max_async_children": 2,
        "orchestrator_enabled": False,
    }
    credentials = {
        "provider": "openai-api", "model": "gpt-6-astra", "base_url": "https://api.openai.com/v1",
        "api_key": None, "api_mode": "chat_completions", "request_overrides": None,
        "command": None, "args": None,
    }
    monkeypatch.setattr(native, "_load_config", lambda: dict(config))
    monkeypatch.setattr(native, "_get_max_spawn_depth", lambda: 2)
    monkeypatch.setattr(native, "_get_orchestrator_enabled", lambda: False)
    monkeypatch.setattr(native, "_get_max_concurrent_children", lambda: 2)
    monkeypatch.setattr(native, "_resolve_delegation_credentials", lambda *_args: dict(credentials))
    monkeypatch.setattr(native, "_resolve_child_runtime", lambda *_args, **_kwargs: {
        "provider": "openai-api", "requested_provider": "openai-api", "model": "gpt-6-astra",
        "base_url": "https://api.openai.com/v1", "api_key": None, "api_mode": "chat_completions",
    })
    monkeypatch.setattr(native, "_resolve_child_credential_pool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(native, "_apply_child_compression_cap", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_agent, "AIAgent", OfflineNativeChild)
    OfflineNativeChild.instances.clear()
    parent = Parent()

    with bind_subagent_parent(parent):
        result = middleware.run_tool_execution_middleware(
            "delegate_task", {"goal": "offline native child only"},
            lambda payload: native.delegate_task(**payload, parent_agent=parent),
            session_id=parent.session_id,
        )
    parsed = json.loads(result)
    assert parsed["results"][0]["status"] == "completed"
    assert len(OfflineNativeChild.instances) == 1
    child = OfflineNativeChild.instances[0]
    assert child.request_body["service_tier"] == "priority"
    assert not runtime.controller._children, "real subagent_stop must retire the exact child binding"


def test_actual_openai_sdk_chat_and_codex_responses_wire_bodies(native_plugin):
    runtime = native_plugin
    parent = SimpleNamespace(session_id="wire-root", service_tier="priority", _fast_until=0.0)
    _spawn_through_native_middleware(runtime, parent, child_session="wire-child", subagent_id="wire-native-id")
    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append((request.url.path, body))
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={
                "id": "chatcmpl-offline-fixture", "object": "chat.completion", "created": 1,
                "model": "gpt-6-astra", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "offline"}, "finish_reason": "stop"}],
            })
        return httpx.Response(200, json={
            "id": "resp_offline_fixture", "object": "response", "created_at": 1,
            "status": "completed", "model": "gpt-6-astra", "output": [{
                "id": "msg_offline_fixture", "type": "message", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": "offline", "annotations": []}],
            }],
        })

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAI(api_key="offline-test-only", base_url="https://api.openai.com/v1", http_client=http_client)
    try:
        chat_kwargs = _managed_request(
            runtime, session="wire-child", model="gpt-6-astra", provider="openai-api",
            base_url="https://api.openai.com/v1", api_mode="chat_completions",
            payload={"model": "gpt-6-astra", "messages": [{"role": "user", "content": "offline fixture"}],
                     "service_tier": "stale", "speed": "fast",
                     "extra_body": {"service_tier": "stale", "speed": "fast", "fixture_keep": "chat"}},
        )
        chat = client.chat.completions.create(**chat_kwargs)
        assert chat.choices[0].message.content == "offline"

        codex_kwargs = _managed_request(
            runtime, session="wire-child", model="gpt-6-astra", provider="openai-codex",
            base_url="https://chatgpt.com/backend-api/codex", api_mode="codex_responses",
            payload={"model": "gpt-6-astra", "input": "offline fixture", "service_tier": "stale",
                     "extra_body": {"service_tier": "stale", "speed": "fast", "fixture_keep": "responses"}},
        )
        # The direct SDK client uses an in-memory MockTransport; it cannot open a socket.
        client.base_url = httpx.URL("https://chatgpt.com/backend-api/codex/")
        response = client.responses.create(**codex_kwargs)
        assert response.status == "completed"
    finally:
        client.close()

    assert [path.rsplit("/", 1)[-1] for path, _body in captured] == ["completions", "responses"]
    chat_body, codex_body = captured[0][1], captured[1][1]
    assert chat_body["service_tier"] == codex_body["service_tier"] == "priority"
    assert chat_body["fixture_keep"] == "chat" and codex_body["fixture_keep"] == "responses"
    assert "speed" not in chat_body and "speed" not in codex_body
    assert "service_tier" not in chat_kwargs["extra_body"] and "speed" not in chat_kwargs["extra_body"]
    assert "service_tier" not in codex_kwargs["extra_body"] and "speed" not in codex_kwargs["extra_body"]


def test_actual_sdk_streaming_keeps_managed_tier_on_the_wire(native_plugin):
    runtime = native_plugin
    parent = SimpleNamespace(session_id="stream-root", service_tier="priority", _fast_until=0.0)
    _spawn_through_native_middleware(runtime, parent, child_session="stream-child", subagent_id="stream-native-id")
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        data = (
            'data: {"id":"chatcmpl-stream-fixture","object":"chat.completion.chunk","created":1,'
            '"model":"gpt-6-astra","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
            'data: {"id":"chatcmpl-stream-fixture","object":"chat.completion.chunk","created":1,'
            '"model":"gpt-6-astra","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)

    client = OpenAI(
        api_key="offline-test-only", base_url="https://api.openai.com/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    try:
        kwargs = _managed_request(
            runtime, session="stream-child", model="gpt-6-astra", provider="openai-api",
            base_url="https://api.openai.com/v1", api_mode="chat_completions",
            payload={"model": "gpt-6-astra", "messages": [{"role": "user", "content": "offline"}],
                     "service_tier": "stale", "speed": "fast"},
        )
        stream = client.chat.completions.create(**kwargs, stream=True)
        chunks = list(stream)
        assert "ok" in "".join(chunk.choices[0].delta.content or "" for chunk in chunks)
    finally:
        client.close()
    assert captured[0]["service_tier"] == "priority"
    assert "speed" not in captured[0]
