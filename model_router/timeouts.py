"""Profile-local runtime limits stored independently from model settings."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any

DEFAULT_DELEGATE_TOTAL_SECONDS = 0
DEFAULT_ROUTED_TOTAL_SECONDS = 3600

_SCHEMA = 1
_RELATIVE_PATH = Path("plugin-data") / "model-router" / "timeouts.json"
_LOCK_NAME = ".timeouts.lock"
_TIMEOUT_FIELDS = frozenset({"delegate_total_seconds", "routed_total_seconds"})
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


def validate_seconds(value: Any) -> float:
    """Return a finite, nonnegative float; booleans and coercions are rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("seconds must be a finite non-negative number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("seconds must be a finite non-negative number") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError("seconds must be a finite non-negative number")
    return result


def _defaults() -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "revision": 0,
        "delegate_total_seconds": float(DEFAULT_DELEGATE_TOTAL_SECONDS),
        "routed_total_seconds": float(DEFAULT_ROUTED_TOTAL_SECONDS),
    }


def _path_chain(path: Path) -> tuple[Path, ...]:
    """Return every lexical ancestor from the filesystem anchor through path."""
    parts = path.parts
    if not parts or not path.is_absolute():
        raise RuntimeError("timeout storage path is not absolute")
    current = Path(parts[0])
    chain = [current]
    for component in parts[1:]:
        current = current / component
        chain.append(current)
    return tuple(chain)


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except OSError as exc:
        raise RuntimeError("timeout storage path cannot be inspected") from exc


def _inspect_path(path: Path) -> os.stat_result | None:
    """Reject links, non-directory ancestors, and inaccessible existing components."""
    chain = _path_chain(path)
    final_info: os.stat_result | None = None
    missing_ancestor = False
    for index, component in enumerate(chain):
        is_final = index == len(chain) - 1
        if missing_ancestor:
            continue
        try:
            info = component.lstat()
        except FileNotFoundError:
            missing_ancestor = True
            continue
        except OSError as exc:
            raise RuntimeError("timeout storage path cannot be inspected") from exc
        if stat.S_ISLNK(info.st_mode) or _is_junction(component):
            raise RuntimeError("timeout storage path contains a link")
        if not is_final and not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("timeout storage ancestor is not a directory")
        if is_final:
            final_info = info
    return final_info


def _paths(home: Path) -> tuple[Path, Path]:
    if not isinstance(home, os.PathLike):
        raise ValueError("home must be a filesystem path")
    try:
        supplied = Path(home)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("home must be a filesystem path") from exc
    if ".." in supplied.parts:
        raise RuntimeError("timeout profile home contains parent traversal")
    try:
        absolute_home = supplied if supplied.is_absolute() else Path.cwd() / supplied
        # Path.absolute normalizes a relative spelling without resolving links;
        # the component walk below then rejects every existing link in its path.
        absolute_home = absolute_home.absolute()
    except OSError as exc:
        raise RuntimeError("timeout profile home cannot be resolved") from exc
    target = absolute_home / _RELATIVE_PATH
    lock = target.with_name(_LOCK_NAME)
    _inspect_path(target)
    _inspect_path(lock)
    return target, lock


def _reject_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "revision",
            "delegate_total_seconds",
            "routed_total_seconds",
        }:
            raise ValueError("timeout settings fields are invalid")
        schema = value["schema"]
        revision = value["revision"]
        if isinstance(schema, bool) or not isinstance(schema, int) or schema != _SCHEMA:
            raise ValueError("timeout settings schema is unsupported")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("timeout settings revision is invalid")
        return {
            "schema": _SCHEMA,
            "revision": revision,
            "delegate_total_seconds": validate_seconds(value["delegate_total_seconds"]),
            "routed_total_seconds": validate_seconds(value["routed_total_seconds"]),
        }
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("timeout settings file is invalid") from exc


def _read_current(home: Path) -> tuple[dict[str, Any] | None, bytes | None]:
    target, _lock = _paths(home)
    info = _inspect_path(target)
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise RuntimeError("timeout settings path is not a regular file")
    try:
        payload = target.read_bytes()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise RuntimeError("timeout settings file cannot be read") from exc
    return _parse(payload), payload


def _digest(payload: bytes | None) -> str:
    return "MISSING" if payload is None else hashlib.sha256(payload).hexdigest()


def _validate_values(values: Any) -> dict[str, float]:
    if not isinstance(values, dict) or set(values) != _TIMEOUT_FIELDS:
        raise ValueError("values must contain exactly the two timeout fields")
    return {
        "delegate_total_seconds": validate_seconds(values["delegate_total_seconds"]),
        "routed_total_seconds": validate_seconds(values["routed_total_seconds"]),
    }


def _validate_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return value


def read_timeouts(home: Path) -> dict[str, Any]:
    """Read this profile's exact timeout document, or return defaults if absent."""
    current, _payload = _read_current(home)
    return _defaults() if current is None else current


def timeout_digest(home: Path) -> str:
    """Return the exact file SHA-256, or MISSING; invalid files fail closed."""
    _current, payload = _read_current(home)
    return _digest(payload)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_timeouts(
    home: Path,
    values: dict[str, Any],
    *,
    expected_digest: str,
    expected_revision: int,
) -> dict[str, Any]:
    """CAS-write changed profile limits under a task-scoped cross-process lock."""
    clean_values = _validate_values(values)
    revision = _validate_revision(expected_revision)
    if not isinstance(expected_digest, str) or (
        expected_digest != "MISSING" and _DIGEST_RE.fullmatch(expected_digest) is None
    ):
        raise ValueError("expected_digest must be a timeout digest")

    target, lock_path = _paths(home)
    # Import lazily so importing this persistence API never initializes Service
    # (and so service can later consume this module without an import cycle).
    from .service import _FileLock, _atomic_write

    try:
        with _FileLock(lock_path):
            current, current_payload = _read_current(home)
            state = _defaults() if current is None else current
            if _digest(current_payload) != expected_digest or state["revision"] != revision:
                raise RuntimeError("timeout settings changed; reload before writing")

            if all(state[field] == clean_values[field] for field in _TIMEOUT_FIELDS):
                return state

            # Re-read and validate immediately before replacement so a writer
            # that does not cooperate with this lock is less likely to be lost.
            latest, latest_payload = _read_current(home)
            if latest_payload != current_payload:
                raise RuntimeError("timeout settings changed; reload before writing")
            if latest is not None and latest["revision"] != revision:
                raise RuntimeError("timeout settings changed; reload before writing")

            updated = {
                "schema": _SCHEMA,
                "revision": revision + 1,
                **clean_values,
            }
            payload = _json_bytes(updated)
            _paths(home)
            _atomic_write(target, payload)
            readback, readback_payload = _read_current(home)
            if readback_payload != payload or readback != updated:
                raise RuntimeError("timeout settings readback mismatch")
            return readback
    except RuntimeError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("timeout settings could not be written") from exc


def timeout_status(home: Path, *, enforcement_available: bool = True) -> dict[str, Any]:
    """Return a secret-free status DTO; invalid data is always read-only."""
    if not isinstance(enforcement_available, bool):
        raise ValueError("enforcement_available must be boolean")
    warnings: list[str] = []
    try:
        state = read_timeouts(home)
        valid = True
    except RuntimeError:
        # Unknown stored values are not defaults. Let older/new UI fail closed
        # and show unavailable state rather than inventing a numeric readback.
        state = {"schema": _SCHEMA, "revision": None,
                 "delegate_total_seconds": None, "routed_total_seconds": None}
        valid = False
        warnings.append("timeouts_invalid")
    if not enforcement_available:
        warnings.append("enforcement_unavailable")
    return {
        **state,
        "editable": valid and enforcement_available,
        "warnings": warnings,
    }
