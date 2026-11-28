from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from model_router import effective_config
from model_router.service import RevisionConflict, Service


def route(provider: str, model: str, reasoning: str = "medium") -> dict[str, str]:
    return {"provider": provider, "model": model, "reasoning": reasoning}


def models(suffix: str = "") -> dict[str, dict[str, str]]:
    return {
        "main": route("openai-codex", f"main-model{suffix}", "high"),
        "delegation": route("deepseek", f"delegation-model{suffix}", "low"),
        "compression": route("openai-codex", f"main-model{suffix}", "high"),
        "title": route("openai-codex", f"main-model{suffix}", "high"),
    }


class FakeConfig:
    def __init__(self, profiles: tuple[str, ...] = ("default", "p1")):
        self.values: dict[str, dict[str, object]] = {}
        for index, profile in enumerate(profiles):
            suffix = str(index)
            self.values[profile] = {
                "model.provider": "openai-codex",
                "model.default": f"main-model{suffix}",
                "agent.reasoning_effort": "high",
                "delegation.provider": "deepseek",
                "delegation.model": f"delegation-model{suffix}",
                "delegation.reasoning_effort": "low",
                "auxiliary.compression.provider": "auto",
                "auxiliary.compression.model": "",
                "auxiliary.compression.reasoning_effort": "",
                "auxiliary.title_generation.provider": "auto",
                "auxiliary.title_generation.model": "",
                "auxiliary.title_generation.reasoning_effort": "",
                "skills.disabled": [],
                "fallback_providers": [],
                "fallback_model": [],
            }
        self.calls: list[tuple[str, str, object]] = []
        self.fail_on_write: int | None = None

    def read(self, _service, profile: str, key: str):
        return copy.deepcopy(self.values[profile].get(key))

    def write(self, profile: str, key: str, value: object):
        self.calls.append((profile, key, copy.deepcopy(value)))
        if self.fail_on_write == len(self.calls):
            raise OSError("fake writer error")
        self.values[profile][key] = copy.deepcopy(value)


def setup_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "config.yaml").write_text("fake-only: true\n", encoding="utf-8")
    profiles = root / "profiles"
    profiles.mkdir()
    (profiles / "p1").mkdir()
    (profiles / "p1" / "config.yaml").write_text("fake-only: true\n", encoding="utf-8")
    fake = FakeConfig()

    def native_snapshot(_service, profile):
        raw = {
            "fallback_providers": copy.deepcopy(fake.values[profile].get("fallback_providers")),
            "fallback_model": copy.deepcopy(fake.values[profile].get("fallback_model")),
        }
        return effective_config.make_snapshot(raw=raw, effective=raw)

    monkeypatch.setattr(Service, "_read_key", lambda _service, profile, key: fake.read(None, profile, key))
    monkeypatch.setattr(Service, "_read_native_snapshot", native_snapshot)
    service = Service(root=root, writer=fake.write)
    service.initialize(["default"])
    fake.calls.clear()
    return service, fake, root


def profile(status: dict, name: str = "default") -> dict:
    return next(row for row in status["profiles"] if row["name"] == name)


def confirmation(scope: str, name: str = "default") -> dict[str, object]:
    return {
        "profile": name,
        "scope": scope,
        "allow_additional_cost": True,
        "allow_task_rerun": False,
    }


def fallback_body(service: Service, updates: list[dict], confirmations: list[dict] | None = None) -> dict:
    return {
        "expected_revision": service.status()["revision"],
        "updates": updates,
        "confirmations": confirmations or [],
    }


def test_status_exposes_fixed_capabilities_and_entry_fields(tmp_path, monkeypatch):
    service, _fake, root = setup_service(tmp_path, monkeypatch)
    status = service.status()
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))
    entry = stored["profiles"]["default"]

    assert stored["schema"] == 5
    assert set(entry) == {"models", "routing", "native_fallback", "delegation_fallback", "fallback_consent"}
    assert entry["routing"] == {"enabled": True, "slots": {}}
    assert entry["native_fallback"] is None
    assert entry["delegation_fallback"] is None
    assert entry["fallback_consent"] == {"native": None, "delegation": None}
    assert set(profile(status)["fallbacks"]) == {"native", "delegation"}
    assert status["fallback_capabilities"] == {
        "native_trigger": "hermes_runtime",
        "native_execution": "continue_conversation",
        "native_reasoning": "profile_overrides",
    }
    assert profile(status)["fallbacks"]["native"]["managed"] is False
    assert profile(status)["fallbacks"]["native"]["editable"] is True
    assert root.joinpath("config.yaml").exists()


def test_native_chain_merges_legacy_keys_and_explicit_apply_projects_both_keys(tmp_path, monkeypatch):
    service, fake, _root = setup_service(tmp_path, monkeypatch)
    fake.values["default"]["fallback_providers"] = [{"provider": "xiaomi", "model": "mimo-v2"}]
    fake.values["default"]["fallback_model"] = {"provider": "deepseek", "model": "flash"}
    initial = profile(service.status())["fallbacks"]["native"]
    assert initial["actual_chain"] == [
        {"provider": "xiaomi", "model": "mimo-v2"},
        {"provider": "deepseek", "model": "flash"},
    ]
    assert initial["editable"] is True

    desired = {"enabled": True, "chain": initial["actual_chain"]}
    preview = service.fallback_preview(fallback_body(service, [{"profile": "default", "native_fallback": desired}], [confirmation("native")]))
    assert {"fallback_model", "fallback_providers"} <= {change["field"] for change in preview["changes"]}
    assert not any("private" in json.dumps(change) for change in preview["changes"])
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    assert fake.values["default"]["fallback_model"] == []
    assert fake.values["default"]["fallback_providers"] == desired["chain"]
    row = profile(service.status())
    assert row["routing"]["enabled"] is True
    assert row["fallbacks"]["native"]["managed"] is True
    assert row["fallbacks"]["native"]["drift"] is False
    assert row["fallbacks"]["native"]["consent"]["source"] == "explicit"


def test_native_off_clears_both_legacy_keys_and_keeps_the_stored_chain(tmp_path, monkeypatch):
    service, fake, _root = setup_service(tmp_path, monkeypatch)
    chain = [{"provider": "xiaomi", "model": "mimo-v2"}]
    enable = service.fallback_preview(fallback_body(
        service,
        [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain}}],
        [confirmation("native")],
    ))
    assert service.apply(enable["plan_id"])["status"] == "applied"

    disable = service.fallback_preview(fallback_body(
        service,
        [{"profile": "default", "native_fallback": {"enabled": False, "chain": chain}}],
    ))
    assert service.apply(disable["plan_id"])["status"] == "applied"
    assert fake.values["default"]["fallback_model"] == []
    assert fake.values["default"]["fallback_providers"] == []
    native = profile(service.status())["fallbacks"]["native"]
    # The status projects the chain Hermes uses (now none); the stored block keeps the chain.
    assert native["enabled"] is False
    assert native["chain"] == [] and native["actual_chain"] == []
    assert native["drift"] is False and native["managed"] is True
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["default"]["native_fallback"]
    assert stored == {"enabled": False, "chain": chain}


def test_advanced_native_entry_is_sanitized_and_read_only(tmp_path, monkeypatch):
    service, fake, _root = setup_service(tmp_path, monkeypatch)
    fake.values["default"]["fallback_providers"] = [{
        "provider": "custom", "model": "private-model", "base_url": "https://secret.example",
        "api_key": "do-not-leak",
    }]
    status = service.status()
    native = profile(status)["fallbacks"]["native"]

    assert native["editable"] is False
    assert native["warnings"] == ["native_fallback_advanced_entry"]
    assert native["actual_chain"] == [{"provider": "custom", "model": "private-model"}]
    assert "secret.example" not in json.dumps(status)
    assert "do-not-leak" not in json.dumps(status)
    with pytest.raises(ValueError, match="read-only"):
        service.fallback_preview(fallback_body(service, [{
            "profile": "default", "native_fallback": {"enabled": False, "chain": []},
        }]))
    assert fake.calls == []


def test_model_preview_cannot_change_fallback_and_preserves_additive_state(tmp_path, monkeypatch):
    service, _fake, _root = setup_service(tmp_path, monkeypatch)
    native_chain = [{"provider": "xiaomi", "model": "mimo-v2"}]
    native_approved = service.fallback_preview(fallback_body(
        service, [{"profile": "default", "native_fallback": {"enabled": True, "chain": native_chain}}],
        [confirmation("native")],
    ))
    assert service.apply(native_approved["plan_id"])["status"] == "applied"
    before = profile(service.status())
    body = {
        "expected_revision": service.status()["revision"],
        "profile": "default",
        "models": copy.deepcopy(before["models"]),
        "model_targets": ["default"],
        "routing": copy.deepcopy(before["routing"]),
        "routing_profiles": ["default"],
    }
    attempted = copy.deepcopy(body)
    attempted["routing"]["fallback"] = {"enabled": False, "heavy": None, "light": None}
    with pytest.raises(ValueError, match="routing must define enabled and slots"):
        service.preview(attempted)

    for role in ("main", "compression", "title"):
        body["models"][role]["model"] = "main-updated"
    preview = service.preview(body)
    assert service.apply(preview["plan_id"])["status"] == "applied"
    after = profile(service.status())
    assert after["models"]["main"]["model"] == "main-updated"
    assert after["fallbacks"] == before["fallbacks"]
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["default"]
    assert stored["native_fallback"] == {"enabled": True, "chain": native_chain}
    assert stored["fallback_consent"]["native"]["source"] == "explicit"


def test_confirmation_paths_profiles_and_chain_validation_are_strict(tmp_path, monkeypatch):
    service, _fake, _root = setup_service(tmp_path, monkeypatch)
    chain = [{"provider": "xiaomi", "model": "mimo-v2"}]
    with pytest.raises(ValueError, match="unknown or missing"):
        service.fallback_preview({**fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}]), "extra": 1})
    with pytest.raises(ValueError, match="duplicate profiles"):
        service.fallback_preview(fallback_body(service, [
            {"profile": "default", "native_fallback": {"enabled": False, "chain": []}},
            {"profile": "default", "delegation_fallback": {"mode": "off", "chain": []}},
        ]))
    with pytest.raises(ValueError, match="duplicate profile scopes"):
        service.fallback_preview(fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain}}], [confirmation("native"), confirmation("native")]))
    too_long = [{"provider": f"provider{i}", "model": f"model{i}"} for i in range(6)]
    with pytest.raises(ValueError, match="at most five"):
        service.fallback_preview(fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": False, "chain": too_long}}]))
    with pytest.raises(ValueError, match="profile scope"):
        service.fallback_preview(fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}], [confirmation("delegation")]))
    with pytest.raises(ValueError, match="confirmation scope"):
        service.fallback_preview(fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain}}], [confirmation("routing")]))
    with pytest.raises(ValueError, match="retry flag"):
        service.fallback_preview(fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain}}],
                                               [{**confirmation("native"), "allow_task_rerun": True}]))
    with pytest.raises(ValueError, match="known fallback scopes"):
        service.fallback_preview(fallback_body(service, [{"profile": "default", "routing_fallback": {"enabled": False, "heavy": None, "light": None}}]))


def test_native_partial_apply_receipt_does_not_claim_unwritten_key(tmp_path, monkeypatch):
    service, fake, _root = setup_service(tmp_path, monkeypatch)
    fake.values["default"]["fallback_model"] = {"provider": "deepseek", "model": "legacy"}
    chain = [{"provider": "xiaomi", "model": "mimo-v2"}]
    preview = service.fallback_preview(fallback_body(
        service,
        [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain}}],
        [confirmation("native")],
    ))
    fake.fail_on_write = 2

    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "partial"
    assert receipt["applied"] == [{"profile": "default", "key": "fallback_model"}]
    assert receipt["remaining"] == [{"profile": "default", "key": "fallback_providers"}]
    assert fake.values["default"]["fallback_model"] == []
    assert fake.values["default"]["fallback_providers"] == []


def test_fallback_preview_revision_conflict_is_rejected(tmp_path, monkeypatch):
    service, _fake, _root = setup_service(tmp_path, monkeypatch)
    body = fallback_body(service, [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}])
    body["expected_revision"] += 1
    with pytest.raises(RevisionConflict):
        service.fallback_preview(body)


@pytest.mark.parametrize("key", ["fallback_providers", "fallback_model"])
@pytest.mark.parametrize("change_kind", ["advanced", "malformed", "oversized"])
def test_native_edit_between_validation_and_cas_is_rejected_without_adoption(
    tmp_path, monkeypatch, key, change_kind,
):
    service, fake, _root = setup_service(tmp_path, monkeypatch)
    initial = [{"provider": "xiaomi", "model": "mimo-v2"}]
    fake.values["default"]["fallback_providers"] = copy.deepcopy(initial)
    fake.values["default"]["fallback_model"] = []
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))
    entry = stored["profiles"]["default"]
    entry["native_fallback"] = {"enabled": True, "chain": copy.deepcopy(initial)}
    from model_router.fallback_policy import make_consent
    entry["fallback_consent"]["native"] = make_consent(
        "default", "native", entry["native_fallback"], source="explicit"
    )
    service.store_path.write_text(json.dumps(stored), encoding="utf-8")
    store_before = service.store_path.read_bytes()
    consent_before = copy.deepcopy(entry["fallback_consent"])
    recent_path = service.root / "plugin-data" / "model-router" / "recent_apply.json"
    recent_before = recent_path.read_bytes() if recent_path.exists() else None
    body = fallback_body(service, [{
        "profile": "default", "native_fallback": {"enabled": False, "chain": []},
    }])

    if change_kind == "advanced":
        changed = [{
            "provider": "external", "model": "private-model",
            "base_url": "https://private.invalid", "api_key": "secret-canary",
        }]
        if key == "fallback_model":
            changed = changed[0]
    elif change_kind == "malformed":
        changed = "not-a-fallback-list" if key == "fallback_providers" else ["malformed-entry"]
    else:
        changed = [
            {"provider": f"provider{i}", "model": f"model{i}"}
            for i in range(6)
        ]

    original_snapshot = service._read_native_snapshot
    calls = 0

    def interleaved_snapshot(profile_name):
        nonlocal calls
        calls += 1
        if calls == 2:
            fake.values["default"][key] = copy.deepcopy(changed)
        return original_snapshot(profile_name)

    monkeypatch.setattr(service, "_read_native_snapshot", interleaved_snapshot)
    with pytest.raises(RevisionConflict, match="changed during preview"):
        service.fallback_preview(body)

    assert calls == 2
    assert fake.values["default"][key] == changed
    other_key = "fallback_model" if key == "fallback_providers" else "fallback_providers"
    assert fake.values["default"][other_key] == ([] if other_key == "fallback_model" else initial)
    assert fake.calls == []
    assert service.store_path.read_bytes() == store_before
    assert json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["default"]["fallback_consent"] == consent_before
    assert (recent_path.read_bytes() if recent_path.exists() else None) == recent_before
    plans_dir = service.store_path.parent / "plans"
    assert not plans_dir.exists() or list(plans_dir.glob("*.json")) == []
