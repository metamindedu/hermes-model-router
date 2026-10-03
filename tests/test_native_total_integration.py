"""Exercise real native creation, owned registry, middleware and cancellation.

Only the model agent class is an offline workload double. No provider API is
called and no native lifecycle/registry record is manufactured by the plugin.
"""
from __future__ import annotations

import contextvars
import json
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from model_router.native_watchdog import register_native_watchdog
from model_router.timeouts import read_timeouts, timeout_digest, write_timeouts


class Parent:
    model = "offline-model"
    provider = "offline-provider"
    requested_provider = "offline-provider"
    base_url = ""
    api_key = None
    api_mode = "chat_completions"
    enabled_toolsets = []
    disabled_toolsets = []
    request_overrides = {}
    _fallback_chain = []
    _delegate_depth = 0
    _interrupt_requested = False
    session_db = None
    tool_progress_callback = None

    def __init__(self):
        self.session_id = "offline-parent-" + uuid4().hex
        self._active_children = []
        self._active_children_lock = threading.Lock()

    def _touch_activity(self, _description):
        pass


class OfflineChild:
    instances = []

    def __init__(self, **kwargs):
        self.session_id = "offline-child-" + uuid4().hex
        self.model = kwargs["model"]
        self.provider = kwargs["provider"]
        self.base_url = kwargs["base_url"]
        self.api_mode = kwargs["api_mode"]
        self.tool_progress_callback = kwargs.get("tool_progress_callback")
        self._parent_session_id = kwargs.get("parent_session_id")
        self._session_init_model_config = {}
        self._interrupt_requested = False
        self._hard_interrupt_requested = threading.Event()
        self.started = threading.Event()
        self.closed = threading.Event()
        self.stop_requested = threading.Event()
        self.max_iterations = kwargs.get("max_iterations", 5)
        self.session_api_calls = 0
        self.messages = []
        self._credential_pool = None
        type(self).instances.append(self)

    def run_conversation(self, *args, **kwargs):
        self.started.set()
        interrupted = self.stop_requested.wait(8)
        return {"completed": not interrupted, "interrupted": interrupted,
                "final_response": "offline task interrupted" if interrupted else "offline task finished",
                "messages": []}

    def interrupt(self, *args, **kwargs):
        self._interrupt_requested = True
        self._hard_interrupt_requested.set()
        self.stop_requested.set()

    def get_activity_summary(self):
        return {"api_call_count": 0, "current_tool": None, "last_activity_ts": time.time(), "max_iterations": 5}

    def close(self):
        self.closed.set()


@pytest.mark.parametrize("background", [False, True])
def test_real_native_child_obeys_plugin_total_after_zero_to_positive_save(tmp_path, monkeypatch, background):
    import run_agent
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli import middleware, plugins, lifecycle
    from hermes_cli.plugins_manifest import parse_manifest_file
    from tools import delegate_tool as native

    home = tmp_path.resolve()
    (home / "config.yaml").write_text("delegation:\n  child_timeout_seconds: 0\n  max_iterations: 5\n", encoding="utf-8")
    token = set_hermes_home_override(str(home))
    parent = Parent()
    manager = plugins.PluginManager(scope_key=str(home))
    source = Path(__file__).resolve().parents[1]
    manifest = parse_manifest_file(source / "plugin.yaml", source, "user", "")
    ctx = plugins.PluginContext(manifest, manager)
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)
    monkeypatch.setattr(run_agent, "AIAgent", OfflineChild)
    monkeypatch.setattr(native, "_load_config", lambda: {"child_timeout_seconds": 0, "max_iterations": 5, "max_concurrent_children": 2})
    OfflineChild.instances.clear()
    before = (home / "config.yaml").read_bytes()
    try:
        # Native whole runtime starts disabled at registration, then the saved
        # profile value becomes effective on NEW dispatch without a reload.
        watchdog = register_native_watchdog(ctx, home)
        assert watchdog is not None
        evidence_published = threading.Event()
        actual_write_evidence = watchdog._write_evidence
        def publish_evidence(value):
            written = actual_write_evidence(value)
            if written:
                evidence_published.set()
            return written
        monkeypatch.setattr(watchdog, "_write_evidence", publish_evidence)
        write_timeouts(home, {"delegate_total_seconds": .15, "routed_total_seconds": 7200},
                       expected_digest=timeout_digest(home), expected_revision=0)
        assert read_timeouts(home)["routed_total_seconds"] == 7200
        args = {"goal": "Offline cancellation fixture only", "background": background}
        with bind_subagent_parent(parent):
            value = middleware.run_tool_execution_middleware(
                "delegate_task", args,
                lambda payload: native.delegate_task(**payload, parent_agent=parent),
                session_id=parent.session_id,
            )
        assert OfflineChild.instances, value
        child = OfflineChild.instances[0]
        assert child.started.wait(2)
        assert child.stop_requested.wait(4), "real native owned child was not interrupted"
        assert child.closed.wait(4), "native cleanup did not settle"
        assert evidence_published.wait(2), "timeout cause was not durably published"
        evidence = home / "plugin-data/model-router/native-watchdog.jsonl"
        rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
        assert rows[-1]["request_outcome"] == "accepted"
        assert rows[-1]["child_subagent_id"] == child._subagent_id
        assert rows[-1]["parent_session_id"] == parent.session_id
        assert (home / "config.yaml").read_bytes() == before
        if background:
            assert json.loads(value)["status"] == "dispatched"
        else:
            results = json.loads(value)["results"]
            assert results[0]["status"] == "interrupted", value
        # Read back exact native registry through its public owned control plane.
        remaining = json.loads(native.delegate_task(action="list", parent_agent=parent))
        assert not any(row["subagent_id"] == child._subagent_id for row in remaining["subagents"])
    finally:
        manager.unload("model-router")
        for child in OfflineChild.instances:
            child.interrupt()
            child.closed.wait(4)
        reset_hermes_home_override(token)
