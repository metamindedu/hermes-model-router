"""Real native CLI discovery/parser/writer in scrubbed fake profile homes.

No Gateway, target session, model, credential lookup or network request is needed.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture(params=['default', 'origin'])
def cli_env(tmp_path, request):
    import hermes_cli
    source = Path(__file__).resolve().parents[1]
    user = tmp_path / 'os-home'
    local = user / 'AppData/Local'
    root = local / 'hermes'
    origin = request.param
    home = root if origin == 'default' else root / 'profiles' / origin
    home.mkdir(parents=True)
    package = home / 'plugins/model-router'
    shutil.copytree(source, package, ignore=shutil.ignore_patterns('.git', 'tests', '__pycache__', '.hermes-catalog.json'))
    cfg = {'plugins': {'enabled': ['model-router']}, 'model': {'provider': 'openrouter', 'default': 'offline-fixture'},
           'agent': {'reasoning_effort': 'medium'}, 'operator_fixture_unrelated': {'keep': True}}
    (home / 'config.yaml').write_text(json.dumps(cfg), encoding='utf-8')
    if origin != 'default':
        (root / 'config.yaml').write_text('{"operator_fixture_root_preserved":true}', encoding='utf-8')
    worker = root / 'profiles/worker'; worker.mkdir(parents=True)
    cwd = tmp_path / 'worker-cwd'; cwd.mkdir()
    worker_config = worker / 'config.yaml'
    worker_config.write_text(json.dumps({'terminal': {'cwd': str(cwd)}, 'model': {'default': 'offline-target'}}), encoding='utf-8')

    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS', 'SYSTEMDRIVE', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'COMMONPROGRAMFILES', 'COMMONPROGRAMFILES(X86)', 'ALLUSERSPROFILE', 'PROGRAMDATA'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    temporary = tmp_path / 'temp'; temporary.mkdir()
    for key, value in {'HOME': user, 'USERPROFILE': user, 'LOCALAPPDATA': local, 'APPDATA': user / 'AppData/Roaming',
                       'HERMES_HOME': root, 'TMPDIR': temporary, 'TEMP': temporary, 'TMP': temporary}.items():
        Path(value).mkdir(parents=True, exist_ok=True); env[key] = str(value)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', HERMES_DISABLE_LAZY_INSTALLS='1')
    core = Path(hermes_cli.__file__).resolve().parent.parent
    assert core != source and (core / 'hermes_cli/main.py').is_file()
    def run(operation, body, *, stdin=False, expected=0, profile=None):
        before_worker = worker_config.read_bytes()
        argv = [sys.executable, '-B', '-m', 'hermes_cli.main', '--profile', profile or origin,
                'model-router', operation, '--body', '-' if stdin else json.dumps(body, separators=(',', ':'))]
        result = subprocess.run(argv, input=json.dumps(body) if stdin else None, env=env, cwd=core,
                                capture_output=True, text=True, encoding='utf-8', errors='strict', timeout=60,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        frames = [line.split(':', 1)[1] for line in result.stdout.splitlines() if line.startswith('MODEL_ROUTER_JSON:')]
        assert len(frames) == 1, (result.returncode, result.stdout[-1500:], result.stderr[-1500:])
        data = json.loads(frames[0])
        if expected is not None:
            assert result.returncode == expected, data
        assert data['origin_profile'] == origin
        assert worker_config.read_bytes() == before_worker
        assert not (home / 'plugin-data/model-router/full-profile-jobs.json').exists()
        assert not (worker / 'state.db').exists()
        return data, result.returncode
    return run, home, cfg, worker_config


def payload(status, enabled=True, targets=None):
    return {'expected_operator_revision': status['operator_revision'], 'enabled': enabled,
            'targets': [x['profile'] for x in status['review_targets']] if targets is None else targets,
            'acknowledge_scope': True}


def without_grant(value):
    value = copy.deepcopy(value)
    plugins = value['plugins']
    entries = plugins.get('entries', {})
    entry = entries.get('model-router', {})
    settings = entry.get('settings', {})
    settings.pop('profile_jobs', None)
    if not settings: entry.pop('settings', None)
    if not entry: entries.pop('model-router', None)
    if not entries: plugins.pop('entries', None)
    return value


def test_real_native_cli_three_process_flow_and_noop(cli_env):
    from model_router.yaml_compat import yaml
    run, home, original, _ = cli_env
    before = (home / 'config.yaml').read_bytes()
    status, _ = run('profile-jobs-status', {'targets': ['worker']}, stdin=True)
    assert status['policy']['enabled'] is False and status['policy']['targets'] == []
    assert (home / 'config.yaml').read_bytes() == before
    saved, _ = run('profile-jobs-configure', payload(status), stdin=True)
    assert saved['status'] == 'saved' and saved['policy']['revision'] == 1
    readback, _ = run('profile-jobs-status', {'targets': ['worker']})
    assert readback['policy'] == saved['policy'] and readback['operator_revision'] == saved['operator_revision']
    config = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8'))
    assert without_grant(config) == original
    noop, _ = run('profile-jobs-configure', payload(readback))
    assert noop['status'] == 'noop' and noop['no_effect'] is True
    assert noop['policy']['revision'] == 1


def test_real_native_cli_competing_processes_and_revocation(cli_env):
    run, _, _, _ = cli_env
    status, _ = run('profile-jobs-status', {'targets': ['worker']})
    def save(_): return run('profile-jobs-configure', payload(status), expected=None)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(save, range(2)))
    assert sorted(code for _, code in results) == [0, 2]
    assert sorted(data['status'] for data, _ in results) == ['refused', 'saved']
    refusal = next(data for data, code in results if code)
    assert refusal['error'] == 'revision_conflict' and refusal['no_effect'] is True
    off, _ = run('profile-jobs-status', {'targets': []})
    saved, _ = run('profile-jobs-configure', payload(off, enabled=False))
    assert saved['policy']['enabled'] is False and saved['policy']['targets'] == []
    stale, _ = run('profile-jobs-configure', payload(status), expected=2)
    assert stale['error'] == 'revision_conflict'


def test_real_native_cli_target_cwd_change_and_extra_authority_refuse(cli_env):
    run, _, _, worker_config = cli_env
    status, _ = run('profile-jobs-status', {'targets': ['worker']})
    for extra in [{'human': True}, {'operator': True}, {'session_id': 'other'}, {'home': '/other'}, {'profile': 'worker'}]:
        result, _ = run('profile-jobs-configure', {**payload(status), **extra}, expected=2)
        assert result['no_effect'] is True and result['error'] == 'invalid_params'
    changed = worker_config.parent / 'changed-cwd'; changed.mkdir()
    cfg = json.loads(worker_config.read_text(encoding='utf-8'))
    cfg['terminal']['cwd'] = str(changed)
    worker_config.write_text(json.dumps(cfg), encoding='utf-8')
    result, _ = run('profile-jobs-configure', payload(status), expected=2)
    assert result['no_effect'] is True and result['error'] == 'revision_conflict'
