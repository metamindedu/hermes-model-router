"""One-time conversion of Model Router v0.17 saved state to the v0.18 formats.

v0.18 reads only its own formats (settings store schema 5, timeouts schema 3, slot-only native
delegation blocks); it has no code for older ones. Run this once, after the v0.18 files are
installed and before (or right after) the Hermes processes restart, with the Python environment
that runs Hermes (it imports PyYAML and the plugin package next to this script):

    python scripts/migrate_to_v018.py [--root HERMES_ROOT]          # dry run: report only
    python scripts/migrate_to_v018.py [--root HERMES_ROOT] --apply  # write

What it converts, per Hermes root:
- plugin-data/model-router/settings.json (schema 4 -> 5): routing becomes {enabled, slots}. Every
  slot keeps its effective v0.17 route: a slot that followed the delegation model (directly or
  through the Light route) is stored as that model, a Heavy-class slot that followed Main keeps
  following Main. The Heavy/Light routes, the disabled routing spare models, the empty routing
  consent and the custom slots' tier are dropped.
- <profile>/plugin-data/model-router/timeouts.json (schema 1/2 -> 3): every slot starts without a
  limit of its own, so it runs on the two-hour default (operator decision for v0.18); the ordinary
  delegation limit is unchanged.
- delegation.backends.model-router / model-router-auto in each profile's config.yaml: a two-role
  block whose spare models are all off becomes the all-off per-slot block.

It refuses (and writes nothing) when a value cannot be carried over unchanged: an enabled routing
spare model, a stored routing consent, a two-role block with spare models on, or an unknown shape.
Before replacing a file it keeps the original bytes once as <file>.pre-v018 (never overwritten).
Output never contains model names, routes or secrets: only profile names, counts and states.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from model_router import native_settings as ns  # noqa: E402
from model_router import slots as slot_model  # noqa: E402
from model_router import timeouts  # noqa: E402
from model_router.service import PROFILE_RE, STORE_RELATIVE, STORE_SCHEMA, Service, _atomic_write, _FileLock  # noqa: E402
from model_router.yaml_compat import yaml  # noqa: E402

# The v0.17 class of each built-in slot (its runtime limit and the route an unset slot used).
V017_CLASS = {"design": "heavy", "code-complex": "light", "code-simple": "light", "verify-simple": "light",
              "verify-complex": "heavy", "computer-use": "light", "advise": "heavy"}
V017_CLASS_FOLLOW = {"heavy": "main", "light": "delegation"}
BACKUP_SUFFIX = ".pre-v018"


class Refused(Exception):
    """A value cannot be carried over unchanged."""


def _homes(root: Path) -> dict[str, Path]:
    homes = {"default": root}
    profiles = root / "profiles"
    if profiles.is_dir():
        for path in sorted(profiles.iterdir()):
            if PROFILE_RE.fullmatch(path.name) and path.is_dir() and (path / "config.yaml").is_file():
                homes[path.name] = path
    return homes


def _route(value: Any, where: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "reasoning"} or not all(
            isinstance(value[key], str) and value[key] for key in ("provider", "model")):
        raise Refused(f"{where}: no complete model route to carry over")
    return copy.deepcopy(value)


def _declaration(declaration: Any, delegation: Any, where: str) -> dict[str, Any]:
    """A v0.17 slot declaration as v0.18 stores it (follow main, or the route itself)."""
    if not isinstance(declaration, dict) or set(declaration) != {"follow", "custom"}:
        raise Refused(f"{where}: unknown slot declaration")
    follow = declaration["follow"]
    if follow == "main":
        return {"follow": "main", "custom": None}
    if follow == "delegation":
        return {"follow": "custom", "custom": _route(delegation, f"{where} (delegation model)")}
    if follow == "custom":
        return {"follow": "custom", "custom": _route(declaration["custom"], where)}
    raise Refused(f"{where}: unknown follow {follow!r}")


def convert_store(data: Any) -> dict[str, Any]:
    """Settings store schema 4 -> 5. Raises Refused for anything not carried over unchanged."""
    if not isinstance(data, dict) or data.get("schema") != 4 or set(data) != {"schema", "revision", "profiles", "custom_slots"}:
        raise Refused("settings store is not the v0.17 schema 4")
    custom_classes: dict[str, str] = {}
    custom_slots = []
    for item in data["custom_slots"]:
        if not isinstance(item, dict) or set(item) != {"id", "label", "description", "tier"} or item["tier"] not in V017_CLASS_FOLLOW:
            raise Refused("custom slot definition has an unknown shape")
        custom_classes[item["id"]] = item["tier"]
        custom_slots.append({"id": item["id"], "label": item["label"], "description": item["description"]})
    classes = {**V017_CLASS, **custom_classes}
    profiles = {}
    for name, entry in data["profiles"].items():
        where = f"profile {name}"
        if not isinstance(entry, dict) or set(entry) != {"models", "routing", "native_fallback", "delegation_fallback", "fallback_consent"}:
            raise Refused(f"{where}: unknown entry shape")
        routing, consent = entry["routing"], entry["fallback_consent"]
        if not isinstance(routing, dict) or set(routing) - {"enabled", "heavy", "light", "fallback", "slots"} or not isinstance(routing.get("enabled"), bool):
            raise Refused(f"{where}: unknown routing shape")
        spare = routing.get("fallback")
        if spare is not None and (not isinstance(spare, dict) or spare.get("enabled") is not False):
            raise Refused(f"{where}: routing spare models are enabled; v0.18 has no routing spare models")
        if not isinstance(consent, dict) or set(consent) != {"native", "routing", "delegation"} or consent["routing"] is not None:
            raise Refused(f"{where}: routing consent is stored")
        delegation = entry["models"].get("delegation") if isinstance(entry["models"], dict) else None
        stored = routing.get("slots") or {}
        if not isinstance(stored, dict) or set(stored) - set(classes):
            raise Refused(f"{where}: slots name an unknown slot")
        slots = {}
        for slot, slot_class in classes.items():
            if slot in stored:
                slots[slot] = _declaration(stored[slot], delegation, f"{where} slot {slot}")
                continue
            # Never set in v0.17: it ran on its class route (Heavy follows Main, Light the delegation model).
            class_route = routing.get(slot_class) or {"follow": V017_CLASS_FOLLOW[slot_class], "custom": None}
            converted = _declaration(class_route, delegation, f"{where} slot {slot} ({slot_class} route)")
            if converted != {"follow": "main", "custom": None}:
                slots[slot] = converted
        profiles[name] = {
            "models": copy.deepcopy(entry["models"]),
            "routing": {"enabled": routing["enabled"], "slots": slots},
            "native_fallback": copy.deepcopy(entry["native_fallback"]),
            "delegation_fallback": copy.deepcopy(entry["delegation_fallback"]),
            "fallback_consent": {"native": copy.deepcopy(consent["native"]), "delegation": copy.deepcopy(consent["delegation"])},
        }
    return {"schema": STORE_SCHEMA, "revision": data["revision"] + 1, "profiles": profiles, "custom_slots": custom_slots}


def convert_timeouts(value: Any) -> dict[str, Any]:
    """Timeouts schema 1/2 -> 3: the ordinary limit is kept; every slot gets the two-hour default."""
    if not isinstance(value, dict) or not isinstance(value.get("revision"), int):
        raise Refused("timeout settings have an unknown shape")
    v017 = {2: {"schema", "revision", "delegate_total_seconds", "routed_light_total_seconds", "routed_heavy_total_seconds"},
            1: {"schema", "revision", "delegate_total_seconds", "routed_total_seconds"}}
    if set(value) != v017.get(value.get("schema"), set()):
        raise Refused("timeout settings are not a v0.17 schema")
    try:
        values = timeouts.validate_policy_values({"delegate_total_seconds": value["delegate_total_seconds"], "slot_seconds": {}})
    except ValueError as exc:
        raise Refused("timeout settings have an invalid ordinary limit") from exc
    return {"schema": 3, "revision": value["revision"] + 1, **values}


def convert_block(profile: str, backend: str, block: Any) -> dict[str, Any] | None:
    """A two-role native block whose spare models are all off -> the all-off per-slot block."""
    if not isinstance(block, dict) or block.get("schema") != 1:
        return None  # absent, or already the per-slot block (validated by v0.18 itself)
    fallbacks = block.get("fallbacks")
    if set(block) != {"schema", "fallbacks"} or not isinstance(fallbacks, dict) or set(fallbacks) != {"heavy", "light"}:
        raise Refused(f"profile {profile}: {backend} block has an unknown shape")
    for row in fallbacks.values():
        if not isinstance(row, dict) or row.get("mode") != "off" or row.get("chain") or row.get("consent") is not None:
            raise Refused(f"profile {profile}: {backend} continues on spare models; save its slots on the v0.18 page instead")
    return ns.build_slot_policy_block(profile, ns.default_slot_policy(), False, backend=backend)


def _json_bytes(value: Any, indent: int | None) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent) + "\n").encode("utf-8")


def _keep_original(path: Path) -> None:
    """Keep the file's current bytes once as <file>.pre-v018 (atomic; an existing copy is kept)."""
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if backup.exists():
        return
    temp = backup.with_name(backup.name + ".tmp")
    with temp.open("xb") as handle:
        handle.write(path.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, backup)


def _config_backends(home: Path) -> dict[str, Any]:
    config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    backends = ((config.get("delegation") or {}).get("backends") or {}) if isinstance(config, dict) else {}
    return backends if isinstance(backends, dict) else {}


def _validate_store(converted: dict[str, Any]) -> None:
    """Load the converted store with the v0.18 loader itself, from a scratch root."""
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / STORE_RELATIVE
        target.parent.mkdir(parents=True)
        target.write_bytes(_json_bytes(converted, 2))
        Service(root=Path(scratch))._load_store()


def plan(root: Path) -> dict[str, Any]:
    """Everything the conversion would write (no writes)."""
    service = Service(root=root)
    result: dict[str, Any] = {"store": "absent", "timeouts": {}, "blocks": {}, "refused": []}
    raw = None
    if service.store_path.is_file():
        raw = json.loads(service.store_path.read_text(encoding="utf-8"))
        if raw.get("schema") == STORE_SCHEMA:
            result["store"] = "current"
        else:
            try:
                converted = convert_store(raw)
                _validate_store(converted)
                result["store"] = converted
            except Refused as exc:
                result["store"] = "refused"
                result["refused"].append(str(exc))
    for name, home in _homes(root).items():
        path = home / "plugin-data" / "model-router" / "timeouts.json"
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("schema") == 3:
                result["timeouts"][name] = "current"
            else:
                try:
                    result["timeouts"][name] = convert_timeouts(value)
                except Refused as exc:
                    result["refused"].append(f"profile {name}: {exc}")
        backends = _config_backends(home)
        for backend in ("model-router", "model-router-auto"):
            try:
                block = convert_block(name, backend, backends.get(backend))
            except Refused as exc:
                result["refused"].append(str(exc))
                continue
            if block is not None:
                result["blocks"][(name, backend)] = block
    return result


def summary(result: dict[str, Any]) -> list[str]:
    lines = []
    store = result["store"]
    if isinstance(store, dict):
        slots = sum(len(entry["routing"]["slots"]) for entry in store["profiles"].values())
        lines.append(f"settings store: schema 4 -> 5 ({len(store['profiles'])} profiles, {slots} stored slots, "
                     f"{len(store['custom_slots'])} custom slots)")
    else:
        lines.append(f"settings store: {store}")
    for name, value in result["timeouts"].items():
        if isinstance(value, dict):
            lines.append(f"timeouts {name}: -> schema 3 (every slot on the 2 h default; "
                         f"ordinary limit {value['delegate_total_seconds']:g} s kept)")
        else:
            lines.append(f"timeouts {name}: {value}")
    for (name, backend) in result["blocks"]:
        lines.append(f"config {name}: delegation.backends.{backend} two-role (all off) -> per-slot (all off)")
    for reason in result["refused"]:
        lines.append(f"REFUSED: {reason}")
    return lines


def apply(root: Path, result: dict[str, Any], done: list[str]) -> None:
    """Write in order: config blocks, timeout files, then the settings store.

    Each step re-checks what it replaces and reads its result back. A failure stops the run; every
    step finished so far is complete on its own, and a rerun plans only what is still old.
    """
    if result["refused"]:
        raise Refused("nothing written: " + "; ".join(result["refused"]))
    service = Service(root=root)
    homes = _homes(root)
    for (name, backend), block in result["blocks"].items():
        home = homes[name]
        current = _config_backends(home).get(backend)
        if convert_block(name, backend, current) != block:
            raise Refused(f"profile {name}: {backend} changed since the plan was made")
        _keep_original(home / "config.yaml")
        service._write_key(name, f"delegation.backends.{backend}", block)
        if _config_backends(home).get(backend) != block:
            raise Refused(f"profile {name}: {backend} readback mismatch")
        done.append(f"config {name} {backend}")
    for name, value in result["timeouts"].items():
        if not isinstance(value, dict):
            continue
        path = homes[name] / "plugin-data" / "model-router" / "timeouts.json"
        with _FileLock(path.with_name(".timeouts.lock")):
            if convert_timeouts(json.loads(path.read_text(encoding="utf-8"))) != value:
                raise Refused(f"profile {name}: timeouts changed since the plan was made")
            _keep_original(path)
            _atomic_write(path, _json_bytes(value, 2))
        if timeouts.read_timeouts(homes[name]) != value:
            raise Refused(f"profile {name}: timeouts readback mismatch")
        done.append(f"timeouts {name}")
    store = result["store"]
    if isinstance(store, dict):
        with _FileLock(service._lock_path):
            current = json.loads(service.store_path.read_text(encoding="utf-8"))
            if convert_store(current) != store:
                raise Refused("settings store changed since the plan was made")
            _keep_original(service.store_path)
            _atomic_write(service.store_path, _json_bytes(store, 2))
        if service._load_store()["revision"] != store["revision"]:  # the v0.18 loader reads it back
            raise Refused("settings store readback mismatch")
        done.append("settings store")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert Model Router v0.17 saved state to the v0.18 formats.")
    parser.add_argument("--root", type=Path, default=None, help="Hermes root (default: the active Hermes home's root)")
    parser.add_argument("--apply", action="store_true", help="write the conversion (default: report only)")
    args = parser.parse_args(argv)
    root = (args.root or Service().root).expanduser().resolve()
    result = plan(root)
    for line in summary(result):
        print(line)
    if not args.apply:
        print("dry run: nothing written" + (" (refusals above must be resolved first)" if result["refused"] else ""))
        return 1 if result["refused"] else 0
    done: list[str] = []
    try:
        apply(root, result, done)
    except Exception as exc:  # report and stop; finished steps stay valid and a rerun continues
        reason = str(exc) if isinstance(exc, Refused) else type(exc).__name__
        print(f"STOPPED: {reason}")
        print(f"completed before the stop: {', '.join(done) or 'nothing'}; fix the cause and run again")
        return 1
    print("applied: " + (", ".join(done) or "nothing to change"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
