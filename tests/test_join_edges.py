from legacy_router_engine import legacy_start
"""Join failure boundaries and native host-call budget compatibility."""
import json
from types import SimpleNamespace

import pytest

from model_router import joining
from test_join import make_case
from test_routing import _make_router


@pytest.mark.parametrize('requested,expected', [(None,4.0),(10000,4.0),(1,1.0)])
def test_join_window_stays_inside_host_deadline_without_changing_it(monkeypatch, requested, expected):
    import agent.tool_executor as native
    monkeypatch.setenv('TERMINAL_TIMEOUT','180')
    monkeypatch.setattr(native,'_resolve_concurrent_tool_timeout',lambda:5.0)
    monkeypatch.setattr(native,'_resolve_sequential_tool_timeout',lambda:20.0)
    assert joining.effective_wait_window(requested) == expected
    assert native._resolve_concurrent_tool_timeout() == 5.0
    assert native._resolve_sequential_tool_timeout() == 20.0


@pytest.mark.parametrize('value', ['0','-1'])
def test_invalid_native_wait_window_is_not_a_busy_loop(monkeypatch, value):
    monkeypatch.setenv('TERMINAL_TIMEOUT',value)
    with pytest.raises(ValueError): joining.effective_wait_window(None)


@pytest.mark.parametrize('code,reason', [(9,'exited'),(-15,'killed'),(None,'unknown'),(False,'exited')])
def test_native_termination_cannot_promote_stale_runner_success(tmp_path, monkeypatch, code, reason):
    c = make_case(tmp_path,monkeypatch)

    c.row.exit_code, c.row.completion_reason = code, reason
    result = c.router.join(c.job_id)
    assert result['join_status'] == 'joined' and result['result_collected'] is True
    assert c.consumed == set()
    assert result['status'] == 'unverified' and result['route_verified'] is False
    assert result['native_exit_code'] == (code if type(code) is int else None)


def test_ownership_change_between_native_wait_slices_stops_before_consumption(tmp_path,monkeypatch):
    c = make_case(tmp_path,monkeypatch)
    c.row.exited = False
    def transferred(seconds):
        c.row.owner_task_id = 'foreign-owner'
        c.row.exited = True
    monkeypatch.setattr(joining,'_pause',transferred)
    with pytest.raises(ValueError): c.router.join(c.job_id)
    assert c.calls == [] and c.consumed == set()


def test_missing_native_tracking_returns_unavailable_without_wait(tmp_path,monkeypatch):
    c = make_case(tmp_path,monkeypatch)
    c.registry.get = lambda identity:None
    result = c.router.join(c.job_id)
    assert result['join_status'] == 'unavailable' and c.calls == []


def test_native_lookup_exception_is_not_forwarded(tmp_path,monkeypatch):
    c = make_case(tmp_path,monkeypatch)
    def broken(*a,**k): raise OSError('PRIVATE_NATIVE_ERROR')
    c.registry.get = broken
    result = c.router.join(c.job_id)
    assert result['join_status'] == 'unavailable' and 'PRIVATE' not in str(result)
    assert c.consumed == set()


@pytest.mark.parametrize('field,value', [('worker_pid',True),('worker_pid',-1),
                                        ('process_started_at',True),('process_started_at',float('nan')),
                                        ('process_id','proc_join'),('process_id','../proc_join123')])
def test_invalid_or_missing_process_incarnation_is_not_joined(tmp_path,monkeypatch,field,value):
    c = make_case(tmp_path,monkeypatch)
    c.launch[field] = value; c.save()
    result = None
    try: result = c.router.join(c.job_id)
    except ValueError: pass
    assert result is None or result['join_status'] == 'unavailable'
    assert c.calls == [] and c.consumed == set()


def test_corrupt_and_oversized_ownership_records_fail_closed(tmp_path,monkeypatch):
    c = make_case(tmp_path,monkeypatch)
    path = c.directory/'snapshot.json'
    for raw in ('[]','{', 'x'*262145):
        path.write_text(raw,encoding='utf-8')
        with pytest.raises(ValueError): c.router.join(c.job_id)
    assert c.calls == []


@pytest.mark.parametrize('mode', [None,True,'wait','JOIN'])
def test_bad_start_mode_is_rejected_before_launch(tmp_path,monkeypatch,mode):
    router,_,_,launches = _make_router(tmp_path,monkeypatch)
    with pytest.raises(ValueError): legacy_start(router, 'mechanical','fixture',tmp_path,completion_mode=mode)
    assert launches == []
