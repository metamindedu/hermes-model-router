"""Regressions for independent review R1–R5, not native E2E authority proof.

Filesystem/helper are real where used. Caller, native process witness and target
Gateway reuse the explicit unit fixtures; only clocks/scheduling are substituted.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
if os.name != 'nt':
    pytest.skip('real protected transport is Windows/local NTFS only', allow_module_level=True)

from tests.test_profile_jobs import env, args, wait
from tests.test_profile_return_control import controller, invoke, meta, prepare, launch, activate, witness_and_ready
from model_router.return_channel import ReturnChannel
from model_router.profile_return_control import ReturnCoordinator


def test_r1_emitted_command_reaches_helper_through_actual_bash(tmp_path):
    from tools.environments.local import _find_bash
    home = tmp_path / 'empty home'
    home.mkdir()
    command = ReturnCoordinator._command(home, '0' * 32)
    clean = {k:v for k,v in os.environ.items() if k.upper() in {
        'PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','HOME','USERPROFILE','LOCALAPPDATA','APPDATA','TMP','TEMP','TMPDIR'}}
    clean.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', MSYS_NO_PATHCONV='1', MSYS2_ARG_CONV_EXCL='*')
    actual = subprocess.run([_find_bash(), '-c', command], cwd=home, env=clean,
                            capture_output=True, text=True, timeout=15)
    assert actual.returncode == 2 and not actual.stderr
    assert json.loads(actual.stdout)['error'] == 'return_helper_unavailable'
    assert not list(home.iterdir())


@pytest.mark.parametrize('rollback_before_open', [False, True])
def test_r2_prepared_monotonic_wait_cannot_be_extended_by_wall_rollback(controller, monkeypatch, rollback_before_open):
    from model_router import profile_return_helper as helper
    from model_router import profile_return as reader_module
    e, co, _, _ = controller
    co.channel_type = ReturnChannel
    _, prepared, channel = prepare(controller, ready_seconds=10, wait_seconds=30)
    launch(co, prepared)
    co.post(**(meta('list-call', 'api-3') | {'tool_name': 'process_manage', 'args': {'action': 'list'},
        'status': 'ok', 'result': json.dumps({'processes': [controller[2]]})}))
    plan = channel.read('plan')
    start = plan['wait_monotonic_deadline'] - 30
    class Clock:
        wall = time.time() - (3600 if rollback_before_open else 0)
        mono = start
        @classmethod
        def time(cls): return cls.wall
        @classmethod
        def monotonic(cls): return cls.mono
    waits = []
    class Event:
        def is_set(self): return False
        def set(self): pass
        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) == 1:
                accepted = activate(e, prepared)
                assert accepted['return_state'] == 'submitted'
                wait(e, prepared['job']['id'])
                Clock.wall -= 3600
                Clock.mono += .1
            elif len(waits) == 2:
                Clock.mono = start + 31.1
            else:
                raise AssertionError('helper renewed its original wait lease')
            return False
    monkeypatch.setattr(helper, 'time', Clock)
    monkeypatch.setattr(reader_module, 'time', Clock)
    monkeypatch.setattr(helper, 'threading', SimpleNamespace(Event=Event,
        current_thread=threading.current_thread, main_thread=threading.main_thread))
    capsule = json.loads(helper.run(e.home, prepared['return_id']))
    assert capsule['outcome'] == 'unknown' and capsule['reason'] == 'wait_deadline'
    assert len(waits) == 2
    assert sum(method == 'prompt.submit' for method, _ in e.gateway.calls) == 1


@pytest.mark.parametrize('next_action', ['prepare', 'start'])
def test_r3_expired_unlaunched_reservations_release_active_slots(controller, next_action):
    e, co, _, _ = controller
    co.channel_type = ReturnChannel
    old_ids, old_channels = [], []
    for index in range(4):
        _, result, channel = prepare(controller, request_id='unlaunched-' + str(index), ready_seconds=.1, wait_seconds=.2)
        old_ids.append(result['job']['id'])
        old_channels.append(channel)
    time.sleep(.3)
    body = args('new-request') | {'action': next_action}
    if next_action == 'prepare':
        body.update(wait_seconds=2, ready_seconds=1)
    reply = invoke(e, body, meta('new-call'))
    assert 'error' not in reply
    jobs = e.manager.journal.read()['jobs']
    assert all(jobs[jid]['status'] == 'failed' and jobs[jid]['reason_code'] == 'return_expired_before_launch' for jid in old_ids)
    assert all(c._closed for c in old_channels)
    assert all(jobs[jid]['activation_state'] == 'reserved' and jobs[jid]['target_session_id'] is None for jid in old_ids)
    assert len(co.channels) == (1 if next_action == 'prepare' else 0)
    if next_action == 'prepare':
        assert not e.gateway.calls and not e.manager.threads
    else:
        wait(e, reply['job']['id'])
        assert sum(method == 'prompt.submit' for method, _ in e.gateway.calls) == 1


def test_r3_tombstone_cleanup_survives_auxiliary_state_write_failure(controller, monkeypatch):
    e, co, _, _ = controller
    co.channel_type = ReturnChannel
    _, old, channel = prepare(controller, ready_seconds=.1, wait_seconds=.2)
    write = channel.write
    def fail_auxiliary(name, value, **kw):
        if name == 'state' and value.get('phase') == 'invalid':
            raise OSError('injected auxiliary state failure, not journal failure')
        return write(name, value, **kw)
    monkeypatch.setattr(channel, 'write', fail_auxiliary)
    time.sleep(.2)
    _, next_job, _ = prepare(controller, request_id='after-aux-failure', ready_seconds=1, wait_seconds=2)
    assert old['return_id'] not in co.channels and channel._closed
    assert e.manager.journal.read()['jobs'][old['job']['id']]['status'] == 'failed'
    assert next_job['return_state'] == 'issued' and not e.gateway.calls


@pytest.mark.parametrize('hook_name', ['pre', 'post'])
def test_r6_retirement_and_hook_snapshot_share_lifecycle_lock(controller, monkeypatch, hook_name):
    from contextlib import contextmanager
    from contextvars import copy_context
    e, co, _, _ = controller
    co.channel_type = ReturnChannel
    _, old, channel = prepare(controller, ready_seconds=10, wait_seconds=20)
    old_deadline = co.leases[old['return_id']][0]
    monkeypatch.setattr('model_router.profile_return_control.time',
        SimpleNamespace(time=time.time, monotonic=lambda: old_deadline + 1))
    entered, release, retired = threading.Event(), threading.Event(), threading.Event()
    original_lock = channel.lock
    failures = []
    @contextmanager
    def scheduled_lock():
        if threading.current_thread().name == 'r6-hook':
            entered.set()
            assert release.wait(5)
        with original_lock():
            yield
    monkeypatch.setattr(channel, 'lock', scheduled_lock)
    kw = meta('unrelated-terminal') | {'tool_name': 'terminal', 'args': {'command': 'unrelated-inert-command'}}
    if hook_name == 'post':
        kw.update(status='ok', result='{}')
    def hook():
        try:
            getattr(co, hook_name)(**kw)
        except BaseException as exc:
            failures.append(type(exc).__name__)
    def retire():
        try:
            co.retire_expired_unlaunched()
        except BaseException as exc:
            failures.append(type(exc).__name__)
        finally:
            retired.set()
    context = copy_context()
    t = threading.Thread(target=lambda: context.run(hook), name='r6-hook')
    r = threading.Thread(target=retire, name='r6-retire')
    t.start()
    try:
        assert entered.wait(5)
        r.start()
        assert not retired.wait(.05), 'retirement must not close a channel in an active hook'
        assert not channel._closed
    finally:
        release.set()
        t.join(5)
        if r.ident is not None:
            r.join(5)
    assert not t.is_alive() and not r.is_alive() and not failures
    assert retired.is_set() and channel._closed and old['return_id'] not in co.channels
    assert co.healthy and co.available()
    _, new, _ = prepare(controller, request_id='new-after-r6', ready_seconds=10, wait_seconds=20)
    refusal = invoke(e, args('new-after-r6') | {'return_id': new['return_id']}, meta('new-start', 'new-api'))
    assert refusal['error'] == 'return_not_ready' and co.healthy and not e.gateway.calls


def test_r6_real_active_corruption_still_disables_admission(controller):
    e, co, _, _ = controller
    co.channel_type = ReturnChannel
    _, prepared, channel = prepare(controller)
    channel.write('state', {'not': 'a valid active generation'})
    co.pre(**(meta('unrelated-terminal') | {'tool_name': 'terminal', 'args': {'command': 'unrelated-inert-command'}}))
    assert not co.healthy and not co.available()
    assert activate(e, prepared)['error'] == 'return_unavailable' and not e.gateway.calls


def test_r4_manager_close_cannot_finish_before_inflight_prepare_is_disposed(controller):
    e, co, _, _ = controller
    close_done = threading.Event()
    threads, constructed = [], []
    class ScheduledChannel:
        @classmethod
        def create(cls, home, rid):
            def unload():
                e.manager.close()
                close_done.set()
            t = threading.Thread(target=unload)
            threads.append(t)
            t.start()
            assert e.manager.closed.wait(5)
            assert not close_done.wait(.05)
            channel = ReturnChannel.create(home, rid)
            constructed.append(channel)
            return channel
    co.channel_type = ScheduledChannel
    body = args() | {'action': 'prepare', 'wait_seconds': 30, 'ready_seconds': 10}
    reply = invoke(e, body, meta())
    for t in threads:
        t.join(5)
        assert not t.is_alive()
    assert close_done.is_set() and co.closed and e.manager.closed.is_set()
    assert reply['error'] == 'owner_unavailable' and 'return_id' not in reply
    assert constructed and all(c._closed for c in constructed)
    assert not co.channels and not e.gateway.calls and not e.manager.threads


@pytest.mark.parametrize('changed', [
    {'request_id': 'DIFFERENT_REQUEST'}, {'profile': 'different-target'},
    {'goal': 'DIFFERENT_GOAL'}, {'context': 'DIFFERENT_CONTEXT'},
])
def test_r5_submitted_retries_validate_exact_payload_without_replay(controller, changed):
    e, co, _, _ = controller
    _, prepared, channel = prepare(controller)
    launch(co, prepared)
    witness_and_ready(controller, channel)
    assert activate(e, prepared)['return_state'] == 'submitted'
    wait(e, prepared['job']['id'])
    body = args() | {'return_id': prepared['return_id']} | changed
    refused = invoke(e, body, meta('changed-call', 'changed-api'))
    assert refused['error'] == 'request_id_conflict'
    assert activate(e, prepared)['return_state'] == 'submitted'
    assert sum(method == 'prompt.submit' for method, _ in e.gateway.calls) == 1
