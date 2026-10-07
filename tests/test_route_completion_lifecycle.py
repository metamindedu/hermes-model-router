"""Native routed completion lifecycle: real worker artifacts, no model/network.

The runner OS seam is fixture-only; publication/exit/queue/Goal handling use
installed native code. These are not evidence of live Desktop activation.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from uuid import uuid4

import pytest

from model_router.runtime_tracking import RouteRuntime
from model_router import routing


@contextmanager
def native_job(tmp_path, monkeypatch, outcome='success', parent='native-parent', profile='claire', registry=None):
    from gateway.session_context import scoped_current_session_id
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.process_registry import ProcessRegistry
    # Keep atomic artifact names under Win32's path limit; use only the
    # process's configured scratch temp root, never a live profile home.
    fixture_home = tempfile.TemporaryDirectory(prefix='mr-')
    home = (Path(fixture_home.name) / 'profiles' / profile).resolve()
    home.mkdir(parents=True)
    (home / 'config.yaml').write_text('{}', encoding='utf8')
    job_id = str(uuid4())
    directory = home / 'plugin-data/model-router/jobs' / job_id
    directory.mkdir(parents=True)
    release = directory / 'release'
    fake_cli = directory / 'hermes.exe'
    fake_cli.write_bytes(b'never executed')
    snapshot = dict(job_id=job_id, profile=profile, purpose='mechanical', cwd=str(tmp_path.resolve()),
                    timeout_seconds=1, parent_session_id=parent, ui_session_id='ui-'+parent,
                    model_provider_evidence={'fallback_enabled': False})
    (directory / 'snapshot.json').write_text(json.dumps(snapshot), encoding='utf8')
    (directory / 'prompt.txt').write_text('PRIVATE_PROMPT_CANARY', encoding='utf8')
    (directory / 'routing-cache.json').write_text('{}', encoding='utf8')
    # The real worker writes state.json before returning its process exit code.
    # A test runner wait supplies only a synthetic exit/result, not a model GO.
    script = '''
import json, pathlib, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from model_router import job_worker, routing
job = pathlib.Path(sys.argv[2]); outcome = sys.argv[3]
while not (job/'release').exists(): time.sleep(0.01)
job_worker.shutil.which = lambda _: str(job/'hermes.exe')
class Runner:
    pid = 987654
    def wait(self, timeout=None):
        if outcome == 'timeout': raise subprocess.TimeoutExpired('fixture-runner', timeout)
        if outcome != 'missing':
            job_worker._atomic_json(job/'runner-result.json', {'exit_code': 0 if outcome == 'success' else 9})
        return 9 if outcome == 'failure' else 0
    def poll(self): return None
job_worker.subprocess.Popen = lambda *a, **k: Runner()
job_worker._terminate_process_tree = lambda process: True
s = json.loads((job/'snapshot.json').read_text())
code = job_worker.run_job(job_dir=job, runner=routing.RUNNER_PATH, python=sys.executable,
    hermes_exe=job/'hermes.exe', profile=s['profile'], purpose=s['purpose'], cwd=pathlib.Path(s['cwd']), timeout=1)
raise SystemExit(code)
'''
    env = dict(__import__('os').environ, HERMES_HOME=str(home))
    token = set_hermes_home_override(str(home))
    registry, process = registry if registry is not None else ProcessRegistry(), None
    try:
        with scoped_current_session_id(parent):
            with (directory / 'job.log').open('ab') as log:
                process = subprocess.Popen([sys.executable, '-c', script, str(routing.PLUGIN_ROOT), str(directory), outcome],
                    env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)
            runtime = RouteRuntime(parent, parent, parent, registry, lambda *a: True, 'ui-'+parent)
            pid = runtime.track(process, job_id=job_id, purpose='mechanical', cwd=str(tmp_path), profile=profile)
            row = registry.get(pid)
            yield dict(home=home, directory=directory, release=release, job_id=job_id,
                       registry=registry, row=row, process=process, parent=parent)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process is not None:
            row._reader_thread.join(timeout=15)
        from hermes_state_registry import close_all_under
        close_all_under(home)
        reset_hermes_home_override(token)
        fixture_home.cleanup()


def finish(case):
    case['release'].write_text('release', encoding='utf8')
    case['process'].wait(timeout=60)
    case['row']._reader_thread.join(timeout=15)
    assert not case['row']._reader_thread.is_alive()
    return case['registry'].completion_queue.get(timeout=2)


@pytest.mark.parametrize('outcome,status,exit_code', [
    ('success', 'finished', 0), ('failure', 'failed', 9),
    ('timeout', 'failed', 124), ('missing', 'unverified', 0),
])
def test_real_worker_publishes_terminal_state_before_native_wake(tmp_path, monkeypatch, outcome, status, exit_code):
    with native_job(tmp_path, monkeypatch, outcome) as c:
        assert c['registry'].completion_queue.empty()
        assert not (c['directory'] / 'state.json').exists()
        event = finish(c)
        state = json.loads((c['directory'] / 'state.json').read_text())
        assert state['status'] == status
        assert state['finished_at']
        assert event['exit_code'] == exit_code
        assert event['session_key'] == event['owner_task_id'] == c['parent']
        assert c['job_id'] in event['output']
        assert 'PRIVATE_PROMPT_CANARY' not in event['output']
        if outcome in ('success', 'failure'):
            assert json.loads((c['directory'] / 'runner-result.json').read_text())['exit_code'] == (0 if outcome == 'success' else 9)
        else:
            assert not (c['directory'] / 'runner-result.json').exists()
        if outcome == 'timeout':
            assert state['timed_out'] and state['cleanup_verified']
        c['registry']._move_to_finished(c['row'])
        assert c['registry'].completion_queue.empty(), 'duplicate native finish must not produce another wake'


@pytest.mark.parametrize('reader_wins', [False, True])
def test_native_cleanup_cancel_wakes_without_fabricating_unpublished_job_result(tmp_path, monkeypatch, reader_wins):
    with native_job(tmp_path, monkeypatch) as c:
        registry, row, process = c['registry'], c['row'], c['process']
        allow_reader = threading.Event()
        if reader_wins:
            def signal_then_collect(*args):
                process.terminate()
                row._reader_thread.join(timeout=15)
                assert row.exited
                return None
            monkeypatch.setattr(registry, '_signal_kill', signal_then_collect)
        else:
            original_finish = registry._finish_exited
            def finish_after_kill(*args, **kwargs):
                assert allow_reader.wait(timeout=30)
                return original_finish(*args, **kwargs)
            monkeypatch.setattr(registry, '_finish_exited', finish_after_kill)
        try:
            receipt = registry.kill_process(row.id, consume_output=False)
            assert receipt['status'] == receipt['completion_reason'] == 'killed'
            assert row._completion_event.wait(timeout=15)
            event = registry.completion_queue.get(timeout=15)
            # Native notices are snapshots. A reader-win event retains exited;
            # native kill corrects the authoritative row/receipt afterwards.
            assert event['completion_reason'] == ('exited' if reader_wins else 'killed')
            assert row.completion_reason == 'killed'
            record = json.loads((c['home'] / 'logs/process-results' / (row.id+'.json')).read_text())
            assert record['completion_reason'] == 'killed'
            assert not (c['directory'] / 'runner-result.json').exists()
            assert not (c['directory'] / 'state.json').exists()
            from types import SimpleNamespace
            status = routing.Router(service=SimpleNamespace(active_profile='claire', base=c['home'].parent.parent)).status(c['job_id'])
            assert status['status'] != 'completed' and status['route_verified'] is False
            assert c['job_id'] in event['output']
            registry._move_to_finished(row)
            assert registry.completion_queue.empty()
        finally:
            allow_reader.set()
            row._reader_thread.join(timeout=15)


@pytest.mark.parametrize('goal_mode', ['waiting', 'paused', 'budget'])
def test_native_goal_wait_or_pause_is_not_reset_by_completion(tmp_path, monkeypatch, goal_mode):
    from hermes_cli.goals import GoalManager
    import tools.process_registry
    from tui_gateway import server
    from tools.process_registry_notifications import format_process_notification
    with native_job(tmp_path, monkeypatch) as c:
        monkeypatch.setattr(tools.process_registry, 'process_registry', c['registry'])
        goal = GoalManager(c['parent'])
        goal.set('fixture-only Goal', max_turns=1)
        if goal_mode == 'waiting':
            goal.wait_on_session(c['row'].id, 'fixture routed result')
            assert goal.is_waiting()
        else:
            if goal_mode == 'budget':
                goal.state.turns_used = goal.state.max_turns
            goal.pause('budget-exhausted' if goal_mode == 'budget' else 'user-paused')
        before_status, before_used, before_reason = goal.state.status, goal.state.turns_used, goal.state.paused_reason
        event = finish(c)
        if goal_mode == 'waiting':
            assert not goal.is_waiting(), 'real native finished process satisfies the Goal barrier'
            assert goal.state.waiting_on_session is None
        submitted = []
        monkeypatch.setattr(server, '_emit', lambda *a: None)
        monkeypatch.setattr(server, '_background_notifications_off', lambda session: False)
        monkeypatch.setattr(server, '_notif_submit', lambda *a, **kw: submitted.append((a, kw)))
        session = dict(session_key=c['parent'], history_lock=threading.RLock(), running=False, goal_manager=goal)
        server._notif_handle_ready('ui-'+c['parent'], session, [event], set(), c['registry'], format_process_notification, None, owned=True)
        assert len(submitted) == 1
        assert c['job_id'] in submitted[0][0][3]
        assert (goal.state.status, goal.state.turns_used, goal.state.paused_reason) == (before_status, before_used, before_reason)
        assert goal.is_active() == (goal_mode == 'waiting')


def test_simultaneous_profile_owned_jobs_keep_separate_native_event_bindings(tmp_path, monkeypatch):
    # ContextVars/receipt homes are fixed at native adoption; later launches
    # cannot redirect an earlier reader's event or retained result.
    with native_job(tmp_path / 'a', monkeypatch, parent='parent-A', profile='claire') as a:
        with native_job(tmp_path / 'b', monkeypatch, parent='parent-B', profile='wallace', registry=a['registry']) as b:
            a['release'].write_text('release', encoding='utf8')
            b['release'].write_text('release', encoding='utf8')
            for c in (a, b):
                c['process'].wait(timeout=60)
                c['row']._reader_thread.join(timeout=15)
            events = {e['session_id']: e for e in (a['registry'].completion_queue.get(timeout=2), a['registry'].completion_queue.get(timeout=2))}
            assert len(events) == 2 and a['registry'].completion_queue.empty()
            for c in (a, b):
                event = events[c['row'].id]
                assert event['session_key'] == event['owner_task_id'] == c['parent']
                assert c['job_id'] in event['output']
                other = b if c is a else a
                assert other['job_id'] not in event['output']
                record = json.loads((c['home'] / 'logs/process-results' / (c['row'].id+'.json')).read_text())
                assert record['parent_session_id'] == c['parent']
                assert not (other['home'] / 'logs/process-results' / (c['row'].id+'.json')).exists()


def test_same_title_long_activity_jobs_recover_exact_ids_from_native_log(tmp_path, monkeypatch):
    from model_router.background_output import BackgroundOutput
    import time
    with native_job(tmp_path / 'a', monkeypatch) as a:
        with native_job(tmp_path / 'b', monkeypatch, registry=a['registry']) as b:
            assert a['row'].command == b['row'].command
            for c in (a, b):
                attempt_id, child_id = str(uuid4()), str(uuid4())
                attempt = c['directory'] / 'attempts' / attempt_id
                attempt.mkdir(parents=True)
                def write(path, value): path.write_text(json.dumps(value), encoding='utf8')
                request = dict(job_id=c['job_id'], attempt_id=attempt_id, session_id=child_id,
                    profile='claire', parent_session_id=c['parent'], home=str(c['home']),
                    source='subagent', prompt='PRIVATE_REQUEST_CANARY')
                write(attempt/'attempt-request.json', request)
                write(c['directory']/'launch.json', dict(process_id=c['row'].id, worker_pid=c['process'].pid))
                observer = BackgroundOutput(session=c['row'], registry=c['registry'], process=c['process'],
                    home=c['home'], job_id=c['job_id'], profile='claire', parent_session_id=c['parent'],
                    session_key=c['parent'], owner_task_id=c['parent'], ui_session_id='ui-'+c['parent'],
                    emit=lambda *a: True, timeout=60)
                public = {k: request[k] for k in ('job_id', 'attempt_id', 'session_id', 'profile', 'parent_session_id')}
                for i in range(35):
                    public.update(schema=1, activity=f'Public activity {i}: '+('a'*90), updated_at=time.time()*1000+i*0.001)
                    write(attempt/'public-progress.json', public)
                    assert observer.tick()
                assert len(c['row'].output_buffer) > 3000
            a['release'].write_text('release', encoding='utf8')
            b['release'].write_text('release', encoding='utf8')
            for c in (a, b):
                c['process'].wait(timeout=60)
                c['row']._reader_thread.join(timeout=15)
            events = {e['session_id']: e for e in (a['registry'].completion_queue.get(timeout=2), a['registry'].completion_queue.get(timeout=2))}
            for c in (a, b):
                event = events[c['row'].id]
                assert event['output_cut'] > 0 and c['job_id'] not in event['output']
                public_log = c['registry'].read_log(event['session_id'], offset=0, limit=40)['output']
                assert public_log.count(c['job_id']) == 1
                assert (b if c is a else a)['job_id'] not in public_log
                assert 'PRIVATE_REQUEST_CANARY' not in public_log+event['output']
                assert 'PRIVATE_PROMPT_CANARY' not in public_log+event['output']
