"""Compare-and-set on the /preview -> /apply store path against what the page froze at load."""
from __future__ import annotations

import copy
import json

import pytest

from model_router.service import ExternalChange, RevisionConflict, Service, SKILL_NAME
from test_service import find_profile, setup_home
from test_combined_preview import setup as combined_setup, body as combined_body, confirmation
from test_native_service import fixture  # noqa: F401 (pytest fixture)
from model_router import native_service, native_settings as ns


def setup(tmp_path, monkeypatch):
    root, cli = setup_home(tmp_path, monkeypatch)
    service = Service(root=root, writer=cli.writer)
    service.initialize(["default", "p1", "p2"])
    cli.calls.clear()
    return service, cli


def mapping(row):
    """The page's pageExpectation(): the status values a store save may overwrite (see the fixture)."""
    routing = row["routing"]
    drift = row.get("drift") or []
    # The routing skill's own switch: the status reports a "skills.disabled" drift when it differs
    # from the canonical flag, and "skills.disabled_unavailable" when it cannot be read.
    skill_enabled = None if "skills.disabled_unavailable" in drift else bool(routing["enabled"]) != ("skills.disabled" in drift)
    out = {"models": copy.deepcopy(row["models"]), "actual_models": copy.deepcopy(row.get("actual_models") or {}),
           "routing": {"enabled": bool(routing["enabled"]), "heavy": routing.get("heavy"), "light": routing.get("light"),
                       "slots": routing.get("slots"), "skill_enabled": skill_enabled}}
    native = (row.get("fallbacks") or {}).get("native")
    if native:
        out["native_fallback"] = {"enabled": native.get("enabled"), "chain": native.get("chain", []), "actual_chain": native.get("actual_chain", [])}
    # The compression and title-generation spare models (auxiliaryExpectation in the page).
    auxiliary = row.get("auxiliary_fallbacks")
    if auxiliary:
        out["auxiliary_fallback"] = {task: {"chain": copy.deepcopy(item["chain"]), "actual_chain": copy.deepcopy(item["actual_chain"])}
                                     for task, item in auxiliary.items()}
    return out


def frozen(status, name, *fields):
    """What the page sends: the status values it showed for one target, per written field."""
    value = mapping(find_profile(status, name))
    return {"profile": name, **{field: value[field] for field in fields}}


def model_body(status, source="p1", targets=("p1",)):
    row = find_profile(status, source)
    return {
        "expected_revision": status["revision"], "profile": source, "save_scope": "models",
        "models": copy.deepcopy(row["models"]), "model_targets": list(targets),
        "routing": {key: value for key, value in copy.deepcopy(row["routing"]).items() if key != "fallback"},
        "routing_profiles": [item["name"] for item in status["profiles"] if item["routing"]["enabled"]],
        "routing_targets": [],
    }


def test_an_external_actual_model_change_refuses_the_save_and_writes_nothing(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status, targets=["p1", "p2"])
    request["models"]["delegation"]["model"] = "my-delegation-edit"
    request["expected"] = [frozen(status, name, "models", "actual_models") for name in ("p1", "p2")]
    store = service.store_path.read_bytes()
    # The main model changes in p2's own config while the page is open (the stored row does not).
    cli.values["p2"]["model.default"] = "changed-elsewhere"
    with pytest.raises(RevisionConflict, match=r"EXTERNAL_CHANGE profile=p2 field=actual_models\.main"):
        service.preview(copy.deepcopy(request))
    assert cli.calls == [] and service.store_path.read_bytes() == store
    # Changed between preview and apply: apply refuses before the first write.
    cli.values["p2"]["model.default"] = "heavy2"
    plan = service.preview(copy.deepcopy(request))["plan_id"]
    cli.values["p1"]["model.default"] = "changed-after-preview"
    with pytest.raises(RevisionConflict, match=r"EXTERNAL_CHANGE profile=p1 field=actual_models\.main"):
        service.apply(plan)
    assert cli.calls == [] and service.store_path.read_bytes() == store


def test_matching_expectations_apply_and_legacy_bodies_keep_the_old_behaviour(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status)
    request["models"]["delegation"]["model"] = "my-delegation-edit"
    request["expected"] = [frozen(status, "p1", "models", "actual_models")]
    assert service.apply(service.preview(copy.deepcopy(request))["plan_id"])["status"] == "applied"
    assert cli.values["p1"]["delegation.model"] == "my-delegation-edit"
    # An older client sends no `expected`: an external change is not detected, as before.
    status = service.status()
    legacy = model_body(status)
    legacy["models"]["delegation"]["model"] = "legacy-edit"
    cli.values["p1"]["model.default"] = "changed-elsewhere"
    assert service.apply(service.preview(legacy)["plan_id"])["status"] == "applied"
    assert cli.values["p1"]["model.default"] == find_profile(status, "p1")["models"]["main"]["model"]


def test_expectations_must_cover_every_written_profile_and_field(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status, targets=["p1", "p2"])
    request["expected"] = [frozen(status, "p1", "models", "actual_models")]
    with pytest.raises(ValueError, match="expected must cover actual_models of p2"):
        service.preview(copy.deepcopy(request))
    request["expected"].append(frozen(status, "p2", "models"))
    with pytest.raises(ValueError, match="expected must cover actual_models of p2"):
        service.preview(copy.deepcopy(request))
    # Routing writes need the routing the page saw.
    routing = model_body(status)
    routing.update(save_scope="routing", model_targets=[], routing_targets=["p1"])
    routing["routing"]["light"] = {"follow": "custom", "custom": {"provider": "deepseek", "model": "routed-light", "reasoning": "low"}}
    routing["expected"] = []
    with pytest.raises(ValueError, match="expected must cover routing of p1"):
        service.preview(copy.deepcopy(routing))
    routing["expected"] = [frozen(status, "p1", "routing")]
    assert service.apply(service.preview(copy.deepcopy(routing))["plan_id"])["status"] == "applied"
    for bad in ([{"profile": "p1"}], [{"profile": "p1", "unknown": 1}], [frozen(status, "p1", "models")] * 2):
        request["expected"] = bad
        with pytest.raises(ValueError):
            service.preview(copy.deepcopy(request))
    assert [call for call in cli.calls if call[1] != "skills.disabled"] == []


def test_the_follow_up_write_of_a_combined_save_carries_the_frozen_expectations(tmp_path, monkeypatch):
    # The model section writes the delegation method first (its own digest-guarded endpoint), then
    # the store. The second /preview carries what the page froze at load; the first write touches
    # none of those fields, so nothing is advanced, and a change elsewhere in between is refused.
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status)
    request["models"]["delegation"]["model"] = "follow-up-edit"
    request["expected"] = [frozen(status, "p1", "models", "actual_models")]
    first = service.preview(copy.deepcopy(request))  # the validation pass before the first write
    assert first["plan_id"]
    cli.values["p1"]["model.default"] = "changed-between-the-two-writes"
    with pytest.raises(RevisionConflict, match=r"EXTERNAL_CHANGE profile=p1 field=actual_models\.main"):
        service.preview(copy.deepcopy(request))
    assert cli.calls == []


def test_a_whole_page_save_guards_its_conversation_fallback_and_the_standalone_save_too(tmp_path, monkeypatch):
    service, fake, _ = combined_setup(tmp_path, monkeypatch)
    status = service.status()
    proposal = combined_body(service)
    proposal["fallback_updates"] = [{"profile": "default", "native_fallback": {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]}}]
    proposal["fallback_confirmations"] = [confirmation("native", "default")]
    proposal["expected"] = []
    with pytest.raises(ValueError, match="expected must cover native_fallback of default"):
        service.preview(copy.deepcopy(proposal))
    proposal["expected"] = [frozen(status, "default", "native_fallback")]
    fake.values["default"]["fallback_providers"] = [{"provider": "elsewhere", "model": "external-spare"}]
    with pytest.raises(RevisionConflict, match="EXTERNAL_CHANGE profile=default field=native_fallback"):
        service.preview(copy.deepcopy(proposal))
    standalone = {"expected_revision": status["revision"], "updates": copy.deepcopy(proposal["fallback_updates"]),
                  "confirmations": copy.deepcopy(proposal["fallback_confirmations"]), "expected": copy.deepcopy(proposal["expected"])}
    with pytest.raises(RevisionConflict, match="EXTERNAL_CHANGE profile=default field=native_fallback"):
        service.fallback_preview(copy.deepcopy(standalone))
    assert fake.calls == []
    fresh = service.status()
    proposal["expected"] = standalone["expected"] = [frozen(fresh, "default", "native_fallback")]
    assert service.apply(service.preview(copy.deepcopy(proposal))["plan_id"])["status"] == "applied"
    assert fake.values["default"]["fallback_providers"] == [{"provider": "xiaomi", "model": "native-spare"}]
    with pytest.raises(ValueError, match="conversation fallback only"):
        service.fallback_preview({**standalone, "updates": [{"profile": "default", "routing_fallback": {"enabled": False, "heavy": None, "light": None}}]})


def test_the_conflict_reaches_the_cli_bridge_as_a_structured_payload(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status)
    request["expected"] = [frozen(status, "p1", "models", "actual_models")]
    cli.values["p1"]["delegation.model"] = "changed-elsewhere"
    with pytest.raises(ExternalChange) as caught:
        service.preview(request)
    # __init__.py prints cli_error_payload(exc) as the MODEL_ROUTER_JSON error frame.
    from model_router.service import cli_error_payload
    payload = cli_error_payload(caught.value)
    assert payload["error"] == "ExternalChange"
    assert payload["conflict"] == {"profile": "p1", "field": "actual_models.delegation"}
    assert "conflict" not in cli_error_payload(ValueError("x"))
    assert (caught.value.profile, caught.value.field) == ("p1", "actual_models.delegation")
    assert isinstance(caught.value, RevisionConflict)


FIXTURE = json.loads((__import__("pathlib").Path(__file__).with_name("fixtures") / "page_expectation_contract.json").read_text(encoding="utf-8"))


def test_the_page_mapping_matches_the_generated_fixture():
    # Generated from desktop/plugin.js pageExpectation() by tests/test_native_contract_desktop.mjs.
    assert FIXTURE["generated_by"] == "tests/test_native_contract_desktop.mjs"
    assert mapping(FIXTURE["row"]) == FIXTURE["expectation"]
    assert FIXTURE["preview_expected"] == [{"profile": "p1", **{key: FIXTURE["expectation"][key]
                                                                for key in ("actual_models", "models", "native_fallback", "routing")},
                                            # only the task the body writes (title)
                                            "auxiliary_fallback": {"title": FIXTURE["expectation"]["auxiliary_fallback"]["title"]}}]
    # The compression and title-generation spare models are frozen per task, in the service's shape.
    assert set(FIXTURE["expectation"]["auxiliary_fallback"]) == {"compression", "title"}
    assert Service._valid_page_expectation("auxiliary_fallback", FIXTURE["expectation"]["auxiliary_fallback"]) is True


def test_the_mapped_status_rows_are_exactly_what_the_service_compares(tmp_path, monkeypatch):
    service, fake, _ = combined_setup(tmp_path, monkeypatch)
    # One profile with a stored entry and conversation spare models, one without a stored entry.
    proposal = combined_body(service)
    proposal["fallback_updates"] = [{"profile": "default", "native_fallback": {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]}}]
    proposal["fallback_confirmations"] = [confirmation("native", "default")]
    service.apply(service.preview(proposal)["plan_id"])
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"].pop("p1", None)
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    status = service.status()
    entries = dict(data["profiles"])
    names = [row["name"] for row in status["profiles"]]
    assert "p1" in names and "p1" not in entries
    for name in names:
        value = mapping(find_profile(status, name))
        for field in service.PAGE_EXPECTATION_FIELDS:
            current = json.loads(json.dumps(service._page_expectation_current(name, field, entries)))
            assert value[field] == current, (name, field)
        # The whole mapped row is accepted as `expected` and holds.
        service._check_page_expectations(service._parse_page_expectations([{"profile": name, **value}], names), entries)


def test_delegation_preview_is_already_guarded_by_the_frozen_per_target_digest(fixture):
    # /delegation-preview needs no `expected`: each update carries the digest the page froze at load
    # (it covers the target's backend, both spare policies and the allow-list, plus the plugin code),
    # checked at preview, and the plan's config CAS is checked again before the first write.
    service, calls, writer = fixture
    frozen_digest = native_service.status(service, "p1")["digest"]
    update = {"profile": "p1", "expected_digest": frozen_digest, "backend": "model-router-profiles", "allow_profile_access": False}
    writer("p1", ns.KEY_BACKEND, "model-router-auto")  # changed elsewhere after the page loaded
    calls.clear()
    with pytest.raises(RevisionConflict, match="reload before saving"):
        service.delegation_preview({"expected_revision": 0, "updates": [update]})
    update["expected_digest"] = native_service.status(service, "p1")["digest"]
    plan = service.delegation_preview({"expected_revision": 0, "updates": [update]})["plan_id"]
    writer("p1", ns.KEY_BACKEND, "model-router")  # and again between preview and apply
    calls.clear()
    with pytest.raises(RevisionConflict):
        service.apply(plan)
    assert calls == []


def test_apply_refuses_when_the_store_changed_for_a_profile_the_save_did_not_target(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    for with_expected in (True, False):
        request = model_body(status)
        request["models"]["delegation"]["model"] = "p1-only-edit"
        if with_expected:
            request["expected"] = [frozen(status, "p1", "models", "actual_models")]
        plan = service.preview(copy.deepcopy(request))["plan_id"]
        data = json.loads(service.store_path.read_text(encoding="utf-8"))
        data["profiles"]["p2"]["routing"]["fallback"]["heavy"] = {"provider": "spare", "model": f"kept-{with_expected}", "reasoning": "high"}
        service.store_path.write_text(json.dumps(data), encoding="utf-8")  # same revision
        changed = service.store_path.read_bytes()
        with pytest.raises(RevisionConflict, match="settings changed since preview"):
            service.apply(plan)
        assert service.store_path.read_bytes() == changed, "p2 is not reverted and nothing is written"
        assert cli.calls == []


def test_a_routing_save_never_re_enables_a_profile_switched_off_in_its_own_config(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    assert frozen(status, "p2", "routing")["routing"]["skill_enabled"] is True
    routing = model_body(status)
    routing.update(save_scope="routing", model_targets=[], routing_targets=[])
    routing["expected"] = [frozen(status, name, "routing") for name in ("default", "p1", "p2")]
    cli.values["p2"]["skills.disabled"] = [SKILL_NAME]  # switched off elsewhere, canonical flag unchanged
    with pytest.raises(ExternalChange, match=r"profile=p2 field=routing"):
        service.preview(copy.deepcopy(routing))
    assert cli.calls == [] and cli.values["p2"]["skills.disabled"] == [SKILL_NAME]


def test_expected_is_bounded_by_the_profiles_not_a_fixed_count(tmp_path, monkeypatch):
    names = ["default", *[f"p{index}" for index in range(1, 71)]]
    root, cli = setup_home(tmp_path, monkeypatch, profiles=tuple(names))
    service = Service(root=root, writer=cli.writer)
    service.initialize(names)
    cli.calls.clear()
    status = service.status()
    assert len(status["profiles"]) == 71
    routing = model_body(status)
    routing.update(save_scope="routing", model_targets=[], routing_targets=["p1"])
    routing["routing"]["light"] = {"follow": "custom", "custom": {"provider": "deepseek", "model": "many", "reasoning": "low"}}
    routing["expected"] = [frozen(status, name, "routing") for name in names]
    assert service.apply(service.preview(copy.deepcopy(routing))["plan_id"])["status"] == "applied"


def test_expected_values_are_strict_and_null_is_not_absent(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    good = frozen(status, "p1", "models", "actual_models", "routing")
    request = model_body(status)
    request["models"]["delegation"]["model"] = "edit"
    def bad(mutate):
        item = copy.deepcopy(good)
        mutate(item)
        return [item]
    cases = {
        "null": None,
        "not a list": {"profile": "p1"},
        "int for a bool": bad(lambda item: item["routing"].update(enabled=1)),
        "int for skill switch": bad(lambda item: item["routing"].update(skill_enabled=0)),
        "unknown nested key": bad(lambda item: item["models"]["main"].update(extra="x")),
        "unknown routing key": bad(lambda item: item["routing"].update(extra=True)),
        "number for a string": bad(lambda item: item["actual_models"]["main"].update(model=5)),
        "oversize string": bad(lambda item: item["actual_models"]["main"].update(model="m" * 600)),
        "unknown role": bad(lambda item: item["models"].update(other=item["models"]["main"])),
        "more entries than profiles": [frozen(status, "p1", "models")] * 4,
    }
    for label, value in cases.items():
        with pytest.raises(ValueError):
            service.preview({**copy.deepcopy(request), "expected": value})
        assert cli.calls == [], label
    # Extra expectations only add checks: covering p2 too never makes p2 a target.
    request["expected"] = [good, frozen(status, "p2", "models", "actual_models", "routing")]
    assert service.apply(service.preview(copy.deepcopy(request))["plan_id"])["status"] == "applied"
    assert {call[0] for call in cli.calls} == {"p1"}


def test_a_change_that_breaks_model_resolution_is_reported_as_that_field(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status)
    request["models"]["delegation"]["model"] = "edit"
    request["expected"] = [frozen(status, "p1", "models", "actual_models")]
    cli.values["p1"]["model.default"] = ""  # cleared elsewhere: p1 no longer resolves a main model
    with pytest.raises(ExternalChange) as caught:
        service.preview(copy.deepcopy(request))
    assert (caught.value.profile, caught.value.field) == ("p1", "actual_models.main")
    assert cli.calls == []


def _skill_off_elsewhere(cli, name="p2"):
    cli.values[name]["skills.disabled"] = [SKILL_NAME]  # canonical flag stays on


def test_an_unrelated_save_never_undoes_a_skill_opt_out(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    _skill_off_elsewhere(cli)
    status = service.status()
    assert find_profile(status, "p2")["routing"]["enabled"] is True
    # A whole-page save of a main-model edit sends the canonical membership, which includes p2.
    body = model_body(status)
    del body["save_scope"]
    body["routing_targets"] = []
    body["models"]["main"]["model"] = "edited-main"
    assert "p2" in body["routing_profiles"]
    preview = service.preview(copy.deepcopy(body))
    assert [change for change in preview["changes"] if change["profile"] == "p2"] == []
    service.apply(preview["plan_id"])
    assert cli.values["p2"]["skills.disabled"] == [SKILL_NAME]
    # The routing scope too.
    status = service.status()
    routing = model_body(status)
    routing.update(save_scope="routing", model_targets=[], routing_targets=[])
    assert [change for change in service.preview(routing)["changes"] if change["profile"] == "p2"] == []


def test_an_explicit_re_enable_still_works_and_the_label_tells_the_skill_state(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    _skill_off_elsewhere(cli)
    status = service.status()
    request = model_body(status)
    request.update(save_scope="routing", model_targets=[], routing_targets=[], reenable_profiles=["p2"])
    preview = service.preview(copy.deepcopy(request))
    assert [change for change in preview["changes"] if change["profile"] == "p2"] == [
        {"profile": "p2", "field": "skills.disabled", "before": "disabled", "after": "enabled"}]
    assert service.apply(preview["plan_id"])["status"] == "applied"
    assert cli.values["p2"]["skills.disabled"] == []
    # The existing flow: a canonically off profile added to routing_profiles is turned on, skill included.
    status = service.status()
    off = model_body(status)
    off.update(save_scope="routing", model_targets=[], routing_targets=[])
    off["routing_profiles"] = [name for name in off["routing_profiles"] if name != "p1"]
    off["routing"]["enabled"] = False
    service.apply(service.preview(copy.deepcopy(off))["plan_id"])
    assert SKILL_NAME in cli.values["p1"]["skills.disabled"]
    status = service.status()
    on = model_body(status)
    on.update(save_scope="routing", model_targets=[], routing_targets=[])
    on["routing_profiles"] = sorted({*on["routing_profiles"], "p1"})
    on["routing"]["enabled"] = True
    preview = service.preview(copy.deepcopy(on))
    assert {"profile": "p1", "field": "skills.disabled", "before": "disabled", "after": "enabled"} in preview["changes"]
    service.apply(preview["plan_id"])
    assert cli.values["p1"]["skills.disabled"] == []
    for bad in (["p2", "p2"], ["ghost"], "p2"):
        with pytest.raises(ValueError):
            service.preview({**copy.deepcopy(request), "reenable_profiles": bad})
    excluded = {**copy.deepcopy(request), "routing_profiles": [name for name in request["routing_profiles"] if name != "p2"]}
    with pytest.raises(ValueError, match="also be in routing_profiles"):
        service.preview(excluded)
    with pytest.raises(ValueError, match="outside the selected save scope"):
        service.preview({**model_body(status), "reenable_profiles": ["p2"]})


def _drop_entry(service, name):
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"].pop(name, None)
    service.store_path.write_text(json.dumps(data), encoding="utf-8")


def test_no_plan_materialises_an_entry_for_an_untargeted_profile(tmp_path, monkeypatch):
    service, fake, _ = combined_setup(tmp_path, monkeypatch)
    _drop_entry(service, "p1")
    status = service.status()
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    untouched = {name: entry for name, entry in stored.items() if name != "default"}
    # Standalone conversation fallback for `default` only.
    service.apply(service.fallback_preview({"expected_revision": status["revision"],
        "updates": [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}], "confirmations": []})["plan_id"])
    after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert "p1" not in after and {name: after[name] for name in untouched} == untouched
    # Whole-page, routing-scope and the combined plan, each targeting `default` only.
    for scope in (None, "routing", "combined"):
        status = service.status()
        request = combined_body(service)
        request["routing_targets"] = ["default"]
        request["routing"].pop("fallback", None)
        request["routing"]["light"] = {"follow": "custom", "custom": {"provider": "deepseek", "model": f"light-{scope}", "reasoning": "low"}}
        if scope == "routing":
            request["save_scope"] = "routing"
        if scope == "combined":
            request["fallback_updates"] = [{"profile": "default", "native_fallback": {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]}}]
            request["fallback_confirmations"] = [confirmation("native", "default")]
        assert service.apply(service.preview(request)["plan_id"])["status"] == "applied", scope
        after = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
        assert "p1" not in after, scope
        assert {name: after[name] for name in untouched} == untouched, scope
    # A routing target without an entry still gets one: it is targeted.
    status = service.status()
    request = combined_body(service)
    request.update(save_scope="routing", routing_targets=["p1"])
    request["routing"].pop("fallback", None)
    request["routing"]["light"] = {"follow": "custom", "custom": {"provider": "deepseek", "model": "for-p1", "reasoning": "low"}}
    service.apply(service.preview(request)["plan_id"])
    assert json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["p1"]["routing"]["light"]["custom"]["model"] == "for-p1"


def test_apply_re_checks_the_store_right_before_replacing_it(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status)
    request["models"]["delegation"]["model"] = "edit"
    plan = service.preview(copy.deepcopy(request))["plan_id"]
    original_backup = Service._backup_config
    def backup_then_change(self, profile, stamp):
        original_backup(self, profile, stamp)
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        data["profiles"]["p2"]["routing"]["fallback"]["heavy"] = {"provider": "spare", "model": "during-apply", "reasoning": "high"}
        self.store_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(Service, "_backup_config", backup_then_change)
    with pytest.raises(RevisionConflict, match="during apply; nothing was written"):
        service.apply(plan)
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert stored["p2"]["routing"]["fallback"]["heavy"]["model"] == "during-apply"
    assert stored["p1"]["models"]["delegation"]["model"] != "edit"
    assert cli.calls == []


def _whole_page(status, source="default", targets=("default", "p1")):
    request = model_body(status, source=source, targets=targets)
    del request["save_scope"]
    request["expected"] = [frozen(status, name, "models", "actual_models", "routing") for name in sorted({*targets, *request["routing_profiles"]})]
    return request


@pytest.mark.parametrize("scope", ["models", None, "combined"])
def test_a_copy_with_a_noop_target_without_a_store_entry_applies(tmp_path, monkeypatch, scope):
    service, cli = setup(tmp_path, monkeypatch)
    _drop_entry(service, "default")
    status = service.status()
    # The draft is default's own current models: `default` is a NOOP target, p1 needs the copy.
    request = _whole_page(status)
    assert find_profile(status, "p1")["actual_models"] != request["models"]
    if scope == "models":
        request["save_scope"] = "models"
        request["expected"] = [frozen(status, name, "models", "actual_models") for name in ("default", "p1")]
    if scope == "combined":
        request["fallback_updates"] = [{"profile": "p1", "native_fallback": {"enabled": False, "chain": []}}]
        request["expected"] = [{**item, **({"native_fallback": frozen(status, "p1", "native_fallback")["native_fallback"]} if item["profile"] == "p1" else {})} for item in request["expected"]]
    preview = service.preview(copy.deepcopy(request))
    receipt = service.apply(preview["plan_id"])
    assert receipt["status"] == "applied" and receipt["remaining"] == [], receipt
    assert service._actual_models("p1") == request["models"] == service._actual_models("default")
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert ("default" in stored) is (scope == "models"), "only the models scope keeps its explicit-target entry"


def test_a_routing_copy_with_a_noop_target_without_a_store_entry_applies(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    _drop_entry(service, "default")
    status = service.status()
    request = model_body(status, source="default", targets=())
    request.update(save_scope="routing", routing_targets=["default", "p1"])
    # default's routing is the submitted one (NOOP); p1's differs.
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"]["p1"]["routing"]["light"] = {"follow": "custom", "custom": {"provider": "deepseek", "model": "p1-own", "reasoning": "low"}}
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    status = service.status()
    request["expected"] = [frozen(status, row["name"], "routing") for row in status["profiles"]]
    receipt = service.apply(service.preview(copy.deepcopy(request))["plan_id"])
    assert receipt["status"] == "applied", receipt
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert "default" not in stored and stored["p1"]["routing"]["light"] == request["routing"]["light"]


def test_a_spare_model_save_with_a_noop_target_without_a_store_entry_applies(tmp_path, monkeypatch):
    service, fake, _ = combined_setup(tmp_path, monkeypatch)
    _drop_entry(service, "p1")
    status = service.status()
    noop = find_profile(status, "p1")["fallbacks"]["native"]
    updates = [{"profile": "default", "native_fallback": {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]}},
               {"profile": "p1", "native_fallback": {"enabled": noop["enabled"], "chain": noop["chain"]}}]
    request = {"expected_revision": status["revision"], "updates": updates, "confirmations": [confirmation("native", "default")],
               "expected": [frozen(status, name, "native_fallback") for name in ("default", "p1")]}
    receipt = service.apply(service.fallback_preview(request)["plan_id"])
    assert receipt["status"] == "applied" and receipt["remaining"] == [], receipt


def test_a_timeout_save_with_a_noop_target_without_a_store_entry_applies(tmp_path, monkeypatch):
    from test_role_timeouts import _package
    service, cli = setup(tmp_path, monkeypatch)
    for name in ("p1", "p2"):
        (_package(service._profile_home(name)) / "routing.py").write_text("ROUTED_ROLE_TIMEOUTS_SUPPORTED = True\n", encoding="utf-8")
    _drop_entry(service, "p2")
    status = service.status()
    request = model_body(status, targets=())
    request.update(save_scope="timeouts", timeout_updates=[
        {"profile": "p1", "expected_revision": 0, "delegate_total_seconds": 120, "routed_light_total_seconds": 1800, "routed_heavy_total_seconds": 7200},
        {"profile": "p2", "expected_revision": 0, "delegate_total_seconds": 0, "routed_light_total_seconds": 3600, "routed_heavy_total_seconds": 3600}])
    receipt = service.apply(service.preview(copy.deepcopy(request))["plan_id"])
    assert receipt["status"] == "applied", receipt
    assert "p2" not in json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]


def test_an_untargeted_entry_is_kept_byte_for_byte(tmp_path, monkeypatch):
    service, cli = setup(tmp_path, monkeypatch)
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    for name in ("p2", "default"):
        data["profiles"][name].pop("delegation_fallback", None)
        data["profiles"][name]["fallback_consent"].pop("delegation", None)
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    untouched = copy.deepcopy(data["profiles"]["p2"])
    for scope in ("models", None):
        status = service.status()
        request = model_body(status)
        request["models"]["delegation"]["model"] = f"edit-{scope}"
        if scope is None:
            del request["save_scope"]
        assert service.apply(service.preview(copy.deepcopy(request))["plan_id"])["status"] == "applied"
        stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
        assert stored["p2"] == untouched, scope
        assert "delegation_fallback" not in stored["default"], scope
    status = service.status()
    service.apply(service.fallback_preview({"expected_revision": status["revision"],
        "updates": [{"profile": "p1", "native_fallback": {"enabled": False, "chain": []}}], "confirmations": []})["plan_id"])
    assert json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["p2"] == untouched
    assert service.status()["revision"] >= 1  # the kept entries still load


@pytest.mark.parametrize("canonical,skill", [(True, True), (True, False), (False, True), (False, False)])
def test_the_native_method_needs_both_routing_switches_like_the_page_rule(fixture, monkeypatch, canonical, skill):
    from test_native_service import body as native_body
    service, calls, writer = fixture
    monkeypatch.setattr(service, "routing_config", Service.routing_config.__get__(service))
    service.initialize(["default", "p1", "p2"])
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    data["profiles"]["p1"]["routing"]["enabled"] = canonical
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    writer("p1", "skills.disabled", [] if skill else [SKILL_NAME])
    row = find_profile(service.status(), "p1")
    # The page's routingEffectivelyOn(row): canonical flag on AND the skill's own switch on.
    page_rule = row["routing"]["enabled"] is True and mapping(row)["routing"]["skill_enabled"] is True
    assert page_rule is (canonical and skill)
    request = native_body(service, "p1")
    request["expected_revision"] = service.status()["revision"]
    if page_rule:
        native_service.preview(service, request)
    else:
        with pytest.raises(ValueError, match="purpose routing is disabled"):
            native_service.preview(service, request)


def _drop_retired_keys(service, *names):
    data = json.loads(service.store_path.read_text(encoding="utf-8"))
    for name in names:
        data["profiles"][name].pop("delegation_fallback", None)
        data["profiles"][name]["fallback_consent"].pop("delegation", None)
    service.store_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def test_a_changed_target_keeps_absent_retired_keys_absent(tmp_path, monkeypatch):
    service, fake, _ = combined_setup(tmp_path, monkeypatch)
    _drop_retired_keys(service, "default")
    status = service.status()
    request = {"expected_revision": status["revision"], "confirmations": [confirmation("native", "default")],
               "updates": [{"profile": "default", "native_fallback": {"enabled": True, "chain": [{"provider": "xiaomi", "model": "native-spare"}]}}]}
    assert service.apply(service.fallback_preview(request)["plan_id"])["status"] == "applied"
    entry = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]["default"]
    assert entry["native_fallback"]["chain"] == [{"provider": "xiaomi", "model": "native-spare"}]
    assert entry["fallback_consent"]["native"] is not None
    assert "delegation_fallback" not in entry and "delegation" not in entry["fallback_consent"]


def test_a_model_save_keeps_absent_retired_keys_absent_on_its_target(tmp_path, monkeypatch):
    service2, cli = setup(tmp_path, monkeypatch)
    _drop_retired_keys(service2, "p1")
    status = service2.status()
    body = model_body(status)
    body["models"]["delegation"]["model"] = "changed"
    assert service2.apply(service2.preview(body)["plan_id"])["status"] == "applied"
    entry = json.loads(service2.store_path.read_text(encoding="utf-8"))["profiles"]["p1"]
    assert entry["models"]["delegation"]["model"] == "changed"
    assert "delegation_fallback" not in entry and "delegation" not in entry["fallback_consent"]
    assert find_profile(service2.status(), "p1")["models"]["delegation"]["model"] == "changed"


def test_the_store_is_re_checked_after_the_new_payload_is_synced(tmp_path, monkeypatch):
    import os as os_module
    service, cli = setup(tmp_path, monkeypatch)
    status = service.status()
    request = model_body(status)
    request["models"]["delegation"]["model"] = "edit"
    plan = service.preview(copy.deepcopy(request))["plan_id"]
    real_fsync, changed = os_module.fsync, []
    def fsync_then_change(fd):
        real_fsync(fd)
        pending = list(service.store_path.parent.glob(f".{service.store_path.name}.*.tmp"))
        if pending and not changed:
            changed.append(True)
            data = json.loads(service.store_path.read_text(encoding="utf-8"))
            data["profiles"]["p2"]["routing"]["light"] = {"follow": "custom", "custom": {"provider": "deepseek", "model": "elsewhere", "reasoning": "low"}}
            service.store_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(os_module, "fsync", fsync_then_change)
    with pytest.raises(RevisionConflict, match="during apply; nothing was written"):
        service.apply(plan)
    assert changed
    stored = json.loads(service.store_path.read_text(encoding="utf-8"))["profiles"]
    assert stored["p2"]["routing"]["light"]["custom"]["model"] == "elsewhere"
    assert stored["p1"]["models"]["delegation"]["model"] != "edit"
    assert cli.calls == []
    assert not list(service.store_path.parent.glob(f".{service.store_path.name}.*.tmp")), "the temporary file is removed"
