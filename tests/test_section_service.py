"""Independent model/routing saves preserve unrelated canonical policy."""
from __future__ import annotations

import copy
import json

from model_router.service import Service
from model_router.timeouts import timeout_digest, write_timeouts
from test_service import find_profile, route, setup_home


def setup(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["default", "p1", "p2"])
    status = service.status()
    source = find_profile(status, "p1")
    body = {
        "expected_revision": status["revision"],
        "profile": "p1",
        "models": copy.deepcopy(source["models"]),
        "model_targets": [],
        "routing": copy.deepcopy(source["routing"]),
        "routing_profiles": [row["name"] for row in status["profiles"] if row["routing"]["enabled"]],
        "routing_targets": [],
    }
    cli.calls.clear()
    return service, cli, body


def test_models_scope_ignores_dirty_routing_draft_and_membership(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    desired = copy.deepcopy(body["models"])
    desired["main"] = route("operator", "models-only-target", "xhigh")
    body.update(save_scope="models", model_targets=["p2"], models=desired)
    body["routing"] = {"dirty": "unrelated draft"}
    body["routing_profiles"] = ["default"]

    preview = service.preview(body)
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert after["p2"]["models"] == desired
    for name in before:
        assert after[name]["routing"] == before[name]["routing"]
        assert after[name]["fallback_consent"] == before[name]["fallback_consent"]
        if name != "p2":
            assert after[name]["models"] == before[name]["models"]
    assert cli.calls
    assert all(name == "p2" for name, _key, _value in cli.calls)
    assert all(key != "skills.disabled" for _name, key, _value in cli.calls)


def test_routing_scope_ignores_dirty_models_and_nested_fallback(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    timeout_bytes = {}
    for name in ("default", "p1", "p2"):
        home = service._profile_home(name)
        write_timeouts(home, {"delegate_total_seconds": 0, "routed_total_seconds": 3601},
                       expected_digest=timeout_digest(home), expected_revision=0)
        timeout_bytes[name] = (home / "plugin-data/model-router/timeouts.json").read_bytes()

    body.update(save_scope="routing", routing_targets=["p2"])
    body["models"] = {"dirty": "unrelated model draft"}
    body["routing"]["heavy"] = {"follow": "custom", "custom": route("operator", "routing-only-heavy", "high")}
    body["routing"]["light"] = {"follow": "custom", "custom": route("operator", "routing-only-light", "low")}
    body["routing"]["fallback"] = {
        "enabled": True,
        "heavy": route("spare", "must-not-copy-heavy", "high"),
        "light": route("spare", "must-not-copy-light", "low"),
    }

    preview = service.preview(body)
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    for name in before:
        assert after[name]["models"] == before[name]["models"]
        assert after[name]["routing"]["fallback"] == before[name]["routing"]["fallback"]
        assert after[name]["fallback_consent"] == before[name]["fallback_consent"]
    assert after["p2"]["routing"]["heavy"] == body["routing"]["heavy"]
    assert after["p2"]["routing"]["light"] == body["routing"]["light"]
    assert after["p1"]["routing"] == before["p1"]["routing"]
    assert {name: (service._profile_home(name) / "plugin-data/model-router/timeouts.json").read_bytes()
            for name in timeout_bytes} == timeout_bytes
    assert cli.calls == []


def test_legacy_no_scope_does_not_overwrite_canonical_model_drift_without_targets(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before_bytes = service.store_path.read_bytes()
    before = json.loads(before_bytes)["profiles"]
    # The projected config has drifted from the canonical desired value.
    cli.values["p2"]["model.default"] = "external-drift"
    body["routing_targets"] = []
    body["model_targets"] = []

    preview = service.preview(body)  # no save_scope is the frozen legacy whole-page behavior
    assert preview["changes"] == []
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "no_change"
    assert service.store_path.read_bytes() == before_bytes
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert after["p2"] == before["p2"]
    row = find_profile(service.status(), "p2")
    assert "models.main" in row["drift"]
    assert row["actual_models"]["main"]["model"] == "external-drift"
    assert cli.calls == []
