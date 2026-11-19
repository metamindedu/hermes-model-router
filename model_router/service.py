"""Profile-scoped canonical settings and safe Hermes CLI projection."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import copy
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import effective_config, fallback_policy, installation, timeouts, native_service
from . import slots as slot_model

SCHEMA = 2
# One status read asks the same questions (which profiles exist, the source package identity) per
# row. While a read is active those answers are computed once; the scope ends with the read.
_READ_SCOPE: ContextVar[dict | None] = ContextVar("model_router_read_scope", default=None)


@contextmanager
def read_scope():
    if _READ_SCOPE.get() is not None:
        yield
        return
    token = _READ_SCOPE.set({})
    try:
        yield
    finally:
        _READ_SCOPE.reset(token)


def scoped(key, compute):
    memo = _READ_SCOPE.get()
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return copy.deepcopy(memo[key])
# Written only while some profile carries task-slot declarations, so an
# untouched install keeps a file an older package can still read.
SLOT_SCHEMA = 3
STORE_RELATIVE = Path("plugin-data") / "model-router" / "settings.json"
STATE_RELATIVE = Path("plugin-data") / "model-router" / "recent_apply.json"
SKILL_NAME = "adaptive-coding-orchestration"
ROUTING_SKILL_IDS = frozenset({SKILL_NAME, "model-router:" + SKILL_NAME})

PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
PROVIDER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
# A model ID may end in one bracketed variant tag, as Hermes catalogs declare (`claude-opus-5[1m]`).
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*(?:\[[A-Za-z0-9._-]{1,32}\])?\Z")
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
# Hermes' own per-task spare models for two auxiliary tasks (auxiliary.<task>.fallback_chain). The
# plugin writes only provider/model entries here, straight into the profile's config: nothing is kept
# in the plugin store, so the store schema (read by every installed package) is unchanged.
AUXILIARY_FALLBACK_KEYS = {
    "compression": "auxiliary.compression.fallback_chain",
    "title": "auxiliary.title_generation.fallback_chain",
}
AUXILIARY_FALLBACK_MAX = 5


def _submitted_models(value: Any) -> tuple[dict[str, dict[str, str]], bool]:
    """A request's `models`: all four roles (older clients), or every role except `delegation`.

    Without `delegation` each model target keeps its own delegation settings: the page no longer edits
    delegation.model/provider/reasoning and never writes them. Returns (models, delegation_kept).
    """
    if isinstance(value, dict) and set(value) == set(MODEL_ROLES) - {"delegation"}:
        return {role: _route(value[role]) for role in MODEL_ROLES if role != "delegation"}, True
    return _models(value), False


AUXILIARY_ENV_MASK = "[env]"


def _auxiliary_task_primary(provider: Any, model: Any, main: dict[str, Any] | None) -> dict[str, str] | None:
    """The route an auxiliary task runs on, as Hermes resolves auxiliary.<task> (agent/auxiliary_client.py
    _resolve_task_provider_model), or None when it cannot be established here.

    `model: auto` (any case) is unset, like an empty model. No provider (or `auto`) and no model runs
    on the main model. A concrete provider with a model runs on exactly that. A concrete provider
    without a model uses that provider's catalog default, and `auto` with a model goes through
    Hermes' auto-detection: neither is known here, so the spare-equals-primary check is skipped for
    them (Hermes tolerates such a spare: one on the failed backend is skipped). Shared with the page
    through tests/fixtures/auxiliary_primary_cases.json.
    """
    provider = provider.strip() if isinstance(provider, str) else ""
    model = model.strip() if isinstance(model, str) else ""
    if model.casefold() == "auto":
        model = ""
    if not provider or provider.casefold() == "auto":
        if model:
            return None
        main_provider = main.get("provider") if isinstance(main, dict) else None
        main_model = main.get("model") if isinstance(main, dict) else None
        if not isinstance(main_provider, str) or not main_provider or not isinstance(main_model, str) or not main_model:
            return None
        return {"provider": main_provider, "model": main_model}
    return {"provider": provider, "model": model} if model else None


def _validate_auxiliary_chain(value: Any) -> list[dict[str, str]]:
    """One auxiliary.<task>.fallback_chain as the page may write it: provider/model pairs only."""
    if not isinstance(value, list) or len(value) > AUXILIARY_FALLBACK_MAX:
        raise ValueError("auxiliary fallback chain must contain at most five entries")
    parsed: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"provider", "model"}:
            raise ValueError("auxiliary fallback entries must contain provider and model only")
        provider = _validate_token(item["provider"], field="auxiliary fallback provider", pattern=PROVIDER_RE)
        model = _validate_token(item["model"], field="auxiliary fallback model", pattern=MODEL_RE)
        identity = (provider.casefold(), model.casefold())
        if identity in seen:
            raise ValueError("auxiliary fallback chain entries must be distinct")
        seen.add(identity)
        parsed.append({"provider": provider, "model": model})
    return parsed


def _auxiliary_pairs(value: Any) -> tuple[list[dict[str, str]], list[str]]:
    """The provider/model pairs of one stored or effective chain, and why it is not editable here."""
    if value is None or value == []:
        return [], []
    if not isinstance(value, list):
        return [], ["auxiliary_fallback_malformed"]
    chain: list[dict[str, str]] = []
    warnings: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            warnings.append("auxiliary_fallback_malformed")
            continue
        if set(item) - {"provider", "model"}:
            # base_url/api_key and other knobs: kept as stored, never rewritten from this page.
            warnings.append("auxiliary_fallback_advanced_entry")
        try:
            provider = _validate_token(item.get("provider"), field="auxiliary fallback provider", pattern=PROVIDER_RE)
        except ValueError:
            warnings.append("auxiliary_fallback_malformed")
            continue
        raw_model = item.get("model")
        if raw_model is None or (isinstance(raw_model, str) and raw_model.strip().casefold() in {"", "auto"}):
            # Hermes runs a provider-only entry on that provider's default model: the entry is real,
            # but this editor cannot show its model. Shown with the provider only, read-only.
            warnings.append("auxiliary_fallback_provider_only")
            chain.append({"provider": provider, "model": ""})
            continue
        try:
            model = _validate_token(raw_model, field="auxiliary fallback model", pattern=MODEL_RE)
        except ValueError:
            warnings.append("auxiliary_fallback_malformed")
            continue
        chain.append({"provider": provider, "model": model})
    if len(value) > AUXILIARY_FALLBACK_MAX:
        warnings.append("auxiliary_fallback_chain_too_long")
    return chain, list(dict.fromkeys(warnings))


class ServiceError(RuntimeError):
    """A safe, non-secret settings-service failure."""


class RevisionConflict(ServiceError):
    """The canonical revision or a projected config value changed since preview."""


class ExternalChange(RevisionConflict):
    """A value the page froze at load changed elsewhere before the save (see `expected`).

    The CLI bridge (cli_error_payload) reports it as ``{"error": "ExternalChange", "conflict":
    {"profile", "field"}}``, which the page maps to its reload state (desktop/plugin.js
    externalChangeFromError). Python callers catch ExternalChange or RevisionConflict and read
    ``profile`` and ``field``.
    """

    def __init__(self, profile: str, field: str):
        super().__init__(f"EXTERNAL_CHANGE profile={profile} field={field}: changed since the page loaded it; reload")
        self.profile, self.field = profile, field


def _external_change(profile: str, field: str) -> ExternalChange:
    return ExternalChange(profile, field)


def cli_error_payload(exc: BaseException) -> dict[str, Any]:
    """The MODEL_ROUTER_JSON error frame for an exception escaping a CLI operation."""
    payload: dict[str, Any] = {
        "error": type(exc).__name__,
        "message": "작업이 완료되지 않았습니다. 상태를 확인한 후 다시 미리보기 하세요.",
    }
    if isinstance(exc, ExternalChange):
        payload["conflict"] = {"profile": str(exc.profile), "field": str(exc.field)}
    return payload


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


def _atomic_write(path: Path, payload: bytes, before_replace: Callable[[], None] | None = None) -> None:
    """Write `payload` to a synced temporary file, then replace `path` with it.

    `before_replace` runs after the temporary file is written and synced, immediately before the
    replace; an exception there leaves `path` untouched and removes the temporary file.
    """
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
        if before_replace is not None:
            before_replace()
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


def _routing_fallback(fallback: Any) -> dict[str, Any]:
    if not isinstance(fallback, dict) or set(fallback) != {"enabled", "heavy", "light"} or not isinstance(fallback["enabled"], bool):
        raise ValueError("routing.fallback must define enabled, heavy, and light")
    fb_heavy = None if fallback["heavy"] is None else _route(fallback["heavy"])
    fb_light = None if fallback["light"] is None else _route(fallback["light"])
    if fallback["enabled"] and (fb_heavy is None or fb_light is None):
        raise ValueError("enabled fallback requires explicit Heavy and Light routes")
    return {"enabled": fallback["enabled"], "heavy": fb_heavy, "light": fb_light}


def _routing(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"slots"} != {"enabled", "heavy", "light", "fallback"}:
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
    result = {"enabled": value["enabled"], **resolved, "fallback": _routing_fallback(value["fallback"])}
    # Canonical form: the key exists only while at least one slot is declared.
    declared = slot_model.validate_slots(value["slots"], _route) if "slots" in value else {}
    if declared:
        result["slots"] = declared
    return result


def _keep_absent_keys(entry: Any, raw: Any, loaded: Any) -> Any:
    """`entry` without the keys the stored `raw` entry did not have and the plan left unchanged.

    Loading adds those keys with their defaults; leaving them out again reads back the same way.
    """
    if not (isinstance(entry, dict) and isinstance(raw, dict) and isinstance(loaded, dict)):
        return entry
    out: dict[str, Any] = {}
    for key, value in entry.items():
        if key not in raw:
            if key in loaded and loaded[key] == value:
                continue
            out[key] = value
        else:
            out[key] = _keep_absent_keys(value, raw[key], loaded.get(key))
    return out


def _store_schema(entries: dict[str, Any]) -> int:
    return SLOT_SCHEMA if any(entry["routing"].get("slots") for entry in entries.values()) else SCHEMA


def _stored_slots(entries: dict[str, Any]) -> dict[str, Any]:
    return {name: entry["routing"]["slots"] for name, entry in entries.items()
            if isinstance(entry, dict) and isinstance(entry.get("routing"), dict) and entry["routing"].get("slots")}


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


# A plan reply larger than this keeps each change's profile and field and drops its values.
CLI_REPLY_BUDGET = 40000


def cli_reply(result: Any) -> str:
    """The framed JSON line of one CLI reply. Hermes hands the page at most 48,000 characters of
    a CLI call's output, so a plan whose change list would be larger than ``CLI_REPLY_BUDGET``
    is sent with each change's profile and field only (``changes_compacted``). The plan stored
    for apply is not affected; only what is printed shrinks."""
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= CLI_REPLY_BUDGET or not isinstance(result, dict) or not isinstance(result.get("changes"), list):
        return "MODEL_ROUTER_JSON:" + text
    changes = [{key: change[key] for key in ("profile", "field") if key in change} if isinstance(change, dict) else {}
               for change in result["changes"]]
    return "MODEL_ROUTER_JSON:" + json.dumps({**result, "changes": changes, "changes_compacted": True}, ensure_ascii=False, separators=(",", ":"))


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
        return scoped(("discover", str(self.root)), self._discover_profiles_now)

    def _discover_profiles_now(self) -> list[str]:
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

    def _store_file_digest(self) -> str:
        """SHA-256 of the canonical store file's exact bytes ("absent" when there is none).

        Apply replaces the whole store with the plan's `after`, which was computed from the store
        as preview read it. A plan records this digest and apply refuses when it differs, so a
        change to any profile's entry since preview (even one that left the revision alone) is
        never reverted by a save that did not target it.
        """
        try:
            return hashlib.sha256(self.store_path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return "absent"

    def _preserve_untouched_entries(self, after: dict[str, Any], loaded: dict[str, Any], expected_digest: str) -> dict[str, Any]:
        """The plan's entries, with every entry the plan leaves unchanged kept exactly as stored.

        Loading normalizes entries in memory (for example adding `delegation_fallback: null`).
        An entry the plan does not change is written back as it is in the file, so a save never
        rewrites another profile's entry. A schema change (migration) writes normalized entries.
        """
        try:
            data = self.store_path.read_bytes()
        except FileNotFoundError:
            return after
        # The entries kept must come from the very bytes the plan was computed from.
        if hashlib.sha256(data).hexdigest() != expected_digest:
            raise RevisionConflict("settings changed since preview; preview again")
        try:
            raw = json.loads(data)
        except ValueError:
            return after
        if not isinstance(raw, dict) or raw.get("schema") != _store_schema(after) or not isinstance(raw.get("profiles"), dict):
            return after
        stored = raw["profiles"]
        kept: dict[str, Any] = {}
        for name, entry in after.items():
            if name in stored and name in loaded and loaded[name] == entry:
                kept[name] = copy.deepcopy(stored[name])
            elif name in stored and name in loaded:
                # A changed entry keeps every key it did not have and this save did not change
                # (for example the retired `delegation_fallback` or `fallback_consent.delegation`).
                kept[name] = _keep_absent_keys(entry, stored[name], loaded[name])
            else:
                kept[name] = entry
        return kept

    def _load_store(self) -> dict[str, Any] | None:
        data = _read_json(self.store_path)
        if data is None:
            return None
        if (
            not isinstance(data, dict)
            or set(data) != {"schema", "revision", "profiles"}
            or isinstance(data.get("schema"), bool)
            or data.get("schema") not in {1, SCHEMA, SLOT_SCHEMA}
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
                    if "slots" in entry["routing"]:
                        raise ValueError("schema1 profile entry cannot declare slots")
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
                    if "slots" in entry["routing"] and (data["schema"] != SLOT_SCHEMA or "slots" not in routing):
                        raise ValueError("slot declarations require the slot schema and must not be empty")
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
        if data["schema"] == SLOT_SCHEMA and _store_schema(normalized) != SLOT_SCHEMA:
            raise ServiceError("settings schema is invalid")
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
            from .yaml_compat import yaml
            import rich
            import pydantic
            modules = (hermes_cli, yaml, rich, pydantic)
            paths = []
            for module in modules:
                origin = getattr(module, "__file__", None)
                if not isinstance(origin, str):
                    return []
                source = Path(origin).resolve()
                paths.append(str(source.parents[1] if hasattr(module, "__path__") else source.parent))
            return list(dict.fromkeys(paths))
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
        from .yaml_compat import yaml
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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

    def _kept_role_route(self, profile: str, role: str, main: dict[str, str]) -> dict[str, str]:
        """One non-main role of `profile` as _actual_models resolves it over the given main route,
        from the profile's own config keys (nothing is written)."""
        provider, model, effort = (self._read_key(profile, key) for key in MODEL_KEYS[role])
        provider = provider if isinstance(provider, str) else ""
        model = model if isinstance(model, str) else ""
        effort = effort if isinstance(effort, str) else ""
        if not provider or provider == "auto":
            provider = main["provider"]
        return _route({"provider": provider, "model": model or main["model"], "reasoning": effort or main["reasoning"] or "medium"})

    def _default_routing(self, enabled: bool = False, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        fallback = fallback or {"enabled": False, "heavy": None, "light": None}
        return {
            "enabled": enabled,
            "heavy": {"follow": "main", "custom": None},
            "light": {"follow": "delegation", "custom": None},
            "fallback": fallback,
        }

    def _initial_routing(self, profile: str) -> dict[str, Any]:
        """Installed, unconfigured profiles default on without persisting a migration."""
        home = self._profile_home(profile)
        manifest = home / "plugins" / "model-router" / "plugin.yaml"
        try:
            installed = manifest.is_file() and not manifest.is_symlink() and _inside(manifest, home)
            enabled = installed and not ROUTING_SKILL_IDS.intersection(self._read_disabled(profile))
        except (OSError, ServiceError):
            enabled = False
        return self._default_routing(enabled)

    @staticmethod
    def _check_primary_routes(routing: dict[str, Any], models: dict[str, dict[str, str]]) -> None:
        if not routing["enabled"]:
            return
        heavy = models["main"] if routing["heavy"]["follow"] == "main" else routing["heavy"]["custom"]
        light = models["delegation"] if routing["light"]["follow"] == "delegation" else routing["light"]["custom"]
        # Heavy/Light are task roles, not a requirement for separate models.
        # Validate both routes while allowing the same provider/model/effort.
        _route(heavy)
        _route(light)
        for slot in routing.get("slots", {}):
            _route(slot_model.slot_route(routing, models, slot))

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

    def _read_auxiliary_snapshot(self, profile: str, keys: tuple[str, ...] | list[str] | None = None) -> effective_config.NativeFallbackSnapshot:
        """The auxiliary fallback_chain keys of one profile (both by default; a plan reads only the
        keys it writes, so a sibling task changed elsewhere never refuses it), effective value and
        managed provenance."""
        selected = tuple(keys) if keys else tuple(AUXILIARY_FALLBACK_KEYS.values())
        return effective_config.read_key_scoped(self._profile_home(profile), selected)

    def _auxiliary_cas_holds(self, profile: str, expected: Any, attribute: str, only_key: str | None = None) -> bool:
        """Whether a plan's recorded auxiliary digests (`cas_digest` or `provenance_digest`) still hold.

        Current plans record one digest per written key, each from that key's own snapshot, so a
        sibling task never takes part. A plan from before (one string) is checked over both keys.
        Raises the snapshot errors; callers turn them into a RevisionConflict.
        """
        if isinstance(expected, dict):
            items = [(key, digest) for key, digest in expected.items() if only_key is None or key == only_key]
            return all(getattr(self._read_auxiliary_snapshot(profile, (key,)), attribute) == digest for key, digest in items)
        return getattr(self._read_auxiliary_snapshot(profile), attribute) == expected

    def _auxiliary_status(
        self, profile: str, snapshots: dict[str, effective_config.NativeFallbackSnapshot] | None = None,
        tasks: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, Any]:
        """The compression and title-generation spare models of one profile.

        `chain` is what the profile's own config stores (absent and `[]` both read as no chain),
        `actual_chain` what Hermes resolves. A key covered by a managed (administrator) overlay, an
        env expression, an entry with more than provider/model (for example base_url/api_key) or any
        unverifiable read is read-only here. Built-in tasks cannot be re-registered by a plugin, so
        no plugin `inherit_from` applies to these two blocks.
        """
        result: dict[str, Any] = {}
        for task, key in AUXILIARY_FALLBACK_KEYS.items():
            if tasks is not None and task not in tasks:
                continue
            # Each task from a snapshot of its own key only: a sibling's env expression, malformed
            # value or overlay never makes this task read-only.
            snapshot = (snapshots or {}).get(task)
            if snapshot is None:
                try:
                    snapshot = self._read_auxiliary_snapshot(profile, (key,))
                except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged, OSError, ValueError):
                    snapshot = None
            if snapshot is None:
                result[task] = {"schema": 1, "key": key, "editable": False, "present": False, "chain": [], "actual_chain": [],
                                "drift": False, "managed_overlay": False, "warnings": ["auxiliary_fallback_unavailable"]}
                continue
            warnings = [warning.replace("scoped_fallback_", "auxiliary_fallback_").replace("scoped_", "auxiliary_fallback_")
                        for warning in snapshot.warnings]
            managed_overlay = any(effective_config._managed_applies(managed, key) for managed in snapshot.managed_keys)
            if managed_overlay:
                warnings.append("auxiliary_fallback_managed_overlay")
            raw_value = snapshot.raw(key)
            effective_value = snapshot.effective(key) if snapshot.effective_available else None
            env_masked = effective_config._contains_env_ref(raw_value) or effective_config._contains_env_ref(effective_value)
            if env_masked:
                # An env expression: the expanded value may be a credential or endpoint, so neither the
                # stored nor the resolved provider/model is ever returned, only one placeholder per entry.
                count = len(raw_value) if isinstance(raw_value, list) else 1
                chain = [{"provider": AUXILIARY_ENV_MASK, "model": AUXILIARY_ENV_MASK} for _ in range(min(count, 16))]
                actual_chain = copy.deepcopy(chain)
                warnings.append("auxiliary_fallback_env_expression")
                if not snapshot.effective_available:
                    warnings.append("auxiliary_fallback_unavailable")
            else:
                chain, raw_warnings = _auxiliary_pairs(raw_value)
                warnings.extend(raw_warnings)
                if snapshot.effective_available:
                    actual_chain, effective_warnings = _auxiliary_pairs(effective_value)
                    warnings.extend(effective_warnings)
                else:
                    actual_chain = []
                    warnings.append("auxiliary_fallback_unavailable")
            warnings = list(dict.fromkeys(warnings))
            result[task] = {
                "schema": 1,
                "key": key,
                "editable": not warnings,
                "present": snapshot.raw_present(key),
                "chain": chain,
                "actual_chain": actual_chain,
                # The chain Hermes uses differs from the one the profile stores (an overlay, or a
                # value this page cannot read as provider/model pairs).
                "drift": bool(snapshot.effective_available and not env_masked and actual_chain != chain),
                "managed_overlay": managed_overlay,
                "env_masked": env_masked,
                # The task's own model as Hermes resolves it (None: not known here; then a spare equal
                # to it is not refused).
                "primary": self._auxiliary_primary(profile, task),
                "warnings": warnings,
            }
        return result

    def _auxiliary_primary_inputs(self, task: str) -> tuple[str, ...]:
        """The config keys the task's primary route is resolved from (bound into a plan's CAS)."""
        return (*MODEL_KEYS[task][:2], *MODEL_KEYS["main"][:2])

    def _auxiliary_primary(self, profile: str, task: str, base_plan: dict | None = None) -> dict[str, str] | None:
        """The route the task runs on for this profile once the plan applies (see
        _auxiliary_task_primary): the approved models of a model target of the same plan, otherwise
        the profile's own auxiliary.<task> and model keys. None when not known here."""
        if base_plan is not None and profile in (base_plan.get("model_targets") or []):
            approved = (base_plan.get("approved_models") or {}).get(profile)
            if approved and task in approved and "main" in approved:
                return _auxiliary_task_primary(approved[task].get("provider"), approved[task].get("model"), approved["main"])
        try:
            task_provider, task_model, main_provider, main_model = (self._read_key(profile, key) for key in self._auxiliary_primary_inputs(task))
        except (ServiceError, OSError, ValueError):
            return None
        return _auxiliary_task_primary(task_provider, task_model, {"provider": main_provider, "model": main_model})

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
                self._check_primary_routes(entries[name]["routing"], entries[name]["models"])
            changed = stored is None or entries != stored["profiles"]
            revision = (stored["revision"] if stored else 0) + (1 if changed else 0)
            data = {"schema": _store_schema(entries), "revision": revision, "profiles": entries}
            if changed:
                _atomic_write(self.store_path, _json_bytes(data))
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            applied: list[str] = []
            for name in discovered:
                want_enabled = name in selected
                try:
                    disabled = self._read_disabled(name)
                    currently_enabled = not ROUTING_SKILL_IDS.intersection(disabled)
                    if currently_enabled != want_enabled:
                        updated = [item for item in disabled if item not in ROUTING_SKILL_IDS]
                        if not want_enabled:
                            updated.append(SKILL_NAME)
                        self._backup_config(name, stamp)
                        self._write_key(name, "skills.disabled", updated)
                        if self._read_disabled(name) != updated:
                            raise ServiceError("skills.disabled readback mismatch")
                        applied.append(name)

                except Exception as exc:
                    receipt = {"status": "partial", "revision": revision, "applied_profiles": applied, "finished_at": _now()}
                    self._store_apply(receipt)
                    if isinstance(exc, ServiceError):
                        raise
                    raise ServiceError("initialization partially applied") from exc
            if applied:
                self._store_apply({"status": "initialized", "revision": revision, "profiles": applied, "finished_at": _now()})
            return self.status()

    def _native_delegation_code_signature(self, profile: str) -> str | None:
        from .native_service import _code_signature
        return _code_signature(self, profile)

    def _read_native_delegation_snapshot(self, profile: str):
        from .native_service import read_snapshot
        return read_snapshot(self, profile)

    def delegation_preview(self, body: dict) -> dict[str, Any]:
        from .native_service import preview
        with read_scope():
            return preview(self, body)

    def initial_setup_preview(self, body: dict) -> dict[str, Any]:
        return native_service.initial_setup_preview(self, body)

    def _role_intro(self, profile: str) -> dict[str, Any]:
        from .role_metadata import resolve
        return resolve(self, profile)

    # Hermes returns at most 48,000 characters of a CLI call's output to the page; a larger reply
    # arrives cut and cannot be parsed. A paged reply stays well under that.
    STATUS_PAGE_BUDGET = 30000

    def status(self, *, paged: bool = False, profiles: list[str] | None = None) -> dict[str, Any]:
        """Settings status. ``paged`` bounds the reply size: rows that do not fit are named in
        ``pending_profiles`` and are read with a further call passing them as ``profiles``."""
        with read_scope():
            return self._status_now(paged=paged, profiles=profiles)

    def _status_now(self, *, paged: bool, profiles: list[str] | None) -> dict[str, Any]:
        discovered = self._discover_profiles()
        if profiles is not None:
            if not paged:
                raise ValueError("profiles requires a paged status")
            if (not isinstance(profiles, list) or not profiles or any(not isinstance(name, str) for name in profiles)
                    or len(set(profiles)) != len(profiles) or not set(profiles) <= set(discovered)):
                raise ValueError("profiles must be distinct known profile names")
        stored = self._load_store()
        entries = stored["profiles"] if stored else {}
        wanted = [name for name in discovered if profiles is None or name in profiles]
        result: dict[str, Any] = {
            "role_proposal": {"schema": 1, "transport": "native_cli", "available": False, "reason_code": "unsupported_transport"},
            "revision": stored["revision"] if stored else 0,
            "current_profile": self.active_profile(),
            "profiles": [],
            "recent_apply": self._recent_apply(),
            "fallback_capabilities": dict(fallback_policy.CAPABILITIES),
            "readiness_context": installation.readiness_context(self),
            "slot_capabilities": {
                "schema": 1,
                "slots": list(slot_model.BUILTIN_SLOTS),
                "tiers": dict(slot_model.SLOT_TIERS),
                "purposes": dict(slot_model.PURPOSE_SLOTS),
                "follows": list(slot_model.FOLLOWS),
                "blocking_profiles": self._slot_blocking_profiles(discovered),
            },
        }
        if not paged:
            result["profiles"] = [self._status_row(name, entries, stored) for name in wanted]
            return result
        result["profile_names"] = list(discovered)
        result["pending_profiles"] = []
        size = len(json.dumps({**result, "pending_profiles": wanted}, ensure_ascii=False, separators=(",", ":")))
        for index, name in enumerate(wanted):
            row = self._status_row(name, entries, stored)
            size += len(json.dumps(row, ensure_ascii=False, separators=(",", ":"))) + 1
            if result["profiles"] and size > self.STATUS_PAGE_BUDGET:
                result["pending_profiles"] = wanted[index:]
                break
            result["profiles"].append(row)
        return result

    def _status_row(self, name: str, entries: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
        entry = entries.get(name)
        try:
            actual = self._actual_models(name, tolerate=True)
        except ServiceError:
            actual = {}
        if entry is None:
            models = actual
            routing = self._initial_routing(name)
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
            if (not ROUTING_SKILL_IDS.intersection(disabled)) != bool(routing.get("enabled")):
                drift.append("skills.disabled")
        except ServiceError:
            drift.append("skills.disabled_unavailable")
        return {
            "name": name,
            "models": models,
            "routing": routing,
            "slots": self._slots_dto(name, routing),
            "actual_models": actual,
            "drift": drift,
            "fallbacks": self._fallback_dto(name, view_entry),
            "auxiliary_fallbacks": self._auxiliary_status(name),
            "readiness": installation.profile_readiness(self, name, stored),
            "native_delegation": native_service.status(self, name),
            "role_intro": self._role_intro(name),
            "initial_setup": native_service.initial_setup_status(self, name),
            "timeouts": {
                **timeouts.timeout_status(
                    self._profile_home(name),
                    enforcement_available=self._timeout_enforcement_available(name),
                ),
                "split_routing_supported": self._timeout_role_enforcement_available(name),
            },
        }

    def _slot_capable(self, profile: str) -> bool:
        """Whether that profile's installed package can read slot settings.

        The canonical store is shared by every profile, so one profile saving
        slots changes what every other installed package has to parse.
        """
        home = self._profile_home(profile)
        package = home / "plugins" / "model-router"
        try:
            if not (package / "plugin.yaml").is_file():
                return True  # nothing installed there reads the shared store
            path = package / "model_router" / "slots.py"
            reference = Path(__file__).with_name("slots.py")
            if path.is_symlink() or not _inside(path, home) or not path.is_file() or path.stat().st_size > 256 * 1024:
                return False
            return path.read_bytes().replace(b"\r\n", b"\n") == reference.read_bytes().replace(b"\r\n", b"\n")
        except OSError:
            return False

    def _slot_blocking_profiles(self, discovered: list[str]) -> list[str]:
        return [name for name in discovered if not self._slot_capable(name)]

    def _slots_dto(self, profile: str, routing: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": 1,
            "capable": self._slot_capable(profile),
            "stored": [slot for slot in slot_model.BUILTIN_SLOTS if slot in routing.get("slots", {})],
            "declarations": slot_model.effective_declarations(routing),
        }

    def native_route_config(self, profile: str) -> dict[str, Any]:
        """Resolve purpose routes without silently adopting externally changed models."""
        config = self.routing_config(profile)
        stored = self._load_store()
        if (stored["revision"] if stored else 0) != config["revision"]:
            raise RevisionConflict("routing settings changed during native dispatch")
        entry = stored["profiles"].get(profile) if stored else None
        if entry is not None and entry["models"] != self._actual_models(profile):
            raise RevisionConflict("native purpose route denied because the profile has model drift")
        return config

    def routing_config(self, profile: str) -> dict[str, Any]:
        profile = self._require_profile(profile)
        stored = self._load_store()
        entry = stored["profiles"].get(profile) if stored else None
        if entry is None:
            models = self._actual_models(profile)
            routing = self._initial_routing(profile)
            revision = stored["revision"] if stored else 0
        else:
            models, routing, revision = entry["models"], entry["routing"], stored["revision"]
        heavy = models["main"] if routing["heavy"]["follow"] == "main" else routing["heavy"]["custom"]
        light = models["delegation"] if routing["light"]["follow"] == "delegation" else routing["light"]["custom"]
        enabled = routing["enabled"] and not ROUTING_SKILL_IDS.intersection(self._read_disabled(profile))
        consent = entry.get("fallback_consent", {}).get("routing") if entry else None
        approved = routing["fallback"]["enabled"] and fallback_policy.consent_matches(
            profile, "routing", routing["fallback"], consent
        )
        limits = timeouts.read_timeouts(self._profile_home(profile))
        config = {
            "enabled": enabled,
            "heavy": dict(heavy),
            "light": dict(light),
            # What each task slot runs on. Heavy/Light above remain for
            # historical readers and for a slot that has never been set.
            "slots": slot_model.resolved_slots(routing, models),
            "slot_tiers": dict(slot_model.SLOT_TIERS),
            "purpose_slots": dict(slot_model.PURPOSE_SLOTS),
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
            "routing": self._initial_routing(profile),
            "native_fallback": None,
            "delegation_fallback": None,
            "fallback_consent": {"native": None, "routing": None, "delegation": None},
        }

    def _timeout_code_support(self, profile: str) -> dict[str, bool]:
        """Observe bounded base/split support without executing plugin code."""
        try:
            self._require_profile(profile)
            base, split = installation.timeout_code_support(
                self._profile_home(profile), self.root, self.store_path
            )
        except (OSError, TypeError, ValueError, RuntimeError):
            return {"base": False, "split": False}
        return {"base": bool(base), "split": bool(split)}

    def _timeout_python_enabled(self, profile: str) -> bool:
        try:
            self._require_profile(profile)
            return installation.timeout_python_enabled(self._profile_home(profile))
        except (OSError, TypeError, ValueError, RuntimeError):
            return False

    def _timeout_enforcement_available(self, profile: str) -> bool:
        """Compatibility predicate: supported base code plus proven Python allow."""
        return self._timeout_code_support(profile)["base"] and self._timeout_python_enabled(profile)

    def _timeout_role_enforcement_available(self, profile: str) -> bool:
        """Split timeout eligibility additionally needs its literal AST marker."""
        return self._timeout_code_support(profile)["split"] and self._timeout_python_enabled(profile)

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

    # Compare-and-set against what the page showed. A page sends, per profile it writes, the status
    # values it froze when it loaded them (`expected`); preview and apply compare each one with the
    # current value and refuse the whole save, writing nothing, on any difference. The error carries a
    # stable code the page maps to its "changed elsewhere, reload" state. Clients that send no
    # `expected` keep the previous behaviour (revision, preview snapshots and apply CAS only).
    PAGE_EXPECTATION_FIELDS = ("models", "actual_models", "routing", "native_fallback", "auxiliary_fallback")

    @staticmethod
    def _valid_page_expectation(field: str, value: Any) -> bool:
        """Strict schema of one expected value: real bools, bounded strings, no unknown keys.

        Python compares 1 == True, so a loose value could match a different stored one; every leaf
        must have exactly the type the status row reports.
        """
        def text(item: Any, limit: int = 512) -> bool:
            return type(item) is str and len(item) <= limit

        def route(item: Any) -> bool:
            return type(item) is dict and set(item) == {"provider", "model", "reasoning"} and all(text(item[key]) for key in item)

        def declaration(item: Any) -> bool:
            return (type(item) is dict and set(item) == {"follow", "custom"} and text(item["follow"], 32) and
                    (item["custom"] is None or route(item["custom"])))

        def chain(item: Any) -> bool:
            return (type(item) is list and len(item) <= 16 and
                    all(type(entry) is dict and set(entry) == {"provider", "model"} and text(entry["provider"]) and text(entry["model"]) for entry in item))

        if field in {"models", "actual_models"}:
            return type(value) is dict and set(value) <= set(MODEL_ROLES) and all(route(item) for item in value.values())
        if field == "routing":
            return (type(value) is dict and set(value) == {"enabled", "heavy", "light", "slots", "skill_enabled"} and
                    type(value["enabled"]) is bool and value["skill_enabled"] in (True, False, None) and
                    (value["skill_enabled"] is None or type(value["skill_enabled"]) is bool) and
                    all(value[key] is None or declaration(value[key]) for key in ("heavy", "light")) and
                    (value["slots"] is None or (type(value["slots"]) is dict and len(value["slots"]) <= 32 and
                                                all(text(key, 64) and declaration(item) for key, item in value["slots"].items()))))
        if field == "native_fallback":
            return (type(value) is dict and set(value) == {"enabled", "chain", "actual_chain"} and
                    (value["enabled"] is None or type(value["enabled"]) is bool) and chain(value["chain"]) and chain(value["actual_chain"]))
        if field == "auxiliary_fallback":
            # Every task the request writes (older pages send both); compared per task.
            return (type(value) is dict and bool(value) and set(value) <= set(AUXILIARY_FALLBACK_KEYS) and
                    all(type(item) is dict and set(item) == {"chain", "actual_chain"} and chain(item["chain"]) and chain(item["actual_chain"])
                        for item in value.values()))
        return False

    def _parse_page_expectations(self, raw: Any, discovered: list[str]) -> list[dict[str, Any]]:
        """Parse a present `expected` (an absent key, not null, is the legacy behaviour).

        One entry per discovered profile at most, so the bound is never lower than the number of
        profiles a status can report. Extra entries only add checks; they never grant a write.
        """
        if type(raw) is not list or len(raw) > len(discovered):
            raise ValueError("expected must be a list with at most one entry per profile")
        items, seen = [], set()
        for item in raw:
            if (type(item) is not dict or "profile" not in item or len(item) < 2 or
                    set(item) - {"profile", *self.PAGE_EXPECTATION_FIELDS}):
                raise ValueError("each expectation names a profile and known fields")
            profile = self._require_profile(item["profile"], discovered)
            if profile in seen:
                raise ValueError("expected must not contain duplicate profiles")
            for field, value in item.items():
                if field != "profile" and not self._valid_page_expectation(field, value):
                    raise ValueError(f"expected {field} of {profile} is malformed")
            if len(json.dumps(item)) > 65536:
                raise ValueError(f"expected entry of {profile} is too large")
            seen.add(profile)
            items.append(copy.deepcopy(item))
        return items

    def _page_expectation_current(self, profile: str, field: str, entries: dict[str, Any]) -> Any:
        """The current value of one expectation field, in the shape the status row reports it."""
        entry = entries.get(profile)
        if field == "actual_models" or (field == "models" and entry is None):
            try:
                return self._actual_models(profile, tolerate=True)
            except ServiceError:
                return {}
        if field == "models":
            return entry["models"]
        if field == "routing":
            routing = entry["routing"] if entry is not None else self._initial_routing(profile)
            # The effective switch is the canonical flag and the routing skill's own state in the
            # profile's skills.disabled (None when unreadable); a save may rewrite either.
            try:
                skill_enabled: bool | None = not ROUTING_SKILL_IDS.intersection(self._read_disabled(profile))
            except ServiceError:
                skill_enabled = None
            return {"enabled": bool(routing.get("enabled")), "heavy": routing.get("heavy"),
                    "light": routing.get("light"), "slots": routing.get("slots"), "skill_enabled": skill_enabled}
        if field == "auxiliary_fallback":
            auxiliary = self._auxiliary_status(profile)
            return {task: {"chain": item["chain"], "actual_chain": item["actual_chain"]} for task, item in auxiliary.items()}
        view = entry if entry is not None else {"native_fallback": None, "fallback_consent": {}}
        native = self._native_status(profile, view)
        return {"enabled": native["enabled"], "chain": native["chain"], "actual_chain": native["actual_chain"]}

    def _check_page_expectations(self, items: list[dict[str, Any]] | None, entries: dict[str, Any],
                                 required: dict[str, set[str]] | None = None) -> None:
        if items is None:
            return
        by_profile = {item["profile"]: item for item in items}
        for profile, fields in sorted((required or {}).items()):
            for field in sorted(fields):
                # "auxiliary_fallback.<task>": that task of the field (the tasks a request writes).
                base, _, part = field.partition(".")
                held = by_profile.get(profile, {})
                if base not in held or (part and not (isinstance(held[base], dict) and part in held[base])):
                    raise ValueError(f"expected must cover {field} of {profile}")
        for item in items:
            profile = item["profile"]
            for field in self.PAGE_EXPECTATION_FIELDS:
                if field not in item:
                    continue
                current = json.loads(json.dumps(self._page_expectation_current(profile, field, entries)))
                if field == "auxiliary_fallback" and isinstance(current, dict):
                    # Only the tasks the page froze (the ones it writes): a sibling task changed
                    # elsewhere never blocks this save.
                    current = {task: current.get(task) for task in item[field]}
                if current == item[field]:
                    continue
                detail = field
                if isinstance(current, dict) and isinstance(item[field], dict):
                    order = {role: index for index, role in enumerate(MODEL_ROLES)}
                    differing = sorted((key for key in set(current) | set(item[field]) if current.get(key) != item[field].get(key)),
                                       key=lambda key: (order.get(key, len(order)), key))
                    if differing and field in {"models", "actual_models", "auxiliary_fallback"}:
                        detail = f"{field}.{differing[0]}"
                raise _external_change(profile, detail)

    def preview(self, body: dict) -> dict[str, Any]:
        required = {"expected_revision", "profile", "models", "model_targets", "routing", "routing_profiles"}
        optional = {"fallback_updates", "fallback_confirmations", "routing_targets", "timeout_updates", "save_scope", "expected", "reenable_profiles"}
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
        page_expected = self._parse_page_expectations(body["expected"], discovered) if "expected" in body else None
        if page_expected is not None and any(isinstance(update, dict) and set(update) & {"routing_fallback", "delegation_fallback"} for update in fallback_updates):
            raise ValueError("expected covers the conversation fallback only")
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
        # Profiles the request explicitly turns routing back on for, including one whose canonical flag
        # is on but whose routing skill is disabled in its own config. Each must also be selected.
        raw_reenable = body.get("reenable_profiles", [])
        if not isinstance(raw_reenable, list) or len(set(map(str, raw_reenable))) != len(raw_reenable):
            raise ValueError("reenable_profiles must be a list of distinct profiles")
        reenable_set = {self._require_profile(name, discovered) for name in raw_reenable}
        if reenable_set - set(selected):
            raise ValueError("reenable_profiles must also be in routing_profiles")
        if reenable_set and scope not in {None, "routing"}:
            raise ValueError("reenable_profiles are outside the selected save scope")
        if len(set(targets)) != len(targets) or len(set(selected)) != len(selected) or len(set(routing_targets)) != len(routing_targets):
            raise ValueError("profile lists must not contain duplicates")
        if scope in {"routing", "timeouts"} and targets:
            raise ValueError("model targets are outside the selected save scope")
        if scope in {"models", "timeouts"} and "routing_targets" in body and routing_targets:
            raise ValueError("routing targets are outside the selected save scope")
        # A page that no longer edits the delegation role leaves it out: each target keeps its own.
        submitted_models, delegation_kept = _submitted_models(body["models"]) if scope in {None, "models"} else (None, False)
        # The retired routed-job fallback is written only by fallback_preview. A client may omit
        # routing.fallback; the stored value is then kept as it is. One that sends it must send the
        # stored value unchanged (older pages), in every save scope.
        routing_body = body["routing"]
        fallback_submitted = isinstance(routing_body, dict) and "fallback" in routing_body
        if isinstance(routing_body, dict) and not fallback_submitted:
            routing_body = {**routing_body, "fallback": {"enabled": False, "heavy": None, "light": None}}
        if scope is None:
            submitted_routing = _routing(routing_body)
        elif scope == "routing":
            if not isinstance(routing_body, dict) or set(routing_body) - {"slots"} != {"enabled", "heavy", "light", "fallback"}:
                raise ValueError("routing must define enabled, heavy, light, and fallback")
            # Validate membership and Heavy/Light declarations here; a submitted fallback is only
            # checked to equal the stored value below (it is never written by this request).
            submitted_routing = _routing({
                "enabled": routing_body["enabled"],
                "heavy": routing_body["heavy"],
                "light": routing_body["light"],
                "fallback": {"enabled": False, "heavy": None, "light": None},
                **({"slots": routing_body["slots"]} if "slots" in routing_body else {}),
            })
        else:
            submitted_routing = None
        if submitted_routing is not None and submitted_routing["enabled"] != (profile in selected):
            raise ValueError("routing.enabled must match routing_profiles membership")
        # A client that predates slots omits the key; its save must leave any
        # stored slot declarations alone instead of clearing what it cannot see.
        slots_submitted = submitted_routing is not None and isinstance(body["routing"], dict) and "slots" in body["routing"]

        store_digest = self._store_file_digest()
        stored = self._load_store()
        revision = stored["revision"] if stored else 0
        if expected != revision:
            raise RevisionConflict("settings revision changed; reload before preview")
        entries = dict(stored["profiles"]) if stored else {}
        # Compare the frozen values before projecting anything: a value changed elsewhere (even one
        # that leaves a model unresolvable) is that profile's ExternalChange, not a later error.
        self._check_page_expectations(page_expected, entries)
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
            projected = {name: self._fresh_profile_entry(name, entries) for name in all_names if name in discovered or name in entries}
            after = copy.deepcopy(projected)
        if fallback_submitted:
            # Compare with the stored value, or the initial one for a profile without a stored entry
            # (the initial routing fallback is always the disabled default). Never resolve the
            # profile's models for this: a timeout-only save must not fail on an unrelated model.
            stored_fallback = entries[profile]["routing"]["fallback"] if profile in entries else self._default_routing()["fallback"]
            if _routing_fallback(routing_body["fallback"]) != stored_fallback:
                raise ValueError("routing.fallback can only be changed by fallback_preview")
        if submitted_routing is not None and submitted_routing.get("slots"):
            blocking = self._slot_blocking_profiles(discovered)
            if blocking:
                raise ValueError("task slots need every installed profile on this plugin version first")
        changes: list[dict[str, Any]] = []
        snapshots: dict[str, dict[str, Any]] = {}
        writes: list[dict[str, Any]] = []

        routing_validation_names: set[str] = set()
        # What each model target must resolve to after apply (readback), when it differs from the
        # models recorded in the store: an omitted delegation role keeps its canonical store value.
        readback_models: dict[str, dict[str, Any]] = {}
        if submitted_models is not None:
            for name in targets:
                entry = after[name]
                desired = submitted_models
                store_models = desired
                if delegation_kept:
                    # The target's own delegation settings, resolved the way _actual_models will read
                    # them once the new main model is written: the readback value only. No delegation
                    # key is written; the per-key config CAS below (all model keys) refuses the apply
                    # if they change.
                    desired = {role: submitted_models[role] if role != "delegation" else self._kept_role_route(name, role, submitted_models["main"])
                               for role in MODEL_ROLES}
                    # The store keeps its own canonical delegation route exactly (legacy Light and
                    # slot routing read it); only a profile without a stored entry gets the resolved one.
                    stored_delegation = (entries.get(name) or {}).get("models", {}).get("delegation")
                    store_models = {**desired, "delegation": copy.deepcopy(stored_delegation)} if stored_delegation is not None else desired
                    readback_models[name] = copy.deepcopy(desired)
                if entry["models"] != store_models:
                    changes.append({"profile": name, "field": "settings.models", "before": entry["models"], "after": store_models})
                actual = self._actual_models(name)
                profile_values = self._profile_digest_keys(name, desired, False)
                snapshots[name] = profile_values
                for role in MODEL_ROLES:
                    if delegation_kept and role == "delegation":
                        continue
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
                entry["models"] = store_models
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
                if slots_submitted:
                    # A copy to another profile keeps that profile's stored slots that follow the
                    # delegation model (an earlier setting the page no longer offers) exactly.
                    kept_legacy = {} if name == profile else {
                        slot: copy.deepcopy(declaration) for slot, declaration in (entry["routing"].get("slots") or {}).items()
                        if isinstance(declaration, dict) and declaration.get("follow") == "delegation"}
                    new_routing.pop("slots", None)
                    merged = {**copy.deepcopy(submitted_routing.get("slots") or {}), **kept_legacy}
                    if merged:
                        new_routing["slots"] = merged
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
            skill_on = not ROUTING_SKILL_IDS.intersection(disabled)
            # The routing skill is removed from skills.disabled (switched on) only for an explicit
            # re-enable: the canonical flag goes off -> on in this request (the re-enable list), or
            # the profile is named in reenable_profiles. Membership alone never undoes an opt-out
            # made in the profile's own config; switching off keeps working as before.
            explicit_reenable = (not old_enabled and new_enabled) or name in reenable_set
            desired_skill_on = new_enabled and (explicit_reenable or skill_on)
            if old_enabled != new_enabled or skill_on != desired_skill_on:
                updated = [item for item in disabled if item not in ROUTING_SKILL_IDS]
                if not desired_skill_on:
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
                    # The routing skill's own state, before and after (not the canonical flag).
                    changes.append({"profile": name, "field": "skills.disabled", "before": "enabled" if skill_on else "disabled", "after": "enabled" if desired_skill_on else "disabled"})


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
                    self._check_primary_routes(entry["routing"], entry["models"])
            if not fallback_updates:
                self._check_changed_routing_fallbacks(entries, after)
        # The models every explicit model target must resolve to after apply, recorded before an
        # unchanged target's projected entry is dropped below (a NOOP target has no entry to read).
        approved_models = {name: copy.deepcopy(readback_models.get(name, after[name]["models"])) for name in (targets if submitted_models is not None else []) if name in after}
        if scope in {None, "routing"}:
            # A profile without a stored entry gets one only if this plan changes it: an entry that
            # was merely projected for the membership loop is dropped, so absent stays absent and its
            # current models are never pinned into the store.
            after = {name: entry for name, entry in after.items() if name in entries or entry != projected.get(name)}
        state_changed = scope != "timeouts" and after != entries
        if page_expected is not None:
            # Every profile and field this save writes must be covered, and must still hold.
            needed: dict[str, set[str]] = {}
            for name in (targets if submitted_models is not None else []):
                needed.setdefault(name, set()).update({"models", "actual_models"})
            for change in changes:
                if change["field"] in {"routing", "routing.enabled", "skills.disabled"}:
                    needed.setdefault(change["profile"], set()).add("routing")
            for update in fallback_updates:
                if isinstance(update, dict) and isinstance(update.get("profile"), str):
                    if "native_fallback" in update:
                        needed.setdefault(update["profile"], set()).add("native_fallback")
                    if isinstance(update.get("auxiliary_fallback"), dict):
                        needed.setdefault(update["profile"], set()).update(f"auxiliary_fallback.{task}" for task in update["auxiliary_fallback"])
            self._check_page_expectations(page_expected, entries, needed)
        plan_id = uuid.uuid4().hex
        expires_epoch = time.time() + self.PLAN_TTL
        expires_at = datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
        config_digests = {name: _digest(values) for name, values in snapshots.items()}
        plan = {
            "id": plan_id, "revision": revision, "after": after, "changes": changes,
            "snapshots": snapshots, "config_digests": config_digests, "writes": writes,
            "model_targets": targets, "approved_models": approved_models, "state_changed": state_changed, "expires_epoch": expires_epoch,
            # Preserve target validation independently of obsolete skill-file ownership.
            "validation_profiles": sorted(set(selected) & set(discovered)) if scope in {None, "routing"} else [],
            "timeout_writes": timeout_writes,
            "save_scope": scope,
            "page_expected": page_expected,
            # The exact store bytes this plan was computed from (read before and after loading).
            "store_digest": store_digest,
        }
        if self._store_file_digest() != store_digest:
            raise RevisionConflict("settings changed during preview; preview again")
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

    def _plan_auxiliary_fallback(
        self, profile: str, chains: dict[str, list[dict[str, str]]], confirmation: dict[str, bool] | None,
        base_plan: dict | None, snapshots: dict, writes: list, changes: list,
        expected: dict, cas: dict, provenance: dict, scope_keys: dict,
    ) -> None:
        """Plan the config-only write of `auxiliary.<task>.fallback_chain` for one profile.

        Only the tasks in `chains` are touched. A key is written only when the requested chain differs
        from the stored one; turning the chain off writes `[]` over a stored chain and leaves an
        absent (or null) key absent. Every key is compare-and-set at apply (raw digest per key, the
        effective snapshot, its managed provenance) and read back through Hermes' effective config.
        """
        # One read per written key: the snapshot editability is judged from is the plan's baseline.
        task_snapshots: dict[str, effective_config.NativeFallbackSnapshot] = {}
        for task in chains:
            try:
                task_snapshots[task] = self._read_auxiliary_snapshot(profile, (AUXILIARY_FALLBACK_KEYS[task],))
            except effective_config.EffectiveConfigChanged as exc:
                raise RevisionConflict("auxiliary fallback config changed during preview") from exc
            except effective_config.EffectiveConfigUnavailable as exc:
                raise ValueError("auxiliary fallback is read-only because effective config cannot be verified") from exc
        status = self._auxiliary_status(profile, task_snapshots, tuple(chains))
        adds_spares = False
        for task, desired in chains.items():
            key = AUXILIARY_FALLBACK_KEYS[task]
            current = status[task]
            if not current["editable"]:
                raise ValueError(f"auxiliary {task} fallback is read-only for this profile")
            primary = self._auxiliary_primary(profile, task, base_plan)
            if primary is not None:
                identity = (primary["provider"].casefold(), primary["model"].casefold())
                if any((item["provider"].casefold(), item["model"].casefold()) == identity for item in desired):
                    raise ValueError(f"auxiliary {task} fallback must differ from the task's primary model")
            raw = task_snapshots[task].raw(key)
            values = snapshots.setdefault(profile, {})
            values[key] = {"sha256": _digest(raw)}
            # The primary route was checked from these keys: a change before apply refuses the apply
            # (a model target of the same plan is checked against its approved models instead).
            if not (base_plan is not None and profile in (base_plan.get("model_targets") or [])):
                for input_key in self._auxiliary_primary_inputs(task):
                    values.setdefault(input_key, self._read_key(profile, input_key))
            expected.setdefault(profile, {})[task] = copy.deepcopy(desired)
            if desired == [] and raw in (None, []):
                continue  # already off; an absent key stays absent
            if raw == desired:
                continue
            if desired:
                adds_spares = True
            writes.append({"profile": profile, "key": key, "before": {"sha256": _digest(raw)}, "after": copy.deepcopy(desired)})
            changes.append({"profile": profile, "field": key, "before": current["chain"], "after": copy.deepcopy(desired)})
        # Nothing is stored for a later save to compare against, so every write that sets spare models
        # carries the page's explicit cost confirmation (the save click), as the conversation spares do.
        if adds_spares and confirmation is None:
            raise ValueError("auxiliary fallback requires explicit additional-cost confirmation")
        # The compare-and-set covers only the keys of the tasks this update writes, one digest per
        # key from the very snapshot its editability was judged from.
        scoped_keys = [AUXILIARY_FALLBACK_KEYS[task] for task in AUXILIARY_FALLBACK_KEYS if task in chains]
        cas[profile] = {AUXILIARY_FALLBACK_KEYS[task]: task_snapshots[task].cas_digest for task in chains}
        provenance[profile] = {AUXILIARY_FALLBACK_KEYS[task]: task_snapshots[task].provenance_digest for task in chains}
        scope_keys[profile] = scoped_keys

    def fallback_preview(self, body: dict) -> dict[str, Any]:
        """Prepare a fallback-only update through the same combined-plan builder."""
        return self._prepare_fallback_preview(body)

    def _prepare_fallback_preview(self, body: dict, *, base_plan: dict | None = None) -> dict[str, Any]:
        """Prepare explicit scope updates, optionally on a pending model plan."""
        fields = {"expected_revision", "updates", "confirmations"}
        # A standalone fallback save may carry the page's frozen expectations, too (see preview).
        if not isinstance(body, dict) or not (set(body) == fields or (base_plan is None and set(body) == fields | {"expected"})):
            raise ValueError("fallback preview body has unknown or missing fields")
        if "expected" in body and isinstance(body["updates"], list) and any(
                isinstance(update, dict) and set(update) & {"routing_fallback", "delegation_fallback"} for update in body["updates"]):
            raise ValueError("expected covers the conversation fallback only")
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
            if not isinstance(update, dict) or not set(update) <= {"profile", "native_fallback", "routing_fallback", "delegation_fallback", "auxiliary_fallback"} or "profile" not in update:
                raise ValueError("each update must contain profile and known fallback scopes")
            if not (set(update) & {"native_fallback", "routing_fallback", "delegation_fallback", "auxiliary_fallback"}):
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
            if "auxiliary_fallback" in update:
                # {task: chain} for the tasks this update writes; a task left out is not touched.
                # `[]` turns the task's spare models off.
                raw = update["auxiliary_fallback"]
                if not isinstance(raw, dict) or not raw or set(raw) - set(AUXILIARY_FALLBACK_KEYS):
                    raise ValueError("auxiliary_fallback must map compression and/or title to a chain")
                scopes["auxiliary"] = {task: _validate_auxiliary_chain(raw[task]) for task in AUXILIARY_FALLBACK_KEYS if task in raw}
            parsed_updates.append((profile, scopes))

        confirmation_map: dict[tuple[str, str], dict[str, bool]] = {}
        for item in confirmations:
            if not isinstance(item, dict) or set(item) != {"profile", "scope", "allow_additional_cost", "allow_task_rerun"}:
                raise ValueError("each confirmation must define profile, scope, cost, and rerun flags")
            profile = self._require_profile(item["profile"], discovered)
            scope = item["scope"]
            if scope not in {"native", "routing", "delegation", "auxiliary"}:
                raise ValueError("confirmation scope must be native, routing, delegation, or auxiliary")
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

        store_digest = self._store_file_digest()
        if base_plan is not None and base_plan.get("store_digest") != store_digest:
            raise RevisionConflict("settings changed during combined preview")
        stored = self._load_store()
        revision = stored["revision"] if stored else 0
        if expected != revision:
            raise RevisionConflict("settings revision changed; reload before fallback preview")
        entries = copy.deepcopy(stored["profiles"]) if stored else {}
        if base_plan is not None and base_plan["revision"] != revision:
            raise RevisionConflict("settings revision changed during combined preview")
        page_expected = self._parse_page_expectations(body["expected"], discovered) if base_plan is None and "expected" in body else None
        if page_expected is not None:
            self._check_page_expectations(page_expected, entries, {
                update["profile"]: ({"native_fallback"} if "native_fallback" in update else set()) |
                                   {f"auxiliary_fallback.{task}" for task in (update.get("auxiliary_fallback") or {})}
                for update in updates
                if isinstance(update, dict) and set(update) & {"native_fallback", "auxiliary_fallback"} and isinstance(update.get("profile"), str)})
        all_names = sorted(set(discovered) | set(entries), key=lambda item: (item != "default", item))
        # Only the profiles this plan changes get an entry. Projecting every discovered profile
        # would publish a new canonical entry (pinning its current models) for untargeted profiles.
        after = copy.deepcopy(base_plan["after"]) if base_plan is not None else copy.deepcopy(entries)
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

        auxiliary_expected: dict[str, dict[str, list[dict[str, str]]]] = {}
        auxiliary_snapshots: dict[str, str] = {}
        auxiliary_provenance: dict[str, str] = {}
        auxiliary_snapshot_keys: dict[str, list[str]] = {}
        for profile, scopes in parsed_updates:
            if "auxiliary" in scopes:
                # Config only: the auxiliary chains never create or change a store entry.
                self._plan_auxiliary_fallback(profile, scopes["auxiliary"], confirmation_map.get((profile, "auxiliary")), base_plan,
                                              snapshots, writes, changes, auxiliary_expected, auxiliary_snapshots, auxiliary_provenance,
                                              auxiliary_snapshot_keys)
            store_scopes = {scope: desired for scope, desired in scopes.items() if scope != "auxiliary"}
            if not store_scopes:
                continue
            entry = after.setdefault(profile, self._fresh_profile_entry(profile, entries))
            for scope, desired in store_scopes.items():
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
            self._check_primary_routes(entry["routing"], entry["models"])
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

            "model_targets": list(base_plan["model_targets"]) if base_plan else [],
            "approved_models": copy.deepcopy(base_plan.get("approved_models", {})) if base_plan else {},
            "validation_profiles": list(base_plan.get("validation_profiles", [])) if base_plan else [],
            "native_expected": native_expected,
            "native_snapshots": native_snapshots,
            "native_provenance": native_provenance,
            "delegation_expected": delegation_expected,
            "delegation_snapshots": delegation_snapshots,
            "delegation_provenance": delegation_provenance,
            "auxiliary_expected": auxiliary_expected,
            "auxiliary_snapshots": auxiliary_snapshots,
            "auxiliary_provenance": auxiliary_provenance,
            "auxiliary_snapshot_keys": auxiliary_snapshot_keys,
            "state_changed": state_changed,
            "expires_epoch": expires_epoch,
            "timeout_writes": copy.deepcopy(base_plan.get("timeout_writes", [])) if base_plan else [],
            "page_expected": copy.deepcopy(base_plan.get("page_expected")) if base_plan else page_expected,
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
        for profile, expected_snapshot in auxiliary_snapshots.items():
            try:
                holds = self._auxiliary_cas_holds(profile, expected_snapshot, "cas_digest")
            except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                raise RevisionConflict("auxiliary fallback config changed during preview") from exc
            if not holds:
                raise RevisionConflict("auxiliary fallback config changed during preview")
        for item in plan["timeout_writes"]:
            self._check_timeout_write(item)
        plan["store_digest"] = store_digest
        if self._store_file_digest() != store_digest:
            raise RevisionConflict("settings changed during fallback preview; preview again")
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
            # An in-flight pre-upgrade plan may still promise a standalone skill copy.
            # Consume it once, but never silently apply a different write contract.
            if plan.get("skill_snapshots"):
                raise RevisionConflict("legacy skill-copy plan; reload settings and preview again")
            if time.time() > plan["expires_epoch"]:
                raise ServiceError("preview plan expired")
            current = self._load_store()
            revision = current["revision"] if current else 0
            if revision != plan["revision"]:
                raise RevisionConflict("settings revision changed; preview again")
            # Compare-and-set before anything is written: what the page saw must still hold.
            self._check_page_expectations(plan.get("page_expected"), dict((current or {}).get("profiles") or {}))
            if plan.get("kind") == "native_delegation":
                return native_service.apply_consumed(self, plan, plan_id)
            if plan.get("kind") == "initial_setup":
                return native_service.initial_setup_apply_consumed(self, plan, plan_id)
            # The plan's `after` replaces the whole store: refuse unless the store is byte-for-byte
            # the one preview computed it from, so no profile the save did not target is reverted.
            if plan.get("store_digest") is None or self._store_file_digest() != plan["store_digest"]:
                raise RevisionConflict("settings changed since preview; preview again")
            # The preview checked that every installed package can read slots; an older
            # package may have appeared since. Clearing all slots stays possible.
            after_slots = _stored_slots(plan.get("after") or {})
            current_slots = _stored_slots((current or {}).get("profiles") or {})
            # Only a plan that adds or changes some profile's slots is stopped; removing them never is.
            if any(after_slots[name] != current_slots.get(name) for name in after_slots):
                if self._slot_blocking_profiles(self._discover_profiles()):
                    raise RevisionConflict("task slots need every installed profile on this plugin version first; preview again")
            for item in plan.get("timeout_writes", []):
                self._check_timeout_write(item)
            for profile in set(plan["snapshots"]) | set(plan.get("validation_profiles", [])):
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
            for profile, expected_snapshot in plan.get("auxiliary_snapshots", {}).items():
                try:
                    holds = self._auxiliary_cas_holds(profile, expected_snapshot, "cas_digest")
                except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                    raise RevisionConflict("auxiliary fallback config changed since preview") from exc
                if not holds:
                    raise RevisionConflict("auxiliary fallback config changed since preview")

            if not plan["changes"]:
                for item in plan.get("timeout_writes", []):
                    self._check_timeout_write(item)
                receipt = {"status": "no_change", "plan_id": plan_id, "revision": revision, "applied": [], "remaining": [], "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            new_revision = revision + 1 if plan["state_changed"] else revision
            next_profiles = self._preserve_untouched_entries(plan["after"], (current or {}).get("profiles") or {}, plan["store_digest"])
            next_store = {"schema": _store_schema(plan["after"]), "revision": new_revision, "profiles": next_profiles}
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
                # Backups and validation ran since the check above; re-check right before replacing.
                # Only config backups exist at this point; no setting has been written.
                if self._store_file_digest() != plan["store_digest"]:
                    raise RevisionConflict("settings changed during apply; nothing was written; preview again")

                def store_unchanged() -> None:
                    # Again after the new payload is written and synced, immediately before the replace.
                    if self._store_file_digest() != plan["store_digest"]:
                        raise RevisionConflict("settings changed during apply; nothing was written; preview again")

                _atomic_write(self.store_path, _json_bytes(next_store), before_replace=store_unchanged)
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
                    if key in AUXILIARY_FALLBACK_KEYS.values() and profile in plan.get("auxiliary_provenance", {}):
                        try:
                            holds = self._auxiliary_cas_holds(profile, plan["auxiliary_provenance"][profile], "provenance_digest", key)
                        except (effective_config.EffectiveConfigUnavailable, effective_config.EffectiveConfigChanged) as exc:
                            raise RevisionConflict("auxiliary managed provenance changed during apply") from exc
                        if not holds:
                            raise RevisionConflict("auxiliary managed provenance changed during apply")
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
                    if set(item["after"]) == timeouts._LEGACY_TIMEOUT_FIELDS and not self._timeout_enforcement_available(item["profile"]):
                        raise RevisionConflict("timeout enforcement changed before final readback")
                    observed = timeouts.read_timeouts(self._profile_home(item["profile"]))
                    if observed["revision"] != item["expected_revision"] + 1 or any(observed[key] != value for key, value in item["after"].items()):
                        raise RevisionConflict("timeout settings differ from approved selection")
                approved_models = plan.get("approved_models") or {}
                for profile in plan.get("model_targets", []):
                    # A NOOP target may have no store entry (absent stays absent); it is verified
                    # against the approved values all the same.
                    expected_models = approved_models.get(profile)
                    if expected_models is None:
                        expected_models = (next_store["profiles"].get(profile) or {}).get("models")
                    if expected_models is None or self._actual_models(profile) != expected_models:
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
                for profile, tasks in plan.get("auxiliary_expected", {}).items():
                    # Read back the written keys only: a sibling task changed meanwhile is not this save's.
                    current = self._auxiliary_status(profile, tasks=tuple(tasks))
                    for task, expected_chain in tasks.items():
                        if current[task]["warnings"] or current[task]["actual_chain"] != expected_chain or current[task]["chain"] != expected_chain:
                            raise RevisionConflict("effective auxiliary fallback chain differs from approved selection")

            except Exception:
                receipt = {"status": "partial", "plan_id": plan_id, "revision": new_revision, "applied": applied,
                           "remaining": [{"profile": item["profile"], "key": item["key"]} for item in pending], "finished_at": _now()}
                self._store_apply(receipt)
                return receipt
            receipt = {"status": "applied", "plan_id": plan_id, "revision": new_revision, "applied": applied,
                       "remaining": [], "finished_at": _now()}
            self._store_apply(receipt)
            return receipt
