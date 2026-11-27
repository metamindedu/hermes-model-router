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

from .slots import BUILTIN_SLOTS, SLOT_TIERS, complete_slot_keys

AUTO_ROUTING_SUPPORTED = True
SCHEMA = 1
# Per-slot continuation block. A schema-1 block keeps its two roles until an
# operator saves a slot-shaped policy; it is never rewritten on read.
SLOT_SCHEMA = 2
BACKENDS = frozenset({"default", "model-router", "model-router-profiles", "model-router-auto"})
KEY_BACKEND = "delegation.backend"
KEY_POLICY = "delegation.backends.model-router"
KEY_PROFILES = "delegation.backends.model-router-profiles"
KEY_AUTO_POLICY = "delegation.backends.model-router-auto"
KEYS = (KEY_BACKEND, KEY_POLICY, KEY_PROFILES, KEY_AUTO_POLICY)
ROLES = ("heavy", "light")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_PROVIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*(?:\[[A-Za-z0-9._-]{1,32}\])?\Z")


def _literal(value: Any, pattern: re.Pattern, label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None or value.casefold() == "keep":
        raise ValueError(f"invalid {label}")
    return value


def validate_policy(value: Any, keys: tuple[str, ...] = ROLES) -> dict[str, Any]:
    """Validate the client policy (which must never include consent)."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("policy must contain heavy and light" if keys == ROLES else "policy must contain every task slot")
    result = {}
    for role in keys:
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


def make_slot_consent(profile: str, backend: str, slot: str, chain: list[dict[str, str]]) -> dict[str, Any]:
    """Slot-bound approval. Never equal to a role consent, so neither can stand in for the other."""
    _literal(profile, _PROFILE, "profile")
    if backend not in ("model-router", "model-router-auto") or slot not in BUILTIN_SLOTS:
        raise ValueError("invalid consent scope")
    policy = {s: {"mode": "custom" if s == slot else "off", "chain": chain if s == slot else []} for s in BUILTIN_SLOTS}
    chain = validate_policy(policy, BUILTIN_SLOTS)[slot]["chain"]
    binding = {"schema": SLOT_SCHEMA, "backend": backend, "origin_profile": profile, "slot": slot,
               "mode": "custom", "chain": chain, "execution": "continue_conversation",
               "trigger": "hermes_runtime", "additional_cost": True}
    encoded = json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"schema": SLOT_SCHEMA, "digest": hashlib.sha256(encoded).hexdigest(),
            "execution": "continue_conversation", "additional_cost": True}


def slot_consent_matches(profile: str, backend: str, slot: str, chain: list[dict[str, str]], consent: Any) -> bool:
    try:
        return (isinstance(consent, dict) and type(consent.get("schema")) is int
                and consent.get("additional_cost") is True
                and consent == make_slot_consent(profile, backend, slot, chain))
    except (ValueError, TypeError):
        return False


def default_policy() -> dict[str, Any]:
    return {role: {"mode": "off", "chain": []} for role in ROLES}


def _off_entry(_slot: str) -> dict[str, Any]:
    return {"mode": "off", "chain": [], "consent": None}


def default_slot_policy() -> dict[str, Any]:
    return {slot: {"mode": "off", "chain": []} for slot in BUILTIN_SLOTS}


def expand_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """A two-role policy shown per slot: each slot continues as its tier does."""
    return {slot: copy.deepcopy(policy[SLOT_TIERS[slot]]) for slot in BUILTIN_SLOTS}


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


def build_slot_policy_block(profile: str, policy: Any, allow_additional_cost: bool, *, backend: str = "model-router") -> dict[str, Any]:
    """Construct a whole owned per-slot block; a custom slot always requires fresh consent."""
    if not isinstance(allow_additional_cost, bool):
        raise ValueError("cost confirmation must be boolean")
    parsed = validate_policy(policy, BUILTIN_SLOTS)
    entries = {}
    for slot, item in parsed.items():
        if item["mode"] == "custom" and not allow_additional_cost:
            raise ValueError("custom continuation requires explicit additional-cost confirmation")
        entries[slot] = {**copy.deepcopy(item), "consent": make_slot_consent(profile, backend, slot, item["chain"]) if item["mode"] == "custom" else None}
    return {"schema": SLOT_SCHEMA, "fallbacks": entries}


def validate_slot_policy_block(profile: str, block: Any, *, backend: str = "model-router") -> dict[str, Any]:
    """Validate a persisted per-slot block and its slot-bound consent."""
    if not isinstance(block, dict) or set(block) != {"schema", "fallbacks"} or type(block["schema"]) is not int or block["schema"] != SLOT_SCHEMA:
        raise ValueError("invalid native policy block")
    try:
        # A block saved before a slot existed leaves that slot off.
        fallbacks = complete_slot_keys(block["fallbacks"], _off_entry)
    except ValueError:
        raise ValueError("invalid native policy block") from None
    plain = {}
    for slot in BUILTIN_SLOTS:
        item = fallbacks[slot]
        if not isinstance(item, dict) or set(item) != {"mode", "chain", "consent"}:
            raise ValueError("invalid native policy entry")
        plain[slot] = {"mode": item["mode"], "chain": item["chain"]}
    parsed = validate_policy(plain, BUILTIN_SLOTS)
    for slot in BUILTIN_SLOTS:
        item = fallbacks[slot]
        if parsed[slot]["mode"] == "off":
            if item["consent"] is not None:
                raise ValueError("off policy cannot carry consent")
        elif not slot_consent_matches(profile, backend, slot, parsed[slot]["chain"], item["consent"]):
            raise ValueError("invalid native continuation consent")
    return parsed


def patch_slot_policy_block(profile: str, stored: Any, patch: Any, allow_additional_cost: bool, *, backend: str = "model-router") -> dict[str, Any]:
    """Merge the submitted slots of a partial save into the stored per-slot block.

    Every slot the patch leaves out keeps its stored entry exactly, consent included. A submitted
    custom slot gets fresh slot-bound consent, an off one none. Nothing stored: the base is the
    all-off block. A stored two-role block is refused: its consent is bound to the roles and is never
    re-bound to slots silently (the whole block is replaced only by an explicit full slot policy).
    """
    if not isinstance(allow_additional_cost, bool):
        raise ValueError("cost confirmation must be boolean")
    if not isinstance(patch, dict) or not patch or any(not isinstance(key, str) for key in patch) or set(patch) - set(BUILTIN_SLOTS):
        raise ValueError("slot policy patch must name one or more known task slots")
    schema = block_schema(stored)
    if schema == SCHEMA:
        raise ValueError("spare models are stored per role on this profile; a per-slot patch cannot replace them")
    if schema == 0:
        base = build_slot_policy_block(profile, default_slot_policy(), False, backend=backend)
    else:
        validate_slot_policy_block(profile, stored, backend=backend)
        base = copy.deepcopy(stored)
        base["fallbacks"] = complete_slot_keys(base["fallbacks"], _off_entry)
    plain = {slot: {"mode": base["fallbacks"][slot]["mode"], "chain": base["fallbacks"][slot]["chain"]} for slot in BUILTIN_SLOTS}
    plain.update({slot: patch[slot] for slot in patch})
    parsed = validate_policy(plain, BUILTIN_SLOTS)
    custom = any(parsed[slot]["mode"] == "custom" for slot in patch)
    if custom and not allow_additional_cost:
        raise ValueError("custom continuation requires explicit additional-cost confirmation")
    if allow_additional_cost and not custom:
        raise ValueError("cost confirmation applies only to submitted slots that continue on spare models")
    fallbacks = {}
    for slot in base["fallbacks"]:
        if slot not in patch:
            fallbacks[slot] = copy.deepcopy(base["fallbacks"][slot])
            continue
        item = parsed[slot]
        fallbacks[slot] = {**copy.deepcopy(item), "consent": make_slot_consent(profile, backend, slot, item["chain"]) if item["mode"] == "custom" else None}
    block = {"schema": SLOT_SCHEMA, "fallbacks": fallbacks}
    validate_slot_policy_block(profile, block, backend=backend)
    return block


def merge_profile_routes(stored: dict[str, Any], patch: Any) -> dict[str, Any]:
    """Apply a partial save's allow-list patch to one target's stored routes (unvalidated result).

    Order: remove, then add (a name already present keeps its entry), then descriptions for names
    present after the merge (others ignored), then `default` when submitted. Without a submitted
    default the stored one is kept while it stays in the list. Callers validate the result exactly
    like a submitted full list (validate_profiles) and decide consent on it.
    """
    if not isinstance(patch, dict) or not patch or set(patch) - {"add", "remove", "descriptions", "default"}:
        raise ValueError("invalid profile routes patch")
    add, remove, descriptions = patch.get("add", []), patch.get("remove", []), patch.get("descriptions", {})
    if (not isinstance(add, list) or len(add) > 64 or
            any(not isinstance(item, dict) or set(item) != {"name", "description"} or not isinstance(item["name"], str)
                or not isinstance(item["description"], str) for item in add)):
        raise ValueError("invalid profile routes patch")
    if not isinstance(remove, list) or len(remove) > 64 or any(not isinstance(name, str) for name in remove):
        raise ValueError("invalid profile routes patch")
    if (not isinstance(descriptions, dict) or len(descriptions) > 64 or
            any(not isinstance(name, str) or not isinstance(text, str) for name, text in descriptions.items())):
        raise ValueError("invalid profile routes patch")
    added = [item["name"] for item in add]
    if len(set(added)) != len(added) or len(set(remove)) != len(remove):
        raise ValueError("profile routes patch names a profile twice")
    if "default" in patch and patch["default"] is not None and not isinstance(patch["default"], str):
        raise ValueError("invalid profile routes patch")
    if not add and not remove and not descriptions and "default" not in patch:
        raise ValueError("profile routes patch changes nothing")
    removed = set(remove)
    rows = [dict(row) for row in stored["profiles"] if row["name"] not in removed]
    present = {row["name"] for row in rows}
    for item in add:
        if item["name"] not in present:
            rows.append({"name": item["name"], "description": item["description"]})
            present.add(item["name"])
    for row in rows:
        if row["name"] in descriptions:
            row["description"] = descriptions[row["name"]]
    if "default" in patch:
        default = patch["default"]
    else:
        default = stored["default"] if stored["default"] in present else None
    return {"profiles": rows, "default": default}


def block_schema(block: Any) -> int:
    """0 when nothing is stored; otherwise the stored block's own schema (unvalidated)."""
    if block is None:
        return 0
    schema = block.get("schema") if isinstance(block, dict) else None
    if type(schema) is not int or schema not in (SCHEMA, SLOT_SCHEMA):
        raise ValueError("invalid native policy block")
    return schema


def read_policy(profile: str, block: Any, *, backend: str = "model-router") -> dict[str, Any]:
    """Validate a stored block of either schema and show it both ways.

    ``policy`` is the two-role view an older client edits; a per-slot block has
    no such view and reports the all-off default there. ``slot_policy`` is what
    actually applies to each slot.
    """
    schema = block_schema(block)
    if schema == 0:
        return {"schema": 0, "policy": default_policy(), "slot_policy": default_slot_policy()}
    if schema == SCHEMA:
        policy = validate_policy_block(profile, block, backend=backend)
        return {"schema": SCHEMA, "policy": policy, "slot_policy": expand_policy(policy)}
    return {"schema": SLOT_SCHEMA, "policy": default_policy(),
            "slot_policy": validate_slot_policy_block(profile, block, backend=backend)}


def validate_profiles_block(block: Any, inventory: set[str] | list[str]) -> dict[str, Any]:
    if not isinstance(block, dict) or set(block) != {"schema", "profiles", "default"} or type(block["schema"]) is not int or block["schema"] != SCHEMA:
        raise ValueError("invalid native profiles block")
    return validate_profiles({"profiles": block["profiles"], "default": block["default"]}, inventory)
