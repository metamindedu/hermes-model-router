import importlib.util
from pathlib import Path
import json
import sys
from types import SimpleNamespace

import yaml
import pytest


ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("installer_subject", ROOT / "scripts/install_local.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def fixture(tmp_path, monkeypatch):
    mod = module()
    root = tmp_path / "home"
    configs = {}
    for name in ("default", "coding", "writing"):
        home = root if name == "default" else root / "profiles" / name
        home.mkdir(parents=True)
        data = {"model": {"default": "unchanged", "provider": "known"}, "agent": {"reasoning_effort": "high"}, "skills": {"disabled": ["unrelated"], "external_dirs": []}, "plugins": {"enabled": ["other-plugin"]}, "unrelated": {"value": "keep"}}
        (home / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        configs[name] = data
    launcher = root / "bin/hermes.exe" if sys.platform == "win32" else root / "bin/hermes"
    launcher.parent.mkdir(); launcher.write_text("fake only")
    package = tmp_path / "package"; package.mkdir()
    (package / "plugin.yaml").write_text("name: model-router\n")
    monkeypatch.setattr(mod, "PACKAGE", package)
    monkeypatch.setattr(mod, "INCLUDE", ["plugin.yaml"])
    def fake_run(cmd, env, **kwargs):
        home = Path(env["HERMES_HOME"])
        file = home / "config.yaml"
        data = yaml.safe_load(file.read_text())
        idx = cmd.index("set")
        key, value = cmd[idx + 1], json.loads(cmd[idx + 2])
        parent, leaf = key.split(".")
        data.setdefault(parent, {})[leaf] = value
        file.write_text(yaml.safe_dump(data), encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return mod, root, configs


def test_dry_run_no_settings_or_package_writes(tmp_path, monkeypatch):
    mod, root, _ = fixture(tmp_path, monkeypatch)
    before = {str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert mod.main(["--root", str(root), "--routing-profiles", "coding"]) == 0
    assert before == {str(p):p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_install_preserves_models_and_unrelated_scope(tmp_path, monkeypatch):
    mod, root, original = fixture(tmp_path, monkeypatch)
    assert mod.main(["--root", str(root), "--routing-profiles", "coding", "--apply"]) == 0
    for name, home in mod.homes(root).items():
        data = yaml.safe_load((home / "config.yaml").read_text())
        for key in ("model", "agent", "unrelated"):
            assert data[key] == original[name][key]
        assert data["plugins"]["enabled"] == ["other-plugin", "model-router"]
        assert "unrelated" in data["skills"]["disabled"]
        assert ("adaptive-coding-orchestration" not in data["skills"]["disabled"]) == (name == "coding")
        assert (home / "plugins/model-router/plugin.yaml").read_text() == "name: model-router\n"


@pytest.mark.parametrize("prototype_name", ["execution_metadata.py", "Execution_Metadata.PY"])
def test_package_copy_excludes_only_unadmitted_component(tmp_path, monkeypatch, prototype_name):
    mod = module()
    package = tmp_path / "package"
    contents = {
        "model_router/__init__.py": "# public package\n",
        "model_router/execution_roster.py": "# admitted roster\n",
        f"model_router/{prototype_name}": "# unadmitted private-schema research\n",
        "model_router/__pycache__/execution_metadata.cpython-314.pyc": "cache",
        "model_router/stale.pyc": "cache",
        "lib/execution_metadata.py": "# unrelated same basename\n",
    }
    for rel, value in contents.items():
        path = package / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    before = {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()}
    monkeypatch.setattr(mod, "PACKAGE", package)
    monkeypatch.setattr(mod, "INCLUDE", ["model_router", "lib"])
    dest = tmp_path / "payload"
    dest.mkdir()
    mod.copy_package(dest)
    assert {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()} == {
        "model_router/__init__.py", "model_router/execution_roster.py", "lib/execution_metadata.py"
    }
    for path in dest.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == before[path.relative_to(dest).as_posix()]
    assert before == {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()}


def test_package_copy_explicit_include_cannot_reenable_prototype(tmp_path, monkeypatch):
    mod = module()
    package = tmp_path / "package"
    (package / "model_router").mkdir(parents=True)
    (package / "model_router/execution_metadata.py").write_text("# research only\n")
    (package / "plugin.yaml").write_text("name: model-router\n")
    monkeypatch.setattr(mod, "PACKAGE", package)
    monkeypatch.setattr(mod, "INCLUDE", ["model_router/execution_metadata.py", "plugin.yaml"])
    dest = tmp_path / "payload"
    dest.mkdir()
    mod.copy_package(dest)
    assert [p.name for p in dest.iterdir()] == ["plugin.yaml"]


def test_package_copy_refuses_nonempty_destination_without_writes(tmp_path):
    mod = module()
    dest = tmp_path / "existing"
    dest.mkdir()
    marker = dest / "user-owned.txt"
    marker.write_bytes(b"preserve")
    with pytest.raises(RuntimeError, match="empty directory"):
        mod.copy_package(dest)
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == {"user-owned.txt": b"preserve"}


def test_real_package_copy_does_not_distribute_private_prototype(tmp_path):
    mod = module()
    dest = tmp_path / "payload"
    dest.mkdir()
    mod.copy_package(dest)
    assert not (dest / "model_router/execution_metadata.py").exists()
    assert not list(dest.rglob("__pycache__"))
    assert not list(dest.rglob("*.pyc"))
    for rel in ("plugin.yaml", "model_router/execution_roster.py", "desktop/plugin.js"):
        assert (dest / rel).read_bytes() == (ROOT / rel).read_bytes()


def test_install_entrypoint_uses_filtered_payload(tmp_path, monkeypatch):
    # All homes/config commands are disposable fixtures, never operator profiles.
    mod, root, _ = fixture(tmp_path, monkeypatch)
    router = mod.PACKAGE / "model_router"
    router.mkdir()
    (router / "__init__.py").write_text("# public package\n")
    (router / "execution_metadata.py").write_text("# unadmitted research\n")
    monkeypatch.setattr(mod, "INCLUDE", ["plugin.yaml", "model_router"])
    assert mod.main(["--root", str(root), "--routing-profiles", "coding", "--apply"]) == 0
    for home in mod.homes(root).values():
        payload = home / "plugins/model-router"
        assert (payload / "model_router/__init__.py").is_file()
        assert not (payload / "model_router/execution_metadata.py").exists()
