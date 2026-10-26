"""Retain apply-time profile validation independently of local skill files."""
import copy
import json

import pytest

from model_router.service import Service, ServiceError
from test_combined_preview import setup, body
from test_fallback_service import confirmation, route


MODES = [(None, False), ("routing", False), (None, True)]


def plan_for(service, combined, scope):
    proposal = body(service)
    proposal["routing_profiles"] = ["default", "p1"]
    proposal["routing_targets"] = ["p1"]
    proposal["routing"]["heavy"] = {"follow": "custom", "custom": route("operator", "new-heavy", "high")}
    if scope:
        proposal["save_scope"] = scope
    if combined:
        proposal["fallback_updates"] = [{"profile": "default", "native_fallback": {
            "enabled": True, "chain": [{"provider": "xiaomi", "model": "spare"}],
        }}]
        proposal["fallback_confirmations"] = [confirmation("native", "default")]
    return service.preview(proposal)


def fixture(tmp_path, monkeypatch):
    service, fake, root = setup(tmp_path, monkeypatch)
    service.initialize(["default", "p1"])
    fake.calls.clear()
    return service, fake, root


@pytest.mark.parametrize(("scope", "combined"), MODES)
@pytest.mark.parametrize("mutation", ["delete_config", "rename_profile"])
def test_canonical_only_target_loss_blocks_all_persistence(tmp_path, monkeypatch, scope, combined, mutation):
    service, fake, root = fixture(tmp_path, monkeypatch)
    plan = plan_for(service, combined, scope)
    persisted = json.loads((service.store_path.parent / "plans" / (plan["plan_id"] + ".json")).read_text())
    assert "p1" not in persisted["snapshots"]
    assert all(w["profile"] != "p1" for w in persisted["writes"])
    before = service.store_path.read_bytes()
    recent = service.store_path.parent / "recent_apply.json"
    receipt_before = recent.read_bytes() if recent.exists() else None
    values = copy.deepcopy(fake.values)
    if mutation == "delete_config":
        (root / "profiles/p1/config.yaml").unlink()
    else:
        (root / "profiles/p1").rename(root / "profiles/renamed")
    with pytest.raises(ValueError, match="existing config-backed profile"):
        Service(root, writer=fake.write).apply(plan["plan_id"])
    assert service.store_path.read_bytes() == before
    assert (recent.read_bytes() if recent.exists() else None) == receipt_before
    assert fake.values == values and fake.calls == []
    with pytest.raises(ServiceError, match="consumed"):
        Service(root, writer=fake.write).apply(plan["plan_id"])
    assert not list(root.rglob("skills/adaptive-coding-orchestration/SKILL.md"))


@pytest.mark.parametrize(("scope", "combined"), MODES)
def test_valid_canonical_only_target_still_saves_without_skill_copies(tmp_path, monkeypatch, scope, combined):
    service, fake, root = fixture(tmp_path, monkeypatch)
    plan = plan_for(service, combined, scope)
    assert Service(root, writer=fake.write).apply(plan["plan_id"])["status"] == "applied"
    assert service.routing_config("p1")["heavy"]["model"] == "new-heavy"
    assert all(name != "p1" for name, _key, _value in fake.calls)
    assert not list(root.rglob("skills/adaptive-coding-orchestration/SKILL.md"))
