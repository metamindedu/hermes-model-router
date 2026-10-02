"""Real supported config CLI, synthetic 11-profile bulk save only."""
import copy
import json
import os
from pathlib import Path
import time

import pytest
import yaml

from model_router.service import Service
from test_integration import make_home
from test_combined_preview import scopes, confirmation


def test_real_eleven_profile_bulk_save_finishes_within_backend_budget(tmp_path, monkeypatch):
    launcher = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/bin/hermes.exe"
    if not launcher.is_file():
        pytest.skip("local Windows Hermes CLI absent")
    for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        monkeypatch.delenv(key, raising=False)
    root = make_home(tmp_path)
    names = ["default"] + [f"p{i}" for i in range(10)]
    for name in names[1:]:
        home = root / "profiles" / name
        home.mkdir(parents=True)
        (home / "config.yaml").write_bytes((root / "config.yaml").read_bytes())
    service = Service(root)
    monkeypatch.setattr(service, "_cli_path", lambda: str(launcher))
    status = service.initialize(names)
    row = status["profiles"][0]
    models = copy.deepcopy(row["models"])
    for role in models:
        models[role]["model"] = "bulk-test-" + role
        models[role]["reasoning"] = "high"
    all_scopes = scopes()
    proposal = {
        "expected_revision": status["revision"], "profile": "default", "models": models,
        "model_targets": names, "routing": row["routing"], "routing_profiles": names,
        "fallback_updates": [{"profile": name, **copy.deepcopy(all_scopes)} for name in names],
        "fallback_confirmations": [confirmation(scope, name) for name in names for scope in ["native", "routing", "delegation"]],
    }
    proposal['routing_targets'] = names
    proposal['routing'] = copy.deepcopy(row['routing'])
    proposal['routing']['heavy'] = {'follow': 'custom', 'custom': {'provider': 'openai-codex', 'model': 'bulk-route-heavy', 'reasoning': 'high'}}
    proposal['routing']['light'] = {'follow': 'custom', 'custom': {'provider': 'openai-codex', 'model': 'bulk-route-light', 'reasoning': 'low'}}
    t = time.monotonic()
    plan = service.preview(proposal)
    receipt = service.apply(plan["plan_id"])
    elapsed = time.monotonic() - t
    print(json.dumps({"real_cli_bulk_profiles": len(names), "writes": len(receipt["applied"]), "seconds": round(elapsed, 3), "status": receipt["status"]}))
    assert receipt["status"] == "applied", receipt
    assert elapsed < 170, "bulk operation must finish before existing 180s backend command budget"
    for name in names:
        home = root if name == "default" else root / "profiles" / name
        data = yaml.safe_load((home / "config.yaml").read_text())
        assert data["model"]["default"] == "bulk-test-main"
        assert data["fallback_providers"] == all_scopes["native_fallback"]["chain"]
        assert data["delegation"]["fallback_providers"] == all_scopes["delegation_fallback"]["chain"]
    reopened = Service(root)
    final = reopened.status()
    assert len(final["profiles"]) == 11
    for name in names:
        effective = reopened.routing_config(name)
        assert effective['heavy'] == proposal['routing']['heavy']['custom']
        assert effective['light'] == proposal['routing']['light']['custom']
        assert effective['enabled'] is True
    assert all(not row["drift"] and not row["fallbacks"]["native"]["drift"] and not row["fallbacks"]["delegation"]["drift"] for row in final["profiles"])
