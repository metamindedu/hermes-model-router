"""Pure validation and consent primitives for native delegation settings.

No filesystem access, provider calls, configuration writes, or legacy fallback
consent. Callers must separately prove profile inventory and plugin readiness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

AUTO_ROUTING_SUPPORTED = True
SCHEMA = 1
BACKENDS = frozenset({"default", "model-router", "model-router-profiles", "model-router-auto"})
KEY_BACKEND = "delegation.backend"
KEY_POLICY = "delegation.backends.model-router"
KEY_PROFILES = "delegation.backends.model-router-profiles"
KEY_AUTO_POLICY = "delegation.backends.model-router-auto"
KEYS = (KEY_BACKEND, KEY_POLICY, KEY_PROFILES, KEY_AUTO_POLICY)
ROLES = ("heavy", "light")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_PROVIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")


def _literal(value: Any, pattern: re.Pattern, label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None or value.casefold() == "keep":
        raise ValueError(f"invalid {label}")
    return value


def validate_policy(value: Any) -> dict[str, Any]:
    """Validate the client policy (which must never include consent)."""
    if not isinstance(value, dict) or set(value) != set(ROLES):
        raise ValueError("policy must contain heavy and light")
    result = {}
    for role in ROLES:
        item = value[role]
        if not isinstance(item, dict) or set(item) != {"mode", "chain"}:
            raise ValueError("invalid role policy")
        mode, chain = item["mode"], item["chain"]
        if mode not in ("off", "custom") or not isinstance(chain, list):
            raise ValueError("invalid fallback mode or chain")
        if (mode == "off" and chain) or (mode == "custom" and not 1 <= len(chain) <= 5):
            raise ValueError("invalid fallback chain length")
        parsed = []
        identities = set()
        for route in chain:
            if not isinstance(route, dict) or set(route) != {"provider", "model"}:
                raise ValueError("invalid fallback route")
            provider = _literal(route["provider"], _PROVIDER, "provider")
            model = _literal(route["model"], _MODEL, "model")
            if "://" in model:
                raise ValueError("invalid model")
            identity = (provider, model)
            if identity in identities:
                raise ValueError("duplicate fallback route")
            identities.add(identity)
            parsed.append({"provider": provider, "model": model})
        result[role] = {"mode": mode, "chain": parsed}
    return result


def validate_profiles(value: Any, inventory: set[str] | list[str]) -> dict[str, Any]:
    """Validate exact profile names against a caller-proven, unlinked inventory."""
    if not isinstance(value, dict) or set(value) != {"profiles", "default"} or not isinstance(value["profiles"], list):
        raise ValueError("invalid profile routes")
    available = set(inventory)
    names = set()
    result = []
    for item in value["profiles"]:
        if not isinstance(item, dict) or set(item) != {"name", "description"}:
            raise ValueError("invalid profile route")
        name = _literal(item["name"], _PROFILE, "profile")
        description = item["description"]
        if name not in available or name in names:
            raise ValueError("profile is missing or duplicated")
        if not isinstance(description, str) or len(description) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in description):
            raise ValueError("invalid profile description")
        names.add(name)
        result.append({"name": name, "description": description})
    default = value["default"]
    if default is not None and (not isinstance(default, str) or default not in names):
        raise ValueError("default must be an allowlisted profile")
    return {"profiles": result, "default": default}


def make_consent(profile: str, backend: str, role: str, chain: list[dict[str, str]]) -> dict[str, Any]:
    """Bind approval to native within-child continuation, never legacy reruns."""
    _literal(profile, _PROFILE, "profile")
    if backend not in ("model-router", "model-router-auto") or role not in ROLES:
        raise ValueError("invalid consent scope")
    policy = {r: {"mode": "custom" if r == role else "off", "chain": chain if r == role else []} for r in ROLES}
    chain = validate_policy(policy)[role]["chain"]
    binding = {"schema": 1, "backend": backend, "origin_profile": profile, "role": role,
               "mode": "custom", "chain": chain, "execution": "continue_conversation",
               "trigger": "hermes_runtime", "additional_cost": True}
    encoded = json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"schema": 1, "digest": hashlib.sha256(encoded).hexdigest(),
            "execution": "continue_conversation", "additional_cost": True}


def consent_matches(profile: str, backend: str, role: str, chain: list[dict[str, str]], consent: Any) -> bool:
    try:
        return (isinstance(consent, dict) and type(consent.get("schema")) is int
                and consent.get("additional_cost") is True
                and consent == make_consent(profile, backend, role, chain))
    except (ValueError, TypeError):
        return False


def default_policy() -> dict[str, Any]:
    return {role: {"mode": "off", "chain": []} for role in ROLES}


def build_policy_block(profile: str, policy: Any, allow_additional_cost: bool, *, backend: str = "model-router") -> dict[str, Any]:
    """Construct a whole owned block; a custom policy always requires fresh consent."""
    if not isinstance(allow_additional_cost, bool):
        raise ValueError("cost confirmation must be boolean")
    parsed = validate_policy(policy)
    entries = {}
    for role, item in parsed.items():
        if item["mode"] == "custom" and not allow_additional_cost:
            raise ValueError("custom continuation requires explicit additional-cost confirmation")
        entries[role] = {**copy.deepcopy(item), "consent": make_consent(profile, backend, role, item["chain"]) if item["mode"] == "custom" else None}
    return {"schema": SCHEMA, "fallbacks": entries}


def validate_policy_block(profile: str, block: Any, *, backend: str = "model-router") -> dict[str, Any]:
    """Validate the final persisted block and its profile-bound consent."""
    if not isinstance(block, dict) or set(block) != {"schema", "fallbacks"} or type(block["schema"]) is not int or block["schema"] != SCHEMA:
        raise ValueError("invalid native policy block")
    fallbacks = block["fallbacks"]
    if not isinstance(fallbacks, dict) or set(fallbacks) != set(ROLES):
        raise ValueError("invalid native policy block")
    plain = {}
    for role in ROLES:
        item = fallbacks[role]
        if not isinstance(item, dict) or set(item) != {"mode", "chain", "consent"}:
            raise ValueError("invalid native policy entry")
        plain[role] = {"mode": item["mode"], "chain": item["chain"]}
    parsed = validate_policy(plain)
    for role in ROLES:
        item = fallbacks[role]
        if parsed[role]["mode"] == "off":
            if item["consent"] is not None:
                raise ValueError("off policy cannot carry consent")
        elif not consent_matches(profile, backend, role, parsed[role]["chain"], item["consent"]):
            raise ValueError("invalid native continuation consent")
    return parsed


def validate_profiles_block(block: Any, inventory: set[str] | list[str]) -> dict[str, Any]:
    if not isinstance(block, dict) or set(block) != {"schema", "profiles", "default"} or type(block["schema"]) is not int or block["schema"] != SCHEMA:
        raise ValueError("invalid native profiles block")
    return validate_profiles({"profiles": block["profiles"], "default": block["default"]}, inventory)
