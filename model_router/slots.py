"""Task slots: which model a routed purpose runs on.

Pure declarations and resolution. No filesystem access, configuration writes
or provider calls; callers prove profile inventory and readiness separately.

A slot is what the operator assigns a model to. A purpose is what the agent
sends. Tier survives only as the internal grouping for what is not per slot:
the two routed runtime limits, the watchdog role, the runtime label and the
meaning of a slot that has never been set.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Mapping

# Order is user-visible (settings page) and part of the tool schema.
BUILTIN_SLOTS = ("design", "code-complex", "code-simple", "verify-simple", "verify-complex", "computer-use")
SLOT_TIERS = {
    "design": "heavy",
    "code-complex": "light",
    "code-simple": "light",
    "verify-simple": "light",
    "verify-complex": "heavy",
    "computer-use": "light",
}
# Existing purposes keep their order; new ones are appended so a running
# session's cached tool schema only ever grows at the end.
PURPOSE_SLOTS = {
    "implementation": "code-complex",
    "mechanical": "code-simple",
    "preliminary-review": "verify-simple",
    "plan": "design",
    "semantic-final": "verify-complex",
    "independent-review": "verify-complex",
    "computer-use": "computer-use",
}
PURPOSE_ROLES = {purpose: SLOT_TIERS[slot] for purpose, slot in PURPOSE_SLOTS.items()}
TIERS = ("heavy", "light")
# The model role a tier follows when its own declaration is not custom.
TIER_FOLLOWS = {"heavy": "main", "light": "delegation"}
FOLLOWS = ("main", "delegation", "custom")
SLOTS_SUPPORTED = True


def validate_slots(value: Any, route: Callable[[Any], dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Validate stored or submitted slot declarations.

    Only built-in slots are accepted. An absent slot is valid and means the
    slot has never been set; it is not filled in here.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("routing.slots must be a mapping of slot declarations")
    unknown = set(value) - set(BUILTIN_SLOTS)
    if unknown:
        raise ValueError("routing.slots contains an unknown slot")
    result: dict[str, dict[str, Any]] = {}
    for slot in BUILTIN_SLOTS:
        if slot not in value:
            continue
        item = value[slot]
        if not isinstance(item, dict) or set(item) != {"follow", "custom"}:
            raise ValueError(f"routing.slots.{slot} must define follow and custom")
        follow = item["follow"]
        if not isinstance(follow, str) or follow not in FOLLOWS:
            raise ValueError(f"routing.slots.{slot}.follow must be main, delegation or custom")
        custom = None if item["custom"] is None else route(item["custom"])
        if follow == "custom" and custom is None:
            raise ValueError(f"routing.slots.{slot}.custom is required when following custom")
        if follow != "custom" and custom is not None:
            raise ValueError(f"routing.slots.{slot}.custom must be null unless following custom")
        result[slot] = {"follow": follow, "custom": custom}
    return result


def tier_route(routing: Mapping[str, Any], models: Mapping[str, Any], tier: str) -> Any:
    """The tier's own declaration, exactly as resolved before slots existed."""
    declaration = routing[tier]
    return models[TIER_FOLLOWS[tier]] if declaration["follow"] == TIER_FOLLOWS[tier] else declaration["custom"]


def slot_route(routing: Mapping[str, Any], models: Mapping[str, Any], slot: str) -> Any:
    """Resolve one built-in slot to its route declaration (not validated here)."""
    if slot not in SLOT_TIERS:
        raise ValueError("unknown slot")
    declaration = (routing.get("slots") or {}).get(slot)
    if declaration is None:
        return tier_route(routing, models, SLOT_TIERS[slot])
    if declaration["follow"] == "custom":
        return declaration["custom"]
    return models[declaration["follow"]]


def resolved_slots(routing: Mapping[str, Any], models: Mapping[str, Any]) -> dict[str, Any]:
    return {slot: copy.deepcopy(slot_route(routing, models, slot)) for slot in BUILTIN_SLOTS}


def effective_declarations(routing: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Every built-in slot as an explicit declaration, for display and editing.

    A never-set slot is shown as what it currently resolves through: its tier's
    live link or the tier's custom route. Nothing is persisted by this view.
    """
    stored = routing.get("slots") or {}
    result = {}
    for slot in BUILTIN_SLOTS:
        if slot in stored:
            result[slot] = copy.deepcopy(stored[slot])
            continue
        tier = SLOT_TIERS[slot]
        declaration = routing[tier]
        if declaration["follow"] == TIER_FOLLOWS[tier]:
            result[slot] = {"follow": TIER_FOLLOWS[tier], "custom": None}
        else:
            result[slot] = {"follow": "custom", "custom": copy.deepcopy(declaration["custom"])}
    return result
