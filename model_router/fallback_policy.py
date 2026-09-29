"""Consent primitives for explicitly scoped fallback settings.

This module is intentionally side-effect free: it does not inspect Hermes config,
perform writes, or make provider/model calls.
"""
from __future__ import annotations

from typing import Any

POLICY_VERSION = 1
NATIVE_TRIGGER = "hermes_runtime"
NATIVE_EXECUTION = "continue_conversation"
NATIVE_REASONING = "profile_overrides"
ROUTING_TRIGGER = "subscription_exhaustion_before_tools"
ROUTING_EXECUTION = "fresh_task"
ROUTING_MAX_RETRIES = 1

CAPABILITIES = {
    "native_trigger": NATIVE_TRIGGER,
    "native_execution": NATIVE_EXECUTION,
    "native_reasoning": NATIVE_REASONING,
    "routing_trigger": ROUTING_TRIGGER,
    "routing_execution": ROUTING_EXECUTION,
    "routing_max_retries": ROUTING_MAX_RETRIES,
}


def selection_for(scope: str, value: dict[str, Any]) -> dict[str, Any]:
    """Return only the exact target selection; ON/OFF does not invalidate consent."""
    if scope == "native":
        return {"chain": value["chain"]}
    if scope == "routing":
        return {"heavy": value["heavy"], "light": value["light"]}
    if scope == "delegation":
        # Default/disabled/custom have different runtime meaning, even with an
        # empty chain. Consent never migrates between these modes or scopes.
        return {"mode": value["mode"], "chain": value["chain"]}
    raise ValueError("unknown fallback consent scope")


def selection_digest(profile: str, scope: str, selection: dict[str, Any]) -> str:
    """Hash profile, consent scope, policy version, and exact fallback selection."""
    import hashlib
    import json

    payload = {
        "profile": profile,
        "scope": scope,
        "policy_version": POLICY_VERSION,
        "selection": selection,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def make_consent(profile: str, scope: str, value: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "selection_digest": selection_digest(profile, scope, selection_for(scope, value)),
        "source": source,
        "allow_additional_cost": True,
        "allow_task_rerun": scope == "routing",
    }


def validate_consent(value: Any) -> dict[str, Any] | None:
    """Validate persisted consent without trusting it to authorize a different selection."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "policy_version", "selection_digest", "source", "allow_additional_cost", "allow_task_rerun"
    }:
        raise ValueError("fallback consent has an invalid shape")
    if value["policy_version"] != POLICY_VERSION or isinstance(value["policy_version"], bool):
        raise ValueError("fallback consent policy version is unsupported")
    digest = value["selection_digest"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("fallback consent digest is invalid")
    if value["source"] not in {"explicit", "legacy-approved"}:
        raise ValueError("fallback consent source is invalid")
    if value["allow_additional_cost"] is not True or not isinstance(value["allow_task_rerun"], bool):
        raise ValueError("fallback consent flags are invalid")
    return dict(value)


def consent_matches(profile: str, scope: str, value: dict[str, Any], consent: Any) -> bool:
    parsed = validate_consent(consent)
    if parsed is None:
        return False
    return (
        parsed["selection_digest"] == selection_digest(profile, scope, selection_for(scope, value))
        and parsed["allow_additional_cost"] is True
        and parsed["allow_task_rerun"] is (scope == "routing")
    )
