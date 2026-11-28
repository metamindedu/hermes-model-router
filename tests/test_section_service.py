"""Independent model/routing saves preserve unrelated canonical policy."""
from __future__ import annotations

import copy
import json

import pytest

from model_router.service import Service, ServiceError
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


def test_routing_scope_ignores_dirty_models_and_preserves_fallbacks_and_limits(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    timeout_bytes = {}
    for name in ("default", "p1", "p2"):
        home = service._profile_home(name)
        write_timeouts(home, {"delegate_total_seconds": 0, "slot_seconds": {"design": 3601}},
                       expected_digest=timeout_digest(home), expected_revision=0)
        timeout_bytes[name] = (home / "plugin-data/model-router/timeouts.json").read_bytes()

    body.update(save_scope="routing", routing_targets=["p2"])
    body["models"] = {"dirty": "unrelated model draft"}
    body["routing"]["slots"]["design"] = {"follow": "custom", "custom": route("operator", "routing-only-design", "high")}
    body["routing"]["slots"]["code-simple"] = {"follow": "custom", "custom": route("operator", "routing-only-code", "low")}
    preview = service.preview(body)
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    for name in before:
        assert after[name]["models"] == before[name]["models"]
        assert after[name]["native_fallback"] == before[name]["native_fallback"]
        assert after[name]["delegation_fallback"] == before[name]["delegation_fallback"]
        assert after[name]["fallback_consent"] == before[name]["fallback_consent"]
    assert after["p2"]["routing"]["slots"]["design"] == body["routing"]["slots"]["design"]
    assert after["p2"]["routing"]["slots"]["code-simple"] == body["routing"]["slots"]["code-simple"]
    assert after["p1"]["routing"] == before["p1"]["routing"]
    assert {name: (service._profile_home(name) / "plugin-data/model-router/timeouts.json").read_bytes()
            for name in timeout_bytes} == timeout_bytes
    assert cli.calls == []


def test_legacy_no_scope_does_not_overwrite_an_external_model_edit_without_targets(tmp_path, monkeypatch):
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
    # The config is the source of the models: an external edit is shown as the model, not as drift,
    # and the stored mirror is not rewritten by a read or a save that does not target it.
    assert not any(item.startswith("models.") or item == "actual_models_unavailable" for item in row["drift"])
    assert row["models"]["main"]["model"] == row["actual_models"]["main"]["model"] == "external-drift"
    assert row["models"]["compression"]["model"] == "external-drift"  # inherited, follows main
    assert row["model_roles"]["compression"]["source"] == "inherited"
    assert service.store_path.read_bytes() == before_bytes
    assert cli.calls == []


@pytest.mark.parametrize("scope", [None, "routing"])
def test_routing_save_refuses_retired_fallback_even_when_disabled(tmp_path, monkeypatch, scope):
    service, cli, body = setup(tmp_path, monkeypatch)
    before = service.store_path.read_bytes()
    if scope:
        body["save_scope"] = scope
    body["routing"]["fallback"] = {"enabled": False, "heavy": None, "light": None}
    with pytest.raises(ValueError, match="routing must define enabled and slots"):
        service.preview(body)
    assert service.store_path.read_bytes() == before and not cli.calls


def test_whole_page_copy_does_not_copy_other_targets_fallbacks(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    # p1 already owns an explicit delegation opt-out. A model/slot copy must not propagate it.
    store = json.loads(service.store_path.read_text(encoding="utf-8"))
    store["profiles"]["p1"]["delegation_fallback"] = {"mode": "off", "chain": []}
    service.store_path.write_text(json.dumps(store), encoding="utf-8")
    body["models"]["title"] = route("operator", "new-title", "none")
    body["routing"]["slots"]["code-simple"] = {"follow": "custom", "custom": route("operator", "copied-code", "low")}
    body.update(model_targets=["p1", "p2"], routing_targets=["p1", "p2"])
    assert service.apply(service.preview(body)["plan_id"])["status"] == "applied"
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    for name in ("p1", "p2"):
        assert after[name]["models"]["title"] == body["models"]["title"]
        assert after[name]["routing"]["slots"] == body["routing"]["slots"]
        for field in ("native_fallback", "delegation_fallback", "fallback_consent"):
            assert after[name][field] == store["profiles"][name][field]


def test_timeout_scope_does_not_require_resolvable_models_or_create_profile_entry(tmp_path, monkeypatch):
    # Only p1 is set up; p2 has no stored entry (as for a profile created afterwards) and its main
    # model is not configured.
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    del data["profiles"]["p2"]
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    for key in ("model.provider", "model.default"):
        cli.values["p2"].pop(key, None)
    with pytest.raises(ServiceError, match="no resolved main model"):
        service._actual_models("p2")
    status = service.status()
    p1 = find_profile(status, "p1")
    initial = service._default_routing()
    proposal = {
        "expected_revision": status["revision"], "profile": "p2", "save_scope": "timeouts",
        "models": copy.deepcopy(p1["models"]), "model_targets": [],
        "routing": copy.deepcopy(initial), "routing_targets": [],
        "routing_profiles": [row["name"] for row in status["profiles"] if row["routing"]["enabled"]],
        "timeout_updates": [],
    }
    assert "p2" not in json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    plan = service.preview(proposal)
    assert plan["changes"] == []
    assert service.apply(plan["plan_id"])["status"] == "no_change"
    assert "p2" not in json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
