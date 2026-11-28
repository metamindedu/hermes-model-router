"""The model section's conversation spare-model save (v0.12.1) against the real plan builder.

The page saves the conversation spare models through the narrow '/fallback-preview' path (with its
`expected` native_fallback), after a scoped models '/preview' when model values change. These tests
pin why: the unscoped combined plan runs the routing pass over every profile, so it writes untargeted
profiles and needs every bystander's models resolved.
"""
import copy
import json
from pathlib import Path

import pytest

from model_router.service import RevisionConflict, ServiceError
from test_fallback_service import setup_service, profile, confirmation

SPARE = {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]}


def bystander_setup(tmp_path, monkeypatch, *, unresolved=False):
    """`default` is the loaded profile; `p1` is an untargeted bystander with task routing off, no stored
    entry and no `skills.disabled` key (optionally without a resolved main model)."""
    service, fake, root = setup_service(tmp_path, monkeypatch)
    # Only the loaded profile has a store entry.
    store = json.loads(service.store_path.read_text(encoding="utf-8"))
    store["profiles"].pop("p1", None)
    service.store_path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    del fake.values["p1"]["skills.disabled"]
    if unresolved:
        fake.values["p1"]["model.provider"] = ""
        fake.values["p1"]["model.default"] = ""
    return service, fake, root


def frozen_native(status, name="default"):
    native = profile(status, name)["fallbacks"]["native"]
    return {"enabled": native["enabled"], "chain": native["chain"], "actual_chain": native["actual_chain"]}


def fallback_preview_body(service, value=SPARE, revision=None):
    """What the page sends: buildFallbackPreviewBody plus the frozen `expected` native_fallback."""
    status = service.status()
    return {"expected_revision": status["revision"] if revision is None else revision,
            "updates": [{"profile": "default", "native_fallback": copy.deepcopy(value)}],
            "confirmations": [confirmation("native")] if value["enabled"] else [],
            "expected": [{"profile": "default", "native_fallback": frozen_native(status)}]}


def unscoped_body(service):
    """The v0.12.1 model-section body (and the whole-page shape): no save_scope, loaded membership."""
    status = service.status()
    current = profile(status)
    routing = {key: value for key, value in copy.deepcopy(current["routing"]).items() if key != "fallback"}
    membership = [row["name"] for row in status["profiles"] if row["routing"]["enabled"]]
    return {"expected_revision": status["revision"], "profile": "default", "models": copy.deepcopy(current["models"]),
            "model_targets": [], "routing": routing, "routing_profiles": membership, "routing_targets": [],
            "fallback_updates": [{"profile": "default", "native_fallback": copy.deepcopy(SPARE)}],
            "fallback_confirmations": [confirmation("native")]}


def models_body(service, main_model):
    status = service.status()
    current = profile(status)
    body = {"expected_revision": status["revision"], "profile": "default", "models": copy.deepcopy(current["models"]),
            "model_targets": ["default"], "routing": {key: value for key, value in copy.deepcopy(current["routing"]).items() if key != "fallback"},
            "routing_profiles": [row["name"] for row in status["profiles"] if row["routing"]["enabled"]],
            "routing_targets": [], "save_scope": "models"}
    body["models"]["main"]["model"] = main_model
    return body


def test_the_unscoped_plan_writes_a_bystander_and_needs_its_models(tmp_path, monkeypatch):
    # Why the page must not send the spare models in an unscoped plan (the v0.12.1 regression).
    service, fake, _ = bystander_setup(tmp_path, monkeypatch)
    assert profile(service.status(), "p1")["routing"]["enabled"] is False
    preview = service.preview(unscoped_body(service))
    bystander = [change for change in preview["changes"] if change["profile"] == "p1"]
    assert [change["field"] for change in bystander] == ["skills.disabled"]
    assert service.apply(preview["plan_id"])["status"] == "applied"
    assert fake.values["p1"]["skills.disabled"] == ["adaptive-coding-orchestration"], "an absent key was materialized"
    (tmp_path / "unresolved").mkdir()
    unresolved, _fake, _ = bystander_setup(tmp_path / "unresolved", monkeypatch, unresolved=True)
    with pytest.raises(ServiceError, match="profile p1 has no resolved main model"):
        unresolved.preview(unscoped_body(unresolved))


@pytest.mark.parametrize("shape", ["whole-page", "routing-scope"])
def test_preexisting_store_wide_plans_also_write_the_bystander(tmp_path, monkeypatch, shape):
    # Not changed by v0.12.1, reported only: the whole-page save (unscoped since before v0.12.0, even
    # for a model-only edit) and every routing-scope save (slot models, re-enable) run the same pass.
    service, fake, _ = bystander_setup(tmp_path, monkeypatch)
    body = unscoped_body(service)
    del body["fallback_updates"], body["fallback_confirmations"]
    if shape == "whole-page":
        body["model_targets"] = ["default"]
        body["models"]["main"]["model"] = "edited-main"
    else:
        body["save_scope"] = "routing"
    preview = service.preview(body)
    assert [change["field"] for change in preview["changes"] if change["profile"] == "p1"] == ["skills.disabled"]


def test_a_scoped_models_body_cannot_carry_spare_models(tmp_path, monkeypatch):
    service, _fake, _ = bystander_setup(tmp_path, monkeypatch)
    body = models_body(service, "main-model0")
    body["fallback_updates"] = [{"profile": "default", "native_fallback": copy.deepcopy(SPARE)}]
    body["fallback_confirmations"] = [confirmation("native")]
    with pytest.raises(ValueError, match="outside the selected save scope"):
        service.preview(body)


@pytest.mark.parametrize("unresolved", [False, True])
def test_the_fallback_path_writes_only_its_target(tmp_path, monkeypatch, unresolved):
    service, fake, _ = bystander_setup(tmp_path, monkeypatch, unresolved=unresolved)
    bystander = copy.deepcopy(fake.values["p1"])
    stored_before = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    preview = service.fallback_preview(fallback_preview_body(service))
    assert {change["profile"] for change in preview["changes"]} == {"default"}
    assert service.apply(preview["plan_id"])["status"] == "applied"
    assert {name for name, _key, _value in fake.calls} == {"default"}
    assert fake.values["p1"] == bystander and "skills.disabled" not in fake.values["p1"], "absent keys stay absent"
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert set(stored) == set(stored_before) == {"default"}, "no store entry is created for the bystander"
    assert stored["default"]["native_fallback"] == SPARE
    assert fake.values["default"]["fallback_providers"] == SPARE["chain"]


@pytest.mark.parametrize("unresolved", [False, True])
def test_models_then_spare_models_chain_on_the_receipt_revision(tmp_path, monkeypatch, unresolved):
    # The page's sequence: scoped models first, then '/fallback-preview' at the revision that apply returned.
    service, fake, _ = bystander_setup(tmp_path, monkeypatch, unresolved=unresolved)
    bystander = copy.deepcopy(fake.values["p1"])
    old_main = profile(service.status())["models"]["main"]["model"]
    first_body = fallback_preview_body(service)
    models = service.preview(models_body(service, "new-main"))
    assert {change["profile"] for change in models["changes"]} == {"default"}
    receipt = service.apply(models["plan_id"])
    assert receipt["status"] == "applied" and receipt["revision"] == first_body["expected_revision"] + 1
    # A spare equal to the old main model is fine once the new main model is stored.
    value = {"enabled": True, "chain": [{"provider": "openai-codex", "model": old_main}]}
    stale = fallback_preview_body(service, value, revision=first_body["expected_revision"])
    with pytest.raises(RevisionConflict, match="revision"):
        service.fallback_preview(stale)
    spare = service.fallback_preview(fallback_preview_body(service, value, revision=receipt["revision"]))
    assert service.apply(spare["plan_id"])["status"] == "applied"
    assert fake.values["default"]["model.default"] == "new-main"
    assert fake.values["default"]["fallback_providers"] == value["chain"]
    assert fake.values["p1"] == bystander and "skills.disabled" not in fake.values["p1"]
    assert set(json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]) == {"default"}


TOKEN_CASES = json.loads((Path(__file__).parent / "fixtures" / "fallback_token_cases.json").read_text(encoding="utf-8"))


def test_the_page_token_fixture_matches_the_service_rules(tmp_path, monkeypatch):
    # tests/test_fallback_desktop.mjs checks the page's up-front validation against the same list.
    service, _fake, _ = bystander_setup(tmp_path, monkeypatch)
    def accepted(provider, model):
        try:
            service._validate_native_fallback({"enabled": True, "chain": [{"provider": provider, "model": model}]})
        except ValueError:
            return False
        return True
    for provider, valid in TOKEN_CASES["providers"]:
        assert accepted(provider, "gpt-6-astra") is valid, provider
    for model, valid in TOKEN_CASES["models"]:
        assert accepted("xiaomi", model) is valid, model
    # Duplicates and the main model are compared with both provider and model case-folded.
    with pytest.raises(ValueError, match="distinct"):
        service._validate_native_fallback({"enabled": True, "chain": [
            {"provider": "Xiaomi", "model": "Spare"}, {"provider": "xiaomi", "model": "spare"}]})


def test_a_spare_differing_from_the_new_main_model_only_in_case_is_refused(tmp_path, monkeypatch):
    # The repro: after the models step stored primary/new-main, the spare primary/NEW-MAIN is refused.
    # The page therefore checks it against the projected main model before the first write.
    service, fake, _ = bystander_setup(tmp_path, monkeypatch)
    body = models_body(service, "new-main")
    body["models"]["main"]["provider"] = "primary"
    receipt = service.apply(service.preview(body)["plan_id"])
    spare = {"enabled": True, "chain": [{"provider": "primary", "model": "NEW-MAIN"}]}
    with pytest.raises(ValueError, match="differ from the primary model"):
        service.fallback_preview(fallback_preview_body(service, spare, revision=receipt["revision"]))
    assert fake.values["default"]["model.default"] == "new-main"


def test_a_spare_is_compared_with_the_real_main_model_not_the_stored_mirror(tmp_path, monkeypatch):
    # Supersedes the stored-main comparison: the main model is the profile's own config. With the
    # main model edited elsewhere, a spare equal to the real main is refused; one equal to the old
    # stored mirror is an ordinary spare.
    service, fake, _ = bystander_setup(tmp_path, monkeypatch)
    stored_main = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["default"]["models"]["main"]
    actual = fake.values["default"]["model.default"] = "runtime-main"
    provider = stored_main["provider"]
    assert stored_main["model"] != actual
    status = service.status()
    assert profile(status)["models"]["main"]["model"] == profile(status)["actual_models"]["main"]["model"] == actual
    runtime_spare = {"enabled": True, "chain": [{"provider": provider.upper(), "model": actual.upper()}]}
    with pytest.raises(ValueError, match="differ from the primary model"):
        service.fallback_preview(fallback_preview_body(service, runtime_spare))
    stored_spare = {"enabled": True, "chain": [{"provider": provider.upper(), "model": stored_main["model"].upper()}]}
    assert service.fallback_preview(fallback_preview_body(service, stored_spare))["changes"]
