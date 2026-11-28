"""Compression and title-generation spare models: Hermes' own auxiliary.<task>.fallback_chain.

Exercises the real plan builder (Service._prepare_fallback_preview / apply) over a fake config
writer and a fake key-scoped effective-config snapshot. No Hermes home, no subprocess, no LLM.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from model_router import effective_config
from model_router.service import AUXILIARY_FALLBACK_KEYS, ExternalChange, RevisionConflict, Service, _auxiliary_task_primary, cli_error_payload
from test_fallback_service import setup_service, profile

COMPRESSION = AUXILIARY_FALLBACK_KEYS["compression"]
TITLE = AUXILIARY_FALLBACK_KEYS["title"]
TOKEN_CASES = json.loads((Path(__file__).parent / "fixtures" / "fallback_token_cases.json").read_text(encoding="utf-8"))


def spare(provider: str, model: str) -> dict[str, str]:
    return {"provider": provider, "model": model}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    service, fake, root = setup_service(tmp_path, monkeypatch)
    # What Hermes resolves for the two keys: the stored value, unless a test overlays something.
    state = {"managed": {}, "effective": {}, "reads": [], "on_read": []}

    def auxiliary_snapshot(_service, name, selected=None):
        keys = tuple(selected) if selected else tuple(AUXILIARY_FALLBACK_KEYS.values())
        raw = {key: copy.deepcopy(fake.values[name][key]) for key in keys if key in fake.values[name]}
        effective = {key: copy.deepcopy(raw.get(key)) for key in keys}
        effective.update(copy.deepcopy(state["effective"].get(name, {})))
        state["reads"].append((name, keys))
        # Like effective_config.read_key_scoped: an env expression in any selected key is a warning of
        # the whole snapshot.
        warnings = ["scoped_fallback_env_expression"] if any(effective_config._contains_env_ref(raw.get(key)) for key in keys) else []
        for hook in state["on_read"]:
            hook(name, keys)
        managed = tuple(key for key in state["managed"].get(name, ()) if key in keys)
        return effective_config.make_key_snapshot(keys=keys, raw=raw, effective=effective, managed_keys=managed,
                                                  managed_signature=f"managed:{sorted(managed)}", warnings=warnings)

    monkeypatch.setattr(Service, "_read_auxiliary_snapshot", auxiliary_snapshot)
    return service, fake, state


def frozen(service: Service, name: str) -> dict:
    row = profile(service.status(), name)
    return {"profile": name, "auxiliary_fallback": {task: {"chain": item["chain"], "actual_chain": item["actual_chain"]}
                                                    for task, item in row["auxiliary_fallbacks"].items()}}


def body(service: Service, updates: list[dict], *, confirm: tuple[str, ...] | None = None, expected: bool = True) -> dict:
    names = [update["profile"] for update in updates]
    result = {
        "expected_revision": service.status()["revision"],
        "updates": updates,
        "confirmations": [{"profile": name, "scope": "auxiliary", "allow_additional_cost": True, "allow_task_rerun": False}
                          for name in (names if confirm is None else confirm)],
    }
    if expected:
        result["expected"] = [frozen(service, name) for name in names]
    return result


def test_status_reports_each_task_chain_with_its_flags(env):
    service, fake, state = env
    fake.values["p1"][TITLE] = [spare("deepseek", "flash")]
    rows = {row["name"]: row["auxiliary_fallbacks"] for row in service.status()["profiles"]}
    assert set(rows["default"]) == {"compression", "title"}
    assert rows["default"]["compression"] == {"schema": 1, "key": COMPRESSION, "editable": True, "present": False, "chain": [],
                                              "actual_chain": [], "drift": False, "managed_overlay": False, "env_masked": False,
                                              "primary": {"provider": "openai-codex", "model": "main-model0"}, "warnings": []}
    assert rows["p1"]["title"]["chain"] == [spare("deepseek", "flash")]
    assert rows["p1"]["title"]["present"] is True
    # A value Hermes resolves differently (here an overlay) is drift, and an overlaid key is read-only.
    state["managed"]["p1"] = (TITLE,)
    state["effective"]["p1"] = {TITLE: [spare("xiaomi", "admin-spare")]}
    title = profile(service.status(), "p1")["auxiliary_fallbacks"]["title"]
    assert title["drift"] is True and title["actual_chain"] == [spare("xiaomi", "admin-spare")]
    assert title["editable"] is False and "auxiliary_fallback_managed_overlay" in title["warnings"]


def test_entries_with_more_than_provider_and_model_are_read_only_and_never_rewritten(env):
    service, fake, _state = env
    fake.values["default"][COMPRESSION] = [{"provider": "custom", "model": "m", "base_url": "https://example.invalid/v1"}]
    item = profile(service.status())["auxiliary_fallbacks"]["compression"]
    assert item["editable"] is False and "auxiliary_fallback_advanced_entry" in item["warnings"]
    with pytest.raises(ValueError, match="read-only"):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": []}}]))
    assert fake.calls == []


def test_a_task_chain_is_written_to_its_key_only_for_the_targeted_profile_and_read_back(env):
    service, fake, _state = env
    before = copy.deepcopy(fake.values)
    store_before = service.store_path.read_bytes()
    chain = [spare("deepseek", "flash"), spare("xiaomi", "mimo")]
    plan = service.fallback_preview(body(service, [{"profile": "p1", "auxiliary_fallback": {"compression": chain}}]))
    assert plan["changes"] == [{"profile": "p1", "field": COMPRESSION, "before": [], "after": chain}]
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied"
    assert receipt["applied"] == [{"profile": "p1", "key": COMPRESSION}]
    assert fake.calls == [("p1", COMPRESSION, chain)]
    # The title key stays absent, the other profile is untouched, and no store entry is created.
    assert TITLE not in fake.values["p1"]
    assert fake.values["default"] == before["default"]
    assert service.store_path.read_bytes() == store_before
    assert profile(service.status(), "p1")["auxiliary_fallbacks"]["compression"]["chain"] == chain


def test_off_keeps_an_absent_key_absent_and_writes_an_empty_list_over_a_stored_chain(env):
    service, fake, _state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [], "title": []}}]))
    assert plan["changes"] == []
    assert service.apply(plan["plan_id"])["status"] == "no_change"
    assert fake.calls == [] and COMPRESSION not in fake.values["default"] and TITLE not in fake.values["default"]
    fake.values["default"][TITLE] = [spare("deepseek", "flash")]
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": []}}], confirm=()))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.calls == [("default", TITLE, [])]
    assert COMPRESSION not in fake.values["default"]


def test_setting_spare_models_needs_the_cost_confirmation_turning_them_off_does_not(env):
    service, fake, _state = env
    with pytest.raises(ValueError, match="additional-cost confirmation"):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}], confirm=()))
    assert fake.calls == []


def test_a_spare_equal_to_the_task_primary_is_refused_as_hermes_resolves_it(env):
    service, fake, _state = env
    # provider 'auto' and no model: the task runs on the main model, so the main model is refused.
    main = spare("OpenAI-Codex", fake.values["default"]["model.default"].upper())
    with pytest.raises(ValueError, match="differ from the task's primary"):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [main]}}]))
    # A pinned task route is its own primary: the main model is then a valid spare, the pin is not.
    fake.values["default"]["auxiliary.compression.provider"] = "deepseek"
    fake.values["default"]["auxiliary.compression.model"] = "flash"
    with pytest.raises(ValueError, match="differ from the task's primary"):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("deepseek", "FLASH")]}}]))
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("openai-codex", "main-model0")]}}]))
    assert plan["changes"][0]["field"] == COMPRESSION
    assert fake.calls == []


@pytest.mark.parametrize("chain, message", [
    ([spare("a", f"m{index}") for index in range(6)], "at most five"),
    ([spare("deepseek", "Flash"), spare("DeepSeek", "flash")], "distinct"),
    ([{"provider": "deepseek", "model": "flash", "base_url": "https://example.invalid"}], "provider and model only"),
    ([{"provider": "deepseek", "model": "flash", "api_key": "not-a-secret"}], "provider and model only"),
    ("deepseek/flash", "at most five"),
])
def test_malformed_chains_are_refused_before_any_read_or_write(env, chain, message):
    service, fake, _state = env
    with pytest.raises(ValueError, match=message):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": chain}}]))
    assert fake.calls == []


def test_unknown_tasks_and_an_empty_mapping_are_refused(env):
    service, _fake, _state = env
    for value in ({}, {"vision": []}, {"title_generation": []}, []):
        with pytest.raises(ValueError, match="compression and/or title"):
            service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": value}], confirm=()))


def test_token_rules_match_the_conversation_spares_and_the_page(env):
    service, fake, _state = env
    for provider, ok in TOKEN_CASES["providers"]:
        request = body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare(provider, "valid-model")]}}])
        if ok:
            service.fallback_preview(request)
        else:
            with pytest.raises(ValueError):
                service.fallback_preview(request)
    for model, ok in TOKEN_CASES["models"]:
        request = body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", model)]}}])
        if ok:
            service.fallback_preview(request)
        else:
            with pytest.raises(ValueError):
                service.fallback_preview(request)
    assert fake.calls == []


def test_a_chain_changed_elsewhere_after_load_is_an_external_change_and_nothing_is_written(env):
    service, fake, _state = env
    request = body(service, [{"profile": "p1", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}])
    fake.values["p1"][TITLE] = [spare("xiaomi", "elsewhere")]
    with pytest.raises(ExternalChange) as caught:
        service.fallback_preview(request)
    assert (caught.value.profile, caught.value.field) == ("p1", "auxiliary_fallback.title")
    assert cli_error_payload(caught.value)["conflict"] == {"profile": "p1", "field": "auxiliary_fallback.title"}
    assert fake.calls == []


def test_the_page_must_cover_every_profile_it_writes(env):
    service, _fake, _state = env
    request = body(service, [{"profile": "p1", "auxiliary_fallback": {"title": []}}], confirm=())
    request["expected"] = []
    with pytest.raises(ValueError, match="expected must cover auxiliary_fallback.title of p1"):
        service.fallback_preview(request)


@pytest.mark.parametrize("with_expected", [True, False])
def test_a_key_changed_between_preview_and_apply_refuses_the_apply_and_writes_nothing(env, with_expected):
    service, fake, state = env
    # Without `expected` (an older client) the per-profile snapshot compare-and-set is the guard.
    # A change Hermes resolves differently for the written task (here only its effective value, which
    # no raw-key digest sees) refuses the apply.
    request = body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("deepseek", "flash")]}}], expected=with_expected)
    plan = service.fallback_preview(request)
    state["effective"]["default"] = {COMPRESSION: [spare("xiaomi", "elsewhere")]}
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []
    assert COMPRESSION not in fake.values["default"]


@pytest.mark.parametrize("with_expected", [True, False])
def test_a_sibling_task_changed_between_preview_and_apply_does_not_refuse_the_apply(env, with_expected):
    service, fake, state = env
    request = body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("deepseek", "flash")]}}], expected=with_expected)
    if with_expected:
        request["expected"] = [{"profile": "default", "auxiliary_fallback": {"compression": request["expected"][0]["auxiliary_fallback"]["compression"]}}]
    plan = service.fallback_preview(request)
    fake.values["default"][TITLE] = [spare("xiaomi", "elsewhere")]
    state["effective"]["default"] = {TITLE: [spare("xiaomi", "elsewhere")]}
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied", receipt
    assert fake.calls == [("default", COMPRESSION, [spare("deepseek", "flash")])]
    assert fake.values["default"][TITLE] == [spare("xiaomi", "elsewhere")], "the sibling is never touched"


def test_a_managed_overlay_appearing_after_preview_refuses_the_apply(env):
    service, fake, state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("deepseek", "flash")]}}]))
    state["managed"]["default"] = (COMPRESSION,)
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []


def test_a_readback_hermes_resolves_differently_is_reported_as_partial(env, monkeypatch):
    service, fake, state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}]))
    original = Service._read_auxiliary_snapshot
    reads = {"count": 0}

    def overlay_after_write(self, profile_name, keys=None):
        reads["count"] += 1
        if fake.calls:  # once written, Hermes resolves something else
            state["effective"]["default"] = {TITLE: [spare("other", "model")]}
        return original(self, profile_name, keys)

    monkeypatch.setattr(Service, "_read_auxiliary_snapshot", overlay_after_write)
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "partial"
    assert fake.calls == [("default", TITLE, [spare("deepseek", "flash")])]


def test_older_clients_without_auxiliary_fields_are_unaffected(env):
    service, fake, _state = env
    request = {"expected_revision": service.status()["revision"],
               "updates": [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}], "confirmations": []}
    plan = service.fallback_preview(request)
    service.apply(plan["plan_id"])
    assert all(key not in AUXILIARY_FALLBACK_KEYS.values() for _name, key, _value in fake.calls)
    # A frozen page row from an older client has no auxiliary_fallback field; it is simply not compared.
    old = {"expected_revision": service.status()["revision"],
           "updates": [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}], "confirmations": [],
           "expected": [{"profile": "default", "native_fallback": {k: v for k, v in profile(service.status())["fallbacks"]["native"].items()
                                                                    if k in {"enabled", "chain", "actual_chain"}}}]}
    service.fallback_preview(old)


def test_whole_page_save_carries_auxiliary_chains_checked_against_the_new_main_model(env):
    service, fake, _state = env
    # A delegation role that follows the main model ('auto'): it is resolved again over the new main
    # model, and still none of its keys is written.
    fake.values["default"]["delegation.provider"] = "auto"
    fake.values["default"]["delegation.model"] = ""
    status = service.status()
    row = profile(status)
    models = {role: route for role, route in row["models"].items() if role != "delegation"}
    models["main"] = {"provider": "xiaomi", "model": "new-main", "reasoning": "high"}
    request = {
        "expected_revision": status["revision"], "profile": "default",
        "models": models, "model_targets": ["default"], "routing": {k: v for k, v in row["routing"].items() if k != "fallback"},
        "routing_profiles": [name for name in ("default", "p1") if profile(status, name)["routing"]["enabled"]],
        "fallback_updates": [{"profile": "default", "auxiliary_fallback": {"compression": [spare("xiaomi", "new-main")]}}],
        "fallback_confirmations": [{"profile": "default", "scope": "auxiliary", "allow_additional_cost": True, "allow_task_rerun": False}],
    }
    # The plan pins each saved role to the route the page showed: compression stays on the old main
    # model while main moves to xiaomi/new-main, so the old main model is now that task's own model.
    with pytest.raises(ValueError, match="differ from the task's primary"):
        service.preview({**request, "fallback_updates": [{"profile": "default", "auxiliary_fallback": {"compression": [spare("openai-codex", "main-model0")]}}]})
    plan = service.preview(request)
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied", receipt
    assert ("default", COMPRESSION, [spare("xiaomi", "new-main")]) in fake.calls
    # The page left the delegation role out: none of its keys was written.
    assert not [key for _name, key, _value in fake.calls if key.startswith("delegation.")]


PRIMARY_CASES = json.loads((Path(__file__).parent / "fixtures" / "auxiliary_primary_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", PRIMARY_CASES, ids=lambda case: f"{case['provider']!r}/{case['model']!r}")
def test_the_task_primary_matches_hermes_and_the_page(case):
    assert _auxiliary_task_primary(case["provider"], case["model"], case["main"]) == case["primary"]


def test_auto_auto_runs_on_the_main_model_so_the_main_model_is_refused(env):
    service, fake, _state = env
    fake.values["default"]["auxiliary.title_generation.model"] = "AUTO"
    with pytest.raises(ValueError, match="differ from the task's primary"):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("openai-codex", "main-model0")]}}]))
    assert profile(service.status())["auxiliary_fallbacks"]["title"]["primary"] == {"provider": "openai-codex", "model": "main-model0"}


def test_a_provider_without_a_model_is_not_known_here_so_an_equal_spare_is_not_refused(env):
    service, fake, _state = env
    fake.values["default"]["auxiliary.title_generation.provider"] = "deepseek"
    assert profile(service.status())["auxiliary_fallbacks"]["title"]["primary"] is None
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}]))
    assert plan["changes"][0]["field"] == TITLE


def test_a_primary_change_between_preview_and_apply_refuses_the_apply(env):
    service, fake, _state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}]))
    # The task now runs on the spare's own model: the check made at preview no longer holds.
    fake.values["default"]["auxiliary.title_generation.provider"] = "deepseek"
    fake.values["default"]["auxiliary.title_generation.model"] = "flash"
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert fake.calls == []


def test_env_expression_values_are_never_returned(env):
    service, fake, state = env
    fake.values["p1"][COMPRESSION] = [{"provider": "${AUX_SPARE_PROVIDER}", "model": "${AUX_SPARE_MODEL}"}]
    state["effective"]["p1"] = {COMPRESSION: [spare("SECRET-PROVIDER-MARKER", "SECRET-MODEL-MARKER")]}
    status = service.status()
    dumped = json.dumps(status)
    assert "SECRET-PROVIDER-MARKER" not in dumped and "SECRET-MODEL-MARKER" not in dumped
    assert "AUX_SPARE_PROVIDER" not in dumped
    item = profile(status, "p1")["auxiliary_fallbacks"]["compression"]
    assert item["env_masked"] is True and item["editable"] is False and item["drift"] is False
    assert item["chain"] == item["actual_chain"] == [{"provider": "[env]", "model": "[env]"}]
    with pytest.raises(ValueError, match="read-only"):
        service.fallback_preview(body(service, [{"profile": "p1", "auxiliary_fallback": {"compression": []}}]))
    assert fake.calls == []


def test_a_provider_only_entry_is_shown_with_its_provider_and_read_only(env):
    service, fake, _state = env
    fake.values["default"][TITLE] = [{"provider": "deepseek"}, {"provider": "xiaomi", "model": "auto"}]
    item = profile(service.status())["auxiliary_fallbacks"]["title"]
    assert item["chain"] == [spare("deepseek", ""), spare("xiaomi", "")], "an active chain is never shown as off"
    assert item["editable"] is False and "auxiliary_fallback_provider_only" in item["warnings"]
    with pytest.raises(ValueError, match="read-only"):
        service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": []}}]))


def test_a_sibling_task_changed_elsewhere_does_not_block_the_other_task(env):
    service, fake, _state = env
    request = body(service, [{"profile": "p1", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}])
    request["expected"] = [{"profile": "p1", "auxiliary_fallback": {"title": request["expected"][0]["auxiliary_fallback"]["title"]}}]
    fake.values["p1"][COMPRESSION] = [spare("xiaomi", "elsewhere")]
    assert service.apply(service.fallback_preview(request)["plan_id"])["status"] == "applied"
    assert fake.calls == [("p1", TITLE, [spare("deepseek", "flash")])]


def test_expected_must_cover_each_written_task(env):
    service, _fake, _state = env
    request = body(service, [{"profile": "p1", "auxiliary_fallback": {"title": []}}], confirm=())
    request["expected"] = [{"profile": "p1", "auxiliary_fallback": {"compression": {"chain": [], "actual_chain": []}}}]
    with pytest.raises(ValueError, match="expected must cover auxiliary_fallback.title of p1"):
        service.fallback_preview(request)


def test_an_omitted_delegation_role_keeps_the_canonical_store_route_exactly(env):
    service, fake, _state = env
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    stored_route = {"provider": "stored", "model": "stored-route", "reasoning": "low"}
    data["profiles"]["default"]["models"]["delegation"] = copy.deepcopy(stored_route)
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    status = service.status()
    row = profile(status)
    assert row["actual_models"]["delegation"]["model"] == "delegation-model0", "the native value differs already"
    models = {role: copy.deepcopy(item) for role, item in row["models"].items() if role != "delegation"}
    models["title"] = {"provider": "deepseek", "model": "title-only", "reasoning": "low"}
    request = {"expected_revision": status["revision"], "profile": "default", "save_scope": "models", "models": models,
               "model_targets": ["default"], "routing": {k: v for k, v in row["routing"].items() if k != "fallback"},
               "routing_profiles": [name for name in ("default", "p1") if profile(status, name)["routing"]["enabled"]]}
    receipt = service.apply(service.preview(request)["plan_id"])
    assert receipt["status"] == "applied", receipt
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert after["default"]["models"]["delegation"] == stored_route
    assert after["default"]["models"]["title"]["model"] == "title-only"
    assert "p1" in after and after["p1"] == data["profiles"]["p1"], "untargeted entry untouched"
    assert not [key for _name, key, _value in fake.calls if key.startswith("delegation.")]


def test_a_sibling_env_chain_never_locks_the_other_task(env):
    service, fake, _state = env
    fake.values["p1"][COMPRESSION] = [{"provider": "${AUX_PROVIDER}", "model": "m"}]
    tasks = profile(service.status(), "p1")["auxiliary_fallbacks"]
    assert tasks["compression"]["editable"] is False and tasks["compression"]["env_masked"] is True
    assert tasks["title"]["editable"] is True and tasks["title"]["warnings"] == []
    plan = service.fallback_preview(body(service, [{"profile": "p1", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}]))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.calls == [("p1", TITLE, [spare("deepseek", "flash")])]


def test_a_sibling_that_turns_into_an_env_chain_at_apply_still_yields_applied(env):
    service, fake, _state = env
    request = body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}], expected=False)
    plan = service.fallback_preview(request)
    fake.values["default"][COMPRESSION] = [{"provider": "${AUX_PROVIDER}", "model": "m"}]
    receipt = service.apply(plan["plan_id"])
    assert receipt["status"] == "applied", receipt
    assert fake.calls == [("default", TITLE, [spare("deepseek", "flash")])]


def test_editability_and_the_baseline_come_from_one_read(env):
    service, fake, state = env
    # (without `expected`, so the first read of the written key during preview is the plan's own)
    request = body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}], expected=False)
    state["reads"].clear()

    def overlay_on_second_read(name, keys):
        # A managed overlay appears right after the first read of the written key during preview.
        if name == "default" and TITLE in keys and sum(1 for n, k in state["reads"] if n == "default" and TITLE in k) == 2:
            state["managed"]["default"] = (TITLE,)

    state["on_read"].append(overlay_on_second_read)
    with pytest.raises(RevisionConflict):
        service.fallback_preview(request)
    assert fake.calls == []


# ---- v0.13.1 hardening: per-key digests fail closed, old plans still apply/refuse, uniform status rows ----

def _plan_file(service: Service, plan_id: str) -> Path:
    return service.store_path.parent / "plans" / (plan_id + ".json")


def _edit_plan(service: Service, plan_id: str, edit) -> None:
    path = _plan_file(service, plan_id)
    plan = json.loads(path.read_text(encoding="utf-8"))
    edit(plan)
    path.write_text(json.dumps(plan), encoding="utf-8")


def test_a_new_plan_records_one_digest_per_written_key_and_no_unused_key_list(env):
    service, _fake, _state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("deepseek", "flash")]}}]))
    stored = json.loads(_plan_file(service, plan["plan_id"]).read_text(encoding="utf-8"))
    assert "auxiliary_snapshot_keys" not in stored
    assert set(stored["auxiliary_snapshots"]["default"]) == {COMPRESSION}
    assert set(stored["auxiliary_provenance"]["default"]) == {COMPRESSION}
    assert all(isinstance(value, str) for value in stored["auxiliary_snapshots"]["default"].values())


@pytest.mark.parametrize("field", ["auxiliary_snapshots", "auxiliary_provenance"])
@pytest.mark.parametrize("damage", ["key", "profile", "empty", "type"])
def test_a_plan_without_the_digest_of_a_written_key_never_writes(env, field, damage):
    service, fake, _state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"compression": [spare("deepseek", "flash")]}}]))

    def edit(stored):
        if damage == "key":
            stored[field]["default"] = {TITLE: stored[field]["default"][COMPRESSION]}
        elif damage == "profile":
            stored[field].pop("default")
        elif damage == "empty":
            stored[field]["default"] = {}
        else:
            stored[field]["default"] = {COMPRESSION: None}

    _edit_plan(service, plan["plan_id"], edit)
    try:
        receipt = service.apply(plan["plan_id"])
    except RevisionConflict:
        receipt = None
    assert receipt is None or receipt["status"] != "applied"
    assert fake.calls == [] and COMPRESSION not in fake.values["default"]


def test_a_plan_from_0_13_0_with_its_unused_key_list_still_applies(env):
    service, fake, _state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}]))
    _edit_plan(service, plan["plan_id"], lambda stored: stored.update(auxiliary_snapshot_keys={"default": [TITLE]}))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.calls == [("default", TITLE, [spare("deepseek", "flash")])]


@pytest.mark.parametrize("changed", [False, True])
def test_an_older_one_string_plan_is_checked_over_both_keys(env, changed):
    service, fake, state = env
    plan = service.fallback_preview(body(service, [{"profile": "default", "auxiliary_fallback": {"title": [spare("deepseek", "flash")]}}], expected=False))
    whole = service._read_auxiliary_snapshot("default")

    def edit(stored):
        stored["auxiliary_snapshots"]["default"] = whole.cas_digest
        stored["auxiliary_provenance"]["default"] = whole.provenance_digest

    _edit_plan(service, plan["plan_id"], edit)
    if changed:
        # A one-string digest covers both keys, so even the sibling refuses it (as before 0.13.1).
        state["effective"]["default"] = {COMPRESSION: [spare("xiaomi", "elsewhere")]}
        with pytest.raises(RevisionConflict):
            service.apply(plan["plan_id"])
        assert fake.calls == []
    else:
        assert service.apply(plan["plan_id"])["status"] == "applied"
        assert fake.calls == [("default", TITLE, [spare("deepseek", "flash")])]


def test_cas_holds_fails_closed_on_a_missing_or_malformed_digest(env):
    service, _fake, _state = env
    digest = service._read_auxiliary_snapshot("default", (COMPRESSION,)).cas_digest
    assert service._auxiliary_cas_holds("default", {COMPRESSION: digest}, "cas_digest") is True
    assert service._auxiliary_cas_holds("default", {COMPRESSION: digest}, "cas_digest", COMPRESSION) is True
    assert service._auxiliary_cas_holds("default", {COMPRESSION: digest}, "cas_digest", TITLE) is False
    assert service._auxiliary_cas_holds("default", {COMPRESSION: digest}, "cas_digest", required=[TITLE]) is False
    assert service._auxiliary_cas_holds("default", {}, "cas_digest") is False
    assert service._auxiliary_cas_holds("default", {COMPRESSION: 7}, "cas_digest") is False
    assert service._auxiliary_cas_holds("default", None, "cas_digest") is False


def test_an_unreadable_task_row_has_the_same_fields_as_a_readable_one(env, monkeypatch):
    service, _fake, _state = env
    readable = profile(service.status())["auxiliary_fallbacks"]["compression"]

    def unavailable(_service, name, selected=None):
        raise effective_config.EffectiveConfigUnavailable("not verifiable")

    monkeypatch.setattr(Service, "_read_auxiliary_snapshot", unavailable)
    row = profile(service.status())["auxiliary_fallbacks"]["compression"]
    assert set(row) == set(readable)
    assert row["editable"] is False and row["env_masked"] is False and row["chain"] == [] and row["actual_chain"] == []
    assert row["primary"] == readable["primary"] == {"provider": "openai-codex", "model": "main-model0"}
    assert row["warnings"] == ["auxiliary_fallback_unavailable"]
