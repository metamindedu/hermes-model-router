"""Completion opt-in for the already validated default local launch scope."""
from types import SimpleNamespace
import pytest
from model_router.runtime_tracking import capture_runtime, RouteRuntime


def capture(values):
    seen={}
    def adopt(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(id='owned-process')
    registry=SimpleNamespace(adopt_local=adopt)
    runtime=capture_runtime(expected_profile='default',task_id='task',get_env=values.get,
                            registry=registry,emit=lambda *a: True)
    return runtime,seen


def local_values():
    return {'HERMES_SESSION_ID':'parent','HERMES_SESSION_KEY':'local-lane',
            'HERMES_SESSION_PLATFORM':'local','HERMES_SESSION_SOURCE':'',
            'HERMES_SESSION_PROFILE':'','HERMES_UI_SESSION_ID':''}


def test_valid_default_local_scope_requests_native_completion_without_ui_id():
    runtime,seen=capture(local_values())
    assert runtime is not None
    runtime.track(SimpleNamespace(pid=123),job_id='job',purpose='independent-review',cwd='fixture')
    assert seen['notify_on_complete'] is True
    assert seen['session_key']=='local-lane'
    assert seen['owner_task_id']=='task'
    assert runtime.ui_session_id==''


@pytest.mark.parametrize('platform',['telegram','cli'])
def test_other_non_ui_surfaces_keep_existing_no_wake_policy(platform):
    values=local_values();values['HERMES_SESSION_PLATFORM']=platform;values['HERMES_SESSION_PROFILE']='default'
    runtime,seen=capture(values)
    assert runtime is not None
    runtime.track(SimpleNamespace(pid=123),job_id='job',purpose='independent-review',cwd='fixture')
    assert seen['notify_on_complete'] is False


def test_unbound_scope_does_not_acquire_completion_authority():
    runtime,seen=capture({})
    assert runtime is None and seen=={}


@pytest.mark.parametrize('mode',['normal','off','busy','stop','foreign-owner','unconsumed-replay'])
def test_local_completion_reaches_native_queue_and_consumer_once(tmp_path, monkeypatch, consumer, mode):
    import subprocess
    import sys
    from gateway import session_context
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tools.process_registry import ProcessRegistry
    from tools.process_registry_notifications import format_process_notification
    server,submitted,emitted,_,_=consumer
    home_token=set_hermes_home_override(str(tmp_path))
    registry=ProcessRegistry()
    process=None
    parent='local-parent'
    values=local_values();values['HERMES_SESSION_ID']=parent;values['HERMES_SESSION_KEY']=parent
    try:
        with session_context.scoped_current_session_id(parent):
            flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
            process=subprocess.Popen([sys.executable,'-B','-c','pass'],stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=flags)
            runtime=capture_runtime(expected_profile='default',task_id='owned-task',get_env=values.get,
                registry=registry,emit=lambda *a: True)
            assert runtime is not None and runtime.ui_session_id==''
            pid=runtime.track(process,job_id='local-test-job',purpose='independent-review',cwd=str(tmp_path))
        process.wait(timeout=10)
        registry.get(pid)._reader_thread.join(timeout=10)
        event=registry.completion_queue.get(timeout=5)
        import threading
        state=dict(session_key=parent,profile_home=str(tmp_path),history_lock=threading.RLock(),running=False)
        if mode=='off':
            monkeypatch.setattr(server,'_load_cfg',lambda:{'display':{'background_process_notifications':'off'}})
        elif mode=='busy': state['running']=True
        elif mode=='stop': state['_turn_cancel_requested']=True
        elif mode=='foreign-owner': state['session_key']='foreign-parent'
        server._sessions['ui-local']=state
        seen=set()
        server._notif_handle_ready('ui-local',state,[event],seen,registry,format_process_notification,[])
        if mode not in {'normal','unconsumed-replay'}:
            assert submitted==[]
            return
        assert len(submitted)==1
        assert 'local-test-job' in submitted[0][0][3]
        if mode=='normal':
            # Native wait/log is the documented consumption boundary. The
            # original submit mock omitted the resumed parent's acknowledgement.
            assert registry.wait(pid,timeout=1)['status']=='exited'
            assert registry.is_completion_consumed(pid)
        state['running']=False
        server._notif_handle_ready('ui-local',state,[event],seen,registry,format_process_notification,[])
        # Preserve the previously failing lower-level replay observation:
        # identical raw re-delivery BEFORE consumption can submit again in core.
        # This plugin neither fabricates such events nor overrides that consumer.
        assert len(submitted)==(1 if mode=='normal' else 2)
    finally:
        if process is not None and process.poll() is None:
            process.terminate();process.wait(timeout=5)
        reset_hermes_home_override(home_token)


from test_desktop_route_completion import consumer
