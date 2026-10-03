"""Total-runtime settings compose with existing one-shot model/fallback plans."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from test_service import setup_home
from model_router.service import Service, RevisionConflict
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
