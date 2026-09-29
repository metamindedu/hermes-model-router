"""Parent integration regressions missed by isolated worker mocks."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from model_router.service import Service, ServiceError
from model_router.processes import is_process_alive


def make_home(tmp_path):
    root = tmp_path / "hermes"; root.mkdir()
    (root / "config.yaml").write_text(yaml.safe_dump({
        "model": {"provider": "openai-codex", "default": "heavy-test"},
        "agent": {"reasoning_effort": "medium"},
        "delegation": {"provider": "openai-codex", "model": "light-test", "reasoning_effort": "high"},
        "auxiliary": {"compression": {"provider": "openai-codex", "model": "light-test", "reasoning_effort": "low"}, "title_generation": {"provider": "openai-codex", "model": "light-test", "reasoning_effort": "none"}},
        "skills": {"disabled": []},
    }), encoding="utf-8")
    return root


def writer(root):
    def write(profile, key, value):
        p = root / "config.yaml"
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        cursor = data
        parts = key.split(".")
        for part in parts[:-1]: cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return write


def payload(service):
    status = service.status(); row = status["profiles"][0]
    return dict(expected_revision=status["revision"], profile="default", models=copy.deepcopy(row["models"]), model_targets=[], routing=copy.deepcopy(row["routing"]), routing_profiles=["default"])


def test_preview_survives_new_service_instance(tmp_path):
    root = make_home(tmp_path)
    first = Service(root, writer(root)); first.initialize(["default"])
    plan = first.preview(payload(first))
    second = Service(root, writer(root))
    assert second.apply(plan["plan_id"])["status"] == "no_change"
    with pytest.raises(ServiceError, match="consumed"):
        Service(root, writer(root)).apply(plan["plan_id"])


def test_real_yaml_projection_and_disabled_live_guard(tmp_path):
    root = make_home(tmp_path)
    service = Service(root, writer(root)); service.initialize(["default"])
    assert service.status()["profiles"][0]["drift"] == []
    writer(root)("default", "skills.disabled", ["adaptive-coding-orchestration"])
    assert service.routing_config("default")["enabled"] is False
    body = payload(service)
    preview = service.preview(body)
    assert service.apply(preview["plan_id"])["status"] == "applied"
    assert service.routing_config("default")["enabled"] is True


def test_plan_does_not_store_private_endpoint_and_clears_before_provider(tmp_path):
    root = make_home(tmp_path); events = []
    write = writer(root)
    write("default", "model.base_url", "https://secret:password@example.invalid")
    def recording(p,k,v): events.append(k); write(p,k,v)
    service = Service(root, recording); service.initialize(["default"])
    body = payload(service); body["model_targets"] = ["default"]
    body["models"]["main"]["provider"] = "openai-api"
    plan = service.preview(body)
    raw = (root / "plugin-data/model-router/plans" / (plan["plan_id"] + ".json")).read_text()
    assert "secret:password" not in raw
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert events.index("model.base_url") < events.index("model.provider")


def test_windows_pid_probe_does_not_terminate_child():
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert is_process_alive(child.pid)
        assert child.poll() is None
        assert is_process_alive(child.pid)
        assert child.poll() is None
    finally:
        child.terminate(); child.wait(timeout=10)
    assert not is_process_alive(child.pid)


def test_actual_cli_writes_only_isolated_home(tmp_path):
    launcher = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/bin/hermes.exe"
    if not launcher.is_file(): pytest.skip("Windows local Hermes CLI not installed")
    root = make_home(tmp_path)
    other = root / "profiles/claire"; other.mkdir(parents=True)
    original_other = (root / "config.yaml").read_bytes()
    (other / "config.yaml").write_bytes(original_other)
    (root / "active_profile").write_text("claire", encoding="utf-8")
    env = dict(os.environ, HERMES_HOME=str(root)); env.pop("HERMES_PROFILE", None)
    check = subprocess.run([str(launcher), "--profile", "default", "config", "path"], env=env, capture_output=True, text=True, timeout=30)
    assert check.returncode == 0 and str(root).lower() in check.stdout.lower()
    service = Service(root)
    service._cli_path = lambda: str(launcher)
    service.initialize(["default"])
    body = payload(service); body["model_targets"] = ["default"]
    body["models"]["main"]["model"] = "isolated-new-heavy"
    plan = service.preview(body)
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied", receipt
    assert yaml.safe_load((root / "config.yaml").read_text())["model"]["default"] == "isolated-new-heavy"
    assert yaml.safe_load((other / "config.yaml").read_text())["model"]["default"] == "heavy-test"
    assert service.status()["profiles"][0]["drift"] == []
