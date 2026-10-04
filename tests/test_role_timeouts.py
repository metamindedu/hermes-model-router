from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_router.service import RevisionConflict, Service
from test_service import setup_home


def _service(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["p1"])
    return service


def _package(home: Path) -> Path:
    package = home / "plugins" / "model-router" / "model_router"
    package.mkdir(parents=True, exist_ok=True)
    (package / "timeouts.py").write_text("# installed base enforcement fixture\n", encoding="utf-8")
    (package / "native_watchdog.py").write_text("# installed base enforcement fixture\n", encoding="utf-8")
    return package


def _body(service: Service, profile: str = "p1", updates=None) -> dict:
    status = service.status()
    row = next(item for item in status["profiles"] if item["name"] == profile)
    return {
        "expected_revision": status["revision"],
        "profile": profile,
        "models": row["models"],
        "model_targets": [],
        "routing": row["routing"],
        "routing_targets": [],
        "routing_profiles": [item["name"] for item in status["profiles"] if item["routing"]["enabled"]],
        "timeout_updates": updates or [],
    }


def test_literal_marker_is_read_only_ast_checked_and_never_executes_module(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    package = _package(service._profile_home("p1"))
    marker = package / "routing.py"
    marker_payload = b"ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\nraise RuntimeError('must not execute')\n"
    marker.write_bytes(marker_payload)
    before = {path.name: path.read_bytes() for path in package.iterdir()}

    assert service._timeout_role_enforcement_available("p1") is True
    row = next(item for item in service.status()["profiles"] if item["name"] == "p1")

    assert row["timeouts"]["split_routing_supported"] is True
    assert row["timeouts"]["editable"] is True
    assert row["timeouts"]["schema"] == 1
    assert before == {path.name: path.read_bytes() for path in package.iterdir()}


@pytest.mark.parametrize("source", [
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = False\n",
    "if True:\n    ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n",
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = bool(True)\n",
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\nROUTED_ROLE_TIMEOUTS_SUPPORTED = False\n",
])
def test_role_capability_requires_one_top_level_literal_true_marker(tmp_path, monkeypatch, source):
    service = _service(tmp_path, monkeypatch)
    package = _package(service._profile_home("p1"))
    (package / "routing.py").write_text(source, encoding="utf-8")

    assert service._timeout_role_enforcement_available("p1") is False


def test_missing_role_marker_is_explicitly_readonly_without_changing_base_editability(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    _package(service._profile_home("p1"))

    row = next(item for item in service.status()["profiles"] if item["name"] == "p1")

    assert row["timeouts"]["split_routing_supported"] is False
    assert row["timeouts"]["editable"] is True
    with pytest.raises(ValueError, match="timeout enforcement"):
        service.preview(_body(service, updates=[{
            "profile": "p1", "expected_revision": 0,
            "delegate_total_seconds": 0, "routed_light_total_seconds": 1800,
            "routed_heavy_total_seconds": 7200,
        }]))
    legacy = service.preview(_body(service, updates=[{
        "profile": "p1", "expected_revision": 0,
        "delegate_total_seconds": 0, "routed_total_seconds": 3600,
    }]))
    assert legacy["changes"] == []


def test_role_marker_path_symlink_is_rejected_even_when_target_stays_inside_profile(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    package = _package(service._profile_home("p1"))
    target = package / "routing-source.py"
    target.write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    marker = package / "routing.py"
    try:
        marker.symlink_to(target)
    except NotImplementedError:
        original_lstat = Path.lstat

        def linked_lstat(path):
            if path == marker:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", linked_lstat)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            original_lstat = Path.lstat

            def linked_lstat(path):
                if path == marker:
                    return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)
                return original_lstat(path)

            monkeypatch.setattr(Path, "lstat", linked_lstat)
        else:
            raise

    assert service._timeout_role_enforcement_available("p1") is False
    assert target.read_text(encoding="utf-8") == "ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n"


def test_split_capability_disappearing_at_apply_preflight_prevents_timeout_write(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    package = _package(service._profile_home("p1"))
    (package / "routing.py").write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    monkeypatch.setattr(Service, "_timeout_role_enforcement_available", lambda self, profile: True)
    preview = service.preview(_body(service, updates=[{
        "profile": "p1", "expected_revision": 0,
        "delegate_total_seconds": 120, "routed_light_total_seconds": 1800,
        "routed_heavy_total_seconds": 7200,
    }]))
    monkeypatch.setattr(Service, "_timeout_role_enforcement_available", lambda self, profile: False)

    with pytest.raises(RevisionConflict, match="timeout enforcement"):
        service.apply(preview["plan_id"])
    assert not (service._profile_home("p1") / "plugin-data/model-router/timeouts.json").exists()


def test_split_capability_is_rechecked_immediately_before_physical_write(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    package = _package(service._profile_home("p1"))
    (package / "routing.py").write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    body = _body(service, updates=[{
        "profile": "p1", "expected_revision": 0,
        "delegate_total_seconds": 120, "routed_light_total_seconds": 1800,
        "routed_heavy_total_seconds": 7200,
    }])
    checks = 0

    def available(self, profile):
        nonlocal checks
        checks += 1
        return checks <= 3  # preview eligibility/snapshot and apply preflight only

    monkeypatch.setattr(Service, "_timeout_role_enforcement_available", available)
    preview = service.preview(body)
    receipt = service.apply(preview["plan_id"])

    assert checks == 4
    assert receipt["status"] == "partial"
    assert receipt["applied"] == []
    assert not (service._profile_home("p1") / "plugin-data/model-router/timeouts.json").exists()


def test_split_noop_rechecks_role_capability_at_final_noop_guard(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    package = _package(service._profile_home("p1"))
    (package / "routing.py").write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    body = _body(service, updates=[{
        "profile": "p1", "expected_revision": 0,
        "delegate_total_seconds": 0, "routed_light_total_seconds": 3600,
        "routed_heavy_total_seconds": 3600,
    }])
    checks = 0

    def available(self, profile):
        nonlocal checks
        checks += 1
        return checks <= 3  # preview eligibility/snapshot and apply preflight

    monkeypatch.setattr(Service, "_timeout_role_enforcement_available", available)
    preview = service.preview(body)
    assert preview["changes"] == []

    with pytest.raises(RevisionConflict, match="timeout enforcement"):
        service.apply(preview["plan_id"])

    assert checks == 4
    assert not (service._profile_home("p1") / "plugin-data/model-router/timeouts.json").exists()


def test_split_capability_lost_after_real_write_must_not_report_applied(tmp_path, monkeypatch):
    from model_router import service as module
    service = _service(tmp_path, monkeypatch)
    home = service._profile_home("p1")
    package = _package(home)
    marker = package / "routing.py"
    marker.write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    body = _body(service, updates=[{
        "profile": "p1", "expected_revision": 0,
        "delegate_total_seconds": 120, "routed_light_total_seconds": 1800,
        "routed_heavy_total_seconds": 7200,
    }])
    body["save_scope"] = "timeouts"
    preview = service.preview(body)
    original = module.timeouts.write_timeouts
    def write_then_lose_role_support(home, values, **kwargs):
        result = original(home, values, **kwargs)
        marker.write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = False\n", encoding="utf-8")
        return result
    monkeypatch.setattr(module.timeouts, "write_timeouts", write_then_lose_role_support)
    receipt = service.apply(preview["plan_id"])
    assert receipt["status"] == "partial"
    assert receipt["applied"] == [{"profile": "p1", "key": "model-router.timeouts"}]
    assert module.timeouts.read_timeouts(home)["routed_heavy_total_seconds"] == 7200
    assert service._timeout_role_enforcement_available("p1") is False
    with pytest.raises(RuntimeError): service.apply(preview["plan_id"])


def test_timeout_status_split_capability_is_boolean_for_every_profile(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)

    rows = service.status()["profiles"]

    assert rows
    assert all(isinstance(row["timeouts"]["split_routing_supported"], bool) for row in rows)
