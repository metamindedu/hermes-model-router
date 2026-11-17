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


def test_normal_registration_never_opens_private_native_metadata(env, monkeypatch):
    import builtins
    r, _, home = env
    opened = []
    original_import = builtins.__import__
    def deny_private_metadata(name, globals=None, locals=None, fromlist=(), level=0):
        package = (globals or {}).get('__package__', '')
        if name == 'model_router.execution_metadata' or (
                name == 'execution_metadata' and level and package.startswith('model_router')):
            opened.append(name)
            raise AssertionError('The unadmitted metadata adapter must not be imported')
        return original_import(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, '__import__', deny_private_metadata)
    (home / 'state.db').write_bytes(b'PRIVATE_UNREADABLE_SENTINEL')
    args = {'tasks': [{'execution': 'profile', 'profile': 'target'}]}
    pre(r, args)
    r.start(parent_session_id='segment-1', child_session_id='original-child', child_subagent_id='sa-native')
    post(r, {'status': 'dispatched', 'delegation_id': 'native-call', 'subagent_ids': ['sa-native']}, args)
    r.stop(parent_session_id='segment-1', child_session_id='rotated-child', child_status='completed')
    assert r._metadata_factory is None and rows(r)[0]['status'] == 'queued'
    assert not opened
    assert (home / 'state.db').read_bytes() == b'PRIVATE_UNREADABLE_SENTINEL'
    assert not (home / 'state.db-shm').exists() and not (home / 'state.db-wal').exists()
    r.stop(parent_session_id='segment-1', child_session_id='original-child', child_status='completed')
    assert rows(r)[0]['status'] == 'completed' and not opened


def test_requested_then_background_refusals_and_units(env):
    r, ctx, _ = env
    tasks = [{'goal': 'same', 'purpose': 'implementation'}, {'goal': 'same', 'profile': 'writer'},
             {'goal': 'same', 'execution': 'model', 'purpose': 'independent-review'}]
    assert pre(r, {'tasks': tasks}) is None
    initial = rows(r)
    assert [x['requested']['kind'] for x in initial] == ['model', 'profile', 'model']
    assert [x['requested']['role'] for x in initial] == ['light', None, 'heavy']
    assert [x['requested']['slot'] for x in initial] == ['code-complex', None, 'verify-complex']
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
    assert [x.get('async_unit_id') for x in got] == ['unit-a', None, 'unit-b']
    assert [x.get('native_call_delegation_id') for x in got] == ['whole', None, 'whole']
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


def test_native_stop_before_dispatch_and_safe_activity(env):
    r, ctx, _ = env
    assert {'subagent_start', 'subagent_stop', 'post_compaction', 'pre_api_request',
            'post_api_request'} <= set(ctx.hooks)
    pre(r)
    ctx.hooks['subagent_start'](parent_session_id='segment-1', child_session_id='child',
                                child_subagent_id='short', child_goal='SECRET')
    r.pre(tool_name='terminal', session_id='child', args={'command': 'SECRET'})
    ctx.hooks['pre_api_request'](session_id='child', model='provider/model', provider='provider',
                                 user_message='SECRET')
    ctx.hooks['post_api_request'](session_id='child', response='SECRET')
    ctx.hooks['subagent_stop'](parent_session_id='segment-1', child_session_id='child',
                               child_status='completed', duration_ms=2500, child_summary='SECRET',
                               tool_call_history=[{'args': 'SECRET'}])
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    row = rows(r)[0]
    assert (row['status'], row['child_session_id'], row['last_tool'], row['tool_count'],
            row['api_call_count'], row['duration_seconds']) == ('completed', 'child', 'terminal', 1, 1, 2.5)
    assert row['model'] == 'provider/model' and row['provider'] == 'provider'
    assert row['observed']['evidence'] == 'unknown'
    assert row['started_at'] <= row['activity_at']
    assert 'SECRET' not in json.dumps(row)
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    assert rows(r)[0]['status'] == 'completed'


@pytest.mark.parametrize('status,expected', [('failed', 'error'), ('interrupted', 'interrupted')])
def test_stop_after_dispatch_and_compactions(env, status, expected):
    r, _, _ = env
    pre(r)
    r.start(parent_session_id='segment-1', child_session_id='child', child_subagent_id='short')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    r.compact(old_session_id='segment-1', session_id='segment-new')
    r.compact(old_session_id='child', session_id='child-new')
    r.pre(tool_name='search', session_id='child-new')
    r.stop(parent_session_id='segment-new', child_session_id='child-new', child_status=status)
    row = rows(r, 'segment-new')[0]
    assert (row['status'], row['child_session_id'], row['last_tool']) == (expected, 'child-new', 'search')
    r.stop(parent_session_id='segment-new', child_session_id='child-new', child_status='completed')
    assert rows(r)[0]['status'] == expected
    assert rows(r, 'unrelated') == []


def test_ambiguous_recycled_short_and_foreign_home(env, monkeypatch):
    r, _, home = env
    pre(r)
    r.start(parent_session_id='segment-1', child_session_id='child-a', child_subagent_id='short')
    r.start(parent_session_id='segment-1', child_session_id='child-b', child_subagent_id='short')
    r.stop(parent_session_id='segment-1', child_session_id='child-a', child_status='completed')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    assert rows(r)[0]['status'] == 'dispatched'
    assert 'child_session_id' not in rows(r)[0]
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home.parent / 'foreign')
    r.stop(parent_session_id='segment-1', child_session_id='child-b', child_status='failed')
    monkeypatch.setattr(hermes_constants, 'get_hermes_home', lambda: home)
    assert r.children['child-b']['status'] == 'queued', 'foreign stop cannot settle the child'


def test_parallel_lifecycle_interleaving(env):
    r, _, _ = env
    def one(i):
        pre(r, tool_call_id=f'call-{i}')
        r.start(parent_session_id='segment-1', child_session_id=f'child-{i}', child_subagent_id=f'short-{i}')
        r.stop(parent_session_id='segment-1', child_session_id=f'child-{i}', child_status='completed')
        post(r, {'status': 'dispatched', 'subagent_ids': [f'short-{i}'], 'delegation_id': f'unit-{i}'},
             tool_call_id=f'call-{i}')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, range(32)))
    assert len(rows(r)) == 32
    assert all(row['status'] == 'completed' for row in rows(r))


def test_short_id_reuse_cannot_overwrite_previous_child(env):
    r, _, _ = env
    pre(r)
    r.start(parent_session_id='segment-1', child_session_id='first', child_subagent_id='short')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'first-unit'})
    r.stop(parent_session_id='segment-1', child_session_id='first', child_status='completed')
    pre(r, tool_call_id='next')
    r.start(parent_session_id='segment-1', child_session_id='second', child_subagent_id='short')
    r.stop(parent_session_id='segment-1', child_session_id='second', child_status='failed')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'second-unit'},
         tool_call_id='next')
    first, second = rows(r)
    assert first['status'] == 'completed' and first['child_session_id'] == 'first'
    assert second['status'] == 'dispatched' and 'child_session_id' not in second


def test_construction_is_queued_until_actual_child_activity(env):
    r, _, _ = env
    pre(r)
    r.start(parent_session_id='segment-1', child_session_id='child', child_subagent_id='short')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    assert rows(r)[0]['status'] == 'queued'
    r.api_pre(session_id='child', model='fixture-model', provider='fixture')
    assert rows(r)[0]['status'] == 'running'
    r.stop(parent_session_id='segment-1', child_session_id='child', child_status='completed')
    r.api_pre(session_id='child', model='late-model', provider='fixture')
    assert rows(r)[0]['status'] == 'completed'
    assert rows(r)[0]['model'] == 'fixture-model'


def test_spare_model_switch_is_recorded_as_ordered_pairs(env):
    r, _, _ = env
    pre(r)
    r.start(parent_session_id='segment-1', child_session_id='child', child_subagent_id='short')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    r.api_pre(session_id='child', model='primary-model', provider='primary')
    r.api_pre(session_id='child', model='primary-model', provider='primary')
    r.api_pre(session_id='child', model='spare-model', provider='spare')
    row = rows(r)[0]
    assert (row['model'], row['provider']) == ('spare-model', 'spare')
    assert row['models'] == [{'model': 'primary-model', 'provider': 'primary'}, {'model': 'spare-model', 'provider': 'spare'}]
    # A provider that fails validation never pairs the new model with the previous provider.
    r.api_pre(session_id='child', model='third-model', provider='bad provider\n')
    row = rows(r)[0]
    assert (row['model'], row['provider']) == ('third-model', None)
    # A -> B -> A is kept as transitions, not collapsed to distinct pairs.
    r.api_pre(session_id='child', model='spare-model', provider='spare')
    assert [m['model'] for m in rows(r)[0]['models']][-2:] == ['third-model', 'spare-model']
    for i in range(6):
        r.api_pre(session_id='child', model=f'm{i}', provider='p')
    models = rows(r)[0]['models']
    assert len(models) == 4 and models[0]['model'] == 'primary-model' and models[-1]['model'] == 'm5'
    assert rows(r)[0]['models_truncated'] is True


def test_activity_does_not_reconcile_all_finished_children(env, monkeypatch):
    r, _, _ = env
    pre(r)
    r.start(parent_session_id='segment-1', child_session_id='child', child_subagent_id='short')
    post(r, {'status': 'dispatched', 'subagent_ids': ['short'], 'delegation_id': 'unit'})
    # A filled bounded history must not multiply every hot-path update by all
    # retired children. Count comparisons, rather than using a flaky wall clock.
    for i in range(200):
        r.children[f'retired-{i}'] = {'parent': 'retired-parent', 'session': f'retired-{i}',
                                    'short': f'retired-short-{i}', 'status': 'completed'}
    count = 0
    original = r._same_session
    def counted(*args):
        nonlocal count
        count += 1
        return original(*args)
    monkeypatch.setattr(r, '_same_session', counted)
    r.api_pre(session_id='child', model='fixture-model', provider='fixture')
    assert count < 2000
    assert rows(r)[0]['api_call_count'] == 1
