"""Narrow, fail-closed reads of Hermes' effective native fallback settings.

This module intentionally exposes only the two native fallback keys and safe
provenance digests. It uses Hermes' supported effective-config and managed-scope
helpers; it never serializes complete config or credential values.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

_ENV_REF = re.compile(r"\$\{[^}]+\}")
_NATIVE_KEYS = ("fallback_providers", "fallback_model")


class EffectiveConfigUnavailable(RuntimeError):
    """Supported effective-config/provenance helpers could not verify a snapshot."""


class EffectiveConfigChanged(RuntimeError):
    """The user or managed config changed during a single snapshot read."""


def _freeze(value: Any) -> Any:
    """Recursively freeze YAML values so one validation/CAS view cannot be mutated."""
    if isinstance(value, dict):
        pairs = [(_freeze(key), _freeze(item)) for key, item in value.items()]
        return ("dict", tuple(sorted(pairs, key=repr)))
    if isinstance(value, list):
        return ("list", tuple(_freeze(item) for item in value))
    if isinstance(value, tuple):
        return ("tuple", tuple(_freeze(item) for item in value))
    if isinstance(value, set):
        return ("set", tuple(sorted((_freeze(item) for item in value), key=repr)))
    if value is None or isinstance(value, (str, int, float, bool)):
        return ("value", value)
    # SafeLoader can produce dates and other non-JSON scalars. They are not
    # editable native values; retain only a stable opaque marker for the digest.
    rendered = repr(value).encode("utf-8", errors="replace")
    return ("opaque", f"{type(value).__module__}.{type(value).__qualname__}", hashlib.sha256(rendered).hexdigest())


def _thaw(value: Any) -> Any:
    kind = value[0]
    if kind == "dict":
        return {_thaw(key): _thaw(item) for key, item in value[1]}
    if kind == "list":
        return [_thaw(item) for item in value[1]]
    if kind == "tuple":
        return tuple(_thaw(item) for item in value[1])
    if kind == "set":
        return {_thaw(item) for item in value[1]}
    if kind == "value":
        return value[1]
    return {"__unsupported_config_scalar__": value[1]}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr)
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def _config_value(config: dict[str, Any], key: str) -> Any:
    value: Any = config
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _contains_env_ref(value: Any) -> bool:
    if isinstance(value, str):
        return _ENV_REF.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_env_ref(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_env_ref(item) for item in value)
    return False


def _file_signature(path: Path | None) -> str:
    if path is None:
        return _digest({"present": False})
    try:
        stat = path.stat()
        payload = path.read_bytes()
    except FileNotFoundError:
        return _digest({"present": False, "path": _digest(os.path.normcase(str(path.resolve(strict=False))))})
    except OSError as exc:
        raise EffectiveConfigUnavailable("config provenance is unreadable") from exc
    identity = {
        "present": True,
        "path": _digest(os.path.normcase(str(path.resolve(strict=False)))),
        "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
        "size": stat.st_size,
        "inode": getattr(stat, "st_ino", 0),
        "ctime_ns": getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
    }
    return _digest(identity)


def _helpers() -> Any:
    """Load the installed Hermes helper APIs; missing APIs are never treated as no overlay."""
    try:
        from agent.secret_scope import reset_secret_scope, set_secret_scope
        from hermes_cli import config, managed_scope
        from hermes_cli.config_effective import load_user_config_effective
        from hermes_cli.config_read_errors import FailedConfigRead
    except Exception as exc:  # import/version failures must fail closed
        raise EffectiveConfigUnavailable("supported Hermes config helpers are unavailable") from exc
    required = (
        getattr(config, "read_user_config_raw", None),
        getattr(managed_scope, "load_managed_config", None),
        getattr(managed_scope, "managed_config_keys", None),
        getattr(managed_scope, "get_managed_dir", None),
        load_user_config_effective,
        getattr(FailedConfigRead, "__name__", None),
        set_secret_scope,
        reset_secret_scope,
    )
    if not all(required):
        raise EffectiveConfigUnavailable("supported Hermes config helpers are incomplete")
    return type("HermesConfigHelpers", (), {
        "read_user_config_raw": staticmethod(config.read_user_config_raw),
        "load_managed_config": staticmethod(managed_scope.load_managed_config),
        "managed_config_keys": staticmethod(managed_scope.managed_config_keys),
        "get_managed_dir": staticmethod(managed_scope.get_managed_dir),
        "load_user_config_effective": staticmethod(load_user_config_effective),
        "FailedConfigRead": FailedConfigRead,
        "set_secret_scope": staticmethod(set_secret_scope),
        "reset_secret_scope": staticmethod(reset_secret_scope),
    })()


@dataclass(frozen=True)
class NativeFallbackSnapshot:
    """Immutable native-key view plus digests; raw advanced values never enter plans/status."""

    _raw: tuple[tuple[str, Any], ...]
    _effective: tuple[tuple[str, Any], ...]
    managed_keys: tuple[str, ...]
    managed_signature: str
    effective_available: bool
    warnings: tuple[str, ...]
    keys: tuple[str, ...] = _NATIVE_KEYS

    def raw(self, key: str) -> Any:
        return _thaw(dict(self._raw)[key])

    def effective(self, key: str) -> Any:
        if not self.effective_available:
            return None
        return _thaw(dict(self._effective)[key])

    @property
    def provenance_digest(self) -> str:
        return _digest({"managed_keys": self.managed_keys, "managed_signature": self.managed_signature})

    @property
    def cas_digest(self) -> str:
        return _digest({
            "keys": self.keys,
            "raw": self._raw,
            "effective": self._effective,
            "effective_available": self.effective_available,
            "managed_keys": self.managed_keys,
            "managed_signature": self.managed_signature,
            "warnings": self.warnings,
        })


def make_snapshot(
    *,
    raw: dict[str, Any],
    effective: dict[str, Any] | None,
    managed_keys: tuple[str, ...] | list[str] | set[str] = (),
    managed_signature: str = "fixture-no-managed-config",
    warnings: tuple[str, ...] | list[str] = (),
) -> NativeFallbackSnapshot:
    """Build an immutable snapshot for explicit fake-helper tests only."""
    keys = tuple(sorted(set(managed_keys)))
    return NativeFallbackSnapshot(
        _raw=tuple((key, _freeze(raw.get(key))) for key in _NATIVE_KEYS),
        _effective=tuple((key, _freeze((effective or {}).get(key))) for key in _NATIVE_KEYS),
        managed_keys=keys,
        managed_signature=managed_signature,
        effective_available=effective is not None,
        warnings=tuple(warnings),
        keys=_NATIVE_KEYS,
    )


def make_key_snapshot(
    *,
    keys: tuple[str, ...] | list[str],
    raw: dict[str, Any],
    effective: dict[str, Any] | None,
    managed_keys: tuple[str, ...] | list[str] | set[str] = (),
    managed_signature: str = "fixture-no-managed-config",
    warnings: tuple[str, ...] | list[str] = (),
) -> NativeFallbackSnapshot:
    """Build an immutable, key-scoped snapshot for explicit fake-helper tests."""
    selected = tuple(keys)
    if not selected or any(not isinstance(key, str) or not key for key in selected):
        raise ValueError("at least one config key is required")
    return NativeFallbackSnapshot(
        _raw=tuple((key, _freeze(raw.get(key))) for key in selected),
        _effective=tuple((key, _freeze((effective or {}).get(key))) for key in selected),
        managed_keys=tuple(sorted(set(managed_keys))),
        managed_signature=managed_signature,
        effective_available=effective is not None,
        warnings=tuple(warnings),
        keys=selected,
    )


def _managed_applies(managed_key: str, key: str) -> bool:
    return key == managed_key or key.startswith(managed_key + ".") or managed_key.startswith(key + ".")


def read_key_scoped(
    profile_home: Path,
    keys: tuple[str, ...] | list[str],
    *,
    helpers: Any | None = None,
) -> NativeFallbackSnapshot:
    """Read selected effective config keys and only their managed provenance.

    ``helpers`` is an explicit test seam matching Hermes' installed helper APIs.
    Production callers omit it and use the genuine installed Hermes helpers.
    Profile-scoped expansion runs under an empty secret scope: credential refs
    remain unresolved instead of borrowing process/another-profile credentials.
    Managed config env refs are not expanded here because Hermes intentionally
    resolves those from process env; they make native editing read-only.
    """
    home = Path(profile_home).expanduser().resolve(strict=False)
    selected_keys = tuple(keys)
    if not selected_keys or len(set(selected_keys)) != len(selected_keys) or any(
        not isinstance(key, str) or not key or any(not part for part in key.split("."))
        for key in selected_keys
    ):
        raise ValueError("config keys must be a non-empty unique dotted-key list")
    label = "native" if selected_keys == _NATIVE_KEYS else "scoped"
    config_path = home / "config.yaml"
    api = helpers if helpers is not None else _helpers()
    try:
        managed_dir = api.get_managed_dir()
        managed_path = Path(managed_dir) / "config.yaml" if managed_dir is not None else None
        user_before = _file_signature(config_path)
        managed_before = _file_signature(managed_path)
        # Hermes normalizes a scalar/list YAML root to {}, so its return type
        # alone cannot prove the source file is a valid editable mapping.
        import yaml
        original_root = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(original_root, dict):
            raise EffectiveConfigUnavailable("profile config source is not a mapping")
        raw_config = api.read_user_config_raw(config_path)
        if not isinstance(raw_config, dict):
            raise EffectiveConfigUnavailable("profile config is not a mapping")
        managed_config = api.load_managed_config()
        if not isinstance(managed_config, dict):
            raise EffectiveConfigUnavailable("managed config provenance is unavailable")
        managed_keys_value = api.managed_config_keys()
        if not isinstance(managed_keys_value, (set, frozenset, list, tuple)) or any(not isinstance(key, str) for key in managed_keys_value):
            raise EffectiveConfigUnavailable("managed config provenance is unavailable")
        all_managed_keys = tuple(sorted(set(managed_keys_value)))
        managed_keys = tuple(sorted(
            key for key in all_managed_keys
            if any(_managed_applies(key, selected) for selected in selected_keys)
        ))
        managed_values = {key: _config_value(managed_config, key) for key in selected_keys}
        managed_signature = _digest({"managed_keys": managed_keys, "managed_values": managed_values})

        warnings: list[str] = []
        for selected in selected_keys:
            parent: Any = raw_config
            for component in selected.split(".")[:-1]:
                parent = parent.get(component) if isinstance(parent, dict) else parent
                if parent is None:
                    break
                if not isinstance(parent, dict):
                    warnings.append(f"{label}_fallback_malformed")
                    break
        if managed_path is not None and managed_path.exists() and not managed_config and not managed_keys:
            # The supported managed loader is fail-open on parse errors. An
            # existing but apparently empty file cannot prove overlay absence.
            warnings.append(f"{label}_managed_provenance_unavailable")
        if any(_contains_env_ref(value) for value in managed_values.values()):
            warnings.append(f"{label}_managed_env_expression_readonly")
        if any(_contains_env_ref(_config_value(raw_config, key)) for key in selected_keys):
            warnings.append(f"{label}_fallback_env_expression")

        effective: dict[str, Any] | None = None
        unsafe_managed = any(warning in warnings for warning in (
            f"{label}_managed_provenance_unavailable",
            f"{label}_managed_env_expression_readonly",
        ))
        if not unsafe_managed:
            token = api.set_secret_scope({}, profile_home=str(home))
            try:
                loaded = api.load_user_config_effective(config_path, fail_closed=True)
            finally:
                api.reset_secret_scope(token)
            if isinstance(loaded, api.FailedConfigRead) or not isinstance(loaded, dict):
                raise EffectiveConfigUnavailable("effective profile config is unavailable")
            effective = {key: _config_value(loaded, key) for key in selected_keys}
        else:
            warnings.append(f"{label}_effective_unavailable")

        user_after = _file_signature(config_path)
        managed_after = _file_signature(managed_path)
        if user_before != user_after or managed_before != managed_after:
            raise EffectiveConfigChanged("profile or managed config changed during snapshot")
        raw = {key: _config_value(raw_config, key) for key in selected_keys}
        effective_values = effective if effective is None else {key: effective[key] for key in selected_keys}
        return make_key_snapshot(
            keys=selected_keys,
            raw=raw,
            effective=effective_values,
            managed_keys=managed_keys,
            managed_signature=managed_signature,
            warnings=warnings,
        )
    except (EffectiveConfigUnavailable, EffectiveConfigChanged):
        raise
    except Exception as exc:
        raise EffectiveConfigUnavailable("effective native fallback state is unavailable") from exc


def read_native_fallback(profile_home: Path, *, helpers: Any | None = None) -> NativeFallbackSnapshot:
    """Backward-compatible native fallback snapshot wrapper."""
    return read_key_scoped(profile_home, _NATIVE_KEYS, helpers=helpers)
