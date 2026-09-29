"""Profile-scoped canonical settings and safe Hermes CLI projection."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
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
        if not isinstance(data, dict) or set(data) != {"schema", "revision", "profiles"} or data.get("schema") != SCHEMA:
            raise ServiceError("settings schema is invalid")
        if not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool) or data["revision"] < 0:
            raise ServiceError("settings revision is invalid")
        if not isinstance(data.get("profiles"), dict):
            raise ServiceError("settings profiles are invalid")
        for name, entry in data["profiles"].items():
            if PROFILE_RE.fullmatch(name) is None or not isinstance(entry, dict) or set(entry) != {"models", "routing"}:
                raise ServiceError("settings profile entry is invalid")
            _models(entry["models"], allow_empty_model=True)
            _routing(entry["routing"])
        return data

    def _cli_path(self) -> str:
        stable = self.root / "bin" / ("hermes.exe" if os.name == "nt" else "hermes")
        path = str(stable) if stable.is_file() else shutil.which("hermes")
        if not path:
            raise ServiceError("Hermes CLI launcher was not found")
        candidate = Path(path).expanduser().resolve(strict=True)
        if not candidate.is_file():
            raise ServiceError("Hermes CLI launcher is unavailable")
        return str(candidate)

    def _env(self, profile: str) -> dict[str, str]:
        env = dict(os.environ)
        env["HERMES_HOME"] = str(self._profile_home(profile))
        for key in ("HERMES_PROFILE", "HERMES_SESSION_ID", "HERMES_PARENT_SESSION_ID", "HERMES_CHILD_SESSION_SOURCE"):
            env.pop(key, None)
        return env

    def _command(self, profile: str, *args: str) -> list[str]:
        command = [self._cli_path(), "--profile", profile]
        command.extend(args)
        return command

    def _read_key(self, profile: str, key: str) -> Any:
        # Reads are local and narrowly selected; launching 143 CLI processes per
        # UI refresh was both slow and unnecessary. Writes still use Hermes CLI.
        import yaml
        self._require_profile(profile)
        try:
            value = yaml.safe_load((self._profile_home(profile) / "config.yaml").read_text(encoding="utf-8")) or {}
            for part in key.split("."):
                if not isinstance(value, dict):
                    return None
                value = value.get(part)
            return value
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ServiceError(f"could not read config key {key}") from exc

    def _write_key(self, profile: str, key: str, value: Any) -> None:
        if self.writer is not None:
            self.writer(profile, key, value)
            return
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        try:
            result = subprocess.run(
                self._command(profile, "config", "set", key, rendered, "--force"),
                env=self._env(profile), shell=False, capture_output=True, text=True, timeout=15, check=False,
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
                    entries[name] = {"models": actual, "routing": self._default_routing(name in selected, self._fallback_for(name, fallbacks))}
                else:
                    item = entries[name]
                    item = {"models": item["models"], "routing": dict(item["routing"])}
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
            else:
                models, routing = entry["models"], entry["routing"]
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
            result_profiles.append({"name": name, "models": models, "routing": routing, "actual_models": actual, "drift": drift})
        return {
            "revision": stored["revision"] if stored else 0,
            "current_profile": self.active_profile(),
            "profiles": result_profiles,
            "recent_apply": self._recent_apply(),
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
        return {"enabled": enabled, "heavy": dict(heavy), "light": dict(light), "fallback": dict(routing["fallback"]), "revision": revision}

    def _fresh_profile_entry(self, profile: str, entries: dict[str, Any]) -> dict[str, Any]:
        if profile in entries:
            return {"models": entries[profile]["models"], "routing": entries[profile]["routing"]}
        actual = self._actual_models(profile)
        return {"models": actual, "routing": self._default_routing(False)}

    def preview(self, body: dict) -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) != {"expected_revision", "profile", "models", "model_targets", "routing", "routing_profiles"}:
            raise ValueError("preview body has unknown or missing fields")
        expected = body["expected_revision"]
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        discovered = self._discover_profiles()
        profile = self._require_profile(body["profile"], discovered)
        targets = body["model_targets"]
        selected = body["routing_profiles"]
        if not isinstance(targets, list) or not isinstance(selected, list):
            raise ValueError("model_targets and routing_profiles must be lists")
        targets = [self._require_profile(name, discovered) for name in targets]
        selected = [self._require_profile(name, discovered) for name in selected]
        if len(set(targets)) != len(targets) or len(set(selected)) != len(selected):
            raise ValueError("profile lists must not contain duplicates")
        submitted_models = _models(body["models"])
        submitted_routing = _routing(body["routing"])
        if submitted_routing["enabled"] != (profile in selected):
            raise ValueError("routing.enabled must match routing_profiles membership")

        stored = self._load_store()
        revision = stored["revision"] if stored else 0
        if expected != revision:
            raise RevisionConflict("settings revision changed; reload before preview")
        entries = dict(stored["profiles"]) if stored else {}
        all_names = sorted(set(discovered) | set(entries), key=lambda item: (item != "default", item))
        after = {name: self._fresh_profile_entry(name, entries) for name in all_names if name in discovered or name in entries}
        changes: list[dict[str, Any]] = []
        snapshots: dict[str, dict[str, Any]] = {}
        writes: list[dict[str, Any]] = []
        skill_snapshots: dict[str, str] = {}
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
        for name in all_names:
            if name not in after or name not in discovered:
                continue
            entry = after[name]
            old_enabled = bool(entry["routing"]["enabled"])
            new_enabled = name in selected_set
            if name == profile:
                new_routing = dict(submitted_routing)
                new_routing["enabled"] = new_enabled
                if entry["routing"] != new_routing:
                    changes.append({"profile": name, "field": "routing", "before": entry["routing"], "after": new_routing})
                entry["routing"] = new_routing
            elif old_enabled != new_enabled:
                entry["routing"] = dict(entry["routing"])
                entry["routing"]["enabled"] = new_enabled
                changes.append({"profile": name, "field": "routing.enabled", "before": old_enabled, "after": new_enabled})
            disabled = self._read_disabled(name)
            if old_enabled != new_enabled or (SKILL_NAME not in disabled) != new_enabled:
                updated = [item for item in disabled if item != SKILL_NAME]
                if not new_enabled:
                    updated.append(SKILL_NAME)
                profile_values = snapshots.setdefault(name, self._profile_digest_keys(name, entry["models"], True))
                profile_values["skills.disabled"] = disabled
                if updated != disabled:
                    writes.append({"profile": name, "key": "skills.disabled", "before": disabled, "after": updated})
                    changes.append({"profile": name, "field": "skills.disabled", "before": "enabled" if old_enabled else "disabled", "after": "enabled" if new_enabled else "disabled"})
            if new_enabled:
                digest = self._skill_digest(name)
                skill_snapshots[name] = digest
                if digest == "MISSING":
                    changes.append({"profile": name, "field": f"skills/{SKILL_NAME}/SKILL.md", "before": "missing", "after": "compatibility shim"})

        for name, entry in after.items():
            self._check_distinct_routes(entry["routing"], entry["models"])
        state_changed = after != entries
        plan_id = uuid.uuid4().hex
        expires_epoch = time.time() + self.PLAN_TTL
        expires_at = datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
        config_digests = {name: _digest(values) for name, values in snapshots.items()}
        plan = {
            "id": plan_id, "revision": revision, "after": after, "changes": changes,
            "snapshots": snapshots, "config_digests": config_digests, "writes": writes,
            "skill_snapshots": skill_snapshots, "model_targets": targets, "state_changed": state_changed, "expires_epoch": expires_epoch,
        }
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
        with _FileLock(self._lock_path):
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
            for profile in set(plan["snapshots"]) | set(plan["skill_snapshots"]):
                self._require_profile(profile)
            # Validate all captured config values before creating backups or writing.
            for profile, values in plan["snapshots"].items():
                current_values = {key: ({"sha256": _digest(self._read_key(profile, key))} if isinstance(expected, dict) and set(expected) == {"sha256"} else self._read_key(profile, key)) for key, expected in values.items()}
                if current_values != values or _digest(current_values) != plan["config_digests"][profile]:
                    raise RevisionConflict("profile config changed since preview; reload before apply")
            for profile, expected in plan["skill_snapshots"].items():
                if self._skill_digest(profile) != expected:
                    raise RevisionConflict("profile skill state changed since preview")
            if not plan["changes"]:
                receipt = {"status": "no_change", "plan_id": plan_id, "revision": revision, "applied": [], "remaining": [], "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            new_revision = revision + 1 if plan["state_changed"] else revision
            next_store = {"schema": SCHEMA, "revision": new_revision, "profiles": plan["after"]}
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            profiles_to_backup = sorted({item["profile"] for item in plan["writes"]})
            try:
                for profile in profiles_to_backup:
                    self._backup_config(profile, stamp)
            except Exception:
                receipt = {"status": "partial", "plan_id": plan_id, "revision": revision, "applied": [],
                           "remaining": [{"profile": item["profile"], "key": item["key"]} for item in plan["writes"]],
                           "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            if plan["state_changed"]:
                _atomic_write(self.store_path, _json_bytes(next_store))
            applied: list[dict[str, str]] = []
            pending = list(plan["writes"])
            try:
                for item in plan["writes"]:
                    profile, key, before, after = item["profile"], item["key"], item["before"], item["after"]
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
                for profile in plan.get("model_targets", []):
                    if self._actual_models(profile) != next_store["profiles"][profile]["models"]:
                        raise RevisionConflict("resolved roles differ from approved desired models")
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
