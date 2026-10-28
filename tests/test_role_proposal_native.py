from types import SimpleNamespace
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from test_role_proposal import environment
from hermes_cli.plugins import PluginContext
from hermes_cli.plugins_manifest import PluginManifest
from model_router import role_proposal as rp


def test_real_ctx_facade_without_override_grants(environment, monkeypatch):
    import agent.auxiliary_client as native
    service, root, target, body = environment
    context = rp.context(service, root, body, True)
    assert context.get('capability', {}).get('available'), context
    request = dict(body, source_digest=context['source']['digest'], route_digest=context['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    calls = []
    def fake_wire(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model='example/model', choices=[SimpleNamespace(message=SimpleNamespace(content='{"description":"Analyzes evidence"}'))], usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5))
    monkeypatch.setattr(native, 'call_llm', fake_wire)
    ctx = PluginContext(PluginManifest(name='model-router'), None)
    result = rp.generate(service, root, request, ctx.llm.complete_structured)
    assert result['status'] == 'proposed', result
    assert len(calls) == 1
    kw = calls[0]
    assert kw['provider'] is None and kw['model'] is None and kw['task'] is None
    assert kw['timeout'] == 30 and kw['max_tokens'] == 512
    assert 'tools' not in kw and kw['extra_body']['response_format']['type'] == 'json_schema'
    assert kw['messages'][0]['role'] == 'system'


def test_registered_cli_injects_actual_ctx_facade(environment, monkeypatch, capsys):
    import agent.auxiliary_client as native
    service, root, target, body = environment
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('test_role_plugin', repo / '__init__.py', submodule_search_locations=[str(repo)])
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, 'test_role_plugin', plugin)
    spec.loader.exec_module(plugin)
    watch = importlib.import_module('test_role_plugin.model_router.native_watchdog')
    fast = importlib.import_module('test_role_plugin.model_router.fast_inheritance')
    delegate = importlib.import_module('test_role_plugin.model_router.native_delegation')
    monkeypatch.setattr(watch, 'register_native_watchdog', lambda *a: None)
    monkeypatch.setattr(fast, 'register_fast_inheritance', lambda *a: None)
    monkeypatch.setattr(delegate, 'register_native_delegation', lambda *a: None)
    ctx = PluginContext(PluginManifest(name='model-router'), None)
    state = {}
    monkeypatch.setattr(ctx, 'register_cli_command', lambda *a: state.update(cli=a))
    monkeypatch.setattr(ctx, 'register_tool', lambda *a, **kw: None)
    monkeypatch.setattr(ctx, 'register_hook', lambda *a, **kw: None)
    monkeypatch.setattr(ctx, 'register_skill', lambda *a, **kw: None)
    calls = []
    def fake_wire(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model='example/model', choices=[SimpleNamespace(message=SimpleNamespace(content='{"description":"Analyzes evidence"}'))], usage=None)
    monkeypatch.setattr(native, 'call_llm', fake_wire)
    plugin.register(ctx)
    handler = state['cli'][3]
    def invoke(op, payload):
        assert handler(SimpleNamespace(operation=op, body=json.dumps(payload))) == 0
        output = capsys.readouterr().out
        return json.loads(output.split('MODEL_ROUTER_JSON:')[-1])
    review = invoke('role-proposal-context', body)
    assert review.get('capability', {}).get('available'), review
    assert calls == []
    request = dict(body, source_digest=review['source']['digest'], route_digest=review['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    result = invoke('role-proposal', request)
    assert result['status'] == 'proposed', result
    assert len(calls) == 1
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(target)
    try:
        assert invoke('role-proposal-context', body)['code'] == 'owner_mismatch'
    finally:
        reset_hermes_home_override(token)
    assert len(calls) == 1
