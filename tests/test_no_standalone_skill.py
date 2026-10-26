"""Routing saves manage settings, never install or own standalone skill files."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from model_router.service import SKILL_NAME, RevisionConflict, Service, ServiceError
from test_service import find_profile, setup_home


def standalone(root: Path, name: str) -> Path:
    home = root if name == "default" else root / "profiles" / name
    return home / "skills" / SKILL_NAME / "SKILL.md"


def body(service: Service, scope, selected=None):
    status = service.status()
    row = find_profile(status, "p1")
    result = {
        "expected_revision": status["revision"], "profile": "p1",
        "models": copy.deepcopy(row["models"]), "model_targets": [],
        "routing": copy.deepcopy(row["routing"]),
        "routing_profiles": ["p1"] if selected is None else selected,
        "routing_targets": [],
    }
    if scope is not None:
        result["save_scope"] = scope
    return result


def initialize_without_copies(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root, writer=cli.writer)
    service.initialize(["p1"])
    # Establish the reported post-cleanup state on both the old and new code.
    for name in ("default", "p1", "p2"):
        standalone(root, name).unlink(missing_ok=True)
    cli.calls.clear()
    return root, cli, service


def test_initialize_never_creates_standalone_skill(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    original = copy.deepcopy(cli.values)
    Service(root, writer=cli.writer).initialize(["default", "p1", "p2"])
    assert not any(standalone(root, name).exists() for name in original)
    assert cli.calls == []
    assert cli.values == original


@pytest.mark.parametrize("scope", [None, "routing"])
def test_missing_skill_is_a_real_noop_not_a_repair_plan(tmp_path, monkeypatch, scope):
    root, cli, service = initialize_without_copies(tmp_path, monkeypatch)
    before = service.store_path.read_bytes()
    values = copy.deepcopy(cli.values)
    plan = service.preview(body(service, scope))
    assert plan["changes"] == []
    receipt = Service(root, writer=cli.writer).apply(plan["plan_id"])
    assert receipt["status"] == "no_change"
    assert service.store_path.read_bytes() == before
    assert cli.values == values and cli.calls == []
    assert not standalone(root, "p1").exists()
    with pytest.raises(ServiceError, match="consumed"):
        Service(root, writer=cli.writer).apply(plan["plan_id"])


@pytest.mark.parametrize("scope", [None, "routing"])
def test_real_routing_save_does_not_recreate_deleted_skill(tmp_path, monkeypatch, scope):
    root, cli, service = initialize_without_copies(tmp_path, monkeypatch)
    original = copy.deepcopy(cli.values)
    plan = service.preview(body(service, scope, selected=["p1", "p2"]))
    assert all(not change["field"].startswith("skills/") for change in plan["changes"])
    receipt = Service(root, writer=cli.writer).apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    assert service.routing_config("p2")["enabled"] is True
    assert not any(standalone(root, name).exists() for name in original)
    for name in original:
        assert {k: v for k, v in cli.values[name].items() if k != "skills.disabled"} == {
            k: v for k, v in original[name].items() if k != "skills.disabled"
        }


@pytest.mark.parametrize("scope", [None, "routing"])
def test_legacy_local_notes_are_not_owned_by_settings_save(tmp_path, monkeypatch, scope):
    root, cli, service = initialize_without_copies(tmp_path, monkeypatch)
    local = standalone(root, "p1")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"profile-specific notes before preview\n")
    plan = service.preview(body(service, scope, selected=["p1", "p2"]))
    after = b"user-edited notes after preview\n"
    local.write_bytes(after)
    receipt = Service(root, writer=cli.writer).apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    assert local.read_bytes() == after
    assert not standalone(root, "p2").exists()


@pytest.mark.parametrize("scope", [None, "routing"])
def test_config_cas_still_blocks_all_writes(tmp_path, monkeypatch, scope):
    root, cli, service = initialize_without_copies(tmp_path, monkeypatch)
    plan = service.preview(body(service, scope, selected=["p1", "p2"]))
    before = service.store_path.read_bytes()
    cli.values["p2"]["skills.disabled"] = ["external-change", SKILL_NAME]
    with pytest.raises(RevisionConflict):
        Service(root, writer=cli.writer).apply(plan["plan_id"])
    assert service.store_path.read_bytes() == before
    assert cli.calls == []
    assert not standalone(root, "p2").exists()


@pytest.mark.parametrize("snapshot", ["MISSING", "a" * 64])
def test_preupgrade_skill_copy_plan_is_rejected_before_writes(tmp_path, monkeypatch, snapshot):
    import json
    root, cli, service = initialize_without_copies(tmp_path, monkeypatch)
    plan = service.preview(body(service, "routing", selected=["p1", "p2"]))
    path = service.store_path.parent / "plans" / (plan["plan_id"] + ".json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["skill_snapshots"] = {"p1": snapshot}
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = service.store_path.read_bytes()
    with pytest.raises(RevisionConflict, match="legacy skill-copy plan"):
        Service(root, writer=cli.writer).apply(plan["plan_id"])
    assert cli.calls == [] and service.store_path.read_bytes() == before
    assert not standalone(root, "p1").exists()
    with pytest.raises(ServiceError, match="consumed"):
        Service(root, writer=cli.writer).apply(plan["plan_id"])


def test_saving_settings_never_reads_legacy_skill_contents(tmp_path, monkeypatch):
    root, cli, service = initialize_without_copies(tmp_path, monkeypatch)
    local = standalone(root, "p1")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"private user notes\n")
    original = Path.read_bytes

    def read(path):
        assert path != local, "settings service must not read or hash standalone skill content"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    plan = service.preview(body(service, "routing", selected=["p1", "p2"]))
    assert service.apply(plan["plan_id"])["status"] == "applied"
