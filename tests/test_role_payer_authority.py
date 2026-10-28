"""Regressions for independently reproduced role payer endpoint/authority defects."""
from types import SimpleNamespace
import pytest
from test_role_proposal import environment
from model_router import role_proposal as rp


@pytest.mark.parametrize('fallback', [False, True])
def test_native_codex_endpoint_key_refuses_before_facade(environment, monkeypatch, fallback):
    service, root, target, body = environment
    config = ('model: {provider: openrouter, default: fixture}\nfallback_providers: [{provider: openai-codex, model: gpt-fixture}]\n' if fallback else 'model: {provider: openai-codex, default: gpt-fixture}\nfallback_providers: []\n')
    (root / 'config.yaml').write_text(config, encoding='utf-8')
    monkeypatch.delenv('HERMES_CODEX_BASE_URL', raising=False)
    review = rp.context(service, root, body, True)
    assert review['capability']['available'], review
    request = dict(body, source_digest=review['source']['digest'], route_digest=review['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    monkeypatch.setenv('HERMES_CODEX_BASE_URL', 'https://fixture-endpoint.invalid/v1')
    after = rp.context(service, root, body, True)
    assert after['capability'] == {'available': False, 'reason_code': 'payer_unavailable'}
    assert rp.generate(service, root, request, lambda **kw: pytest.fail('endpoint override reached facade'))['code'] == 'payer_unavailable'


@pytest.mark.parametrize('route,alias,fallback', [('gemini', False, False), ('gemini', False, True), ('gemini', True, False), ('openai', True, False)])
def test_same_metadata_user_transport_and_alias_shadow_refused(environment, route, alias, fallback):
    service, root, target, body = environment
    import providers
    from hermes_cli.auth import PROVIDER_REGISTRY
    # Normal bundled/generic routes are admitted before the scoped user shadow.
    config = (f'model: {{provider: openrouter, default: fixture}}\nfallback_providers: [{{provider: {route}, model: fixture-model}}]\n' if fallback else f'model: {{provider: {route}, default: fixture-model}}\nfallback_providers: []\n')
    (root / 'config.yaml').write_text(config, encoding='utf-8')
    before = rp.context(service, root, body, True)
    assert before['capability']['available'], before
    request = dict(body, source_digest=before['source']['digest'], route_digest=before['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})
    plugin = root / 'plugins' / 'model-providers' / 'fixture-shadow'
    plugin.mkdir(parents=True)
    canonical = 'fixture-shadow' if alias else route
    aliases = repr((route, 'openai-api')) if route == 'openai' else repr((route,)) if alias else '()'
    (plugin / '__init__.py').write_text('from providers import register_provider\nfrom providers.base import ProviderProfile\nclass Shadow(ProviderProfile):\n    def create_client(self, **kwargs):\n        raise AssertionError("preview must never create a client")\nregister_provider(Shadow(name=' + repr(canonical) + ', aliases=' + aliases + '))\n', encoding='utf-8')
    providers.refresh_bound_home()
    assert providers.provider_source(route) == 'user'
    if route == 'gemini' and not alias:
        assert PROVIDER_REGISTRY.get('gemini') == dict.get(PROVIDER_REGISTRY, 'gemini')
    after = rp.context(service, root, body, True)
    assert after['capability'] == {'available': False, 'reason_code': 'payer_unavailable'}
    assert rp.generate(service, root, request, lambda **kw: pytest.fail('user transport reached facade'))['code'] == 'payer_unavailable'
