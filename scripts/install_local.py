"""Install reviewed local package using copies and supported config commands.

No model/credential changes. Run only after independent Heavy review. Config
changes are deliberate plugin+skill activation; all previous values are backed up.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import datetime

import yaml

PACKAGE = Path(__file__).resolve().parents[1]
INCLUDE = ["plugin.yaml", "__init__.py", "model_router", "desktop", "dashboard", "skills", "compat", "lib", "cli.py", "README.md"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def homes(root):
    found = {"default": root}
    for path in sorted((root / "profiles").glob("*/config.yaml")):
        name = path.parent.name
        if not name.startswith(".") and path.parent.resolve().parent == (root / "profiles").resolve():
            found[name] = path.parent
    return found


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--routing-profiles", nargs="*", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    root = args.root.resolve()
    targets = homes(root)
    if not set(args.routing_profiles) <= set(targets):
        p.error("Unknown routing profile")
    print(json.dumps({"profiles": list(targets), "routing_profiles": args.routing_profiles, "apply": args.apply, "model_changes": False}))
    if not args.apply:
        return 0
    launcher = root / "bin" / ("hermes.exe" if os.name == "nt" else "hermes")
    if not launcher.is_file():
        raise RuntimeError("Stable Hermes launcher missing")
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / "profiles/claire/backups" / ("model-router-install-" + timestamp)
    backup.mkdir(parents=True, exist_ok=False)
    receipt = {"started": timestamp, "backup": str(backup), "completed": [], "status": "in_progress"}
    receipt_file = backup / "receipt.json"

    def save():
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    def setkey(name, home, key, value):
        env = dict(os.environ, HERMES_HOME=str(home))
        for variable in ("HERMES_PROFILE", "HERMES_CHILD_SESSION_SOURCE", "HERMES_SESSION_ID", "HERMES_PARENT_SESSION_ID"):
            env.pop(variable, None)
        cmd = [str(launcher), "--profile", name]
        cmd += ["config", "set", key, json.dumps(value, ensure_ascii=False), "--force"]
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=45)
        if r.returncode:
            raise RuntimeError("Config command failed: " + name + "/" + key)
        observed = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
        for part in key.split("."):
            observed = observed[part]
        if observed != value:
            raise RuntimeError("Config readback mismatch: " + name + "/" + key)

    try:
        for name, home in targets.items():
            config = home / "config.yaml"
            data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            entry_backup = backup / name
            entry_backup.mkdir()
            shutil.copy2(config, entry_backup / "config.yaml")
            dest = home / "plugins/model-router"
            if dest.exists():
                raise RuntimeError("Existing model-router install requires explicit update: " + name)
            dest.mkdir(parents=True)
            for item in INCLUDE:
                origin = PACKAGE / item
                if origin.is_dir():
                    shutil.copytree(origin, dest / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    shutil.copy2(origin, dest / item)
            enabled = list(data.get("plugins", {}).get("enabled", []))
            if "model-router" not in enabled:
                setkey(name, home, "plugins.enabled", enabled + ["model-router"])
            denied = list(data.get("plugins", {}).get("disabled", []))
            if "model-router" in denied:
                setkey(name, home, "plugins.disabled", [v for v in denied if v != "model-router"])
            # Preserve prior bare-skill discovery; only add a compat root if absent.
            disabled = list(data.get("skills", {}).get("disabled", []))
            if name in args.routing_profiles:
                if "adaptive-coding-orchestration" in disabled:
                    setkey(name, home, "skills.disabled", [s for s in disabled if s != "adaptive-coding-orchestration"])
                dirs = list(data.get("skills", {}).get("external_dirs", []))
                compat = str(dest / "compat").replace("\\", "/")
                if compat not in dirs:
                    setkey(name, home, "skills.external_dirs", dirs + [compat])
            elif "adaptive-coding-orchestration" not in disabled:
                setkey(name, home, "skills.disabled", disabled + ["adaptive-coding-orchestration"])
            current = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
            # Installation is not model migration: untouched sections must stay identical.
            for key in set(data) | set(current):
                if key not in {"plugins", "skills"} and data.get(key) != current.get(key):
                    raise RuntimeError("Unrelated config changed: " + name + "/" + key)
            for key in {"plugins", "skills"}:
                allowed = {"enabled", "disabled"} if key == "plugins" else {"external_dirs", "disabled"}
                before_section, after_section = data.get(key, {}), current.get(key, {})
                for subkey in set(before_section) | set(after_section):
                    if subkey not in allowed and before_section.get(subkey) != after_section.get(subkey):
                        raise RuntimeError("Unrelated config changed: " + name + "/" + key + "/" + subkey)
            installed = {str(f.relative_to(dest)): digest(f) for f in dest.rglob("*") if f.is_file() and "__pycache__" not in f.parts}
            for rel, sha in installed.items():
                if digest(PACKAGE / rel) != sha:
                    raise RuntimeError("Installed package hash mismatch")
            receipt["completed"].append({"profile": name, "config_after": digest(config), "package_files": installed})
            save()
        receipt["status"] = "installed"
        save()
        print(json.dumps({"status": "installed", "count": len(receipt["completed"]), "receipt": str(receipt_file)}))
        return 0
    except Exception as exc:
        receipt["status"] = "partial"
        receipt["error_type"] = type(exc).__name__
        save()
        print(json.dumps({"status": "partial", "receipt": str(receipt_file), "error_type": type(exc).__name__}), file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
