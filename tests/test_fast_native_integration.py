"""Native plugin-loader/middleware and OpenAI SDK wire tests; no live sockets or auth."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from openai import OpenAI



CORE_SPEC = importlib.util.find_spec("hermes_cli")
CORE = Path(CORE_SPEC.origin).resolve().parents[1] if CORE_SPEC and CORE_SPEC.origin else None
REPO = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / "model-router-native-fixtures"


@pytest.fixture
def native_plugin(monkeypatch):
    if CORE is None:
        pytest.skip("native Hermes integration requires an installed compatible core")
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

    # The request hook must see the current child agent identity and configured
    # runtime, not merely matching caller-supplied metadata.
    binding = runtime.controller._children.get(session)
    child_fields = {}
    if binding is not None:
        child_fields = {
            "_parent_session_id": binding.parent_session_id,
            "_subagent_id": binding.child_subagent_id,
            "platform": "subagent",
        }
    child_agent = SimpleNamespace(
        session_id=session, service_tier=None, model=model, provider=provider,
        base_url=base_url, api_mode=api_mode, **child_fields,
    )
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

    native_parent_binding = runtime.controller._children["native-child-a"]
    nested_parent = SimpleNamespace(
        session_id="native-child-a", _parent_session_id=native_parent_binding.parent_session_id,
        _subagent_id=native_parent_binding.child_subagent_id, platform="subagent", service_tier=None,
        model="gpt-6-astra", provider="openai-api", base_url="https://api.openai.com/v1",
        api_mode="chat_completions", _fast_until=0.0,
    )

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
    # The fixture already binds the genuine home override before plugin load.
    # Rebinding HERMES_HOME here changes the inferred base/profile (custom ->
    # default on current hosts) AFTER the controller captured its identity;
    # correctly fail-closed Fast callbacks must then refuse that stale scope.
    from hermes_constants import get_hermes_home
    from hermes_cli.profiles import get_active_profile_name
    assert get_hermes_home().resolve() == runtime.home
    assert get_active_profile_name() == runtime.controller.profile
    assert runtime.controller._scope_is_current()
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
            self.platform = kwargs["platform"]
            self._parent_session_id = kwargs["parent_session_id"]
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


def test_actual_sdk_wire_model_and_paid_tier_stay_coupled_after_middleware(native_plugin):
    runtime = native_plugin
    parent = SimpleNamespace(session_id="mismatch-root", service_tier="priority", _fast_until=0.0)
    _spawn_through_native_middleware(runtime, parent, child_session="mismatch-child", subagent_id="mismatch-native-id")
    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json={
            "id": "chatcmpl-mismatch-fixture", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "offline"}, "finish_reason": "stop"}],
        })

    client = OpenAI(
        api_key="offline-test-only", base_url="https://api.openai.com/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    cases = (
        {"model": "untrusted-wire-model", "messages": [{"role": "user", "content": "offline"}],
         "service_tier": "stale", "speed": "fast"},
        {"model": "gpt-6-astra", "messages": [{"role": "user", "content": "offline"}],
         "service_tier": "stale", "extra_body": {"model": "untrusted-extra-model",
                                                    "service_tier": "stale", "speed": "fast"}},
    )
    try:
        for payload in cases:
            kwargs = _managed_request(
                runtime, session="mismatch-child", model="gpt-6-astra", provider="openai-api",
                base_url="https://api.openai.com/v1", api_mode="chat_completions", payload=payload,
            )
            response = client.chat.completions.create(**kwargs)
            assert response.choices[0].message.content == "offline"
    finally:
        client.close()

    assert [body["model"] for body in captured] == ["untrusted-wire-model", "untrusted-extra-model"]
    assert all("service_tier" not in body and "speed" not in body for body in captured)


def test_native_runtime_context_mismatch_only_cleans_managed_fast_fields(native_plugin):
    runtime = native_plugin
    parent = SimpleNamespace(session_id="runtime-root", service_tier="priority", _fast_until=0.0)
    _spawn_through_native_middleware(runtime, parent, child_session="runtime-child", subagent_id="runtime-native-id")
    binding = runtime.controller._children["runtime-child"]
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli.middleware import apply_llm_request_middleware

    child = SimpleNamespace(
        session_id="runtime-child", _parent_session_id=binding.parent_session_id,
        _subagent_id=binding.child_subagent_id, platform="subagent", service_tier=None,
        model="gpt-6-astra", provider="openai-api", base_url="https://api.openai.com/v1",
        api_mode="chat_completions",
    )
    request = {"model": "gpt-6-astra", "service_tier": "stale", "speed": "fast",
               "extra_body": {"service_tier": "stale", "speed": "fast", "keep": True}}
    with bind_subagent_parent(child):
        result = apply_llm_request_middleware(
            request, session_id=child.session_id, model="different-runtime-model", provider=child.provider,
            base_url=child.base_url, api_mode=child.api_mode, api_call_count=1,
        ).payload
    assert "service_tier" not in result and "speed" not in result
    assert result["extra_body"] == {"keep": True}


def test_creator_proof_survives_actual_native_async_and_daemon_child_dispatch(native_plugin, monkeypatch):
    import threading

    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli import middleware
    from tools import async_delegation, delegate_tool, delegate_tool_dispatch
    from tools.daemon_pool import DaemonThreadPoolExecutor

    runtime = native_plugin
    monkeypatch.setattr(runtime.fast, "MAX_CHILD_BINDINGS", 1)
    parent = SimpleNamespace(session_id="queued-root", service_tier="priority", _fast_until=0.0)
    children = [
        SimpleNamespace(
            session_id=f"queued-child-{index}", _parent_session_id=parent.session_id,
            _subagent_id=f"queued-native-{index}", platform="subagent", service_tier=None,
            model="gpt-6-astra", provider="openai-api", base_url="https://api.openai.com/v1",
            api_mode="chat_completions",
        )
        for index in (0, 1)
    ]
    observed = {}
    observed_lock = threading.Lock()
    finished = threading.Event()
    completion = {}
    executors = []

    monkeypatch.setattr(async_delegation, "_persist_dispatch", lambda _record: None)
    monkeypatch.setattr(async_delegation, "_persist_completion", lambda *_args: None)

    def capture_completion(_record, result, status):
        completion.update(result=result, status=status)
        finished.set()

    monkeypatch.setattr(async_delegation, "_push_completion_event", capture_completion)

    def make_executor(max_workers):
        executor = DaemonThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mfr-test-async")
        executors.append(executor)
        return executor

    monkeypatch.setattr(async_delegation, "_get_executor", make_executor)
    monkeypatch.setattr(delegate_tool_dispatch, "_report_child_done", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delegate_tool_dispatch, "_record_finished_child", lambda *_args, **_kwargs: None)

    def run_single(*, task_index, child, **_kwargs):
        payload = {
            "model": child.model, "messages": [], "service_tier": "stale", "speed": "fast",
            "extra_body": {"service_tier": "stale", "speed": "fast", "keep": task_index},
        }
        with bind_subagent_parent(child):
            clean = middleware.apply_llm_request_middleware(
                payload, session_id=child.session_id, model=child.model, provider=child.provider,
                base_url=child.base_url, api_mode=child.api_mode, api_call_count=1,
            ).payload
        with observed_lock:
            observed[child.session_id] = clean
        return {"task_index": task_index, "status": "completed", "duration_seconds": 0.0}

    monkeypatch.setattr(delegate_tool, "_run_single_child", run_single)
    tasks = [{"goal": "offline queued fixture A"}, {"goal": "offline queued fixture B"}]
    batch = SimpleNamespace(
        task_list=tasks,
        children=[(index, tasks[index], child) for index, child in enumerate(children)],
        parent_agent=parent,
        max_children=2,
        live_deleg_id=None,
        live_paths=[],
        unit_id=None,
        run_child=lambda index, task, child: run_single(task_index=index, child=child),
    )

    def background_runner():
        results = []
        delegate_tool_dispatch._run_children_parallel(batch, results, honor_parent_interrupt=False)
        return {"status": "completed", "results": results}

    def native_queue_dispatch(_args):
        for child in children:
            runtime.manager.invoke_hook(
                "subagent_start", parent_session_id=parent.session_id,
                child_session_id=child.session_id, child_subagent_id=child._subagent_id,
                child_role="leaf", child_goal="PRIVATE_QUEUED_GOAL_NOT_RETAINED",
            )
        # Child 0 is deliberately evicted from the bounded global cache when 1 registers.
        assert "queued-child-0" not in runtime.controller._children
        return async_delegation.dispatch_async_delegation(
            goal="offline async queue fixture", context=None, toolsets=None, role="leaf", model=None,
            session_key="fixture-session", parent_session_id=parent.session_id,
            runner=background_runner, max_async_children=2,
        )

    try:
        with bind_subagent_parent(parent):
            handle = middleware.run_tool_execution_middleware(
                "delegate_task", {}, native_queue_dispatch, session_id=parent.session_id,
            )
        assert handle["status"] == "dispatched"
        assert finished.wait(timeout=30), "actual async delegation queue did not finish its offline fixture"
        assert completion["status"] == "completed"
        assert set(observed) == {child.session_id for child in children}
        assert all(row["service_tier"] == "priority" for row in observed.values())
        assert all("speed" not in row and "service_tier" not in row["extra_body"] for row in observed.values())
    finally:
        for executor in executors:
            executor.shutdown(wait=True, cancel_futures=True)
        if "handle" in locals() and handle.get("delegation_id"):
            with async_delegation._records_lock:
                async_delegation._records.pop(handle["delegation_id"], None)
        for child in children:
            runtime.manager.invoke_hook(
                "subagent_stop", parent_session_id=parent.session_id, child_session_id=child.session_id,
            )
