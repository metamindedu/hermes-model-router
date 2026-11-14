"""Real native relay/serialization/replay -> pure JS observer projection.

Private native producer imports are fixture-only, not plugin dependencies.
The dispatcher rows and progress callback transport are inert seams. This is
NOT authorized Gateway RPC, actual child execution, SDK routing or provider E2E.
"""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


NODE_PROJECTION = r"""
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const params = {};
for (const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) {
  for (const name of m[1].split(',').map(x=>x.trim()).filter(Boolean)) params[name]=undefined;
}
params.DesktopSDK={};
params.jsx=(type,props={})=>({type,props}); params.jsxs=params.jsx;
const code=source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g,'')
  .replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m,'')
  .replace(/export default /g,'const pluginDefinition = ').replace(/^export\s+/gm,'');
const api=new Function(...Object.keys(params),code+'\nreturn {createExecutionReplayStore,mergeExecutionRows,overlayExecutionReplay,ExecutionRow};')(...Object.values(params));
const scope={connectionId:'fixture-origin',profile:'observer',sessionId:'parent'};
const store=api.createExecutionReplayStore();
if (!store.accept(scope,store.cursor(scope),input.bootstrap).accepted) throw Error('bootstrap refused');
if (!store.accept(scope,store.cursor(scope),input.replay,123).accepted) throw Error('replay refused');
const rows=api.overlayExecutionReplay(api.mergeExecutionRows(input.roster,input.live,'observer'),store.snapshot(scope),scope);
const text=n=>typeof n==='string'?n:Array.isArray(n)?n.map(text).join(' '):n?.props?text(n.props.children):'';
console.log(JSON.stringify({projection:store.snapshot(scope),rows,text:rows.map(row=>text(api.ExecutionRow({row})))}));
"""


@pytest.mark.parametrize('status', ['completed', 'failed', 'timeout', 'interrupted'])
def test_actual_native_progress_replay_reaches_candidate_metadata_and_card(tmp_path, status):
    root = os.environ.get('HERMES_DESKTOP_SOURCE_ROOT')
    if not root:
        pytest.skip('Explicit coherent native source/runtime required')
    assert isinstance(root, str)
    core = Path(root).resolve()
    import hermes_constants
    from gateway.session_events import SessionEvents
    from tools.delegate_tool_progress import _build_child_progress_callback
    from tui_gateway.tool_progress import _subagent_payload
    import inspect
    for function in (SessionEvents, _build_child_progress_callback, _subagent_payload):
        assert Path(inspect.getfile(function)).resolve().is_relative_to(core)
    token = hermes_constants.set_hermes_home_override(tmp_path)
    stream = SessionEvents()
    try:
        bootstrap = stream.since(None, 0)
        def parent_callback(event_type, name=None, preview=None, args=None, **kwargs):
            payload = _subagent_payload(event_type, name, preview, kwargs, show_reasoning=False)
            stream.publish('parent', payload, event_type=event_type)
        parent = SimpleNamespace(tool_progress_callback=parent_callback, _delegate_spinner=None,
                                 session_id='parent')
        callbacks = [_build_child_progress_callback(index, 'PRIVATE_FIXTURE_GOAL', parent, 2,
            subagent_id=f'sa-{index}-native', parent_id='parent', depth=1,
            model='fixture-model', toolsets=['terminal'],
            session_ref={'session_id':f'original-child-{index}', 'delegation_id':'actual-call'})
            for index in range(2)]
        for callback in callbacks:
            assert callable(callback)
            callback('subagent.start')
        fast_callback = callbacks[0]
        assert callable(fast_callback)
        fast_callback('subagent.complete', preview='PRIVATE_FIXTURE_PREVIEW', status=status,
                     summary='PRIVATE_FIXTURE_SUMMARY', api_calls=2, duration_seconds=2.5,
                     output_tail=[{'text':'PRIVATE_FIXTURE_OUTPUT'}])
        # The slow sibling has not completed. No group result or stop hook exists.
        replay = stream.since(bootstrap['replay_epoch'], 0)
        assert replay['snapshot_required'] is False and replay['count'] == 3
        assert 'PRIVATE_FIXTURE_' in json.dumps(replay), 'Fixture must exercise raw prose stripping'
        rows = [{'id':f'fixture:{index}', 'execution_mode':'native', 'conversation_id':'parent',
                 'parent_session_id':'parent', 'task_index':index, 'subagent_id':f'sa-{index}-native',
                 'delegation_id':'opaque-unit', 'async_unit_id':'opaque-unit',
                 'native_call_delegation_id':'actual-call', 'status':'queued',
                 'child_session_id':f'rotated-physical-{index}',
                 'requested':{'kind':'profile','profile':'specialist'}, 'observed':{'kind':'unknown'}}
                for index in range(2)]
        data = {'bootstrap':bootstrap,'replay':replay,
                'live':{'subagents':[{'subagent_id':'sa-1-native','delegation_id':'actual-call','status':'running'}]},
                'roster':{'schema':1,'origin_profile':'observer','rows':rows}}
        result = subprocess.run(['node','-e',NODE_PROJECTION,str(Path(__file__).parents[1]/'desktop/plugin.js')],
            input=json.dumps(data), capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert 'PRIVATE_FIXTURE_' not in json.dumps(output)
        assert [row['status'] for row in output['rows']] == [status, 'running']
        fast, slow = output['rows']
        assert fast['status_evidence'] == 'public_session_event'
        assert fast['requested']['profile'] == 'specialist'
        assert fast['observed']['kind'] == 'unknown'
        assert fast['child_session_id'] == 'rotated-physical-0'
        assert fast['reported_child_session_id'] == 'original-child-0'
        assert fast['api_call_count'] == 2 and fast['duration_seconds'] == 2.5
        assert slow['api_call_count'] is None
        assert output['projection']['coverage_gap'] is False
        assert output['projection']['needs_recovery'] is False
        assert ('모델 호출 2회' in output['text'][0] and '모델 호출 횟수 미관찰' in output['text'][1])
    finally:
        stream.release()
        hermes_constants.reset_hermes_home_override(token)
