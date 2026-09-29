#!/usr/bin/env python3
"""Validate and atomically maintain the model-routing cache.

The canonical cache is JSON. Network research happens outside this script; a
candidate file is validated before the short compare-and-swap critical section.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = SKILL_ROOT / "references" / "model-routing-cache.json"
DEFAULT_SUMMARY = SKILL_ROOT / "references" / "model-routing-cache.md"
ROLES = {"LIGHTWEIGHT", "HEAVYWEIGHT", "GENERAL"}
CONFIDENCE = {"low", "medium", "high"}
STATUS = {"active", "deprecated", "unavailable"}
OPERATOR_ROUTE_ROLES = ("HEAVYWEIGHT", "LIGHTWEIGHT")
OPERATOR_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
OPERATOR_ROUTE_SOURCE = "desktop-model-switcher"
OPERATOR_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
OPERATOR_MODEL_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")
CREDENTIAL_FIELD_PARTS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "credential",
    "refresh_token",
    "access_token",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_operator_routes(routes: Any) -> None:
    """Validate the literal Heavy/Light operator route override contract."""

    _require(isinstance(routes, dict), "operator_routes must be an object")
    _require(
        set(routes) == set(OPERATOR_ROUTE_ROLES),
        "operator_routes must define exactly HEAVYWEIGHT and LIGHTWEIGHT",
    )
    pairs: dict[str, tuple[str, str]] = {}
    required_fields = {"provider", "model_id", "reasoning_effort"}
    for role in OPERATOR_ROUTE_ROLES:
        route = routes[role]
        _require(isinstance(route, dict), f"operator_routes.{role} must be an object")
        _require(
            set(route) == required_fields,
            f"operator_routes.{role} must define exactly provider, model_id, and reasoning_effort",
        )
        for field in ("provider", "model_id"):
            value = route[field]
            _require(isinstance(value, str) and bool(value), f"operator_routes.{role}.{field} must be a non-empty literal token")
            token_pattern = OPERATOR_MODEL_TOKEN if field == "model_id" else OPERATOR_TOKEN
            _require(
                value == value.strip() and value.casefold() != "keep" and token_pattern.fullmatch(value) is not None,
                f"operator_routes.{role}.{field} must be a safe literal token (KEEP and interpolation are forbidden)",
            )
        effort = route["reasoning_effort"]
        _require(
            isinstance(effort, str) and effort in OPERATOR_REASONING_EFFORTS,
            f"operator_routes.{role}.reasoning_effort must be one of {', '.join(sorted(OPERATOR_REASONING_EFFORTS))}",
        )
        pairs[role] = (route["provider"], route["model_id"])
    _require(
        pairs["HEAVYWEIGHT"] != pairs["LIGHTWEIGHT"],
        "HEAVYWEIGHT and LIGHTWEIGHT operator routes must not be identical",
    )


def _parse_iso(value: Any, field: str) -> None:
    _require(isinstance(value, str) and value.strip(), f"{field} must be a non-empty ISO timestamp")
    normalized = value.replace("Z", "+00:00")
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO timestamp") from exc
    _require(parsed.tzinfo is not None, f"{field} must include a timezone")


def _scan_for_credentials(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in CREDENTIAL_FIELD_PARTS or any(
                normalized.endswith("_" + part) for part in CREDENTIAL_FIELD_PARTS
            ):
                raise ValueError(f"credential-like field is forbidden at {path}.{key}")
            _scan_for_credentials(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_credentials(child, f"{path}[{index}]")


def _validate_source(source: Any, model_key: str, index: int) -> None:
    _require(isinstance(source, dict), f"{model_key} source {index} must be an object")
    for field in ("url", "kind", "checked_at"):
        _require(isinstance(source.get(field), str) and source[field].strip(), f"{model_key} source {index} missing {field}")
    parts = urlsplit(source["url"])
    _require(parts.scheme in {"http", "https"} and bool(parts.netloc), f"{model_key} source {index} must use http(s)")
    _require(parts.username is None and parts.password is None, f"{model_key} source {index} URL must not contain userinfo")
    _parse_iso(source["checked_at"], f"{model_key}.sources[{index}].checked_at")


def _validate_pricing(pricing: Any, model_key: str) -> None:
    _require(isinstance(pricing, dict), f"{model_key}.pricing must be an object")
    for field in ("currency", "unit", "notes"):
        _require(isinstance(pricing.get(field), str) and pricing[field].strip(), f"{model_key}.pricing missing {field}")
    for field in ("input", "cached_input", "output"):
        value = pricing.get(field)
        _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{model_key}.pricing.{field} must be numeric")
        _require(math.isfinite(float(value)) and float(value) >= 0, f"{model_key}.pricing.{field} must be finite and non-negative")


def validate_cache(data: Any) -> None:
    """Raise ValueError when cache data violates the v1 contract."""

    _require(isinstance(data, dict), "cache root must be an object")
    _scan_for_credentials(data)
    _require(data.get("schema_version") == 1, "schema_version must be 1")
    for field in ("generated_at", "fresh_until", "evidence_cutoff"):
        _parse_iso(data.get(field), field)

    routes = data.get("default_routes")
    _require(isinstance(routes, dict), "default_routes must be an object")
    _require("LIGHTWEIGHT" in routes and "HEAVYWEIGHT" in routes, "default_routes must define LIGHTWEIGHT and HEAVYWEIGHT")

    if "operator_routes" in data:
        validate_operator_routes(data["operator_routes"])
    if "operator_route_source" in data:
        _require("operator_routes" in data, "operator_route_source requires operator_routes")
        _require(
            data["operator_route_source"] == OPERATOR_ROUTE_SOURCE,
            f"operator_route_source must be {OPERATOR_ROUTE_SOURCE}",
        )

    models = data.get("models")
    _require(isinstance(models, list) and models, "models must be a non-empty array")
    seen_keys: set[str] = set()
    by_key: dict[str, dict[str, Any]] = {}
    for index, model in enumerate(models):
        _require(isinstance(model, dict), f"models[{index}] must be an object")
        for field in (
            "key",
            "provider",
            "model_id",
            "role",
            "status",
            "confidence",
            "coding_summary",
            "agentic_summary",
        ):
            _require(isinstance(model.get(field), str) and model[field].strip(), f"models[{index}] missing {field}")
        key = model["key"]
        _require(key not in seen_keys, f"duplicate model key: {key}")
        seen_keys.add(key)
        by_key[key] = model
        _require(model["role"] in ROLES, f"{key} has invalid role")
        _require(model["status"] in STATUS, f"{key} has invalid status")
        _require(model["confidence"] in CONFIDENCE, f"{key} has invalid confidence")
        _require(key == f"{model['provider']}/{model['model_id']}", f"{key} must equal provider/model_id")
        for numeric in ("context_window", "max_output_tokens"):
            value = model.get(numeric)
            _require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{key}.{numeric} must be a positive integer")
        efforts = model.get("reasoning_efforts")
        _require(isinstance(efforts, list) and all(isinstance(item, str) and item for item in efforts), f"{key}.reasoning_efforts must be a string array")
        _require(isinstance(model.get("tool_use"), bool), f"{key}.tool_use must be boolean")
        uses = model.get("recommended_use")
        _require(isinstance(uses, list) and all(isinstance(item, str) and item for item in uses), f"{key}.recommended_use must be a string array")
        _validate_pricing(model.get("pricing"), key)
        sources = model.get("sources")
        _require(isinstance(sources, list) and sources, f"{key}.sources must be non-empty")
        for source_index, source in enumerate(sources):
            _validate_source(source, key, source_index)

    for role, key in routes.items():
        _require(role in ROLES, f"default_routes has invalid role {role}")
        _require(isinstance(key, str) and key in by_key, f"default route {role} points to unknown model")
        _require(by_key[key]["status"] == "active", f"default route {role} must point to an active model")
        if role in {"LIGHTWEIGHT", "HEAVYWEIGHT"}:
            _require(by_key[key]["role"] == role, f"default route {role} points to a different role")

    deprecated = data.get("recently_deprecated")
    _require(isinstance(deprecated, list), "recently_deprecated must be an array")

    fallbacks = data.get("fallback_routes")
    if fallbacks is not None:
        _require(isinstance(fallbacks, dict), "fallback_routes must be an object")
        for role, key in fallbacks.items():
            _require(role in ROLES, f"fallback_routes has invalid role {role}")
            _require(
                isinstance(key, str) and key in by_key,
                f"fallback route {role} points to unknown model",
            )
            _require(
                by_key[key]["status"] == "active",
                f"fallback route {role} must point to an active model",
            )
            if role in {"LIGHTWEIGHT", "HEAVYWEIGHT"}:
                _require(
                    by_key[key]["role"] == role,
                    f"fallback route {role} points to a different role",
                )

    sets = data.get("candidate_sets")
    if sets is not None:
        _require(isinstance(sets, dict) and sets, "candidate_sets must be a non-empty object")
        for name, body in sets.items():
            _require(isinstance(name, str) and name.strip(), "candidate set names must be non-empty strings")
            _require(isinstance(body, dict), f"candidate set {name} must be an object")
            description = body.get("description")
            _require(
                isinstance(description, str) and description.strip(),
                f"candidate set {name} missing description",
            )
            set_routes = body.get("routes")
            _require(isinstance(set_routes, dict) and set_routes, f"candidate set {name} must declare routes")
            for role, key in set_routes.items():
                _require(role in ROLES, f"candidate set {name} has invalid role {role}")
                _require(
                    isinstance(key, str) and key in by_key,
                    f"candidate set {name}.{role} points to unknown model",
                )
                _require(
                    by_key[key]["status"] == "active",
                    f"candidate set {name}.{role} must point to an active model",
                )
                if role in {"LIGHTWEIGHT", "HEAVYWEIGHT"}:
                    _require(
                        by_key[key]["role"] == role,
                        f"candidate set {name}.{role} points to a different role",
                    )
        active = data.get("active_set")
        if active is not None:
            _require(
                isinstance(active, str) and active in sets,
                "active_set must name a declared candidate set",
            )
            _require(isinstance(fallbacks, dict), "active_set requires fallback_routes")
            _require(
                dict(fallbacks) == dict(sets[active]["routes"]),
                "fallback_routes must mirror the active candidate set",
            )
    subscription = data.get("subscription_routes")
    if subscription is not None:
        _require(isinstance(subscription, dict), "subscription_routes must be an object")
        _require(
            "LIGHTWEIGHT" in subscription and "HEAVYWEIGHT" in subscription,
            "subscription_routes must define LIGHTWEIGHT and HEAVYWEIGHT",
        )
        for role, key in subscription.items():
            _require(role in ROLES, f"subscription_routes has invalid role {role}")
            _require(
                isinstance(key, str) and key in by_key,
                f"subscription_routes.{role} points to unknown model",
            )
            _require(
                by_key[key]["status"] == "active",
                f"subscription_routes.{role} must point to an active model",
            )
            if role in {"LIGHTWEIGHT", "HEAVYWEIGHT"}:
                _require(
                    by_key[key]["role"] == role,
                    f"subscription_routes.{role} points to a different role",
                )


def _load_cache_snapshot(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read cache {path}: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read cache {path}: {exc}") from exc
    validate_cache(data)
    return raw, data


def load_cache(path: Path) -> dict[str, Any]:
    return _load_cache_snapshot(path)[1]


def canonical_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def file_digest(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_markdown(data: dict[str, Any]) -> str:
    models = {model["key"]: model for model in data["models"]}
    lines = [
        "# Model Routing Cache",
        "",
        "> `model-routing-cache.json is authoritative`; this file is generated for fast human/LLM review.",
        "",
        f"- Generated: `{data['generated_at']}`",
        f"- Fresh until: `{data['fresh_until']}`",
        f"- Evidence cutoff: `{data['evidence_cutoff']}`",
        "",
    ]
    operator_routes = data.get("operator_routes")
    if isinstance(operator_routes, dict):
        lines.extend(
            [
                "## Applied operator routes",
                "",
                "> Operator intent only; this is not verified capability or pricing metadata.",
                "",
            ]
        )
        source = data.get("operator_route_source")
        if isinstance(source, str):
            lines.extend([f"- Source: `{source}`", ""])
        lines.extend(
            [
                "| Route | Provider | Model ID | Reasoning effort |",
                "|---|---|---|---|",
            ]
        )
        for role in OPERATOR_ROUTE_ROLES:
            route = operator_routes[role]
            lines.append(
                f"| `{role}` | `{route['provider']}` | `{route['model_id']}` | `{route['reasoning_effort']}` |"
            )
        lines.extend(["", "## Research default routes", ""])
    lines.extend(
        [
            "| Route | Provider | Model ID | Confidence | Standard input / cached / output per 1M |",
            "|---|---|---|---|---|",
        ]
    )
    for role in ("LIGHTWEIGHT", "HEAVYWEIGHT", "GENERAL"):
        key = data["default_routes"].get(role)
        if not key:
            continue
        model = models[key]
        pricing = model["pricing"]
        price = f"{pricing['currency']} {pricing['input']:g} / {pricing['cached_input']:g} / {pricing['output']:g}"
        lines.append(f"| `{role}` | `{model['provider']}` | `{model['model_id']}` | {model['confidence']} | {price} |")
    fallbacks = data.get("fallback_routes")
    if isinstance(fallbacks, dict) and fallbacks:
        lines.extend(
            [
                "",
                "## Subscription-exhaustion fallback",
                "",
                "When a subscription lane reports a usage-limit exhaustion, the routed-process adapter continues once on the declared fallback route and records it in the artifact. Other failure types do not trigger a fallback.",
                "",
                "| Route | Fallback provider | Fallback model ID |",
                "|---|---|---|",
            ]
        )
        for role in ("LIGHTWEIGHT", "HEAVYWEIGHT", "GENERAL"):
            key = fallbacks.get(role)
            if not key:
                continue
            model = models[key]
            lines.append(f"| `{role}` | `{model['provider']}` | `{model['model_id']}` |")
    sets = data.get("candidate_sets")
    if isinstance(sets, dict) and sets:
        active = data.get("active_set")
        lines.extend(["", "## Candidate sets", ""])
        rule = data.get("set_selection_rule")
        if isinstance(rule, str) and rule.strip():
            lines.extend([rule, ""])
        for name, body in sets.items():
            marker = " (active)" if name == active else ""
            lines.extend([f"### Set `{name}`{marker}", ""])
            description = body.get("description")
            if isinstance(description, str) and description.strip():
                lines.extend([description, ""])
            set_routes = body.get("routes") or {}
            lines.extend(["| Route | Provider | Model ID |", "|---|---|---|"])
            for role in ("LIGHTWEIGHT", "HEAVYWEIGHT", "GENERAL"):
                key = set_routes.get(role)
                if not key:
                    continue
                model = models[key]
                lines.append(f"| `{role}` | `{model['provider']}` | `{model['model_id']}` |")
            lines.append("")
    lines.extend(["", "## Active assessments", ""])
    for model in data["models"]:
        if model["status"] != "active":
            continue
        lines.extend(
            [
                f"### `{model['key']}` — {model['role']}",
                "",
                f"- Coding: {model['coding_summary']}",
                f"- Agent/tool use: {model['agentic_summary']}",
                f"- Context/output: {model['context_window']:,} / {model['max_output_tokens']:,} tokens",
                f"- Reasoning efforts: {', '.join(model['reasoning_efforts'])}",
                f"- Recommended: {', '.join(model['recommended_use'])}",
                f"- Pricing note: {model['pricing']['notes']}",
                "- Evidence:",
            ]
        )
        for source in model["sources"]:
            lines.append(f"  - [{source['kind']}]({source['url']}) — checked `{source['checked_at']}`")
        lines.append("")
    lines.extend(
        [
            "## Refresh triggers",
            "",
            "Refresh when this cache expires, the configured provider/model changes, a route disappears or is deprecated, a declared fallback route becomes unusable, an unknown model becomes material to a non-trivial task, or the user requests a current reassessment. Do not refresh for every small coding task.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
        if os.name != "nt":
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _pid_state(pid: int) -> str:
    if pid <= 0:
        return "unknown"
    if pid == os.getpid():
        return "live"
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return "live"
        error = ctypes.windll.kernel32.GetLastError()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID does not exist.
            return "dead"
        return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "live"
    except OSError:
        return "unknown"
    return "live"


class CacheLock:
    def __init__(self, path: Path, timeout: float, stale_after: float = 300.0):
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self.token = secrets.token_hex(16)

    def _break_if_proven_stale(self) -> bool:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            pid = raw.get("pid")
            created = raw.get("created_epoch")
            if not isinstance(pid, int) or isinstance(pid, bool):
                return False
            if not isinstance(created, (int, float)) or isinstance(created, bool):
                return False
            if time.time() - float(created) <= self.stale_after:
                return False
            if _pid_state(pid) != "dead":
                return False
            self.path.unlink()
            return True
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        metadata = json.dumps(
            {"pid": os.getpid(), "created_epoch": time.time(), "token": self.token},
            separators=(",", ":"),
        ).encode("utf-8")
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, metadata)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return self
            except FileExistsError:
                if self._break_if_proven_stale():
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out acquiring cache lock {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("token") == self.token:
                self.path.unlink()
        except (OSError, ValueError, json.JSONDecodeError):
            pass


def commit_cache(
    *,
    cache_path: Path,
    summary_path: Path,
    candidate_path: Path,
    expected_digest: str,
    lock_timeout: float,
) -> str:
    candidate = load_cache(candidate_path)
    lock_path = cache_path.with_name(f".{cache_path.name}.lock")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with CacheLock(lock_path, timeout=lock_timeout):
        current_digest = file_digest(cache_path)
        if current_digest != expected_digest:
            raise RuntimeError(
                f"digest mismatch: expected {expected_digest}, found {current_digest}; reread and merge before retrying"
            )
        _atomic_write(cache_path, canonical_json(candidate))
        try:
            _atomic_write(summary_path, render_markdown(candidate).encode("utf-8"))
        except OSError as exc:
            raise RuntimeError(
                f"partial apply: cache JSON committed but summary update failed: {exc}; "
                f'run render --cache "{cache_path}" --summary "{summary_path}" to repair'
            ) from exc
        return file_digest(cache_path)


def _write_candidate_temp(cache_path: Path, payload: bytes) -> Path:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(cache_path.parent),
            prefix=f".{cache_path.name}.routing-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return Path(temp_name)
    except BaseException:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        raise


def _remove_candidate_temp(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _apply_candidate_set(data: dict[str, Any], set_name: str, primary: str) -> None:
    sets = data.get("candidate_sets") or {}
    if set_name not in sets:
        raise ValueError(f"unknown candidate set: {set_name}")
    if primary not in {"set", "subscription"}:
        raise ValueError(f"unsupported primary: {primary}")
    set_routes = dict(sets[set_name]["routes"])
    subscription_routes = dict(data.get("subscription_routes") or {})
    if primary == "subscription" and not subscription_routes:
        raise ValueError("subscription_routes is not declared in the cache")

    data["active_set"] = set_name
    data["fallback_routes"] = set_routes
    default_routes = dict(data.get("default_routes") or {})
    for role in set_routes:
        if primary == "set":
            default_routes[role] = set_routes[role]
        elif role not in subscription_routes:
            raise ValueError(f"subscription_routes has no {role} entry")
        else:
            default_routes[role] = subscription_routes[role]
    if primary == "subscription":
        default_routes.update(subscription_routes)
    data["default_routes"] = default_routes


def sync_model_routes(
    *,
    cache_path: Path,
    summary_path: Path,
    routes: dict[str, Any],
    set_name: str,
    primary: str,
    dry_run: bool = False,
    lock_timeout: float = 10.0,
) -> dict[str, Any]:
    """Select an existing candidate set and atomically install literal operator routes."""

    validate_operator_routes(routes)
    original_bytes, original = _load_cache_snapshot(cache_path)
    expected_digest = hashlib.sha256(original_bytes).hexdigest()
    candidate = json.loads(json.dumps(original))
    _apply_candidate_set(candidate, set_name, primary)
    candidate["operator_routes"] = {
        role: {
            "provider": routes[role]["provider"],
            "model_id": routes[role]["model_id"],
            "reasoning_effort": routes[role]["reasoning_effort"],
        }
        for role in OPERATOR_ROUTE_ROLES
    }
    candidate["operator_route_source"] = OPERATOR_ROUTE_SOURCE
    validate_cache(candidate)
    changed = canonical_json(candidate) != canonical_json(original)
    result: dict[str, Any] = {
        "changed": changed,
        "dry_run": dry_run,
        "active_set": set_name,
        "primary": primary,
        "operator_routes": candidate["operator_routes"],
        "fallback_routes": candidate["fallback_routes"],
    }
    if dry_run or not changed:
        if not dry_run:
            try:
                summary_current = summary_path.read_text(encoding="utf-8") == render_markdown(candidate)
            except OSError:
                summary_current = False
            if not summary_current:
                raise RuntimeError(
                    "cache JSON already matches, but summary is missing/stale/unreadable; "
                    f'run render --cache "{cache_path}" --summary "{summary_path}" to repair'
                )
        result["digest"] = expected_digest
        return result

    candidate_path = _write_candidate_temp(cache_path, canonical_json(candidate))
    try:
        result["digest"] = commit_cache(
            cache_path=cache_path,
            summary_path=summary_path,
            candidate_path=candidate_path,
            expected_digest=expected_digest,
            lock_timeout=lock_timeout,
        )
    finally:
        _remove_candidate_temp(candidate_path)
    return result


def switch_active_set(
    *,
    cache_path: Path,
    summary_path: Path,
    set_name: str,
    primary: str,
    lock_timeout: float = 10.0,
) -> dict[str, Any]:
    """Switch ``active_set`` and every route map that mirrors it in one CAS edit.

    ``primary='set'`` points ``default_routes`` at the chosen set's own routes (work runs on
    that family directly). ``primary='subscription'`` points them at ``subscription_routes``
    (free lane first) while the set stays the declared fallback. Roles a set does not declare
    (GENERAL) are left alone under ``'set'`` and follow ``subscription_routes`` under
    ``'subscription'``. Idempotent: a cache that already matches is not rewritten, so the
    model-switcher script is safe to run twice.
    """
    original_bytes, data = _load_cache_snapshot(cache_path)
    if data.get("operator_routes"):
        raise ValueError("operator routes are applied; use sync-models to change candidate set or primary")
    expected_digest = hashlib.sha256(original_bytes).hexdigest()
    new = json.loads(json.dumps(data))
    _apply_candidate_set(new, set_name, primary)
    validate_cache(new)

    if canonical_json(new) == canonical_json(data):
        return {
            "changed": False,
            "active_set": set_name,
            "primary": primary,
            "digest": expected_digest,
        }

    candidate_path = _write_candidate_temp(cache_path, canonical_json(new))
    try:
        digest = commit_cache(
            cache_path=cache_path,
            summary_path=summary_path,
            candidate_path=candidate_path,
            expected_digest=expected_digest,
            lock_timeout=lock_timeout,
        )
    finally:
        _remove_candidate_temp(candidate_path)
    return {
        "changed": True,
        "active_set": set_name,
        "primary": primary,
        "default_routes": new["default_routes"],
        "fallback_routes": new["fallback_routes"],
        "digest": digest,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("validate", "show", "digest", "prepare"):
        item = sub.add_parser(name)
        item.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
        if name == "prepare":
            item.add_argument("--output", type=Path, required=True)

    render = sub.add_parser("render")
    render.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    render.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    render.add_argument("--check", action="store_true")

    commit = sub.add_parser("commit")
    commit.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    commit.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    commit.add_argument("--candidate", type=Path, required=True)
    commit.add_argument("--expected-digest", required=True)
    commit.add_argument("--lock-timeout", type=float, default=10.0)

    set_active = sub.add_parser("set-active")
    set_active.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    set_active.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    set_active.add_argument("--set", dest="set_name", required=True)
    set_active.add_argument("--primary", choices=("set", "subscription"), default="set")
    set_active.add_argument("--lock-timeout", type=float, default=10.0)

    sync = sub.add_parser("sync-models")
    sync.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    sync.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    sync.add_argument("--heavy-provider", required=True)
    sync.add_argument("--heavy-model", required=True)
    sync.add_argument("--heavy-reasoning", required=True)
    sync.add_argument("--light-provider", required=True)
    sync.add_argument("--light-model", required=True)
    sync.add_argument("--light-reasoning", required=True)
    sync.add_argument("--set", dest="set_name", required=True)
    sync.add_argument("--primary", choices=("set", "subscription"), default="set")
    sync.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            data = load_cache(args.cache)
            print(json.dumps({"valid": True, "models": len(data["models"]), "fresh_until": data["fresh_until"]}))
        elif args.command == "show":
            data = load_cache(args.cache)
            models = {model["key"]: model for model in data["models"]}
            routes = {
                role: {
                    "provider": models[key]["provider"],
                    "model_id": models[key]["model_id"],
                    "status": models[key]["status"],
                }
                for role, key in data["default_routes"].items()
            }
            shown: dict[str, Any] = {"fresh_until": data["fresh_until"]}
            if "operator_routes" in data:
                shown["operator_routes"] = data["operator_routes"]
                if "operator_route_source" in data:
                    shown["operator_route_source"] = data["operator_route_source"]
            shown["routes"] = {
                **routes,
                **{
                    role: {**route, "status": "operator_selected"}
                    for role, route in data.get("operator_routes", {}).items()
                },
            }
            if "operator_routes" in data:
                shown["research_routes"] = routes
            print(json.dumps(shown, indent=2, ensure_ascii=False))
        elif args.command == "digest":
            print(file_digest(args.cache))
        elif args.command == "prepare":
            data = load_cache(args.cache)
            _atomic_write(args.output, canonical_json(data))
            print(json.dumps({"candidate": str(args.output), "base_digest": file_digest(args.cache)}))
        elif args.command == "render":
            data = load_cache(args.cache)
            rendered = render_markdown(data)
            if args.check:
                current = args.summary.read_text(encoding="utf-8") if args.summary.exists() else ""
                if current != rendered:
                    raise RuntimeError("rendered summary is stale")
                print(json.dumps({"summary_current": True, "path": str(args.summary)}))
            else:
                _atomic_write(args.summary, rendered.encode("utf-8"))
                print(json.dumps({"rendered": str(args.summary)}))
        elif args.command == "commit":
            digest = commit_cache(
                cache_path=args.cache,
                summary_path=args.summary,
                candidate_path=args.candidate,
                expected_digest=args.expected_digest,
                lock_timeout=args.lock_timeout,
            )
            print(json.dumps({"committed": True, "digest": digest}))
        elif args.command == "set-active":
            result = switch_active_set(
                cache_path=args.cache,
                summary_path=args.summary,
                set_name=args.set_name,
                primary=args.primary,
                lock_timeout=args.lock_timeout,
            )
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "sync-models":
            result = sync_model_routes(
                cache_path=args.cache,
                summary_path=args.summary,
                routes={
                    "HEAVYWEIGHT": {
                        "provider": args.heavy_provider,
                        "model_id": args.heavy_model,
                        "reasoning_effort": args.heavy_reasoning,
                    },
                    "LIGHTWEIGHT": {
                        "provider": args.light_provider,
                        "model_id": args.light_model,
                        "reasoning_effort": args.light_reasoning,
                    },
                },
                set_name=args.set_name,
                primary=args.primary,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
        print(f"routing_cache: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
