"""Real protected FS/helper + actual journal/controller integration.

Caller/middleware/process witness and target Gateway are explicitly synthetic
unit fixtures. This does NOT prove normal parent admission or native delivery.
No provider, real target profile or production state is used.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
if os.name != 'nt':
    pytest.skip('initial protected helper is Windows/local NTFS only', allow_module_level=True)

from tests.test_profile_jobs import env, wait
from tests.test_profile_return_control import controller, meta, prepare, activate
from model_router.return_channel import ReturnChannel
from model_router.profile_return_control import ReturnCoordinator


def launch(controller, *, ready_seconds=10, wait_seconds=25, witness=True):
    e, co, row, _ = controller
    co.channel_type = ReturnChannel
    co.command_factory = ReturnCoordinator._command
    _, prepared, _ = prepare(controller, ready_seconds=ready_seconds, wait_seconds=wait_seconds)
    rid = prepared['return_id']
    term = prepared['terminal']
    kw = meta('launch-call', 'api-2') | {'tool_name': 'terminal', 'args': term}
    co.pre(**kw)
    helper = Path(__file__).resolve().parents[1] / 'model_router' / 'profile_return_helper.py'
    clean = {k:v for k,v in os.environ.items() if k.upper() in {
        'PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','HOME','USERPROFILE','LOCALAPPDATA','APPDATA','TMP','TEMP','TMPDIR'}}
    clean.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    from tools.environments.local import _find_bash
    clean.update(MSYS_NO_PATHCONV='1', MSYS2_ARG_CONV_EXCL='*')
    # Exercise the ACTUAL emitted command through the native Bash contract,
    # rather than reconstructing a hand-built argv that conceals shell defects.
    p = subprocess.Popen([_find_bash(), '-c', term['command']],
        cwd=e.home, env=clean, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    co.post(**(kw | {'status': 'ok', 'result': json.dumps({'session_id': row['session_id'], 'notify_on_complete': True})}))
    if witness:
        co.post(**(meta('list-call', 'api-3') | {'tool_name': 'process_manage', 'args': {'action': 'list'},
                    'status': 'ok', 'result': json.dumps({'processes': [row]})}))
    return prepared, co.channels[rid], p


def finish(p, timeout=15):
    try:
        out, err = p.communicate(timeout=timeout)
        assert not err, 'helper stderr must remain empty (contents not printed)'
        assert p.returncode == 0, 'helper did not complete normally'
        return json.loads(out)
    finally:
        if p.poll() is None:
            p.terminate()
            p.communicate(timeout=15)


def ready(channel, p):
    until = time.monotonic() + 8
    while time.monotonic() < until:
        candidate = channel.read('ready')
        if candidate is not None:
            verified = channel.verify_ready(channel.read('challenge'), candidate)
            assert verified, 'private ready proof rejected'
            return
        assert p.poll() is None, 'helper exited before private readiness'
        time.sleep(.03)
    raise AssertionError('private ready proof missing (no secret dump)')


def test_real_helper_capsule_matches_actual_source_job_and_result(controller):
    e, co, _, _ = controller
    prepared, channel, p = launch(controller)
    try:
        assert not e.gateway.calls, 'readiness must not submit target work'
        ready(channel, p)
        reply = activate(e, prepared)
        assert 'job' in reply and reply.get('status') != 'refused'
        job = wait(e, prepared['job']['id'])
        e.gateway.finish(job['target_session_id'], 'PRIVATE_RESULT_NOT_IN_CAPSULE')
        capsule = finish(p)
        assert capsule['kind'] == 'model_router.profile_completion'
        assert capsule['job_id'] == job['id'] and capsule['outcome'] == 'completed'
        assert capsule['result_available'] is True
        assert 'PRIVATE_RESULT_NOT_IN_CAPSULE' not in json.dumps(capsule)
        result = e.manager.tool({'action': 'result', 'job_id': job['id']}, session_id='parent', conversation_id='parent')
        assert 'PRIVATE_RESULT_NOT_IN_CAPSULE' in result
        assert sum(method == 'session.create' for method, _ in e.gateway.calls) == 1
        assert sum(method == 'prompt.submit' for method, _ in e.gateway.calls) == 1
    finally:
        if p.poll() is None:
            channel.write('stop', {'schema': 1, 'return_id': prepared['return_id'], 'reason': 'activation_unknown'}, exclusive=True)
            p.communicate(timeout=15)


def test_no_challenge_times_out_without_target_work(controller):
    e, co, _, _ = controller
    prepared, channel, p = launch(controller, ready_seconds=.8, wait_seconds=3, witness=False)
    capsule = finish(p)
    assert capsule['outcome'] == 'unknown' and capsule['reason'] == 'wait_deadline'
    assert capsule['result_available'] is False and not e.gateway.calls
    assert channel.read('ready') is None
    assert e.manager.journal.read()['jobs'][prepared['job']['id']]['activation_state'] == 'reserved'


def test_stop_does_not_cancel_or_start_target(controller):
    e, co, _, _ = controller
    prepared, channel, p = launch(controller)
    ready(channel, p)
    channel.write('stop', {'schema': 1, 'return_id': prepared['return_id'], 'reason': 'activation_unknown'}, exclusive=True)
    capsule = finish(p)
    assert capsule['outcome'] == 'unknown' and capsule['reason'] == 'helper_cancelled'
    assert not e.gateway.calls
    assert e.manager.journal.read()['jobs'][prepared['job']['id']]['status'] == 'preparing'


def test_missing_generation_closed_nonsecret_error(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    helper = Path(__file__).resolve().parents[1] / 'model_router' / 'profile_return_helper.py'
    result = subprocess.run([sys.executable, '-B', str(helper), '--home', str(home), '--return-id', '0' * 32],
        cwd=home, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and not result.stderr
    data = json.loads(result.stdout)
    assert data == {'kind': 'model_router.profile_return_refused', 'schema': 1, 'error': 'return_helper_unavailable'}
    assert not list(home.rglob('*'))
