"""Whole-page preview/apply uses one token with exact fallback targets."""
import copy
import json

import pytest

from model_router import effective_config
from model_router.service import RevisionConflict, Service, ServiceError
from test_fallback_service import setup_service, profile, confirmation, route


def setup(tmp_path, monkeypatch):
    service, fake, root = setup_service(tmp_path, monkeypatch)
    monkeypatch.setattr(Service, "_read_delegation_snapshot", lambda self, name: effective_config.make_key_snapshot(
        keys=("delegation.fallback_providers",),
        raw={"delegation.fallback_providers": copy.deepcopy(fake.values[name].get("delegation.fallback_providers"))},
        effective={"delegation.fallback_providers": copy.deepcopy(fake.values[name].get("delegation.fallback_providers"))},
    ))
    return service, fake, root


def body(service):
    status = service.status()
    current = profile(status)
    return {"expected_revision": status["revision"], "profile": "default",
            "models": copy.deepcopy(current["models"]), "model_targets": [],
            "routing": copy.deepcopy(current["routing"]), "routing_profiles": ["default"]}


def scopes():
    return {"native_fallback": {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]},
            "routing_fallback": {"enabled": True, "heavy": route("xiaomi", "heavy-spare"), "light": route("deepseek", "light-spare")},
            "delegation_fallback": {"mode": "custom", "chain": [{"provider": "deepseek", "model": "delegate-spare"}]}}


def attach(proposal, name="default"):
    proposal["fallback_updates"] = [{"profile": name, **scopes()}]
    proposal["fallback_confirmations"] = [confirmation(scope, name) for scope in ("native", "routing", "delegation")]
    return proposal


def test_one_preview_contains_models_and_three_scopes_and_one_apply_persists_all(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = attach(body(service))
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"]["model"] = "new-primary"
    proposal["models"]["delegation"]["model"] = "new-delegated"
    initial = copy.deepcopy(fake.values)
    initial_store = service.store_path.read_bytes()
    preview = service.preview(proposal)
    assert initial == fake.values and initial_store == service.store_path.read_bytes()
    assert fake.calls == []
    fields = {change["field"] for change in preview["changes"]}
    assert {"models.main", "models.delegation", "native_fallback", "routing.fallback", "delegation_fallback"} <= fields
    assert len(list((service.store_path.parent / "plans").glob("*.json"))) == 1
    receipt = Service(service.root, writer=fake.write).apply(preview["plan_id"])
    assert receipt["status"] == "applied" and receipt["revision"] == proposal["expected_revision"] + 1
    stored = json.loads(service.store_path.read_text())["profiles"]["default"]
    assert stored["models"] == proposal["models"]
    assert stored["native_fallback"] == scopes()["native_fallback"]
    assert stored["routing"]["fallback"] == scopes()["routing_fallback"]
    assert stored["delegation_fallback"] == scopes()["delegation_fallback"]
    assert fake.values["default"]["model.default"] == "new-primary"
    assert fake.values["default"]["fallback_providers"] == scopes()["native_fallback"]["chain"]
    assert fake.values["default"]["delegation.fallback_providers"] == scopes()["delegation_fallback"]["chain"]
    assert fake.values["p1"] == initial["p1"]
    with pytest.raises(ServiceError):
        service.apply(preview["plan_id"])


def test_fallback_targets_independent_from_model_targets(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    initial = copy.deepcopy(fake.values)
    proposal = attach(body(service), "p1")
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"]["model"] = "new-primary"
    preview = service.preview(proposal)
    assert service.apply(preview["plan_id"])["status"] == "applied"
    assert fake.values["default"]["model.default"] == "new-primary"
    assert fake.values["default"]["fallback_providers"] == initial["default"]["fallback_providers"]
    assert fake.values["default"].get("delegation.fallback_providers") is None
    assert fake.values["p1"]["model.default"] == initial["p1"]["model.default"]
    assert fake.values["p1"]["fallback_providers"] == scopes()["native_fallback"]["chain"]


def test_unchanged_fallbacks_are_not_adopted_by_general_save(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    before = json.loads(service.store_path.read_text())["profiles"]
    proposal = body(service)
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"]["model"] = "new-primary"
    proposal.update(fallback_updates=[], fallback_confirmations=[])
    preview = service.preview(proposal)
    assert service.apply(preview["plan_id"])["status"] == "applied"
    after = json.loads(service.store_path.read_text())["profiles"]
    for name in before:
        for key in ("native_fallback", "delegation_fallback", "fallback_consent"):
            assert after[name][key] == before[name][key]
    assert not any("fallback" in key for _, key, _ in fake.calls)


@pytest.mark.parametrize("key,scope", [("native_fallback", "native"), ("routing_fallback", "routing")])
def test_combined_validation_uses_new_primary_not_old_model(tmp_path, monkeypatch, key, scope):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = body(service)
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"] = route("xiaomi", "collision")
    value = scopes()[key]
    if scope == "native":
        value["chain"] = [{"provider": "xiaomi", "model": "collision"}]
    else:
        value["heavy"] = route("xiaomi", "collision")
    proposal["fallback_updates"] = [{"profile": "default", key: value}]
    proposal["fallback_confirmations"] = [confirmation(scope)]
    with pytest.raises(ValueError, match="differ"):
        service.preview(proposal)
    assert fake.calls == []
    assert not list((service.store_path.parent / "plans").glob("*.json"))


def test_fallback_to_old_primary_allowed_when_primary_changes(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = body(service)
    old = proposal["models"]["main"]
    proposal["models"]["main"] = route("xiaomi", "new-primary")
    proposal["model_targets"] = ["default"]
    proposal["fallback_updates"] = [{"profile": "default", "native_fallback": {"enabled": True, "chain": [{"provider": old["provider"], "model": old["model"]}]}}]
    proposal["fallback_confirmations"] = [confirmation("native")]
    preview = service.preview(proposal)
    assert service.apply(preview["plan_id"])["status"] == "applied"


@pytest.mark.parametrize("field", ["fallback_providers", "delegation.fallback_providers", "model.default"])
def test_combined_plan_rejects_external_changes_before_any_write(tmp_path, monkeypatch, field):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = attach(body(service))
    proposal["model_targets"] = ["default"]
    preview = service.preview(proposal)
    fake.values["default"][field] = "external"
    before = copy.deepcopy(fake.values), service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(preview["plan_id"])
    assert before == (fake.values, service.store_path.read_bytes())
    assert fake.calls == []


def test_invalid_combined_fallback_cannot_leave_model_only_plan(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = attach(body(service))
    proposal["fallback_confirmations"] = []
    before = service.store_path.read_bytes()
    with pytest.raises(ValueError, match="confirmation"):
        service.preview(proposal)
    assert fake.calls == [] and service.store_path.read_bytes() == before
    assert not list((service.store_path.parent / "plans").glob("*.json"))


def test_partial_combined_write_reports_remaining_and_consumes_token(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = attach(body(service))
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"]["model"] = "new-primary"
    preview = service.preview(proposal)
    fake.fail_on_write = 2
    receipt = service.apply(preview["plan_id"])
    assert receipt["status"] == "partial" and receipt["remaining"]
    assert len(receipt["applied"]) == 1
    with pytest.raises(ServiceError):
        service.apply(preview["plan_id"])


@pytest.mark.parametrize("extra", [{"fallback_updates": None}, {"fallback_confirmations": [{}]}, {"unexpected": []}])
def test_combined_payload_rejects_invalid_optional_fields(tmp_path, monkeypatch, extra):
    service, fake, _ = setup(tmp_path, monkeypatch)
    proposal = body(service)
    proposal.update(extra)
    with pytest.raises(ValueError):
        service.preview(proposal)
    assert fake.calls == []


def test_combined_apply_through_real_hermes_cli_in_isolated_home(tmp_path, monkeypatch):
    """No real model calls; real config CLI plus effective readback in fake home."""
    import os
    from pathlib import Path
    import yaml
    from test_integration import make_home, payload
    launcher = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/bin/hermes.exe"
    if not launcher.is_file():
        pytest.skip("Windows local Hermes CLI not installed")
    for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        monkeypatch.delenv(key, raising=False)
    root = make_home(tmp_path)
    service = Service(root)
    monkeypatch.setattr(service, "_cli_path", lambda: str(launcher))
    service.initialize(["default"])
    proposal = attach(payload(service))
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"]["model"] = "isolated-combined-main"
    preview = service.preview(proposal)
    before = (root / "config.yaml").read_bytes()
    assert (root / "config.yaml").read_bytes() == before
    receipt = service.apply(preview["plan_id"])
    assert receipt["status"] == "applied", receipt
    actual = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert actual["model"]["default"] == "isolated-combined-main"
    assert actual["fallback_providers"] == scopes()["native_fallback"]["chain"]
    assert actual["fallback_model"] == []
    assert actual["delegation"]["fallback_providers"] == scopes()["delegation_fallback"]["chain"]
    final = service.status()["profiles"][0]
    assert final["fallbacks"]["native"]["drift"] is False
    assert final["fallbacks"]["delegation"]["drift"] is False
    assert service.routing_config("default")["fallback"] == scopes()["routing_fallback"]
    assert final["models"] == proposal["models"]


@pytest.mark.parametrize("kind", ["model", "custom", "other-scope"])
def test_retained_routing_spare_conflicts_rejected_at_backend(tmp_path, monkeypatch, kind):
    service, fake, _ = setup(tmp_path, monkeypatch)
    fallback = scopes()["routing_fallback"]
    service.apply(service.fallback_preview({
        "expected_revision": service.status()["revision"],
        "updates": [{"profile": "default", "routing_fallback": fallback}],
        "confirmations": [confirmation("routing")],
    })["plan_id"])
    fake.calls.clear()
    proposal = body(service)
    if kind == "custom":
        proposal["routing"]["heavy"] = {"follow": "custom", "custom": copy.deepcopy(fallback["heavy"])}
    else:
        proposal["model_targets"] = ["default"]
        proposal["models"]["main"] = copy.deepcopy(fallback["heavy"])
    if kind == "other-scope":
        proposal["fallback_updates"] = [{"profile": "default", "delegation_fallback": scopes()["delegation_fallback"]}]
        proposal["fallback_confirmations"] = [confirmation("delegation")]
    before = service.store_path.read_bytes(), copy.deepcopy(fake.values)
    with pytest.raises(ValueError, match="final primary"):
        service.preview(proposal)
    assert fake.calls == [] and before == (service.store_path.read_bytes(), fake.values)


def test_retained_routing_spare_and_approval_preserved_on_nonconflicting_model_save(tmp_path, monkeypatch):
    service, fake, _ = setup(tmp_path, monkeypatch)
    service.apply(service.fallback_preview({
        "expected_revision": service.status()["revision"],
        "updates": [{"profile": "default", "routing_fallback": scopes()["routing_fallback"]}],
        "confirmations": [confirmation("routing")],
    })["plan_id"])
    before = json.loads(service.store_path.read_text())["profiles"]["default"]
    proposal = body(service)
    proposal["model_targets"] = ["default"]
    proposal["models"]["main"]["model"] = "new-nonconflicting-main"
    assert service.apply(service.preview(proposal)["plan_id"])["status"] == "applied"
    after = json.loads(service.store_path.read_text())["profiles"]["default"]
    assert after["routing"]["fallback"] == before["routing"]["fallback"]
    assert after["fallback_consent"] == before["fallback_consent"]
