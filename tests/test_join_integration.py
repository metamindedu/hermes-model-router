"""Native plugin dispatch + real Popen/registry wait, fixed-output runner seam.

No model requests or live session state. This proves same-turn result collection,
not Desktop activation or detached automatic continuation.
"""
from contextvars import Context
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
import hermes_bootstrap
from test_routing import FakeService
from legacy_router_engine import legacy_start


@pytest.mark.parametrize('profile', ['default', 'claire'])
@pytest.mark.parametrize('outcome', ['result', 'failure', 'missing', 'interrupted', 'steer', 'stop-during-wait'])
def test_real_start_parent_parallel_work_then_join(tmp_path, monkeypatch, profile, outcome):
    from gateway import session_context
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.registry import ToolRegistry
    from tools.process_registry import ProcessRegistry
    import tools.process_registry as native_module
    import tools.interrupt
    import tools.desktop_ui
    import hermes_cli.venv_sync

    root = tmp_path / 'home'
    home = root if profile == 'default' else root / 'profiles' / profile
    home.mkdir(parents=True)
    (home / 'config.yaml').write_text('{}', encoding='utf-8')
    fake_cli = tmp_path / 'hermes.exe'; fake_cli.write_bytes(b'not executed')
    package_root = Path(__file__).resolve().parents[1]
    name = 'join_native_fixture_' + profile
    spec = importlib.util.spec_from_file_location(name, package_root / '__init__.py',
                                                 submodule_search_locations=[str(package_root)])
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, plugin)
    spec.loader.exec_module(plugin)
    service_module = importlib.import_module(name + '.model_router.service')
    routing = importlib.import_module(name + '.model_router.routing')
    monkeypatch.setattr(service_module, 'Service', lambda: FakeService(root, profile))
    monkeypatch.setattr(hermes_cli.venv_sync, 'prepare_launch', lambda *a,**k:None)
    monkeypatch.setattr(routing.shutil, 'which', lambda _:str(fake_cli))
    monkeypatch.setattr(tools.desktop_ui, '_emit', None)
    native = ProcessRegistry()
    monkeypatch.setattr(native_module, 'process_registry', native)
    actual_popen = subprocess.Popen
    processes, directories = [], []
    script = '''
import json,pathlib,sys,time
job=pathlib.Path(sys.argv[1]); outcome=sys.argv[2]
while not (job/'release').exists(): time.sleep(0.01)
code=9 if outcome=='failure' else 0
if outcome!='missing':
    (job/'runner-result.json').write_text(json.dumps({'exit_code':code,'process_exit_code':code,
        'final_response':'FIXED_JOIN_RESULT'}),encoding='utf-8')
(job/'state.json').write_text(json.dumps({'status':'failed' if code else 'finished'}),encoding='utf-8')
raise SystemExit(code)
'''
    def spawn(command, **kwargs):
        directory = Path(command[command.index('--job-dir') + 1]); directories.append(directory)
        process = actual_popen([getattr(sys,'_base_executable',sys.executable),'-B','-c',script,
                                str(directory),outcome], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(routing.subprocess, 'Popen', spawn)
    registry = ToolRegistry()
    ctx = SimpleNamespace(register_cli_command=lambda *a:None, register_skill=lambda *a:None,
                          register_delegation_provider=lambda *a:None, register_hook=lambda *a:None, register_tool=lambda **kw:registry.register(**kw))
    def turn():
        token = set_hermes_home_override(home)
        tokens = session_context.set_session_vars(platform='local' if profile=='default' else 'telegram',
                    session_id='parent-fixture', session_key='fixture-lane',
                    profile='' if profile=='default' else profile)
        try:
            plugin.register(ctx)
            def call(args, **kwargs):
                if args.get('action') == 'start':
                    # Historical fixture creation is not a production API.
                    runtime_module = importlib.import_module(name + '.model_router.runtime_tracking')
                    with runtime_module.route_session_context(session_id='parent-fixture', expected_profile=profile):
                        runtime = runtime_module.capture_runtime(task_id='fixture-owner', expected_profile=profile)
                        router = routing.Router(FakeService(root, profile), runtime=runtime)
                        return legacy_start(router, args['purpose'], args['prompt'], args['cwd'],
                                            args.get('timeout'), completion_mode=args.get('completion_mode', 'notify'))
                return json.loads(registry.dispatch('coding_route', args, task_id='fixture-owner',
                                                    session_id=kwargs.get('session_id','parent-fixture')))
            args = dict(action='start',purpose='mechanical',prompt='fixed fixture only',cwd=str(tmp_path),
                        completion_mode='join',timeout=5400)
            first, second = call(args), call(args)
            assert first['status'] == second['status'] == 'running'
            assert len(processes) == 2 and all(p.poll() is None for p in processes)
            assert first['join_available'] and second['join_available']
            assert native.completion_queue.empty() and native.pending_watchers == []
            rows = [native.get(item['process_id']) for item in (first,second)]
            assert all(row.notify_on_complete is False for row in rows)
            # This work is performed by the PARENT only after BOTH dispatches returned.
            marker = tmp_path / 'parent-independent-work'
            marker.write_text('PARENT_PARALLEL_WORK_DONE',encoding='utf-8')
            assert all(p.poll() is None for p in processes)
            snapshots = [(p/'snapshot.json').read_bytes() for p in directories]
            denied = call(dict(action='join',job_id=first['job_id']),session_id='foreign-parent')
            assert denied['error'] == 'invalid_or_denied'
            assert not any(native.is_completion_consumed(row.id) for row in rows)
            if outcome == 'interrupted':
                with monkeypatch.context() as stop:
                    stop.setattr(tools.interrupt,'is_interrupted',lambda:True)
                    paused = call(dict(action='join',job_id=first['job_id']))
                assert paused['join_status'] == 'interrupted'
                assert all(p.poll() is None for p in processes)
                assert not native.is_completion_consumed(first['process_id'])
            if outcome in {'steer','stop-during-wait'}:
                tid = threading.current_thread().ident
                def interrupt_wait():
                    if outcome == 'steer': tools.interrupt.request_yield(tid)
                    else: tools.interrupt.set_interrupt(True,thread_id=tid)
                alarm = threading.Timer(0.1,interrupt_wait)
                alarm.start()
                try:
                    paused = call(dict(action='join',job_id=first['job_id']))
                finally:
                    alarm.join(timeout=10)
                    tools.interrupt.set_interrupt(False,thread_id=tid)
                assert paused['join_status'] == 'interrupted'
                assert all(p.poll() is None for p in processes)
                assert not native.is_completion_consumed(first['process_id'])
            # Already-finished and still-running join cases share the same identity.
            (directories[1]/'release').touch()
            processes[1].wait(timeout=10)
            release = threading.Timer(0.1, lambda:(directories[0]/'release').touch())
            release.start()
            try:
                one = call(dict(action='join',job_id=first['job_id']))
            finally:
                release.join(timeout=10)
            two = call(dict(action='join',job_id=second['job_id']))
            for item in (one,two):
                assert item['join_status'] == 'joined' and item['result_collected'] is True
                assert item['native_consumption'] == 'not_requested'
                # Fixture did NOT call a provider or produce model-identity evidence.
                assert item['route_verified'] is False
                assert item['status'] == ('failed' if outcome=='failure' else 'unverified')
                if outcome != 'missing': assert item['answer'] == 'FIXED_JOIN_RESULT'
            again = call(dict(action='join',job_id=first['job_id']))
            assert again['join_status'] == 'joined'
            assert len(processes) == 2 and native.completion_queue.empty() and native.pending_watchers == []
            assert all(not native.is_completion_consumed(row.id) for row in rows)
            assert all(row.id not in native._poll_observed for row in rows)
            assert [(p/'snapshot.json').read_bytes() for p in directories] == snapshots
            assert marker.read_text(encoding='utf-8') == 'PARENT_PARALLEL_WORK_DONE'
        finally:
            for directory in directories: (directory/'release').touch()
            for process in processes:
                if process.poll() is None: process.terminate()
                process.wait(timeout=10)
            for row in native.list_sessions():
                record = native.get(row['session_id'])
                if record and record._reader_thread: record._reader_thread.join(timeout=10)
            session_context.clear_session_vars(tokens)
            reset_hermes_home_override(token)
    Context().run(turn)
