"""Role source/payer counterexamples; fake homes and no network."""
from types import SimpleNamespace
import json
import os
import pytest
from test_role_proposal import environment
from model_router import role_proposal as rp
from model_router import role_metadata as rm


def request(service, root, body):
    review = rp.context(service, root, body, True)
    assert review['capability']['available'], review
    return review, dict(body, source_digest=review['source']['digest'], route_digest=review['payer']['route_digest'], consent={'send_reviewed_sources': True, 'use_owner_native_policy': True})


def test_enabled_local_skill_names_are_evidence_but_bodies_and_disabled_are_not(environment, monkeypatch):
    service, root, target, body = environment
    (target / 'profile.yaml').unlink()
    (target / 'SOUL.md').unlink()
    (target / 'config.yaml').write_text('skills:\n  disabled: [skip-me]\n', encoding='utf-8')
    for name in ['evidence', 'skip-me']:
        directory = target / 'skills' / 'research' / name
        directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text('DO_NOT_SEND_SKILL_BODY_OR_PRIVATE_TEXT', encoding='utf-8')
    read = rp.read_bounded
    def spy(path, *args, **kwargs):
        assert path.name != 'SKILL.md', 'skill body must not be opened'
        return read(path, *args, **kwargs)
    monkeypatch.setattr(rp, 'read_bounded', spy)
    review, req = request(service, root, body)
    assert review['source']['enabled_skill_names'] == ['research/evidence']
    assert 'DO_NOT_SEND' not in json.dumps(review)
    calls = []
    rp.generate(service, root, req, lambda **kw: calls.append(kw) or SimpleNamespace(parsed={'description': 'Collects research evidence'}, provider='openrouter', model='example/model', usage=None))
    assert len(calls) == 1
    assert json.loads(calls[0]['input'][0]['text'])['enabled_skill_names'] == ['research/evidence']
    (target / 'config.yaml').write_text('skills:\n  disabled: [evidence, skip-me]\n', encoding='utf-8')
    assert rp.generate(service, root, req, lambda **kw: pytest.fail('stale skill inventory called model'))['code'] in ('source_changed', 'no_evidence')


def test_skill_inventory_is_bounded_and_external_skill_paths_are_not_traversed(environment):
    service, root, target, body = environment
    outside = root.parent / 'private-external'
    outside.mkdir()
    (outside / 'SKILL.md').write_text('PRIVATE_EXTERNAL_BODY', encoding='utf-8')
    (target / 'config.yaml').write_text('skills:\n  external_dirs: [' + json.dumps(str(outside)) + ']\n', encoding='utf-8')
    for index in range(40):
        skill = target / 'skills' / ('role-' + str(index).zfill(2))
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('NO_BODY', encoding='utf-8')
    review, _ = request(service, root, body)
    assert len(review['source']['enabled_skill_names']) == 32
    assert review['source']['truncated'] is True
    assert 'external_skills_omitted' in review['source']['omitted_sources']
    assert str(outside) not in json.dumps(review) and 'PRIVATE_EXTERNAL_BODY' not in json.dumps(review)


def test_credential_environment_presence_change_stales_without_reading_value(environment, monkeypatch):
    service, root, target, body = environment
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    review, req = request(service, root, body)
    assert 'fixture-owner-key' not in json.dumps(review)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fixture-owner-key-b')
    assert rp.generate(service, root, req, lambda **kw: pytest.fail('payer changed but model called'))['code'] == 'payer_changed'


def test_payer_never_acquires_credential_environment_values(environment, monkeypatch):
    service, root, target, body = environment
    import hermes_cli.auth  # metadata module loaded, no provider requests
    class PresenceOnly(dict):
        def __getitem__(self, key):
            if key == 'OPENROUTER_API_KEY':
                pytest.fail('plugin acquired a credential value')
            return super().__getitem__(key)
        def get(self, key, default=None):
            if key == 'OPENROUTER_API_KEY':
                pytest.fail('plugin acquired a credential value')
            return super().get(key, default)
    env = PresenceOnly(os.environ)
    env['OPENROUTER_API_KEY'] = 'fixture-never-readable'
    monkeypatch.setattr(rp.os, 'environ', env)
    assert len(rp._payer_provenance(service, root, {'openrouter'})) == 64


def test_endpoint_overrides_are_unavailable_instead_of_sending_role_sources(environment, monkeypatch):
    service, root, target, body = environment
    monkeypatch.setenv('OPENROUTER_BASE_URL', 'https://fixture.invalid/v1')
    review = rp.context(service, root, body, True)
    assert review['capability']['available'] is False
    assert review['capability']['reason_code'] == 'payer_unavailable'
    assert 'fixture.invalid' not in json.dumps(review)


def test_owner_dotenv_provenance_changes_without_reading_its_content(environment, monkeypatch):
    service, root, target, body = environment
    dotenv = root / '.env'
    dotenv.write_text('DO_NOT_READ_PROVIDER_KEY=fixture-a\n', encoding='utf-8')
    original = rp.read_bounded
    def guarded(path, *args, **kwargs):
        assert path.name not in ('.env', 'auth.json'), 'role code must not read credential file bytes'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(rp, 'read_bounded', guarded)
    review, req = request(service, root, body)
    assert 'DO_NOT_READ_PROVIDER_KEY' not in json.dumps(review)
    dotenv.write_text('DO_NOT_READ_PROVIDER_KEY=fixture-b-changed-length\n', encoding='utf-8')
    assert rp.generate(service, root, req, lambda **kw: pytest.fail('changed credential provenance called model'))['code'] == 'payer_changed'


def test_known_sensitive_source_is_omitted_before_preview_or_model(environment):
    service, root, target, body = environment
    (target / 'SOUL.md').write_text('## Role\nAnalyze evidence\nAPI_KEY = fixture-sensitive-credential-value\n', encoding='utf-8')
    review, req = request(service, root, body)
    assert 'fixture-sensitive' not in json.dumps(review)
    assert review['source']['soul_role_excerpt'] == ''
    assert 'soul_sensitive' in review['source']['omitted_sources']
    (target / 'profile.yaml').write_text('description: "API_KEY = fixture-sensitive-credential-value"\n', encoding='utf-8')
    dto = rm.resolve(service, 'worker')
    assert dto['state'] == 'unavailable' and dto['default_description'] == ''


def test_fenced_example_role_is_not_source_material(environment):
    service, root, target, body = environment
    (target / 'SOUL.md').write_text('```markdown\n## Role\nPRIVATE_FENCED_EXAMPLE\n```\n## Role\nCollect evidence\n## Other\nPRIVATE_OTHER\n', encoding='utf-8')
    review, _ = request(service, root, body)
    assert review['source']['soul_role_excerpt'] == 'Collect evidence'
    assert 'PRIVATE_' not in json.dumps(review)


def test_hardlinked_skill_entry_is_not_followed_or_sent(environment):
    service, root, target, body = environment
    skill = target / 'skills' / 'linked'
    skill.mkdir(parents=True)
    source = root / 'credential-sentinel'
    source.write_text('PRIVATE_VALUE', encoding='utf-8')
    try:
        os.link(source, skill / 'SKILL.md')
    except OSError:
        pytest.skip('hardlinks unavailable')
    review, _ = request(service, root, body)
    assert review['source']['enabled_skill_names'] == []
    assert 'skills_unavailable' in review['source']['omitted_sources']
    assert 'PRIVATE_VALUE' not in json.dumps(review)
