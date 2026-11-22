"""Regression cases for four reviewed release blockers of the native model settings projection.

Synthetic configs only: no live profile, credential or model call. Env references below are
placeholders (never resolved); no value of any provider entry may reach status or a plan.
"""
from __future__ import annotations

import copy
import json

import pytest

from model_router import effective_config
from model_router import service as service_module
from model_router.service import MODEL_KEYS, RevisionConflict, Service, _project_roles, _role_scope_keys
from test_fallback_service import confirmation
from test_native_model_authority import chain, fallback_request, native_body, route, row, svc  # noqa: F401


def base_values(**extra):
    values = {key: None for role in MODEL_KEYS for key in service_module._role_keys(role)}
    values.update({"model.provider": "openai-codex", "model.default": "m", "agent.reasoning_effort": "high",
                   "delegation.provider": "deepseek", "delegation.model": "child", "delegation.reasoning_effort": "low"})
    values.update(extra)
    return values


OK = {"available": True, "managed": {}}


# --- (1) malformed role values stay local ------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("auxiliary.title_generation.model", ["a", "b"]),
    ("auxiliary.title_generation.model", {"x": 1}),
    ("auxiliary.title_generation.provider", ["zai"]),
    ("auxiliary.title_generation.provider", 7),
])
def test_malformed_auxiliary_value_with_inherited_effort_is_local(field, value):
    values = base_values(**{"auxiliary.title_generation.provider": "zai", "auxiliary.title_generation.model": "t",
                            "agent.reasoning_overrides": {"m": "low"}})
    values[field] = value
    models, roles = _project_roles(values, OK)
    assert "title" not in models and roles["title"]["state"] == "unverified" and roles["title"]["reason"] in {"invalid", "provider_default_model", "auto_provider"}
    # Every other role is still projected on its own (compression inherits main's per-model override).
    assert set(models) == {"main", "delegation"} and roles["compression"]["reason"] == "reasoning_override"
    assert models["main"] == route("openai-codex", "m", "low")


def test_status_and_custom_route_survive_a_list_valued_title_model(svc):
    service, fake, _ = svc
    fake.values["default"].update({"auxiliary.title_generation.provider": "zai",
                                   "auxiliary.title_generation.model": ["t1", "t2"],
                                   "auxiliary.title_generation.reasoning_effort": ""})
    item = row(service.status())
    assert item["model_roles"]["title"]["state"] == "unverified" and item["model_roles"]["title"]["reason"] == "invalid"
    assert "title" not in item["models"]
    assert item["models"]["main"] == route("openai-codex", "heavy0", "high")
    assert set(item["models"]) == {"main", "delegation", "compression"}
    # The other roles still save normally (a main edit is unaffected by the broken title).
    plan = service.preview(native_body(service, {"main": route("openai-codex", "next-main", "high")}))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["default"]["model.default"] == "next-main"
    assert fake.values["default"]["auxiliary.title_generation.model"] == ["t1", "t2"]


# --- (2) a managed unused provider entry with env references -----------------------------------

def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for key, value in over.items():
        out[key] = _deep_merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out


def _fake_helpers(managed_dir, managed_config):
    from model_router.yaml_compat import yaml

    def flat_keys(value, prefix=""):
        return {prefix + key for key in value} if isinstance(value, dict) else set()

    class Failed:
        pass

    class Api:
        FailedConfigRead = Failed

        @staticmethod
        def get_managed_dir():
            return managed_dir

        @staticmethod
        def read_user_config_raw(path):
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        @staticmethod
        def load_managed_config():
            return copy.deepcopy(managed_config)

        @staticmethod
        def managed_config_keys():
            return flat_keys(managed_config)

        @staticmethod
        def load_user_config_effective(path, fail_closed=True):
            return _deep_merge(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, managed_config)

        @staticmethod
        def set_secret_scope(scope, profile_home=None):
            return object()

        @staticmethod
        def reset_secret_scope(token):
            return None
    return Api()


USER_CONFIG = ("model:\n  provider: openai-codex\n  default: yaml-main\nagent:\n  reasoning_effort: high\n"
               "delegation:\n  provider: deepseek\n  model: yaml-child\n  reasoning_effort: low\n")
UNUSED = {"providers": {"unused-lab": {"base_url": "${UNUSED_LAB_URL}", "api_key": "${UNUSED_LAB_KEY}"}}}


def _real_overlay_service(tmp_path, monkeypatch, user_config, managed_config, *, managed_file=True):
    from conftest import real_model_overlay_reader
    from model_router.yaml_compat import yaml
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "config.yaml").write_text(user_config, encoding="utf-8")
    managed_dir = tmp_path / "managed"
    managed_dir.mkdir()
    if managed_file:
        (managed_dir / "config.yaml").write_text(yaml.safe_dump(managed_config), encoding="utf-8")
    monkeypatch.setattr(effective_config, "_helpers", lambda: _fake_helpers(managed_dir, managed_config))
    monkeypatch.setattr(Service, "_read_model_overlay", real_model_overlay_reader())
    return Service(root=root)


def test_unused_managed_provider_with_env_entry_denies_no_role(tmp_path, monkeypatch):
    service = _real_overlay_service(tmp_path, monkeypatch, USER_CONFIG, UNUSED)
    overlay = service._read_model_overlay("default")
    assert all(item["available"] for item in overlay["roles"].values())
    # Names only: the managed entry's endpoint/credential expressions never leave the reader.
    assert overlay["managed"]["providers"] == {"unused-lab": True}
    assert "UNUSED_LAB" not in json.dumps(overlay, default=str)
    models, roles = service._native_models("default", overlay=overlay)
    assert set(models) == {"main", "delegation", "compression", "title"}
    assert models["main"] == route("openai-codex", "yaml-main", "high")


def test_referenced_managed_env_provider_still_fails_closed(tmp_path, monkeypatch):
    user = USER_CONFIG.replace("provider: openai-codex", "provider: unused-lab")
    service = _real_overlay_service(tmp_path, monkeypatch, user, UNUSED)
    overlay = service._read_model_overlay("default")
    # Main (and every role that may inherit main) depends on the env-bearing entry.
    assert overlay["roles"]["main"]["available"] is False
    assert overlay["roles"]["compression"]["available"] is False
    _, roles = service._native_models("default", overlay=overlay)
    assert roles["main"]["state"] == "unverified" and roles["main"]["reason"] == "provenance_unavailable"
    # A main model prefix naming the entry is a reference too.
    prefixed = USER_CONFIG.replace("default: yaml-main", "default: unused-lab/yaml-main")
    (tmp_path / "b").mkdir()
    service2 = _real_overlay_service(tmp_path / "b", monkeypatch, prefixed, UNUSED)
    assert service2._read_model_overlay("default")["roles"]["main"]["available"] is False


def test_whole_managed_file_unavailability_and_non_entry_env_keep_denying(tmp_path, monkeypatch):
    # An existing but apparently empty managed file cannot prove overlay absence.
    service = _real_overlay_service(tmp_path, monkeypatch, USER_CONFIG, {}, managed_file=True)
    assert service._read_model_overlay("default")["available"] is False
    # An env expression in a role key (not a named entry) keeps the whole-scope read-only rule.
    (tmp_path / "c").mkdir()
    service = _real_overlay_service(tmp_path / "c", monkeypatch, USER_CONFIG, {"model": {"default": "${ADMIN_MODEL}"}})
    assert service._read_model_overlay("default")["roles"]["main"]["available"] is False


def test_reader_names_only_contract_rejects_unselected_keys(tmp_path, monkeypatch):
    service = _real_overlay_service(tmp_path, monkeypatch, USER_CONFIG, UNUSED)
    with pytest.raises(ValueError):
        effective_config.read_key_scoped(service._profile_home("default"), ("model.default",), names_only=("providers",))
    snap = effective_config.read_key_scoped(service._profile_home("default"), ("providers",), names_only=("providers",))
    assert snap.raw("providers") is None and snap.effective("providers") == {"unused-lab": True}
    assert snap.entry_env == (("providers", "unused-lab"),) and not snap.warnings


# --- (3) auxiliary prefer_fast_model and extra_body reasoning ----------------------------------

def test_new_auxiliary_route_keys_are_scoped_per_role():
    assert "auxiliary.title_generation.prefer_fast_model" in _role_scope_keys("title")
    assert "auxiliary.title_generation.extra_body" in _role_scope_keys("title")
    assert "auxiliary.compression.extra_body" in _role_scope_keys("compression")
    assert not any(key.startswith("auxiliary.") for key in _role_scope_keys("main"))
    assert "auxiliary.title_generation.prefer_fast_model" not in _role_scope_keys("compression")


@pytest.mark.parametrize("flag,verified", [(True, False), ("yes", False), ({"x": 1}, False), (None, True), (False, True), ("off", True)])
def test_inherited_title_with_prefer_fast_model_is_not_claimed_verified(flag, verified):
    values = base_values(**{"auxiliary.title_generation.prefer_fast_model": flag})
    values = {key: service_module._route_dependency_view(key, value) if key in service_module._DEPENDENCY_VIEW_KEYS else value
              for key, value in values.items()}
    models, roles = _project_roles(values, OK)
    assert ("title" in models) is verified
    assert roles["title"]["state"] == ("verified" if verified else "unverified")
    if not verified:
        assert roles["title"]["reason"] == "fast_model"
    assert models["compression"] == route("openai-codex", "m", "high")


@pytest.mark.parametrize("body", [{"reasoning": {"enabled": False}}, {"reasoning": {"effort": "low"}},
                                  {"chat_template_kwargs": {"enable_thinking": False}}, {"Reasoning_Effort": "low"}])
def test_extra_body_reasoning_overrides_are_never_shown_as_verified(svc, body):
    service, fake, _ = svc
    fake.values["default"].update({"auxiliary.compression.provider": "zai", "auxiliary.compression.model": "c",
                                   "auxiliary.compression.reasoning_effort": "high",
                                   "auxiliary.compression.extra_body": dict(body, headers={"X-Marker": "PRIVATE-BODY-MARKER"})})
    status = service.status()
    item = row(status)
    assert "compression" not in item["models"] and item["model_roles"]["compression"]["reason"] == "reasoning_override"
    assert "PRIVATE-BODY-MARKER" not in json.dumps(status)
    # A save cannot claim the submitted effort either: refused before any write.
    with pytest.raises(ValueError):
        service.preview(native_body(service, {"compression": route("zai", "c2", "high")}, frozen_roles=["main"]))
    assert fake.calls == []


def test_non_reasoning_extra_body_keeps_the_role_verified(svc):
    service, fake, _ = svc
    fake.values["default"].update({"auxiliary.compression.provider": "zai", "auxiliary.compression.model": "c",
                                   "auxiliary.compression.reasoning_effort": "low",
                                   "auxiliary.compression.extra_body": {"service_tier": "flex"}})
    assert row(service.status())["models"]["compression"] == route("zai", "c", "low")


# --- (4) CAS binds the main role's dependencies -------------------------------------------------

def test_fallback_plan_refuses_a_same_name_alias_added_after_preview(svc):
    service, fake, _ = svc
    plan = service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("spare")}, [confirmation("native")]))
    fake.values["default"]["model_aliases"] = {"heavy0": {"provider": "xiaomi", "model": "spare"}}
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []


@pytest.mark.parametrize("edit", [
    {"agent.reasoning_overrides": {"heavy0": "low"}},
    {"providers": {"heavy0-host": {"base_url": "https://x.example"}}},
    {"model.api_mode": "chat_completions"},
])
def test_fallback_plan_refuses_other_main_dependency_changes(svc, edit):
    service, fake, _ = svc
    plan = service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("spare")}, [confirmation("native")]))
    fake.values["default"].update(copy.deepcopy(edit))
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []


def test_fallback_plan_still_applies_over_unrelated_concurrent_edits(svc):
    service, fake, _ = svc
    fake.values["default"]["providers"] = {"lab": {"base_url": "https://a.example", "api_key": "OLD-KEY"}}
    plan = service.fallback_preview(fallback_request(service, {"enabled": True, "chain": chain("spare")}, [confirmation("native")]))
    assert "OLD-KEY" not in json.dumps(json.loads((service.store_path.parent / "plans" / (plan["plan_id"] + ".json")).read_text(encoding="utf-8")))
    # Unrelated: delegation model, an auxiliary role, a credential rotated inside an existing entry.
    fake.values["default"]["delegation.model"] = "outside-child"
    fake.values["default"]["auxiliary.title_generation.provider"] = "zai"
    fake.values["default"]["providers"]["lab"]["api_key"] = "NEW-KEY"
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["default"]["fallback_providers"] == chain("spare")
    assert {key for _profile, key, _value in fake.calls} == {"fallback_providers"}


def test_main_model_save_refuses_a_same_name_alias_added_after_preview(svc):
    service, fake, _ = svc
    plan = service.preview(native_body(service, {"main": route("openai-codex", "next-main", "high")}))
    fake.values["default"]["model.aliases"] = {"next-main": {"provider": "xiaomi", "model": "other"}}
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == [] and fake.values["default"]["model.default"] == "heavy0"


def test_title_save_refuses_a_reasoning_extra_body_added_after_preview_but_not_main_edits(svc):
    service, fake, _ = svc
    plan = service.preview(native_body(service, {"title": route("zai", "t-new", "low")}))
    fake.values["default"]["auxiliary.title_generation.extra_body"] = {"reasoning": {"enabled": False}}
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []
    fake.values["default"].pop("auxiliary.title_generation.extra_body")
    plan = service.preview(native_body(service, {"title": route("zai", "t-new", "low")}))
    fake.values["default"]["delegation.model"] = "outside-child"  # unrelated
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["default"]["auxiliary.title_generation.model"] == "t-new"


def test_combined_plan_records_main_provenance_with_the_model_roles(svc, monkeypatch):
    service, fake, _ = svc
    digests = {"main": "m1", "delegation": "d1", "compression": "c1", "title": "t1"}

    def overlay(self, profile):
        return {"available": True, "managed": {}, "digest": "all",
                "roles": {role: {"available": True, "digest": digests[role]} for role in digests}}
    monkeypatch.setattr(Service, "_read_model_overlay", overlay)
    request = native_body(service, {"title": route("zai", "t-new", "low")})
    request.pop("save_scope")
    request["fallback_updates"] = [{"profile": "default", "native_fallback": {"enabled": True, "chain": chain("spare")}}]
    request["fallback_confirmations"] = [confirmation("native")]
    native = row(service.status())["fallbacks"]["native"]
    request["expected"][0]["native_fallback"] = {"enabled": native["enabled"], "chain": native["chain"], "actual_chain": native["actual_chain"]}
    plan = service.preview(copy.deepcopy(request))
    stored = json.loads((service.store_path.parent / "plans" / (plan["plan_id"] + ".json")).read_text(encoding="utf-8"))
    assert stored["model_provenance"]["default"].startswith("roles:main,title:")
    digests["main"] = "m2"  # main's managed provenance changes between preview and apply
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []
    digests["main"] = "m1"
    digests["delegation"] = "d2"  # unrelated role: still applies
    plan = service.preview(copy.deepcopy(dict(request, expected_revision=service.status()["revision"])))
    digests["compression"] = "c2"
    assert service.apply(plan["plan_id"])["status"] == "applied"
