"""Regressions: main route projection (aliases, qualified defaults, reasoning overrides) and
role-scoped managed overlay provenance. Synthetic config only; nothing is dialed or written live."""
from __future__ import annotations

import pytest

from model_router import effective_config
from model_router.service import (ROUTE_DEPENDENCY_KEYS, Service, _overlay_digest, _overlay_digest_holds,
                                  _project_roles, _role_scope_keys)

OK = {"available": True, "managed": {}}


def values(**extra):
    base = {"model.provider": "openrouter", "model.default": "localqwen", "agent.reasoning_effort": "high"}
    base.update(extra)
    return base


def test_alias_default_is_never_projected_as_provider_plus_alias_name():
    models, roles = _project_roles(values(model_aliases={"localqwen": True}), OK)
    assert "main" not in models and roles["main"]["state"] == "unverified" and roles["main"]["reason"] == "alias"
    # Inherited roles follow main, so they are not projected either.
    assert "compression" not in models and roles["compression"]["reason"] == "inherits_unverified"
    models, roles = _project_roles(values(**{"model.aliases": {"LocalQwen": True}}), OK)
    assert "main" not in models and roles["main"]["reason"] == "alias"
    _, roles = _project_roles(values(model_aliases=False), OK)
    assert roles["main"]["reason"] == "alias_unverified"
    # No alias of that name: the literal route stays verified.
    models, _ = _project_roles(values(model_aliases={"other": True}), OK)
    assert models["main"] == {"provider": "openrouter", "model": "localqwen", "reasoning": "high"}


def test_qualified_and_configured_prefix_defaults_are_unverified():
    _, roles = _project_roles(values(**{"model.default": "anthropic:claude-x"}), OK)
    assert roles["main"]["reason"] == "qualified_model"
    # A colon that is not a provider delimiter (an Ollama tag) stays literal.
    models, _ = _project_roles(values(**{"model.provider": "ollama", "model.default": "qwen3:8b"}), OK)
    assert models["main"]["model"] == "qwen3:8b"
    _, roles = _project_roles(values(**{"model.default": "mybox/qwen"}, providers={"mybox": True}), OK)
    assert roles["main"]["reason"] == "provider_prefix"
    _, roles = _project_roles(values(**{"model.default": "mybox/qwen"}, providers=False), OK)
    assert roles["main"]["reason"] == "provider_prefix_unverified"
    models, _ = _project_roles(values(**{"model.default": "anthropic/claude-x"}), OK)
    assert models["main"]["model"] == "anthropic/claude-x"


def test_reasoning_override_wins_over_agent_reasoning_effort():
    over = {"agent.reasoning_overrides": {"localqwen": "low"}}
    models, roles = _project_roles(values(**over), OK)
    assert models["main"]["reasoning"] == "low" and roles["main"]["state"] == "verified"
    models, _ = _project_roles(values(**{"agent.reasoning_overrides": {"localqwen": "none"}}), OK)
    assert models["main"]["reasoning"] == "none"
    _, roles = _project_roles(values(**{"agent.reasoning_overrides": {"localqwen": {"enabled": True, "effort": "fast"}}}), OK)
    assert roles["main"]["reason"] == "reasoning_override"
    _, roles = _project_roles(values(**{"agent.reasoning_overrides": ["bad"]}), OK)
    assert roles["main"]["reason"] == "reasoning_override"
    # An inheriting role whose effort would follow an override is not claimed.
    _, roles = _project_roles(values(**over), OK)
    assert roles["compression"]["reason"] == "reasoning_override"
    models, _ = _project_roles(values(**{"agent.reasoning_overrides": {"unrelated-model": "low"}}), OK)
    assert models["main"]["reasoning"] == "high" and models["compression"]["reasoning"] == "high"


def test_role_scope_keys_are_stable_and_include_route_dependencies():
    assert set(ROUTE_DEPENDENCY_KEYS) <= set(_role_scope_keys("main"))
    assert "auxiliary.title_generation.model" not in _role_scope_keys("main")
    assert "model.default" in _role_scope_keys("title") and "auxiliary.compression.model" not in _role_scope_keys("title")


def _reader(managed_by_key, env_managed=()):
    def reader(home, selected, **_):
        selected = tuple(selected)
        if any(key in selected for key in env_managed):
            return effective_config.make_key_snapshot(keys=selected, raw={}, effective=None,
                                                      warnings=("scoped_managed_env_expression_readonly",))
        managed = tuple(key for key in selected if key in managed_by_key)
        return effective_config.make_key_snapshot(
            keys=selected, raw={}, effective={key: managed_by_key.get(key) for key in selected},
            managed_keys=managed, managed_signature=repr(sorted((k, managed_by_key[k]) for k in managed)))
    return reader


def test_managed_title_env_overlay_does_not_deny_main(tmp_path, monkeypatch):
    from conftest import real_model_overlay_reader
    monkeypatch.setattr(Service, "_read_model_overlay", real_model_overlay_reader())
    service = Service(root=tmp_path)
    monkeypatch.setattr(effective_config, "read_key_scoped",
                        _reader({"auxiliary.title_generation.model": "${TITLE}"}, env_managed=("auxiliary.title_generation.model",)))
    overlay = service._read_model_overlay("default")
    assert overlay["available"] is True
    assert overlay["roles"]["main"]["available"] is True and overlay["roles"]["title"]["available"] is False
    models, roles = _project_roles(values(**{"model.default": "real-main"}), overlay)
    assert models["main"]["model"] == "real-main" and roles["main"]["editable"] is True
    assert roles["title"]["reason"] == "provenance_unavailable"
    assert _overlay_digest(overlay, ["title"]) is None and isinstance(_overlay_digest(overlay, ["main"]), str)


def test_unrelated_managed_change_keeps_the_main_plan_digest(tmp_path, monkeypatch):
    from conftest import real_model_overlay_reader
    monkeypatch.setattr(Service, "_read_model_overlay", real_model_overlay_reader())
    service = Service(root=tmp_path)
    managed = {"auxiliary.title_generation.model": "t1"}
    monkeypatch.setattr(effective_config, "read_key_scoped", _reader(managed))
    first = service._read_model_overlay("default")
    recorded = _overlay_digest(first, ["main"])
    title_recorded = _overlay_digest(first, ["title"])
    managed["auxiliary.title_generation.model"] = "t2"
    second = service._read_model_overlay("default")
    assert _overlay_digest_holds(second, recorded)
    assert not _overlay_digest_holds(second, title_recorded)
    # A managed change to main invalidates every role that depends on it.
    managed["model.default"] = "admin"
    third = service._read_model_overlay("default")
    assert not _overlay_digest_holds(third, recorded) and not _overlay_digest_holds(third, _overlay_digest(second, ["title"]))
    # Legacy whole-overlay digests still compare whole; tampered role lists fail closed.
    assert _overlay_digest_holds(third, third["digest"]) and not _overlay_digest_holds(third, "roles:evil:x")


def test_status_and_overlay_reads_create_no_files(tmp_path, monkeypatch):
    """A status read (real overlay reader) leaves the home byte-for-byte unchanged and carries no
    compare token, key or secret-derived value."""
    import json
    from conftest import real_model_overlay_reader
    monkeypatch.setattr(Service, "_read_model_overlay", real_model_overlay_reader())
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(json.dumps({"model": {"provider": "openai-codex", "default": "fixture-shared"},
                                                  "model_aliases": {"localqwen": {"model": "q", "base_url": "http://x"}}}),
                                      encoding="utf-8")
    before = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
    service = Service(home)
    status = service.status()
    assert sorted(str(path.relative_to(home)) for path in home.rglob("*")) == before
    assert not (home / "plugin-data").exists()
    text = json.dumps(status)
    assert "model_role_token" not in text and "http://x" not in text
    assert service.status() == status, "a repeated read is identical"
