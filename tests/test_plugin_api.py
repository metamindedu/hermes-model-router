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
    service = SimpleNamespace(status=lambda: {"revision": 2, "profiles": []}, preview=lambda b: {"plan_id": "x" * 32}, fallback_preview=lambda b: {"plan_id": "f" * 32}, apply=lambda p: {"status": "applied"})
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
        def fallback_preview(self, body):
            state['fallback_body'] = body
            return {'plan_id': 'f' * 32, 'changes': [], 'warnings': []}
    class Router:
        def __init__(self, service, **kwargs):
            self.service = service
            state['router_kwargs'] = kwargs
            self.fast_snapshot = kwargs.get('fast_snapshot')
            self.runtime = kwargs.get('runtime')
        def start(self, *args, **kwargs): state["started"] += 1; state['start_kwargs'] = kwargs; return {"job_id": "a" * 32, "status": "running"}
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
    observer_module = ModuleType(package.__name__ + '.attempt_observer')
    observer_module.record_event = lambda event_name, **payload: state.setdefault('events', []).append((event_name, payload))
    monkeypatch.setitem(sys.modules, observer_module.__name__, observer_module)
    runtime_module = ModuleType(package.__name__ + '.runtime_tracking')
    from contextlib import nullcontext
    runtime_module.route_session_context = lambda **kwargs: nullcontext()
    runtime_module.capture_runtime = lambda **kwargs: state.setdefault('runtime_calls', []).append(kwargs) or SimpleNamespace(parent_session_id='parent-session')
    monkeypatch.setitem(sys.modules, runtime_module.__name__, runtime_module)
    watchdog_module = ModuleType(package.__name__ + '.native_watchdog')
    watchdog_module.register_native_watchdog = lambda ctx, home: state.setdefault('watchdog_homes', []).append(str(home))
    monkeypatch.setitem(sys.modules, watchdog_module.__name__, watchdog_module)
    fast_module = ModuleType(package.__name__ + '.fast_inheritance')
    def capture_for_route(*, session_id, profile):
        state.setdefault('fast_captures', []).append({'session_id': session_id, 'profile': profile})
        return state.get('fast_snapshot')
    controller = SimpleNamespace(capture_for_route=capture_for_route)
    fast_module.register_fast_inheritance = lambda ctx, home: state.setdefault('fast_homes', []).append(str(home)) or controller
    monkeypatch.setitem(sys.modules, fast_module.__name__, fast_module)
    tools, skills = [], []
    ctx = SimpleNamespace(register_cli_command=lambda *args: state.update(cli=args), register_tool=lambda **kwargs: tools.append(kwargs), register_skill=lambda *args: skills.append(args), register_hook=lambda event, callback: state.setdefault('hooks', {}).update({event: callback}))
    return mod, ctx, state, tools, skills


def test_disabled_profile_registers_neither_tools_nor_skill(plugin):
    mod, ctx, state, tools, skills = plugin
    state["enabled"] = False
    mod.register(ctx)
    assert tools == skills == []
    assert state['watchdog_homes'] == [str(Path("C:/fake/profiles/claire"))]


def test_active_profile_registers_scoped_tool_and_skill(plugin):
    mod, ctx, state, tools, skills = plugin
    mod.register(ctx)
    assert tools[0]["name"] == "coding_route"
    assert skills[0][0] == "adaptive-coding-orchestration"
    result = json.loads(tools[0]["handler"]({"action": "start", "purpose": "independent-review", "prompt": "bounded", "cwd": "C:/fake"}))
    assert result["status"] == "running"
    assert state["started"] == 1
    assert state['runtime_calls'] == [{'task_id': '', 'expected_profile': 'claire'}]
    assert state["bound"][-1] == "token"


def test_registered_discovery_copy_defaults_small_work_to_main(plugin):
    mod, ctx, state, tools, skills = plugin
    mod.register(ctx)
    description = tools[0]['schema']['description']
    assert 'Main handles small bounded changes directly' in description
    assert 'at least two substantive independent workstreams' in description
    assert 'unless explicitly requested by the user' in description
    assert 'required Heavy/independent review remains mandatory' in description
    assert 'Main handles small bounded changes directly' in skills[0][2]
    assert state['started'] == 0
    assert tools[0]['schema']['parameters']['required'] == ['action']


def test_public_title_schema_is_forwarded_without_changing_scope(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    schema = tools[0]['schema']['parameters']['properties']['title']
    assert schema['maxLength'] == 96 and schema['minLength'] == 1
    result = json.loads(tools[0]['handler']({'action': 'start', 'purpose': 'mechanical', 'prompt': 'bounded', 'cwd': 'C:/fake', 'title': '테스트 및 검증'}))
    assert result['status'] == 'running'
    assert state['start_kwargs'] == {'title': '테스트 및 검증'}
    assert state['runtime_calls'] == [{'task_id': '', 'expected_profile': 'claire'}]


def test_timeout_schema_exposes_zero_and_no_independent_ceiling(plugin):
    mod, ctx, _, tools, _ = plugin
    mod.register(ctx)
    timeout = tools[0]['schema']['parameters']['properties']['timeout']
    assert timeout['minimum'] == 0
    assert 'maximum' not in timeout
    assert 'profile' in timeout['description'] and '3600' in timeout['description']


def test_stale_tool_cannot_bypass_profile_disable(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    state["enabled"] = False
    result = json.loads(tools[0]["handler"]({"action": "start", "purpose": "implementation"}))
    assert result["error"] == "routing_disabled"
    assert state["started"] == 0


def test_backend_fallback_preview_uses_separate_service_method(api):
    _, service, client = api
    captured = []
    service.fallback_preview = lambda body: captured.append(body) or {'plan_id': 'f' * 32}
    body = {'expected_revision': 4, 'updates': [{'profile': 'claire', 'native_fallback': {'enabled': False, 'chain': []}}], 'confirmations': []}
    assert client.post('/fallback-preview', json=body).json()['plan_id'] == 'f' * 32
    assert captured == [body]


def test_native_fallback_command_is_scoped_and_framed(plugin, capsys):
    mod, ctx, state, _, _ = plugin
    mod.register(ctx)
    body = {'expected_revision': 4, 'updates': [{'profile': 'claire', 'native_fallback': {'enabled': False, 'chain': []}}], 'confirmations': []}
    handler = state['cli'][3]
    assert handler(SimpleNamespace(operation='fallback-preview', body=json.dumps(body))) == 0
    output = capsys.readouterr().out
    assert json.loads(output.split('MODEL_ROUTER_JSON:', 1)[1])['plan_id'] == 'f' * 32
    assert state['fallback_body'] == body
    assert state['bound'][-1] == 'token'
    assert handler(SimpleNamespace(operation='fallback-preview', body='x' * 16385)) == 2
    assert 'x' * 50 not in capsys.readouterr().out


def test_observer_events_bind_distinct_names_and_original_profile(plugin, monkeypatch, tmp_path):
    mod, ctx, state, _, _ = plugin
    home = tmp_path / 'claire'
    home.mkdir()
    monkeypatch.setattr(sys.modules['hermes_constants'], 'get_hermes_home', lambda: home)
    monkeypatch.setenv('HERMES_HOME', str(home))
    mod.register(ctx)
    expected = {'pre_api_request', 'post_api_request', 'api_request_error', 'pre_tool_call', 'post_tool_call'}
    assert set(state['hooks']) == expected
    for event in sorted(expected):
        state['hooks'][event](session_id='attempt-session')
        assert state['events'][-1] == (event, {'session_id': 'attempt-session'})
        assert state['bound'][-2] == str(home)
        assert state['bound'][-1] == 'token'


def test_tool_rejects_cross_profile_field(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    result = json.loads(tools[0]["handler"]({"action": "start", "purpose": "implementation", "profile": "other"}))
    assert result["error"] == "invalid_or_denied"
    assert state["started"] == 0


def test_fast_registration_is_independent_of_routing_opt_in(plugin):
    mod, ctx, state, tools, _ = plugin
    state['enabled'] = False
    mod.register(ctx)
    assert state['fast_homes'] == [str(Path('C:/fake/profiles/claire'))]
    assert tools == []


def test_router_inherits_only_host_bound_parent_snapshot(plugin):
    mod, ctx, state, tools, _ = plugin
    snapshot = {'schema': 1, 'profile': 'claire', 'origin_session_id': 'parent-session',
                'parent_session_id': 'parent-session', 'mode': 'priority', 'expires_at': None}
    state['fast_snapshot'] = snapshot
    mod.register(ctx)
    handler = tools[0]['handler']
    result = json.loads(handler({'action': 'start', 'purpose': 'mechanical', 'prompt': 'bounded', 'cwd': 'C:/fake'},
                                session_id='parent-session', task_id='host-task'))
    assert result['status'] == 'running'
    assert state['fast_captures'] == [{'session_id': 'parent-session', 'profile': 'claire'}]
    assert state['router_kwargs']['fast_snapshot'] == snapshot
    assert state['router_kwargs']['runtime'].parent_session_id == 'parent-session'
    assert state['start_kwargs'] == {}
    before = len(state['fast_captures'])
    denied = json.loads(handler({'action': 'start', 'purpose': 'mechanical', 'fast_snapshot': snapshot}))
    assert denied['error'] == 'invalid_or_denied'
    assert len(state['fast_captures']) == before


def test_status_never_captures_or_changes_fast_mode(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    result = json.loads(tools[0]['handler']({'action': 'status', 'job_id': 'a' * 32}))
    assert result['status'] == 'failed'
    assert state.get('fast_captures', []) == []
