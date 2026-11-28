import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import json
import re
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
    for name, cls in [("service", Service)]:
        child = ModuleType(package.__name__ + "." + name)
        setattr(child, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, child.__name__, child)
    # The real cli_reply is tested in test_slots.py; this stand-in shows the handler printed through it.
    sys.modules[package.__name__ + ".service"].cli_reply = lambda result: "MODEL_ROUTER_JSON:" + json.dumps({**result, "via_cli_reply": True}, ensure_ascii=False, separators=(",", ":"))
    constants = ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: Path("C:/fake/profiles/claire")
    constants.set_hermes_home_override = lambda home: state["bound"].append(str(home)) or "token"
    constants.reset_hermes_home_override = lambda token: state["bound"].append(token)
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
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
    native_module = ModuleType(package.__name__ + '.native_delegation')
    native_module.register_native_delegation = lambda ctx, home: state.setdefault('provider_homes', []).append(str(home))
    monkeypatch.setitem(sys.modules, native_module.__name__, native_module)

    # This fixture isolates root registration; the adapters' real
    # registration/authority/inertness is exercised by their own native tests.
    for feature, registrar, key in [('execution_roster', 'register_execution_roster', 'roster_homes'),
                                     ('profile_jobs', 'register_profile_jobs', 'profile_job_homes'),
                                     ('advise_guard', 'register_advise_guard', 'advise_homes')]:
        child = ModuleType(package.__name__ + '.' + feature)
        def registrar_fn(ctx, home, _key=key, **kwargs):
            state.setdefault(_key, []).append(str(home))
            state.setdefault(_key + '_kwargs', []).append(kwargs)
        setattr(child, registrar, registrar_fn)
        monkeypatch.setitem(sys.modules, child.__name__, child)

    tools, skills = [], []
    ctx = SimpleNamespace(register_cli_command=lambda *args: state.update(cli=args), register_tool=lambda **kwargs: tools.append(kwargs), register_skill=lambda *args: skills.append(args), register_hook=lambda event, callback: state.setdefault('hooks', {}).update({event: callback}))
    return mod, ctx, state, tools, skills


def test_disabled_profile_keeps_config_reads_and_provider_registration(plugin):
    mod, ctx, state, tools, skills = plugin
    state['enabled'] = False
    mod.register(ctx)
    assert skills == [] and len(tools) == 1 and tools[0]['check_fn']()
    assert state['provider_homes'] == [str(Path('C:/fake/profiles/claire'))]
    assert state['roster_homes'] == state['profile_job_homes'] == state['provider_homes'] == state['advise_homes']
    assert json.loads(tools[0]['handler']({'action': 'config'}))['enabled'] is False
    # The advisor tool follows the profile's routing switch at check time, not at registration.
    [advise_kwargs] = state['advise_homes_kwargs']
    assert advise_kwargs['routing_enabled']() is False
    state['enabled'] = True
    assert advise_kwargs['routing_enabled']() is True


def test_active_profile_registers_the_config_tool_and_policy(plugin):
    mod, ctx, state, tools, skills = plugin
    mod.register(ctx)
    assert tools[0]['name'] == 'coding_route' and skills[0][0] == 'adaptive-coding-orchestration'
    assert json.loads(tools[0]['handler']({'action': 'config'}))['enabled'] is True
    assert state['bound'][-1] == 'token'


def test_registered_discovery_copy_defaults_small_work_to_main(plugin):
    mod, ctx, state, tools, skills = plugin
    mod.register(ctx)
    description = tools[0]['schema']['description']
    assert 'Main handles small bounded changes directly' in description
    assert 'at least two substantive independent workstreams' in description
    assert 'large context, long runtime' in description
    assert "on Main's own model, design stays with Main" in description
    assert 'unless explicitly requested by the user' in description
    assert 'required reviews (semantic-final, independent-review) remain mandatory' in description
    assert not re.search(r'heavy|light', description, re.IGNORECASE)
    assert 'Main handles small bounded changes directly' in skills[0][2]
    assert tools[0]['schema']['parameters']['required'] == ['action']


def test_the_tool_only_reads_config(plugin):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    props = tools[0]['schema']['parameters']['properties']
    assert props == {'action': {'type': 'string', 'enum': ['config']}}
    assert tools[0]['schema']['parameters']['additionalProperties'] is False


@pytest.mark.parametrize('args', [
    {'action': 'start', 'purpose': 'implementation'}, {'action': 'status', 'job_id': 'a' * 32},
    {'action': 'join', 'job_id': 'owned-job', 'wait_timeout': 30}, {'action': 'config', 'profile': 'other'}, {},
])
def test_every_other_call_is_refused_and_launches_nothing(plugin, args):
    mod, ctx, state, tools, _ = plugin
    mod.register(ctx)
    result = json.loads(tools[0]['handler'](args, session_id='parent-session', task_id='host-task'))
    assert result['error'] == 'invalid_or_denied'
    assert state.get('fast_captures', []) == []


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
    reply = json.loads(output.split('MODEL_ROUTER_JSON:', 1)[1])
    assert reply['plan_id'] == 'f' * 32 and reply['via_cli_reply'] is True, 'a plan reply is bounded to fit one Hermes CLI reply'
    assert state['fallback_body'] == body
    assert state['bound'][-1] == 'token'
    assert handler(SimpleNamespace(operation='fallback-preview', body='x' * 16385)) == 2
    assert 'x' * 50 not in capsys.readouterr().out


def test_registration_adds_no_api_or_tool_hooks_of_its_own(plugin):
    mod, ctx, state, _, _ = plugin
    mod.register(ctx)
    # Every hook belongs to a feature module (stubbed here); the root registers none.
    assert state.get('hooks', {}) == {}


def test_fast_registration_is_independent_of_routing_opt_in(plugin):
    mod, ctx, state, tools, _ = plugin
    state['enabled'] = False
    mod.register(ctx)
    assert state['fast_homes'] == [str(Path('C:/fake/profiles/claire'))]
    assert len(tools) == 1 and tools[0]["check_fn"]()
