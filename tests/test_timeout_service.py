"""Total-runtime settings compose with existing one-shot model/fallback plans."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from test_service import setup_home
from model_router.service import Service, RevisionConflict, SKILL_NAME
from model_router.timeouts import read_timeouts, timeout_digest, write_timeouts


def fixture(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    monkeypatch.setattr(Service, "_timeout_enforcement_available", lambda self, profile: True)
    service.initialize(["p1"])
    cli.calls.clear()
    return service, cli, root


def body_for(service, profile="p1", **extra):
    status = service.status()
    row = next(row for row in status["profiles"] if row["name"] == profile)
    return {
        "expected_revision": status["revision"], "profile": profile,
        "models": copy.deepcopy(row["models"]), "model_targets": [],
        "routing": copy.deepcopy(row["routing"]), "routing_targets": [],
        "routing_profiles": [row["name"] for row in status["profiles"] if row["routing"]["enabled"]],
        **extra,
    }


def update(profile="p1", revision=0, delegate=120, routed=7200):
    return {"profile": profile, "expected_revision": revision,
            "delegate_total_seconds": delegate, "routed_total_seconds": routed}


def test_timeout_only_plan_writes_only_selected_profile_not_models_or_native_inactivity(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    model_store_before = service.store_path.read_bytes()
    native_config_before = {p: (service._profile_home(p) / "config.yaml").read_bytes() for p in ("default", "p1", "p2")}
    plan = service.preview(body_for(service, timeout_updates=[update()]))
    assert [item["field"] for item in plan["changes"]] == ["timeouts"]
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    assert receipt["applied"] == [{"profile": "p1", "key": "model-router.timeouts"}]
    assert read_timeouts(service._profile_home("p1"))["routed_total_seconds"] == 7200
    assert read_timeouts(service._profile_home("p1"))["delegate_total_seconds"] == 120
    assert service.store_path.read_bytes() == model_store_before
    assert not (service._profile_home("p2") / "plugin-data/model-router/timeouts.json").exists()
    assert cli.calls == []
    assert native_config_before == {p: (service._profile_home(p) / "config.yaml").read_bytes() for p in native_config_before}
    with pytest.raises(RuntimeError):
        service.apply(plan["plan_id"])


def test_timeout_config_drift_aborts_before_other_settings_writes(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    body = body_for(service, timeout_updates=[update()])
    body["model_targets"] = ["p1"]
    body["models"]["main"]["model"] = "new-heavy"
    plan = service.preview(body)
    home = service._profile_home("p1")
    write_timeouts(home, {"delegate_total_seconds": 0, "routed_total_seconds": 4000}, expected_digest=timeout_digest(home), expected_revision=0)
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert service.store_path.read_bytes() == before
    assert cli.calls == []


def test_timeout_stale_ui_revision_and_unsupported_enforcement_are_rejected(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    home = service._profile_home("p1")
    write_timeouts(home, {"delegate_total_seconds": 0, "routed_total_seconds": 4000}, expected_digest=timeout_digest(home), expected_revision=0)
    with pytest.raises(RevisionConflict):
        service.preview(body_for(service, timeout_updates=[update(revision=0)]))
    monkeypatch.setattr(Service, "_timeout_enforcement_available", lambda self, profile: False)
    with pytest.raises(ValueError, match="timeout"):
        service.preview(body_for(service, timeout_updates=[update(revision=1)]))
    assert service.status()["profiles"][1]["timeouts"]["editable"] is False


@pytest.mark.parametrize("updates", [None, {}, [update(), update()], [update(profile="../p1")], [{**update(), "unknown": 1}], [update(delegate=True)], [update(routed=-1)], [update(revision=True)]])
def test_invalid_timeout_updates_are_rejected_without_write(tmp_path, monkeypatch, updates):
    service, cli, root = fixture(tmp_path, monkeypatch)
    with pytest.raises((ValueError, RuntimeError)):
        service.preview(body_for(service, timeout_updates=updates))
    assert cli.calls == []
    assert not (service._profile_home("p1") / "plugin-data/model-router/timeouts.json").exists()


def test_models_and_fallback_only_saves_preserve_runtime_limits(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    home = service._profile_home("p1")
    write_timeouts(home, {"delegate_total_seconds": 0, "routed_total_seconds": 0}, expected_digest=timeout_digest(home), expected_revision=0)
    before = timeout_digest(home)
    plan = service.preview(body_for(service))
    assert service.apply(plan["plan_id"])["status"] == "no_change"
    assert timeout_digest(home) == before
    route = service.routing_config("p1")
    assert route["timeout_seconds"] == 0
    assert route["delegate_timeout_seconds"] == 0


def test_combined_fallback_plan_retains_timeout_write_and_cas(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    # A routing fallback OFF update needs no paid-route consent and composes
    # through the real fallback plan builder, not a sequential apply.
    body = body_for(service, timeout_updates=[update()], fallback_updates=[{
        "profile": "p1", "routing_fallback": {"enabled": False, "heavy": None, "light": None}
    }], fallback_confirmations=[])
    plan = service.preview(body)
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    assert read_timeouts(service._profile_home("p1"))["revision"] == 1
    assert cli.calls == []


def test_timeout_write_failure_is_partial_not_success(tmp_path, monkeypatch):
    from model_router import service as module
    service, cli, root = fixture(tmp_path, monkeypatch)
    plan = service.preview(body_for(service, timeout_updates=[update()]))
    monkeypatch.setattr(module.timeouts, "write_timeouts", lambda *a, **kw: (_ for _ in ()).throw(OSError("fixture failure")))
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "partial"
    assert receipt["applied"] == []
    assert receipt["remaining"] == [{"profile": "p1", "key": "model-router.timeouts"}]


def test_timeout_updates_use_each_targets_own_revision(tmp_path, monkeypatch):
    service, _cli, _root = fixture(tmp_path, monkeypatch)
    p2 = service._profile_home("p2")
    for routed in (4000, 5000):
        current = read_timeouts(p2)
        write_timeouts(p2, {"delegate_total_seconds": 0, "routed_total_seconds": routed},
                       expected_digest=timeout_digest(p2), expected_revision=current["revision"])

    preview = service.preview(body_for(service, timeout_updates=[
        update("p1", revision=0, delegate=120, routed=7200),
        update("p2", revision=2, delegate=240, routed=10800),
    ]))
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    assert receipt["applied"] == [
        {"profile": "p1", "key": "model-router.timeouts"},
        {"profile": "p2", "key": "model-router.timeouts"},
    ]
    assert read_timeouts(service._profile_home("p1")) == {
        "schema": 1, "delegate_total_seconds": 120, "routed_total_seconds": 7200, "revision": 1,
    }
    assert read_timeouts(p2) == {
        "schema": 1, "delegate_total_seconds": 240, "routed_total_seconds": 10800, "revision": 3,
    }


def test_unchanged_explicit_timeout_target_is_persisted_as_cas_guard(tmp_path, monkeypatch):
    service, cli, _root = fixture(tmp_path, monkeypatch)
    body = body_for(service, timeout_updates=[update("p2", revision=0, delegate=0, routed=3600)])
    preview = service.preview(body)
    persisted = json.loads((service.store_path.parent / "plans" / f"{preview['plan_id']}.json").read_text(encoding="utf-8"))

    assert preview["changes"] == []
    assert persisted["timeout_writes"] == [{
        "profile": "p2", "key": "model-router.timeouts", "before": "MISSING",
        "before_values": {"delegate_total_seconds": 0.0, "routed_total_seconds": 3600.0},
        "expected_revision": 0,
        "after": {"delegate_total_seconds": 0.0, "routed_total_seconds": 3600.0},
        "write_required": False,
    }]
    store_before = service.store_path.read_bytes()
    p1 = service._profile_home("p1")
    p2 = service._profile_home("p2")
    write_timeouts(p2, {"delegate_total_seconds": 0, "routed_total_seconds": 4000},
                   expected_digest=timeout_digest(p2), expected_revision=0)
    p2_before = (p2 / "plugin-data/model-router/timeouts.json").read_bytes()

    with pytest.raises(RevisionConflict):
        service.apply(preview["plan_id"])

    assert service.store_path.read_bytes() == store_before
    assert timeout_digest(p1) == "MISSING"
    assert (p2 / "plugin-data/model-router/timeouts.json").read_bytes() == p2_before
    assert cli.calls == []


def test_non_source_timeout_race_aborts_all_targets_before_any_other_write(tmp_path, monkeypatch):
    service, cli, _root = fixture(tmp_path, monkeypatch)
    body = body_for(service, timeout_updates=[
        update("p1", revision=0, delegate=120, routed=7200),
        update("p2", revision=0, delegate=240, routed=10800),
    ])
    preview = service.preview(body)
    p1 = service._profile_home("p1")
    p2 = service._profile_home("p2")
    # A competing writer changes the non-source target after preview.
    write_timeouts(p2, {"delegate_total_seconds": 0, "routed_total_seconds": 4000},
                   expected_digest=timeout_digest(p2), expected_revision=0)
    store_before = service.store_path.read_bytes()
    p1_before = timeout_digest(p1)
    p2_before = (p2 / "plugin-data/model-router/timeouts.json").read_bytes()
    configs_before = {name: (service._profile_home(name) / "config.yaml").read_bytes()
                      for name in ("default", "p1", "p2")}
    cli_values_before = copy.deepcopy(cli.values)

    with pytest.raises(RevisionConflict):
        service.apply(preview["plan_id"])

    assert service.store_path.read_bytes() == store_before
    assert timeout_digest(p1) == p1_before
    assert (p2 / "plugin-data/model-router/timeouts.json").read_bytes() == p2_before
    assert configs_before == {name: (service._profile_home(name) / "config.yaml").read_bytes()
                              for name in configs_before}
    assert cli.values == cli_values_before
    assert cli.calls == []


def test_second_timeout_target_failure_returns_exact_partial_receipt(tmp_path, monkeypatch):
    from model_router import service as module

    service, cli, _root = fixture(tmp_path, monkeypatch)
    original_write = module.timeouts.write_timeouts
    calls = []

    def fail_second(home, values, **kwargs):
        calls.append(Path(home).name)
        if len(calls) == 2:
            raise OSError("second target failure")
        return original_write(home, values, **kwargs)

    monkeypatch.setattr(module.timeouts, "write_timeouts", fail_second)
    preview = service.preview(body_for(service, timeout_updates=[
        update("p1", revision=0, delegate=120, routed=7200),
        update("p2", revision=0, delegate=240, routed=10800),
    ]))

    receipt = service.apply(preview["plan_id"])

    assert calls == ["p1", "p2"]
    assert receipt["status"] == "partial"
    assert receipt["applied"] == [{"profile": "p1", "key": "model-router.timeouts"}]
    assert receipt["remaining"] == [{"profile": "p2", "key": "model-router.timeouts"}]
    assert service.status()["recent_apply"] == receipt
    assert read_timeouts(service._profile_home("p1"))["revision"] == 1
    assert read_timeouts(service._profile_home("p2"))["revision"] == 0
    assert cli.calls == []


def test_unsupported_timeout_target_rejects_entire_preview_before_persisting_plan(tmp_path, monkeypatch):
    service, cli, _root = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(Service, "_timeout_enforcement_available",
                        lambda self, profile: profile == "p1")

    with pytest.raises(ValueError, match="timeout enforcement"):
        service.preview(body_for(service, timeout_updates=[
            update("p1", revision=0), update("p2", revision=0),
        ]))

    assert not list((service.store_path.parent / "plans").glob("*.json"))
    assert not (service._profile_home("p1") / "plugin-data/model-router/timeouts.json").exists()
    assert not (service._profile_home("p2") / "plugin-data/model-router/timeouts.json").exists()
    assert cli.calls == []


@pytest.mark.parametrize("updates", [
    [update("p1", revision=0), update("p1", revision=0, delegate=240)],
    [update("unknown", revision=0)],
])
def test_duplicate_or_unknown_timeout_targets_are_rejected(tmp_path, monkeypatch, updates):
    service, cli, _root = fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        service.preview(body_for(service, timeout_updates=updates))

    assert not list((service.store_path.parent / "plans").glob("*.json"))
    assert cli.calls == []


def test_timeout_scope_preserves_canonical_config_and_drifted_skill_bytes(tmp_path, monkeypatch):
    service, cli, _root = fixture(tmp_path, monkeypatch)
    p1 = service._profile_home("p1")
    store_before = service.store_path.read_bytes()
    config_before = {name: (service._profile_home(name) / "config.yaml").read_bytes()
                     for name in ("default", "p1", "p2")}
    skill = p1 / "skills" / SKILL_NAME / "SKILL.md"
    skill_before = skill.read_bytes()
    # Existing drift must not make a timeout-only save reconcile routing.
    cli.values["p1"]["skills.disabled"] = [SKILL_NAME, "unrelated-disabled-skill"]
    values_before = copy.deepcopy(cli.values)
    cli.calls.clear()
    body = body_for(service, timeout_updates=[update()])
    body["save_scope"] = "timeouts"
    body["models"] = {"dirty": "ignored model draft"}
    body["routing"] = {"dirty": "ignored routing draft"}
    body["routing_profiles"] = ["default"]

    preview = service.preview(body)
    receipt = service.apply(preview["plan_id"])

    assert receipt["status"] == "applied"
    assert service.store_path.read_bytes() == store_before
    assert config_before == {name: (service._profile_home(name) / "config.yaml").read_bytes()
                             for name in config_before}
    assert skill.read_bytes() == skill_before
    assert cli.values == values_before
    assert cli.calls == []
    assert read_timeouts(p1)["routed_total_seconds"] == 7200


@pytest.mark.parametrize(("scope", "field", "value"), [
    ("models", "routing_targets", ["p2"]),
    ("models", "timeout_updates", [update("p1", revision=0)]),
    ("models", "fallback_updates", [{"profile": "p1", "routing_fallback": {"enabled": False, "heavy": None, "light": None}}]),
    ("routing", "model_targets", ["p2"]),
    ("routing", "timeout_updates", [update("p1", revision=0)]),
    ("routing", "fallback_updates", [{"profile": "p1", "routing_fallback": {"enabled": False, "heavy": None, "light": None}}]),
    ("timeouts", "model_targets", ["p2"]),
    ("timeouts", "routing_targets", ["p2"]),
    ("timeouts", "fallback_updates", [{"profile": "p1", "routing_fallback": {"enabled": False, "heavy": None, "light": None}}]),
])
def test_section_scopes_reject_cross_scope_targets_and_updates(tmp_path, monkeypatch, scope, field, value):
    service, cli, _root = fixture(tmp_path, monkeypatch)
    body = body_for(service)
    body["save_scope"] = scope
    body[field] = value

    with pytest.raises(ValueError, match="scope"):
        service.preview(body)

    assert not list((service.store_path.parent / "plans").glob("*.json"))
    assert cli.calls == []


@pytest.mark.parametrize("scope", [None, "", "all", "Models", [], {}])
def test_unknown_or_ambiguous_save_scope_is_rejected(tmp_path, monkeypatch, scope):
    service, cli, _root = fixture(tmp_path, monkeypatch)
    body = body_for(service)
    body["save_scope"] = scope

    with pytest.raises(ValueError, match="save_scope"):
        service.preview(body)

    assert not list((service.store_path.parent / "plans").glob("*.json"))
    assert cli.calls == []
