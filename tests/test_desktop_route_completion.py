"""Native Desktop consumer regressions, isolated from the live host/model."""
from contextlib import nullcontext
import subprocess
import sys
import threading
from uuid import uuid4

import pytest

from model_router.runtime_tracking import RouteRuntime, DesktopSeedUnavailable
from test_route_completion_lifecycle import native_job, finish


@pytest.fixture
def consumer(monkeypatch):
    from tui_gateway import server
    from tools.process_registry_notifications import format_process_notification
    submitted, emitted = [], []
    # Only the external model/transport and config I/O seams are stubbed.
    # Ownership, queue, dedup, native turn admission and Stop latch stay real.
    monkeypatch.setattr(server, '_emit', lambda *a: emitted.append(a))
    def submit(*args, **kwargs):
        submitted.append((args, kwargs))
        return True  # Native _notif_submit returns True only when its turn was accepted.
    monkeypatch.setattr(server, '_notif_submit', submit)
    monkeypatch.setattr(server, '_session_profile_runtime_scope', lambda *a, **k: nullcontext())
    monkeypatch.setattr(server, '_load_cfg', lambda: {'display': {'background_process_notifications': 'concise'}})
    monkeypatch.setattr(server, '_sessions', {})
    def session(case, parent=None):
        parent = parent or case['parent']
        s = dict(session_key=parent, profile_home=str(case['home']), history_lock=threading.RLock(), running=False)
        server._sessions['ui-'+parent] = s
        return s
    def handle(case, s, events, seen=None, deferred=None):
        server._notif_handle_ready('ui-'+s['session_key'], s, events, seen if seen is not None else set(),
            case['registry'], format_process_notification, deferred)
    return server, submitted, emitted, session, handle


def test_running_user_turn_and_stop_latch_defer_then_idle_wakes_once(tmp_path, monkeypatch, consumer):
    server, submitted, emitted, make_session, handle = consumer
    with native_job(tmp_path, monkeypatch) as c:
        s, seen = make_session(c), set()
        event = finish(c)
        s['running'] = True
        handle(c, s, [event], seen)
        assert submitted == []
        assert c['registry'].completion_queue.get_nowait() is event
        s['running'], s['_turn_cancel_requested'] = False, True
        handle(c, s, [event], seen)
        assert submitted == []
        assert c['registry'].completion_queue.get_nowait() is event
        s['_turn_cancel_requested'] = False
        handle(c, s, [event], seen)
        assert len(submitted) == 1
        assert c['job_id'] in submitted[0][0][3]
        assert len(emitted) == 1, 'requeue must not repeat visible completion status'
        assert c['registry'].completion_queue.empty()
        assert s['running'] is True


def test_explicit_notifications_off_remains_optout(tmp_path, monkeypatch, consumer):
    server, submitted, emitted, make_session, handle = consumer
    monkeypatch.setattr(server, '_load_cfg', lambda: {'display': {'background_process_notifications': 'off'}})
    with native_job(tmp_path, monkeypatch) as c:
        handle(c, make_session(c), [finish(c)])
        assert submitted == [] and len(emitted) == 1


def test_wrong_live_parent_defers_without_adopting_completion(tmp_path, monkeypatch, consumer):
    server, submitted, emitted, make_session, handle = consumer
    with native_job(tmp_path, monkeypatch) as c:
        correct = make_session(c)
        other = make_session(c, 'parent-foreign')
        event, deferred = finish(c), []
        handle(c, other, [event], deferred=deferred)
        assert submitted == emitted == []
        assert deferred == [event]
        handle(c, correct, deferred)
        assert len(submitted) == 1
        assert submitted[0][0][1] == 'ui-'+c['parent']


def test_manual_native_wait_consumes_completion_without_duplicate_wake(tmp_path, monkeypatch, consumer):
    server, submitted, emitted, make_session, handle = consumer
    with native_job(tmp_path, monkeypatch) as c:
        event = finish(c)
        c['registry'].wait(c['row'].id, timeout=1)
        assert c['registry'].is_completion_consumed(c['row'].id)
        handle(c, make_session(c), [event])
        assert submitted == emitted == []


@pytest.mark.parametrize('emit_fails', [False, True])
@pytest.mark.parametrize('ui_session', ['ui-parent', ''])
def test_already_exited_real_process_is_seeded_before_native_reader(tmp_path, monkeypatch, emit_fails, ui_session):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from gateway.session_context import scoped_current_session_id
    from tools.process_registry import ProcessRegistry
    from tui_gateway.contracts.events import StatusUpdatePayload
    token = set_hermes_home_override(str(tmp_path.resolve()))
    registry = ProcessRegistry()
    job_id, events = str(uuid4()), []
    original = registry._track_started
    def before_reader(row, *a, **k):
        assert row.output_buffer.count(job_id) == 1
        assert 'PRIVATE_STDOUT_CANARY' not in row.output_buffer
        return original(row, *a, **k)
    monkeypatch.setattr(registry, '_track_started', before_reader)
    def emit(name, payload):
        StatusUpdatePayload.model_validate(payload)
        events.append((name, payload))
        if emit_fails: raise RuntimeError('PRIVATE_EMIT_ERROR')
        return True
    try:
        with scoped_current_session_id('parent-fast'):
            with (tmp_path/'private.log').open('wb') as out:
                p = subprocess.Popen([sys.executable, '-c', "print('PRIVATE_STDOUT_CANARY')"],
                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert p.wait(timeout=5) == 0
            runtime = RouteRuntime('parent-fast', 'parent-fast', 'parent-fast', registry, emit, ui_session)
            if emit_fails:
                with pytest.raises(DesktopSeedUnavailable) as failed:
                    runtime.track(p, job_id=job_id, purpose='mechanical', cwd=str(tmp_path))
                row = registry.get(failed.value.process_id)
            else:
                process_id = runtime.track(p, job_id=job_id, purpose='mechanical', cwd=str(tmp_path))
                row = registry.get(process_id)
            row._reader_thread.join(timeout=5)
            assert row.exited and row.output_buffer.count(job_id) == 1
            assert len(events) == 1 and events[0][1] == {'kind': 'process', 'text': ''}
            if ui_session:
                event = registry.completion_queue.get(timeout=2)
                assert event['session_key'] == 'parent-fast' and event['output'].count(job_id) == 1
                assert 'PRIVATE_STDOUT_CANARY' not in event['output']
                assert 'PRIVATE_EMIT_ERROR' not in event['output']
            assert registry.completion_queue.empty()
            assert row.notify_on_complete is bool(ui_session)
    finally:
        reset_hermes_home_override(token)
