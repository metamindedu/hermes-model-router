"""Actual native hook-call contracts with inert agents; no provider/agent run.

The hook calls are compiled from the explicitly selected native source. Only the
hook dispatcher and content-redaction helper dependencies are substituted. This
is producer-to-observer contract evidence, not a live Gateway/provider test.
"""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import hermes_constants
import pytest
from model_router.execution_roster import register_execution_roster


class Context:
    def __init__(self):
        self.hooks = {}
        self.rpc = {}
        self.events = []

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_rpc(self, name, callback):
        self.rpc[name] = callback

    def emit_to_session(self, *args):
        self.events.append(args)


@pytest.fixture
def observer_home(tmp_path):
    home = tmp_path / 'profiles' / 'observer'
    home.mkdir(parents=True)
    # A process-global monkeypatch reroutes unrelated native background cache
    # workers into this fixture. Bind only this execution context instead.
    token = hermes_constants.set_hermes_home_override(home)
    try:
        yield home
    finally:
        hermes_constants.reset_hermes_home_override(token)


@pytest.fixture
def native_source():
    value = os.environ.get('HERMES_DESKTOP_SOURCE_ROOT')
    if not value:
        pytest.skip('Explicit native source checkout is required')
    assert isinstance(value, str)
    core = Path(value)
    assert (core / 'tools/delegate_tool.py').is_file()
    return core


def native_start(core, ctx, parent, child, short_id, *, dispatcher=None):
    source = core / 'tools/delegate_tool.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == '_invoke_hook'
             and node.args and isinstance(node.args[0], ast.Constant)
             and node.args[0].value == 'subagent_start']
    assert len(calls) == 1, 'Native start contract changed; inspect producer'
    scope = {'_invoke_hook': dispatcher or (lambda name, **kw: ctx.hooks[name](**kw)),
             'parent_sid': parent.session_id, 'parent_agent': parent,
             'parent_subagent_id': None, 'child': child, 'subagent_id': short_id,
             'effective_role': 'leaf', 'goal': 'PRIVATE_NATIVE_GOAL'}
    eval(compile(ast.Expression(calls[0]), str(source), 'eval'), scope)


def native_stop(core, ctx, monkeypatch, parent, child, status, *, native_dispatch=False):
    source = core / 'tools/delegate_tool_results.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name == '_fire_subagent_stop_hooks']
    assert len(nodes) == 1, 'Native stop contract changed; inspect producer'
    import hermes_cli.plugins as plugins
    if not native_dispatch:
        monkeypatch.setattr(plugins, 'invoke_hook', lambda name, **kw: ctx.hooks[name](**kw))
    namespace: dict[str, Any] = {'redact_child_value': lambda value: value,
                                '_subagent_stop_tool_call_history': lambda value: value}
    exec(compile(ast.Module(body=[nodes[0]], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['_fire_subagent_stop_hooks'](
        [{'task_index': 0, 'status': status, '_child_role': 'leaf', '_child_cost_usd': 0,
          'summary': 'PRIVATE_NATIVE_SUMMARY', 'duration_seconds': 2.5,
          'tool_trace': [{'tool': 'read_file', 'arguments': 'PRIVATE_ARGUMENTS'}]}],
        {0: child}, parent)


@pytest.mark.parametrize('status', ['completed', 'failed', 'interrupted'])
@pytest.mark.parametrize('stop_before_post', [False, True])
def test_actual_native_producers_settle_exact_row_without_retaining_content(
        observer_home, monkeypatch, native_source, status, stop_before_post):
    home = observer_home
    ctx = Context()
    roster = register_execution_roster(ctx, home)
    ids = {'session_id': 'segment', 'conversation_id': 'parent-root', 'tool_call_id': 'call'}
    args = {'tasks': [{'goal': 'PRIVATE_TASK_GOAL', 'execution': 'model', 'purpose': 'independent-review'}]}
    roster.pre(tool_name='delegate_task', args=args, **ids)
    parent = SimpleNamespace(session_id='segment', _current_turn_id='turn')
    child = SimpleNamespace(session_id='child-native-stored')
    native_start(native_source, ctx, parent, child, 'sa-native')
    if stop_before_post:
        native_stop(native_source, ctx, monkeypatch, parent, child, status)
    roster.post(tool_name='delegate_task', args=args,
                result={'status': 'dispatched', 'count': 1, 'delegation_id': 'deleg-native',
                        'subagent_ids': ['sa-native']}, **ids)
    if not stop_before_post:
        native_stop(native_source, ctx, monkeypatch, parent, child, status)
    rows = roster.list({'session_id': 'parent-root'}, session_id='parent-root')['rows']
    assert len(rows) == 1
    expected = 'error' if status == 'failed' else status
    assert rows[0]['status'] == expected
    assert rows[0]['subagent_id'] == 'sa-native'
    assert rows[0]['delegation_id'] == 'deleg-native'
    assert rows[0]['child_session_id'] == 'child-native-stored'
    assert rows[0]['duration_seconds'] == 2.5
    assert rows[0]['observed']['evidence'] == 'unknown', 'leaf is not a Heavy identity'
    assert 'PRIVATE_' not in json.dumps(rows)
    assert not list(home.iterdir()), 'Passive observers must not write profile files'


def test_foreign_profile_activity_is_unknown_not_zero(observer_home):
    home = observer_home
    ctx = Context()
    roster = register_execution_roster(ctx, home)
    ids = {'session_id': 'segment', 'conversation_id': 'parent-root', 'tool_call_id': 'call'}
    args = {'tasks': [{'goal': 'PRIVATE_PROFILE_GOAL', 'execution': 'profile', 'profile': 'specialist'}]}
    roster.pre(tool_name='delegate_task', args=args, **ids)
    roster.start(parent_session_id='segment', child_session_id='child-native-stored', child_subagent_id='sa-native')
    roster.post(tool_name='delegate_task', args=args, result={
        'status': 'dispatched', 'count': 1, 'delegation_id': 'deleg-native', 'subagent_ids': ['sa-native']}, **ids)
    target = home.parent / 'specialist'
    target.mkdir()
    token = hermes_constants.set_hermes_home_override(target)
    try:
        roster.api_pre(session_id='child-native-stored', model='target-model', provider='fixture')
        roster.pre(tool_name='read_file', args={'path': 'PRIVATE_TARGET_PATH'}, session_id='child-native-stored')
    finally:
        hermes_constants.reset_hermes_home_override(token)
    roster.stop(parent_session_id='segment', child_session_id='child-native-stored', child_status='completed')
    row = roster.list({'session_id': 'parent-root'}, session_id='parent-root')['rows'][0]
    assert row['status'] == 'completed'
    assert row['tool_count'] is None and row['api_call_count'] is None
    assert 'PRIVATE_' not in json.dumps(row)
    assert not list(home.iterdir()) and not list(target.iterdir())


@pytest.fixture
def per_home_dispatch(observer_home, monkeypatch):
    """Real per-home dispatcher; discovery and observability are inert seams."""
    from hermes_cli import lifecycle, plugins
    target_home = observer_home.parent / 'specialist'
    target_home.mkdir()
    managers, contexts, rosters = {}, {}, {}
    class ManagerContext(Context):
        def __init__(self, manager):
            super().__init__()
            self.manager = manager
        def register_hook(self, name, callback):
            self.manager._hooks.setdefault(name, []).append(callback)
            super().register_hook(name, callback)
    for home in (observer_home, target_home):
        manager = plugins.PluginManager(scope_key=hermes_constants.hermes_home_key(home))
        manager._discovered = True
        context = ManagerContext(manager)
        token = hermes_constants.set_hermes_home_override(home)
        try:
            roster = register_execution_roster(context, home)
        finally:
            hermes_constants.reset_hermes_home_override(token)
        managers[home.resolve()], contexts[home], rosters[home] = manager, context, roster
    monkeypatch.setattr(plugins, '_plugin_managers_by_home', managers)
    monkeypatch.setattr(plugins, '_plugin_manager', managers[observer_home.resolve()])
    monkeypatch.setattr(plugins, '_join_background_discovery', lambda: False)
    monkeypatch.setattr(plugins, '_resolve_hook_callback_timeout', lambda: 0)
    monkeypatch.setattr(lifecycle, '_observe', lambda *a, **kw: None)
    return plugins, lifecycle, target_home, contexts[observer_home], rosters[observer_home], rosters[target_home]


def _native_dispatch_begin(core, plugins, lifecycle, ctx, parent, children):
    args = {'tasks': [{'execution': 'profile', 'profile': 'specialist', 'goal': 'PRIVATE_GOAL'} for _ in children]}
    ids = dict(session_id=parent.session_id, conversation_id='parent-root', tool_call_id='call')
    plugins.invoke_hook('pre_tool_call', tool_name='delegate_task', args=args, **ids)
    for i, child in enumerate(children):
        native_start(core, ctx, parent, child, f'sa-native-{i}', dispatcher=lifecycle.invoke_hook)
    plugins.invoke_hook('post_tool_call', tool_name='delegate_task', args=args, result={
        'status': 'dispatched', 'count': len(children), 'delegation_id': 'unit-native',
        'subagent_ids': [f'sa-native-{i}' for i in range(len(children))]}, **ids)


def test_actual_native_publication_requires_matching_origin_compaction(
        observer_home, native_source, per_home_dispatch, monkeypatch):
    from hermes_state import SessionDB
    from agent.compaction_events import fire_post_compaction
    plugins, lifecycle, target, ctx, origin, foreign = per_home_dispatch
    # Foreign hooks cannot attest lineage through an unadmitted private reader.
    assert origin._metadata_factory is None
    parent = SimpleNamespace(session_id='segment', _current_turn_id='turn')
    child = SimpleNamespace(session_id='child-native-stored')
    db = SessionDB(db_path=observer_home / 'state.db')
    markers = {'_delegate_from': 'segment', '_subagent_id': 'sa-native-0', 'private': 'PRIVATE_DB_METADATA'}
    try:
        db.create_session('segment', 'fixture')
        db.create_session(child.session_id, 'delegate', parent_session_id='segment', model_config=markers)
        _native_dispatch_begin(native_source, plugins, lifecycle, ctx, parent, [child])
        token = hermes_constants.set_hermes_home_override(target)
        try:
            for new in ('middle-native', 'tip-native'):
                old = child.session_id
                holder = 'fixture-' + new
                assert db.try_acquire_compression_lock(old, holder)
                db.publish_compression_child(parent_session_id=old, child_session_id=new,
                    source='delegate', model_config=markers, compression_lock_holder=holder,
                    messages=[{'role': 'user', 'content': 'PRIVATE_HISTORY'},
                              {'role': 'assistant', 'content': 'PRIVATE_HANDOFF'}])
                fire_post_compaction(session_id=new, old_session_id=old, kind='summarize', reason='auto',
                    before_tokens=100, after_tokens=40, messages_removed=4)
                child.session_id = new
        finally:
            hermes_constants.reset_hermes_home_override(token)
        assert not origin.aliases and not foreign.children
        native_stop(native_source, ctx, monkeypatch, parent, child, 'completed', native_dispatch=True)
        row = origin.list({'session_id': 'parent-root'}, session_id='parent-root')['rows'][0]
        assert row['status'] == 'queued'
        assert row['child_session_id'] == 'child-native-stored'
        assert origin._metadata_factory is None
        # Explicit matching-origin public contract replay, not DB recovery.
        for old, new in [('child-native-stored', 'middle-native'), ('middle-native', 'tip-native')]:
            fire_post_compaction(session_id=new, old_session_id=old, kind='summarize', reason='auto',
                before_tokens=100, after_tokens=40, messages_removed=4)
        native_stop(native_source, ctx, monkeypatch, parent, child, 'completed', native_dispatch=True)
        row = origin.list({'session_id': 'parent-root'}, session_id='parent-root')['rows'][0]
        assert row['status'] == 'completed' and row['child_session_id'] == 'tip-native'
        assert row['tool_count'] is None and row['api_call_count'] is None
        assert 'PRIVATE_' not in json.dumps(row)
        assert not list(target.iterdir()), 'Never open or create the target profile database'
    finally:
        db.close()


def test_actual_native_cleanup_records_do_not_replace_public_stop_hooks(
        observer_home, native_source, per_home_dispatch, monkeypatch):
    from hermes_state import SessionDB
    from tools import delegate_tool_resumable as records
    plugins, lifecycle, target, ctx, origin, _ = per_home_dispatch
    assert origin._metadata_factory is None
    db = SessionDB(db_path=observer_home / 'state.db')
    parent = SimpleNamespace(session_id='segment', _current_turn_id='turn', _session_db=db)
    children = [SimpleNamespace(session_id=f'child-native-{i}', _parent_session_id='segment',
        _delegation_unit_id='unit-native', _delegation_id='batch-native', model='fixture',
        _delegate_resume={'goal': 'PRIVATE_GOAL', 'context': 'PRIVATE_CONTEXT',
                          'toolsets': [], 'endpoint': [], 'route': None}) for i in range(2)]
    # Only workspace/terminal discovery is stubbed; the actual native record
    # serializer, classification, SQL start/stop writes and projection run.
    monkeypatch.setattr(records, '_child_cwd', lambda run: str(observer_home))
    monkeypatch.setattr(records, '_worktrees_of', lambda cwd: [])
    try:
        db.create_session('segment', 'fixture')
        for i, child in enumerate(children):
            db.create_session(child.session_id, 'delegate', parent_session_id='segment',
                model_config={'_delegate_from': 'segment', '_subagent_id': f'sa-native-{i}'})
        _native_dispatch_begin(native_source, plugins, lifecycle, ctx, parent, children)
        runs = [SimpleNamespace(child=child, parent_agent=parent, subagent_id=f'sa-native-{i}',
                  child_task_id=f'fixture-task-{i}', worktree_info=None) for i, child in enumerate(children)]
        for run in runs:
            records.record_start(run)
        records.record_stop(runs[0], {'status': 'completed', 'exit_reason': 'completed'})
        stored_only = origin.list({'session_id': 'parent-root'}, session_id='parent-root')['rows']
        assert [row['status'] for row in stored_only] == ['queued', 'queued']
        # Core persistence cannot replace the original public stop producer.
        native_stop(native_source, ctx, monkeypatch, parent, children[0], 'completed', native_dispatch=True)
        midpoint = origin.list({'session_id': 'parent-root'}, session_id='parent-root')['rows']
        assert [row['status'] for row in midpoint] == ['completed', 'queued']
        records.record_stop(runs[1], {'status': 'completed', 'exit_reason': 'completed'})
        assert [row['status'] for row in origin.list({'session_id': 'parent-root'}, session_id='parent-root')['rows']] == ['completed', 'queued']
        native_stop(native_source, ctx, monkeypatch, parent, children[1], 'completed', native_dispatch=True)
        final = origin.list({'session_id': 'parent-root'}, session_id='parent-root')['rows']
        assert [row['status'] for row in final] == ['completed', 'completed']
        assert 'PRIVATE_' not in json.dumps(final)
        assert all(row['api_call_count'] is None and row['tool_count'] is None for row in final)
        assert not list(target.iterdir())
    finally:
        db.close()


def test_actual_native_split_reply_keeps_call_and_unit_ids_distinct(observer_home, native_source):
    from tools.delegate_tool_dispatch import _dispatched_payload
    from tools.delegate_tool_child_run import _register_child
    from tools.delegate_tool_registry import list_active_subagents, _unregister_subagent
    from tui_gateway.methods_subagents import _SUBAGENT_SNAPSHOT_FIELDS, _child_session_id
    ctx = Context()
    roster = register_execution_roster(ctx, observer_home)
    parent = SimpleNamespace(session_id='segment')
    units = ['opaque-native-z', 'opaque-native-a']
    children = [SimpleNamespace(_subagent_id=f'contract-split-{i}', _delegation_id='contract-call',
        _delegation_unit_id=units[i], session_id=f'contract-child-{i}',
        _parent_session_id='segment', model='fixture') for i in range(2)]
    tasks = [{'goal':'PRIVATE_GOAL','purpose':'mechanical'} for _ in children]
    members = [(i, task, child) for i, (task, child) in enumerate(zip(tasks, children))]
    batch: Any = SimpleNamespace(task_list=tasks, children=members, live_deleg_id='contract-call',
                            refused=[], live_paths=[])
    explicit: Any = [(SimpleNamespace(group=None, children=[member]), units[i]) for i, member in enumerate(members)]
    ids = dict(session_id='segment', conversation_id='root', tool_call_id='split-call')
    args = {'tasks':tasks}
    try:
        roster.pre(tool_name='delegate_task', args=args, **ids)
        for child in children:
            native_start(native_source, ctx, parent, child, child._subagent_id)
            _register_child(child, parent, 'PRIVATE_GOAL', owner_session_id='fixture-owner',
                            owner_transport=object(), owner_session_record=object())
        roster.post(tool_name='delegate_task', args=args, result=_dispatched_payload(batch, explicit), **ids)
        rows = roster.list({'session_id':'root'}, session_id='root')['rows']
        live = [{**{key:item.get(key) for key in _SUBAGENT_SNAPSHOT_FIELDS},
                 'child_session_id':_child_session_id(item)} for item in list_active_subagents()
                if item.get('subagent_id') in {child._subagent_id for child in children}]
        assert len(rows) == len(live) == 2
        assert [row['async_unit_id'] for row in rows] == units
        assert all(row['native_call_delegation_id']=='contract-call' for row in rows)
        assert all(item['delegation_id']=='contract-call' for item in live)
        assert 'PRIVATE_' not in json.dumps(rows)
    finally:
        for child in children:
            _unregister_subagent(child._subagent_id)

