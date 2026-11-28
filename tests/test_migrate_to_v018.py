"""The one-time v0.17 -> v0.18 conversion script (scripts/migrate_to_v018.py)."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from model_router import native_settings as ns
from model_router import slots
from model_router.service import Service
from model_router.timeouts import read_timeouts

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("migrate_to_v018", ROOT / "scripts" / "migrate_to_v018.py")
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def route(provider, model, reasoning="high"):
    return {"provider": provider, "model": model, "reasoning": reasoning}


MAIN = route("openai-codex", "main-model")
DELEGATE = route("deepseek", "delegate-model", "low")
OWN = route("zai", "own-model", "medium")


def models():
    return {"main": copy.deepcopy(MAIN), "delegation": copy.deepcopy(DELEGATE),
            "compression": copy.deepcopy(MAIN), "title": copy.deepcopy(MAIN)}


def v017_entry(**routing):
    return {
        "models": models(),
        "routing": {"enabled": True, "heavy": {"follow": "main", "custom": None},
                    "light": {"follow": "delegation", "custom": None},
                    "fallback": {"enabled": False, "heavy": None, "light": None}, "slots": {}, **routing},
        "native_fallback": None, "delegation_fallback": None,
        "fallback_consent": {"native": None, "routing": None, "delegation": None},
    }


def v017_store(**profiles):
    return {"schema": 4, "revision": 7,
            "custom_slots": [{"id": "custom:frontend", "label": "Frontend", "description": "UI work", "tier": "light"}],
            "profiles": profiles or {"default": v017_entry()}}


def test_every_slot_keeps_its_effective_route():
    stored = {"design": {"follow": "custom", "custom": OWN}, "code-simple": {"follow": "delegation", "custom": None},
              "verify-complex": {"follow": "main", "custom": None}}
    converted = mig.convert_store(v017_store(default=v017_entry(slots=stored)))
    assert converted["schema"] == 5 and converted["revision"] == 8
    assert converted["custom_slots"] == [{"id": "custom:frontend", "label": "Frontend", "description": "UI work"}]
    entry = converted["profiles"]["default"]
    assert set(entry["routing"]) == {"enabled", "slots"} and set(entry["fallback_consent"]) == {"native", "delegation"}
    resolved = slots.resolved_slots(entry["routing"], entry["models"], converted["custom_slots"])
    assert resolved["design"] == OWN
    assert resolved["code-simple"] == DELEGATE  # followed the delegation model
    assert resolved["verify-complex"] == MAIN
    # Never set in v0.17: Light-class slots ran on the Light route (the delegation model), Heavy-class on Main.
    for slot in ("code-complex", "verify-simple", "computer-use", "custom:frontend"):
        assert resolved[slot] == DELEGATE, slot
        assert entry["routing"]["slots"][slot] == {"follow": "custom", "custom": DELEGATE}
    assert resolved["advise"] == MAIN and "advise" not in entry["routing"]["slots"]


def test_an_unset_slot_follows_its_class_override():
    entry = v017_entry(heavy={"follow": "custom", "custom": OWN}, light={"follow": "custom", "custom": DELEGATE})
    converted = mig.convert_store(v017_store(default=entry))["profiles"]["default"]
    resolved = slots.resolved_slots(converted["routing"], converted["models"], [])
    assert resolved["design"] == resolved["advise"] == OWN and resolved["code-complex"] == DELEGATE


@pytest.mark.parametrize("change, reason", [
    (lambda e: e["routing"]["fallback"].update(enabled=True), "spare models are enabled"),
    (lambda e: e["fallback_consent"].update(routing={"schema": 1}), "routing consent"),
    (lambda e: e["routing"]["slots"].update({"design": {"follow": "delegation", "custom": None}}) or e["models"].pop("delegation"), "delegation model"),
    (lambda e: e["routing"].update(extra=True), "unknown routing shape"),
    (lambda e: e["routing"]["slots"].update({"bogus": {"follow": "main", "custom": None}}), "unknown slot"),
])
def test_what_cannot_be_carried_over_is_refused(change, reason):
    entry = v017_entry()
    change(entry)
    with pytest.raises(mig.Refused, match=reason):
        mig.convert_store(v017_store(default=entry))


def test_only_the_v017_store_is_converted():
    for value in ({"schema": 3, "revision": 1, "profiles": {}}, {"schema": 5, "revision": 1, "profiles": {}, "custom_slots": []}):
        with pytest.raises(mig.Refused):
            mig.convert_store(value)


def test_timeouts_keep_the_ordinary_limit_and_put_every_slot_on_the_default():
    value = {"schema": 2, "revision": 3, "delegate_total_seconds": 60.0,
             "routed_light_total_seconds": 5400.0, "routed_heavy_total_seconds": 10800.0}
    converted = mig.convert_timeouts(value)
    assert converted == {"schema": 3, "revision": 4, "delegate_total_seconds": 60.0, "slot_seconds": {}}
    single = mig.convert_timeouts({"schema": 1, "revision": 0, "delegate_total_seconds": 0, "routed_total_seconds": 3600})
    assert single["slot_seconds"] == {}
    for bad in ({"schema": 3, "revision": 0, "delegate_total_seconds": 0, "slot_seconds": {}},
                {"schema": 2, "revision": 0, "delegate_total_seconds": 0, "routed_total_seconds": 1}):
        with pytest.raises(mig.Refused):
            mig.convert_timeouts(bad)


def test_an_all_off_two_role_block_becomes_the_all_off_slot_block():
    off = {"mode": "off", "chain": [], "consent": None}
    block = mig.convert_block("default", "model-router", {"schema": 1, "fallbacks": {"heavy": dict(off), "light": dict(off)}})
    assert block == ns.build_slot_policy_block("default", ns.default_slot_policy(), False)
    assert mig.convert_block("default", "model-router", None) is None
    assert mig.convert_block("default", "model-router", block) is None  # already per slot
    spare = {"mode": "custom", "chain": [{"provider": "x", "model": "y"}], "consent": {"schema": 1}}
    with pytest.raises(mig.Refused, match="spare models"):
        mig.convert_block("default", "model-router", {"schema": 1, "fallbacks": {"heavy": spare, "light": dict(off)}})


def _home(tmp_path):
    root = tmp_path / "hermes"
    (root / "plugin-data" / "model-router").mkdir(parents=True)
    off = {"mode": "off", "chain": [], "consent": None}
    (root / "config.yaml").write_text(json.dumps({"delegation": {"backend": "model-router-auto", "backends": {
        "model-router": {"schema": 1, "fallbacks": {"heavy": dict(off), "light": dict(off)}}}}}), encoding="utf-8")
    store = v017_store(default=v017_entry(slots={"design": {"follow": "custom", "custom": OWN}}))
    (root / "plugin-data" / "model-router" / "settings.json").write_text(json.dumps(store), encoding="utf-8")
    (root / "plugin-data" / "model-router" / "timeouts.json").write_text(json.dumps({
        "schema": 2, "revision": 1, "delegate_total_seconds": 0.0,
        "routed_light_total_seconds": 5400.0, "routed_heavy_total_seconds": 10800.0}), encoding="utf-8")
    return root, store


def test_dry_run_writes_nothing_and_apply_writes_v018_files_once(tmp_path, monkeypatch, capsys):
    root, store = _home(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert mig.main(["--root", str(root)]) == 0
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    out = capsys.readouterr().out
    assert "dry run: nothing written" in out and "own-model" not in out and "main-model" not in out

    writes = []

    def write(self, profile, key, value):
        writes.append((profile, key, value))
        config = json.loads((root / "config.yaml").read_text(encoding="utf-8"))
        config["delegation"]["backends"][key.rsplit(".", 1)[1]] = value
        (root / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(Service, "_write_key", write)
    assert mig.main(["--root", str(root), "--apply"]) == 0
    service = Service(root=root)
    loaded = service._load_store()
    assert loaded["schema"] == 5 and loaded["revision"] == store["revision"] + 1
    assert service.routing_config("default")["slots"]["design"] == OWN
    assert set(service.routing_config("default")["slot_timeout_seconds"].values()) == {7200}
    assert read_timeouts(root)["slot_seconds"] == {} and read_timeouts(root)["delegate_total_seconds"] == 0.0
    assert writes == [("default", "delegation.backends.model-router",
                       ns.build_slot_policy_block("default", ns.default_slot_policy(), False))]
    data = root / "plugin-data" / "model-router"
    assert json.loads((data / "settings.json.pre-v018").read_text(encoding="utf-8")) == store
    assert (data / "timeouts.json.pre-v018").is_file()
    # A second run finds everything current and keeps the first originals.
    original = (data / "settings.json.pre-v018").read_bytes()
    writes.clear()
    assert mig.main(["--root", str(root), "--apply"]) == 0
    assert (data / "settings.json.pre-v018").read_bytes() == original
    assert "settings store: current" in capsys.readouterr().out


def test_apply_with_a_refusal_writes_nothing(tmp_path, monkeypatch):
    root, store = _home(tmp_path)
    store["profiles"]["default"]["routing"]["fallback"]["enabled"] = True
    (root / "plugin-data" / "model-router" / "settings.json").write_text(json.dumps(store), encoding="utf-8")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(Service, "_write_key", lambda *args: pytest.fail("no config write"))
    assert mig.main(["--root", str(root), "--apply"]) == 1
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_a_failure_midway_stops_reports_and_a_rerun_finishes(tmp_path, monkeypatch, capsys):
    root, _store = _home(tmp_path)
    monkeypatch.setattr(Service, "_write_key", lambda self, profile, key, value: (_ for _ in ()).throw(RuntimeError("cli")))
    assert mig.main(["--root", str(root), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "STOPPED: RuntimeError" in out and "completed before the stop: nothing" in out
    # The config step failed first, so timeouts and the store are untouched.
    assert json.loads((root / "plugin-data/model-router/settings.json").read_text(encoding="utf-8"))["schema"] == 4

    def write(self, profile, key, value):
        config = json.loads((root / "config.yaml").read_text(encoding="utf-8"))
        config["delegation"]["backends"][key.rsplit(".", 1)[1]] = value
        (root / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(Service, "_write_key", write)
    assert mig.main(["--root", str(root), "--apply"]) == 0
    assert "applied: config default model-router, timeouts default, settings store" in capsys.readouterr().out
    assert Service(root=root)._load_store()["schema"] == 5
    assert (root / "config.yaml.pre-v018").is_file()


def test_non_profile_directories_are_ignored(tmp_path):
    root, _ = _home(tmp_path)
    for name in (".trash", "Old Copy"):
        (root / "profiles" / name).mkdir(parents=True)
        (root / "profiles" / name / "config.yaml").write_text("{}", encoding="utf-8")
    assert list(mig._homes(root)) == ["default"]
