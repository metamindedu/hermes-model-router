"""Fixed CLI worker protocol, isolated output and cleanup contracts."""
import io
import json
from pathlib import Path
import runpy

import pytest

from model_router import config_writer
from model_router.service import Service, ServiceError
from test_integration import make_home


def test_batch_reuses_exact_profile_worker_and_closes_on_failure(tmp_path, monkeypatch):
    created = []
    class Worker:
        def __init__(self, env):
            self.env, self.keys, self.closed = env, [], False
            created.append(self)
        def set(self, key, value):
            self.keys.append(key)
            if key == "model.default":
                raise config_writer.ConfigWriterError("unknown result")
        def close(self):
            self.closed = True
    monkeypatch.setattr(config_writer, "ConfigWriter", Worker)
    service = Service(make_home(tmp_path))
    with pytest.raises(ServiceError):
        with service._batch_writes():
            service._write_key("default", "model.provider", "openai-codex")
            service._write_key("default", "model.default", "test-main")
    assert len(created) == 1
    assert created[0].closed
    assert created[0].keys == ["model.provider", "model.default"]
    assert created[0].env["HERMES_HOME"] == str(service.root)
    assert service._config_workers is None


def test_worker_uses_native_config_dispatcher_and_never_forwards_its_output(monkeypatch, capsys):
    from hermes_cli import config
    seen = []
    def dispatch(args):
        seen.append(vars(args))
        print("SECRET_TEST_CANARY old endpoint warning")
    monkeypatch.setattr(config, "config_command", dispatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"key": "model.default", "value": "test-main"}) + "\n"))
    assert config_writer.main() == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"ok": True}
    assert "SECRET_TEST_CANARY" not in output
    assert seen == [{"config_command": "set", "key": "model.default", "value": "test-main", "force": True}]


def test_worker_rejects_unknown_key_and_catches_native_cli_refusal(monkeypatch, capsys):
    from hermes_cli import config
    seen = []
    def refuse(args):
        seen.append(args.key)
        raise SystemExit(2)
    monkeypatch.setattr(config, "config_command", refuse)
    requests = [{"key": "api_key", "value": "not-allowed"}, {"key": "fallback_providers", "value": []}]
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(json.dumps(x) + "\n" for x in requests)))
    assert config_writer.main() == 0
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [{"ok": False}, {"ok": False}]
    assert seen == ["fallback_providers"]


def test_import_stall_and_full_pipe_are_bounded_and_child_is_reaped(tmp_path):
    import os
    import time
    package = tmp_path / "hermes_cli"
    package.mkdir()
    (package / "__init__.py").write_text("")
    ready = tmp_path / "ready"
    (package / "config.py").write_text(
        "import time\nfrom pathlib import Path\n"
        + f"Path({str(ready)!r}).write_text('ready')\n"
        + "while True: time.sleep(.05)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    env["HERMES_HOME"] = str(tmp_path)
    env.pop("PYTHONHOME", None)
    worker = config_writer.ConfigWriter(env)
    try:
        until = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < until:
            time.sleep(.01)
        assert ready.exists(), "must reach the deliberately stuck import"
        before = time.monotonic()
        with pytest.raises(config_writer.ConfigWriterError):
            worker.set("model.default", "x" * 65000, timeout=.15)
        assert time.monotonic() - before < 2
        assert worker.process.poll() is not None
        assert worker.reader is None or not worker.reader.is_alive()
    finally:
        assert worker.close()


def test_cleanup_failure_does_not_skip_other_workers_or_hide_receipt(tmp_path, monkeypatch):
    service = Service(make_home(tmp_path))
    calls = []
    class Worker:
        def __init__(self, name, fail=False): self.name, self.fail = name, fail
        def close(self):
            calls.append(self.name)
            if self.fail: raise OSError("synthetic cleanup failure")
            return True
    receipt = {"status": "applied", "revision": 1, "applied": [{"profile": "default", "key": "model.default"}], "remaining": []}
    with service._batch_writes():
        service._config_workers["default"] = Worker("default", True)
        service._config_workers["p0"] = Worker("p0")
        service._store_apply(receipt)
    assert calls == ["default", "p0"]
    assert receipt["status"] == "unknown" and receipt["config_status"] == "applied"
    assert receipt["cleanup_failed_profiles"] == ["default"]
    assert service._recent_apply() == receipt
    assert receipt["applied"] == [{"profile": "default", "key": "model.default"}]


def test_kill_and_wait_failures_are_reported_not_raised():
    import subprocess
    class Process:
        stdin = io.StringIO()
        stdout = io.StringIO()
        def poll(self): return None
        def terminate(self): raise OSError("denied")
        def kill(self): raise OSError("denied")
        def wait(self, timeout): raise subprocess.TimeoutExpired("fake", timeout)
    worker = config_writer.ConfigWriter.__new__(config_writer.ConfigWriter)
    worker.process, worker.reader = Process(), None
    assert worker.close() is False
