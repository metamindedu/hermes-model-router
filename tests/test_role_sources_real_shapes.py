"""Role sources in the shapes real profiles have: a large Desktop-written profile.yaml, large SOULs,
and linked skill folders."""
import json
import os
import subprocess
import pytest
from test_role_proposal import environment  # noqa: F401
from model_router import role_proposal as rp, role_metadata as rm


def test_large_desktop_profile_yaml_still_yields_its_description(environment):
    service, root, target, body = environment
    padding = 'x' * 40000
    (target / 'profile.yaml').write_text(f'description: Analyst\nui_meta:\n  blob: "{padding}"\n', encoding='utf-8')
    review = rp.context(service, root, body, True)
    assert review['capability']['available'], review
    assert review['source']['native_description'] == 'Analyst'


def test_profile_yaml_token_and_depth_budgets_refuse_before_loading(environment, monkeypatch):
    service, root, target, body = environment
    many = 'description: Analyst\nui_meta:\n' + ''.join(f'  k{i}: {i}\n' for i in range(25000))
    (target / 'profile.yaml').write_text(many, encoding='utf-8')
    loads = []
    import yaml
    monkeypatch.setattr(yaml, 'safe_load', lambda *a, **k: loads.append(1) or {})
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'
    deep = 'description: Analyst\nui_meta:\n' + ''.join('  ' * (i + 1) + f'k{i}:\n' for i in range(40)) + '  ' * 41 + 'leaf: 1\n'
    (target / 'profile.yaml').write_text(deep, encoding='utf-8')
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'
    assert loads == []


def test_parsed_metadata_is_cached_by_content(environment, monkeypatch):
    service, root, target, body = environment
    (target / 'profile.yaml').write_text('description: Cached analyst\n', encoding='utf-8')
    assert rm.resolve(service, 'worker')['default_description'] == 'Cached analyst'
    import yaml
    monkeypatch.setattr(yaml, 'scan', lambda *a, **k: pytest.fail('re-scanned unchanged metadata'))
    assert rm.resolve(service, 'worker')['default_description'] == 'Cached analyst'


def test_oversized_soul_is_left_out_not_cut(environment):
    service, root, target, body = environment
    (target / 'SOUL.md').write_text('# Big\n' + 'a' * (rp.SOUL_LIMIT + 10), encoding='utf-8')
    review = rp.context(service, root, body, True)
    assert review['capability']['available'], review
    assert review['source']['soul_text'] == '' and 'soul_too_large' in review['source']['omitted_sources']


def test_soul_that_would_overflow_the_cli_reply_is_left_out(environment):
    service, root, target, body = environment
    # Under the byte cap, but every newline doubles when JSON-escaped.
    (target / 'SOUL.md').write_bytes('\n'.join('x' for _ in range(16000)).encode('utf-8'))
    assert (target / 'SOUL.md').stat().st_size < rp.SOUL_LIMIT
    review = rp.context(service, root, body, True)
    assert review['source']['soul_text'] == '' and 'soul_too_large' in review['source']['omitted_sources']
    assert len(json.dumps(review, ensure_ascii=False)) < 48000


def test_large_korean_soul_is_sent_whole(environment):
    service, root, target, body = environment
    text = '# 작업자\n' + '\n'.join(f'- 증거를 분석하고 보고서를 작성한다 {i}' for i in range(500))
    assert len(text.encode('utf-8')) < rp.SOUL_LIMIT
    (target / 'SOUL.md').write_text(text, encoding='utf-8')
    review = rp.context(service, root, body, True)
    assert review['source']['soul_text'] == text


def _link_dir(link, target):
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def test_linked_skill_folder_is_skipped_not_fatal(environment, tmp_path):
    service, root, target, body = environment
    skills = target / 'skills'
    (skills / 'local-skill').mkdir(parents=True)
    (skills / 'local-skill' / 'SKILL.md').write_text('---\nname: local-skill\n---\n', encoding='utf-8')
    outside = tmp_path / 'outside-skill'
    outside.mkdir()
    (outside / 'SKILL.md').write_text('---\nname: outside\n---\n', encoding='utf-8')
    _link_dir(skills / 'linked-skill', outside)
    review = rp.context(service, root, body, True)
    assert review['source']['enabled_skill_names'] == ['local-skill']
    assert 'linked_skills_omitted' in review['source']['omitted_sources']


def test_symlinked_skill_folder_is_skipped_not_fatal(environment, tmp_path):
    service, root, target, body = environment
    skills = target / 'skills'
    (skills / 'local-skill').mkdir(parents=True)
    (skills / 'local-skill' / 'SKILL.md').write_text('---\nname: local-skill\n---\n', encoding='utf-8')
    outside = tmp_path / 'outside-skill'
    outside.mkdir()
    (outside / 'SKILL.md').write_text('---\nname: outside\n---\n', encoding='utf-8')
    try:
        os.symlink(outside, skills / 'symlinked-skill', target_is_directory=True)
    except OSError:
        pytest.skip('symlinks need privilege here')
    review = rp.context(service, root, body, True)
    assert review['source']['enabled_skill_names'] == ['local-skill']
    assert 'linked_skills_omitted' in review['source']['omitted_sources']


def test_oversized_hardlinked_soul_refuses_the_target(environment, tmp_path):
    service, root, target, body = environment
    outside = root / 'outside-soul.md'
    outside.write_bytes(b'a' * (rp.SOUL_LIMIT + 10))
    (target / 'SOUL.md').unlink()
    try:
        os.link(outside, target / 'SOUL.md')
    except OSError:
        pytest.skip('hard links unavailable')
    review = rp.context(service, root, body, True)
    assert review['capability']['reason_code'] is not None
    assert 'source_unavailable' in review['source']['omitted_sources']
    assert 'soul_too_large' not in review['source']['omitted_sources']


def test_indentless_sequences_count_toward_the_depth_budget(environment):
    service, root, target, body = environment
    lines, indent = ['description: Analyst', 'ui_meta:'], ''
    # 11 levels: scanner depth stays under 32, parser event depth exceeds it.
    for i in range(11):
        lines.append(f'{indent}k{i}:')
        lines.append(f'{indent}- n{i}:')
        indent += '    '
    lines.append(f'{indent}leaf: 1')
    (target / 'profile.yaml').write_bytes(('\n'.join(lines) + '\n').encode('utf-8'))
    assert rm.resolve(service, 'worker')['state'] == 'unavailable'


def test_heading_only_soul_is_not_evidence(environment):
    service, root, target, body = environment
    (target / 'profile.yaml').write_text('{}\n', encoding='utf-8')
    for soul in ('# SOUL\n\n## Role\n', 'SOUL\n====\n\nRole\n----\n'):
        (target / 'SOUL.md').write_text(soul, encoding='utf-8')
        review = rp.context(service, root, body, True)
        assert review['capability'] == {'available': False, 'reason_code': 'no_evidence'}, soul
    (target / 'SOUL.md').write_text('SOUL\n====\nAnalyzes evidence\n', encoding='utf-8')
    assert rp.context(service, root, body, True)['capability']['available']
