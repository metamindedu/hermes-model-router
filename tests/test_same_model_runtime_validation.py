"""Same-model routing relaxes identity only, never route/fallback admission."""
import copy
import json

import pytest

from lib import routing_cache, run_routed_agent as runner
from model_router import routing
from test_routing import HEAVY, _load, _make_router, _start


def _same_routes():
    route = {"provider": HEAVY["provider"], "model_id": HEAVY["model"], "reasoning_effort": "high"}
    return {role: dict(route) for role in ("HEAVYWEIGHT", "LIGHTWEIGHT")}


@pytest.mark.parametrize("effort", ["low", "high"])
def test_full_cache_accepts_same_model_operator_routes_without_mutating_input(effort):
    cache = json.loads(routing.TEMPLATE_CACHE_PATH.read_text(encoding="utf-8"))
    cache["operator_routes"] = _same_routes()
    cache["operator_routes"]["LIGHTWEIGHT"]["reasoning_effort"] = effort
    before = copy.deepcopy(cache)
    routing_cache.validate_cache(cache)
    assert cache == before


@pytest.mark.parametrize("field,value", [
    ("provider", "KEEP"), ("provider", " provider"), ("provider", "provider;command"),
    ("model_id", "${MODEL}"), ("model_id", "model "), ("model_id", "KEEP"),
    ("reasoning_effort", "enabled"), ("reasoning_effort", True),
    ("api_key", "not-a-real-credential"),
])
def test_same_model_operator_cache_preserves_literal_schema_and_effort_guards(tmp_path, field, value):
    routes = _same_routes()
    routes["LIGHTWEIGHT"][field] = value
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"operator_routes": routes}), encoding="utf-8")
    with pytest.raises(ValueError, match="operator_routes"):
        runner.resolve_route(path, "HEAVYWEIGHT")


@pytest.mark.parametrize("extra_role", [False, True])
def test_operator_cache_still_requires_exact_role_set(extra_role):
    routes = _same_routes()
    if extra_role:
        routes["GENERAL"] = dict(routes["HEAVYWEIGHT"])
    else:
        del routes["LIGHTWEIGHT"]
    with pytest.raises(ValueError, match="exactly HEAVYWEIGHT and LIGHTWEIGHT"):
        routing_cache.validate_operator_routes(routes)


def test_same_model_cache_still_rejects_nested_credential_fields():
    cache = json.loads(routing.TEMPLATE_CACHE_PATH.read_text(encoding="utf-8"))
    cache["operator_routes"] = _same_routes()
    cache["metadata"] = {"nested": [{"access_token": "not-a-real-credential"}]}
    with pytest.raises(ValueError, match="credential-like field is forbidden"):
        routing_cache.validate_cache(cache)


@pytest.mark.parametrize("role", ["heavy", "light"])
def test_same_model_primary_still_forbids_self_fallback_before_spawn(tmp_path, monkeypatch, role):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    service.light = dict(HEAVY)
    service.fallback_enabled = True
    # Even a different effort cannot turn the primary into a valid fallback.
    setattr(service, f"{role}_fallback", {**HEAVY, "reasoning": "low"})
    with pytest.raises(routing.RoutingError, match="must differ from its primary route"):
        _start(router, tmp_path, "plan")
    assert calls == []
    assert not (root / "profiles/claire/plugin-data").exists()


@pytest.mark.parametrize("enabled,approved", [(False, True), (True, False), (True, True)])
def test_same_model_primary_keeps_explicit_fallback_consent_and_role_routes(
    tmp_path, monkeypatch, enabled, approved
):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    service.light = dict(HEAVY)
    service.fallback_enabled = enabled
    service.fallback_approved = approved
    result = _start(router, tmp_path, "independent-review")
    assert result["status"] == "running"
    assert len(calls) == 1
    directory = root / "profiles/claire/plugin-data/model-router/jobs" / result["job_id"]
    snapshot = _load(directory / "snapshot.json")
    evidence = snapshot["model_provider_evidence"]
    assert evidence["fallback_enabled"] is (enabled and approved)
    assert evidence["fallback_policy"]["approved"] is approved
    cache = _load(directory / "routing-cache.json")
    if enabled and approved:
        for role, expected in (("HEAVYWEIGHT", service.heavy_fallback), ("LIGHTWEIGHT", service.light_fallback)):
            resolved = runner.resolve_fallback(directory / "routing-cache.json", role)
            assert resolved is not None
            assert resolved["provider"] == expected["provider"]
            assert resolved["model_id"] == expected["model"]
            assert resolved["reasoning_effort"] == expected["reasoning"]
            assert resolved["role"] == role
    else:
        assert cache["fallback_routes"] == {}
        assert evidence["fallback"] == {"HEAVYWEIGHT": None, "LIGHTWEIGHT": None}
