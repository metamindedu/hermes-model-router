import importlib.util
from pathlib import Path
import json
import sys
from types import SimpleNamespace

import yaml


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
