from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_router import service as service_module
from model_router.service import MODEL_KEYS, SKILL_NAME, RevisionConflict, Service, ServiceError


def route(provider: str, model: str, reasoning: str = "medium") -> dict[str, str]:
    return {"provider": provider, "model": model, "reasoning": reasoning}


def make_models(suffix: str = "") -> dict[str, dict[str, str]]:
    return {
        "main": route("openai-codex", f"heavy{suffix}", "high"),
        "delegation": route("deepseek", f"light{suffix}", "low"),
        "compression": route("openai-codex", f"heavy{suffix}", "high"),
        "title": route("openai-codex", f"heavy{suffix}", "high"),
    }


def make_routing(enabled: bool = False) -> dict:
    return {
        "enabled": enabled,
        "heavy": {"follow": "main", "custom": None},
        "light": {"follow": "delegation", "custom": None},
        "fallback": {"enabled": False, "heavy": None, "light": None},
    }


class FakeCLI:
    def __init__(self, profiles: list[str]):
        self.values: dict[str, dict[str, object]] = {}
        for index, profile in enumerate(profiles):
            suffix = str(index)
            self.values[profile] = {
                "model.provider": "openai-codex",
                "model.default": f"heavy{suffix}",
                "agent.reasoning_effort": "high",
                "delegation.provider": "deepseek",
                "delegation.model": f"light{suffix}",
                "delegation.reasoning_effort": "low",
                "auxiliary.compression.provider": "auto",
                "auxiliary.compression.model": "",
                "auxiliary.compression.reasoning_effort": "",
                "auxiliary.title_generation.provider": "auto",
                "auxiliary.title_generation.model": "",
                "auxiliary.title_generation.reasoning_effort": "",
                "model.base_url": "",
                "model.api_mode": "",
                "delegation.base_url": "",
                "delegation.api_mode": "",
                "skills.disabled": [],
            }
        self.calls: list[tuple[str, str, object]] = []
        self.fail_on_write: int | None = None

    def writer(self, profile: str, key: str, value: object) -> None:
        self.calls.append((profile, key, copy.deepcopy(value)))
        if self.fail_on_write is not None and len(self.calls) == self.fail_on_write:
            raise OSError("synthetic writer failure")
        self.values[profile][key] = copy.deepcopy(value)

    def run(self, command, *, env, shell, capture_output, text, timeout, check):
        assert shell is False
        profile = command[command.index("--profile") + 1] if "--profile" in command else "default"
        action = command.index("config")
        subcommand, key = command[action + 1], command[action + 2]
        if subcommand == "get":
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.values[profile].get(key)), stderr="")
        assert subcommand == "set"
        raw = command[action + 3]
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        self.values[profile][key] = value
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def setup_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, profiles=("default", "p1", "p2")):
    root = tmp_path / "hermes"
    root.mkdir()
    cli = FakeCLI(list(profiles))
    if "default" in profiles:
        (root / "config.yaml").write_text("fake-only: true\n", encoding="utf-8")
    profiles_dir = root / "profiles"
    profiles_dir.mkdir()
    for profile in profiles:
        if profile == "default":
            continue
        home = profiles_dir / profile
        home.mkdir()
        (home / "config.yaml").write_text("fake-only: true\n", encoding="utf-8")
    monkeypatch.setattr(Service, "_cli_path", lambda self: "fake-hermes")
    monkeypatch.setattr(Service, "_read_key", lambda self, profile, key: copy.deepcopy(cli.values[profile].get(key)))
    monkeypatch.setattr(service_module.subprocess, "run", cli.run)
    source = tmp_path / "compat" / "SKILL.md"
    source.parent.mkdir()
    source.write_text("# fake compatibility skill\n", encoding="utf-8")
    monkeypatch.setattr(service_module, "COMPAT_SKILL_SOURCE", source)
    return root, cli


def find_profile(status: dict, name: str) -> dict:
    return next(item for item in status["profiles"] if item["name"] == name)


def test_initialize_preserves_models_and_only_toggles_selected_skill(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    cli.values["default"]["skills.disabled"] = ["unrelated-skill"]
    cli.values["p1"]["skills.disabled"] = ["unrelated-skill", SKILL_NAME]
    cli.values["p2"]["skills.disabled"] = ["unrelated-skill"]
    original = copy.deepcopy(cli.values)
    service = Service(root=root, writer=cli.writer)

    status = service.initialize(["p1"])

    assert status["revision"] == 1
    assert [p["name"] for p in status["profiles"]] == ["default", "p1", "p2"]
    p1 = find_profile(status, "p1")
    assert p1["models"] == make_models("1")
    assert p1["routing"]["enabled"] is True
    assert p1["drift"] == []
    assert service.routing_config("p1")["light"] == make_models("1")["delegation"]
    assert service.routing_config("p1")["heavy"] == make_models("1")["main"]
    assert service.routing_config("p2")["enabled"] is False
    assert cli.values["default"]["skills.disabled"] == ["unrelated-skill", SKILL_NAME]
    assert cli.values["p1"]["skills.disabled"] == ["unrelated-skill"]
    assert cli.values["p2"]["skills.disabled"] == ["unrelated-skill", SKILL_NAME]
    assert all(key == "skills.disabled" for _, key, _ in cli.calls)
    assert cli.values["default"]["model.default"] == original["default"]["model.default"]
    assert (root / "profiles" / "p1" / "skills" / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8").startswith("# fake")
    assert not (root / "profiles" / "p2" / "skills" / SKILL_NAME / "SKILL.md").exists()


def test_initialize_imports_only_explicit_fallback_routes(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    fallbacks = {"enabled": True, "heavy": route("xiaomi", "mimo/pro:1", "high"), "light": route("deepseek", "flash:free", "low")}

    status = service.initialize(["p1"], fallbacks={"p1": fallbacks})

    assert find_profile(status, "p1")["routing"]["fallback"] == fallbacks
    assert find_profile(status, "p2")["routing"]["fallback"] == {"enabled": False, "heavy": None, "light": None}


def test_preview_apply_projects_models_only_to_targets_and_clears_existing_stale_overrides(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    cli.values["p2"]["model.base_url"] = "https://private.example/v1"
    cli.values["p2"]["model.api_mode"] = "chat_completions"
    cli.values["p2"]["delegation.base_url"] = "https://private-delegation.example/v1"
    current = find_profile(service.status(), "p1")
    desired = copy.deepcopy(current["models"])
    desired["main"] = route("openai-api", "gpt/6:final", "xhigh")
    body = {
        "expected_revision": service.status()["revision"], "profile": "p1", "models": desired,
        "model_targets": ["p2"], "routing": current["routing"], "routing_profiles": ["p1"],
    }

    preview = service.preview(body)
    text = json.dumps(preview["changes"])
    assert "private.example" not in text
    assert "model.base_url" in text and "model.api_mode" in text
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    assert cli.values["p2"]["model.provider"] == "openai-api"
    assert cli.values["p2"]["model.default"] == "gpt/6:final"
    assert cli.values["p2"]["agent.reasoning_effort"] == "xhigh"
    assert cli.values["p2"]["model.base_url"] == ""
    assert cli.values["p2"]["model.api_mode"] == ""
    assert cli.values["p2"]["delegation.base_url"] == "https://private-delegation.example/v1"
    assert cli.values["p1"]["model.provider"] == "openai-codex"
    assert find_profile(service.status(), "p2")["models"] == desired
    assert receipt["revision"] == body["expected_revision"] + 1
    assert (root / "plugin-data" / "model-router" / "backups").is_dir()


def test_apply_rejects_config_drift_and_consumes_plan_once(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    p1 = find_profile(service.status(), "p1")
    desired = copy.deepcopy(p1["models"])
    desired["main"] = route("openai-api", "new-model", "high")
    plan = service.preview({
        "expected_revision": service.status()["revision"], "profile": "p1", "models": desired,
        "model_targets": ["p2"], "routing": p1["routing"], "routing_profiles": ["p1"],
    })
    cli.values["p2"]["model.default"] = "external-edit"

    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    with pytest.raises(ServiceError, match="consumed"):
        service.apply(plan["plan_id"])
    assert not cli.calls or all(key == "skills.disabled" for _, key, _ in cli.calls)


def test_noop_plan_is_safe_and_does_not_increment_revision(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    before = service.status()
    p1 = find_profile(before, "p1")
    preview = service.preview({
        "expected_revision": before["revision"], "profile": "p1", "models": p1["models"],
        "model_targets": [], "routing": p1["routing"], "routing_profiles": ["p1"],
    })
    assert preview["changes"] == []

    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "no_change"
    assert receipt["revision"] == before["revision"]
    assert service.status()["revision"] == before["revision"]


def test_preview_rejects_extra_fields_unsafe_tokens_and_collapsed_routes(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    p1 = find_profile(service.status(), "p1")
    base = {
        "expected_revision": service.status()["revision"], "profile": "p1", "models": p1["models"],
        "model_targets": [], "routing": p1["routing"], "routing_profiles": ["p1"],
    }
    with pytest.raises(ValueError, match="unknown or missing"):
        service.preview({**base, "extra": True})
    unsafe = copy.deepcopy(base)
    unsafe["models"]["main"]["provider"] = "openai;touch"
    with pytest.raises(ValueError, match="unsupported characters"):
        service.preview(unsafe)
    collapsed = copy.deepcopy(base)
    same = route("one", "same-model")
    collapsed["routing"]["heavy"] = {"follow": "custom", "custom": same}
    collapsed["routing"]["light"] = {"follow": "custom", "custom": same}
    plan = service.preview(collapsed)
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    effective = service.routing_config('p1')
    assert effective['heavy'] == effective['light'] == same


def test_new_config_backed_profile_is_off_until_explicitly_selected(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    new_home = root / "profiles" / "newone"
    new_home.mkdir()
    (new_home / "config.yaml").write_text("fake-only: true\n", encoding="utf-8")
    cli.values["newone"] = copy.deepcopy(cli.values["p2"])

    config = service.routing_config("newone")

    assert config["enabled"] is False
    assert config["heavy"]["model"] == cli.values["newone"]["model.default"]
    with pytest.raises(ValueError, match="invalid profile name"):
        service.routing_config("../p1")


def test_partial_writer_failure_is_recorded_without_claiming_remaining_keys(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    cli.calls.clear()
    p1 = find_profile(service.status(), "p1")
    desired = copy.deepcopy(p1["models"])
    desired["main"] = route("openai-api", "new-model", "xhigh")
    preview = service.preview({
        "expected_revision": service.status()["revision"], "profile": "p1", "models": desired,
        "model_targets": ["p2"], "routing": p1["routing"], "routing_profiles": ["p1"],
    })
    cli.fail_on_write = 2

    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "partial"
    assert len(receipt["applied"]) == 1
    assert receipt["remaining"]
    assert service.status()["recent_apply"] == receipt
    assert all("synthetic" not in value for value in receipt.values() if isinstance(value, str))
    assert len(cli.calls) == 2


def test_default_writer_uses_supported_cli_shell_false_and_profile_bound_home(tmp_path, monkeypatch):
    root, _cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root)
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_module.subprocess, "run", fake_run)
    service._write_key("p1", "model.default", "provider/model:1")

    assert seen["command"] == [service_module.sys.executable, "-m", "hermes_cli.main", "--profile", "p1", "config", "set", "model.default", "provider/model:1", "--force"]
    assert seen["env"]["PYTHONPATH"] == os.pathsep.join(service._loaded_cli_paths())
    assert seen["shell"] is False
    assert seen["env"]["HERMES_HOME"] == str(root / "profiles" / "p1")


def test_profile_discovery_ignores_hidden_and_symlink_escape(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    hidden = root / "profiles" / ".hidden"
    hidden.mkdir()
    (hidden / "config.yaml").write_text("fake\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config.yaml").write_text("fake\n", encoding="utf-8")
    link = root / "profiles" / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable in this test environment")

    assert Service(root=root, writer=cli.writer)._discover_profiles() == ["default", "p1", "p2"]
