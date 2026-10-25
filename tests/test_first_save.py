"""First save must CAS against raw config, not normalized skill-list views."""
import copy


import pytest
import yaml

from model_router.service import Service, RevisionConflict, SKILL_NAME
from model_router.timeouts import read_timeouts
from test_integration import make_home
from test_role_timeouts import _package


@pytest.mark.parametrize("raw", [Ellipsis, None, "", "[]", ["unrelated", "unrelated"], '["unrelated", "unrelated"]'])
@pytest.mark.parametrize("scope", [None, "routing"])
def test_first_save_reconciles_uninitialized_skill_list_with_raw_cas(tmp_path, raw, scope):
    root = make_home(tmp_path)
    config = root / "config.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    if raw is Ellipsis:
        data.pop("skills")  # New installs normally omit skills.disabled entirely.
    else:
        data["skills"]["disabled"] = raw
    data["unrelated"] = {"keep": "unchanged"}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    package = _package(root)
    (package / "routing.py").write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    service = Service(root)
    status = service.status()
    row = status["profiles"][0]
    models = copy.deepcopy(row["models"])
    models["main"]["model"] = "first-save-main"
    body = {
        "expected_revision": status["revision"], "profile": "default",
        "models": models, "model_targets": ["default"] if scope is None else [],
        # The complete native package now correctly derives default routing ON;
        # this test explicitly chooses OFF and must submit matching membership.
        "routing": {**row["routing"], "enabled": False}, "routing_profiles": [], "routing_targets": [],
    }
    if scope:
        body["save_scope"] = scope
    else:
        body["timeout_updates"] = [{
            "profile": "default", "expected_revision": 0,
            "delegate_total_seconds": 120, "routed_light_total_seconds": 1800,
            "routed_heavy_total_seconds": 7200,
        }]
    plan = service.preview(body)
    # Apply in a fresh instance, like the two separate native CLI requests.
    receipt = Service(root).apply(plan["plan_id"])
    assert receipt["status"] == "applied", receipt
    actual = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert SKILL_NAME in actual["skills"]["disabled"]
    assert actual["unrelated"] == {"keep": "unchanged"}
    if raw not in (Ellipsis, None, "", "[]"):
        assert "unrelated" in actual["skills"]["disabled"]
    if scope is None:
        assert actual["model"]["default"] == "first-save-main"
        assert read_timeouts(root)["routed_heavy_total_seconds"] == 7200
    else:
        assert actual["model"]["default"] == "heavy-test"
        assert read_timeouts(root)["revision"] == 0
    assert not Service(root).status()["profiles"][0]["drift"]


def test_raw_skill_list_change_after_preview_still_blocks_all_writes(tmp_path):
    root = make_home(tmp_path)
    config = root / "config.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data.pop("skills")
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    service = Service(root)
    status = service.status()
    row = status["profiles"][0]
    plan = service.preview({
        "expected_revision": status["revision"], "profile": "default",
        "models": row["models"], "model_targets": ["default"],
        "routing": row["routing"], "routing_profiles": [], "routing_targets": [],
    })
    data["skills"] = {"disabled": []}  # Same logical view, different raw CAS state.
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    before = config.read_bytes()
    with pytest.raises(RevisionConflict):
        Service(root).apply(plan["plan_id"])
    assert config.read_bytes() == before
    assert not service.store_path.exists()
