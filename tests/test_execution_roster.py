import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import hermes_constants
from model_router.execution_roster import register_execution_roster


class Context:
    def __init__(self):
        self.hooks = {}
        self.events = []
        self.rpc = {}
    def register_hook(self, name, fn):
        self.hooks[name] = fn
    def register_rpc(self, name, fn):
        self.rpc[name] = fn
    def emit_to_session(self, sid, name, payload):
        self.events.append((sid, name, payload))


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / 'profiles' / 'observer'
    home.mkdir(parents=True)
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home)
    ctx = Context()
    roster = register_execution_roster(ctx, home)
    return roster, ctx, home


def pre(r, args=None, **ids):
    data = dict(session_id='segment-1', conversation_id='root', tool_call_id='call-1')
    data.update(ids)
    return r.pre(tool_name='delegate_task', args=args or {'goal': 'PRIVATE_GOAL'}, **data)


def post(r, result, args=None, **ids):
    data = dict(session_id='segment-1', conversation_id='root', tool_call_id='call-1')
    data.update(ids)
    return r.post(tool_name='delegate_task', args=args or {'goal': 'PRIVATE_GOAL'}, result=json.dumps(result), **data)


def rows(r, sid='root'):
    return r.list({'session_id': sid}, session_id=sid)['rows']


def test_requested_then_background_refusals_and_units(env):
    r, ctx, _ = env
    tasks = [{'goal': 'same', 'purpose': 'implementation'}, {'goal': 'same', 'profile': 'writer'},
             {'goal': 'same', 'execution': 'model', 'purpose': 'independent-review'}]
    assert pre(r, {'tasks': tasks}) is None
    initial = rows(r)
    assert [x['requested']['kind'] for x in initial] == ['model', 'profile', 'model']
    assert [x['requested']['role'] for x in initial] == ['light', None, 'heavy']
    assert all(x['status'] == 'requested' for x in initial)
    payload = {'status': 'dispatched', 'mode': 'background', 'count': 2, 'delegation_id': 'whole',
               'goals': ['same'] * 3, 'subagent_ids': ['sa-0-ab', 'sa-2-cd'],
               'refused': [{'task_index': 1, 'status': 'failed', 'error': 'SECRET'}],
               'units': [{'delegation_id': 'unit-a', 'group': 'private', 'task_indexes': [0]},
                         {'delegation_id': 'unit-b', 'task_indexes': [2]}]}
    assert post(r, payload, {'tasks': tasks}) is None
    got = rows(r)
    assert [x['subagent_id'] for x in got] == ['sa-0-ab', None, 'sa-2-cd']
    assert [x['delegation_id'] for x in got] == ['unit-a', None, 'unit-b']
    assert [x['status'] for x in got] == ['dispatched', 'error', 'dispatched']
    assert set(ctx.rpc) == {'execution.list'}
    assert all(e[1:] == ('execution.changed', {'schema': 1}) for e in ctx.events)
    assert 'SECRET' not in json.dumps(got)


def test_ambiguity_and_inline_never_guess(env):
    r, _, _ = env
    args = {'tasks': [{'goal': 'same'} for _ in range(3)]}
    pre(r, args)
    post(r, {'status': 'dispatched', 'subagent_ids': ['a', 'b'],
             'refused': [{'task_index': 1}, {'task_index': 1}]}, args)
    assert all(x['subagent_id'] is None for x in rows(r))
    post(r, {'status': 'dispatched', 'subagent_ids': ['a', 'b', 'c'],
             'units': [{'delegation_id': 'u', 'task_indexes': [0, 1]},
                       {'delegation_id': 'v', 'task_indexes': [1, 2]}]}, args)
    assert all(x['delegation_id'] is None for x in rows(r))
    pre(r, args, tool_call_id='call-2')
    post(r, {'status': 'dispatched', 'subagent_ids': ['x', 'y', 'z'],
             'inline_results': [{'task_index': 2, 'status': 'completed'}],
             'units': [{'delegation_id': 'u', 'task_indexes': [0, 1]}]}, args, tool_call_id='call-2')
    got = [x for x in rows(r) if x['tool_call_id'] == 'call-2']
    assert [x['subagent_id'] for x in got] == [None] * 3
    assert [x['status'] for x in got] == ['dispatched', 'dispatched', 'completed']


def test_route_is_runtime_report_not_request_or_response(env):
    r, _, _ = env
    args = {'tasks': [{'goal': 'one', 'purpose': 'implementation'}, {'goal': 'two'}]}
    pre(r, args)
    post(r, {'results': [{'task_index': 0, 'status': 'completed', 'model': 'actual/model',
                          'summary': 'PRIVATE', 'route': {'backend': 'model-router-auto', 'label': 'model:heavy'}},
                         {'task_index': 1, 'status': 'failed', 'model': 'unknown',
                          'route': {'backend': 'other', 'label': 'model:light'}}]}, args)
    one, two = rows(r)
    assert one['requested']['role'] == 'light'
    assert one['observed']['role'] == 'heavy'
    assert one['observed']['evidence'] == 'runtime_reported'
    assert one['observed']['model'] == 'actual/model'
    assert two['observed']['evidence'] == 'unknown'
    assert 'PRIVATE' not in json.dumps(rows(r))


def test_session_profile_alias_and_untrusted_rpc(env, monkeypatch):
    r, _, home = env
    pre(r)
    pre(r, tool_call_id='call-2', session_id='segment-2')
    assert len(rows(r, 'segment-1')) == len(rows(r, 'segment-2')) == 2
    assert rows(r, 'unknown') == []
    assert not r.list({'session_id': 'root', 'conversation_id': 'root'}, session_id='root')['rows']
    assert not r.list({'session_id': 'segment-2'}, session_id='segment-1')['rows']
    assert len(r.list({'session_id': 'root', 'profile': 'observer'}, session_id='root')['rows']) == 2
    assert not r.list({'session_id': 'root', 'profile': 'foreign'}, session_id='root')['rows']
    assert not r.list({'session_id': 'root', 'profile': ['observer']}, session_id='root')['rows']
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home.parent / 'foreign')
    pre(r, tool_call_id='foreign')
    assert not rows(r)
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home)
    assert len(rows(r)) == 2


def test_list_exact_identity_and_empty_context(env):
    r, _, _ = env
    pre(r, conversation_id=None)
    assert not rows(r)
    pre(r)
    post(r, {'status': 'dispatched', 'subagent_ids': ['sa-1'], 'delegation_id': 'del-1'})
    post(r, {'action': 'list', 'subagents': [{'subagent_id': 'sa-1', 'status': 'completed', 'goal': 'SECRET'},
                                             {'subagent_id': 'other', 'status': 'completed'}]},
         {'action': 'list'}, tool_call_id='list-call')
    assert rows(r)[0]['status'] == 'dispatched', 'current native list lacks exact unit proof'
    post(r, {'action': 'list', 'subagents': [{'subagent_id': 'sa-1', 'delegation_id': 'foreign', 'status': 'completed'}]},
         {'action': 'list'}, tool_call_id='other-list')
    assert rows(r)[0]['status'] == 'dispatched'
    post(r, {'action': 'list', 'subagents': [{'subagent_id': 'sa-1', 'delegation_id': 'del-1', 'status': 'completed'}]},
         {'action': 'list'}, tool_call_id='bound-list')
    assert rows(r)[0]['status'] == 'completed'
    assert 'SECRET' not in json.dumps(rows(r))


def test_invalid_ids_and_bounded_rows(env):
    r, _, _ = env
    pre(r, tool_call_id='x\nLEAK')
    assert not rows(r)
    for i in range(520):
        pre(r, tool_call_id=f'c-{i}')
    assert len(r.rows) == 512
    assert len(rows(r)) == 128


def test_concurrent_hooks_and_no_files(env):
    r, _, home = env
    def one(i):
        pre(r, {'goal': 'SECRET', 'context': 'PRIVATE'}, tool_call_id=f'c-{i}')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, range(100)))
    assert len(rows(r)) == 100
    assert not list(home.iterdir())
    assert 'SECRET' not in json.dumps(rows(r))
    assert not any(t.name.startswith('roster') for t in threading.enumerate())


def test_rpc_optional_and_callbacks_fail_open(tmp_path, monkeypatch):
    home = tmp_path / 'profiles' / 'observer'
    home.mkdir(parents=True)
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home)
    ctx = Context()
    monkeypatch.setattr(ctx, 'register_rpc', None)
    r = register_execution_roster(ctx, home)
    assert r.list({}, session_id='root')['reason'] == 'rpc_unavailable'
    assert r.pre(tool_name='delegate_task', args={'tasks': [{'purpose': []}]}, session_id='s', conversation_id='r', tool_call_id='c') is None
    assert r.post(tool_name='delegate_task', args={}, result='{broken', session_id='s', conversation_id='r', tool_call_id='c') is None


def test_default_root_identity(tmp_path, monkeypatch):
    home = tmp_path / 'root'
    home.mkdir()
    monkeypatch.setattr(hermes_constants, 'get_default_hermes_root', lambda: home)
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home)
    r = register_execution_roster(Context(), home)
    pre(r)
    snapshot = r.list({'session_id': 'root', 'profile': 'default'}, session_id='root')
    assert snapshot['origin_profile'] == 'default'
    assert len(snapshot['rows']) == 1
    assert not r.list({'session_id': 'root', 'profile': 'root'}, session_id='root')['rows']


def test_native_task_normalization(env):
    r, _, _ = env
    pre(r, {'goal': 'one', 'tasks': [], 'purpose': 'implementation'})
    assert rows(r)[0]['requested']['kind'] == 'unknown'
    pre(r, {'tasks': json.dumps([{'goal': 'two', 'profile': 'writer'}])}, tool_call_id='c2')
    assert rows(r)[1]['requested']['profile'] == 'writer'
