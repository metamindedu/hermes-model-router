"""Task slots: which model a routed purpose runs on, and for how long.

Pure declarations and resolution. No filesystem access, configuration writes
or provider calls; callers prove profile inventory and readiness separately.

A slot is what the operator assigns a model and a runtime limit to. A purpose
is what the agent sends; each purpose names exactly one slot.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Callable, Iterable, Mapping

# Order is user-visible (settings page) and part of the tool schema.
BUILTIN_SLOTS = ("design", "code-complex", "code-simple", "verify-simple", "verify-complex", "computer-use", "advise")
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
    "advise": "advise",
}
FOLLOWS = ("main", "custom")
# A slot that has never been set runs on the profile's main model.
DEFAULT_FOLLOW = "main"
# A slot without its own runtime limit stops after two hours (0 means no limit).
DEFAULT_SLOT_SECONDS = 7200.0
# The advisor answers one question for the agent that asked it. Its purpose is
# dispatched only by the ask_advisor tool, whose child is read-only.
ADVISE_SLOT = "advise"
ADVISOR_PURPOSES = frozenset({"advise"})
# Operator-added slots: defined once for every profile (label, one-line scope description); each
# profile picks its model and runtime limit like a built-in slot. The slot id is also the purpose.
CUSTOM_PREFIX = "custom:"
CUSTOM_SLOT_LIMIT = 4
CUSTOM_LABEL_LIMIT = 24
CUSTOM_DESCRIPTION_LIMIT = 120
_CUSTOM_ID = re.compile(r"custom:[a-z0-9][a-z0-9-]{1,31}\Z")
# Control and format characters (C0/C1 controls, bidi controls, zero-width joiners and tag
# characters), lone surrogates and line/paragraph separators render invisibly or reorder text; the page refuses the same categories.
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def is_custom_slot(value: Any) -> bool:
    return isinstance(value, str) and _CUSTOM_ID.fullmatch(value) is not None


def _custom_text(value: Any, limit: int, field: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > limit or value != value.strip()
            or any(unicodedata.category(char) in _HIDDEN_CATEGORIES for char in value)):
        raise ValueError(f"custom slot {field} must be 1-{limit} characters on one line")
    return value


def validate_custom_slots(value: Any) -> list[dict[str, str]]:
    """Validate the operator's custom slot definitions (an ordered list, at most four)."""
    if not isinstance(value, list) or len(value) > CUSTOM_SLOT_LIMIT:
        raise ValueError(f"custom_slots must be a list of at most {CUSTOM_SLOT_LIMIT} slots")
    result, ids, labels = [], set(), set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "label", "description"}:
            raise ValueError("each custom slot defines id, label and description")
        slot = item["id"]
        if not is_custom_slot(slot) or slot in ids:
            raise ValueError("custom slot id must be custom: plus 2-32 lowercase letters, digits or hyphens, used once")
        label = _custom_text(item["label"], CUSTOM_LABEL_LIMIT, "label")
        if label.casefold() in labels:
            raise ValueError("custom slot labels must differ")
        description = _custom_text(item["description"], CUSTOM_DESCRIPTION_LIMIT, "description")
        ids.add(slot)
        labels.add(label.casefold())
        result.append({"id": slot, "label": label, "description": description})
    return result


def slot_ids(definitions: Iterable[Mapping[str, Any]] = ()) -> tuple[str, ...]:
    """Every slot: the built-ins, then the defined custom slots in order."""
    return (*BUILTIN_SLOTS, *(item["id"] for item in definitions))


def purpose_slots(definitions: Iterable[Mapping[str, Any]] = ()) -> dict[str, str]:
    """Purpose -> slot. A custom slot's purpose is its own id; built-in purposes come first."""
    return {**PURPOSE_SLOTS, **{item["id"]: item["id"] for item in definitions}}


def require_builtin_keys(mapping: Any) -> dict[str, Any]:
    """A per-slot mapping that names exactly every built-in slot, in slot order."""
    if not isinstance(mapping, dict) or frozenset(mapping) != frozenset(BUILTIN_SLOTS):
        raise ValueError("per-slot mapping must name every task slot")
    return {slot: mapping[slot] for slot in BUILTIN_SLOTS}


def validate_slots(value: Any, route: Callable[[Any], dict[str, str]],
                   custom_ids: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    """Validate stored or submitted slot declarations.

    Built-in slots and custom slot ids are accepted. With ``custom_ids`` given, a custom id must be
    one of them; without, any well-formed custom id passes here and the caller checks it against the
    stored definitions. An absent slot is valid and means the slot has never been set; it is not
    filled in here.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("routing.slots must be a mapping of slot declarations")
    customs = sorted(key for key in value if key not in BUILTIN_SLOTS)
    if any(not is_custom_slot(key) for key in customs):
        raise ValueError("routing.slots contains an unknown slot")
    if custom_ids is not None:
        known = list(custom_ids)
        if set(customs) - set(known):
            raise ValueError("routing.slots names a custom slot that is not defined")
        customs = [key for key in known if key in value]
    result: dict[str, dict[str, Any]] = {}
    for slot in (*BUILTIN_SLOTS, *customs):
        if slot not in value:
            continue
        item = value[slot]
        if not isinstance(item, dict) or set(item) != {"follow", "custom"}:
            raise ValueError(f"routing.slots.{slot} must define follow and custom")
        follow = item["follow"]
        if not isinstance(follow, str) or follow not in FOLLOWS:
            raise ValueError(f"routing.slots.{slot}.follow must be main or custom")
        custom = None if item["custom"] is None else route(item["custom"])
        if follow == "custom" and custom is None:
            raise ValueError(f"routing.slots.{slot}.custom is required when following custom")
        if follow != "custom" and custom is not None:
            raise ValueError(f"routing.slots.{slot}.custom must be null unless following custom")
        result[slot] = {"follow": follow, "custom": custom}
    return result


def slot_route(routing: Mapping[str, Any], models: Mapping[str, Any], slot: str,
               known: Iterable[str] | None = None) -> Any:
    """Resolve one slot to its route declaration (not validated here). ``known`` adds custom slots."""
    if slot not in (BUILTIN_SLOTS if known is None else tuple(known)):
        raise ValueError("unknown slot")
    declaration = (routing.get("slots") or {}).get(slot)
    if declaration is None:
        return models[DEFAULT_FOLLOW]
    if declaration["follow"] == "custom":
        return declaration["custom"]
    return models[declaration["follow"]]


def resolved_slots(routing: Mapping[str, Any], models: Mapping[str, Any],
                   definitions: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    known = slot_ids(definitions)
    return {slot: copy.deepcopy(slot_route(routing, models, slot, known)) for slot in known}


def effective_declarations(routing: Mapping[str, Any],
                           definitions: Iterable[Mapping[str, Any]] = ()) -> dict[str, dict[str, Any]]:
    """Every slot as an explicit declaration, for display and editing.

    A never-set slot is shown as following the main model. Nothing is persisted by this view.
    """
    stored = routing.get("slots") or {}
    return {slot: copy.deepcopy(stored[slot]) if slot in stored else {"follow": DEFAULT_FOLLOW, "custom": None}
            for slot in slot_ids(definitions)}
