"""Read-only, fail-closed observation of per-profile model-router readiness.

This module intentionally never imports plugin code, discovers packages, runs a
subprocess, creates a directory, or writes an installation/provenance record.
All public values are fixed enums, validated versions, booleans, and opaque
SHA-256 observations.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from . import effective_config

SCHEMA = 1
MAX_SOURCE_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_STORE_BYTES = 1024 * 1024
PLUGIN_NAME = "model-router"
PLUGIN_RELATIVE = Path("plugins") / PLUGIN_NAME
SELECTION_KEYS = ("plugins.enabled", "plugins.disabled")
SKILL_OPT_OUT_IDS = frozenset({
    "adaptive-coding-orchestration",
    "model-router:adaptive-coding-orchestration",
})
TRUSTED_SOURCES = frozenset({
    "https://github.com/metamindedu/hermes-model-router",
    "https://github.com/metamindedu/hermes-model-router.git",
})
_VERSION_RE = re.compile(r"(?:0|[1-9][0-9]{0,4})\.(?:0|[1-9][0-9]{0,4})\.(?:0|[1-9][0-9]{0,4})\Z")
_REVISION_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
_ENV_REF_RE = re.compile(r"\$\{[^}]+\}")

_EXPECTED_HOOKS = frozenset({
    "pre_api_request", "post_api_request", "api_request_error", "pre_tool_call",
    "post_tool_call", "subagent_start", "subagent_stop",
})
_EXPECTED_MIDDLEWARE = frozenset({"tool_execution", "llm_request"})


class _PathUnsafe(Exception):
    """A link/reparse point, escape, or non-regular path was observed."""


class _PathUnreadable(Exception):
    """A bounded local observation could not be completed."""


class _PathChanged(Exception):
    """A path changed while its bounded bytes were being read."""


@dataclass(frozen=True)
class _FileObservation:
    present: bool
    data: bytes | None
    signature: tuple[Any, ...]
    error: str | None = None


@dataclass(frozen=True)
class _Capture:
    home_ok: bool
    config: _FileObservation
    plugins_dir: _FileObservation
    package_dir: _FileObservation
    code_dir: _FileObservation
    files: dict[str, _FileObservation]
    store: _FileObservation
    signature: tuple[Any, ...]


@dataclass(frozen=True)
class _Selection:
    python: str
    managed: bool
    digest: str | None
    reasons: tuple[str, ...]


def _path_attrs(info: os.stat_result) -> tuple[Any, ...]:
    return (
        getattr(info, "st_mode", 0), getattr(info, "st_dev", 0),
        getattr(info, "st_ino", 0), getattr(info, "st_size", 0),
        getattr(info, "st_mtime_ns", int(getattr(info, "st_mtime", 0) * 1_000_000_000)),
        getattr(info, "st_ctime_ns", int(getattr(info, "st_ctime", 0) * 1_000_000_000)),
        getattr(info, "st_file_attributes", 0),
    )


def _component_attrs(info: os.stat_result) -> tuple[Any, ...]:
    # Directory contents/mtime can change because of unrelated logs or another
    # profile. Only incarnation/type/reparse changes affect path authority.
    if stat.S_ISDIR(info.st_mode):
        return (info.st_mode, info.st_dev, info.st_ino, getattr(info, "st_file_attributes", 0))
    return _path_attrs(info)


def _is_reparse(path: Path, info: os.stat_result) -> bool:
    if stat.S_ISLNK(getattr(info, "st_mode", 0)):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(info, "st_file_attributes", 0) & reparse_flag:
        return True
    checker = getattr(path, "is_junction", None)
    if checker is not None:
        try:
            if checker():
                return True
        except OSError as exc:
            raise _PathUnreadable from exc
    return False


def _inspect(path: Path, expected: str, *, base: Path | None) -> tuple[os.stat_result | None, tuple[Any, ...]]:
    """Inspect every lexical component, rejecting links and nonregular targets."""
    try:
        absolute = Path(path).absolute()
    except (TypeError, ValueError, OSError) as exc:
        raise _PathUnreadable from exc
    parts = absolute.parts
    if not parts:
        raise _PathUnreadable
    current = Path(parts[0])
    signature: list[Any] = []
    try:
        anchor_info = current.lstat()
    except FileNotFoundError:
        return None, (parts[0], "missing")
    except OSError as exc:
        raise _PathUnreadable from exc
    if _is_reparse(current, anchor_info) or not stat.S_ISDIR(anchor_info.st_mode):
        raise _PathUnsafe
    signature.append((parts[0], _component_attrs(anchor_info)))
    final_info: os.stat_result | None = anchor_info if len(parts) == 1 else None
    for index, component in enumerate(parts[1:], start=1):
        current = current / component
        is_final = index == len(parts) - 1
        try:
            info = current.lstat()
        except FileNotFoundError:
            signature.append((component, "missing"))
            return None, tuple(signature)
        except OSError as exc:
            raise _PathUnreadable from exc
        if _is_reparse(current, info):
            raise _PathUnsafe
        if not is_final and not stat.S_ISDIR(info.st_mode):
            raise _PathUnsafe
        if is_final:
            if expected == "dir" and not stat.S_ISDIR(info.st_mode):
                raise _PathUnsafe
            if expected == "file" and not stat.S_ISREG(info.st_mode):
                raise _PathUnsafe
            final_info = info
        signature.append((component, _component_attrs(info)))
    if final_info is not None and base is not None:
        try:
            resolved = absolute.resolve(strict=True)
            resolved_base = Path(base).resolve(strict=True)
            resolved.relative_to(resolved_base)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _PathUnsafe from exc
    return final_info, tuple(signature)


def _file(path: Path, *, base: Path, limit: int | None) -> _FileObservation:
    try:
        info, before = _inspect(path, "file", base=base)
        if info is None:
            return _FileObservation(False, None, before)
        if limit is not None and info.st_size > limit:
            return _FileObservation(True, None, before + (("oversized", info.st_size),), "oversized")
        data = None
        if limit is not None:
            try:
                with Path(path).open("rb") as stream:
                    data = stream.read(limit)
            except OSError as exc:
                return _FileObservation(True, None, before, "unreadable")
            if len(data) > limit or len(data) != info.st_size:
                return _FileObservation(True, None, before + (("unstable_size", len(data)),), "changed")
        after_info, after = _inspect(path, "file", base=base)
        if after_info is None or before != after:
            return _FileObservation(True, None, before + (("changed",),), "changed")
        signature = before
        if data is not None:
            signature += (("sha256", hashlib.sha256(data).hexdigest()),)
        return _FileObservation(True, data, signature)
    except _PathUnsafe:
        return _FileObservation(False, None, ("unsafe",), "unsafe")
    except _PathChanged:
        return _FileObservation(True, None, ("changed",), "changed")
    except _PathUnreadable:
        return _FileObservation(False, None, ("unreadable",), "unreadable")


def _directory(path: Path, *, base: Path | None) -> _FileObservation:
    try:
        info, signature = _inspect(path, "dir", base=base)
        return _FileObservation(info is not None, None, signature)
    except _PathUnsafe:
        return _FileObservation(False, None, ("unsafe",), "unsafe")
    except _PathUnreadable:
        return _FileObservation(False, None, ("unreadable",), "unreadable")


def _capture(home: Path, root: Path, store_path: Path) -> _Capture:
    home_observation = _directory(home, base=None)
    config = _file(home / "config.yaml", base=home, limit=None)
    plugins_dir = _directory(home / "plugins", base=home)
    package_dir = _directory(home / PLUGIN_RELATIVE, base=home)
    code_dir = _directory(home / PLUGIN_RELATIVE / "model_router", base=home)
    files: dict[str, _FileObservation] = {}
    specifications = {
        "manifest": (home / PLUGIN_RELATIVE / "plugin.yaml", MAX_MANIFEST_BYTES, home),
        "entrypoint": (home / PLUGIN_RELATIVE / "__init__.py", MAX_SOURCE_BYTES, home),
        "init": (home / PLUGIN_RELATIVE / "model_router" / "__init__.py", MAX_SOURCE_BYTES, home),
        "timeouts": (home / PLUGIN_RELATIVE / "model_router" / "timeouts.py", MAX_SOURCE_BYTES, home),
        "watchdog": (home / PLUGIN_RELATIVE / "model_router" / "native_watchdog.py", MAX_SOURCE_BYTES, home),
        "routing": (home / PLUGIN_RELATIVE / "model_router" / "routing.py", MAX_SOURCE_BYTES, home),
        "pyproject": (home / PLUGIN_RELATIVE / "pyproject.toml", MAX_SOURCE_BYTES, home),
        "metadata": (home / "plugins" / ".install-metadata.json", MAX_METADATA_BYTES, home),
        "package_json": (home / PLUGIN_RELATIVE / "package.json", None, home),
    }
    for name, (path, limit, base) in specifications.items():
        files[name] = _file(path, base=base, limit=limit)
    store = _file(store_path, base=root, limit=MAX_STORE_BYTES)
    signature = (
        home_observation.signature, config.signature, plugins_dir.signature,
        package_dir.signature, code_dir.signature,
        tuple((name, observation.signature, observation.error) for name, observation in sorted(files.items())),
        store.signature, store.error,
    )
    return _Capture(
        home_ok=home_observation.present and home_observation.error is None,
        config=config, plugins_dir=plugins_dir, package_dir=package_dir,
        code_dir=code_dir, files=files, store=store, signature=signature,
    )


def _sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_manifest(data: bytes | None) -> tuple[dict[str, Any] | None, str | None]:
    if data is None:
        return None, "manifest_invalid"
    try:
        from .yaml_compat import yaml
    except (ImportError, ModuleNotFoundError):
        return None, "manifest_invalid"
    try:
        value = yaml.safe_load(data.decode("utf-8-sig"))
    except (UnicodeError, ValueError, yaml.YAMLError):
        return None, "manifest_invalid"
    if not isinstance(value, dict):
        return None, "manifest_invalid"
    return value, None


def _version(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 17 or _VERSION_RE.fullmatch(value) is None:
        return None
    return value


def _literal_marker(source: bytes | None) -> bool:
    if source is None:
        return False
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeError, SyntaxError, ValueError, TypeError):
        return False
    assignments: list[ast.expr | None] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "ROUTED_ROLE_TIMEOUTS_SUPPORTED"
                for target in node.targets
            ):
                assignments.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ROUTED_ROLE_TIMEOUTS_SUPPORTED":
                assignments.append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ROUTED_ROLE_TIMEOUTS_SUPPORTED":
                assignments.append(None)
    return (
        len(assignments) == 1
        and isinstance(assignments[0], ast.Constant)
        and assignments[0].value is True
    )


def _manifest_from_capture(capture: _Capture) -> tuple[dict[str, Any] | None, str | None]:
    manifest_observation = capture.files["manifest"]
    if manifest_observation.error in {"unsafe", "unreadable", "changed", "oversized"}:
        return None, "manifest_invalid" if manifest_observation.error == "oversized" else "package_unreadable"
    manifest, error = _parse_manifest(manifest_observation.data)
    if error:
        return None, error
    if manifest is None:
        return None, "manifest_invalid"
    name = manifest.get("name")
    if name != PLUGIN_NAME:
        return manifest, "manifest_id_mismatch"
    return manifest, None


def _code_analysis(capture: _Capture) -> dict[str, Any]:
    reasons: list[str] = []
    if not capture.home_ok:
        return {
            "files": "unsafe", "base_supported": False, "split_supported": False,
            "version": None, "manifest": None, "reasons": ["unsafe_package_path"],
        }
    if capture.config.error == "unsafe" or capture.plugins_dir.error == "unsafe" or capture.package_dir.error == "unsafe" or capture.code_dir.error == "unsafe":
        reasons.append("unsafe_package_path")
        return {
            "files": "unsafe", "base_supported": False, "split_supported": False,
            "version": None, "manifest": None, "reasons": reasons,
        }
    if (
        capture.plugins_dir.error == "unreadable"
        or capture.package_dir.error == "unreadable"
        or capture.code_dir.error == "unreadable"
    ):
        return {
            "files": "partial", "base_supported": False, "split_supported": False,
            "version": None, "manifest": None, "reasons": ["package_unreadable"],
        }
    if not capture.package_dir.present and capture.package_dir.error is None:
        reasons.append("package_missing")
        return {
            "files": "missing", "base_supported": False, "split_supported": False,
            "version": None, "manifest": None, "reasons": reasons,
        }

    required_names = ("manifest", "entrypoint", "init", "timeouts", "watchdog")
    required_missing = any(
        not capture.files[name].present and capture.files[name].error is None
        for name in required_names
    ) or not capture.code_dir.present
    base_unsafe = any(capture.files[name].error == "unsafe" for name in required_names)
    optional_unsafe = capture.files["routing"].error == "unsafe"
    any_unsafe = base_unsafe or optional_unsafe
    if any_unsafe:
        reasons.append("unsafe_package_path")
    if required_missing:
        reasons.append("package_partial")
    if any(capture.files[name].error in {"unreadable", "changed", "oversized"} for name in required_names):
        reasons.append("package_unreadable")
    if capture.files["routing"].error in {"unreadable", "changed", "oversized"}:
        reasons.append("package_unreadable")

    manifest, manifest_error = _manifest_from_capture(capture)
    if manifest_error:
        reasons.append(manifest_error)
    version = _version(manifest.get("version")) if manifest else None
    if version is None:
        reasons.append("version_or_provenance_unverified")

    source_error = False
    for name in ("entrypoint", "init", "timeouts", "watchdog"):
        observation = capture.files[name]
        if observation.data is None:
            source_error = True
            continue
        try:
            ast.parse(observation.data.decode("utf-8"))
        except (UnicodeError, SyntaxError, ValueError, TypeError):
            source_error = True
    if source_error and "package_unreadable" not in reasons:
        reasons.append("package_unreadable")

    base_supported = bool(
        capture.package_dir.present and capture.code_dir.present
        and not required_missing and not base_unsafe and not source_error
        and manifest is not None and manifest_error is None
    )
    split_marker = capture.files["routing"]
    split_supported = bool(
        base_supported and split_marker.present and split_marker.error is None
        and _literal_marker(split_marker.data)
    )
    if base_supported and not split_supported:
        reasons.append("split_marker_missing_or_invalid")

    if any_unsafe:
        file_state = "unsafe"
    elif required_missing:
        file_state = "partial"
    else:
        file_state = "complete"
    return {
        "files": file_state,
        "base_supported": base_supported,
        "split_supported": split_supported,
        "version": version,
        "manifest": manifest,
        "reasons": list(dict.fromkeys(reasons)),
    }


def _contains_env(value: Any) -> bool:
    if isinstance(value, str):
        return _ENV_REF_RE.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_env(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_env(item) for item in value)
    return False


def _managed_applies(managed_key: str, key: str) -> bool:
    return key == managed_key or key.startswith(managed_key + ".") or managed_key.startswith(key + ".")


def _read_selection(home: Path) -> _Selection:
    try:
        snapshot = effective_config.read_key_scoped(home, SELECTION_KEYS)
    except effective_config.EffectiveConfigChanged:
        return _Selection("unknown", False, None, ("profile_changed",))
    except effective_config.EffectiveConfigUnavailable:
        return _Selection("unknown", False, None, ("effective_selection_unavailable",))
    except (OSError, TypeError, ValueError, RuntimeError):
        return _Selection("unknown", False, None, ("effective_selection_unavailable",))

    try:
        effective_available = snapshot.effective_available
        managed_values = snapshot.managed_keys
        warning_values = snapshot.warnings
        if type(effective_available) is not bool:
            raise TypeError("invalid effective availability")
        if not isinstance(managed_values, (list, tuple, set, frozenset)) or any(
            not isinstance(item, str) for item in managed_values
        ):
            raise TypeError("invalid managed provenance")
        if not isinstance(warning_values, (list, tuple)) or any(
            not isinstance(item, str) for item in warning_values
        ):
            raise TypeError("invalid helper warnings")
        managed_keys = tuple(managed_values)
        managed = any(
            _managed_applies(item, key)
            for item in managed_keys
            for key in SELECTION_KEYS
        )
        warnings = tuple(warning_values)
        values = {key: snapshot.effective(key) for key in SELECTION_KEYS} if effective_available else None
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return _Selection("unknown", False, None, ("effective_selection_unavailable",))

    reasons: list[str] = []
    if not effective_available or values is None:
        reasons.append("effective_selection_unavailable")
    for warning in warnings:
        if not isinstance(warning, str):
            reasons.append("effective_selection_unavailable")
            continue
        if "env_expression" in warning:
            reasons.append("dynamic_selection_unsupported")
        elif "managed_provenance_unavailable" in warning:
            reasons.append("managed_provenance_unavailable")
        elif "malformed" in warning:
            reasons.append("plugin_selection_invalid")
        elif "effective_unavailable" in warning:
            reasons.append("effective_selection_unavailable")
        else:
            # Unknown/future warnings must not turn into an optimistic allow.
            reasons.append("effective_selection_unavailable")
    if values is not None and _contains_env(values):
        reasons.append("dynamic_selection_unsupported")

    if reasons:
        return _Selection("unknown", managed, getattr(snapshot, "cas_digest", None), tuple(dict.fromkeys(reasons)))
    enabled = values["plugins.enabled"]
    disabled = values["plugins.disabled"]
    for value in (enabled, disabled):
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            return _Selection("unknown", managed, getattr(snapshot, "cas_digest", None), ("plugin_selection_invalid",))
    enabled_values = enabled if isinstance(enabled, list) else []
    disabled_values = disabled if isinstance(disabled, list) else []
    if PLUGIN_NAME in disabled_values:
        python = "disabled"
        reason = "plugin_explicitly_disabled"
    elif PLUGIN_NAME not in enabled_values:
        python = "not_enabled"
        reason = "plugin_not_enabled"
    else:
        python = "enabled"
        reason = None
    if managed:
        reasons_out = ["managed_selection"]
    else:
        reasons_out = []
    if reason:
        reasons_out.insert(0, reason)
    return _Selection(python, managed, getattr(snapshot, "cas_digest", None), tuple(reasons_out))


def _profile_opt_out(service: Any, profile: str, stored: Any, *, read_skills: bool) -> tuple[bool, bool]:
    explicit = False
    if isinstance(stored, dict):
        entry = stored.get("profiles", {}).get(profile) if isinstance(stored.get("profiles"), dict) else None
        routing = entry.get("routing") if isinstance(entry, dict) else None
        if isinstance(routing, dict) and routing.get("enabled") is False:
            explicit = True
    if not read_skills:
        return explicit, False
    try:
        disabled = service._read_disabled(profile)
    except (OSError, TypeError, ValueError, RuntimeError):
        return explicit, False
    if not isinstance(disabled, list) or any(not isinstance(item, str) for item in disabled):
        return explicit, False
    return explicit or bool(SKILL_OPT_OUT_IDS.intersection(disabled)), True


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


def _trusted_metadata(data: bytes | None) -> dict[str, Any] | None:
    if data is None:
        return None
    try:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        outer = json.loads(
            data.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(outer, dict):
        return None
    record = outer.get(PLUGIN_NAME)
    if not isinstance(record, dict):
        return None
    allowed = {"revision", "source", "pinned", "catalog"}
    if set(record) - allowed or not {"revision", "source", "pinned"} <= set(record):
        return None
    revision, source, pinned = record.get("revision"), record.get("source"), record.get("pinned")
    if (
        not isinstance(revision, str) or _REVISION_RE.fullmatch(revision) is None
        or not isinstance(source, str) or source not in TRUSTED_SOURCES or pinned is not True
        or ("catalog" in record and record["catalog"] != PLUGIN_NAME)
    ):
        return None
    return {"revision": revision, "source": source}


def _stable(capture: _Capture) -> bool:
    return not any(
        observation.error == "changed"
        for observation in (
            capture.config, capture.plugins_dir, capture.package_dir,
            capture.code_dir, capture.store, *capture.files.values(),
        )
    )


def profile_readiness(service: Any, profile: str, stored: Any) -> dict[str, Any]:
    """Return the frozen schema-1 per-profile readiness DTO, without writes."""
    home = Path(service._profile_home(profile))
    root = Path(service.root)
    before = _capture(home, root, Path(service.store_path))
    selection = (
        _read_selection(home)
        if before.home_ok and before.config.present and before.config.error is None
        else _Selection("unknown", False, None, ("effective_selection_unavailable",))
    )
    opt_out, opt_out_known = _profile_opt_out(
        service, profile, stored,
        read_skills=before.home_ok and before.config.present and before.config.error is None,
    )
    if before.store.error in {"unsafe", "unreadable", "oversized", "changed"}:
        opt_out_known = False
    after = _capture(home, root, Path(service.store_path))
    analysis = _code_analysis(before)
    reasons = list(analysis["reasons"])
    reasons.extend(selection.reasons)
    if not opt_out_known:
        reasons.append("plugin_selection_invalid")
    if opt_out:
        reasons.append("routing_opt_out_preserved")
    metadata = _trusted_metadata(before.files["metadata"].data) if before.files["metadata"].error is None else None
    if analysis["version"] is None or metadata is None:
        reasons.append("version_or_provenance_unverified")

    changed = (
        before.signature != after.signature
        or "profile_changed" in selection.reasons
        or not _stable(before) or not _stable(after)
    )
    if changed:
        reasons.append("profile_changed")

    python = selection.python
    base_supported = analysis["base_supported"]
    split_supported = analysis["split_supported"]
    files = analysis["files"]
    if changed:
        state = "unsupported"
        base_supported = False
        split_supported = False
        identity = None
    elif files == "missing":
        state = "missing"
        identity = _sha((before.signature, python, opt_out, selection.digest))
    elif (
        files == "unsafe" or not base_supported or not opt_out_known or python == "unknown"
        or "package_unreadable" in reasons
    ):
        state = "unsupported"
        identity = None if files == "unsafe" else _sha((before.signature, python, opt_out, selection.digest))
    elif python == "enabled":
        state = "ready"
        identity = _sha((before.signature, python, selection.managed, opt_out, selection.digest))
    else:
        state = "disabled"
        identity = _sha((before.signature, python, selection.managed, opt_out, selection.digest))
    return {
        "schema": SCHEMA,
        "state": state,
        "reason_codes": list(dict.fromkeys(reasons)),
        "files": files,
        "python": python,
        "base_supported": bool(base_supported),
        "split_supported": bool(split_supported),
        "explicit_opt_out": bool(opt_out),
        "managed_selection": bool(selection.managed),
        "version": analysis["version"],
        "identity": identity,
    }


def timeout_code_support(home: Path, root: Path, store_path: Path) -> tuple[bool, bool]:
    """Return static base/split support only; selection is checked separately."""
    capture = _capture(Path(home), Path(root), Path(store_path))
    analysis = _code_analysis(capture)
    if not _stable(capture):
        return False, False
    return bool(analysis["base_supported"]), bool(analysis["split_supported"])


def timeout_python_enabled(home: Path) -> bool:
    selection = _read_selection(Path(home))
    return selection.python == "enabled"


def _root_identity(root: Path) -> str:
    info, _signature = _inspect(root, "dir", base=None)
    if info is None:
        raise _PathUnreadable
    canonical = str(Path(root).resolve(strict=True))
    payload = {
        "canonical_root": os.path.normcase(canonical),
        "st_dev": getattr(info, "st_dev", 0),
        "st_ino": getattr(info, "st_ino", 0),
    }
    return _sha(payload)


def _release_policy(capture: _Capture) -> dict[str, str] | None:
    analysis = _code_analysis(capture)
    if not analysis["base_supported"] or analysis["files"] == "unsafe":
        return None
    manifest = analysis["manifest"]
    if not isinstance(manifest, dict) or _version(manifest.get("version")) is None:
        return None
    if manifest.get("provides_tools") != ["coding_route"]:
        return None
    hooks = manifest.get("provides_hooks")
    middleware = manifest.get("provides_middleware")
    if (
        not isinstance(hooks, list) or any(not isinstance(item, str) for item in hooks)
        or len(hooks) != len(_EXPECTED_HOOKS) or set(hooks) != _EXPECTED_HOOKS
        or not isinstance(middleware, list) or any(not isinstance(item, str) for item in middleware)
        or len(middleware) != len(_EXPECTED_MIDDLEWARE) or set(middleware) != _EXPECTED_MIDDLEWARE
        or manifest.get("requires_env") != [] or "capabilities" in manifest
    ):
        return None
    package_json = capture.files["package_json"]
    if package_json.present or package_json.error is not None:
        return None
    pyproject = capture.files["pyproject"]
    if pyproject.data is None or pyproject.error is not None:
        return None
    try:
        try:
            import tomllib
        except ModuleNotFoundError as exc:
            if exc.name != "tomllib":
                return None
            import tomli as tomllib
        document = tomllib.loads(pyproject.data.decode("utf-8"))
    except (ImportError, ModuleNotFoundError, UnicodeError, ValueError):
        return None
    project = document.get("project") if isinstance(document, dict) else None
    if not isinstance(project, dict):
        return None
    if project.get("dependencies") != ["PyYAML>=6,<7"] or project.get("version") != analysis["version"]:
        return None
    metadata = _trusted_metadata(capture.files["metadata"].data)
    if metadata is None:
        return None
    return {
        "catalog_name": PLUGIN_NAME,
        "version": analysis["version"],
        "ref": metadata["revision"],
    }


def readiness_context(service: Any) -> dict[str, Any]:
    """Return stable base identity, active profile, and optional strict release policy."""
    root = Path(service.root)
    active_profile = service.active_profile()
    active_home = Path(service._profile_home(active_profile))
    release = None
    try:
        capture = _capture(active_home, root, Path(service.store_path))
        if _stable(capture):
            release = _release_policy(capture)
    except (OSError, RuntimeError, ValueError):
        release = None
    return {
        "schema": SCHEMA,
        "base_identity": _root_identity(root),
        "source_profile": active_profile,
        "release": release,
    }
