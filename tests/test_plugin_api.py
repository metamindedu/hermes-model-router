import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def load(name, path, package=False):
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(ROOT)] if package else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api(monkeypatch):
    mod = load("test_router_dashboard", ROOT / "dashboard/plugin_api.py")
    service = SimpleNamespace(status=lambda: {"revision": 2, "profiles": []}, preview=lambda b: {"plan_id": "x" * 32}, apply=lambda p: {"status": "applied"})
    monkeypatch.setattr(mod, "_service", lambda: service)
    app = FastAPI(); app.include_router(mod.router)
    return mod, service, TestClient(app)


def test_backend_status_preview_and_apply(api):
    mod, service, client = api
    assert client.get("/status").json()["revision"] == 2
    assert client.post("/preview", json={}).json()["plan_id"] == "x" * 32
    assert client.post("/apply", json={"plan_id": "x" * 32}).json() == {"status": "applied"}


def test_apply_rejects_extra_fields_and_traversal(api):
    _, _, client = api
    assert client.post("/apply", json={"plan_id": "x" * 32, "profile": "other"}).status_code == 422
    assert client.post("/apply", json={"plan_id": "../token"}).status_code == 422


def test_backend_does_not_leak_subprocess_exception(api):
    _, service, client = api
    def fail():
        raise Exception("SECRET-DO-NOT-RETURN")
    service.status = fail
    response = client.get("/status")
    assert response.status_code == 500
    assert "SECRET-DO-NOT-RETURN" not in response.text


def test_backend_partial_is_not_converted_to_success(api):
    _, service, client = api
    service.apply = lambda p: {"status": "partial", "applied": ["main.model"]}
    assert client.post("/apply", json={"plan_id": "x" * 32}).json()["status"] == "partial"


@pytest.fixture
def plugin(monkeypatch):
    mod = load("test_model_router_plugin", ROOT / "__init__.py", package=True)
    package = ModuleType("test_model_router_plugin.model_router")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    state = {"enabled": True, "started": 0, "bound": []}
    class Service:
        def active_profile(self): return "claire"
        def routing_config(self, profile): return {"enabled": state["enabled"], "revision": 1}
    class Router:
        def __init__(self, service): self.service = service
        def start(self, *args): state["started"] += 1; return {"job_id": "a" * 32, "status": "running"}
        def status(self, job_id): return {"status": "failed", "verification_status": "unmet"}
    for name, cls in [("service", Service), ("routing", Router)]:
        child = ModuleType(package.__name__ + "." + name)
        setattr(child, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, child.__name__, child)
    constants = ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: Path("C:/fake/profiles/claire")
    constants.set_hermes_home_override = lambda home: state["bound"].append(str(home)) or "token"
    constants.reset_hermes_home_override = lambda token: state["bound"].append(token)
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    tools, skills = [], []
    ctx = SimpleNamespace(register_cli_command=lambda *args: state.update(cli=args), register_tool=lambda **kwargs: tools.append(kwargs), register_skill=lambda *args: skills.append(args))
    return mod, ctx, state, tools, skills


def test_disabled_profile_registers_neither_tools_nor_skill(plugin):
    mod, ctx, state, tools, skills = plugin
    state["enabled"] = False
    mod.register(ctx)
    assert tools == skills == []


def test_active_profile_registers_scoped_tool_and_skill(plugin):
    mod, ctx, state, tools, skills = plugin
    mod.register(ctx)
    assert tools[0]["name"] == "coding_route"
    assert skills[0][0] == "adaptive-coding-orchestration"
    result = json.loads(tools[0]["handler"]({"action": "start", "purpose": "independent-review", "prompt": "bounded", "cwd": "C:/fake"}))
    assert result["status"] == "running"
    assert state["started"] == 1
    assert state["bound"][-1] == "token"


def test_stale_tool_cannot_bypass_profile_disable(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    state["enabled"] = False
    result = json.loads(tools[0]["handler"]({"action": "start", "purpose": "implementation"}))
    assert result["error"] == "routing_disabled"
    assert state["started"] == 0


def test_tool_rejects_cross_profile_field(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    result = json.loads(tools[0]["handler"]({"action": "start", "purpose": "implementation", "profile": "other"}))
    assert result["error"] == "invalid_or_denied"
    assert state["started"] == 0
