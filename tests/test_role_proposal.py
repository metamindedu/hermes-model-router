import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from model_router import role_proposal as rp
from model_router.service import Service
from model_router.installation import _root_identity


@pytest.fixture
def environment(tmp_path, monkeypatch):
    root = tmp_path / 'home'
    target = root / 'profiles' / 'worker'
    target.mkdir(parents=True)
    (root / 'config.yaml').write_text('model:\n  provider: openrouter\n  default: example/model\nfallback_providers: []\n', encoding='utf-8')
    (target / 'config.yaml').write_text('{}\n', encoding='utf-8')
    (target / 'profile.yaml').write_text('description: Analyst\n', encoding='utf-8')
    (target / 'SOUL.md').write_text('# Private\nDO NOT SEND\n## Role\nAnalyze evidence\n## Other\nDO NOT SEND\n', encoding='utf-8')
    monkeypatch.setattr('hermes_constants.get_default_hermes_root', lambda: root)
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(root)
    try:
        service = Service(root=root)
        body = {'schema': 1, 'owner_profile': 'default', 'base_identity': _root_identity(root), 'target_profile': 'worker'}
        yield service, root, target, body
    finally:
        reset_hermes_home_override(token)


def test_review_and_single_native_facade_operation(environment):
    service, root, target, body = environment
    before = {p.name: p.read_bytes() for p in (target / 'profile.yaml', target / 'SOUL.md')}
    rp._owner(service, root, body)
    rp._source(service, body['target_profile'], body['base_identity'])
    rp._payer(service, body['owner_profile'])
    context = rp.context(service, root, body, True)
    assert context.get('capability', {}).get('available'), context
    assert context['source']['native_description'] == 'Analyst'
    assert context['source']['soul_role_excerpt'] == 'Analyze evidence'
    assert 'DO NOT SEND' not in json.dumps(context)
    request = dict(body, source_digest=context['source']['digest'], route_digest=context['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed={'description': 'Analyzes evidence'}, provider='openrouter', model='example/model', usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6))
    result = rp.generate(service, root, request, complete)
    assert result['status'] == 'proposed', result
    assert len(calls) == 1 and 'tools' not in calls[0]
    assert not {'provider', 'model', 'profile', 'task', 'agent_id', 'temperature'} & calls[0].keys()
    assert json.loads(calls[0]['input'][0]['text'])['soul_role_excerpt'] == 'Analyze evidence'
    assert result['model_attribution']['provider_verified'] is False
    assert before == {p.name: p.read_bytes() for p in (target / 'profile.yaml', target / 'SOUL.md')}


def test_stale_source_and_invalid_output_never_retried(environment):
    service, root, target, body = environment
    rp._owner(service, root, body)
    rp._source(service, body['target_profile'], body['base_identity'])
    rp._payer(service, body['owner_profile'])
    context = rp.context(service, root, body, True)
    assert context.get('capability', {}).get('available'), context
    request = dict(body, source_digest=context['source']['digest'], route_digest=context['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    calls = []
    def bad(**kw):
        calls.append(kw)
        return SimpleNamespace(parsed={'description': 'secret: bad'}, provider='', model='', usage=None)
    assert rp.generate(service, root, request, bad)['code'] == 'invalid_output'
    assert len(calls) == 1
    (target / 'SOUL.md').write_text('## Role\nChanged', encoding='utf-8')
    rp._owner(service, root, body)
    rp._source(service, body['target_profile'], body['base_identity'])
    rp._payer(service, body['owner_profile'])
    fresh = rp.context(service, root, body, True)
    assert fresh.get('status') != 'error', fresh
    assert rp.generate(service, root, request, bad)['code'] == 'source_changed'
    assert len(calls) == 1


def test_unavailable_context_retains_payer_and_sources(environment):
    service, root, target, body = environment
    (target / 'profile.yaml').unlink()
    (target / 'SOUL.md').unlink()
    dto = rp.context(service, root, body, True)
    assert dto['capability'] == {'available': False, 'reason_code': 'no_evidence'}
    assert dto['payer']['provider'] == 'openrouter'
    assert dto['source']['native_description'] == ''
    (root / 'config.yaml').write_text('model: {provider: auto, default: foo}\n', encoding='utf-8')
    dto = rp.context(service, root, body, True)
    assert dto['capability']['reason_code'] == 'payer_unavailable'
    assert dto['payer']['provider'] is None


def test_owner_config_change_during_facade_returns_stale(environment):
    service, root, target, body = environment
    ctx = rp.context(service, root, body, True)
    req = dict(body, source_digest=ctx['source']['digest'], route_digest=ctx['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    def call(**kwargs):
        (root / 'config.yaml').write_text('model: {provider: openrouter, default: changed}\n', encoding='utf-8')
        return SimpleNamespace(parsed={'description':'Analyzes evidence'}, provider='openrouter', model='changed', usage=None)
    assert rp.generate(service, root, req, call)['code'] == 'stale_result'
