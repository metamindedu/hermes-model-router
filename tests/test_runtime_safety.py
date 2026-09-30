from contextvars import Context
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from test_routing import _make_router, _start
from model_router.runtime_tracking import capture_runtime, RouteRuntime, DesktopSeedUnavailable


@pytest.mark.parametrize('own_key', [False, True])
def test_spawn_scrubs_foreign_host_credentials_and_overlays_only_target(tmp_path, monkeypatch, own_key):
    router, _, root, calls = _make_router(tmp_path, monkeypatch)
    home = root / 'profiles/claire'
    (home / 'config.yaml').write_text('{}', encoding='utf-8')
    if own_key:
        (home / '.env').write_text('DEEPSEEK_API_KEY=TARGET_CANARY\n', encoding='utf-8')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'FOREIGN_CANARY')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'FOREIGN_DEEPSEEK')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'FOREIGN_BOT_CANARY')
    from tools.environments import local
    monkeypatch.setattr(local, '_is_routed_home', lambda _: True)
    assert _start(router, tmp_path)['status'] == 'running'
    env = calls[0][1]['env']
    assert 'ANTHROPIC_API_KEY' not in env
    assert 'TELEGRAM_BOT_TOKEN' not in env
    assert env.get('DEEPSEEK_API_KEY') == ('TARGET_CANARY' if own_key else None)
    assert 'FOREIGN_CANARY' not in env.values()


def test_spawn_preserves_native_runtime_without_foreign_pythonpath(tmp_path, monkeypatch):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    import hermes_bootstrap
    actual_run = subprocess.run
    router, _, _, calls = _make_router(tmp_path, monkeypatch)
    monkeypatch.setenv('PYTHONPATH', 'FOREIGN_PYTHONPATH_CANARY')
    assert _start(router, tmp_path)['status'] == 'running'
    env = calls[0][1]['env']
    assert 'FOREIGN_PYTHONPATH_CANARY' not in env.get('PYTHONPATH', '')
    # Execute a real child before replacing any subprocess entry point. No
    # provider/network/config writes: verifies code origin AND native dependencies.
    monkeypatch.undo()
    source = Path(__file__).resolve().parents[1] / 'model_router/scoped_agent.py'
    program = ('import importlib.util,json; '
        f'spec=importlib.util.spec_from_file_location("scope",{str(source)!r}); '
        'scope=importlib.util.module_from_spec(spec); spec.loader.exec_module(scope); '
        'import yaml; print(json.dumps({"root":str(scope._trusted_core_root()),"yaml":yaml.__file__}))')
    result = actual_run([sys.executable, '-B', '-c', program], env=env,
        cwd=calls[0][1]['cwd'], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['root'] == str(Path(hermes_bootstrap.__file__).resolve().parent)


def test_real_desktop_missing_ui_id_cannot_borrow_global_ui(monkeypatch):
    import gateway.session_context as context
    monkeypatch.setenv('HERMES_UI_SESSION_ID', 'foreign-ui')
    def check():
        tokens = context.set_session_vars(platform='desktop', session_id='parent', session_key='key', profile='claire', ui_session_id='')
        try:
            with pytest.raises(ValueError, match='incomplete desktop'):
                capture_runtime(expected_profile='claire')
        finally:
            context.clear_session_vars(tokens)
    Context().run(check)


def test_missing_context_never_borrows_global_parent(monkeypatch):
    import gateway.session_context as context
    monkeypatch.setattr(context, '_session_context_engaged', True)
    monkeypatch.setenv('HERMES_SESSION_ID', 'parent-A')
    def unbound():
        with pytest.raises(ValueError, match='bound current-session'):
            capture_runtime(expected_profile='claire')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(unbound).result()


def test_real_bound_contexts_are_profile_local_under_concurrency(monkeypatch):
    import gateway.session_context as context
    monkeypatch.setenv('HERMES_SESSION_ID', 'FOREIGN_GLOBAL_PARENT')
    def bound(profile):
        tokens = context.set_session_vars(platform='desktop', session_id='parent-' + profile,
            session_key='key-' + profile, ui_session_id='ui-' + profile, profile=profile)
        try:
            runtime = capture_runtime(expected_profile=profile, registry=SimpleNamespace(adopt_local=lambda *a, **k: None), emit=lambda *a: True)
            assert runtime.parent_session_id == 'parent-' + profile
            with pytest.raises(ValueError, match='profile'):
                capture_runtime(expected_profile='different-profile')
        finally:
            context.clear_session_vars(tokens)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(bound, ['claire', 'wallace']))


@pytest.mark.parametrize('values', [
    {'HERMES_UI_SESSION_ID': 'ui', 'HERMES_SESSION_KEY': 'key'},
    {'HERMES_SESSION_ID': 'parent', 'HERMES_UI_SESSION_ID': 'ui', 'HERMES_SESSION_PROFILE': 'claire'},
    {'HERMES_SESSION_KEY': 'key'},
    {'HERMES_SESSION_PLATFORM': 'desktop', 'HERMES_SESSION_ID': 'parent', 'HERMES_SESSION_KEY': 'key', 'HERMES_SESSION_PROFILE': 'claire'},
])
def test_incomplete_desktop_context_fails_before_spawn(values):
    with pytest.raises(ValueError):
        capture_runtime(get_env=lambda k, d='': values.get(k, d))


@pytest.mark.parametrize('seed', ['true', 'false', 'exception'])
def test_ui_seed_state_is_explicit_after_exactly_one_adoption(tmp_path, monkeypatch, seed):
    router, _, _, calls = _make_router(tmp_path, monkeypatch)
    adopted = []
    class Registry:
        def adopt_local(self, process, **kwargs):
            adopted.append(process)
            return SimpleNamespace(id='proc_adopted')
    def emit(*args):
        if seed == 'exception':
            raise RuntimeError('SECRET_EXCEPTION_CANARY')
        return seed == 'true'
    router.runtime = RouteRuntime('parent', 'key', 'task', Registry(), emit)
    result = _start(router, tmp_path)
    assert len(calls) == len(adopted) == 1
    assert result['status'] == 'running'
    assert result['process_id'] == 'proc_adopted'
    assert 'SECRET_EXCEPTION_CANARY' not in str(result)
    if seed == 'true':
        assert 'tracking_error' not in result
    else:
        assert result['tracking_error'] == 'DesktopSeedUnavailable'
        assert result['ui_seeded'] is False
