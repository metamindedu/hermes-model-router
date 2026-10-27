"""Genuine template/profile-seed integration in a credential-free child home."""
from pathlib import Path
import os
import subprocess
import sys
import textwrap
import pytest


@pytest.mark.parametrize('mode', ['explicit_template', 'native_seed'])
def test_actual_template_and_fresh_profile_have_no_saved_backend(tmp_path, mode):
    home = tmp_path / 'template-home'
    home.mkdir()
    env = dict(os.environ)
    if mode == 'explicit_template' and not Path(env.get('HERMES_TEST_CONFIG_TEMPLATE', '')).is_file():
        pytest.skip('explicit compatible Hermes config template unavailable')
    env['INITIAL_SETUP_SEED_MODE'] = mode
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               LOCALAPPDATA=str(home/'AppData/Local'), APPDATA=str(home/'AppData/Roaming'),
               HERMES_DISABLE_LAZY_INSTALLS='1', PYTHONDONTWRITEBYTECODE='1')
    for key in ('LOCALAPPDATA','APPDATA'): Path(env[key]).mkdir(parents=True)
    script = textwrap.dedent(r'''
        import copy, os
        from pathlib import Path
        import hermes_cli
        from hermes_constants import get_hermes_home, get_default_hermes_root
        from hermes_cli.profiles import create_profile
        from hermes_cli.config import read_user_config_raw, save_config, seed_config_file
        from model_router.yaml_compat import yaml
        from model_router import effective_config, native_settings as ns
        root = Path(get_hermes_home())
        assert Path(get_default_hermes_root()).resolve() == root.resolve()
        template = Path(os.environ['HERMES_TEST_CONFIG_TEMPLATE']) if os.environ['INITIAL_SETUP_SEED_MODE'] == 'explicit_template' else None
        seed_config_file(root/'config.yaml', template)
        raw = read_user_config_raw(root/'config.yaml')
        assert isinstance(raw, dict)
        assert 'backend' not in (raw.get('delegation') or {})
        raw['model'] = {'provider': 'openai-codex', 'default': 'offline-fixture'}
        save_config(raw)
        default = read_user_config_raw(root/'config.yaml')
        assert 'backend' not in default.get('delegation', {})
        profile = create_profile('fresh-seeded', no_alias=True, no_skills=True)
        assert profile.resolve().parent == (root/'profiles').resolve()
        named = read_user_config_raw(profile/'config.yaml')
        assert 'backend' not in named.get('delegation', {})
        assert named['model']['default'] == 'offline-fixture'
        for path in (root, profile):
            snap = effective_config.read_key_scoped(path, ns.KEYS)
            assert not snap.raw_present(ns.KEY_BACKEND)
            assert snap.raw(ns.KEY_BACKEND) is None
        print('actual_template_and_profile_seed=PASS')
    ''')
    result = subprocess.run([sys.executable, '-B', '-c', script], env=env, cwd=Path(__file__).resolve().parents[1],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')[-2500:]
    assert b'actual_template_and_profile_seed=PASS' in result.stdout
