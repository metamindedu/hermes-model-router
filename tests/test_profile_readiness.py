from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_router import effective_config
from model_router.service import RevisionConflict, Service


SELECTION_KEYS = ("plugins.enabled", "plugins.disabled")
SOURCE = "https://github.com/metamindedu/hermes-model-router"


def _selection(*, enabled=None, disabled=None, managed=(), warnings=(), available=True):
    effective = {"plugins.enabled": enabled, "plugins.disabled": disabled} if available else None
    return effective_config.make_key_snapshot(
        keys=SELECTION_KEYS,
        raw={"plugins.enabled": enabled, "plugins.disabled": disabled},
        effective=effective,
        managed_keys=managed,
        warnings=warnings,
    )


def _manifest(*, release=False, version="0.4.7"):
    if not release:
        return f"name: model-router\nversion: {version}\n"
    return (
        f"name: model-router\nversion: {version}\n"
        "provides_tools:\n  - coding_route\n"
        "provides_hooks:\n"
        "  - pre_api_request\n  - post_api_request\n  - api_request_error\n"
        "  - pre_tool_call\n  - post_tool_call\n  - subagent_start\n  - subagent_stop\n"
        "provides_middleware:\n  - tool_execution\n  - llm_request\n"
        "requires_env: []\n"
    )


def _install_package(home: Path, *, marker="ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", release=False):
    package = home / "plugins" / "model-router"
    code = package / "model_router"
    code.mkdir(parents=True)
    (package / "plugin.yaml").write_text(_manifest(release=release), encoding="utf-8")
    (package / "__init__.py").write_text("raise RuntimeError('foreign entrypoint executed')\n", encoding="utf-8")
    # These statements are syntactically valid but must never be executed.
    (code / "__init__.py").write_text("raise RuntimeError('foreign plugin executed')\n", encoding="utf-8")
    (code / "timeouts.py").write_text("raise RuntimeError('foreign timeout module executed')\n", encoding="utf-8")
    (code / "native_watchdog.py").write_text("raise RuntimeError('foreign watchdog executed')\n", encoding="utf-8")
    if marker is not None:
        (code / "routing.py").write_text(marker, encoding="utf-8")
    if release:
        (package / "pyproject.toml").write_text(
            '[project]\nname = "hermes-model-router"\nversion = "0.4.7"\n'
            'dependencies = ["PyYAML>=6,<7"]\n', encoding="utf-8"
        )
    return package


def _snapshot_tree(root: Path):
    rows = {}
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*"), key=lambda item: str(item)):
        if path.is_file() and not path.is_symlink():
            rows[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif path.is_dir() and not path.is_symlink():
            rows[str(path.relative_to(root))] = "<dir>"
        else:
            rows[str(path.relative_to(root))] = "<link>"
    return rows


def _service(tmp_path, monkeypatch, *, selections=None, skills=None, installed=(), store=None):
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "config.yaml").write_text("plugins: {}\n", encoding="utf-8")
    profiles = root / "profiles"
    profiles.mkdir()
    homes = {"default": root}
    for name in ("p1",):
        home = profiles / name
        home.mkdir()
        (home / "config.yaml").write_text("plugins: {}\n", encoding="utf-8")
        homes[name] = home
    for name in installed:
        _install_package(homes[name])

    service = Service(root=root)
    empty_models = {
        "main": {"provider": "openai-codex", "model": "main-model", "reasoning": "high"},
        "delegation": {"provider": "openai-codex", "model": "light-model", "reasoning": "max"},
        "compression": {"provider": "openai-codex", "model": "main-model", "reasoning": "high"},
        "title": {"provider": "openai-codex", "model": "main-model", "reasoning": "high"},
    }
    monkeypatch.setattr(service, "_actual_models", lambda _profile, tolerate=False: empty_models)
    skill_values = skills or {}
    monkeypatch.setattr(service, "_read_disabled", lambda profile: list(skill_values.get(profile, [])))
    monkeypatch.setattr(service, "_fallback_dto", lambda *_args: {
        "native": {}, "routing": {}, "delegation": {},
    })
    if store is not None:
        monkeypatch.setattr(service, "_load_store", lambda: store)

    snapshots = selections or {}

    def read_selection(profile_home, keys):
        assert tuple(keys) == SELECTION_KEYS
        name = Path(profile_home).name if Path(profile_home).name != "hermes" else "default"
        value = snapshots.get(name, _selection())
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(effective_config, "read_key_scoped", read_selection)
    return service, root, homes


def _row(service, profile="p1"):
    return next(item for item in service.status()["profiles"] if item["name"] == profile)


def _store_with_routing(profile: str, enabled: bool):
    models = {
        "main": {"provider": "openai-codex", "model": "main-model", "reasoning": "high"},
        "delegation": {"provider": "openai-codex", "model": "light-model", "reasoning": "max"},
        "compression": {"provider": "openai-codex", "model": "main-model", "reasoning": "high"},
        "title": {"provider": "openai-codex", "model": "main-model", "reasoning": "high"},
    }
    routing = {
        "enabled": enabled,
        "heavy": {"follow": "main", "custom": None},
        "light": {"follow": "delegation", "custom": None},
        "fallback": {"enabled": False, "heavy": None, "light": None},
    }
    return {"schema": 2, "revision": 1, "profiles": {profile: {
        "models": models, "routing": routing, "native_fallback": None,
        "delegation_fallback": None,
        "fallback_consent": {"native": None, "routing": None, "delegation": None},
    }}}


def test_status_readiness_distinguishes_ready_and_disabled_with_deny_wins(tmp_path, monkeypatch):
    selections = {
        "default": _selection(enabled=["model-router"]),
        "p1": _selection(enabled=["model-router"], disabled=["model-router"]),
    }
    service, _root, _homes = _service(
        tmp_path, monkeypatch, selections=selections, installed=("default", "p1")
    )

    rows = {row["name"]: row["readiness"] for row in service.status()["profiles"]}

    assert rows["default"]["state"] == "ready"
    assert rows["default"]["python"] == "enabled"
    assert rows["p1"]["state"] == "disabled"
    assert rows["p1"]["python"] == "disabled"
    assert "plugin_explicitly_disabled" in rows["p1"]["reason_codes"]
    assert set(rows["p1"]) == {
        "schema", "state", "reason_codes", "files", "python", "base_supported",
        "split_supported", "explicit_opt_out", "managed_selection", "version", "identity",
    }


def test_absent_package_is_missing_and_absent_allow_is_not_selected(tmp_path, monkeypatch):
    service, _root, _homes = _service(tmp_path, monkeypatch, selections={
        "default": _selection(enabled=["model-router"]),
        "p1": _selection(disabled=[]),
    })

    missing = _row(service, "default")["readiness"]
    not_selected = _row(service, "p1")["readiness"]

    assert missing["state"] == "missing"
    assert missing["files"] == "missing"
    assert missing["python"] == "enabled"
    assert "package_missing" in missing["reason_codes"]
    assert not_selected["state"] == "missing"
    assert not_selected["python"] == "not_enabled"
    assert "plugin_not_enabled" in not_selected["reason_codes"]


def test_supported_package_is_ready_while_route_and_skill_opt_outs_remain_unchanged(tmp_path, monkeypatch):
    service, _root, _homes = _service(
        tmp_path,
        monkeypatch,
        selections={"p1": _selection(enabled=["model-router"])},
        skills={"p1": ["adaptive-coding-orchestration", "model-router:adaptive-coding-orchestration"]},
        installed=("p1",),
        store=_store_with_routing("p1", False),
    )

    before = _snapshot_tree(service._profile_home("p1"))
    readiness = _row(service, "p1")["readiness"]
    after = _snapshot_tree(service._profile_home("p1"))

    assert readiness["state"] == "ready"
    assert readiness["python"] == "enabled"
    assert readiness["base_supported"] is True
    assert readiness["split_supported"] is True
    assert readiness["explicit_opt_out"] is True
    assert "routing_opt_out_preserved" in readiness["reason_codes"]
    assert before == after


def test_managed_effective_selection_can_be_observed_ready_without_setup_authority(tmp_path, monkeypatch):
    service, _root, _homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"], managed=("plugins.enabled",)),
    }, installed=("p1",))

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "ready"
    assert readiness["managed_selection"] is True
    assert "managed_selection" in readiness["reason_codes"]
    assert readiness["identity"] and re.fullmatch(r"[0-9a-f]{64}", readiness["identity"])


@pytest.mark.parametrize("snapshot, reason", [
    (_selection(enabled="${PLUGIN_ALLOW}"), "dynamic_selection_unsupported"),
    (_selection(enabled=[1]), "plugin_selection_invalid"),
    (_selection(enabled=["model-router"], available=False), "effective_selection_unavailable"),
    (_selection(enabled=["model-router"], warnings=("scoped_managed_provenance_unavailable",)), "managed_provenance_unavailable"),
])
def test_invalid_dynamic_or_unavailable_effective_selection_fails_closed(tmp_path, monkeypatch, snapshot, reason):
    service, _root, _homes = _service(tmp_path, monkeypatch, selections={"p1": snapshot}, installed=("p1",))

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "unsupported"
    assert readiness["python"] == "unknown"
    assert reason in readiness["reason_codes"]


def test_complete_package_without_allow_is_disabled_not_selected(tmp_path, monkeypatch):
    service, _root, _homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=None, disabled=[]),
    }, installed=("p1",))

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "disabled"
    assert readiness["python"] == "not_enabled"
    assert "plugin_not_enabled" in readiness["reason_codes"]


def test_oversized_manifest_and_source_are_unsupported_not_missing(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    })
    package = _install_package(homes["p1"])
    manifest = package / "plugin.yaml"
    manifest.write_bytes(b"x" * (64 * 1024 + 1))

    oversized_manifest = _row(service, "p1")["readiness"]
    assert oversized_manifest["state"] == "unsupported"
    assert oversized_manifest["files"] == "complete"
    assert "package_missing" not in oversized_manifest["reason_codes"]
    assert "manifest_invalid" in oversized_manifest["reason_codes"]

    manifest.write_text(_manifest(), encoding="utf-8")
    source = package / "model_router" / "timeouts.py"
    source.write_bytes(b"#" * (1024 * 1024 + 1))
    oversized_source = _row(service, "p1")["readiness"]
    assert oversized_source["state"] == "unsupported"
    assert "package_unreadable" in oversized_source["reason_codes"]
    assert "package_missing" not in oversized_source["reason_codes"]


def test_nonregular_package_file_is_unsafe_not_missing(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    })
    package = _install_package(homes["p1"])
    source = package / "model_router" / "timeouts.py"
    source.unlink()
    source.mkdir()

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "unsupported"
    assert readiness["files"] == "unsafe"
    assert "unsafe_package_path" in readiness["reason_codes"]
    assert "package_missing" not in readiness["reason_codes"]


def test_unreadable_optional_split_source_makes_readiness_unsupported(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    })
    package = _install_package(homes["p1"])
    (package / "model_router" / "routing.py").write_bytes(b"#" * (1024 * 1024 + 1))

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "unsupported"
    assert readiness["files"] == "complete"
    assert readiness["base_supported"] is True
    assert readiness["split_supported"] is False
    assert "package_unreadable" in readiness["reason_codes"]


def test_partial_package_and_wrong_manifest_are_unsupported_not_missing(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    })
    partial = homes["p1"] / "plugins" / "model-router"
    partial.mkdir(parents=True)
    (partial / "plugin.yaml").write_text("name: model-router\nversion: 0.4.7\n", encoding="utf-8")

    partial_readiness = _row(service, "p1")["readiness"]
    assert partial_readiness["state"] == "unsupported"
    assert partial_readiness["files"] == "partial"
    assert "package_partial" in partial_readiness["reason_codes"]

    shutil.rmtree(partial)
    _install_package(homes["p1"])
    (partial / "plugin.yaml").write_text("name: other-plugin\nversion: 0.4.7\n", encoding="utf-8")
    wrong_id = _row(service, "p1")["readiness"]
    assert wrong_id["state"] == "unsupported"
    assert "manifest_id_mismatch" in wrong_id["reason_codes"]


def test_unsafe_package_file_is_unsupported_without_following_link(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    }, installed=("p1",))
    source = homes["p1"] / "plugins" / "model-router" / "model_router" / "timeouts.py"
    outside = tmp_path / "outside.py"
    outside.write_text("raise RuntimeError('must not read')\n", encoding="utf-8")
    try:
        source.unlink()
        source.symlink_to(outside)
    except OSError:
        source.write_text("# keep fixture and simulate a reparse path\n", encoding="utf-8")
        original_lstat = Path.lstat

        def linked_lstat(path):
            if path == source:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", linked_lstat)

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "unsupported"
    assert readiness["files"] == "unsafe"
    assert "unsafe_package_path" in readiness["reason_codes"]
    assert outside.read_text(encoding="utf-8") == "raise RuntimeError('must not read')\n"


@pytest.mark.parametrize("marker", [
    None,
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = False\n",
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = bool(True)\n",
    "if True:\n    ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n",
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\nROUTED_ROLE_TIMEOUTS_SUPPORTED = False\n",
    "ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\ndef =\n",
])
def test_split_marker_is_unique_literal_ast_and_never_executes_plugin_code(tmp_path, monkeypatch, marker):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    })
    _install_package(homes["p1"], marker=marker)

    readiness = _row(service, "p1")["readiness"]

    assert readiness["base_supported"] is True
    assert readiness["split_supported"] is (marker == "ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n")
    assert readiness["state"] == "ready"
    assert "foreign plugin executed" not in json.dumps(readiness)
    if not readiness["split_supported"]:
        assert "split_marker_missing_or_invalid" in readiness["reason_codes"]
    assert not (homes["p1"] / "plugins" / "model-router" / "model_router" / "__pycache__").exists()


def test_unrelated_directory_entry_does_not_invalidate_profile_observation(tmp_path, monkeypatch):
    service, root, _homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    }, installed=("p1",))
    touched = False

    def read_and_touch(profile_home, keys):
        nonlocal touched
        if Path(profile_home).name == "p1" and not touched:
            touched = True
            (root / "unrelated-observer-note").write_text("incidental directory activity", encoding="utf-8")
        return _selection(enabled=["model-router"])

    monkeypatch.setattr(effective_config, "read_key_scoped", read_and_touch)
    observed = _row(service, "p1")["readiness"]
    assert observed["state"] == "ready"
    assert "profile_changed" not in observed["reason_codes"]


def test_profile_change_during_observation_is_unsupported(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    }, installed=("p1",))
    module = homes["p1"] / "plugins" / "model-router" / "model_router" / "timeouts.py"
    changed = False

    def mutate_after_snapshot(profile_home, keys):
        nonlocal changed
        result = _selection(enabled=["model-router"])
        if Path(profile_home).name == "p1" and not changed:
            changed = True
            module.write_text("# simulated concurrent replacement\n", encoding="utf-8")
        return result

    monkeypatch.setattr(effective_config, "read_key_scoped", mutate_after_snapshot)

    readiness = _row(service, "p1")["readiness"]

    assert readiness["state"] == "unsupported"
    assert readiness["identity"] is None
    assert "profile_changed" in readiness["reason_codes"]


def test_readiness_context_uses_stable_root_identity_and_only_trusted_native_release_metadata(tmp_path, monkeypatch):
    service, root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    })
    package = _install_package(homes["p1"], release=True)
    plugins = homes["p1"] / "plugins"
    (plugins / ".install-metadata.json").write_text(json.dumps({"model-router": {
        "revision": "a" * 40, "source": SOURCE, "pinned": True, "catalog": "model-router",
    }}), encoding="utf-8")
    (package / ".hermes-catalog.json").write_text(json.dumps({"source": "https://evil.invalid"}), encoding="utf-8")
    monkeypatch.setattr(service, "active_profile", lambda: "p1")

    first = service.status()["readiness_context"]
    second = service.status()["readiness_context"]

    assert first["schema"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", first["base_identity"])
    assert first["base_identity"] == second["base_identity"]
    assert first["source_profile"] == "p1"
    assert first["release"] == {"catalog_name": "model-router", "version": "0.4.7", "ref": "a" * 40}
    assert "github.com" not in json.dumps(first)
    assert str(root) not in json.dumps(first)


def test_readiness_context_never_trusts_in_tree_catalog_sidecar_or_unapproved_source(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch)
    package = _install_package(homes["p1"], release=True)
    (package / ".hermes-catalog.json").write_text(json.dumps({
        "catalog": "model-router", "revision": "b" * 40, "source": SOURCE,
    }), encoding="utf-8")
    monkeypatch.setattr(service, "active_profile", lambda: "p1")
    assert service.status()["readiness_context"]["release"] is None

    (homes["p1"] / "plugins" / ".install-metadata.json").write_text(json.dumps({"model-router": {
        "revision": "c" * 40, "source": "https://evil.invalid/repo", "pinned": True,
    }}), encoding="utf-8")
    assert service.status()["readiness_context"]["release"] is None


@pytest.mark.parametrize("entrypoint", [None, "def =\n"])
def test_native_root_entrypoint_missing_or_invalid_is_not_ready(tmp_path, monkeypatch, entrypoint):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    }, installed=("p1",))
    entry = homes["p1"] / "plugins" / "model-router" / "__init__.py"
    if entrypoint is None:
        entry.unlink()
    else:
        entry.write_text(entrypoint, encoding="utf-8")
    result = _row(service, "p1")["readiness"]
    assert result["state"] == "unsupported"
    assert result["base_supported"] is False
    assert service._timeout_enforcement_available("p1") is False


def test_timeout_eligibility_requires_supported_files_and_proven_python_selection(tmp_path, monkeypatch):
    service, _root, _homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=[]),
    }, installed=("p1",))

    assert service._timeout_enforcement_available("p1") is False
    monkeypatch.setattr(effective_config, "read_key_scoped", lambda _home, _keys: _selection(enabled=["model-router"]))
    assert service._timeout_enforcement_available("p1") is True
    assert service._timeout_role_enforcement_available("p1") is True


def test_disabling_python_after_timeout_preview_rejects_before_timeout_write(tmp_path, monkeypatch):
    selections = {"p1": _selection(enabled=["model-router"])}
    service, _root, homes = _service(
        tmp_path, monkeypatch, selections=selections, installed=("p1",)
    )
    status = service.status()
    row = next(item for item in status["profiles"] if item["name"] == "p1")
    body = {
        "expected_revision": status["revision"],
        "profile": "p1",
        "models": row["models"],
        "model_targets": [],
        "routing": row["routing"],
        "routing_profiles": [],
        "timeout_updates": [{
            "profile": "p1", "expected_revision": 0,
            "delegate_total_seconds": 120,
            "routed_light_total_seconds": 1800,
            "routed_heavy_total_seconds": 7200,
        }],
        "save_scope": "timeouts",
    }

    preview = service.preview(body)
    config_before = (homes["p1"] / "config.yaml").read_bytes()
    selections["p1"] = _selection(enabled=[], disabled=["model-router"])
    with pytest.raises(RevisionConflict, match="timeout enforcement"):
        service.apply(preview["plan_id"])

    assert not (homes["p1"] / "plugin-data" / "model-router" / "timeouts.json").exists()
    assert (homes["p1"] / "config.yaml").read_bytes() == config_before


def test_noop_timeout_plan_rechecks_python_selection_at_final_guard(tmp_path, monkeypatch):
    service, _root, homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    }, installed=("p1",))
    status = service.status()
    row = next(item for item in status["profiles"] if item["name"] == "p1")
    body = {
        "expected_revision": status["revision"], "profile": "p1",
        "models": row["models"], "model_targets": [], "routing": row["routing"],
        "routing_profiles": [], "save_scope": "timeouts",
        "timeout_updates": [{
            "profile": "p1", "expected_revision": 0,
            "delegate_total_seconds": 0,
            "routed_light_total_seconds": 3600,
            "routed_heavy_total_seconds": 3600,
        }],
    }
    preview = service.preview(body)
    assert preview["changes"] == []
    reads = 0

    def disable_on_final_guard(_home, _keys):
        nonlocal reads
        reads += 1
        if reads == 1:
            return _selection(enabled=["model-router"])
        return _selection(enabled=[], disabled=["model-router"])

    monkeypatch.setattr(effective_config, "read_key_scoped", disable_on_final_guard)
    with pytest.raises(RevisionConflict, match="timeout enforcement"):
        service.apply(preview["plan_id"])

    assert reads == 2
    assert not (homes["p1"] / "plugin-data" / "model-router" / "timeouts.json").exists()


def test_readiness_status_is_read_only_and_does_not_change_config_or_install_state(tmp_path, monkeypatch):
    service, root, _homes = _service(tmp_path, monkeypatch, selections={
        "p1": _selection(enabled=["model-router"]),
    }, installed=("p1",))
    before = _snapshot_tree(root)

    result = service.status()

    assert result["readiness_context"]["source_profile"] == "default"
    assert all("readiness" in row for row in result["profiles"])
    assert before == _snapshot_tree(root)
    assert not list(root.rglob("__pycache__"))
