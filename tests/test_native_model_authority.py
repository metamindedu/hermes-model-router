"""The profile's own Hermes config is the read-time source of every model role.

Synthetic, distinct routes per role and profile. No live config, credentials or model calls: the
fake config is a dict behind Service._read_key, writes go through an injected writer.
"""
from __future__ import annotations

import copy
import json

import pytest

from model_router import effective_config
from model_router import service as service_module
from model_router.routing import RoutingError, _safe_route
from model_router.service import (ExternalChange, MODEL_KEYS, MODEL_SETTINGS_SCHEMA, RevisionConflict, Service,
                                  _project_roles)
from test_fallback_service import confirmation, setup_service

ROLE_META_KEYS = {"state", "source", "editable", "reason"}


def route(provider, model, reasoning="medium"):
    return {"provider": provider, "model": model, "reasoning": reasoning}


def row(status, name="default"):
    return next(item for item in status["profiles"] if item["name"] == name)


def custom_slots():
    """Every slot declared: design/verify-complex follow main, code-* follow delegation, one custom."""
    return {
        "design": {"follow": "main", "custom": None},
        "verify-complex": {"follow": "main", "custom": None},
        "code-complex": {"follow": "delegation", "custom": None},
        "code-simple": {"follow": "delegation", "custom": None},
        "verify-simple": {"follow": "custom", "custom": route("custom-co", "custom-verify", "low")},
        "computer-use": {"follow": "main", "custom": None},
    }


def store_slots(service, name="default", slots=None):
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["schema"] = 3
    data["profiles"][name]["routing"]["slots"] = slots or custom_slots()
    service.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


@pytest.fixture
def svc(tmp_path, monkeypatch):
    service, fake, root = setup_service(tmp_path, monkeypatch)
    # Distinct explicit routes for the two auxiliary roles of p1; default keeps them inherited.
    fake.values["p1"].update({
        "auxiliary.compression.provider": "zai", "auxiliary.compression.model": "compress-p1",
        "auxiliary.compression.reasoning_effort": "low",
        "auxiliary.title_generation.provider": "xiaomi", "auxiliary.title_generation.model": "title-p1",
        "auxiliary.title_generation.reasoning_effort": "minimal",
    })
    return service, fake, root


def frozen(status, name, roles):
    item = row(status, name)
    return {"profile": name,
            "models": {role: copy.deepcopy(item["models"][role]) for role in roles},
            "actual_models": {role: copy.deepcopy(item["actual_models"][role]) for role in roles}}


def native_body(service, models, targets=("default",), *, status=None, frozen_roles=None):
    status = status or service.status()
    source = row(status, "default")
    return {
        "model_settings_schema": MODEL_SETTINGS_SCHEMA,
        "expected_revision": status["revision"], "profile": "default", "save_scope": "models",
        "models": copy.deepcopy(models), "model_targets": list(targets),
        "routing": {key: value for key, value in copy.deepcopy(source["routing"]).items() if key != "fallback"},
        "routing_profiles": [item["name"] for item in status["profiles"] if item["routing"]["enabled"]],
        "routing_targets": [],
        "expected": [frozen(status, name, frozen_roles or list(models)) for name in targets],
    }


def snapshot_bytes(service, fake):
    return service.store_path.read_bytes(), json.dumps(fake.values, sort_keys=True)


# --- read projection ---------------------------------------------------------------------------

def test_status_projects_every_role_from_config_and_reports_no_model_drift(svc):
    service, fake, _ = svc
    fake.values["default"].update({"model.default": "ext-main", "delegation.model": "ext-delegation",
                                   "auxiliary.compression.provider": "zai", "auxiliary.compression.model": "ext-compress",
                                   "auxiliary.title_generation.provider": "xiaomi", "auxiliary.title_generation.model": "ext-title"})
    before = snapshot_bytes(service, fake)
    status = service.status()
    item = row(status)
    assert status["model_settings_schema"] == 1
    assert item["models"] == item["actual_models"] == {
        "main": route("openai-codex", "ext-main", "high"),
        "delegation": route("deepseek", "ext-delegation", "low"),
        "compression": route("zai", "ext-compress", "high"),
        "title": route("xiaomi", "ext-title", "high"),
    }
    assert all(meta == {"state": "verified", "source": "explicit", "editable": True} for meta in item["model_roles"].values())
    assert item["drift"] == []
    # A read never writes the store or the config.
    assert snapshot_bytes(service, fake) == before and fake.calls == []


def test_role_metadata_is_stable_and_nonsecret(svc):
    service, fake, _ = svc
    fake.values["default"]["delegation.base_url"] = "https://secret-endpoint.example/v1"
    fake.values["default"]["auxiliary.title_generation.api_key"] = "PRIVATE-KEY-MARKER"
    text = json.dumps(service.status())
    assert "secret-endpoint" not in text and "PRIVATE-KEY-MARKER" not in text
    for item in service.status()["profiles"]:
        for meta in item["model_roles"].values():
            assert set(meta) <= ROLE_META_KEYS and {"state", "source", "editable"} <= set(meta)
            assert meta["state"] in {"verified", "unverified"} and meta["source"] in {"explicit", "inherited"}
            assert type(meta["editable"]) is bool


def test_unresolved_roles_are_omitted_not_fabricated(svc):
    service, fake, _ = svc
    fake.values["default"]["auxiliary.title_generation.provider"] = "xiaomi"  # provider default model: unknown
    fake.values["default"]["auxiliary.compression.reasoning_effort"] = "bogus"
    item = row(service.status())
    assert "title" not in item["models"] and "compression" not in item["models"]
    assert item["model_roles"]["title"] == {"state": "unverified", "source": "explicit", "editable": True, "reason": "provider_default_model"}
    assert item["model_roles"]["compression"]["reason"] == "invalid"
    assert item["models"]["main"] == route("openai-codex", "heavy0", "high")


def test_inheritance_aliases_follow_hermes_resolution():
    values: dict[str, object] = {key: None for role in MODEL_KEYS for key in service_module._role_keys(role)}
    values.update({"model.provider": "openai-codex", "model.default": "m", "agent.reasoning_effort": "high",
                   "delegation.provider": "", "delegation.model": "child", "delegation.reasoning_effort": "",
                   "auxiliary.compression.provider": "AUTO", "auxiliary.compression.model": "Auto",
                   "auxiliary.title_generation.provider": "auto", "auxiliary.title_generation.model": "named-model"})
    models, roles = _project_roles(values, {"available": True, "managed": {}})
    # Delegation without a provider keeps the parent's provider and its own model.
    assert models["delegation"] == route("openai-codex", "child", "high") and roles["delegation"]["source"] == "explicit"
    # `auto`/`Auto` (any case) means inherit for an auxiliary task.
    assert models["compression"] == route("openai-codex", "m", "high") and roles["compression"]["source"] == "inherited"
    # An auxiliary model with `auto` provider goes through Hermes auto-detection: not known here.
    assert "title" not in models and roles["title"]["reason"] == "auto_provider"
    # The main model's own base_url with a named provider is that provider's endpoint, not a blocker.
    values["model.base_url"] = "https://api.example.test/v1"
    assert "main" in _project_roles(values, {"available": True, "managed": {}})[0]
    values["model.provider"] = "custom"
    models, roles = _project_roles(values, {"available": True, "managed": {}})
    assert "main" not in models and roles["main"]["reason"] == "direct_endpoint"
    assert roles["compression"]["reason"] == "inherits_unverified"


def test_unverifiable_provenance_marks_every_role_unverified_and_read_only(svc, monkeypatch):
    service, _, _ = svc
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: {"available": False, "managed": {}, "digest": None})
    item = row(service.status())
    assert item["models"] == {} and item["actual_models"] == {}
    assert all(meta["state"] == "unverified" and meta["editable"] is False and meta["reason"] == "provenance_unavailable"
               for meta in item["model_roles"].values())


def test_managed_role_shows_the_effective_value_read_only(svc, monkeypatch):
    service, _, _ = svc
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: {
        "available": True, "managed": {"model.default": "admin-main"} if profile == "default" else {}, "digest": "managed-1"})
    item = row(service.status())
    assert item["models"]["main"] == route("openai-codex", "admin-main", "high")
    assert item["model_roles"]["main"] == {"state": "verified", "source": "explicit", "editable": False, "reason": "managed"}
    # Inherited roles follow the effective managed main; they stay editable themselves.
    assert item["models"]["compression"]["model"] == "admin-main" and item["model_roles"]["compression"]["editable"] is True
    with pytest.raises(ValueError, match="main model of default is read-only"):
        service.preview(native_body(service, {"main": route("openai-codex", "page-main", "high")}))


# --- dispatch routes ---------------------------------------------------------------------------

def test_native_routes_follow_each_externally_edited_role_and_keep_custom(svc):
    service, fake, _ = svc
    store_slots(service)
    before = snapshot_bytes(service, fake)
    fake.values["default"]["model.default"] = "edited-main"
    fake.values["default"]["delegation.model"] = "edited-delegation"
    config = service.native_route_config("default")
    assert config["heavy"] == route("openai-codex", "edited-main", "high")
    assert config["light"] == route("deepseek", "edited-delegation", "low")
    assert config["slots"]["design"] == config["slots"]["computer-use"] == config["heavy"]
    assert config["slots"]["code-complex"] == config["light"]
    assert config["slots"]["verify-simple"] == route("custom-co", "custom-verify", "low")
    # Dispatch reads nothing back into the store and writes no config.
    assert snapshot_bytes(service, fake)[0] == before[0] and fake.calls == []


def test_invalid_title_never_blocks_an_independent_follow_route(svc):
    service, fake, _ = svc
    store_slots(service)
    fake.values["default"]["auxiliary.title_generation.provider"] = "${TITLE_PROVIDER}"
    config = service.native_route_config("default")
    assert config["model_roles"]["title"] == {"state": "unverified", "source": "explicit", "editable": False, "reason": "dynamic"}
    assert config["heavy"] == route("openai-codex", "heavy0", "high")
    assert all(value is not None for value in config["slots"].values())


@pytest.mark.parametrize("key,value,blocked", [
    ("delegation.base_url", "https://direct.example/v1", "delegation"),
    ("delegation.api_key", "inline-secret", "delegation"),
    ("delegation.model", "${CHILD_MODEL}", "delegation"),
    ("model.api_key", "inline-secret", "main"),
    ("agent.reasoning_effort", "turbo", "main"),
])
def test_unverifiable_role_blocks_only_its_dependent_follow_routes(svc, key, value, blocked):
    service, fake, _ = svc
    store_slots(service)
    fake.values["default"][key] = value
    config = service.native_route_config("default")
    follows = {slot: declaration["follow"] for slot, declaration in custom_slots().items()}
    for slot, follow in follows.items():
        if follow == blocked:
            assert config["slots"][slot] is None
            with pytest.raises(RoutingError):
                _safe_route(config["slots"][slot], "slot")  # what the native provider does: refuse that task
        else:
            assert _safe_route(config["slots"][slot], "slot") == config["slots"][slot]
    assert config["slots"]["verify-simple"] == route("custom-co", "custom-verify", "low")


def test_managed_and_unavailable_provenance_fail_closed_for_follow_routes_only(svc, monkeypatch):
    service, _, _ = svc
    store_slots(service)
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: {"available": False, "managed": {}, "digest": None})
    config = service.native_route_config("default")
    assert config["heavy"] is None and config["light"] is None
    assert config["slots"]["verify-simple"] == route("custom-co", "custom-verify", "low")
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: {
        "available": True, "managed": {"model.default": "admin-main"}, "digest": "m"})
    config = service.native_route_config("default")
    assert config["heavy"] == route("openai-codex", "admin-main", "high")  # trustworthy effective value


def test_external_edit_is_not_a_global_denial_and_the_revision_fence_remains(svc, monkeypatch):
    service, fake, _ = svc
    fake.values["default"]["model.default"] = "outside-edit"
    assert service.native_route_config("default")["heavy"]["model"] == "outside-edit"
    original = service._load_store
    calls = {"n": 0}

    def racing_store():
        calls["n"] += 1
        data = original()
        if calls["n"] == 2:
            data["revision"] += 1
        return data
    monkeypatch.setattr(service, "_load_store", racing_store)
    with pytest.raises(RevisionConflict, match="changed during native dispatch"):
        service.native_route_config("default")


# --- scoped native-wire saves ------------------------------------------------------------------

def test_main_change_keeps_inherited_auxiliary_roles_inherited(svc):
    service, fake, _ = svc
    request = native_body(service, {"main": route("anthropic", "new-main", "max")})
    plan = service.preview(request)
    written = {(item["key"]) for item in service._plans[plan["plan_id"]]["writes"]}
    assert written == {"model.provider", "model.default", "agent.reasoning_effort"}
    assert service.apply(plan["plan_id"])["status"] == "applied"
    values = fake.values["default"]
    assert (values["auxiliary.compression.provider"], values["auxiliary.compression.model"]) == ("auto", "")
    assert (values["auxiliary.title_generation.provider"], values["auxiliary.title_generation.model"]) == ("auto", "")
    item = row(service.status())
    assert item["models"]["compression"] == item["models"]["title"] == route("anthropic", "new-main", "max")
    assert item["model_roles"]["compression"]["source"] == item["model_roles"]["title"]["source"] == "inherited"
    # Delegation (not edited by this wire) is untouched.
    assert values["delegation.model"] == "light0"


def test_one_role_save_writes_only_that_role_on_every_target(svc):
    service, fake, _ = svc
    others = copy.deepcopy(fake.values)
    plan = service.preview(native_body(service, {"title": route("xiaomi", "fresh-title", "low")}, targets=("default", "p1")))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    touched = {(profile, key) for profile, key, _ in fake.calls}
    # Only title keys, and only where they differ (p1 already used the xiaomi provider).
    assert touched == {(name, key) for name in ("default", "p1") for key in MODEL_KEYS["title"]} - {("p1", "auxiliary.title_generation.provider")}
    for name in ("default", "p1"):
        for key, value in others[name].items():
            if key not in MODEL_KEYS["title"]:
                assert fake.values[name][key] == value
    # p1's own explicit compression route was a sibling and stays exactly as configured.
    assert row(service.status(), "p1")["models"]["compression"] == route("zai", "compress-p1", "low")


def test_native_wire_requires_expected_and_a_role_subset(svc):
    service, _, _ = svc
    request = native_body(service, {"main": route("anthropic", "x", "high")})
    request.pop("expected")
    with pytest.raises(ValueError, match="require expected"):
        service.preview(request)
    for bad in ({}, {"delegation": route("deepseek", "x", "low")}, {"main": route("anthropic", "x", "high"), "extra": {}}):
        request = native_body(service, {"main": route("anthropic", "x", "high")})
        request["models"] = bad
        with pytest.raises(ValueError):
            service.preview(request)
    request = native_body(service, {"main": route("anthropic", "x", "high")})
    request["model_settings_schema"] = 2
    with pytest.raises(ValueError, match="model_settings_schema"):
        service.preview(request)
    request = native_body(service, {"main": route("anthropic", "x", "high")})
    request["expected"][0]["models"] = {}
    request["expected"][0]["actual_models"] = {}
    with pytest.raises(ValueError, match="expected must cover"):
        service.preview(request)


def test_stale_edited_role_refuses_at_preview_and_before_the_first_write_at_apply(svc):
    service, fake, _ = svc
    status = service.status()
    request = native_body(service, {"main": route("anthropic", "page-main", "high")}, status=status)
    fake.values["default"]["model.default"] = "changed-before-preview"
    store = service.store_path.read_bytes()
    with pytest.raises(ExternalChange) as caught:
        service.preview(copy.deepcopy(request))
    assert (caught.value.profile, caught.value.field) == ("default", "actual_models.main")
    fake.values["default"]["model.default"] = "heavy0"
    plan = service.preview(copy.deepcopy(request))["plan_id"]
    fake.values["default"]["model.default"] = "changed-after-preview"
    with pytest.raises(ExternalChange):
        service.apply(plan)
    assert fake.calls == [] and service.store_path.read_bytes() == store


def test_unrelated_sibling_role_changed_between_request_preview_and_apply_does_not_block(svc):
    service, fake, _ = svc
    status = service.status()
    request = native_body(service, {"title": route("xiaomi", "page-title", "low")}, status=status)
    fake.values["default"]["auxiliary.compression.model"] = "outside-compress"
    fake.values["default"]["auxiliary.compression.provider"] = "zai"
    plan = service.preview(copy.deepcopy(request))["plan_id"]
    fake.values["default"]["delegation.model"] = "outside-delegation"  # independent of title
    assert service.apply(plan)["status"] == "applied"
    values = fake.values["default"]
    assert values["delegation.model"] == "outside-delegation" and values["auxiliary.compression.model"] == "outside-compress"
    assert row(service.status())["models"]["title"] == route("xiaomi", "page-title", "low")


def test_a_managed_edited_role_is_refused_before_any_write(svc, monkeypatch):
    service, _, _ = svc
    # Editing only title while it is managed would write under the overlay: refused before preview.
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: {
        "available": True, "managed": {"auxiliary.title_generation.provider": "xiaomi", "auxiliary.title_generation.model": "admin-title"},
        "digest": "m"})
    with pytest.raises(ValueError, match="title model of default is read-only"):
        service.preview(native_body(service, {"title": route("xiaomi", "page-title", "low")}))


def test_managed_provenance_change_after_preview_refuses_apply_before_any_write(svc, monkeypatch):
    service, fake, _ = svc
    plan = service.preview(native_body(service, {"main": route("anthropic", "page-main", "high")}))["plan_id"]
    monkeypatch.setattr(Service, "_read_model_overlay", lambda self, profile: {
        "available": True, "managed": {}, "digest": "a-new-overlay-appeared"})
    with pytest.raises(RevisionConflict, match="managed model settings changed"):
        service.apply(plan)
    assert fake.calls == []


def test_native_wire_never_creates_a_store_entry_and_keeps_untargeted_bytes(svc):
    service, fake, _ = svc
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"].pop("p1")
    service.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    plan = service.preview(native_body(service, {"main": route("anthropic", "p1-main", "high")}, targets=("p1",)))
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))
    assert "p1" not in stored["profiles"] and stored["profiles"]["default"] == data["profiles"]["default"]
    assert fake.values["p1"]["model.default"] == "p1-main"


def test_unchanged_native_wire_save_is_a_noop(svc):
    service, fake, _ = svc
    before = snapshot_bytes(service, fake)
    plan = service.preview(native_body(service, {"main": route("openai-codex", "heavy0", "high")}))
    assert plan["changes"] == []
    assert service.apply(plan["plan_id"])["status"] == "no_change"
    assert fake.calls == [] and service.store_path.read_bytes() == before[0]


def test_old_three_role_body_keeps_its_legacy_semantics(svc):
    service, fake, _ = svc
    status = service.status()
    item = row(status)
    models = {role: copy.deepcopy(item["models"][role]) for role in ("main", "compression", "title")}
    models["main"]["model"] = "legacy-main"
    request = {"expected_revision": status["revision"], "profile": "default", "save_scope": "models",
               "models": models, "model_targets": ["default"],
               "routing": {key: value for key, value in copy.deepcopy(item["routing"]).items() if key != "fallback"},
               "routing_profiles": ["default"], "routing_targets": []}
    assert service.apply(service.preview(request)["plan_id"])["status"] == "applied"
    # The legacy wire writes every role it carries: the inherited compression role becomes the
    # explicit route the page sent (old semantics, kept for old clients).
    assert fake.values["default"]["model.default"] == "legacy-main"
    assert (fake.values["default"]["auxiliary.compression.provider"], fake.values["default"]["auxiliary.compression.model"]) == ("openai-codex", "heavy0")
    assert fake.values["default"]["delegation.model"] == "light0"


# --- native fallback chain ---------------------------------------------------------------------

def chain(*models):
    return [{"provider": "xiaomi", "model": model} for model in models]


def fallback_request(service, value, confirmations=(), *, native_wire=True):
    status = service.status()
    item = row(status)
    body = {"expected_revision": status["revision"], "updates": [{"profile": "default", "native_fallback": value}],
            "confirmations": list(confirmations)}
    native = item["fallbacks"]["native"]
    body["expected"] = [{"profile": "default", "native_fallback": {"enabled": native["enabled"], "chain": native["chain"], "actual_chain": native["actual_chain"]}}]
    if native_wire:
        body["model_settings_schema"] = 1
    return body


def test_status_projects_the_real_chain_and_never_grants_cost_for_an_external_edit(svc):
    service, fake, _ = svc
    fake.values["default"]["fallback_providers"] = chain("outside-spare")
    store = service.store_path.read_bytes()
    native = row(service.status())["fallbacks"]["native"]
    assert native["enabled"] is True and native["chain"] == native["actual_chain"] == chain("outside-spare")
    assert native["consent"] is None and native["drift"] is False and native["managed"] is False
    assert service.store_path.read_bytes() == store


def test_unchanged_chain_keeps_its_consent_after_an_external_main_edit(svc):
    service, fake, _ = svc
    value = {"enabled": True, "chain": chain("spare-a")}
    assert service.apply(service.fallback_preview(fallback_request(service, value, [confirmation("native")]))["plan_id"])["status"] == "applied"
    fake.values["default"]["model.default"] = "outside-main"
    native = row(service.status())["fallbacks"]["native"]
    assert native["consent"]["source"] == "explicit" and native["chain"] == chain("spare-a")
    # Resubmitting the same chain needs no new cost confirmation and changes no consent.
    plan = service.fallback_preview(fallback_request(service, value))
    assert not any(change["field"].startswith("fallback_consent") for change in plan["changes"])
    # A different chain still needs explicit cost confirmation.
    with pytest.raises(ValueError, match="additional-cost confirmation"):
        service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("spare-b")}))


def test_chain_is_compared_with_the_real_main_and_bound_to_it(svc):
    service, fake, _ = svc
    fake.values["default"]["model.default"] = "real-main"
    fake.values["default"]["model.provider"] = "xiaomi"
    with pytest.raises(ValueError, match="differ from the primary model"):
        service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("REAL-MAIN")}, [confirmation("native")]))
    plan = service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("spare")}, [confirmation("native")]))
    # The real primary changes before apply: refused before the first write.
    fake.values["default"]["model.default"] = "spare"
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []


def test_chain_needs_a_verified_main_model(svc):
    service, fake, _ = svc
    fake.values["default"]["model.api_key"] = "inline-secret"
    with pytest.raises(ValueError, match="verified main model"):
        service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("spare")}, [confirmation("native")]))
    # Turning spares off never depends on the primary.
    assert service.fallback_preview(fallback_request(service, {"enabled": False, "chain": []}))["plan_id"]


def test_combined_save_compares_the_chain_with_the_prospective_main(svc):
    service, fake, _ = svc
    request = native_body(service, {"main": route("xiaomi", "next-main", "high")})
    request["save_scope"] = None
    request.pop("save_scope")
    request["routing_targets"] = []
    request["fallback_updates"] = [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain("next-main")}}]
    request["fallback_confirmations"] = [confirmation("native")]
    native = row(service.status())["fallbacks"]["native"]
    request["expected"][0]["native_fallback"] = {"enabled": native["enabled"], "chain": native["chain"], "actual_chain": native["actual_chain"]}
    with pytest.raises(ValueError, match="differ from the primary model"):
        service.preview(copy.deepcopy(request))
    request["fallback_updates"][0]["native_fallback"]["chain"] = chain("heavy0")  # the old main is a fine spare
    plan = service.preview(copy.deepcopy(request))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["default"]["model.default"] == "next-main"
    assert fake.values["default"]["fallback_providers"] == chain("heavy0")
    # Siblings untouched: inherited auxiliary roles and the delegation model.
    assert fake.values["default"]["auxiliary.compression.model"] == "" and fake.values["default"]["delegation.model"] == "light0"


# --- the production readers --------------------------------------------------------------------

def test_overlay_reader_maps_managed_keys_and_fails_closed(tmp_path, monkeypatch):
    from conftest import real_model_overlay_reader
    monkeypatch.setattr(Service, "_read_model_overlay", real_model_overlay_reader())
    service = Service(root=tmp_path)
    keys = service._all_role_keys()
    seen = {}

    def reader(home, selected, **_kwargs):
        seen["keys"] = tuple(selected)
        return effective_config.make_key_snapshot(keys=selected, raw={}, effective={"model.default": "admin-main"},
                                                  managed_keys=("model.default",), managed_signature=seen.get("sig", "s1"))
    monkeypatch.setattr(effective_config, "read_key_scoped", reader)
    overlay = service._read_model_overlay("default")
    # Read per role over its scope (superseded: one all-key read); the last read is the title scope.
    assert seen["keys"] == service_module._role_scope_keys("title") and overlay["available"] is True
    assert overlay["managed"] == {"model.default": "admin-main"} and isinstance(overlay["digest"], str)
    seen["sig"] = "s2"
    assert service._read_model_overlay("default")["digest"] != overlay["digest"]

    monkeypatch.setattr(effective_config, "read_key_scoped", lambda home, selected, **_: effective_config.make_key_snapshot(
        keys=selected, raw={}, effective=None, warnings=("scoped_managed_provenance_unavailable",)))
    assert {k: v for k, v in service._read_model_overlay("default").items() if k != "roles"} == {"available": False, "managed": {}, "digest": None}

    def unavailable(home, selected, **_):
        raise effective_config.EffectiveConfigUnavailable("helpers missing")
    monkeypatch.setattr(effective_config, "read_key_scoped", unavailable)
    assert service._read_model_overlay("default")["available"] is False


def test_real_yaml_reads_project_roles_without_touching_any_bytes(tmp_path):
    root = tmp_path / "hermes"
    root.mkdir()
    config = root / "config.yaml"
    config.write_text(
        "model:\n  provider: openai-codex\n  default: yaml-main\n  base_url: https://chatgpt.example/backend-api/codex\n"
        "agent:\n  reasoning_effort: high\n"
        "delegation:\n  provider: deepseek\n  model: yaml-child\n  reasoning_effort: low\n"
        "auxiliary:\n  compression:\n    provider: auto\n    model: ''\n  title_generation:\n    provider: zai\n    model: yaml-title\n",
        encoding="utf-8")
    service = Service(root=root)
    before = config.read_bytes()
    models, roles = service._native_models("default")
    assert models == {"main": route("openai-codex", "yaml-main", "high"), "delegation": route("deepseek", "yaml-child", "low"),
                      "compression": route("openai-codex", "yaml-main", "high"), "title": route("zai", "yaml-title", "high")}
    assert roles["compression"]["source"] == "inherited" and roles["main"]["state"] == "verified"
    assert config.read_bytes() == before and not (root / "plugin-data").exists()


# --- whole-page (combined) native wire: no scope expansion --------------------------------------

def routing_expectation(service, name):
    item = row(service.status(), name)
    routing = item["routing"]
    skill_enabled = bool(routing["enabled"]) != ("skills.disabled" in item["drift"])
    return {"enabled": bool(routing["enabled"]), "heavy": routing.get("heavy"), "light": routing.get("light"),
            "slots": routing.get("slots"), "skill_enabled": skill_enabled}


def whole_page_body(service, models, routing_profiles):
    request = native_body(service, models)
    request.pop("save_scope")
    request["routing_profiles"] = list(routing_profiles)
    request["routing"]["enabled"] = "default" in routing_profiles
    return request


def test_whole_page_save_ignores_an_unresolvable_untouched_bystander(svc):
    service, fake, _ = svc
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"].pop("p1")
    service.store_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    fake.values["p1"]["model.default"] = ""  # p1 cannot be resolved at all
    fake.values["p1"]["skills.disabled"] = ["adaptive-coding-orchestration"]  # routing off, unchanged
    request = whole_page_body(service, {"main": route("anthropic", "whole-main", "high")}, ["default"])
    plan = service.preview(request)
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["default"]["model.default"] == "whole-main"
    assert "p1" not in json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert not any(profile == "p1" for profile, _key, _value in fake.calls)


def test_membership_change_binds_only_the_skill_list_of_that_profile(svc):
    service, fake, _ = svc
    request = whole_page_body(service, {"title": route("xiaomi", "whole-title", "low")}, ["default", "p1"])
    request["expected"].append({"profile": "p1", "routing": routing_expectation(service, "p1")})
    plan = service.preview(request)
    # A sibling model of p1 changes elsewhere: the membership save does not write models, so it is not blocked.
    fake.values["p1"]["model.default"] = "p1-outside-main"
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["p1"]["skills.disabled"] == [] and fake.values["p1"]["model.default"] == "p1-outside-main"
    assert {key for profile, key, _ in fake.calls if profile == "p1"} == {"skills.disabled"}
