"""Profile-scoped canonical settings and safe Hermes CLI projection."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import effective_config, fallback_policy, timeouts

SCHEMA = 2
STORE_RELATIVE = Path("plugin-data") / "model-router" / "settings.json"
STATE_RELATIVE = Path("plugin-data") / "model-router" / "recent_apply.json"
SKILL_NAME = "adaptive-coding-orchestration"
COMPAT_SKILL_SOURCE = Path(__file__).resolve().parents[1] / "compat" / SKILL_NAME / "SKILL.md"
PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
PROVIDER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
MODEL_ROLES = ("main", "delegation", "compression", "title")
MODEL_KEYS = {
    "main": ("model.provider", "model.default", "agent.reasoning_effort"),
    "delegation": ("delegation.provider", "delegation.model", "delegation.reasoning_effort"),
    "compression": ("auxiliary.compression.provider", "auxiliary.compression.model", "auxiliary.compression.reasoning_effort"),
    "title": ("auxiliary.title_generation.provider", "auxiliary.title_generation.model", "auxiliary.title_generation.reasoning_effort"),
}
STALE_KEYS = {
    "main": ("model.base_url", "model.api_mode"),
    "delegation": ("delegation.base_url", "delegation.api_mode"),
}
DELEGATION_FALLBACK_KEY = "delegation.fallback_providers"


class ServiceError(RuntimeError):
    """A safe, non-secret settings-service failure."""


class RevisionConflict(ServiceError):
    """The canonical revision or a projected config value changed since preview."""


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()).expanduser().resolve(strict=False)
    except ImportError:
        value = os.environ.get("HERMES_HOME")
        if not value:
            raise ServiceError("Set HERMES_HOME explicitly for the standalone CLI")
        return Path(value).expanduser().resolve(strict=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)


def _atomic_write(path: Path, payload: bytes) -> None:
    _secure_dir(path.parent)
    tmp: str | None = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _read_json(path: Path, *, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ServiceError("settings data is unreadable") from exc


def _validate_token(value: Any, *, field: str, pattern: re.Pattern[str], empty: bool = False) -> str:
    if not isinstance(value, str) or value != value.strip() or (not value and not empty):
        raise ValueError(f"{field} must be a literal token")
    if value and pattern.fullmatch(value) is None:
        raise ValueError(f"{field} contains unsupported characters")
    if value.casefold() == "keep":
        raise ValueError(f"{field} cannot use KEEP")
    return value


def _route(value: Any, *, allow_empty_model: bool = False) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "reasoning"}:
        raise ValueError("route must contain exactly provider, model, and reasoning")
    provider = _validate_token(value["provider"], field="provider", pattern=PROVIDER_RE)
    model = _validate_token(value["model"], field="model", pattern=MODEL_RE, empty=allow_empty_model)
    effort = value["reasoning"]
    if not isinstance(effort, str) or effort not in EFFORTS:
        raise ValueError("reasoning must be an explicitly supported effort")
    return {"provider": provider, "model": model, "reasoning": effort}


def _models(value: Any, *, allow_empty_model: bool = False) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != set(MODEL_ROLES):
        raise ValueError("models must define main, delegation, compression, and title")
    return {role: _route(value[role], allow_empty_model=allow_empty_model) for role in MODEL_ROLES}


def _routing(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"enabled", "heavy", "light", "fallback"}:
        raise ValueError("routing must define enabled, heavy, light, and fallback")
    if not isinstance(value["enabled"], bool):
        raise ValueError("routing.enabled must be boolean")
    resolved: dict[str, dict[str, Any]] = {}
    for key, expected in (("heavy", "main"), ("light", "delegation")):
        item = value[key]
        if not isinstance(item, dict) or set(item) != {"follow", "custom"}:
            raise ValueError(f"routing.{key} must define follow and custom")
        follow = item["follow"]
        if follow not in {expected, "custom"}:
            raise ValueError(f"routing.{key}.follow must be {expected} or custom")
        custom = None if item["custom"] is None else _route(item["custom"])
        if follow == "custom" and custom is None:
            raise ValueError(f"routing.{key}.custom is required when following custom")
        if follow != "custom" and custom is not None:
            raise ValueError(f"routing.{key}.custom must be null when following {expected}")
        resolved[key] = {"follow": follow, "custom": custom}
    fallback = value["fallback"]
    if not isinstance(fallback, dict) or set(fallback) != {"enabled", "heavy", "light"} or not isinstance(fallback["enabled"], bool):
        raise ValueError("routing.fallback must define enabled, heavy, and light")
    fb_heavy = None if fallback["heavy"] is None else _route(fallback["heavy"])
    fb_light = None if fallback["light"] is None else _route(fallback["light"])
    if fallback["enabled"] and (fb_heavy is None or fb_light is None):
        raise ValueError("enabled fallback requires explicit Heavy and Light routes")
    return {"enabled": value["enabled"], **resolved, "fallback": {"enabled": fallback["enabled"], "heavy": fb_heavy, "light": fb_light}}


class _FileLock:
    def __init__(self, path: Path, timeout: float = 8.0):
        self.path, self.timeout, self.token = path, timeout, uuid.uuid4().hex

    def __enter__(self):
        _secure_dir(self.path.parent)
        deadline = time.monotonic() + self.timeout
        data = json.dumps({"pid": os.getpid(), "time": time.time(), "token": self.token}).encode()
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    os.write(fd, data)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return self
            except FileExistsError:
                # Do not reap an O_EXCL lock by PID: another process may replace
                # it between inspection and unlink. Stale locks require explicit
                # operator recovery after checking the owner; fail closed here.
                if time.monotonic() >= deadline:
                    raise ServiceError("timed out acquiring settings lock")
                time.sleep(0.05)

    def __exit__(self, *_exc):
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("token") == self.token:
                self.path.unlink()
        except (OSError, ValueError, json.JSONDecodeError):
            pass


class Service:
    """Settings authority for one Hermes base. ``root`` is a testable Hermes base override."""

    PLAN_TTL = 300.0
    PLAN_LIMIT = 64

    def __init__(self, root: Path | None = None, writer: Callable[..., Any] | None = None):
        self._root_override = Path(root).expanduser().resolve(strict=False) if root is not None else None
        self.writer = writer
        self._plans: dict[str, dict[str, Any]] = {}
        # Exact bytes, not mtime: every read still sees external/config CLI edits.
        self._config_reads: dict[str, tuple[bytes, Any]] = {}

    @property
    def root(self) -> Path:
        if self._root_override is not None:
            return self._root_override
        home = _hermes_home()
        if home.parent.name == "profiles" and not home.name.startswith("."):
            return home.parent.parent
        return home

    @property
    def store_path(self) -> Path:
        return self.root / STORE_RELATIVE

    @property
    def _lock_path(self) -> Path:
        return self.store_path.with_name(".settings.lock")

    def _active_home(self) -> Path:
        if self._root_override is not None:
            return self._root_override
        return _hermes_home()

    def active_profile(self) -> str:
        home = self._active_home()
        if home.parent.name == "profiles" and not home.name.startswith(".") and PROFILE_RE.fullmatch(home.name):
            return home.name
        return "default"

    def _profile_home(self, name: str) -> Path:
        return self.root if name == "default" else self.root / "profiles" / name

    def _discover_profiles(self) -> list[str]:
        root = self.root.resolve(strict=False)
        found: set[str] = set()
        default_config = root / "config.yaml"
        if default_config.is_file() and not default_config.is_symlink():
            found.add("default")
        profiles_dir = root / "profiles"
        try:
            entries = list(profiles_dir.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if entry.name.startswith(".") or PROFILE_RE.fullmatch(entry.name) is None or not entry.is_dir():
                continue
            if not _inside(entry, profiles_dir):
                continue
            config = entry / "config.yaml"
            try:
                if not config.is_file() or not _inside(config, entry) or config.is_symlink():
                    continue
            except OSError:
                continue
            found.add(entry.name)
        return sorted(found, key=lambda item: (item != "default", item))

    def _require_profile(self, name: Any, discovered: list[str] | None = None) -> str:
        if not isinstance(name, str) or PROFILE_RE.fullmatch(name) is None:
            raise ValueError("invalid profile name")
        available = discovered if discovered is not None else self._discover_profiles()
        if name not in available:
            raise ValueError("profile is not an existing config-backed profile")
        return name

    def _load_store(self) -> dict[str, Any] | None:
        data = _read_json(self.store_path)
        if data is None:
            return None
        if (
            not isinstance(data, dict)
            or set(data) != {"schema", "revision", "profiles"}
            or isinstance(data.get("schema"), bool)
            or data.get("schema") not in {1, SCHEMA}
        ):
            raise ServiceError("settings schema is invalid")
        if not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool) or data["revision"] < 0:
            raise ServiceError("settings revision is invalid")
        if not isinstance(data.get("profiles"), dict):
            raise ServiceError("settings profiles are invalid")
        normalized: dict[str, Any] = {}
        for name, entry in data["profiles"].items():
            if PROFILE_RE.fullmatch(name) is None or not isinstance(entry, dict):
                raise ServiceError("settings profile entry is invalid")
            try:
                if data["schema"] == 1:
                    if set(entry) != {"models", "routing"}:
                        raise ValueError("schema1 profile entry has unknown fields")
                    models = _models(entry["models"], allow_empty_model=True)
                    routing = _routing(entry["routing"])
                    native_fallback = None
                    delegation_fallback = None
                    legacy_consent = None
                    if routing["fallback"]["enabled"]:
                        legacy_consent = fallback_policy.make_consent(
                            name, "routing", routing["fallback"], source="legacy-approved"
                        )
                    consent = {"native": None, "routing": legacy_consent, "delegation": None}
                else:
                    old_fields = {"models", "routing", "native_fallback", "fallback_consent"}
                    if not old_fields <= set(entry) or set(entry) - old_fields - {"delegation_fallback"}:
                        raise ValueError("schema2 profile entry has unknown fields")
                    models = _models(entry["models"], allow_empty_model=True)
                    routing = _routing(entry["routing"])
                    native_fallback = self._validate_native_fallback(entry["native_fallback"])
                    delegation_fallback = self._validate_delegation_fallback(entry.get("delegation_fallback"))
                    raw_consent = entry["fallback_consent"]
                    if (
                        not isinstance(raw_consent, dict)
                        or not {"native", "routing"} <= set(raw_consent)
                        or set(raw_consent) - {"native", "routing", "delegation"}
                    ):
                        raise ValueError("fallback consent must define native, routing, and optional delegation")
                    consent = {
                        "native": fallback_policy.validate_consent(raw_consent["native"]),
                        "routing": fallback_policy.validate_consent(raw_consent["routing"]),
                        "delegation": fallback_policy.validate_consent(raw_consent.get("delegation")),
                    }
                    for scope in ("native", "routing", "delegation"):
                        item = consent[scope]
                        if item is not None and item["allow_task_rerun"] is not (scope == "routing"):
                            raise ValueError("fallback consent scope flags are invalid")
                normalized[name] = {
                    "models": models,
                    "routing": routing,
                    "native_fallback": native_fallback,
                    "delegation_fallback": delegation_fallback,
                    "fallback_consent": consent,
                }
            except (TypeError, ValueError, KeyError) as exc:
                raise ServiceError("settings profile entry is invalid") from exc
        # Schema-1 reads are normalized only in memory. Persistence occurs only
        # through an explicit settings apply or the existing initializer.
        return {"schema": data["schema"], "revision": data["revision"], "profiles": normalized}

    def _validate_native_fallback(self, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"enabled", "chain"} or not isinstance(value["enabled"], bool):
            raise ValueError("native fallback must define enabled and chain")
        chain = value["chain"]
        if not isinstance(chain, list) or len(chain) > 5:
            raise ValueError("native fallback chain must contain at most five entries")
        parsed: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in chain:
            if not isinstance(item, dict) or set(item) != {"provider", "model"}:
                raise ValueError("native fallback entries must contain provider and model")
            provider = _validate_token(item["provider"], field="fallback provider", pattern=PROVIDER_RE)
            model = _validate_token(item["model"], field="fallback model", pattern=MODEL_RE)
            identity = (provider.casefold(), model.casefold())
            if identity in seen:
                raise ValueError("native fallback chain entries must be distinct")
            seen.add(identity)
            parsed.append({"provider": provider, "model": model})
        return {"enabled": value["enabled"], "chain": parsed}

    def _validate_delegation_fallback(self, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"mode", "chain"}:
            raise ValueError("delegation fallback must define mode and chain")
        mode, chain = value["mode"], value["chain"]
        if mode not in {"default", "off", "custom"}:
            raise ValueError("delegation fallback mode is invalid")
        if not isinstance(chain, list):
            raise ValueError("delegation fallback chain must be a list")
        if mode != "custom" and chain:
            raise ValueError("default and off delegation modes require an empty chain")
        if mode == "custom" and not 1 <= len(chain) <= 5:
            raise ValueError("custom delegation fallback requires one to five routes")
        parsed: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in chain:
            if not isinstance(item, dict) or set(item) != {"provider", "model"}:
                raise ValueError("delegation routes must contain only provider and model")
            provider = _validate_token(item["provider"], field="delegation fallback provider", pattern=PROVIDER_RE)
            model = _validate_token(item["model"], field="delegation fallback model", pattern=MODEL_RE)
            identity = (provider.casefold(), model.casefold())
            if identity in seen:
                raise ValueError("delegation fallback routes must be distinct")
            seen.add(identity)
            parsed.append({"provider": provider, "model": model})
        return {"mode": mode, "chain": parsed}

    def _cli_path(self) -> str:
        stable = self.root / "bin" / ("hermes.exe" if os.name == "nt" else "hermes")
        path = str(stable) if stable.is_file() else shutil.which("hermes")
        if not path:
            raise ServiceError("Hermes CLI launcher was not found")
        candidate = Path(path).expanduser().resolve(strict=True)
        if not candidate.is_file():
            raise ServiceError("Hermes CLI launcher is unavailable")
        return str(candidate)

    @staticmethod
    def _loaded_cli_paths() -> list[str]:
        """Same loaded core/dependencies, never renderer paths or boot a new venv."""
        try:
            import hermes_cli
            import yaml
            import rich
            import pydantic
            modules = (hermes_cli, yaml, rich, pydantic)
            return list(dict.fromkeys(str(Path(module.__file__).resolve().parents[1]) for module in modules))
        except (ImportError, TypeError, OSError):
            return []

    def _env(self, profile: str) -> dict[str, str]:
        env = dict(os.environ)
        env["HERMES_HOME"] = str(self._profile_home(profile))
        for key in ("HERMES_PROFILE", "HERMES_SESSION_ID", "HERMES_PARENT_SESSION_ID", "HERMES_CHILD_SESSION_SOURCE"):
            env.pop(key, None)
        paths = self._loaded_cli_paths()
        if paths:
            env["PYTHONPATH"] = os.pathsep.join(paths)
            env.pop("PYTHONHOME", None)
            env.pop("VIRTUAL_ENV", None)
        return env

    def _command(self, profile: str, *args: str) -> list[str]:
        # Native cli.exec uses this same-interpreter entry point. Re-running the
        # package-manager launcher for each key can spend seconds per setting.
        prefix = [sys.executable, "-m", "hermes_cli.main"] if self._loaded_cli_paths() else [self._cli_path()]
        return [*prefix, "--profile", profile, *args]

    def _read_key(self, profile: str, key: str) -> Any:
        # Reads are local and narrowly selected; launching 143 CLI processes per
        # UI refresh was both slow and unnecessary. Writes still use Hermes CLI.
        import yaml
        self._require_profile(profile)
        try:
            raw = (self._profile_home(profile) / "config.yaml").read_bytes()
            cached = self._config_reads.get(profile)
            if cached is None or cached[0] != raw:
                value = yaml.safe_load(raw.decode("utf-8")) or {}
                self._config_reads[profile] = (raw, value)
            else:
                value = cached[1]
            for part in key.split("."):
                if not isinstance(value, dict):
                    return None
                value = value.get(part)
            return copy.deepcopy(value)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ServiceError(f"could not read config key {key}") from exc

    @contextmanager
    def _batch_writes(self):
        # Reuse the native config CLI dispatcher without re-importing every
        # Hermes command/plugin once per key. Isolate each profile's process.
        from .config_writer import ConfigWriter
        prior = getattr(self, "_config_workers", None)
        prior_receipt = getattr(self, "_batch_receipt", None)
        workers = {}
        self._batch_receipt = None
        self._config_workers = workers if self.writer is None and self._loaded_cli_paths() else None
        try:
            yield
        finally:
            receipt = self._batch_receipt
            self._config_workers = prior
            self._batch_receipt = prior_receipt
            failed = []
            for profile, worker in workers.items():
                try:
                    if worker.close() is False:
                        failed.append(profile)
                except Exception:
                    failed.append(profile)
            if failed and receipt is not None:
                receipt["config_status"] = receipt["status"]
                receipt["status"] = "unknown"
                receipt["cleanup_failed_profiles"] = sorted(failed)
                self._store_apply(receipt)

    def _write_key(self, profile: str, key: str, value: Any) -> None:
        if self.writer is not None:
            self.writer(profile, key, value)
            return
        workers = getattr(self, "_config_workers", None)
        if workers is not None:
            from .config_writer import ConfigWriter, ConfigWriterError
            self._require_profile(profile)
            try:
                if profile not in workers:
                    workers[profile] = ConfigWriter(self._env(profile))
                workers[profile].set(key, value)
                return
            except (OSError, ConfigWriterError) as exc:
                raise ServiceError(f"could not write config key {key}") from exc
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        try:
            result = subprocess.run(
                self._command(profile, "config", "set", key, rendered, "--force"),
                env=self._env(profile), shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ServiceError(f"could not write config key {key}") from exc
        if result.returncode != 0:
            raise ServiceError(f"could not write config key {key}")

    def _actual_models(self, profile: str, *, tolerate: bool = False) -> dict[str, dict[str, str]]:
        values: dict[str, dict[str, str]] = {}
        for role, keys in MODEL_KEYS.items():
            try:
                provider, model, effort = (self._read_key(profile, key) for key in keys)
            except ServiceError:
                if tolerate:
                    return {}
                raise
            provider = provider if isinstance(provider, str) else ""
            model = model if isinstance(model, str) else ""
            effort = effort if isinstance(effort, str) else ""
            if role != "main":
                if not provider or provider == "auto":
                    provider = values["main"]["provider"]
                if not model:
                    model = values["main"]["model"]
                if not effort:
                    effort = values["main"]["reasoning"]
            if not provider or not model:
                if tolerate:
                    return {}
                raise ServiceError(f"profile {profile} has no resolved {role} model")
            if not effort:
                effort = "medium"
            values[role] = {"provider": provider, "model": model, "reasoning": effort}
        try:
            return _models(values, allow_empty_model=False)
        except ValueError as exc:
            if tolerate:
                return {}
            raise ServiceError(f"profile {profile} has invalid model settings") from exc

    def _default_routing(self, enabled: bool = False, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        fallback = fallback or {"enabled": False, "heavy": None, "light": None}
        return {
            "enabled": enabled,
            "heavy": {"follow": "main", "custom": None},
            "light": {"follow": "delegation", "custom": None},
            "fallback": fallback,
        }

    @staticmethod
    def _check_distinct_routes(routing: dict[str, Any], models: dict[str, dict[str, str]]) -> None:
        if not routing["enabled"]:
            return
        heavy = models["main"] if routing["heavy"]["follow"] == "main" else routing["heavy"]["custom"]
        light = models["delegation"] if routing["light"]["follow"] == "delegation" else routing["light"]["custom"]
        if (heavy["provider"], heavy["model"]) == (light["provider"], light["model"]):
            raise ValueError("enabled Heavy and Light routes must resolve to distinct models")

    @staticmethod
    def _check_changed_routing_fallbacks(before: dict, after: dict) -> None:
        """Validate final primaries, including retained spares, without adopting them."""
        def primary_ids(entry):
            routing, models = entry["routing"], entry["models"]
            return tuple(
                (route["provider"].casefold(), route["model"].casefold())
                for role, model_role in (("heavy", "main"), ("light", "delegation"))
                for route in [models[model_role] if routing[role]["follow"] == model_role else routing[role]["custom"]]
            )
        for name, entry in after.items():
            fallback = entry["routing"]["fallback"]
            if not fallback["enabled"]:
                continue
            old = before.get(name)
            primaries = primary_ids(entry)
            if old is not None and primaries == primary_ids(old) and fallback == old["routing"]["fallback"]:
                continue
            spares = tuple((fallback[role]["provider"].casefold(), fallback[role]["model"].casefold()) for role in ("heavy", "light"))
            if spares[0] == spares[1]:
                raise ValueError("enabled Heavy and Light fallbacks must be distinct")
            if any(primary == spare for primary, spare in zip(primaries, spares)):
                raise ValueError("fallback route must differ from its final primary route")

    def _fallback_for(self, profile: str, fallbacks: dict[str, Any] | None) -> dict[str, Any]:
        if not fallbacks:
            return {"enabled": False, "heavy": None, "light": None}
        raw = fallbacks.get(profile) if profile in fallbacks else fallbacks
        if not isinstance(raw, dict):
            raise ValueError("fallbacks must map profiles to Heavy/Light routes")
        if "fallback" in raw and set(raw) <= {"fallback"}:
            raw = raw["fallback"]
        enabled = raw.get("enabled", bool(raw.get("heavy") and raw.get("light")))
        heavy = None if raw.get("heavy") is None else _route(raw["heavy"])
        light = None if raw.get("light") is None else _route(raw["light"])
        if not isinstance(enabled, bool):
            raise ValueError("fallback enabled must be boolean")
        if enabled and (heavy is None or light is None):
            raise ValueError("enabled fallback requires explicit Heavy and Light routes")
        return {"enabled": enabled, "heavy": heavy, "light": light}

    def _read_native_snapshot(self, profile: str) -> effective_config.NativeFallbackSnapshot:
        """Read one profile's effective native keys and provenance through Hermes helpers."""
        return effective_config.read_native_fallback(self._profile_home(profile))

    def _native_actual(
        self, profile: str, snapshot: effective_config.NativeFallbackSnapshot | None = None,
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Return only safe provider/model pairs from one effective-config snapshot."""
        if snapshot is None:
            snapshot = self._read_native_snapshot(profile)
        warnings = list(snapshot.warnings)
        if not snapshot.effective_available:
            warnings.append("native_fallback_unavailable")
            return [], list(dict.fromkeys(warnings))
        if any(
            key == target or key.startswith(target + ".") or target.startswith(key + ".")
            for key in snapshot.managed_keys
            for target in ("fallback_providers", "fallback_model")
        ):
            warnings.append("native_fallback_managed_overlay")
        providers = snapshot.effective("fallback_providers")
        legacy = snapshot.effective("fallback_model")

        def source_entries(value: Any, *, legacy_source: bool) -> list[Any] | None:
            if value in (None, [], {}):
                return []
            if legacy_source and isinstance(value, dict):
                return [value]
            if isinstance(value, list):
                return value
            return None

        modern_entries = source_entries(providers, legacy_source=False)
        legacy_entries = source_entries(legacy, legacy_source=True)
        if modern_entries is None or legacy_entries is None:
            warnings.append("native_fallback_malformed")
            modern_entries = modern_entries or []
            legacy_entries = legacy_entries or []

        chain: list[dict[str, str]] = []
        identities: set[tuple[str, str, str]] = set()
        for item in [*modern_entries, *legacy_entries]:
            if not isinstance(item, dict):
                warnings.append("native_fallback_malformed")
                continue
            advanced = set(item) - {"provider", "model"}
            if advanced:
                warnings.append("native_fallback_advanced_entry")
            try:
                provider = _validate_token(item.get("provider"), field="fallback provider", pattern=PROVIDER_RE)
                model = _validate_token(item.get("model"), field="fallback model", pattern=MODEL_RE)
            except ValueError:
                warnings.append("native_fallback_malformed")
                continue
            base_url = item.get("base_url")
            hidden_endpoint = base_url.casefold().rstrip("/") if isinstance(base_url, str) else ""
            identity = (provider.casefold(), model.casefold(), hidden_endpoint)
            if identity in identities:
                continue
            identities.add(identity)
            chain.append({"provider": provider, "model": model})
        if len(chain) > 5:
            warnings.append("native_fallback_chain_too_long")
        return chain, list(dict.fromkeys(warnings))

    def _native_status(
        self,
        profile: str,
        entry: dict[str, Any],
        snapshot: effective_config.NativeFallbackSnapshot | None = None,
    ) -> dict[str, Any]:
        managed_value = entry.get("native_fallback")
        managed = managed_value is not None
        try:
            snapshot = snapshot or self._read_native_snapshot(profile)
            actual_chain, warnings = self._native_actual(profile, snapshot)
        except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged, OSError):
            snapshot = None
            actual_chain, warnings = [], ["native_fallback_unavailable"]
        editable = not any(
            warning in {
                "native_fallback_unavailable",
                "native_effective_unavailable",
                "native_managed_provenance_unavailable",
                "native_managed_env_expression_readonly",
                "native_fallback_env_expression",
                "native_fallback_managed_overlay",
                "native_fallback_malformed",
                "native_fallback_advanced_entry",
                "native_fallback_chain_too_long",
            }
            for warning in warnings
        )
        unknown = snapshot is None or not snapshot.effective_available or (
            "native_fallback_malformed" in warnings and not actual_chain
        )
        if managed:
            chain = copy.deepcopy(managed_value["chain"])
            enabled = managed_value["enabled"]
            expected = chain if enabled else []
            drift = actual_chain != expected
        else:
            chain = copy.deepcopy(actual_chain)
            enabled = bool(actual_chain)
            drift = False
        if unknown:
            # Unknown effective state must not be rendered as OFF.
            enabled = None
            drift = True if managed else False
        consent = entry.get("fallback_consent", {}).get("native")
        if not managed or not fallback_policy.consent_matches(profile, "native", {"chain": chain}, consent):
            consent = None
        return {
            "managed": managed,
            "editable": editable,
            "enabled": enabled,
            "chain": chain,
            "actual_chain": actual_chain,
            "drift": drift,
            "warnings": warnings,
            "consent": copy.deepcopy(consent),
        }

    def _read_delegation_snapshot(self, profile: str) -> effective_config.NativeFallbackSnapshot:
        """Read only the effective delegation fallback key and its provenance."""
        return effective_config.read_key_scoped(
            self._profile_home(profile), (DELEGATION_FALLBACK_KEY,)
        )

    def _delegation_actual(
        self, snapshot: effective_config.NativeFallbackSnapshot,
    ) -> tuple[str | None, list[dict[str, str]], list[str]]:
        warnings = [
            warning.replace("scoped_fallback_", "delegation_fallback_").replace("scoped_", "delegation_fallback_")
            for warning in snapshot.warnings
        ]
        if not snapshot.effective_available:
            warnings.append("delegation_fallback_unavailable")
            return None, [], list(dict.fromkeys(warnings))
        if any(
            key == DELEGATION_FALLBACK_KEY
            or DELEGATION_FALLBACK_KEY.startswith(key + ".")
            or key.startswith(DELEGATION_FALLBACK_KEY + ".")
            for key in snapshot.managed_keys
        ):
            warnings.append("delegation_fallback_managed_overlay")
        value = snapshot.effective(DELEGATION_FALLBACK_KEY)
        if value is None:
            return "default", [], list(dict.fromkeys(warnings))
        if value == []:
            return "off", [], list(dict.fromkeys(warnings))
        if not isinstance(value, list):
            warnings.append("delegation_fallback_malformed")
            return None, [], list(dict.fromkeys(warnings))
        chain: list[dict[str, str]] = []
        malformed = False
        advanced = False
        for item in value:
            if not isinstance(item, dict):
                malformed = True
                continue
            if set(item) != {"provider", "model"}:
                advanced = True
            try:
                provider = _validate_token(item.get("provider"), field="delegation fallback provider", pattern=PROVIDER_RE)
                model = _validate_token(item.get("model"), field="delegation fallback model", pattern=MODEL_RE)
            except ValueError:
                malformed = True
                continue
            chain.append({"provider": provider, "model": model})
        if malformed:
            warnings.append("delegation_fallback_malformed")
        if advanced:
            warnings.append("delegation_fallback_advanced_entry")
        if len(value) > 5:
            warnings.append("delegation_fallback_chain_too_long")
        if not value:
            mode = "off"
        else:
            mode = None if malformed else "custom"
        return mode, chain, list(dict.fromkeys(warnings))

    def _delegation_status(
        self,
        profile: str,
        entry: dict[str, Any],
        snapshot: effective_config.NativeFallbackSnapshot | None = None,
    ) -> dict[str, Any]:
        managed_value = entry.get("delegation_fallback")
        managed = managed_value is not None
        try:
            snapshot = snapshot or self._read_delegation_snapshot(profile)
            actual_mode, actual_chain, warnings = self._delegation_actual(snapshot)
            actual_value = snapshot.effective(DELEGATION_FALLBACK_KEY) if snapshot.effective_available else None
        except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged, OSError):
            snapshot = None
            actual_mode, actual_chain = None, []
            actual_value = None
            warnings = ["delegation_fallback_unavailable"]
        # Any unresolved or future warning is read-only, never fail-open.
        editable = not warnings and actual_mode in {"default", "off", "custom"}
        if managed:
            mode = managed_value["mode"]
            chain = copy.deepcopy(managed_value["chain"])
            projected = None if mode == "default" else [] if mode == "off" else chain
            drift = snapshot is None or not snapshot.effective_available or actual_value != projected
        else:
            mode = actual_mode
            chain = copy.deepcopy(actual_chain)
            drift = False
        consent = entry.get("fallback_consent", {}).get("delegation")
        if not managed or not fallback_policy.consent_matches(profile, "delegation", managed_value, consent):
            consent = None
        return {
            "managed": managed,
            "editable": editable,
            "mode": mode,
            "chain": chain,
            "actual_mode": actual_mode,
            "actual_chain": actual_chain,
            "drift": drift,
            "warnings": warnings,
            "consent": copy.deepcopy(consent),
        }

    def _fallback_dto(self, profile: str, entry: dict[str, Any]) -> dict[str, Any]:
        native = self._native_status(profile, entry)
        delegation = self._delegation_status(profile, entry)
        routing_value = entry["routing"]["fallback"]
        consent = entry["fallback_consent"].get("routing")
        if not fallback_policy.consent_matches(profile, "routing", routing_value, consent):
            consent = None
        return {
            "native": native,
            "routing": {
                "enabled": routing_value["enabled"],
                "heavy": copy.deepcopy(routing_value["heavy"]),
                "light": copy.deepcopy(routing_value["light"]),
                "consent": copy.deepcopy(consent),
            },
            "delegation": delegation,
        }

    def _read_disabled(self, profile: str) -> list[str]:
        value = self._read_key(profile, "skills.disabled")
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(dict.fromkeys(value))
        if value in (None, ""):
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
                    return list(dict.fromkeys(parsed))
            except json.JSONDecodeError:
                pass
        raise ServiceError("skills.disabled is not a string list")

    def _skill_digest(self, profile: str) -> str:
        home = self._profile_home(profile)
        target = home / "skills" / SKILL_NAME / "SKILL.md"
        if target.exists() or target.is_symlink():
            if not _inside(target, home):
                raise ServiceError("compat skill path escapes profile home")
            try:
                return hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError as exc:
                raise ServiceError("compat skill cannot be inspected") from exc
        return "MISSING"

    def _ensure_compat_skill(self, profile: str) -> None:
        home = self._profile_home(profile).resolve(strict=False)
        target = self._profile_home(profile) / "skills" / SKILL_NAME / "SKILL.md"
        if target.exists():
            if not _inside(target, home):
                raise ServiceError("compat skill path escapes profile home")
            return
        if target.is_symlink():
            raise ServiceError("compat skill path is unsafe")
        source = COMPAT_SKILL_SOURCE
        if not source.is_file():
            raise ServiceError("bundled compatibility skill is unavailable")
        if not _inside(target.parent, home):
            raise ServiceError("compat skill path escapes profile home")
        _secure_dir(target.parent)
        payload = source.read_bytes()
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def _profile_digest_keys(self, profile: str, models: dict[str, dict[str, str]], routing_change: bool) -> dict[str, Any]:
        keys = {key for group in MODEL_KEYS.values() for key in group}
        if routing_change:
            keys.add("skills.disabled")
        values = {key: self._read_key(profile, key) for key in sorted(keys)}
        return values

    def _read_optional_key(self, profile: str, key: str) -> Any:
        try:
            return self._read_key(profile, key)
        except ServiceError:
            # Older Hermes schemas may not define these legacy override slots.
            return None

    def _backup_config(self, profile: str, stamp: str) -> None:
        config = self._profile_home(profile) / "config.yaml"
        if not config.is_file() or config.is_symlink() or not _inside(config, self._profile_home(profile)):
            raise ServiceError("profile config cannot be safely backed up")
        backup = self.root / "plugin-data" / "model-router" / "backups" / stamp / profile / "config.yaml"
        _secure_dir(backup.parent)
        payload = config.read_bytes()
        fd = os.open(str(backup), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def _store_apply(self, receipt: dict[str, Any]) -> None:
        _atomic_write(self.root / STATE_RELATIVE, _json_bytes(receipt))
        if getattr(self, "_config_workers", None) is not None:
            self._batch_receipt = receipt

    def _recent_apply(self) -> dict[str, Any] | None:
        value = _read_json(self.root / STATE_RELATIVE)
        return value if isinstance(value, dict) else None

    def initialize(self, routing_profiles: list[str], fallbacks: dict | None = None) -> dict[str, Any]:
        if not isinstance(routing_profiles, list):
            raise ValueError("routing_profiles must be a list")
        discovered = self._discover_profiles()
        selected = set()
        for name in routing_profiles:
            selected.add(self._require_profile(name, discovered))
        if len(selected) != len(routing_profiles):
            raise ValueError("routing_profiles contains duplicates")
        with _FileLock(self._lock_path):
            stored = self._load_store()
            entries: dict[str, Any] = dict(stored["profiles"]) if stored else {}
            for name in discovered:
                if name not in entries:
                    actual = self._actual_models(name)
                    entries[name] = {
                        "models": actual,
                        "routing": self._default_routing(name in selected, self._fallback_for(name, fallbacks)),
                        "native_fallback": None,
                        "delegation_fallback": None,
                        "fallback_consent": {"native": None, "routing": None, "delegation": None},
                    }
                else:
                    item = copy.deepcopy(entries[name])
                    item["routing"]["enabled"] = name in selected
                    if fallbacks is not None and item["routing"]["fallback"] == {"enabled": False, "heavy": None, "light": None}:
                        item["routing"]["fallback"] = self._fallback_for(name, fallbacks)
                    entries[name] = item
                self._check_distinct_routes(entries[name]["routing"], entries[name]["models"])
            changed = stored is None or entries != stored["profiles"]
            revision = (stored["revision"] if stored else 0) + (1 if changed else 0)
            data = {"schema": SCHEMA, "revision": revision, "profiles": entries}
            if changed:
                _atomic_write(self.store_path, _json_bytes(data))
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            applied: list[str] = []
            for name in discovered:
                want_enabled = name in selected
                try:
                    disabled = self._read_disabled(name)
                    currently_enabled = SKILL_NAME not in disabled
                    if currently_enabled != want_enabled:
                        updated = [item for item in disabled if item != SKILL_NAME]
                        if not want_enabled:
                            updated.append(SKILL_NAME)
                        self._backup_config(name, stamp)
                        self._write_key(name, "skills.disabled", updated)
                        if self._read_disabled(name) != updated:
                            raise ServiceError("skills.disabled readback mismatch")
                        applied.append(name)
                    if want_enabled:
                        self._ensure_compat_skill(name)
                except Exception as exc:
                    receipt = {"status": "partial", "revision": revision, "applied_profiles": applied, "finished_at": _now()}
                    self._store_apply(receipt)
                    if isinstance(exc, ServiceError):
                        raise
                    raise ServiceError("initialization partially applied") from exc
            if applied:
                self._store_apply({"status": "initialized", "revision": revision, "profiles": applied, "finished_at": _now()})
            return self.status()

    def status(self) -> dict[str, Any]:
        discovered = self._discover_profiles()
        stored = self._load_store()
        entries = stored["profiles"] if stored else {}
        result_profiles: list[dict[str, Any]] = []
        for name in discovered:
            entry = entries.get(name)
            try:
                actual = self._actual_models(name, tolerate=True)
            except ServiceError:
                actual = {}
            if entry is None:
                models = actual
                routing = self._default_routing(False)
                view_entry = {
                    "models": models,
                    "routing": routing,
                    "native_fallback": None,
                    "delegation_fallback": None,
                    "fallback_consent": {"native": None, "routing": None, "delegation": None},
                }
            else:
                models, routing = entry["models"], entry["routing"]
                view_entry = entry
            drift: list[str] = []
            if not actual:
                drift.append("actual_models_unavailable")
            else:
                for role in MODEL_ROLES:
                    if models.get(role) != actual.get(role):
                        drift.append(f"models.{role}")
            try:
                disabled = self._read_disabled(name)
                if (SKILL_NAME not in disabled) != bool(routing.get("enabled")):
                    drift.append("skills.disabled")
            except ServiceError:
                drift.append("skills.disabled_unavailable")
            result_profiles.append({
                "name": name,
                "models": models,
                "routing": routing,
                "actual_models": actual,
                "drift": drift,
                "fallbacks": self._fallback_dto(name, view_entry),
                "timeouts": {
                    **timeouts.timeout_status(
                        self._profile_home(name),
                        enforcement_available=self._timeout_enforcement_available(name),
                    ),
                    "split_routing_supported": self._timeout_role_enforcement_available(name),
                },
            })
        return {
            "revision": stored["revision"] if stored else 0,
            "current_profile": self.active_profile(),
            "profiles": result_profiles,
            "recent_apply": self._recent_apply(),
            "fallback_capabilities": dict(fallback_policy.CAPABILITIES),
        }

    def routing_config(self, profile: str) -> dict[str, Any]:
        profile = self._require_profile(profile)
        stored = self._load_store()
        entry = stored["profiles"].get(profile) if stored else None
        if entry is None:
            models = self._actual_models(profile)
            routing = self._default_routing(False)
            revision = stored["revision"] if stored else 0
        else:
            models, routing, revision = entry["models"], entry["routing"], stored["revision"]
        heavy = models["main"] if routing["heavy"]["follow"] == "main" else routing["heavy"]["custom"]
        light = models["delegation"] if routing["light"]["follow"] == "delegation" else routing["light"]["custom"]
        enabled = routing["enabled"] and SKILL_NAME not in self._read_disabled(profile)
        consent = entry.get("fallback_consent", {}).get("routing") if entry else None
        approved = routing["fallback"]["enabled"] and fallback_policy.consent_matches(
            profile, "routing", routing["fallback"], consent
        )
        limits = timeouts.read_timeouts(self._profile_home(profile))
        config = {
            "enabled": enabled,
            "heavy": dict(heavy),
            "light": dict(light),
            "fallback": dict(routing["fallback"]),
            "revision": revision,
            "light_timeout_seconds": timeouts.routed_seconds(limits, "light"),
            "heavy_timeout_seconds": timeouts.routed_seconds(limits, "heavy"),
            "delegate_timeout_seconds": limits["delegate_total_seconds"],
            "timeout_revision": limits["revision"],
            "fallback_policy": {
                "trigger": fallback_policy.ROUTING_TRIGGER,
                "max_retries": fallback_policy.ROUTING_MAX_RETRIES,
                "approved": approved,
            },
        }
        if limits["schema"] == 1:
            config["timeout_seconds"] = limits["routed_total_seconds"]
        return config

    def _fresh_profile_entry(self, profile: str, entries: dict[str, Any]) -> dict[str, Any]:
        if profile in entries:
            return copy.deepcopy(entries[profile])
        actual = self._actual_models(profile)
        return {
            "models": actual,
            "routing": self._default_routing(False),
            "native_fallback": None,
            "delegation_fallback": None,
            "fallback_consent": {"native": None, "routing": None, "delegation": None},
        }

    def _timeout_enforcement_available(self, profile: str) -> bool:
        home = self._profile_home(profile)
        package = home / "plugins/model-router/model_router"
        return all((package / name).is_file() and not (package / name).is_symlink()
                   and _inside(package / name, home)
                   for name in ("timeouts.py", "native_watchdog.py"))

    def _timeout_role_enforcement_available(self, profile: str) -> bool:
        """Trust only a safe installed routing module with a literal AST marker."""
        try:
            self._require_profile(profile)
        except (TypeError, ValueError):
            return False
        if not self._timeout_enforcement_available(profile):
            return False

        home = self._profile_home(profile)
        relative_parts = ("plugins", "model-router", "model_router", "routing.py")
        marker_path = home.joinpath(*relative_parts)
        if not _inside(marker_path, home):
            return False
        current = home
        try:
            home_info = current.lstat()
            if stat.S_ISLNK(home_info.st_mode) or getattr(current, "is_junction", lambda: False)():
                return False
            for index, part in enumerate(relative_parts):
                current = current / part
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(current, "is_junction", lambda: False)():
                    return False
                is_file = index == len(relative_parts) - 1
                if is_file and not stat.S_ISREG(info.st_mode):
                    return False
                if not is_file and not stat.S_ISDIR(info.st_mode):
                    return False
            source = marker_path.read_text(encoding="utf-8")
            module = ast.parse(source, filename=str(marker_path))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            return False

        assignments: list[ast.expr | None] = []
        for node in module.body:
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "ROUTED_ROLE_TIMEOUTS_SUPPORTED"
                       for target in node.targets):
                    assignments.append(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "ROUTED_ROLE_TIMEOUTS_SUPPORTED":
                    assignments.append(node.value)
        return len(assignments) == 1 and isinstance(assignments[0], ast.Constant) and assignments[0].value is True

    def _prepare_timeout_updates(self, updates: Any, discovered: list[str]) -> list[dict[str, Any]]:
        if not isinstance(updates, list):
            raise ValueError("timeout_updates must be a list")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for update in updates:
            if not isinstance(update, dict) or not {"profile", "expected_revision"} <= set(update):
                raise ValueError("timeout update has unknown or missing fields")
            raw_values = {key: value for key, value in update.items() if key not in {"profile", "expected_revision"}}
            values = timeouts.validate_policy_values(raw_values)
            split_update = "routed_total_seconds" not in values
            profile = self._require_profile(update["profile"], discovered)
            if profile in seen:
                raise ValueError("timeout updates must target each profile only once")
            seen.add(profile)
            supported = (
                self._timeout_role_enforcement_available(profile)
                if split_update else self._timeout_enforcement_available(profile)
            )
            if not supported:
                raise ValueError("timeout enforcement is unavailable for this profile")
            revision = update["expected_revision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError("timeout expected_revision must be a nonnegative integer")
            home = self._profile_home(profile)
            digest = timeouts.timeout_digest(home)
            current = timeouts.read_timeouts(home)
            if digest != timeouts.timeout_digest(home) or revision != current["revision"]:
                raise RevisionConflict("timeout settings changed; reload before preview")
            if not split_update and current["schema"] == 2:
                raise ValueError("legacy timeout updates cannot target split settings")
            before_values = timeouts.policy_values(current, split=split_update)
            result.append({"profile": profile, "key": "model-router.timeouts", "before": digest,
                           "before_values": before_values, "expected_revision": revision,
                           "after": values, "write_required": values != before_values})
        return result

    def _check_timeout_write(self, item: dict[str, Any]) -> None:
        profile = self._require_profile(item["profile"])
        home = self._profile_home(profile)
        split_update = "routed_total_seconds" not in item.get("after", {})
        supported = (
            self._timeout_role_enforcement_available(profile)
            if split_update else self._timeout_enforcement_available(profile)
        )
        if not supported:
            raise RevisionConflict("timeout enforcement changed since preview")
        if timeouts.timeout_digest(home) != item["before"] or timeouts.read_timeouts(home)["revision"] != item["expected_revision"]:
            raise RevisionConflict("timeout settings changed since preview")

    def preview(self, body: dict) -> dict[str, Any]:
        required = {"expected_revision", "profile", "models", "model_targets", "routing", "routing_profiles"}
        optional = {"fallback_updates", "fallback_confirmations", "routing_targets", "timeout_updates", "save_scope"}
        if not isinstance(body, dict) or not required <= set(body) or set(body) - required - optional:
            raise ValueError("preview body has unknown or missing fields")
        scope = body.get("save_scope")
        if "save_scope" in body and (not isinstance(scope, str) or scope not in {"models", "routing", "timeouts"}):
            raise ValueError("save_scope must be models, routing, or timeouts")
        fallback_updates = body.get("fallback_updates", [])
        fallback_confirmations = body.get("fallback_confirmations", [])
        if not isinstance(fallback_updates, list) or not isinstance(fallback_confirmations, list):
            raise ValueError("fallback updates and confirmations must be lists")
        if fallback_confirmations and not fallback_updates:
            raise ValueError("fallback confirmations require explicit fallback updates")
        if scope is not None and (fallback_updates or fallback_confirmations):
            raise ValueError("fallback updates are outside the selected save scope")
        expected = body["expected_revision"]
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        discovered = self._discover_profiles()
        profile = self._require_profile(body["profile"], discovered)
        raw_timeout_updates = body.get("timeout_updates", [])
        if not isinstance(raw_timeout_updates, list):
            raise ValueError("timeout_updates must be a list")
        if scope in {"models", "routing"} and raw_timeout_updates:
            raise ValueError("timeout updates are outside the selected save scope")
        timeout_writes = (
            self._prepare_timeout_updates(raw_timeout_updates, discovered)
            if scope in {None, "timeouts"} else []
        )
        targets = body["model_targets"]
        selected = body["routing_profiles"]
        if not isinstance(targets, list) or not isinstance(selected, list):
            raise ValueError("model_targets and routing_profiles must be lists")
        targets = [self._require_profile(name, discovered) for name in targets]
        selected = [self._require_profile(name, discovered) for name in selected]
        raw_routing_targets = body.get("routing_targets", [profile])
        if not isinstance(raw_routing_targets, list):
            raise ValueError("routing_targets must be a list")
        routing_targets = [self._require_profile(name, discovered) for name in raw_routing_targets]
        if len(set(targets)) != len(targets) or len(set(selected)) != len(selected) or len(set(routing_targets)) != len(routing_targets):
            raise ValueError("profile lists must not contain duplicates")
        if scope in {"routing", "timeouts"} and targets:
            raise ValueError("model targets are outside the selected save scope")
        if scope in {"models", "timeouts"} and "routing_targets" in body and routing_targets:
            raise ValueError("routing targets are outside the selected save scope")
        submitted_models = _models(body["models"]) if scope in {None, "models"} else None
        if scope is None:
            submitted_routing = _routing(body["routing"])
        elif scope == "routing":
            routing_body = body["routing"]
            if not isinstance(routing_body, dict) or set(routing_body) != {"enabled", "heavy", "light", "fallback"}:
                raise ValueError("routing must define enabled, heavy, light, and fallback")
            # Fallback is a separate save scope. Validate only membership and
            # Heavy/Light declarations; the submitted fallback draft is inert.
            submitted_routing = _routing({
                "enabled": routing_body["enabled"],
                "heavy": routing_body["heavy"],
                "light": routing_body["light"],
                "fallback": {"enabled": False, "heavy": None, "light": None},
            })
        else:
            submitted_routing = None
        if submitted_routing is not None and submitted_routing["enabled"] != (profile in selected):
            raise ValueError("routing.enabled must match routing_profiles membership")

        stored = self._load_store()
        revision = stored["revision"] if stored else 0
        if expected != revision:
            raise RevisionConflict("settings revision changed; reload before preview")
        entries = dict(stored["profiles"]) if stored else {}
        if scope == "timeouts":
            # Timeout plans do not project or initialize canonical model/routing state.
            all_names = []
            after = copy.deepcopy(entries)
        elif scope == "models":
            # A model-section save may materialize a new canonical entry only
            # for profiles explicitly selected as model targets.
            all_names = []
            after = copy.deepcopy(entries)
            for name in targets:
                if name not in after:
                    after[name] = self._fresh_profile_entry(name, entries)
        else:
            all_names = sorted(set(discovered) | set(entries), key=lambda item: (item != "default", item))
            after = {name: self._fresh_profile_entry(name, entries) for name in all_names if name in discovered or name in entries}
        if scope is None and submitted_routing["fallback"] != after[profile]["routing"]["fallback"]:
            raise ValueError("routing.fallback can only be changed by fallback_preview")
        changes: list[dict[str, Any]] = []
        snapshots: dict[str, dict[str, Any]] = {}
        writes: list[dict[str, Any]] = []
        skill_snapshots: dict[str, str] = {}
        routing_validation_names: set[str] = set()
        if submitted_models is not None:
            for name in targets:
                entry = after[name]
                desired = submitted_models
                if entry["models"] != desired:
                    changes.append({"profile": name, "field": "settings.models", "before": entry["models"], "after": desired})
                actual = self._actual_models(name)
                profile_values = self._profile_digest_keys(name, desired, False)
                snapshots[name] = profile_values
                for role in MODEL_ROLES:
                    if actual[role] != desired[role] or (role != "main" and actual["main"] != desired["main"]):
                        changes.append({"profile": name, "field": f"models.{role}", "before": actual[role], "after": desired[role]})
                        role_writes = []
                        for key, value in zip(MODEL_KEYS[role], (desired[role]["provider"], desired[role]["model"], desired[role]["reasoning"])):
                            old = profile_values[key]
                            if old != value:
                                role_writes.append({"profile": name, "key": key, "before": old, "after": value})
                        if role in STALE_KEYS and actual[role]["provider"] != desired[role]["provider"]:
                            for key in STALE_KEYS[role]:
                                old = self._read_optional_key(name, key)
                                comparable = {"sha256": _digest(old)}
                                profile_values[key] = comparable
                                if old not in (None, ""):
                                    writes.append({"profile": name, "key": key, "before": comparable, "after": ""})
                                    changes.append({"profile": name, "field": key, "before": "[configured]", "after": ""})
                        writes.extend(role_writes)
                entry["models"] = desired
        selected_set = set(selected)
        routing_target_set = set(routing_targets)
        for name in all_names if scope in {None, "routing"} else []:
            if name not in after or name not in discovered:
                continue
            entry = after[name]
            old_enabled = bool(entry["routing"]["enabled"])
            new_enabled = name in selected_set
            if name in routing_target_set:
                routing_validation_names.add(name)
                new_routing = copy.deepcopy(entry["routing"])
                new_routing["heavy"] = copy.deepcopy(submitted_routing["heavy"])
                new_routing["light"] = copy.deepcopy(submitted_routing["light"])
                new_routing["enabled"] = new_enabled
                if entry["routing"] != new_routing:
                    changes.append({"profile": name, "field": "routing", "before": entry["routing"], "after": new_routing})
                entry["routing"] = new_routing
            elif old_enabled != new_enabled:
                routing_validation_names.add(name)
                entry["routing"] = dict(entry["routing"])
                entry["routing"]["enabled"] = new_enabled
                changes.append({"profile": name, "field": "routing.enabled", "before": old_enabled, "after": new_enabled})
            raw_disabled = self._read_key(name, "skills.disabled")
            disabled = self._read_disabled(name)
            if old_enabled != new_enabled or (SKILL_NAME not in disabled) != new_enabled:
                updated = [item for item in disabled if item != SKILL_NAME]
                if not new_enabled:
                    updated.append(SKILL_NAME)
                if scope == "routing":
                    profile_values = snapshots.setdefault(name, {"skills.disabled": raw_disabled})
                else:
                    profile_values = snapshots.setdefault(name, self._profile_digest_keys(name, entry["models"], True))
                # Normalize only the desired list, never the raw CAS baseline.
                # Missing/null/legacy JSON lists must match their stored form.
                profile_values["skills.disabled"] = raw_disabled
                if updated != disabled:
                    writes.append({"profile": name, "key": "skills.disabled", "before": raw_disabled, "after": updated})
                    changes.append({"profile": name, "field": "skills.disabled", "before": "enabled" if old_enabled else "disabled", "after": "enabled" if new_enabled else "disabled"})
            if new_enabled:
                digest = self._skill_digest(name)
                skill_snapshots[name] = digest
                if digest == "MISSING":
                    changes.append({"profile": name, "field": f"skills/{SKILL_NAME}/SKILL.md", "before": "missing", "after": "compatibility shim"})

        if scope in {None, "models", "routing"}:
            if scope is None:
                route_validation_names = set(after)
            elif scope == "models":
                route_validation_names = set(targets)
            else:
                route_validation_names = routing_validation_names
            for name in route_validation_names:
                entry = after.get(name)
                if entry is not None:
                    self._check_distinct_routes(entry["routing"], entry["models"])
            if not fallback_updates:
                self._check_changed_routing_fallbacks(entries, after)
        state_changed = scope != "timeouts" and after != entries
        plan_id = uuid.uuid4().hex
        expires_epoch = time.time() + self.PLAN_TTL
        expires_at = datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
        config_digests = {name: _digest(values) for name, values in snapshots.items()}
        plan = {
            "id": plan_id, "revision": revision, "after": after, "changes": changes,
            "snapshots": snapshots, "config_digests": config_digests, "writes": writes,
            "skill_snapshots": skill_snapshots, "model_targets": targets, "state_changed": state_changed, "expires_epoch": expires_epoch,
            "timeout_writes": timeout_writes,
            "save_scope": scope,
        }
        for item in timeout_writes:
            if item.get("write_required", True):
                changes.append({"profile": item["profile"], "field": "timeouts", "before": item["before_values"], "after": item["after"]})
            self._check_timeout_write(item)
        if fallback_updates:
            # Compose before publishing: one immutable token, revision and apply.
            # Never apply two independent previews in sequence.
            return self._prepare_fallback_preview({
                "expected_revision": expected,
                "updates": fallback_updates,
                "confirmations": fallback_confirmations,
            }, base_plan=plan)
        self._plans[plan_id] = plan
        plans_dir = self.store_path.parent / "plans"
        with _FileLock(self._lock_path):
            _secure_dir(plans_dir)
            for path in plans_dir.glob("*.json"):
                if path.is_symlink():
                    raise ServiceError("unsafe preview plan path")
                old = _read_json(path, default={})
                if old.get("expires_epoch", 0) < time.time():
                    path.unlink(missing_ok=True)
            if len(list(plans_dir.glob("*.json"))) >= self.PLAN_LIMIT:
                raise ServiceError("too many pending previews; wait for expiry")
            plan["owner_profile"] = self.active_profile()
            _atomic_write(plans_dir / (plan_id + ".json"), _json_bytes(plan))
        return {"plan_id": plan_id, "changes": json.loads(json.dumps(changes)), "warnings": [], "expires_at": expires_at}

    def fallback_preview(self, body: dict) -> dict[str, Any]:
        """Prepare a fallback-only update through the same combined-plan builder."""
        return self._prepare_fallback_preview(body)

    def _prepare_fallback_preview(self, body: dict, *, base_plan: dict | None = None) -> dict[str, Any]:
        """Prepare explicit scope updates, optionally on a pending model plan."""
        if not isinstance(body, dict) or set(body) != {"expected_revision", "updates", "confirmations"}:
            raise ValueError("fallback preview body has unknown or missing fields")
        expected = body["expected_revision"]
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        updates = body["updates"]
        confirmations = body["confirmations"]
        if not isinstance(updates, list) or not updates:
            raise ValueError("updates must be a non-empty list")
        if not isinstance(confirmations, list):
            raise ValueError("confirmations must be a list")

        discovered = self._discover_profiles()
        parsed_updates: list[tuple[str, dict[str, Any]]] = []
        seen_profiles: set[str] = set()
        for update in updates:
            if not isinstance(update, dict) or not set(update) <= {"profile", "native_fallback", "routing_fallback", "delegation_fallback"} or "profile" not in update:
                raise ValueError("each update must contain profile and known fallback scopes")
            if not (set(update) & {"native_fallback", "routing_fallback", "delegation_fallback"}):
                raise ValueError("each update must change at least one fallback scope")
            profile = self._require_profile(update["profile"], discovered)
            if profile in seen_profiles:
                raise ValueError("updates must not contain duplicate profiles")
            seen_profiles.add(profile)
            scopes: dict[str, Any] = {}
            if "native_fallback" in update:
                scopes["native"] = self._validate_native_fallback(update["native_fallback"])
                if scopes["native"] is None:
                    raise ValueError("native_fallback must define enabled and chain")
                if scopes["native"]["enabled"] and not scopes["native"]["chain"]:
                    raise ValueError("enabled native fallback requires at least one chain entry")
            if "routing_fallback" in update:
                raw = update["routing_fallback"]
                if not isinstance(raw, dict) or set(raw) != {"enabled", "heavy", "light"} or not isinstance(raw["enabled"], bool):
                    raise ValueError("routing_fallback must define enabled, heavy, and light")
                heavy = None if raw["heavy"] is None else _route(raw["heavy"])
                light = None if raw["light"] is None else _route(raw["light"])
                if raw["enabled"] and (heavy is None or light is None):
                    raise ValueError("enabled routing fallback requires Heavy and Light routes")
                scopes["routing"] = {"enabled": raw["enabled"], "heavy": heavy, "light": light}
            if "delegation_fallback" in update:
                scopes["delegation"] = self._validate_delegation_fallback(update["delegation_fallback"])
                if scopes["delegation"] is None:
                    raise ValueError("delegation_fallback must define mode and chain")
            parsed_updates.append((profile, scopes))

        confirmation_map: dict[tuple[str, str], dict[str, bool]] = {}
        for item in confirmations:
            if not isinstance(item, dict) or set(item) != {"profile", "scope", "allow_additional_cost", "allow_task_rerun"}:
                raise ValueError("each confirmation must define profile, scope, cost, and rerun flags")
            profile = self._require_profile(item["profile"], discovered)
            scope = item["scope"]
            if scope not in {"native", "routing", "delegation"}:
                raise ValueError("confirmation scope must be native, routing, or delegation")
            pair = (profile, scope)
            if pair in confirmation_map:
                raise ValueError("confirmations must not contain duplicate profile scopes")
            if not isinstance(item["allow_additional_cost"], bool) or not isinstance(item["allow_task_rerun"], bool):
                raise ValueError("confirmation flags must be boolean")
            confirmation_map[pair] = {
                "allow_additional_cost": item["allow_additional_cost"],
                "allow_task_rerun": item["allow_task_rerun"],
            }

        allowed_pairs = {(profile, scope) for profile, scopes in parsed_updates for scope in scopes}
        if set(confirmation_map) - allowed_pairs:
            raise ValueError("confirmation is not bound to an updated profile scope")
        for (profile, scope), confirmation in confirmation_map.items():
            if confirmation["allow_additional_cost"] is not True:
                raise ValueError("fallback confirmation must allow additional cost")
            expected_rerun = scope == "routing"
            if confirmation["allow_task_rerun"] is not expected_rerun:
                raise ValueError("fallback confirmation retry flag does not match its fixed execution path")

        stored = self._load_store()
        revision = stored["revision"] if stored else 0
        if expected != revision:
            raise RevisionConflict("settings revision changed; reload before fallback preview")
        entries = copy.deepcopy(stored["profiles"]) if stored else {}
        if base_plan is not None and base_plan["revision"] != revision:
            raise RevisionConflict("settings revision changed during combined preview")
        all_names = sorted(set(discovered) | set(entries), key=lambda item: (item != "default", item))
        after = (copy.deepcopy(base_plan["after"]) if base_plan is not None else
                 {name: self._fresh_profile_entry(name, entries) for name in all_names if name in discovered or name in entries})
        changes: list[dict[str, Any]] = copy.deepcopy(base_plan["changes"]) if base_plan else []
        snapshots: dict[str, dict[str, Any]] = copy.deepcopy(base_plan["snapshots"]) if base_plan else {}
        writes: list[dict[str, Any]] = copy.deepcopy(base_plan["writes"]) if base_plan else []
        native_expected: dict[str, list[dict[str, str]]] = {}
        native_snapshots: dict[str, str] = {}
        native_provenance: dict[str, str] = {}
        delegation_expected: dict[str, Any] = {}
        delegation_snapshots: dict[str, str] = {}
        delegation_provenance: dict[str, str] = {}

        def raw_pair_view(raw: Any, *, legacy: bool) -> list[dict[str, str]]:
            if raw in (None, [], {}):
                return []
            if legacy and isinstance(raw, dict):
                values = [raw]
            elif isinstance(raw, list):
                values = raw
            else:
                return []
            return [
                {"provider": item["provider"], "model": item["model"]}
                for item in values
                if isinstance(item, dict) and set(item) == {"provider", "model"}
                and isinstance(item.get("provider"), str) and isinstance(item.get("model"), str)
            ]

        for profile, scopes in parsed_updates:
            entry = after[profile]
            for scope, desired in scopes.items():
                consent_key = scope
                old_consent = entry["fallback_consent"][consent_key]
                confirmation = confirmation_map.get((profile, scope))
                if scope == "native":
                    try:
                        native_snapshot = self._read_native_snapshot(profile)
                    except effective_config.EffectiveConfigChanged as exc:
                        raise RevisionConflict("native config changed during preview") from exc
                    except effective_config.EffectiveConfigUnavailable as exc:
                        raise ValueError("native fallback is read-only because effective config cannot be verified") from exc
                    current_status = self._native_status(profile, entry, native_snapshot)
                    if not current_status["editable"] or current_status["enabled"] is None:
                        raise ValueError("native fallback is read-only for this profile")
                    primary = entry["models"]["main"]
                    if desired["enabled"] and any(
                        (item["provider"].casefold(), item["model"].casefold())
                        == (primary["provider"].casefold(), primary["model"].casefold())
                        for item in desired["chain"]
                    ):
                        raise ValueError("native fallback must differ from the primary model")
                    old_managed = entry["native_fallback"]
                    already_approved = (
                        old_managed is not None
                        and fallback_policy.consent_matches(profile, scope, desired, old_consent)
                    )
                    needs_consent = desired["enabled"] and not already_approved
                    if needs_consent and confirmation is None:
                        raise ValueError("native fallback requires explicit additional-cost confirmation")
                    new_consent = (
                        fallback_policy.make_consent(profile, scope, desired, source="explicit")
                        if confirmation is not None
                        else old_consent if fallback_policy.consent_matches(profile, scope, desired, old_consent)
                        else None
                    )
                    before_native = {
                        "managed": old_managed is not None,
                        "enabled": current_status["enabled"],
                        "chain": current_status["chain"],
                    }
                    if old_managed != desired:
                        changes.append({"profile": profile, "field": "native_fallback", "before": before_native, "after": desired})
                    entry["native_fallback"] = desired
                    entry["fallback_consent"]["native"] = new_consent

                    raw_providers = native_snapshot.raw("fallback_providers")
                    raw_legacy = native_snapshot.raw("fallback_model")
                    projected = copy.deepcopy(desired["chain"]) if desired["enabled"] else []
                    target_providers = projected
                    target_legacy: list[Any] = []
                    native_expected[profile] = projected
                    native_snapshots[profile] = native_snapshot.cas_digest
                    native_provenance[profile] = native_snapshot.provenance_digest
                    profile_snapshot = snapshots.setdefault(profile, {})
                    for key, raw in (("fallback_providers", raw_providers), ("fallback_model", raw_legacy)):
                        profile_snapshot[key] = {"sha256": _digest(raw)}
                    for key, raw, target, legacy_source in (
                        ("fallback_model", raw_legacy, target_legacy, True),
                        ("fallback_providers", raw_providers, target_providers, False),
                    ):
                        if raw != target:
                            writes.append({"profile": profile, "key": key, "before": {"sha256": _digest(raw)}, "after": target})
                            changes.append({
                                "profile": profile,
                                "field": key,
                                "before": raw_pair_view(raw, legacy=legacy_source),
                                "after": target,
                            })
                elif scope == "routing":
                    old_fallback = entry["routing"]["fallback"]
                    heavy_primary = entry["models"]["main"] if entry["routing"]["heavy"]["follow"] == "main" else entry["routing"]["heavy"]["custom"]
                    light_primary = entry["models"]["delegation"] if entry["routing"]["light"]["follow"] == "delegation" else entry["routing"]["light"]["custom"]
                    if desired["enabled"]:
                        heavy_id = (desired["heavy"]["provider"].casefold(), desired["heavy"]["model"].casefold())
                        light_id = (desired["light"]["provider"].casefold(), desired["light"]["model"].casefold())
                        if heavy_id == light_id:
                            raise ValueError("enabled Heavy and Light fallbacks must be distinct")
                        if heavy_id == (heavy_primary["provider"].casefold(), heavy_primary["model"].casefold()) or light_id == (light_primary["provider"].casefold(), light_primary["model"].casefold()):
                            raise ValueError("fallback route must differ from its primary route")
                    already_approved = fallback_policy.consent_matches(profile, scope, desired, old_consent)
                    needs_consent = desired["enabled"] and not already_approved
                    if needs_consent and confirmation is None:
                        raise ValueError("routing fallback requires cost and fresh-task rerun confirmation")
                    new_consent = (
                        fallback_policy.make_consent(profile, scope, desired, source="explicit")
                        if confirmation is not None
                        else old_consent if fallback_policy.consent_matches(profile, scope, desired, old_consent)
                        else None
                    )
                    if old_fallback != desired:
                        changes.append({"profile": profile, "field": "routing.fallback", "before": old_fallback, "after": desired})
                    entry["routing"]["fallback"] = desired
                    entry["fallback_consent"]["routing"] = new_consent
                elif scope == "delegation":
                    try:
                        delegated_snapshot = self._read_delegation_snapshot(profile)
                    except effective_config.EffectiveConfigChanged as exc:
                        raise RevisionConflict("delegation config changed during preview") from exc
                    except effective_config.EffectiveConfigUnavailable as exc:
                        raise ValueError("delegation fallback is read-only because effective config cannot be verified") from exc
                    current_status = self._delegation_status(profile, entry, delegated_snapshot)
                    if not current_status["editable"] or current_status["actual_mode"] is None:
                        raise ValueError("delegation fallback is read-only for this profile")
                    old_managed = entry.get("delegation_fallback")
                    approved = old_managed is not None and fallback_policy.consent_matches(profile, scope, desired, old_consent)
                    if desired["mode"] != "off" and not approved and confirmation is None:
                        raise ValueError("delegation fallback requires explicit additional-cost confirmation")
                    new_consent = (
                        fallback_policy.make_consent(profile, scope, desired, source="explicit")
                        if confirmation is not None else old_consent if approved else None
                    )
                    if old_managed != desired:
                        changes.append({"profile": profile, "field": "delegation_fallback",
                                        "before": {"managed": old_managed is not None, "mode": current_status["mode"], "chain": current_status["chain"]},
                                        "after": desired})
                    entry["delegation_fallback"] = desired
                    entry["fallback_consent"]["delegation"] = new_consent
                    raw = delegated_snapshot.raw(DELEGATION_FALLBACK_KEY)
                    projected = None if desired["mode"] == "default" else copy.deepcopy(desired["chain"]) if desired["mode"] == "custom" else []
                    delegation_expected[profile] = projected
                    delegation_snapshots[profile] = delegated_snapshot.cas_digest
                    delegation_provenance[profile] = delegated_snapshot.provenance_digest
                    snapshots.setdefault(profile, {})[DELEGATION_FALLBACK_KEY] = {"sha256": _digest(raw)}
                    if raw != projected:
                        writes.append({"profile": profile, "key": DELEGATION_FALLBACK_KEY,
                                       "before": {"sha256": _digest(raw)}, "after": projected})
                        changes.append({"profile": profile, "field": DELEGATION_FALLBACK_KEY,
                                        "before": raw, "after": projected})
                old_source = old_consent.get("source") if isinstance(old_consent, dict) else None
                new_source = new_consent.get("source") if isinstance(new_consent, dict) else None
                if old_source != new_source:
                    changes.append({
                        "profile": profile,
                        "field": f"fallback_consent.{scope}",
                        "before": old_source,
                        "after": new_source,
                    })

        for name, entry in after.items():
            self._check_distinct_routes(entry["routing"], entry["models"])
        self._check_changed_routing_fallbacks(entries, after)
        state_changed = after != entries
        plan_id = uuid.uuid4().hex
        expires_epoch = time.time() + self.PLAN_TTL
        expires_at = datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
        config_digests = {name: _digest(values) for name, values in snapshots.items()}
        plan = {
            "kind": "fallback",
            "id": plan_id,
            "revision": revision,
            "after": after,
            "changes": changes,
            "snapshots": snapshots,
            "config_digests": config_digests,
            "writes": writes,
            "skill_snapshots": copy.deepcopy(base_plan["skill_snapshots"]) if base_plan else {},
            "model_targets": list(base_plan["model_targets"]) if base_plan else [],
            "native_expected": native_expected,
            "native_snapshots": native_snapshots,
            "native_provenance": native_provenance,
            "delegation_expected": delegation_expected,
            "delegation_snapshots": delegation_snapshots,
            "delegation_provenance": delegation_provenance,
            "state_changed": state_changed,
            "expires_epoch": expires_epoch,
            "timeout_writes": copy.deepcopy(base_plan.get("timeout_writes", [])) if base_plan else [],
        }
        # Eligibility, sanitized preview and before hashes all came from the
        # same immutable snapshot. Reject an intervening edit instead of
        # adopting it as the CAS baseline.
        for profile, expected_snapshot in native_snapshots.items():
            try:
                current_snapshot = self._read_native_snapshot(profile)
            except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                raise RevisionConflict("native config changed during preview") from exc
            if current_snapshot.cas_digest != expected_snapshot:
                raise RevisionConflict("native config changed during preview")
        for profile, expected_snapshot in delegation_snapshots.items():
            try:
                current_snapshot = self._read_delegation_snapshot(profile)
            except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                raise RevisionConflict("delegation config changed during preview") from exc
            if current_snapshot.cas_digest != expected_snapshot:
                raise RevisionConflict("delegation config changed during preview")
        for item in plan["timeout_writes"]:
            self._check_timeout_write(item)
        self._plans[plan_id] = plan
        plans_dir = self.store_path.parent / "plans"
        with _FileLock(self._lock_path):
            _secure_dir(plans_dir)
            for path in plans_dir.glob("*.json"):
                if path.is_symlink():
                    raise ServiceError("unsafe preview plan path")
                old = _read_json(path, default={})
                if old.get("expires_epoch", 0) < time.time():
                    path.unlink(missing_ok=True)
            if len(list(plans_dir.glob("*.json"))) >= self.PLAN_LIMIT:
                raise ServiceError("too many pending previews; wait for expiry")
            plan["owner_profile"] = self.active_profile()
            _atomic_write(plans_dir / (plan_id + ".json"), _json_bytes(plan))
        return {"plan_id": plan_id, "changes": json.loads(json.dumps(changes)), "warnings": [], "expires_at": expires_at}

    def _actual_key_matches(self, profile: str, key: str, expected: Any) -> bool:
        observed = self._read_key(profile, key)
        if isinstance(expected, dict) and set(expected) == {"sha256"}:
            return _digest(observed) == expected["sha256"]
        return observed == expected

    def apply(self, plan_id: str) -> dict[str, Any]:
        if not isinstance(plan_id, str) or re.fullmatch(r"[0-9a-f]{32}", plan_id) is None:
            raise ValueError("valid plan_id is required")
        with _FileLock(self._lock_path), self._batch_writes():
            plan_path = self.store_path.parent / "plans" / (plan_id + ".json")
            if plan_path.is_symlink() or not _inside(plan_path, self.store_path.parent):
                raise ServiceError("unsafe preview plan path")
            plan = _read_json(plan_path)
            if plan is None:
                raise ServiceError("preview plan is unknown or already consumed")
            if plan.get("owner_profile") != self.active_profile():
                raise ServiceError("preview belongs to another profile connection")
            plan_path.unlink()  # one-shot under the same lock, before any write
            self._plans.pop(plan_id, None)
            if time.time() > plan["expires_epoch"]:
                raise ServiceError("preview plan expired")
            current = self._load_store()
            revision = current["revision"] if current else 0
            if revision != plan["revision"]:
                raise RevisionConflict("settings revision changed; preview again")
            for item in plan.get("timeout_writes", []):
                self._check_timeout_write(item)
            for profile in set(plan["snapshots"]) | set(plan["skill_snapshots"]):
                self._require_profile(profile)
            # Validate all captured config values before creating backups or writing.
            for profile, values in plan["snapshots"].items():
                current_values = {key: ({"sha256": _digest(self._read_key(profile, key))} if isinstance(expected, dict) and set(expected) == {"sha256"} else self._read_key(profile, key)) for key, expected in values.items()}
                if current_values != values or _digest(current_values) != plan["config_digests"][profile]:
                    raise RevisionConflict("profile config changed since preview; reload before apply")
            for profile, expected_snapshot in plan.get("native_snapshots", {}).items():
                try:
                    current_snapshot = self._read_native_snapshot(profile)
                except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                    raise RevisionConflict("native config changed since preview; reload before apply") from exc
                if current_snapshot.cas_digest != expected_snapshot:
                    raise RevisionConflict("native config changed since preview; reload before apply")
            for profile, expected_snapshot in plan.get("delegation_snapshots", {}).items():
                try:
                    current_snapshot = self._read_delegation_snapshot(profile)
                except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                    raise RevisionConflict("delegation config changed since preview") from exc
                if current_snapshot.cas_digest != expected_snapshot:
                    raise RevisionConflict("delegation config changed since preview")
            for profile, expected in plan["skill_snapshots"].items():
                if self._skill_digest(profile) != expected:
                    raise RevisionConflict("profile skill state changed since preview")
            if not plan["changes"]:
                for item in plan.get("timeout_writes", []):
                    self._check_timeout_write(item)
                receipt = {"status": "no_change", "plan_id": plan_id, "revision": revision, "applied": [], "remaining": [], "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            new_revision = revision + 1 if plan["state_changed"] else revision
            next_store = {"schema": SCHEMA, "revision": new_revision, "profiles": plan["after"]}
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            profiles_to_backup = sorted({item["profile"] for item in plan["writes"]})
            timeout_writes = [item for item in plan.get("timeout_writes", []) if item.get("write_required", True)]
            all_writes = list(plan["writes"]) + timeout_writes
            try:
                for profile in profiles_to_backup:
                    self._backup_config(profile, stamp)
            except Exception:
                receipt = {"status": "partial", "plan_id": plan_id, "revision": revision, "applied": [],
                           "remaining": [{"profile": item["profile"], "key": item["key"]} for item in all_writes],
                           "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            if plan["state_changed"]:
                _atomic_write(self.store_path, _json_bytes(next_store))
            applied: list[dict[str, str]] = []
            pending = list(all_writes)
            try:
                for item in all_writes:
                    profile, key, before, after = item["profile"], item["key"], item["before"], item["after"]
                    if key == "model-router.timeouts":
                        self._check_timeout_write(item)
                        timeouts.write_timeouts(self._profile_home(profile), after,
                                                expected_digest=before, expected_revision=item["expected_revision"])
                        applied.append({"profile": profile, "key": key})
                        pending.pop(0)
                        continue
                    if profile in plan.get("native_provenance", {}):
                        try:
                            current_snapshot = self._read_native_snapshot(profile)
                        except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                            raise RevisionConflict("native managed provenance changed during apply") from exc
                        if current_snapshot.provenance_digest != plan["native_provenance"][profile]:
                            raise RevisionConflict("native managed provenance changed during apply")
                    if profile in plan.get("delegation_provenance", {}):
                        current_snapshot = self._read_delegation_snapshot(profile)
                        if current_snapshot.provenance_digest != plan["delegation_provenance"][profile]:
                            raise RevisionConflict("delegation managed provenance changed during apply")
                    if not self._actual_key_matches(profile, key, before):
                        raise RevisionConflict("profile config changed during apply")
                    self._write_key(profile, key, after)
                    if not self._actual_key_matches(profile, key, after):
                        raise ServiceError("config readback mismatch")
                    applied.append({"profile": profile, "key": key})
                    pending.pop(0)
                for item in plan["writes"]:
                    if not self._actual_key_matches(item["profile"], item["key"], item["after"]):
                        raise RevisionConflict("profile changed before final readback")
                # Every explicit target is part of the approved final state,
                # including NOOP targets which were not physically written.
                for item in plan.get("timeout_writes", []):
                    if not item.get("write_required", True):
                        self._check_timeout_write(item)
                        continue
                    if set(item["after"]) == timeouts._SPLIT_TIMEOUT_FIELDS and not self._timeout_role_enforcement_available(item["profile"]):
                        raise RevisionConflict("role timeout enforcement changed before final readback")
                    observed = timeouts.read_timeouts(self._profile_home(item["profile"]))
                    if observed["revision"] != item["expected_revision"] + 1 or any(observed[key] != value for key, value in item["after"].items()):
                        raise RevisionConflict("timeout settings differ from approved selection")
                for profile in plan.get("model_targets", []):
                    if self._actual_models(profile) != next_store["profiles"][profile]["models"]:
                        raise RevisionConflict("resolved roles differ from approved desired models")
                for profile, expected_chain in plan.get("native_expected", {}).items():
                    actual_chain, warnings = self._native_actual(profile)
                    if warnings or actual_chain != expected_chain:
                        raise RevisionConflict("effective native fallback chain differs from approved selection")
                for profile, expected_value in plan.get("delegation_expected", {}).items():
                    current_snapshot = self._read_delegation_snapshot(profile)
                    _mode, _chain, warnings = self._delegation_actual(current_snapshot)
                    if warnings or current_snapshot.effective(DELEGATION_FALLBACK_KEY) != expected_value:
                        raise RevisionConflict("effective delegation fallback differs from approved selection")
                for profile in plan["skill_snapshots"]:
                    if next_store["profiles"].get(profile, {}).get("routing", {}).get("enabled"):
                        self._ensure_compat_skill(profile)
            except Exception:
                receipt = {"status": "partial", "plan_id": plan_id, "revision": new_revision, "applied": applied,
                           "remaining": [{"profile": item["profile"], "key": item["key"]} for item in pending], "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            receipt = {"status": "applied", "plan_id": plan_id, "revision": new_revision, "applied": applied,
                       "remaining": [], "finished_at": _now()}
            self._store_apply(receipt)
            return receipt
