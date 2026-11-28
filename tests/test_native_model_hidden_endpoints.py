"""Hidden endpoint protection of the model settings wire, without any compare token or key.

A role's endpoint, credential and api_mode keys are never shown, sent, written or cleared by a model
save. A provider change that would leave (or, for an auxiliary role, enter) a configured hidden
destination is refused before any write; every hidden key a planned role depends on is bound by
digest until apply. Status is read-only and nothing secret-derived is on the wire, so status, preview
and apply work from separate Service processes. Synthetic configs only: no live profile, credential
or provider call.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from model_router.service import ExternalChange, RevisionConflict
from test_native_model_authority import native_body, route, row, svc  # noqa: F401  (fixture)

REPO = Path(__file__).resolve().parents[1]
CHANGE_IN_HERMES = "change its provider in Hermes"


def legacy_body(status, models, *, expected=True):
    """What a v0.12-v0.13 Desktop page (whole-mapping wire, frozen `expected`) sends."""
    source = row(status)
    body = {"expected_revision": status["revision"], "profile": "default", "models": copy.deepcopy(models),
            "model_targets": ["default"],
            "routing": {key: value for key, value in copy.deepcopy(source["routing"]).items() if key != "fallback"},
            "routing_profiles": [item["name"] for item in status["profiles"] if item["routing"]["enabled"]]}
    if expected:
        body["expected"] = [{"profile": "default", "models": copy.deepcopy(source["models"]),
                             "actual_models": copy.deepcopy(source["actual_models"])}]
    return body


# --- in-process --------------------------------------------------------------------------------

def test_status_carries_no_token_key_or_secret(svc):
    service, fake, _ = svc
    fake.values["default"]["model.api_key"] = "PRIVATE-KEY-MARKER"
    fake.values["default"]["model.base_url"] = "https://secret-endpoint.example/v1"
    status = service.status()
    text = json.dumps(status)
    assert "PRIVATE-KEY-MARKER" not in text and "secret-endpoint" not in text
    assert "model_role_token" not in text and "mrt1." not in text
    assert not list(service.store_path.parent.glob(".model_role_token*"))


@pytest.mark.parametrize("key,value", [("model.base_url", "https://new-endpoint.example/v1"),
                                       ("model.api_mode", "anthropic_messages")])
def test_endpoint_added_after_page_open_is_never_cleared_by_a_provider_change(svc, key, value):
    service, fake, _ = svc
    status = service.status()  # the page opens: no override yet
    request = native_body(service, {"main": route("anthropic", "page-main", "high")}, status=status)
    fake.values["default"][key] = value
    store = service.store_path.read_bytes()
    with pytest.raises(ValueError, match=CHANGE_IN_HERMES):
        service.preview(copy.deepcopy(request))
    assert fake.values["default"][key] == value and fake.calls == [] and service.store_path.read_bytes() == store


def test_a_reloaded_page_still_never_clears_a_hidden_override(svc):
    service, fake, _ = svc
    fake.values["default"]["model.api_mode"] = "codex_responses"
    status = service.status()  # refreshed after the override was set
    with pytest.raises(ValueError, match=CHANGE_IN_HERMES):
        service.preview(native_body(service, {"main": route("anthropic", "page-main", "high")}, status=status))
    assert fake.values["default"]["model.api_mode"] == "codex_responses" and fake.calls == []


def test_same_provider_edit_keeps_the_endpoint_and_binds_it_until_apply(svc):
    service, fake, _ = svc
    fake.values["default"]["model.base_url"] = "https://endpoint.example/v1"
    status = service.status()
    plan = service.preview(native_body(service, {"main": route("openai-codex", "page-main", "high")}, status=status))
    assert "endpoint.example" not in json.dumps(plan)
    assert service.apply(plan["plan_id"])["status"] == "applied"
    assert fake.values["default"]["model.base_url"] == "https://endpoint.example/v1"
    assert all(key != "model.base_url" for _, key, _ in fake.calls)
    # The same save again, with the endpoint changed between preview and apply: refused, no write.
    plan = service.preview(native_body(service, {"main": route("openai-codex", "page-main-2", "high")}))["plan_id"]
    fake.values["default"]["model.base_url"] = "https://other-endpoint.example/v1"
    calls = list(fake.calls)
    with pytest.raises(RevisionConflict):
        service.apply(plan)
    assert fake.calls == calls and fake.values["default"]["model.default"] == "page-main"


def test_an_auxiliary_role_never_enters_mains_hidden_endpoint(svc):
    service, fake, _ = svc
    fake.values["default"]["model.base_url"] = "https://endpoint.example/v1"
    fake.values["default"].update({"auxiliary.title_generation.provider": "xiaomi", "auxiliary.title_generation.model": "t",
                                   "auxiliary.title_generation.reasoning_effort": "low"})
    with pytest.raises(ValueError, match=CHANGE_IN_HERMES):
        service.preview(native_body(service, {"title": route("openai-codex", "page-title", "low")}))
    assert fake.calls == []


def test_an_inherited_role_never_leaves_mains_hidden_endpoint(svc):
    service, fake, _ = svc
    fake.values["default"]["model.base_url"] = "https://endpoint.example/v1"  # title inherits main
    with pytest.raises(ValueError, match=CHANGE_IN_HERMES):
        service.preview(native_body(service, {"title": route("xiaomi", "page-title", "low")}))
    assert fake.calls == []


def test_an_unrelated_role_saves_while_mains_hidden_keys_change(svc):
    service, fake, _ = svc
    fake.values["default"].update({"auxiliary.title_generation.provider": "xiaomi", "auxiliary.title_generation.model": "t",
                                   "auxiliary.title_generation.reasoning_effort": "low"})
    status = service.status()
    request = native_body(service, {"title": route("xiaomi", "page-title", "low")}, status=status)
    fake.values["default"]["model.base_url"] = "https://new-endpoint.example/v1"  # main only
    fake.values["default"]["delegation.model"] = "outside-delegation"
    plan = service.preview(copy.deepcopy(request))["plan_id"]
    fake.values["default"]["model.api_mode"] = "anthropic_messages"
    assert service.apply(plan)["status"] == "applied"
    assert row(service.status())["models"]["title"] == route("xiaomi", "page-title", "low")
    assert fake.values["default"]["model.base_url"] == "https://new-endpoint.example/v1"
    assert fake.values["default"]["model.api_mode"] == "anthropic_messages"


def test_a_concurrent_visible_change_of_the_edited_role_refuses_before_writing(svc):
    service, fake, _ = svc
    status = service.status()
    request = native_body(service, {"main": route("openai-codex", "page-main", "high")}, status=status)
    fake.values["default"]["model.default"] = "outside-main"
    with pytest.raises(ExternalChange) as caught:
        service.preview(copy.deepcopy(request))
    assert caught.value.profile == "default" and caught.value.field.startswith(("models", "actual_models"))
    assert fake.calls == []


def test_token_fields_are_not_part_of_the_wire(svc):
    service, _, _ = svc
    status = service.status()
    request = native_body(service, {"main": route("anthropic", "page-main", "high")}, status=status)
    with pytest.raises(ValueError):
        service.preview({**copy.deepcopy(request), "model_role_token_schema": 1})
    tokened = copy.deepcopy(request)
    tokened["expected"][0]["model_role_tokens"] = {"main": "mrt1." + "0" * 64}
    with pytest.raises(ValueError):
        service.preview(tokened)


def test_legacy_page_with_expected_cannot_wipe_a_just_added_endpoint(svc):
    service, fake, _ = svc
    status = service.status()
    models = copy.deepcopy(row(status)["models"])
    models["main"] = route("anthropic", "page-main", "high")
    request = legacy_body(status, models)
    fake.values["default"]["model.base_url"] = "https://new-endpoint.example/v1"
    store = service.store_path.read_bytes()
    with pytest.raises(ValueError, match=CHANGE_IN_HERMES):
        service.preview(request)
    assert fake.values["default"]["model.base_url"] == "https://new-endpoint.example/v1"
    assert fake.calls == [] and service.store_path.read_bytes() == store


def test_legacy_save_never_carries_an_inline_credential_to_another_provider(svc):
    service, fake, _ = svc
    fake.values["default"]["delegation.api_key"] = "PRIVATE-KEY-MARKER"
    status = service.status()
    models = copy.deepcopy(row(status)["models"])
    models["delegation"] = route("zai", "page-delegation", "low")
    models["main"] = route("openai-codex", "main-model0", "high")
    with pytest.raises(ValueError, match=CHANGE_IN_HERMES):
        service.preview(legacy_body(status, models, expected=False))
    assert fake.values["default"]["delegation.api_key"] == "PRIVATE-KEY-MARKER" and fake.calls == []


# --- separate processes ------------------------------------------------------------------------

CHILD = r'''
import json, os, sys
from pathlib import Path
from model_router import effective_config
from model_router.service import Service
from model_router.yaml_compat import yaml

root, op, payload = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])

def config_path(profile):
    return root / "config.yaml" if profile == "default" else root / "profiles" / profile / "config.yaml"

def writer(profile, key, value):
    path = config_path(profile)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    node = data
    *parents, leaf = key.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

def native_snapshot(service, profile):
    raw = {key: service._read_key(profile, key) for key in ("fallback_providers", "fallback_model")}
    return effective_config.make_snapshot(raw=raw, effective=raw)

# As tests/conftest.py: a fake home has no managed overlay (the Hermes helper may be absent).
Service._read_model_overlay = lambda self, profile: {"available": True, "managed": {}, "digest": "fixture-no-managed-model-config"}
Service._read_native_snapshot = native_snapshot
service = Service(root=root, writer=writer)
out = {"pid": os.getpid()}
try:
    if op == "status":
        out["status"] = service.status()
    elif op == "preview":
        out["result"] = service.preview(payload)
    else:
        out["result"] = service.apply(payload["plan_id"])
except Exception as exc:  # reported to the parent test
    out["error"] = {"type": type(exc).__name__, "message": str(exc),
                    "profile": getattr(exc, "profile", None), "field": getattr(exc, "field", None)}
out["plugin_data"] = (root / "plugin-data").exists()
print(json.dumps(out))
'''

BASE_CONFIG = {
    "model": {"provider": "openai-codex", "default": "main-a"},
    "agent": {"reasoning_effort": "high"},
    "delegation": {"provider": "deepseek", "model": "child-a", "reasoning_effort": "low"},
    "auxiliary": {"compression": {"provider": "zai", "model": "comp-a", "reasoning_effort": "low"},
                  "title_generation": {"provider": "xiaomi", "model": "title-a", "reasoning_effort": "minimal"}},
    "skills": {"disabled": []},
}
CONFIG_KEYS = {"main": ("model.provider", "model.default", "agent.reasoning_effort"),
               "compression": ("auxiliary.compression.provider", "auxiliary.compression.model", "auxiliary.compression.reasoning_effort"),
               "title": ("auxiliary.title_generation.provider", "auxiliary.title_generation.model", "auxiliary.title_generation.reasoning_effort")}
EDITS = {"main": route("openai-codex", "main-edited", "xhigh"),
         "compression": route("zai", "comp-edited", "medium"),
         "title": route("xiaomi", "title-edited", "low")}


@pytest.fixture
def home(tmp_path):
    from model_router.yaml_compat import yaml
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "config.yaml").write_text(yaml.safe_dump(BASE_CONFIG, sort_keys=True), encoding="utf-8")
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    return root, script


def run(home, op, payload=None):
    root, script = home
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
           "HERMES_HOME": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, str(script), str(root), op, json.dumps(payload or {})],
                          cwd=str(script.parent), env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def config(home):
    from model_router.yaml_compat import yaml
    return yaml.safe_load((home[0] / "config.yaml").read_text(encoding="utf-8"))


def edit_config(home, key, value):
    from model_router.yaml_compat import yaml
    data = config(home)
    node = data
    *parents, leaf = key.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value
    (home[0] / "config.yaml").write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def read(data, key):
    for part in key.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data


@pytest.mark.parametrize("role", ["main", "compression", "title"])
def test_cross_process_status_preview_apply_saves_an_ordinary_edit(home, role):
    status = run(home, "status")
    assert status["plugin_data"] is False, "a status read creates no plugin-data"
    assert "error" not in status and "model_role_token" not in json.dumps(status)
    before = config(home)
    preview = run(home, "preview", native_body(None, {role: EDITS[role]}, status=status["status"]))
    assert "error" not in preview, preview.get("error")
    applied = run(home, "apply", {"plan_id": preview["result"]["plan_id"]})
    assert "error" not in applied, applied.get("error")
    assert len({status["pid"], preview["pid"], applied["pid"], os.getpid()}) == 4, "four distinct processes"
    assert applied["result"]["status"] == "applied"
    after = config(home)
    assert [read(after, key) for key in CONFIG_KEYS[role]] == [EDITS[role][part] for part in ("provider", "model", "reasoning")]
    for other, keys in CONFIG_KEYS.items():
        if other != role:
            assert [read(after, key) for key in keys] == [read(before, key) for key in keys]
    assert read(after, "model.base_url") is None and read(after, "model.api_mode") is None
    assert row(run(home, "status")["status"])["models"][role] == EDITS[role]


def test_cross_process_stale_edited_role_fails_and_unrelated_role_saves(home):
    status = run(home, "status")["status"]
    # The edited role changed elsewhere after the page opened: refused before any write.
    edit_config(home, "auxiliary.compression.model", "comp-outside")
    stale = run(home, "preview", native_body(None, {"compression": EDITS["compression"]}, status=status))
    assert stale["error"]["type"] == "ExternalChange" and stale["error"]["profile"] == "default"
    assert stale["error"]["field"].endswith("compression")
    assert read(config(home), "auxiliary.compression.model") == "comp-outside"
    # The same stale page editing an unrelated role still saves.
    preview = run(home, "preview", native_body(None, {"title": EDITS["title"]}, status=status))
    assert "error" not in preview, preview.get("error")
    assert run(home, "apply", {"plan_id": preview["result"]["plan_id"]})["result"]["status"] == "applied"
    assert read(config(home), "auxiliary.title_generation.model") == "title-edited"
    assert read(config(home), "auxiliary.compression.model") == "comp-outside"


def test_cross_process_change_between_preview_and_apply_refuses_apply(home):
    status = run(home, "status")["status"]
    preview = run(home, "preview", native_body(None, {"main": EDITS["main"]}, status=status))
    edit_config(home, "model.base_url", "https://added-later.example/v1")
    applied = run(home, "apply", {"plan_id": preview["result"]["plan_id"]})
    assert applied["error"]["type"] in {"RevisionConflict", "ExternalChange"}
    data = config(home)
    assert read(data, "model.default") == "main-a" and read(data, "model.base_url") == "https://added-later.example/v1"


def test_cross_process_hidden_endpoint_added_after_status_blocks_a_provider_change(home):
    status = run(home, "status")["status"]
    edit_config(home, "model.api_mode", "anthropic_messages")
    refused = run(home, "preview", native_body(None, {"main": route("anthropic", "main-x", "high")}, status=status))
    assert refused["error"]["type"] == "ValueError" and CHANGE_IN_HERMES in refused["error"]["message"]
    data = config(home)
    assert read(data, "model.api_mode") == "anthropic_messages" and read(data, "model.provider") == "openai-codex"
