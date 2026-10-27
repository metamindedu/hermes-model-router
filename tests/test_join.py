from legacy_router_engine import legacy_start
"""Explicit same-turn joins: no live profiles, models or completion injections."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from model_router import routing
from model_router.runtime_tracking import RouteRuntime
from test_routing import FakeService, _make_router, _load


def make_case(tmp_path, monkeypatch, *, profile='claire'):
    home = tmp_path if profile == 'default' else tmp_path / 'profiles' / profile
    home.mkdir(parents=True, exist_ok=True)
    service = FakeService(tmp_path, profile)
    job_id = str(uuid4())
    directory = home / 'plugin-data/model-router/jobs' / job_id
    directory.mkdir(parents=True)
    row = SimpleNamespace(id='proc_join123', pid=123, started_at=1234.5,
                          parent_session_id='parent-A', session_key='lane-A',
                          task_id='owner-A', owner_task_id='owner-A', notify_on_complete=False,
                          exited=True, exit_code=0, completion_reason='exited')
    calls = []

    consumed = set()
    def wait(process_id, timeout=None):
        calls.append((process_id, timeout))
        raise AssertionError('join must not consume a native result')
    registry = SimpleNamespace(get=lambda process_id: row if process_id == row.id else None,
                               wait=wait, is_completion_consumed=lambda process_id: process_id in consumed)
    runtime = RouteRuntime('parent-A', 'lane-A', 'owner-A', registry, lambda *a: True)
    owner = dict(schema=1, profile=profile, home=str(home.resolve()), parent_session_id='parent-A',
                 session_key='lane-A', owner_task_id='owner-A')
    snapshot = dict(job_id=job_id, profile=profile, parent_session_id='parent-A',
                    completion_mode='join', join_owner=owner, timeout_seconds=5400)
    launch = dict(worker_pid=123, process_id=row.id, process_started_at=1234.5, join_available=True)
    def save():
        (directory / 'snapshot.json').write_text(json.dumps(snapshot), encoding='utf-8')
        (directory / 'launch.json').write_text(json.dumps(launch), encoding='utf-8')
    save()
    router = routing.Router(service, runtime=runtime)
    artifact_status = {'job_id': job_id, 'profile': profile, 'status': 'completed',
                       'route_verified': True, 'answer': 'FIXED_RESULT'}
    monkeypatch.setattr(router, 'status', lambda identity: deepcopy(artifact_status))
    return SimpleNamespace(**locals())


def test_join_collects_readonly_and_is_idempotent(tmp_path, monkeypatch):
    c = make_case(tmp_path, monkeypatch)

    result = c.router.join(c.job_id)
    assert result['join_status'] == 'joined'
    assert result['status'] == 'completed' and result['answer'] == 'FIXED_RESULT'
    assert result['result_collected'] is True and result['native_consumption'] == 'not_requested'
    assert c.calls == []
    assert c.router.join(c.job_id)['join_status'] == 'joined'
    assert c.consumed == set()


@pytest.mark.parametrize('native_status', ['interrupted', 'not_found', 'error'])
def test_join_returns_without_retry_on_native_interruption_or_unavailable(tmp_path, monkeypatch, native_status):
    c = make_case(tmp_path, monkeypatch)

    if native_status == 'interrupted':
        monkeypatch.setattr('model_router.joining._interrupted', lambda:True)
    elif native_status == 'not_found':
        c.registry.get = lambda _:None
    else:
        def broken(_): raise OSError('PRIVATE_ERROR')
        c.registry.get = broken
    c.artifact_status['status'] = 'running'
    result = c.router.join(c.job_id)
    assert result['join_status'] == ('interrupted' if native_status == 'interrupted' else 'unavailable')
    assert c.calls == [] and c.consumed == set()
    assert 'PRIVATE' not in str(result)


@pytest.mark.parametrize('status', ['failed', 'unverified'])
def test_native_exit_is_not_fabricated_route_success(tmp_path, monkeypatch, status):
    c = make_case(tmp_path, monkeypatch)
    c.artifact_status.update(status=status, route_verified=False, answer='')
    result = c.router.join(c.job_id)
    assert result['join_status'] == 'joined' and result['status'] == status
    assert result['route_verified'] is False


@pytest.mark.parametrize('field,value', [('parent_session_id','foreign'), ('session_key','foreign'),
                                        ('owner_task_id','foreign'), ('profile','other'),
                                        ('home','C:/foreign'), ('schema',True)])
def test_foreign_snapshot_owner_never_waits_or_consumes(tmp_path, monkeypatch, field, value):
    c = make_case(tmp_path, monkeypatch)
    c.snapshot['join_owner'][field] = value; c.save()
    with pytest.raises(ValueError): c.router.join(c.job_id)
    assert c.calls == [] and c.consumed == set()


@pytest.mark.parametrize('field,value', [('parent_session_id','foreign'), ('session_key','foreign'),
                                        ('owner_task_id','foreign'), ('task_id','foreign'),
                                        ('pid',456), ('started_at',9876.0), ('notify_on_complete',True)])
def test_foreign_or_promoted_native_process_is_not_consumed(tmp_path, monkeypatch, field, value):
    c = make_case(tmp_path, monkeypatch)
    setattr(c.row, field, value)
    with pytest.raises(ValueError): c.router.join(c.job_id)
    assert c.calls == [] and c.consumed == set()


@pytest.mark.parametrize('mode', ['notify', None])
def test_notify_and_legacy_jobs_are_not_converted(tmp_path, monkeypatch, mode):
    c = make_case(tmp_path, monkeypatch)
    if mode is None: c.snapshot.pop('completion_mode')
    else: c.snapshot['completion_mode'] = mode
    c.save()
    with pytest.raises(ValueError): c.router.join(c.job_id)
    assert c.calls == []


def test_unbound_caller_is_denied_but_disabled_routing_keeps_legacy_join(tmp_path, monkeypatch):
    c = make_case(tmp_path, monkeypatch)
    c.router.runtime = None
    with pytest.raises(ValueError): c.router.join(c.job_id)
    c.router.runtime = c.runtime; c.service.enabled = False
    result = c.router.join(c.job_id)
    assert result['join_status'] == 'joined'
    assert c.calls == []


@pytest.mark.parametrize('bad', [0,-1,True,1.5,float('nan'),float('inf'),'30'])
def test_wait_timeout_is_separate_positive_integer_window(tmp_path, monkeypatch, bad):
    c = make_case(tmp_path, monkeypatch)
    with pytest.raises(ValueError): c.router.join(c.job_id, wait_timeout=bad)
    assert c.calls == []


def test_wait_window_returns_pending_without_changing_job_deadline(tmp_path, monkeypatch):
    c = make_case(tmp_path, monkeypatch)
    c.artifact_status['status'] = 'running'
    c.row.exited = False
    before = (c.directory / 'snapshot.json').read_bytes()
    import model_router.joining as joining
    clock = [0.0]
    monkeypatch.setattr(joining.time, 'monotonic', lambda: clock[0])

    monkeypatch.setattr(joining, '_pause', lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    result = c.router.join(c.job_id, wait_timeout=2)
    assert result['join_status'] == 'pending' and result['status'] == 'running'
    assert c.calls == [] and c.consumed == set()
    assert (c.directory / 'snapshot.json').read_bytes() == before


def test_start_join_mode_remains_nonblocking_and_records_owner(tmp_path, monkeypatch):
    router, service, root, launches = _make_router(tmp_path, monkeypatch)
    row = SimpleNamespace(id='proc_join_start', pid=987654, started_at=1234.5,
                          parent_session_id='parent-A', session_key='lane-A',
                          task_id='owner-A', owner_task_id='owner-A', notify_on_complete=False)
    def no_wait(*a, **k): raise AssertionError('start must not wait')
    adopted = []
    def adopt(process, **kwargs):
        adopted.append(kwargs)
        return row
    registry = SimpleNamespace(adopt_local=adopt, get=lambda identity: row,
                               wait=no_wait, is_completion_consumed=lambda identity: False)
    router.runtime = RouteRuntime('parent-A','lane-A','owner-A',registry,lambda *a:True,ui_session_id='ui-A')
    result = legacy_start(router, 'mechanical','fixture',tmp_path,completion_mode='join')
    assert result['status'] == 'running' and len(launches) == 1
    assert adopted[0]['notify_on_complete'] is False
    assert result['completion_mode'] == 'join' and result['join_available'] is True
    directory = root / 'profiles/claire/plugin-data/model-router/jobs' / result['job_id']
    snapshot = _load(directory / 'snapshot.json')
    assert snapshot['join_owner']['parent_session_id'] == 'parent-A'
    assert snapshot['join_owner']['profile'] == 'claire'
    assert snapshot['join_owner']['home'] == str((root / 'profiles/claire').resolve())
    assert _load(directory / 'launch.json')['process_started_at'] == row.started_at
    # A separate parent operation can run while the routed worker remains running.
    marker = tmp_path / 'parent-independent-work'; marker.write_text('done')
    assert marker.read_text() == 'done'


def test_join_mode_requires_bound_native_runtime_before_spawning(tmp_path, monkeypatch):
    router, service, root, launches = _make_router(tmp_path, monkeypatch)
    with pytest.raises(ValueError): legacy_start(router, 'mechanical','fixture',tmp_path,completion_mode='join')
    assert launches == []
    assert not (root / 'profiles/claire/plugin-data/model-router/jobs').exists()


def test_silent_tracking_failure_never_respawns(tmp_path, monkeypatch):
    router, service, root, launches = _make_router(tmp_path, monkeypatch)
    row = SimpleNamespace(id='proc_join_failure',pid=987654,started_at=1234.5,
                          parent_session_id='parent-A',session_key='lane-A',task_id='owner-A',
                          owner_task_id='owner-A',notify_on_complete=False)
    registry = SimpleNamespace(adopt_local=lambda *a,**k:row,get=lambda identity:row,
                               wait=lambda *a,**k:None,is_completion_consumed=lambda identity:False)
    def emit(*a): raise RuntimeError('PRIVATE_SEED_FAILURE')
    router.runtime = RouteRuntime('parent-A','lane-A','owner-A',registry,emit)
    result = legacy_start(router, 'mechanical','fixture',tmp_path,completion_mode='join')
    assert len(launches) == 1 and result['process_id'] == row.id
    assert result['status'] == 'running' and result['join_available'] is True
    assert 'PRIVATE' not in str(result)
