"""Offline contract tests for the ordinary native delegate watchdog."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_router import native_watchdog as nw


class ManualScheduler:
    instances = []

    def __init__(self, callback, interval, context):
        self.callback = callback
        self.interval = interval
        self.context = context
        self.started = False
        self.stopped = False
        type(self).instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def fire(self):
        self.context.copy().run(self.callback)


class FakeContext:
    def __init__(self):
        self.middleware = []
        self.hooks = {}
        self.unload = []

    def register_middleware(self, kind, callback):
        self.middleware.append((kind, callback))
        return _Registration(lambda: self.middleware.remove((kind, callback)))

    def register_hook(self, event, callback):
        self.hooks.setdefault(event, []).append(callback)
        return _Registration(lambda: self.hooks[event].remove(callback))

    def on_unload(self, callback):
        self.unload.append(callback)
        return _Registration(lambda: self.unload.remove(callback))


class _Registration:
    def __init__(self, dispose):
        self._dispose = dispose

    def dispose(self):
        self._dispose()


class NativeHarness:
    def __init__(self, home, *, parent=None, now=100.0, total=60.0):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.home = self.home.resolve()
        self.parent = parent or SimpleNamespace(session_id="parent-A")
        self.now = [now]
        self.total = total
        self.children = {}
        self.calls = []
        self.list_count = 0
        self.list_hook = None
        self.stop_result = None
        self.scheduler_factory = ManualScheduler

        def control(*, action, parent_agent, subagent_id=None):
            self.calls.append((action, parent_agent, subagent_id))
            assert parent_agent is self.parent
            if action == "list":
                self.list_count += 1
                if self.list_hook:
                    self.list_hook(self)
                entries = list(self.children.values())
                return json.dumps({"action": "list", "count": len(entries), "subagents": entries})
            assert action == "stop"
            if self.stop_result is not None:
                return self.stop_result
            if subagent_id not in self.children:
                return json.dumps({"error": "finished or unknown"})
            return json.dumps({"action": "stop", "subagent_id": subagent_id,
                               "status": "interrupt_requested"})

        self.control = control
        self.watchdog = nw.NativeWatchdog(
            self.home,
            self.total,
            get_hermes_home=lambda: self.home,
            get_active_parent=lambda: self.parent,
            delegate_task=self.control,
            monotonic=lambda: self.now[0],
            wall_clock=lambda: self.now[0] + 1_000.0,
            scheduler_factory=self.scheduler_factory,
        )

    def spawn(self, children, *, session_id=None, result="spawned"):
        args = {"goal": "PRIVATE_PROMPT_MUST_NOT_BE_STORED"}
        calls = []

        def next_call(*forwarded):
            calls.append(forwarded)
            for sid, child_session in children:
                self.watchdog.on_subagent_start(
                    parent_session_id=self.parent.session_id,
                    child_session_id=child_session,
                    child_subagent_id=sid,
                    child_goal="PRIVATE_PROMPT_MUST_NOT_BE_STORED",
                )
            return result

        returned = self.watchdog.middleware(
            tool_name="delegate_task", args=args, original_args=args,
            session_id=session_id or self.parent.session_id, next_call=next_call,
        )
        assert calls == [()]
        return returned

    def add_native(self, sid, running_seconds, *, status="running"):
        self.children[sid] = {"subagent_id": sid, "status": status,
                              "running_seconds": running_seconds}


@pytest.fixture(autouse=True)
def reset_schedulers():
    ManualScheduler.instances.clear()
    yield
    ManualScheduler.instances.clear()


def test_zero_limit_registers_dormant_observer_and_does_not_start_a_watcher(tmp_path):
    ctx = FakeContext()
    result = nw.register_native_watchdog(
        ctx, tmp_path,
        read_timeouts_fn=lambda home: {"delegate_total_seconds": 0},
        get_hermes_home_fn=lambda: tmp_path,
        get_active_parent_fn=lambda: None,
        delegate_task_fn=lambda **kwargs: None,
        scheduler_factory=ManualScheduler,
    )
    assert result is not None
    assert [kind for kind, _callback in ctx.middleware] == ["tool_execution"]
    assert set(ctx.hooks) == {"subagent_start", "subagent_stop"}
    assert len(ctx.unload) == 1
    assert ManualScheduler.instances == []


def test_registration_uses_public_hook_and_middleware_apis_with_profile_limit(tmp_path):
    ctx = FakeContext()
    home = tmp_path.resolve()
    watch = nw.register_native_watchdog(
        ctx, home,
        read_timeouts_fn=lambda seen_home: (
            {"delegate_total_seconds": 73} if Path(seen_home) == home else {}
        ),
        get_hermes_home_fn=lambda: home,
        get_active_parent_fn=lambda: None,
        delegate_task_fn=lambda **kwargs: None,
        scheduler_factory=ManualScheduler,
    )
    assert watch is not None
    assert watch.total_seconds == 73
    assert [kind for kind, _callback in ctx.middleware] == ["tool_execution"]
    assert set(ctx.hooks) == {"subagent_start", "subagent_stop"}
    assert len(ctx.unload) == 1
    ctx.unload[0]()
    assert watch.closed
    assert ManualScheduler.instances == []


def test_real_hermes_plugin_context_dispatches_registered_watchdog_hooks(tmp_path, monkeypatch):
    core = Path("C:/Users/ovpow/AppData/Local/hermes/hermes-agent")
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(core))
    pytest.importorskip("ruamel.yaml", reason="Hermes core plugin manager requires its installed YAML dependency")
    from hermes_cli import middleware, plugins
    from hermes_cli.plugins_manifest import parse_manifest_file

    home = tmp_path.resolve()
    manager = plugins.PluginManager(scope_key=str(home))
    manifest = parse_manifest_file(root / "plugin.yaml", root, "user", "")
    assert manifest is not None
    ctx = plugins.PluginContext(manifest, manager)
    parent = SimpleNamespace(session_id="actual-parent")
    watch = nw.register_native_watchdog(
        ctx, home,
        read_timeouts_fn=lambda _home: {"delegate_total_seconds": 30},
        get_hermes_home_fn=lambda: home,
        get_active_parent_fn=lambda: parent,
        delegate_task_fn=lambda **kwargs: None,
        scheduler_factory=ManualScheduler,
    )
    assert watch is not None
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)
    args = {}

    def native_dispatch(received):
        assert received is args
        manager.invoke_hook(
            "subagent_start", parent_session_id="actual-parent",
            child_session_id="actual-child", child_subagent_id="sa-actual",
        )
        return "native-result"

    try:
        assert middleware.run_tool_execution_middleware(
            "delegate_task", args, native_dispatch, session_id="actual-parent",
        ) == "native-result"
        assert "sa-actual" in watch.children
        assert len(manager._hooks["subagent_start"]) == 1
        assert len(manager._middleware["tool_execution"]) == 1
    finally:
        manager.unload("model-router")
    assert watch.closed
    assert not manager._hooks.get("subagent_start")
    assert not manager._middleware.get("tool_execution")


def test_non_delegate_and_control_actions_forward_once_without_mutation(tmp_path):
    h = NativeHarness(tmp_path)
    args = {"action": "list", "sentinel": object()}
    for tool_name, value in (("read_file", {}), ("delegate_task", args)):
        calls = []
        result = h.watchdog.middleware(
            tool_name=tool_name, args=value, original_args=value,
            session_id="parent-A", next_call=lambda *passed: calls.append(passed) or "native-result",
        )
        assert result == "native-result"
        assert calls == [()]
    for action in ("list", "steer", "stop"):
        control_args = {"action": action, "subagent_id": "child-A"}
        calls = []
        h.watchdog.middleware(
            tool_name="delegate_task", args=control_args, session_id="parent-A",
            next_call=lambda *passed: calls.append(passed) or "control-result",
        )
        assert calls == [()]
    assert h.watchdog.children == {}
    assert h.calls == []


def test_passthrough_or_spawn_exception_is_never_retried(tmp_path):
    h = NativeHarness(tmp_path)
    cases = [
        ("read_file", {}, "parent-A"),
        ("delegate_task", {"action": "list"}, "parent-A"),
        ("delegate_task", {}, "foreign-parent"),
    ]
    for tool_name, args, session_id in cases:
        calls = []

        def fail_once():
            calls.append("called")
            raise RuntimeError("native call failed")

        with pytest.raises(RuntimeError, match="native call failed"):
            h.watchdog.middleware(
                tool_name=tool_name, args=args, session_id=session_id, next_call=fail_once,
            )
        assert calls == ["called"]

    spawn_calls = []

    def fail_after_hook():
        spawn_calls.append("called")
        h.watchdog.on_subagent_start(
            parent_session_id="parent-A", child_session_id="child-fail",
            child_subagent_id="sa-fail", child_goal="SECRET",
        )
        raise RuntimeError("native spawn failed")

    with pytest.raises(RuntimeError, match="native spawn failed"):
        h.watchdog.middleware(
            tool_name="delegate_task", args={}, session_id="parent-A", next_call=fail_after_hook,
        )
    assert spawn_calls == ["called"]
    # The ContextVar binding was reset even when downstream native execution raised.
    h.watchdog.on_subagent_start(
        parent_session_id="parent-A", child_session_id="orphan", child_subagent_id="sa-orphan",
    )
    assert set(h.watchdog.children) == {"sa-fail"}


@pytest.mark.parametrize("result", ['{"error":"preflight refused"}', '{"results":[]}'])
def test_terminal_native_result_retires_unregistered_build_without_stopping_it(tmp_path, result):
    h = NativeHarness(tmp_path)
    assert h.spawn([("sa-short", "child-short")], result=result) == result
    assert not h.watchdog.children
    assert not h.calls
    assert ManualScheduler.instances[0].stopped


def test_profile_and_exact_parent_session_are_required_before_binding(tmp_path):
    h = NativeHarness(tmp_path)
    h.watchdog.get_hermes_home = lambda: tmp_path.parent
    h.spawn([("sa-foreign-profile", "child-session")])
    assert not h.watchdog.children
    h.watchdog.get_hermes_home = lambda: h.home
    h.spawn([("sa-wrong-session", "child-session")], session_id="another-parent")
    assert not h.watchdog.children
    # The hook itself also checks the parent and profile rather than trusting IDs alone.
    calls = []
    h.watchdog.middleware(
        tool_name="delegate_task", args={}, session_id="parent-A",
        next_call=lambda: h.watchdog.on_subagent_start(
            parent_session_id="parent-other", child_session_id="child-X",
            child_subagent_id="sa-X", child_goal="SECRET",
        ),
    )
    assert not h.watchdog.children
    assert calls == []


def test_queued_child_gets_no_clock_until_first_owned_list_registration(tmp_path):
    h = NativeHarness(tmp_path, now=100, total=120)
    h.spawn([("sa-queued", "child-queued")])
    scheduler, = ManualScheduler.instances
    assert scheduler.started
    assert h.watchdog.children["sa-queued"].deadline is None
    scheduler.fire()  # child is built but still queued; not in native owned list
    assert h.watchdog.children["sa-queued"].deadline is None
    assert not h.watchdog.children["sa-queued"].registered
    assert not [call for call in h.calls if call[0] == "stop"]

    h.now[0] = 180
    h.add_native("sa-queued", 40.0)
    scheduler.fire()
    child = h.watchdog.children["sa-queued"]
    assert child.registered
    assert child.first_running_seconds == 40.0
    assert child.deadline == pytest.approx(260.0)


def test_async_spawn_remains_tracked_after_next_call_returns_and_uses_fixed_deadline(tmp_path):
    h = NativeHarness(tmp_path, now=1_000, total=100)
    assert h.spawn([("sa-async", "child-async")]) == "spawned"
    child = h.watchdog.children["sa-async"]
    assert child.scope_closed
    h.add_native("sa-async", 30.0)
    h.watchdog.poll_once()
    assert child.deadline == pytest.approx(1_070.0)
    # Progress/list reads advance elapsed time but never move the original deadline.
    h.now[0] = 1_020
    h.children["sa-async"]["running_seconds"] = 50.0
    h.watchdog.poll_once()
    assert child.deadline == pytest.approx(1_070.0)
    assert not [call for call in h.calls if call[0] == "stop"]
    h.now[0] = 1_070
    h.watchdog.poll_once()
    assert [call[0] for call in h.calls].count("stop") == 1
    assert h.calls[-1] == ("stop", h.parent, "sa-async")
    assert child.stop_attempted
    assert child.stop_outcome == "accepted"
    # The accepted native interrupt request is not fabricated as termination.
    assert "sa-async" in h.watchdog.children
    h.watchdog.poll_once()
    assert [call[0] for call in h.calls].count("stop") == 1


def test_synchronous_child_can_be_stopped_while_native_delegate_call_is_active(tmp_path):
    h = NativeHarness(tmp_path, now=10, total=30)
    calls = []

    def native_call():
        calls.append("entered")
        h.watchdog.on_subagent_start(
            parent_session_id="parent-A", child_session_id="child-sync",
            child_subagent_id="sa-sync", child_goal="SECRET",
        )
        h.add_native("sa-sync", 30.0)
        h.watchdog.poll_once()
        return "synchronous-result"

    result = h.watchdog.middleware(
        tool_name="delegate_task", args={}, session_id="parent-A", next_call=native_call,
    )
    assert result == "synchronous-result"
    assert calls == ["entered"]
    assert [call[2] for call in h.calls if call[0] == "stop"] == ["sa-sync"]
    assert h.watchdog.children["sa-sync"].scope_closed


def test_batch_children_have_independent_deadlines_and_only_expired_child_is_stopped(tmp_path):
    h = NativeHarness(tmp_path, now=50, total=60)
    h.spawn([("sa-young", "child-young"), ("sa-old", "child-old")])
    h.add_native("sa-young", 5.0)
    h.add_native("sa-old", 55.0)
    h.watchdog.poll_once()
    young = h.watchdog.children["sa-young"]
    old = h.watchdog.children["sa-old"]
    assert young.deadline == pytest.approx(105.0)
    assert old.deadline == pytest.approx(55.0)
    h.now[0] = 55
    h.watchdog.poll_once()
    assert [call[2] for call in h.calls if call[0] == "stop"] == ["sa-old"]
    assert not young.stop_attempted


def test_long_finite_limit_is_not_arbitrarily_capped(tmp_path):
    h = NativeHarness(tmp_path, now=10, total=10_000_000)
    h.spawn([("sa-long", "child-long")])
    h.add_native("sa-long", 1.0)
    h.watchdog.poll_once()
    assert h.watchdog.children["sa-long"].deadline == pytest.approx(10 + 9_999_999)
    assert not [call for call in h.calls if call[0] == "stop"]


def test_completion_cleanup_requires_exact_child_session_and_parent(tmp_path):
    h = NativeHarness(tmp_path)
    h.spawn([("sa-one", "child-one"), ("sa-two", "child-two")])
    h.watchdog.on_subagent_stop(parent_session_id="parent-A", child_session_id="child-other")
    assert set(h.watchdog.children) == {"sa-one", "sa-two"}
    h.watchdog.on_subagent_stop(parent_session_id="foreign-parent", child_session_id="child-one")
    assert set(h.watchdog.children) == {"sa-one", "sa-two"}
    h.watchdog.on_subagent_stop(parent_session_id="parent-A", child_session_id="child-one")
    assert set(h.watchdog.children) == {"sa-two"}


def test_registered_but_missing_child_is_reconciled_but_queued_child_is_retained(tmp_path):
    h = NativeHarness(tmp_path)
    h.spawn([("sa-registered", "child-r"), ("sa-queued", "child-q")])
    h.add_native("sa-registered", 1.0)
    h.watchdog.poll_once()
    del h.children["sa-registered"]
    h.watchdog.poll_once()
    assert "sa-registered" not in h.watchdog.children
    assert "sa-queued" in h.watchdog.children
    assert not [call for call in h.calls if call[0] == "stop"]


def test_control_errors_and_malformed_owned_list_fail_closed(tmp_path):
    h = NativeHarness(tmp_path)
    h.spawn([("sa-error", "child-error")])
    h.add_native("sa-error", 0)
    child = h.watchdog.children["sa-error"]
    h.stop_result = "not-json"
    h.watchdog.poll_once()
    # First read is valid, revalidation read remains valid; malformed stop response is ambiguous.
    h.now[0] = 160
    h.watchdog.poll_once()
    assert child.stop_attempted
    assert child.stop_outcome == "unknown"
    assert "sa-error" in h.watchdog.children
    assert [call[0] for call in h.calls].count("stop") == 1

    other = NativeHarness(tmp_path / "other")
    other.spawn([("sa-list-error", "child-list-error")])
    other.add_native("sa-list-error", 100)
    original = other.control
    other.control = lambda **kwargs: "not-json" if kwargs["action"] == "list" else original(**kwargs)
    other.watchdog.delegate_task = other.control
    other.watchdog.poll_once()
    assert other.watchdog.children["sa-list-error"].deadline is None
    assert not [call for call in other.calls if call[0] == "stop"]


def test_finish_race_on_revalidation_does_not_issue_or_claim_stop(tmp_path):
    h = NativeHarness(tmp_path, now=5, total=10)
    h.spawn([("sa-race", "child-race")])
    h.add_native("sa-race", 10.0)
    # The second owned-list read is the mandatory revalidation immediately before stop.
    h.list_hook = lambda harness: harness.children.clear() if harness.list_count == 2 else None
    h.watchdog.poll_once()  # first list binds an immediate deadline; second proves the race
    child = h.watchdog.children.get("sa-race")
    assert not [call for call in h.calls if call[0] == "stop"]
    assert "sa-race" not in h.watchdog.children
    assert child is None or not child.stop_attempted


def test_nonrunning_race_is_not_treated_as_stop_success(tmp_path):
    h = NativeHarness(tmp_path, now=1, total=5)
    h.spawn([("sa-finishing", "child-finishing")])
    h.add_native("sa-finishing", 5.0, status="finishing")
    h.watchdog.poll_once()
    child = h.watchdog.children["sa-finishing"]
    assert child.registered
    assert child.deadline == pytest.approx(1.0)
    assert not child.stop_attempted
    assert not [call for call in h.calls if call[0] == "stop"]


def test_stop_evidence_is_bounded_private_and_contains_no_goal_or_prompt(tmp_path):
    h = NativeHarness(tmp_path, now=20, total=1)
    h.spawn([("sa-evidence", "child-evidence")])
    h.add_native("sa-evidence", 2.0)
    h.watchdog.poll_once()
    h.watchdog.poll_once()
    evidence = h.home / "plugin-data" / "model-router" / "native-watchdog.jsonl"
    rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "native_total_timeout_stop"
    assert row["request_outcome"] == "accepted"
    assert row["parent_session_id"] == "parent-A"
    assert row["child_session_id"] == "child-evidence"
    assert row["child_subagent_id"] == "sa-evidence"
    assert "PRIVATE_PROMPT" not in evidence.read_text(encoding="utf-8")

    for index in range(nw.MAX_EVIDENCE_RECORDS + 10):
        h.watchdog._write_evidence({
            "kind": "native_total_timeout_stop", "parent_session_id": "p",
            "child_session_id": f"c{index}", "child_subagent_id": f"sa{index}",
            "request_outcome": "unknown", "timestamp": 0,
            "total_seconds": 1, "running_seconds": 2,
        })
    lines = evidence.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= nw.MAX_EVIDENCE_RECORDS
    assert evidence.stat().st_size <= nw.MAX_EVIDENCE_BYTES
    assert "PRIVATE_PROMPT" not in evidence.read_text(encoding="utf-8")


def test_scheduler_releases_dispatch_and_stops_when_last_child_finishes(tmp_path):
    h = NativeHarness(tmp_path)
    h.spawn([("sa-idle", "child-idle")])
    scheduler, = ManualScheduler.instances
    assert scheduler.context.copy().run(nw._ACTIVE_DISPATCH.get) is None
    h.watchdog.on_subagent_stop(parent_session_id="parent-A", child_session_id="child-idle")
    assert scheduler.stopped and h.watchdog._scheduler is None
    h.spawn([("sa-next", "child-next")])
    assert len(ManualScheduler.instances) == 2
    assert ManualScheduler.instances[1].started


def test_parent_session_rotation_does_not_disable_owned_child_limit(tmp_path):
    h = NativeHarness(tmp_path, total=1)
    h.spawn([("sa-rotation", "child-rotation")])
    h.add_native("sa-rotation", 1)
    h.parent.session_id = "parent-rotated-on-compression"
    h.watchdog.poll_once()
    assert [call[2] for call in h.calls if call[0] == "stop"] == ["sa-rotation"]
    assert h.watchdog.children["sa-rotation"].parent_session_id == "parent-A"


def test_replaced_parent_object_never_controls_original_child(tmp_path):
    h = NativeHarness(tmp_path, total=1)
    h.spawn([("sa-owner", "child-owner")])
    h.add_native("sa-owner", 1)
    h.watchdog.get_active_parent = lambda: SimpleNamespace(session_id="parent-A")
    h.watchdog.poll_once()
    assert not h.calls


def test_unload_stops_only_the_monitor_and_does_not_stop_native_children(tmp_path):
    h = NativeHarness(tmp_path)
    h.spawn([("sa-unload", "child-unload")])
    h.add_native("sa-unload", 1.0)
    scheduler, = ManualScheduler.instances
    h.watchdog.close()
    assert scheduler.stopped
    assert "sa-unload" in h.children  # native child remains untouched
    assert not h.watchdog.children
    assert not [call for call in h.calls if call[0] == "stop"]
    scheduler.fire()
    assert not [call for call in h.calls if call[0] == "stop"]


def test_native_control_errors_do_not_break_original_tool_execution(tmp_path):
    h = NativeHarness(tmp_path)
    h.watchdog.delegate_task = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("control failed"))
    calls = []

    def next_call():
        calls.append("called")
        h.watchdog.on_subagent_start(
            parent_session_id="parent-A", child_session_id="child-A",
            child_subagent_id="sa-control-error", child_goal="SECRET",
        )
        return "native result"

    assert h.watchdog.middleware(
        tool_name="delegate_task", args={}, session_id="parent-A", next_call=next_call,
    ) == "native result"
    assert calls == ["called"]
    h.watchdog.poll_once()
    assert "sa-control-error" in h.watchdog.children


def test_invalid_timeout_values_preserve_original_call_without_starting_watcher(tmp_path):
    for invalid in (True, -1, float("nan"), float("inf"), "60"):
        ctx = FakeContext()
        result = nw.register_native_watchdog(
            ctx, tmp_path,
            read_timeouts_fn=lambda _home, value=invalid: {"delegate_total_seconds": value},
            get_hermes_home_fn=lambda: tmp_path,
            get_active_parent_fn=lambda: None,
            delegate_task_fn=lambda **kwargs: None,
            scheduler_factory=ManualScheduler,
        )
        assert result is not None
        calls = []
        result.middleware(tool_name="delegate_task", args={}, session_id="parent-A", next_call=lambda: calls.append(1))
        assert calls == [1]
        assert not result.children and not ManualScheduler.instances


def test_new_dispatch_reads_saved_policy_but_never_retimes_existing_children(tmp_path):
    h = NativeHarness(tmp_path, now=0, total=1)
    settings = {"delegate_total_seconds": 0}
    h.watchdog.read_timeouts_fn = lambda _home: dict(settings)
    h.spawn([("sa-disabled", "child-disabled")])
    assert not h.watchdog.children and not ManualScheduler.instances
    settings["delegate_total_seconds"] = 10
    h.spawn([("sa-first", "child-first")])
    h.add_native("sa-first", 0)
    h.watchdog.poll_once()
    assert h.watchdog.children["sa-first"].deadline == 10
    h.now[0] = 2
    settings["delegate_total_seconds"] = 40
    h.spawn([("sa-second", "child-second")])
    h.add_native("sa-second", 0)
    h.watchdog.poll_once()
    assert h.watchdog.children["sa-first"].total_seconds == 10
    assert h.watchdog.children["sa-second"].deadline == 42
    settings["delegate_total_seconds"] = 0
    h.spawn([("sa-disabled-later", "child-disabled-later")])
    assert "sa-disabled-later" not in h.watchdog.children
    h.now[0] = 10
    h.watchdog.poll_once()
    assert [call[2] for call in h.calls if call[0] == "stop"] == ["sa-first"]
