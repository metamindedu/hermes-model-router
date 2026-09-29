"""Delegation acceptance at the real YAML/Service boundary, no providers."""
import copy
import json

import pytest
import yaml

from model_router.service import Service, ServiceError, RevisionConflict
from test_integration import make_home, writer

CHAIN = [{"provider": "xiaomi", "model": "mimo-test"}]


def setup(tmp_path):
    root = make_home(tmp_path)
    service = Service(root, writer(root))
    service.initialize(["default"])
    return service, root / "config.yaml"


def row(service):
    return next(p for p in service.status()["profiles"] if p["name"] == "default")


def body(service, mode, chain=None, consent=True):
    return {"expected_revision": service.status()["revision"],
            "updates": [{"profile": "default", "delegation_fallback": {"mode": mode, "chain": chain or []}}],
            "confirmations": ([{"profile": "default", "scope": "delegation",
                                "allow_additional_cost": True, "allow_task_rerun": False}] if consent else [])}


def config(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def set_declared(path, value):
    cfg = config(path)
    cfg.setdefault("delegation", {})["fallback_providers"] = value
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


@pytest.mark.parametrize("declared,mode", [(None, "default"), ([], "off"), (CHAIN, "custom")])
def test_delegation_declared_modes_are_distinct_readonly(tmp_path, declared, mode):
    service, path = setup(tmp_path)
    set_declared(path, declared)
    before = path.read_bytes(), service.store_path.read_bytes()
    dto = row(service)["fallbacks"]["delegation"]
    assert dto["actual_mode"] == mode
    assert dto["mode"] == mode
    assert dto["managed"] is False
    assert dto["actual_chain"] == (CHAIN if mode == "custom" else [])
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_delegation_custom_requires_own_consent_and_changes_only_own_key(tmp_path):
    service, path = setup(tmp_path)
    before_config, before_row = config(path), row(service)
    proposal = body(service, "custom", CHAIN, consent=False)
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(proposal)
    proposal["confirmations"] = [{"profile": "default", "scope": "native", "allow_additional_cost": True, "allow_task_rerun": False}]
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(proposal)
    plan = service.fallback_preview(body(service, "custom", CHAIN))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    after = config(path)
    assert after["delegation"].pop("fallback_providers") == CHAIN
    assert after == before_config
    updated = row(service)
    assert updated["models"] == before_row["models"]
    assert updated["routing"] == before_row["routing"]
    for scope in ("native", "routing"):
        assert updated["fallbacks"][scope] == before_row["fallbacks"][scope]
    assert updated["fallbacks"]["delegation"]["consent"]["allow_task_rerun"] is False


def test_delegation_off_and_default_are_different_projections(tmp_path):
    service, path = setup(tmp_path)
    set_declared(path, CHAIN)
    plan = service.fallback_preview(body(service, "off", consent=False))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert config(path)["delegation"]["fallback_providers"] == []
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(body(service, "default", consent=False))
    plan = service.fallback_preview(body(service, "default"))
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert config(path)["delegation"]["fallback_providers"] is None
    assert row(service)["fallbacks"]["delegation"]["drift"] is False


def test_delegation_external_advanced_chain_is_preserved(tmp_path):
    service, path = setup(tmp_path)
    advanced = [{"provider": "custom", "model": "example", "api_key": "TEST_ONLY_SENTINEL", "base_url": "https://invalid.example"}]
    set_declared(path, advanced)
    before = path.read_bytes(), service.store_path.read_bytes()
    dto = row(service)["fallbacks"]["delegation"]
    assert dto["editable"] is False
    assert "TEST_ONLY_SENTINEL" not in json.dumps(dto)
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(body(service, "off", consent=False))
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_delegation_external_change_after_preview_cannot_be_adopted(tmp_path):
    service, path = setup(tmp_path)
    plan = service.fallback_preview(body(service, "custom", CHAIN))
    advanced = [{"provider": "custom", "model": "external", "base_url": "https://invalid.example"}]
    set_declared(path, advanced)
    before = path.read_bytes(), service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan["plan_id"])
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_native_update_does_not_rewrite_explicit_delegation_chain(tmp_path):
    service, path = setup(tmp_path)
    set_declared(path, CHAIN)
    before = copy.deepcopy(config(path)["delegation"])
    proposal = {"expected_revision": service.status()["revision"], "updates": [{"profile": "default", "native_fallback": {"enabled": False, "chain": []}}], "confirmations": []}
    plan = service.fallback_preview(proposal)
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert config(path)["delegation"] == before


def test_old_schema2_delegation_defaults_are_readonly(tmp_path):
    service, path = setup(tmp_path)
    store = json.loads(service.store_path.read_text(encoding="utf-8"))
    for entry in store["profiles"].values():
        entry.pop("delegation_fallback", None)
        entry.get("fallback_consent", {}).pop("delegation", None)
    service.store_path.write_text(json.dumps(store), encoding="utf-8")
    before = path.read_bytes(), service.store_path.read_bytes()
    assert row(service)["fallbacks"]["delegation"]["managed"] is False
    assert before == (path.read_bytes(), service.store_path.read_bytes())


@pytest.mark.parametrize('managed_value', [None, [], CHAIN, [{'provider': 'custom', 'model': 'x', 'api_key': 'TEST_ONLY_SENTINEL'}]])
def test_managed_delegation_declaration_is_readonly(tmp_path, monkeypatch, managed_value):
    service, path = setup(tmp_path)
    managed = tmp_path / 'managed'
    managed.mkdir()
    (managed / 'config.yaml').write_text(yaml.safe_dump({'delegation': {'fallback_providers': managed_value}}), encoding='utf-8')
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    before = path.read_bytes(), service.store_path.read_bytes()
    assert row(service)['fallbacks']['delegation']['editable'] is False
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(body(service, 'off', consent=False))
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_delegation_managed_overlay_after_preview_is_conflict(tmp_path, monkeypatch):
    service, path = setup(tmp_path)
    managed = tmp_path / 'managed'
    managed.mkdir()
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    plan = service.fallback_preview(body(service, 'custom', CHAIN))
    (managed / 'config.yaml').write_text(yaml.safe_dump({'delegation': {'fallback_providers': []}}), encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])
    assert before == (path.read_bytes(), service.store_path.read_bytes())


@pytest.mark.parametrize('bad', ['unknown', None, 1])
def test_invalid_delegation_mode_is_rejected(tmp_path, bad):
    service, path = setup(tmp_path)
    before = path.read_bytes(), service.store_path.read_bytes()
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(body(service, bad))
    assert before == (path.read_bytes(), service.store_path.read_bytes())


def test_model_apply_preserves_delegation_policy_and_consent(tmp_path):
    from test_integration import payload
    service, path = setup(tmp_path)
    plan = service.fallback_preview(body(service, 'custom', CHAIN))
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    before = row(service)['fallbacks']['delegation']
    proposal = payload(service)
    proposal['models']['main']['model'] = 'new-heavy-model'
    proposal['model_targets'] = ['default']
    plan = service.preview(proposal)
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    assert row(service)['fallbacks']['delegation'] == before
    assert config(path)['delegation']['fallback_providers'] == CHAIN


def test_non_mapping_delegation_parent_cannot_be_silently_replaced(tmp_path):
    service, path = setup(tmp_path)
    cfg = config(path)
    cfg['delegation'] = 'unexpected-scalar'
    path.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    before = path.read_bytes(), service.store_path.read_bytes()
    assert row(service)['fallbacks']['delegation']['editable'] is False
    with pytest.raises((ServiceError, ValueError)):
        service.fallback_preview(body(service, 'off', consent=False))
    assert before == (path.read_bytes(), service.store_path.read_bytes())
