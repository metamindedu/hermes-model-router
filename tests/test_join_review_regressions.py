from legacy_router_engine import legacy_start
"""Deterministic review regressions on task-owned native processes and executor."""
from contextlib import contextmanager
from contextvars import copy_context
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from model_router import joining, routing
from model_router.runtime_tracking import RouteRuntime
from test_join import make_case
from test_routing import FakeService, _make_router


@contextmanager
def real_case(tmp_path, monkeypatch):
    from gateway.session_context import scoped_current_session_id
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.process_registry import ProcessRegistry
    home = tmp_path/'h'; home.mkdir()
    token = set_hermes_home_override(home)
    job_id = str(uuid4()); directory = home/'plugin-data/model-router/jobs'/job_id
    directory.mkdir(parents=True); gate = directory/'release'
    registry = ProcessRegistry()
    runtime = RouteRuntime('race-parent','race-lane','race-owner',registry,lambda *a:True)
    owner = joining.owner_binding(runtime,'default',home)
    process = None
    try:
        with scoped_current_session_id('race-parent'):
            process = subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-B','-c',
                'import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile not p.exists(): time.sleep(0.01)',str(gate)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            process_id = runtime.track(process,job_id=job_id,purpose='mechanical',cwd=str(tmp_path),completion_mode='join')
            row = registry.get(process_id)
            snapshot = dict(job_id=job_id,profile='default',parent_session_id='race-parent',
                            completion_mode='join',join_owner=owner,timeout_seconds=5400)
            launch = dict(process_id=process_id,worker_pid=process.pid,process_started_at=row.started_at,join_available=True)
            (directory/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
            (directory/'launch.json').write_text(json.dumps(launch),encoding='utf-8')
            router = routing.Router(FakeService(home,'default'),runtime=runtime)
            artifact = dict(job_id=job_id,status='completed',route_verified=True,answer='FIXTURE_RESULT')
            monkeypatch.setattr(router,'status',lambda identity:dict(artifact))
            def forbidden(*a,**k): raise AssertionError('join must not acknowledge or observe native completion')
            for name in ('wait','poll','read_log'): monkeypatch.setattr(registry,name,forbidden)
            yield SimpleNamespace(**locals())
    finally:
        gate.touch()
        if process:
            process.wait(timeout=10)
            row._reader_thread.join(timeout=10)
        reset_hermes_home_override(token)


@pytest.mark.parametrize('phase',['lookup','active-wait'])
def test_real_handoff_and_exit_cannot_be_consumed_by_old_joiner(tmp_path,monkeypatch,phase):
    with real_case(tmp_path,monkeypatch) as c:
        original_get = c.registry.get
        transferred = False
        def transfer():
            nonlocal transferred
            if transferred: return
            transferred = True
            assert c.registry.transfer_ownership(c.process_id,from_owner='race-owner',to_owner='new-owner',
                       to_task_id='new-owner',to_session_key='new-lane') is c.row
            c.gate.touch(); c.process.wait(timeout=10); c.row._reader_thread.join(timeout=10)
        if phase == 'lookup':
            def during_lookup(identity):
                row = original_get(identity)
                if not transferred: transfer()
                return row
            monkeypatch.setattr(c.registry,'get',during_lookup)
        else:
            monkeypatch.setattr(joining,'_pause',lambda seconds:transfer())
        with pytest.raises(ValueError): c.router.join(c.job_id)
        assert transferred and c.row.exited and c.row.owner_task_id == 'new-owner'
        assert not c.registry.is_completion_consumed(c.process_id)
        assert c.process_id not in c.registry._poll_observed
        assert c.registry.completion_queue.empty()


def test_real_late_native_kill_correction_is_reconciled_after_artifact_read(tmp_path,monkeypatch):
    with real_case(tmp_path,monkeypatch) as c:
        natural, correction = threading.Event(), threading.Event()
        def signal(*a,**k):
            c.gate.touch(); c.process.wait(timeout=10); c.row._reader_thread.join(timeout=10)
            natural.set()
            assert correction.wait(timeout=10)
        monkeypatch.setattr(c.registry,'_signal_kill',signal)
        context = copy_context()
        receipt = []
        killer = threading.Thread(target=lambda:context.run(lambda:receipt.append(
            c.registry.kill_process(c.process_id,consume_output=False))))
        killer.start()
        assert natural.wait(timeout=10)
        assert c.row.exit_code == 0 and c.row.completion_reason == 'exited'
        def artifact(identity):
            correction.set(); killer.join(timeout=10)
            assert not killer.is_alive() and c.row.completion_reason == 'killed'
            return dict(c.artifact)
        monkeypatch.setattr(c.router,'status',artifact)
        try:
            result = c.router.join(c.job_id)
        finally:
            correction.set(); killer.join(timeout=10)
        assert result['join_status'] == 'joined' and result['native_snapshot_changed'] is True
        assert result['status'] == 'unverified' and result['route_verified'] is False
        assert result['native_completion_reason'] == 'killed'
        assert not c.registry.is_completion_consumed(c.process_id)
        assert c.router.join(c.job_id)['status'] == 'unverified'


def test_publication_failure_never_advertises_join_available(tmp_path,monkeypatch):
    router,service,root,launches = _make_router(tmp_path,monkeypatch)
    adopted = []
    row = SimpleNamespace(id='proc_publish',pid=987654,started_at=1234.5,parent_session_id='parent-A',
                          session_key='lane-A',task_id='owner-A',owner_task_id='owner-A',notify_on_complete=False)
    def adopt(*a,**k): adopted.append(k); return row
    registry = SimpleNamespace(adopt_local=adopt,get=lambda identity:row)
    runtime = RouteRuntime('parent-A','lane-A','owner-A',registry,lambda *a:True)
    router.runtime = runtime
    def no_observer(*a,**k): raise AssertionError('observer must not start after failed publication')
    monkeypatch.setattr(RouteRuntime,'observe',no_observer)
    write = routing._write_json
    def fail_publication(path,data,**kwargs):
        if path.name == 'launch.json' and not kwargs.get('exclusive'): raise OSError('fixture sharing violation')
        return write(path,data,**kwargs)
    monkeypatch.setattr(routing,'_write_json',fail_publication)
    result = legacy_start(router, 'mechanical','fixture',tmp_path,completion_mode='join')
    assert len(launches) == len(adopted) == 1 and adopted[0]['notify_on_complete'] is False
    assert result['status'] == 'running' and result['process_id'] == row.id
    assert result['join_available'] is False and result['join_error'] == 'LaunchPublicationFailed'
    with pytest.raises(ValueError): router.join(result['job_id'])


def call(name,args):
    return SimpleNamespace(function=SimpleNamespace(name=name,arguments=json.dumps(args)))


def test_actual_native_planner_never_queues_join_in_concurrent_batch(tmp_path):
    from agent.tool_dispatch_helpers import _plan_tool_batch_segments, _batch_admission
    joins = [call('coding_route',{'action':'join','job_id':str(uuid4())}) for _ in range(9)]
    assert all(_batch_admission(item,tmp_path) is None for item in joins)
    segments = _plan_tool_batch_segments(joins,execution_cwd=tmp_path)
    assert len(segments) == 1 and segments[0][0] == 'sequential' and segments[0][1] == joins
    reads = [call('read_file',{'path':str(tmp_path/'a')}),call('read_file',{'path':str(tmp_path/'b')})]
    mixed = _plan_tool_batch_segments(reads+joins+reads,execution_cwd=tmp_path)
    assert [kind for kind,_ in mixed] == ['parallel','sequential','parallel']
    bridge = call('tool_call',{'calls':[{'name':'coding_route','arguments':{'action':'join','job_id':str(uuid4())}}]})
    assert _batch_admission(bridge,tmp_path) is None


@pytest.mark.parametrize('other_limit',[None,5.0])
def test_actual_native_sequential_executor_returns_pending_before_its_own_deadline(tmp_path,monkeypatch,other_limit):
    from agent import tool_executor as native
    c = make_case(tmp_path,monkeypatch)
    c.row.exited = False
    agent = SimpleNamespace(_tool_worker_threads=set(),_tool_worker_threads_lock=threading.Lock(),
                            _interrupt_requested=False,_touch_activity=lambda *a:None)
    monkeypatch.setattr(native,'_resolve_sequential_tool_timeout',lambda:1.5)
    monkeypatch.setattr(native,'_resolve_concurrent_tool_timeout',lambda:other_limit)
    monkeypatch.setattr(native,'_emit_terminal_post_tool_call',lambda *a,**k:None)
    trace = []
    def middleware(agent,**kwargs):
        trace.append(('worker-enter',time.monotonic(),joining.effective_wait_window(None)))
        value = kwargs['execute'](kwargs.get('function_args',{}))
        trace.append(('worker-return',time.monotonic(),value))
        return native._ManagedToolResult(result=value,args={},middleware_trace=[],blocked=False,dispatched=True)
    monkeypatch.setattr(native,'_run_agent_tool_execution_middleware',middleware)
    # Real join-mode start and native batch planning preflight these helpers
    # before the per-call executor starts its clock. Mirror that supported path.
    joining.effective_wait_window(None)
    # The real start-before-join workflow has already constructed a native
    # tool worker. Initialize that core path outside the deliberately tiny
    # test deadline (cold approval imports otherwise dominate the first call).
    with native._registered_tool_worker(agent):
        pass
    from agent.tool_dispatch_helpers import _batch_admission
    assert _batch_admission(call('coding_route',{'action':'join'}),tmp_path) is None
    started = time.monotonic()
    result = native._run_sequential_tool_execution_middleware(agent,function_name='coding_route',
        function_args={'action':'join','job_id':c.job_id},effective_task_id='owner-A',tool_call_id='join-call',
        execute=lambda args:json.dumps(c.router.join(c.job_id)))
    assert str(result.result).startswith('{'), repr((trace,result.result))
    assert json.loads(result.result)['join_status'] == 'pending'
    assert time.monotonic()-started < 1.5
    assert c.consumed == set() and c.calls == []
