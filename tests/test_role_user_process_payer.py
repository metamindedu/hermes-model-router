"""The owner's main model on a user-installed external-process provider (for example a subscription
bridge) is an admitted payer route; shadows, endpoint overrides and other auth types stay refused."""
from types import SimpleNamespace
import pytest
from test_role_proposal import environment  # noqa: F401
from model_router import role_proposal as rp

NAME = 'fixture-process-bridge'


def _install(root, *, name=NAME, auth_type='external_process', aliases=(), base_url=None, command=None):
    import providers, sys
    base_url = f'process://{name}' if base_url is None else base_url
    command = sys.executable if command is None else command
    plugin = root / 'plugins' / 'model-providers' / 'fixture-process'
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / '__init__.py').write_text(
        'from providers import register_provider\nfrom providers.base import ProviderProfile\n'
        'class Bridge(ProviderProfile):\n    def create_client(self, **kwargs):\n        raise AssertionError("preview must never create a client")\n'
        f'register_provider(Bridge(name={name!r}, aliases={tuple(aliases)!r}, auth_type={auth_type!r}, base_url={base_url!r}, process_command={command!r}))\n', encoding='utf-8')
    providers.refresh_bound_home()


def _config(root, provider=NAME, model='bridge-model[1m]', extra=''):
    (root / 'config.yaml').write_text(
        f'model:\n  provider: {provider}\n  default: {model}\n{extra}fallback_providers: []\n', encoding='utf-8')


def _request(body, review):
    return dict(body, source_digest=review['source']['digest'], route_digest=review['payer']['route_digest'],
                consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})


def test_user_process_main_route_is_admitted_and_disclosed(environment):
    service, root, target, body = environment
    _install(root)
    _config(root, extra=f'  base_url: process://{NAME}\n  api_mode: chat_completions\n')
    review = rp.context(service, root, body, True)
    assert review['capability'] == {'available': True, 'reason_code': None}, review
    assert review['payer']['provider'] == NAME and review['payer']['model'] == 'bridge-model[1m]'
    assert review['payer']['transport'] == 'user_process'
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed={'description': 'Analyzes evidence'}, provider=NAME, model='bridge-model[1m]',
                               usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6))
    result = rp.generate(service, root, _request(body, review), complete)
    assert result['status'] == 'proposed', result
    assert len(calls) == 1 and not {'provider', 'model', 'profile', 'task'} & calls[0].keys()
    # Same digest across separate evaluations (context and generate run in separate CLI processes).
    assert rp.context(service, root, body, True)['payer']['route_digest'] == review['payer']['route_digest']


@pytest.mark.parametrize('case', ['endpoint', 'api_key', 'api_mode', 'oauth', 'builtin_alias', 'builtin_name', 'host_builtin_alias',
                                  'host_builtin_name', 'bundled_alias', 'router_keyword', 'tcp_endpoint', 'no_command',
                                  'named_provider', 'named_provider_label', 'custom_provider', 'custom_provider_shape', 'providers_shape'])
def test_user_process_lookalikes_refused(environment, case):
    service, root, target, body = environment
    if case == 'oauth':
        _install(root, auth_type='oauth_external')
    elif case == 'builtin_alias':
        _install(root, aliases=('anthropic',))
    elif case == 'builtin_name':
        _install(root, name='anthropic')
    elif case == 'host_builtin_alias':
        # A host built-in outside the payer allowlist is still a reserved name.
        _install(root, aliases=('xai-oauth',))
    elif case == 'host_builtin_name':
        _install(root, name='xai-oauth')
    elif case == 'bundled_alias':
        # A bundled provider plugin outside the static auth rows is reserved too.
        _install(root, aliases=('fireworks',))
    elif case == 'router_keyword':
        _install(root, name='moa')
    elif case == 'tcp_endpoint':
        _install(root, base_url='acp+tcp://fixture.invalid:9000')
    elif case == 'no_command':
        _install(root, command='definitely-not-an-installed-command-xyz')
    else:
        _install(root)
    extra = {'endpoint': '  base_url: https://fixture.invalid/v1\n', 'api_key': '  api_key: fixture-key\n',
             'api_mode': '  api_mode: responses\n'}.get(case, '')
    provider = {'builtin_name': 'anthropic', 'host_builtin_name': 'xai-oauth', 'router_keyword': 'moa'}.get(case, NAME)
    _config(root, provider=provider, extra=extra)
    # A same-name named route wins over the registered process client in Hermes' resolver.
    tail = {'named_provider': f'providers:\n  {NAME}:\n    base_url: https://fixture.invalid/v1\n',
            'named_provider_label': f'providers:\n  other:\n    name: {NAME.upper()}\n    base_url: https://fixture.invalid/v1\n',
            'custom_provider': f'custom_providers:\n  - name: {NAME}\n    base_url: https://fixture.invalid/v1\n',
            'custom_provider_shape': 'custom_providers: {}\n', 'providers_shape': 'providers: [broken]\n'}.get(case)
    if tail:
        (root / 'config.yaml').write_text((root / 'config.yaml').read_text(encoding='utf-8') + tail, encoding='utf-8')
    review = rp.context(service, root, body, True)
    assert review['capability'] == {'available': False, 'reason_code': 'payer_unavailable'}, (case, review)


def test_changed_process_arguments_change_the_route_digest(environment, monkeypatch):
    service, root, target, body = environment
    _install(root)
    _config(root)
    first = rp.context(service, root, body, True)
    assert first['capability']['available'], first
    import hermes_cli.auth as auth
    original = auth._external_process_spec
    def changed(config):
        command, args, url, resolved, envs = original(config)
        return command, [*args, '--other-bridge.py'], url, resolved, envs
    monkeypatch.setattr(auth, '_external_process_spec', changed)
    second = rp.context(service, root, body, True)
    assert second['capability']['available'] and second['payer']['route_digest'] != first['payer']['route_digest']


def test_user_alias_on_auto_refuses_even_a_builtin_payer(environment):
    service, root, target, body = environment
    (root / 'config.yaml').write_text('model: {provider: openrouter, default: example/model}\nfallback_providers: []\n', encoding='utf-8')
    assert rp.context(service, root, body, True)['capability']['available']
    _install(root, aliases=('auto',))
    assert rp.context(service, root, body, True)['capability'] == {'available': False, 'reason_code': 'payer_unavailable'}


def test_named_endpoint_for_a_builtin_fallback_is_refused(environment):
    service, root, target, body = environment
    (root / 'config.yaml').write_text('model: {provider: openrouter, default: example/model}\nfallback_providers: [{provider: groq, model: fixture}]\n'
                                      'providers:\n  groq:\n    base_url: https://fixture.invalid/v1\n', encoding='utf-8')
    assert rp.context(service, root, body, True)['capability'] == {'available': False, 'reason_code': 'payer_unavailable'}


def test_user_provider_cannot_launder_through_fallback_chain(environment):
    service, root, target, body = environment
    _install(root)
    (root / 'config.yaml').write_text(
        f'model:\n  provider: openrouter\n  default: example/model\nfallback_providers: [{{provider: {NAME}, model: bridge-model}}]\n', encoding='utf-8')
    assert rp.context(service, root, body, True)['capability'] == {'available': False, 'reason_code': 'payer_unavailable'}
