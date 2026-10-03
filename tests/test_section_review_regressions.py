"""Deterministic regressions for the independent section-save review."""
from pathlib import Path
import pytest
from model_router import service as module
from model_router.timeouts import read_timeouts, timeout_digest
from test_timeout_service import fixture, body_for, update


@pytest.mark.parametrize("race", ["values", "enforcement"])
def test_noop_target_race_after_real_write_is_partial_not_applied(tmp_path, monkeypatch, race):
    service, cli, root = fixture(tmp_path, monkeypatch)
    p1, p2 = service._profile_home("p1"), service._profile_home("p2")
    plan = service.preview(body_for(service, save_scope="timeouts", timeout_updates=[
        update("p1", delegate=120, routed=7200), update("p2", delegate=0, routed=3600),
    ]))
    original = module.timeouts.write_timeouts
    def write_then_race(home, values, **kwargs):
        result = original(home, values, **kwargs)
        assert Path(home) == p1
        if race == "values":
            original(p2, {"delegate_total_seconds": 0, "routed_total_seconds": 0},
                     expected_digest=timeout_digest(p2), expected_revision=0)
        else:
            monkeypatch.setattr(module.Service, "_timeout_enforcement_available", lambda self, profile: profile != "p2")
        return result
    monkeypatch.setattr(module.timeouts, "write_timeouts", write_then_race)
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "partial"
    assert receipt["applied"] == [{"profile": "p1", "key": "model-router.timeouts"}]
    assert read_timeouts(p1)["routed_total_seconds"] == 7200
    assert read_timeouts(p2)["routed_total_seconds"] == (0 if race == "values" else 3600)
    assert cli.calls == []
    with pytest.raises(RuntimeError): service.apply(plan["plan_id"])


def test_quiet_noop_target_does_not_create_file_or_increment_revision(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    p2 = service._profile_home("p2")
    before = timeout_digest(p2)
    plan = service.preview(body_for(service, save_scope="timeouts", timeout_updates=[
        update("p1", delegate=120, routed=7200), update("p2", delegate=0, routed=3600),
    ]))
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    assert receipt["applied"] == [{"profile": "p1", "key": "model-router.timeouts"}]
    assert timeout_digest(p2) == before == "MISSING"
    assert read_timeouts(p2)["revision"] == 0
    assert cli.calls == []


def test_changed_target_final_readback_race_is_still_partial(tmp_path, monkeypatch):
    service, cli, root = fixture(tmp_path, monkeypatch)
    home = service._profile_home("p1")
    plan = service.preview(body_for(service, save_scope="timeouts", timeout_updates=[update()]))
    original = module.timeouts.write_timeouts
    def write_then_replace(home, values, **kwargs):
        result = original(home, values, **kwargs)
        original(home, {"delegate_total_seconds": 0, "routed_total_seconds": 0},
                 expected_digest=timeout_digest(home), expected_revision=1)
        return result
    monkeypatch.setattr(module.timeouts, "write_timeouts", write_then_replace)
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "partial"
    assert receipt["applied"] == [{"profile": "p1", "key": "model-router.timeouts"}]
    assert read_timeouts(home)["revision"] == 2
    assert read_timeouts(home)["routed_total_seconds"] == 0
    assert cli.calls == []
