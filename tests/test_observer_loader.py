"""Actual Hermes loader/hook seam with fake API transport (no provider calls)."""
import json
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from model_router import attempt_observer, scoped_agent
from test_scoped_agent import attempt, _fake_dependencies

_BOOTSTRAP_SPEC = importlib.util.find_spec('hermes_bootstrap')
if _BOOTSTRAP_SPEC is None or _BOOTSTRAP_SPEC.origin is None:
    raise RuntimeError('the active Hermes bootstrap source is unavailable to this test runtime')
CORE = Path(_BOOTSTRAP_SPEC.origin).resolve(strict=True).parent
REPO = Path(__file__).resolve().parents[1]
_CORE_MARKERS = (
    'hermes_bootstrap.py', 'run_agent.py', 'agent/agent_init.py',
    'hermes_cli/runtime_provider.py',
)


def _write_core_markers(root, *, omit=()):
    for relative in _CORE_MARKERS:
        if relative in omit:
            continue
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# fixture marker\n', encoding='utf-8')


def _create_directory_redirect(path, target, *, force_junction=False):
    if not force_junction:
        try:
            path.symlink_to(target, target_is_directory=True)
            return
        except OSError:
            pass
    # Windows directory junctions are available without symlink privileges.
    try:
        result = subprocess.run(
            ['cmd.exe', '/c', 'mklink', '/J', str(path), str(target)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f'directory links are unavailable in this test environment: {exc}')
        return
    if result.returncode != 0:
        pytest.skip(f'directory links are unavailable in this test environment: {result.stderr}')
        return
    is_junction = getattr(path, 'is_junction', None)
    if not force_junction and not path.is_symlink() and not (callable(is_junction) and is_junction()):
        pytest.skip('directory link creation did not produce a symlink or junction')
    if force_junction and (not callable(is_junction) or not is_junction()):
        pytest.skip('junction creation did not produce a directory junction')


def test_trusted_core_root_prefers_served_interpreter_workspace_over_stale_path(tmp_path, monkeypatch):
    runtime = tmp_path / 'install' / 'environments' / 'served'
    served_root = runtime / 'workspace'
    stale_root = tmp_path / 'old-install' / 'workspace'
    prefix = runtime / 'venv'
    executable = tmp_path / 'base-python' / 'python'
    _write_core_markers(served_root)
    _write_core_markers(stale_root)
    prefix.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'base interpreter target')
    monkeypatch.setattr(scoped_agent.sys, 'prefix', str(prefix))
    monkeypatch.setattr(scoped_agent.sys, 'base_prefix', str(executable.parent))
    # A venv executable may resolve to this base interpreter on POSIX.
    monkeypatch.setattr(scoped_agent.sys, 'executable', str(executable))
    monkeypatch.setattr(scoped_agent.sys, 'path', [str(stale_root)])

    assert scoped_agent._trusted_core_root() == served_root.resolve()


@pytest.mark.parametrize('invalid_workspace', ['missing', 'incomplete', 'workspace_symlink', 'marker_symlink'])
def test_trusted_core_root_fails_closed_for_invalid_served_workspace(tmp_path, monkeypatch, invalid_workspace):
    runtime = tmp_path / 'install' / 'environments' / 'served'
    prefix = runtime / 'venv'
    workspace = runtime / 'workspace'
    unrelated = tmp_path / 'unrelated-fake-source'
    _write_core_markers(unrelated)
    prefix.mkdir(parents=True)
    executable = prefix / 'Scripts' / 'python.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fixture interpreter')
    base_prefix = tmp_path / 'base-python'
    base_prefix.mkdir()

    if invalid_workspace == 'incomplete':
        _write_core_markers(workspace, omit=('hermes_cli/runtime_provider.py',))
    elif invalid_workspace == 'workspace_symlink':
        _create_directory_redirect(workspace, unrelated)
    elif invalid_workspace == 'marker_symlink':
        workspace.mkdir(parents=True)
        for relative in _CORE_MARKERS[1:]:
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture marker\n', encoding='utf-8')
        shutil.rmtree(workspace / 'agent')
        _create_directory_redirect(workspace / 'agent', unrelated / 'agent', force_junction=True)
        # Exercise the resolve-based guard used on Python versions before 3.12.
        monkeypatch.setattr(type(workspace), 'is_junction', lambda _path: False, raising=False)

    monkeypatch.setattr(scoped_agent.sys, 'prefix', str(prefix))
    monkeypatch.setattr(scoped_agent.sys, 'base_prefix', str(tmp_path / 'base-python'))
    monkeypatch.setattr(scoped_agent.sys, 'executable', str(executable))
    monkeypatch.setattr(scoped_agent.sys, 'path', [str(unrelated)])

    with pytest.raises(scoped_agent.AttemptError, match='trusted Hermes'):
        scoped_agent._trusted_core_root()


@pytest.mark.parametrize('fallback', ['sys_path', 'find_spec'])
def test_trusted_core_root_rejects_unbound_marker_roots(tmp_path, monkeypatch, fallback):
    unrelated = tmp_path / 'unrelated-fake-source'
    _write_core_markers(unrelated)
    unbound_prefix = tmp_path / 'ordinary-python'
    unbound_prefix.mkdir()
    executable = unbound_prefix / 'python'
    executable.write_bytes(b'ordinary interpreter')
    monkeypatch.setattr(scoped_agent.sys, 'prefix', str(unbound_prefix))
    monkeypatch.setattr(scoped_agent.sys, 'base_prefix', str(unbound_prefix))
    monkeypatch.setattr(scoped_agent.sys, 'executable', str(executable))

    if fallback == 'sys_path':
        monkeypatch.setattr(scoped_agent.sys, 'path', [str(unrelated)])
    else:
        from types import SimpleNamespace
        monkeypatch.setattr(scoped_agent.sys, 'path', [])
        monkeypatch.setattr(
            scoped_agent.importlib.util,
            'find_spec',
            lambda _name: SimpleNamespace(origin=str(unrelated / 'hermes_bootstrap.py')),
        )

    with pytest.raises(scoped_agent.AttemptError, match='trusted Hermes'):
        scoped_agent._trusted_core_root()


@pytest.mark.parametrize('venv_name', ['.venv', 'venv'])
def test_trusted_core_root_accepts_interpreter_owned_legacy_source_venv(tmp_path, monkeypatch, venv_name):
    source = tmp_path / 'legacy-hermes-source'
    prefix = source / venv_name
    base_prefix = tmp_path / 'base-python'
    executable = base_prefix / 'bin' / 'python'
    _write_core_markers(source)
    prefix.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'base interpreter target')
    monkeypatch.setattr(scoped_agent.sys, 'prefix', str(prefix))
    monkeypatch.setattr(scoped_agent.sys, 'base_prefix', str(base_prefix))
    monkeypatch.setattr(scoped_agent.sys, 'executable', str(executable))
    monkeypatch.setattr(scoped_agent.sys, 'path', [])

    assert scoped_agent._trusted_core_root() == source.resolve()


def test_trusted_core_root_rejects_legacy_venv_name_without_interpreter_binding(tmp_path, monkeypatch):
    source = tmp_path / 'legacy-hermes-source'
    prefix = source / '.venv'
    _write_core_markers(source)
    prefix.mkdir(parents=True)
    monkeypatch.setattr(scoped_agent.sys, 'prefix', str(prefix))
    monkeypatch.setattr(scoped_agent.sys, 'base_prefix', str(prefix))
    monkeypatch.setattr(scoped_agent.sys, 'executable', str(prefix / 'python'))
    monkeypatch.setattr(scoped_agent.sys, 'path', [])

    with pytest.raises(scoped_agent.AttemptError, match='trusted Hermes'):
        scoped_agent._trusted_core_root()


@pytest.fixture
def loaded(attempt, monkeypatch):
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS', '1')
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    monkeypatch.setenv('HERMES_PROFILE', attempt['request']['profile'])
    (attempt['home'] / 'config.yaml').write_text('plugins:\n  enabled: [model-router]\n', encoding='utf-8')
    from hermes_cli import plugins
    from hermes_cli.plugins_manifest import parse_manifest_file
    manager = plugins.PluginManager(scope_key=str(attempt['home']))
    manifest = parse_manifest_file(REPO / 'plugin.yaml', REPO, 'user', '')
    assert manifest is not None
    manager._load_plugin(manifest)
    entry = manager._plugins['model-router']
    assert entry.enabled, entry.error
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: manager)
    observer = scoped_agent._resolve_registered_observer(attempt['home'], REPO)
    assert observer is not attempt_observer
    assert observer.__name__.startswith('hermes_plugins.model_router')
    yield manager, observer
    observer.reset_for_tests()
    manager.unload('model-router')


def test_other_profile_hook_cannot_record_this_attempt(attempt, loaded, monkeypatch):
    manager, observer = loaded
    from hermes_cli import plugins
    from hermes_cli.plugins_manifest import parse_manifest_file
    other_home = attempt['base'] / 'foreign'
    other_home.mkdir()
    (other_home / 'config.yaml').write_text('plugins:\n  enabled: [model-router]\n'.replace('\n', '\n'), encoding='utf-8')
    other = plugins.PluginManager(scope_key=str(other_home))
    manifest = parse_manifest_file(REPO / 'plugin.yaml', REPO, 'user', '')
    other._load_plugin(manifest)
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: other)
    foreign_observer = scoped_agent._resolve_registered_observer(other_home, REPO)
    assert foreign_observer is not observer
    monkeypatch.setenv('MODEL_ROUTER_ATTEMPT_REQUEST', str(attempt['request_path']))
    req = attempt['request']
    identity = dict(api_request_id='foreign-test', session_id=req['session_id'],
                    task_id=req['task_id'], provider=req['route']['provider'],
                    model=req['route']['model'], api_mode='chat_completions')
    try:
        other.invoke_hook('pre_api_request', **identity, request={'body': {'model': req['route']['model']}})
        other.invoke_hook('post_api_request', **identity, response_model=req['route']['model'], assistant_tool_call_count=0)
        assert foreign_observer.snapshot()['observed_routes'] == []
        assert observer.snapshot()['observed_routes'] == []
    finally:
        other.unload('model-router')


@pytest.mark.parametrize('outcome', ['success', 'exhausted', 'tool', 'partial'])
def test_actual_loader_and_adapter_share_observer(attempt, loaded, outcome):
    manager, observer = loaded
    request = attempt['request']
    def fake_transport(agent, prompt, task_id):
        identity = dict(api_request_id='fixture-api', session_id=request['session_id'],
                        task_id=task_id, provider=request['route']['provider'],
                        model=request['route']['model'], api_mode='chat_completions')
        manager.invoke_hook('pre_api_request', **identity, request={'body': {'model': request['route']['model']}})
        if outcome == 'exhausted':
            manager.invoke_hook('api_request_error', **identity,
                                error={'type': 'usage_limit_reached', 'code': 'usage_limit_reached', 'message': 'subscription usage limit'},
                                error_type='usage_limit_reached', error_code='usage_limit_reached', status_code=429,
                                reason='billing', retryable=False)
            return {'completed': False, 'failed': True, 'error': {'type': 'usage_limit_reached', 'code': 'usage_limit_reached', 'message': 'subscription usage limit'}, 'final_response': ''}
        if outcome == 'tool':
            agent.kwargs['tool_start_callback']('fake_tool', {})
        if outcome == 'partial':
            agent.kwargs['stream_delta_callback']('partial fixture text')
        manager.invoke_hook('post_api_request', **identity, response_model=request['route']['model'], assistant_tool_call_count=0)
        return {'completed': True, 'failed': False, 'partial': False, 'final_response': 'fixture response'}
    deps, stats = _fake_dependencies(attempt, on_run=fake_transport)
    prepare = deps['prepare_runtime']
    deps['observer'] = observer
    deps['prepare_runtime'] = lambda req: {**prepare(req), 'observer': observer}
    result = scoped_agent.run_attempt(request, dependencies=deps)
    assert result['evidence_complete'] is True
    assert len(result['observed_routes']) == 1
    assert result['closure_complete'] is True
    assert stats['close_calls'] == 1
    assert result['tool_seen'] is (outcome == 'tool')
    assert result['partial_output'] is (outcome == 'partial')
    assert result['exhaustion_confirmed'] is (outcome == 'exhausted')
    assert result['completed'] is (outcome != 'exhausted')
    # The former top-level observer has no events: no accidental global alias.
    assert attempt_observer.snapshot()['observed_routes'] == []


def test_registered_observer_accepts_only_schema2_snapshot_bound_to_job(attempt, loaded, monkeypatch):
    _manager, observer = loaded
    original_parent = "native-parent-A"
    fast_snapshot = {
        "schema": 1,
        "profile": "claire",
        "origin_session_id": "fast-origin-A",
        "parent_session_id": original_parent,
        "mode": "priority",
        "expires_at": None,
    }
    job_dir = attempt["attempt_dir"].parent.parent
    (job_dir / "snapshot.json").write_text(json.dumps({
        "schema": 1,
        "job_id": attempt["request"]["job_id"],
        "profile": "claire",
        "parent_session_id": original_parent,
        "fast_snapshot": fast_snapshot,
    }), encoding="utf-8")
    request = {
        **attempt["request"],
        "schema": 2,
        "parent_session_id": "primary-attempt-session",
        "fast_snapshot": fast_snapshot,
    }
    attempt["request_path"].write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(attempt["home"]))
    monkeypatch.setenv("HERMES_PROFILE", "claire")
    monkeypatch.setenv("MODEL_ROUTER_ATTEMPT_REQUEST", str(attempt["request_path"]))

    assert observer._load_verified_state() is not None
    observer.reset_for_tests()
    forged = {**request, "fast_snapshot": {**fast_snapshot, "mode": "normal"}}
    attempt["request_path"].write_text(json.dumps(forged), encoding="utf-8")
    assert observer._load_verified_state() is None
    observer.reset_for_tests()


def test_registered_observer_keeps_legacy_job_snapshot_without_fast_field(attempt, loaded, monkeypatch):
    _manager, observer = loaded
    job_dir = attempt["attempt_dir"].parent.parent
    (job_dir / "snapshot.json").write_text(json.dumps({
        "schema": 1,
        "job_id": attempt["request"]["job_id"],
        "profile": "claire",
        "parent_session_id": None,
    }), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(attempt["home"]))
    monkeypatch.setenv("HERMES_PROFILE", "claire")
    monkeypatch.setenv("MODEL_ROUTER_ATTEMPT_REQUEST", str(attempt["request_path"]))
    assert observer._load_verified_state() is not None
    observer.reset_for_tests()

    (job_dir / "snapshot.json").write_text("{malformed", encoding="utf-8")
    assert observer._load_verified_state() is None
    observer.reset_for_tests()


def test_registered_observer_rejects_schema1_downgrade_from_fast_job(attempt, loaded, monkeypatch):
    _manager, observer = loaded
    job_dir = attempt["attempt_dir"].parent.parent
    fast_snapshot = {
        "schema": 1,
        "profile": "claire",
        "origin_session_id": "host-parent",
        "parent_session_id": "host-parent",
        "mode": "normal",
        "expires_at": None,
    }
    (job_dir / "snapshot.json").write_text(json.dumps({
        "schema": 1,
        "job_id": attempt["request"]["job_id"],
        "profile": "claire",
        "parent_session_id": "host-parent",
        "fast_snapshot": fast_snapshot,
    }), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(attempt["home"]))
    monkeypatch.setenv("HERMES_PROFILE", "claire")
    monkeypatch.setenv("MODEL_ROUTER_ATTEMPT_REQUEST", str(attempt["request_path"]))
    assert observer._load_verified_state() is None
    observer.reset_for_tests()


def test_registered_observer_rejects_symlinked_legacy_job_snapshot(attempt, loaded, monkeypatch):
    _manager, observer = loaded
    job_dir = attempt["attempt_dir"].parent.parent
    outside = attempt["base"] / "external-job-snapshot.json"
    outside.write_text(
        json.dumps({"schema": 1, "job_id": attempt["request"]["job_id"], "profile": "claire"}),
        encoding="utf-8",
    )
    try:
        (job_dir / "snapshot.json").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable in this test environment: {exc}")
    monkeypatch.setenv("HERMES_HOME", str(attempt["home"]))
    monkeypatch.setenv("HERMES_PROFILE", "claire")
    monkeypatch.setenv("MODEL_ROUTER_ATTEMPT_REQUEST", str(attempt["request_path"]))
    assert observer._load_verified_state() is None
    observer.reset_for_tests()


def test_registered_observer_rejects_foreign_profile_and_wrong_root(attempt, loaded):
    _manager, _observer = loaded
    other = attempt['base'] / 'other'
    other.mkdir()
    with pytest.raises(scoped_agent.AttemptError):
        scoped_agent._resolve_registered_observer(other, REPO)
    with pytest.raises(scoped_agent.AttemptError):
        scoped_agent._resolve_registered_observer(attempt['home'], other)


def test_strict_real_config_valid_snapshot_has_no_recovery(attempt, monkeypatch):
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    monkeypatch.setenv('HERMES_PROFILE', 'default')
    path = attempt['home'] / 'config.yaml'
    path.write_text('agent:\n  max_turns: 7\nsecurity:\n  redact_secrets: true\n', encoding='utf-8')
    effective, config, raw = scoped_agent._strict_profile_config(path)
    assert effective['agent']['max_turns'] == 7
    assert config['agent']['max_turns'] == 7
    assert raw == path.read_bytes()


@pytest.mark.parametrize('legacy_available', [False, True])
def test_real_default_bootstrap_prepares_copied_plugin_without_provider_call(attempt, monkeypatch, legacy_available):
    import importlib.util
    import shutil
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS', '1')
    from hermes_cli import env_loader, runtime_provider, plugins, mcp_startup, profiles
    monkeypatch.setattr(profiles, '_get_default_hermes_home', lambda: attempt['home'])
    import types
    tirith_security = types.ModuleType('tools.tirith_security')
    tirith_security.ensure_installed = lambda **kw: None
    monkeypatch.setitem(sys.modules, 'tools.tirith_security',
                        tirith_security if legacy_available else None)
    destination = attempt['home'] / 'plugins/model-router'
    destination.mkdir(parents=True)
    for name in ('plugin.yaml', '__init__.py'):
        shutil.copy2(REPO / name, destination / name)
    shutil.copytree(REPO / 'model_router', destination / 'model_router', ignore=shutil.ignore_patterns('__pycache__'))
    (attempt['home'] / 'config.yaml').write_text(
        'plugins:\n  enabled: [model-router]\nagent:\n  max_turns: 7\nsecurity:\n  redact_secrets: true\n'.replace('\\n', '\n'), encoding='utf-8')
    # Bootstrap policy/readers/loader remain real. Only external setup edges are
    # replaced so this test cannot refresh auth, install tools or start MCPs.
    calls = []
    monkeypatch.setattr(env_loader, 'load_hermes_dotenv', lambda **kw: calls.append('env') or [])
    monkeypatch.setattr(tirith_security, 'ensure_installed', lambda **kw: calls.append('tirith'))
    monkeypatch.setattr(mcp_startup, 'ensure_mcp_discovery_before_agent_build', lambda **kw: calls.append('mcp'))
    def forbidden_provider(**kw):
        raise AssertionError('No provider resolution is allowed in preparation')
    monkeypatch.setattr(runtime_provider, 'resolve_runtime_provider', forbidden_provider)
    spec = importlib.util.spec_from_file_location('test_real_copied_adapter', destination / 'model_router/scoped_agent.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    request = {**attempt['request'], 'profile': 'default'}
    attempt['request_path'].write_text(json.dumps(request), encoding='utf-8')
    with module._attempt_environment(request, attempt['request_path']):
        prepared = module._default_prepare_runtime(request)
        assert prepared['agent_options']['max_iterations'] == 7
        assert prepared['observer'].__name__.startswith('hermes_plugins.model_router')
        assert Path(prepared['observer'].__file__).resolve().parent.parent == destination.resolve()
        assert prepared['resolve_runtime_provider'] is forbidden_provider
        expected_startup = ['env', 'tirith', 'mcp'] if legacy_available else ['env', 'mcp']
        assert calls[:len(expected_startup)] == expected_startup
        assert all(call == 'env' for call in calls[len(expected_startup):])
        plugins.get_plugin_manager().unload('model-router')


def test_default_prepare_rejects_tampered_bootstrap_spec_origin(tmp_path, monkeypatch):
    import importlib.util
    import types

    trusted_root = tmp_path / 'served' / 'workspace'
    stale_root = tmp_path / 'stale' / 'workspace'
    trusted_bootstrap = trusted_root / 'hermes_bootstrap.py'
    stale_bootstrap = stale_root / 'hermes_bootstrap.py'
    trusted_bootstrap.parent.mkdir(parents=True)
    stale_bootstrap.parent.mkdir(parents=True)
    trusted_bootstrap.write_text('# trusted fixture\n', encoding='utf-8')
    stale_bootstrap.write_text('# stale fixture\n', encoding='utf-8')
    tampered = types.ModuleType('hermes_bootstrap')
    tampered.__file__ = str(trusted_bootstrap)
    tampered.__spec__ = importlib.util.spec_from_file_location('hermes_bootstrap', stale_bootstrap)
    setattr(tampered, 'harden_import_path', lambda _root: pytest.fail('tampered bootstrap must not execute'))
    monkeypatch.setattr(scoped_agent, '_trusted_core_root', lambda: trusted_root)
    monkeypatch.setitem(sys.modules, 'hermes_bootstrap', tampered)

    with pytest.raises(scoped_agent.AttemptError, match='Hermes bootstrap origin changed'):
        scoped_agent._default_prepare_runtime({'profile': 'default'})


def test_child_process_prepares_copied_plugin_read_only_with_served_yaml(attempt):
    destination = attempt['home'] / 'plugins/model-router'
    destination.mkdir(parents=True)
    for name in ('plugin.yaml', '__init__.py'):
        shutil.copy2(REPO / name, destination / name)
    shutil.copytree(REPO / 'model_router', destination / 'model_router', ignore=shutil.ignore_patterns('__pycache__'))
    config_path = attempt['home'] / 'config.yaml'
    config_bytes = (
        'plugins:\n  enabled: [model-router]\n'
        'agent:\n  max_turns: 7\n'
        'security:\n  redact_secrets: true\n'
    ).encode('utf-8')
    config_path.write_bytes(config_bytes)
    request = {**attempt['request'], 'profile': 'default'}
    attempt['request_path'].write_text(json.dumps(request), encoding='utf-8')
    (attempt['cwd'] / 'hermes_bootstrap.py').write_text(
        "raise RuntimeError('untrusted cwd bootstrap was imported')\n", encoding='utf-8'
    )

    program = f'''\
import importlib.util, json, sys
from pathlib import Path
core_root = {str(CORE)!r}
home = Path({str(attempt['home'])!r})
request_path = Path({str(attempt['request_path'])!r})
source = Path({str(destination / 'model_router/scoped_agent.py')!r})
from hermes_cli import env_loader, mcp_startup, plugins, profiles, runtime_provider
env_loader.load_hermes_dotenv = lambda **_kwargs: []
mcp_startup.ensure_mcp_discovery_before_agent_build = lambda **_kwargs: None
runtime_provider.resolve_runtime_provider = lambda **_kwargs: (_ for _ in ()).throw(AssertionError('provider resolution called'))
profiles._get_default_hermes_home = lambda: home
sys.modules['tools.tirith_security'] = None
spec = importlib.util.spec_from_file_location('read_only_child_scope', source)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)
request = json.loads(request_path.read_text(encoding='utf-8'))
prepared = scope._default_prepare_runtime(request)
import hermes_bootstrap, hermes_yaml
parsed = hermes_yaml.safe_load('agent:\\n  max_turns: 7\\n')
assert Path(prepared['core_root']).resolve() == Path(core_root).resolve()
assert Path(hermes_bootstrap.__file__).resolve() == Path(core_root, 'hermes_bootstrap.py').resolve()
assert Path(prepared['observer'].__file__).resolve().parent.parent == source.parents[1].resolve()
assert prepared['resolve_runtime_provider'] is runtime_provider.resolve_runtime_provider
assert parsed == {{'agent': {{'max_turns': 7}}}}
plugins.get_plugin_manager().unload('model-router')
print('PREPARE_RESULT=' + json.dumps({{'root': str(prepared['core_root']), 'yaml': hermes_yaml.__file__, 'config': prepared['config']['agent']['max_turns']}}))
'''
    child_env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'HERMES_MANAGED_DIR'):
        child_env.pop(key, None)
    child_env.update({
        'PYTHONPATH': str(CORE),
        'HERMES_HOME': str(attempt['home']),
        'HERMES_PROFILE': 'default',
        'HERMES_DISABLE_LAZY_INSTALLS': '1',
        'PYTHONUTF8': '1',
    })
    result = subprocess.run(
        [sys.executable, '-B', '-c', program], env=child_env, cwd=attempt['cwd'],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = next(line.removeprefix('PREPARE_RESULT=') for line in result.stdout.splitlines()
                   if line.startswith('PREPARE_RESULT='))
    prepared_result = json.loads(payload)
    assert Path(prepared_result['root']).resolve() == CORE.resolve()
    assert Path(prepared_result['yaml']).resolve() == (CORE / 'hermes_yaml.py').resolve()
    assert prepared_result['config'] == 7
    assert config_path.read_bytes() == config_bytes


@pytest.mark.parametrize('broken', ['security: [', '- invalid-root'])
def test_strict_config_rejects_malformed_managed_policy(attempt, monkeypatch, broken):
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    managed = attempt['base'] / 'managed'
    managed.mkdir()
    (managed / 'config.yaml').write_text(broken, encoding='utf-8')
    monkeypatch.setenv('HERMES_MANAGED_DIR', str(managed))
    path = attempt['home'] / 'config.yaml'
    path.write_text('agent: {max_turns: 7}', encoding='utf-8')
    with pytest.raises(scoped_agent.AttemptError):
        scoped_agent._strict_profile_config(path)
