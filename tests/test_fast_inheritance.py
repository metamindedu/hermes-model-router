"""RED/GREEN unit contracts for plugin-owned Fast inheritance.

Every fixture is contained under Claire's explicit scratch directory.
"""
from __future__ import annotations

import asyncio
import json
import math
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from model_router import fast_inheritance as fi

SCRATCH = Path("C:/Users/ovpow/AppData/Local/hermes/profiles/claire/cache/scratch")


@pytest.fixture
def home():
    path = SCRATCH / f"mfr-fast-unit-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path.resolve()
    finally:
        shutil.rmtree(path, ignore_errors=True)


def snap(mode="priority", *, profile="custom", origin="root-A", parent="root-A", expires=None):
    return {
        "schema": 1,
        "profile": profile,
        "origin_session_id": origin,
        "parent_session_id": parent,
        "mode": mode,
        "expires_at": expires,
    }


class Registration:
    def __init__(self, dispose):
        self._dispose = dispose

    def dispose(self):
        if self._dispose is not None:
            callback, self._dispose = self._dispose, None
            callback()


class PluginContext:
    profile_name = "custom"

    def __init__(self, *, fail_at=None):
        self.middleware = []
        self.hooks = {}
        self.unload = []
        self.fail_at = fail_at

    def _add(self, kind, key, callback):
        if self.fail_at == (kind, key):
            raise RuntimeError("fixture registration failure")
        if kind == "middleware":
            row = (key, callback)
            self.middleware.append(row)
            return Registration(lambda: self.middleware.remove(row) if row in self.middleware else None)
        row = callback
        self.hooks.setdefault(key, []).append(row)
        def remove_hook():
            callbacks = self.hooks.get(key, [])
            if row in callbacks:
                callbacks.remove(row)
            if not callbacks:
                self.hooks.pop(key, None)
        return Registration(remove_hook)

    def register_middleware(self, kind, callback):
        return self._add("middleware", kind, callback)

    def register_hook(self, name, callback):
        return self._add("hook", name, callback)

    def on_unload(self, callback):
        if self.fail_at == ("unload", ""):
            raise RuntimeError("fixture unload registration failure")
        self.unload.append(callback)
        return Registration(lambda: self.unload.remove(callback) if callback in self.unload else None)


def register(monkeypatch, home, parent, *, fail_at=None):
    ctx = PluginContext(fail_at=fail_at)
    monkeypatch.setattr(fi, "_get_hermes_home", lambda: home)
    monkeypatch.setattr(fi, "_get_active_parent", lambda: parent)
    controller = fi.register_fast_inheritance(ctx, home)
    if controller is not None:
        monkeypatch.setattr(controller, "_current_profile", lambda: "custom")
    return ctx, controller


def test_snapshot_validation_is_exact_primitive_and_unavailable_is_not_normal():
    original = snap("auto", expires=1234.5)
    clean = fi.validate_fast_snapshot(original, profile="custom", parent_session_id="root-A")
    assert clean == original
    assert clean is not original
    assert fi.validate_fast_snapshot(None) is None
    assert fi.validate_fast_snapshot(snap("normal"))["mode"] == "normal"

    bad = [
        {**original, "schema": True},
        {**original, "other": "extra"},
        {**original, "profile": "../custom"},
        {**original, "origin_session_id": " root-A"},
        {**original, "mode": "fast-ish"},
        {**original, "expires_at": float("nan")},
        {**original, "expires_at": True},
        {**snap("priority"), "expires_at": 12.0},
        {**snap("normal"), "expires_at": 0.0},
    ]
    for value in bad:
        with pytest.raises(ValueError):
            fi.validate_fast_snapshot(value)
    with pytest.raises(ValueError):
        fi.validate_fast_snapshot(original, profile="foreign")
    with pytest.raises(ValueError):
        fi.validate_fast_snapshot(original, parent_session_id="foreign-parent")


def test_capture_uses_actual_parent_and_native_fast_mode_without_private_writes(monkeypatch, home):
    parent = SimpleNamespace(session_id="root-A", service_tier="ultrafast", _fast_until=88.0)
    _ctx, controller = register(monkeypatch, home, parent)
    assert controller is not None
    before = parent._fast_until
    captured = fi.capture_fast_snapshot(
        parent, profile="custom", parent_session_id="root-A", monotonic=lambda: 100.0,
        wall_clock=lambda: 500.0,
    )
    assert captured == snap("ultrafast")
    assert parent._fast_until == before
    assert fi.capture_fast_snapshot(
        parent, profile="custom", parent_session_id="different", monotonic=lambda: 1,
        wall_clock=lambda: 1,
    ) is None
    assert fi.capture_fast_snapshot(
        parent, profile="../foreign", parent_session_id="root-A", monotonic=lambda: 1,
        wall_clock=lambda: 1,
    ) is None


def test_auto_and_cold_copy_original_expiry_and_never_reopen_inactive_window(monkeypatch, home):
    parent = SimpleNamespace(session_id="root-A", service_tier="auto", _fast_until=120.0)
    register(monkeypatch, home, parent)
    parent_until = parent._fast_until
    active = fi.capture_fast_snapshot(
        parent, profile="custom", parent_session_id="root-A", monotonic=lambda: 100.0,
        wall_clock=lambda: 1_000.0,
    )
    assert active == snap("auto", expires=1_020.0)
    assert parent._fast_until == parent_until

    nested_parent = SimpleNamespace(session_id="child-A", service_tier=None)
    monkeypatch.setattr(fi, "_get_active_parent", lambda: nested_parent)
    nested = fi.capture_fast_snapshot(
        nested_parent, profile="custom",
        parent_session_id="child-A", inherited_snapshot=active,
        monotonic=lambda: 10_000.0, wall_clock=lambda: 50_000.0,
    )
    assert nested == snap("auto", origin="root-A", parent="child-A", expires=1_020.0)

    monkeypatch.setattr(fi, "_get_active_parent", lambda: parent)
    parent.service_tier = "cold"
    parent._fast_until = 99.0
    inactive = fi.capture_fast_snapshot(
        parent, profile="custom", parent_session_id="root-A", monotonic=lambda: 100.0,
        wall_clock=lambda: 0.0,
    )
    assert inactive == snap("cold", expires=0.0)
    assert parent._fast_until == 99.0


def test_missing_or_unknown_bounded_expiry_is_unavailable_not_normal(monkeypatch, home):
    for until in (None, "unknown", float("nan"), float("inf"), True):
        parent = SimpleNamespace(session_id="root-A", service_tier="cold", _fast_until=until)
        register(monkeypatch, home, parent)
        assert fi.capture_fast_snapshot(
            parent, profile="custom", parent_session_id="root-A", monotonic=lambda: 5.0,
            wall_clock=lambda: 100.0,
        ) is None
    parent = SimpleNamespace(session_id="root-A", service_tier="unrecognized")
    register(monkeypatch, home, parent)
    assert fi.capture_fast_snapshot(
        parent, profile="custom", parent_session_id="root-A", monotonic=lambda: 5.0,
        wall_clock=lambda: 100.0,
    ) is None


def test_managed_normal_and_expired_requests_remove_only_fast_fields():
    source = {
        "model": "gpt-6-astra",
        "messages": [{"role": "user", "content": "fixture"}],
        "service_tier": "stale-tier",
        "speed": "fast",
        "extra_body": {"service_tier": "priority", "speed": "fast", "reasoning": {"effort": "high"}, "keep": [1, 2]},
        "timeout": 17,
    }
    resolver_calls = []
    clean = fi.apply_fast_snapshot(
        source, snap("normal"), model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions",
        resolver=lambda **kw: resolver_calls.append(kw) or {"service_tier": "priority"},
    )
    assert "service_tier" not in clean and "speed" not in clean
    assert "service_tier" not in clean["extra_body"] and "speed" not in clean["extra_body"]
    assert clean["extra_body"] == {"reasoning": {"effort": "high"}, "keep": [1, 2]}
    assert clean["messages"] == source["messages"] and clean["timeout"] == 17
    assert clean is not source and clean["extra_body"] is not source["extra_body"]
    assert source["service_tier"] == "stale-tier" and source["extra_body"]["speed"] == "fast"
    assert resolver_calls == []

    expired = fi.apply_fast_snapshot(
        source, snap("auto", expires=9.0), model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", wall_clock=lambda: 9.0,
    )
    assert "service_tier" not in expired and "speed" not in expired


def test_supported_openai_api_and_codex_use_native_resolver_without_ultrafast_downgrade():
    calls = []

    def resolver(**kwargs):
        calls.append(kwargs)
        return {"service_tier": "ultrafast"} if kwargs.get("tier") == "ultrafast" else {"service_tier": "priority"}

    request = {"model": "gpt-6-astra", "messages": [], "extra_body": {"unrelated": True, "speed": "fast"}}
    api = fi.apply_fast_snapshot(
        request, snap("priority"), model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions", resolver=resolver,
    )
    codex = fi.apply_fast_snapshot(
        request, snap("ultrafast"), model="gpt-6-astra", provider="openai-codex",
        base_url="https://chatgpt.com/backend-api/codex", api_mode="codex_responses", resolver=resolver,
    )
    assert api["service_tier"] == "priority" and "speed" not in api
    assert codex["service_tier"] == "ultrafast" and "speed" not in codex
    assert codex["extra_body"] == {"unrelated": True}
    assert calls == [
        {"tier": None, "model_id": "gpt-6-astra", "provider": "openai-api", "base_url": "https://api.openai.com/v1"},
        {"tier": "ultrafast", "model_id": "gpt-6-astra", "provider": "openai-codex", "base_url": "https://chatgpt.com/backend-api/codex"},
    ]

    unsupported = fi.apply_fast_snapshot(
        request, snap("ultrafast"), model="gpt-6-astra", provider="openai-api",
        base_url="https://api.openai.com/v1", api_mode="chat_completions",
        resolver=lambda **_kw: None,
    )
    assert "service_tier" not in unsupported and "speed" not in unsupported
    proxy = fi.apply_fast_snapshot(
        request, snap("priority"), model="gpt-6-astra", provider="openai-api",
        base_url="https://proxy.example/v1", api_mode="chat_completions",
        resolver=lambda **_kw: {"service_tier": "priority"},
    )
    assert "service_tier" not in proxy and "speed" not in proxy
    unknown_endpoint = fi.apply_fast_snapshot(
        request, snap("priority"), model="gpt-6-astra", provider="openai-api",
        base_url="", api_mode="chat_completions",
        resolver=lambda **_kw: {"service_tier": "priority"},
    )
    assert "service_tier" not in unknown_endpoint and "speed" not in unknown_endpoint
    foreign_provider = fi.apply_fast_snapshot(
        request, snap("priority"), model="gpt-6-astra", provider="openrouter",
        base_url="https://openrouter.ai/api/v1", api_mode="chat_completions",
        resolver=lambda **_kw: {"service_tier": "priority"},
    )
    assert "service_tier" not in foreign_provider and "speed" not in foreign_provider


def test_unavailable_snapshot_is_inert_but_invalid_snapshot_fails_closed():
    source = {"model": "gpt-6-astra", "service_tier": "keep", "extra_body": {"speed": "fast"}}
    untouched = fi.apply_fast_snapshot(
        source, None, model="gpt-6-astra", provider="openai-api", base_url="https://api.openai.com/v1",
        api_mode="chat_completions",
    )
    assert untouched == source and untouched is not source
    with pytest.raises(ValueError):
        fi.apply_fast_snapshot(
            source, {"schema": True}, model="gpt-6-astra", provider="openai-api",
            base_url="https://api.openai.com/v1", api_mode="chat_completions",
        )


def test_route_capture_is_scoped_to_actual_tool_execution_and_profile(monkeypatch, home):
    parent = SimpleNamespace(session_id="route-parent", service_tier="priority")
    ctx, controller = register(monkeypatch, home, parent)
    assert controller is not None
    execution = next(callback for kind, callback in ctx.middleware if kind == "tool_execution")
    called = []

    def downstream():
        called.append("once")
        first = controller.capture_for_route("route-parent", "custom")
        first["mode"] = "normal"
        return controller.capture_for_route("route-parent", "custom")

    assert controller.capture_for_route("route-parent", "custom") is None
    assert execution(
        tool_name="coding_route", args={"action": "status"}, session_id="route-parent",
        next_call=lambda: called.append("once"),
    ) is None
    assert called == ["once"]
    called.clear()

    value = execution(tool_name="coding_route", args={"action": "start"}, session_id="route-parent", next_call=downstream)
    assert value == snap("priority", origin="route-parent", parent="route-parent") and called == ["once"]

    wrong = execution(
        tool_name="coding_route", args={"action": "start"}, session_id="foreign-parent",
        next_call=lambda: controller.capture_for_route("foreign-parent", "custom"),
    )
    assert wrong is None
    wrong_profile = execution(
        tool_name="coding_route", args={"action": "start"}, session_id="route-parent",
        next_call=lambda: controller.capture_for_route("route-parent", "foreign"),
    )
    assert wrong_profile is None

    monkeypatch.setattr(fi, "_get_active_parent", lambda: SimpleNamespace(session_id="route-parent", service_tier="priority"))
    replacement = SimpleNamespace(session_id="route-parent", service_tier="priority")
    def replaced_parent_dispatch():
        monkeypatch.setattr(fi, "_get_active_parent", lambda: replacement)
        return controller.capture_for_route("route-parent", "custom")
    assert execution(
        tool_name="coding_route", args={"action": "start"}, session_id="route-parent",
        next_call=replaced_parent_dispatch,
    ) is None


def test_next_call_result_exception_and_async_route_scope_are_preserved(monkeypatch, home):
    parent = SimpleNamespace(session_id="root-A", service_tier="priority")
    ctx, controller = register(monkeypatch, home, parent)
    execution = next(callback for kind, callback in ctx.middleware if kind == "tool_execution")
    calls = []
    marker = object()
    assert execution(
        tool_name="other", args={}, session_id="root-A",
        next_call=lambda: calls.append(1) or marker,
    ) is marker
    assert calls == [1]

    calls.clear()

    def fail():
        calls.append(1)
        raise LookupError("downstream marker")

    with pytest.raises(LookupError, match="downstream marker"):
        execution(tool_name="coding_route", args={"action": "start"}, session_id="root-A", next_call=fail)
    assert calls == [1]

    async def async_dispatch():
        await asyncio.sleep(0)
        return controller.capture_for_route("root-A", "custom")

    async_result = execution(
        tool_name="coding_route", args={"action": "start"}, session_id="root-A",
        next_call=lambda: async_dispatch(),
    )
    assert asyncio.run(async_result) == snap("priority")
    assert controller.capture_for_route("root-A", "custom") is None


def test_native_ids_bind_multi_child_nested_snapshots_and_retire_exactly(monkeypatch, home):
    parent = SimpleNamespace(session_id="root-A", service_tier="priority")
    ctx, controller = register(monkeypatch, home, parent)
    assert controller is not None
    execute = next(cb for kind, cb in ctx.middleware if kind == "tool_execution")
    start = ctx.hooks["subagent_start"][0]
    stop = ctx.hooks["subagent_stop"][0]

    def dispatch():
        start(parent_session_id="root-A", child_session_id="child-A", child_subagent_id="native-A", child_goal="private")
        start(parent_session_id="root-A", child_session_id="child-B", child_subagent_id="native-B", child_goal="private")
        return "queued"

    assert execute(tool_name="delegate_task", args={}, session_id="root-A", next_call=dispatch) == "queued"
    llm = next(cb for kind, cb in ctx.middleware if kind == "llm_request")

    def apply(session_id):
        monkeypatch.setattr(fi, "_get_active_parent", lambda: SimpleNamespace(session_id=session_id, service_tier=None))
        request = {"model": "gpt-6-astra", "messages": [], "service_tier": "stale"}
        result = llm(request=request, session_id=session_id, model="gpt-6-astra", provider="openai-api",
                     base_url="https://api.openai.com/v1", api_mode="chat_completions")
        return result["request"] if result is not None else None

    first = apply("child-A")
    second = apply("child-B")
    assert first["service_tier"] == second["service_tier"] == "priority"

    child_parent = SimpleNamespace(session_id="child-A", service_tier=None)
    monkeypatch.setattr(fi, "_get_active_parent", lambda: child_parent)
    nested = execute(
        tool_name="delegate_task", args={"action": "spawn"}, session_id="child-A",
        next_call=lambda: start(parent_session_id="child-A", child_session_id="grandchild-A", child_subagent_id="native-grandchild"),
    )
    assert nested is None
    grandchild = apply("grandchild-A")
    assert grandchild["service_tier"] == "priority"

    stop(parent_session_id="root-A", child_session_id="child-A")
    assert apply("child-A") is None
    assert apply("child-B")["service_tier"] == "priority"
    stop(parent_session_id="foreign-parent", child_session_id="child-B")
    assert apply("child-B")["service_tier"] == "priority"
    stop(parent_session_id="root-A", child_session_id="child-B")
    stop(parent_session_id="child-A", child_session_id="grandchild-A")


def test_native_explicit_normal_cleans_stale_tiers_but_unavailable_is_inert(monkeypatch, home):
    parent = SimpleNamespace(session_id="normal-parent", service_tier=None)
    ctx, controller = register(monkeypatch, home, parent)
    execute = next(cb for kind, cb in ctx.middleware if kind == "tool_execution")
    start = ctx.hooks["subagent_start"][0]
    llm = next(cb for kind, cb in ctx.middleware if kind == "llm_request")
    request = {"model": "gpt-6-astra", "service_tier": "stale", "speed": "fast",
               "extra_body": {"service_tier": "stale", "speed": "fast", "keep": True}}
    execute(
        tool_name="delegate_task", args={}, session_id="normal-parent",
        next_call=lambda: start(parent_session_id="normal-parent", child_session_id="normal-child",
                                child_subagent_id="normal-native-id"),
    )
    normal_child = SimpleNamespace(session_id="normal-child", service_tier=None)
    monkeypatch.setattr(fi, "_get_active_parent", lambda: normal_child)
    normal = llm(request=request, session_id="normal-child", model="gpt-6-astra", provider="openai-api",
                 base_url="https://api.openai.com/v1", api_mode="chat_completions")
    assert "service_tier" not in normal["request"] and "speed" not in normal["request"]
    assert normal["request"]["extra_body"] == {"keep": True}

    stop = ctx.hooks["subagent_stop"][0]
    stop(parent_session_id="normal-parent", child_session_id="normal-child")
    unavailable_parent = SimpleNamespace(session_id="unavailable-parent")
    monkeypatch.setattr(fi, "_get_active_parent", lambda: unavailable_parent)
    execute(
        tool_name="delegate_task", args={}, session_id="unavailable-parent",
        next_call=lambda: start(parent_session_id="unavailable-parent", child_session_id="unknown-child",
                                child_subagent_id="unknown-native-id"),
    )
    unknown_child = SimpleNamespace(session_id="unknown-child", service_tier=None)
    monkeypatch.setattr(fi, "_get_active_parent", lambda: unknown_child)
    unavailable = llm(request=request, session_id="unknown-child", model="gpt-6-astra", provider="openai-api",
                      base_url="https://api.openai.com/v1", api_mode="chat_completions")
    assert unavailable is None
    assert request["service_tier"] == "stale" and request["extra_body"]["speed"] == "fast"


def test_routed_contextvar_binds_only_exact_session_home_and_actual_module(monkeypatch, home):
    parent = SimpleNamespace(session_id="root-A", service_tier="priority")
    ctx, controller = register(monkeypatch, home, parent)
    llm = next(cb for kind, cb in ctx.middleware if kind == "llm_request")
    request = {"model": "gpt-6-astra", "messages": [], "service_tier": "stale"}

    with pytest.raises(ValueError):
        with fi.bind_routed_fast_snapshot({"schema": True}, session_id="route-child", home=home):
            pass
    with pytest.raises(ValueError):
        with fi.bind_routed_fast_snapshot(snap("priority"), session_id="route-child", home=home.parent):
            pass

    routed_child = SimpleNamespace(session_id="route-child", service_tier=None)
    monkeypatch.setattr(fi, "_get_active_parent", lambda: routed_child)
    with fi.bind_routed_fast_snapshot(snap("priority"), session_id="route-child", home=home):
        result = llm(request=request, session_id="route-child", model="gpt-6-astra", provider="openai-api",
                     base_url="https://api.openai.com/v1", api_mode="chat_completions")
        assert result["request"]["service_tier"] == "priority"

        execution = next(cb for kind, cb in ctx.middleware if kind == "tool_execution")
        start = ctx.hooks["subagent_start"][0]
        stop = ctx.hooks["subagent_stop"][0]
        execution(
            tool_name="delegate_task", args={}, session_id="route-child",
            next_call=lambda: start(parent_session_id="route-child", child_session_id="route-native-child",
                                    child_subagent_id="route-native-id"),
        )
        nested_parent = SimpleNamespace(session_id="route-native-child", service_tier=None)
        monkeypatch.setattr(fi, "_get_active_parent", lambda: nested_parent)
        nested_request = llm(request=request, session_id="route-native-child", model="gpt-6-astra",
                             provider="openai-api", base_url="https://api.openai.com/v1",
                             api_mode="chat_completions")
        assert nested_request["request"]["service_tier"] == "priority"
        stop(parent_session_id="route-child", child_session_id="route-native-child")
        monkeypatch.setattr(fi, "_get_active_parent", lambda: routed_child)

        foreign = llm(request=request, session_id="other-child", model="gpt-6-astra", provider="openai-api",
                      base_url="https://api.openai.com/v1", api_mode="chat_completions")
        assert foreign is None
        auxiliary = llm(request=request, session_id="route-child", model="gpt-6-astra", provider="openai-api",
                        base_url="https://api.openai.com/v1", api_mode="chat_completions", aux_task="title_generation")
        assert auxiliary is None

    with fi.bind_routed_fast_snapshot(snap("priority"), session_id="route-child", home=home):
        monkeypatch.setattr(fi, "_get_hermes_home", lambda: home.parent)
        foreign_home = llm(request=request, session_id="route-child", model="gpt-6-astra", provider="openai-api",
                           base_url="https://api.openai.com/v1", api_mode="chat_completions")
        assert foreign_home is None


def test_registration_failure_unload_and_bounded_child_state(monkeypatch, home):
    parent = SimpleNamespace(session_id="root-A", service_tier="priority")
    failed_ctx, failed = register(monkeypatch, home, parent, fail_at=("hook", "subagent_stop"))
    assert failed is None
    assert failed_ctx.middleware == [] and not any(failed_ctx.hooks.values()) and failed_ctx.unload == []

    ctx, controller = register(monkeypatch, home, parent)
    assert controller is not None
    start = ctx.hooks["subagent_start"][0]
    now = [100.0]
    monkeypatch.setattr(controller, "_now", lambda: now[0])
    for index in range(fi.MAX_CHILD_BINDINGS + 2):
        start(parent_session_id="root-A", child_session_id=f"child-{index}", child_subagent_id=f"native-{index}")
    assert len(controller._children) <= fi.MAX_CHILD_BINDINGS
    now[0] += fi.BINDING_TTL_SECONDS + 1
    llm = next(cb for kind, cb in ctx.middleware if kind == "llm_request")
    last_child = f"child-{fi.MAX_CHILD_BINDINGS + 1}"
    monkeypatch.setattr(fi, "_get_active_parent", lambda: SimpleNamespace(session_id=last_child, service_tier=None))
    clean = llm(request={"model": "gpt-6-astra", "service_tier": "stale"}, session_id=last_child,
                model="gpt-6-astra", provider="openai-api", base_url="https://api.openai.com/v1",
                api_mode="chat_completions")
    assert clean is None
    assert not controller._children

    ctx.unload[0]()
    assert controller.closed
    assert not controller._children
    assert ctx.middleware == [] and ctx.hooks == {}
