"""Exact-byte read cache: speed without hiding external config edits."""
import copy
import pytest
import yaml

from model_router.service import Service, ServiceError
from test_integration import make_home


def test_same_config_bytes_are_parsed_once_per_service(tmp_path, monkeypatch):
    root = make_home(tmp_path)
    service = Service(root)
    calls = []
    original = yaml.safe_load
    def counted(raw):
        calls.append(raw)
        return original(raw)
    monkeypatch.setattr(yaml, "safe_load", counted)
    assert service._read_key("default", "model.default") == "heavy-test"
    assert service._read_key("default", "delegation.model") == "light-test"
    assert service._read_key("default", "model.default") == "heavy-test"
    assert len(calls) == 1, "a status request must not parse the same full YAML once per field"


def test_external_change_is_seen_even_when_size_and_timestamp_are_unchanged(tmp_path):
    import os
    root = make_home(tmp_path)
    service = Service(root)
    path = root / "config.yaml"
    assert service._read_key("default", "model.default") == "heavy-test"
    stat = path.stat()
    before = path.read_bytes()
    after = before.replace(b"heavy-test", b"other-test")
    assert len(before) == len(after)
    path.write_bytes(after)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert service._read_key("default", "model.default") == "other-test"


def test_mutating_returned_container_cannot_change_cached_config(tmp_path):
    root = make_home(tmp_path)
    path = root / "config.yaml"
    data = yaml.safe_load(path.read_text())
    data["skills"]["disabled"] = ["keep"]
    path.write_text(yaml.safe_dump(data))
    service = Service(root)
    result = service._read_key("default", "skills.disabled")
    result.append("caller-only")
    assert service._read_key("default", "skills.disabled") == ["keep"]
    assert yaml.safe_load(path.read_text())["skills"]["disabled"] == ["keep"]


def test_same_interpreter_clears_foreign_paths_and_keeps_profile_binding(tmp_path, monkeypatch):
    service = Service(make_home(tmp_path))
    monkeypatch.setenv("PYTHONPATH", "C:/untrusted-project")
    monkeypatch.setenv("PYTHONHOME", "C:/foreign-interpreter")
    monkeypatch.setenv("HERMES_PROFILE", "foreign")
    env = service._env("default")
    assert "C:/untrusted-project" not in env["PYTHONPATH"]
    assert "PYTHONHOME" not in env and "HERMES_PROFILE" not in env
    assert env["HERMES_HOME"] == str(service.root)
    assert service._command("default", "config", "get", "model.default")[1:5] == ["-m", "hermes_cli.main", "--profile", "default"]


def test_standalone_environment_without_loaded_core_uses_stable_cli(tmp_path, monkeypatch):
    service = Service(make_home(tmp_path))
    monkeypatch.setattr(service, "_loaded_cli_paths", lambda: [])
    monkeypatch.setattr(service, "_cli_path", lambda: "stable-hermes")
    assert service._command("default", "config", "get", "model.default") == ["stable-hermes", "--profile", "default", "config", "get", "model.default"]


def test_invalid_changed_config_never_reuses_old_cached_values(tmp_path):
    root = make_home(tmp_path)
    service = Service(root)
    path = root / "config.yaml"
    original = path.read_bytes()
    assert service._read_key("default", "model.default") == "heavy-test"
    path.write_text("model: [broken\n")
    with pytest.raises(ServiceError):
        service._read_key("default", "model.default")
    path.write_bytes(original)
    assert service._read_key("default", "model.default") == "heavy-test"
