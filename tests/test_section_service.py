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


def test_routing_scope_ignores_dirty_models_and_refuses_a_changed_nested_fallback(tmp_path, monkeypatch):
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
    changed = copy.deepcopy(body)
    changed["routing"]["fallback"] = {
        "enabled": True,
        "heavy": route("spare", "must-not-copy-heavy", "high"),
        "light": route("spare", "must-not-copy-light", "low"),
    }
    # A changed routing.fallback is refused in this scope too; this endpoint never writes it.
    try:
        service.preview(changed)
    except ValueError as error:
        assert "fallback_preview" in str(error)
    else:
        raise AssertionError("a changed routing.fallback must be refused in the routing scope")

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


def _store_routing_fallback(service, name):
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"][name]["routing"]["fallback"] = {
        "enabled": True, "heavy": route("spare", "kept-heavy", "high"), "light": route("spare", "kept-light", "low")}
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    return copy.deepcopy(data["profiles"][name]["routing"]["fallback"])


def test_omitted_routing_fallback_keeps_the_stored_value_in_every_scope(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    kept = _store_routing_fallback(service, "p1")
    # Whole-page (no scope): a model and routing copy without routing.fallback.
    whole = copy.deepcopy(body)
    del whole["routing"]["fallback"]
    whole["models"]["title"] = route("operator", "new-title", "none")
    whole["model_targets"] = ["p1", "p2"]
    whole["routing"]["light"] = {"follow": "custom", "custom": route("operator", "copied-light", "low")}
    whole["routing_targets"] = ["p1", "p2"]
    assert service.apply(service.preview(whole)["plan_id"])["status"] == "applied"
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert after["p1"]["routing"]["fallback"] == kept
    assert after["p2"]["routing"]["light"]["custom"]["model"] == "copied-light"
    assert after["p2"]["routing"]["fallback"] == {"enabled": False, "heavy": None, "light": None}
    # Scoped saves without it are accepted too.
    for scope in ("models", "routing"):
        status = service.status()
        scoped = copy.deepcopy(body)
        scoped.update(expected_revision=status["revision"], save_scope=scope, model_targets=[], routing_targets=[])
        scoped["routing"] = copy.deepcopy(find_profile(status, "p1")["routing"])
        del scoped["routing"]["fallback"]
        service.apply(service.preview(scoped)["plan_id"])
        assert json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["p1"]["routing"]["fallback"] == kept


def test_an_older_client_that_sends_routing_fallback_must_still_send_it_unchanged(tmp_path, monkeypatch):
    service, cli, body = setup(tmp_path, monkeypatch)
    kept = _store_routing_fallback(service, "p1")
    for scope in (None, "routing", "models", "timeouts"):
        old = copy.deepcopy(body)
        if scope is not None:
            old["save_scope"] = scope
        old["routing"]["fallback"] = kept
        assert service.preview(old)["changes"] == [], scope
        old["routing"]["fallback"] = {"enabled": False, "heavy": None, "light": None}
        try:
            service.preview(old)
        except ValueError as error:
            assert "fallback_preview" in str(error), scope
        else:
            raise AssertionError(f"a changed routing.fallback must be refused in scope {scope}")



def test_an_older_timeout_save_compares_routing_fallback_without_resolving_models(tmp_path, monkeypatch):
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
    old = {
        "expected_revision": status["revision"], "profile": "p2", "save_scope": "timeouts",
        "models": copy.deepcopy(p1["models"]), "model_targets": [],
        "routing": copy.deepcopy(initial), "routing_targets": [],
        "routing_profiles": [row["name"] for row in status["profiles"] if row["routing"]["enabled"]],
        "timeout_updates": [],
    }
    assert "p2" not in json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert service.preview(copy.deepcopy(old))["changes"] == []
    old["routing"]["fallback"] = {"enabled": True, "heavy": route("spare", "h", "high"), "light": route("spare", "l", "low")}
    with pytest.raises(ValueError, match="fallback_preview"):
        service.preview(old)
