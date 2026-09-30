"""Exercise native ownership guard and actual Popen tree cancellation offline."""
import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
from tools.process_registry import ProcessRegistry
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from model_router.runtime_tracking import RouteRuntime


def _native_kill_handler(registry):
    import tui_gateway.methods_tools as methods
    source = Path(methods.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        isinstance(d, ast.Call) and any(isinstance(a, ast.Constant) and a.value == 'process.kill' for a in d.args)
        for d in n.decorator_list))
    node = copy.deepcopy(node); node.decorator_list = []; node.name = 'kill_rpc'
    scope = {'_tools_mod': lambda _: SimpleNamespace(process_registry=registry),
             '_err': lambda rid, code, message: {'error': {'code': code}},
             '_ok': lambda rid, result: {'result': result}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<native-process-kill>', 'exec'), scope)
    return scope['kill_rpc']


def test_native_owner_guard_and_kill_stop_actual_worker_runner_adapter_tree(tmp_path):
    token = set_hermes_home_override(str(tmp_path))
    registry = ProcessRegistry()
    process = None
    descendant_ids = []
    try:
        # root -> runner -> adapter; all task-owned and bounded even on failure.
        grandchild_code = 'import time; time.sleep(20)'
        runner_code = "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c',%r]); Path(%r).write_text(str(p.pid)); time.sleep(20)" % (grandchild_code, str(tmp_path / 'adapter.pid'))
        root_code = "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c',%r]); Path(%r).write_text(str(p.pid)); time.sleep(20)" % (runner_code, str(tmp_path / 'runner.pid'))
        flags = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == 'win32' else {'start_new_session': True}
        with (tmp_path / 'job.log').open('wb') as out:
            process = subprocess.Popen([sys.executable, '-c', root_code], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, close_fds=True, **flags)
        runtime = RouteRuntime('parent', 'owner-key', 'owner-task', registry, lambda *a: True)
        process_id = runtime.track(process, job_id='cancel-test', purpose='mechanical', cwd=str(tmp_path))
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not (tmp_path / 'adapter.pid').exists():
            time.sleep(.05)
        assert (tmp_path / 'adapter.pid').exists(), 'actual tree did not start'
        descendant_ids = [int((tmp_path / name).read_text()) for name in ['runner.pid', 'adapter.pid']]
        handler = _native_kill_handler(registry)
        denied = handler(1, {'process_id': process_id}, {'session_key': 'foreign-key'})
        assert denied['error']['code'] == 4044
        assert process.poll() is None
        stopped = handler(2, {'process_id': process_id}, {'session_key': 'owner-key'})
        assert stopped['result']['status'] in {'killed', 'already_exited'}
        process.wait(timeout=6)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(psutil.pid_exists(pid) for pid in descendant_ids):
            time.sleep(.05)
        assert not any(psutil.pid_exists(pid) for pid in descendant_ids)
    finally:
        if process is not None and process.poll() is None:
            registry.kill_all(task_id='owner-task')
        reset_hermes_home_override(token)
