import json
import sqlite3
import threading
import time

import pytest
import hermes_constants
from model_router.delegation_reports import DelegationRouteReports
from model_router.execution_roster import register_execution_roster


# The core's async-delegation ledger shape (columns this adapter reads plus the
# surrounding NOT NULL columns, so the fixture matches a real state.db).
_SCHEMA = """CREATE TABLE async_delegations (
    delegation_id TEXT PRIMARY KEY,
    origin_session TEXT NOT NULL,
    origin_ui_session_id TEXT NOT NULL DEFAULT '',
    parent_session_id TEXT,
    state TEXT NOT NULL,
    dispatched_at REAL NOT NULL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    event_json TEXT,
    result_json TEXT,
    delivery_state TEXT NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at REAL,
    owner_pid INTEGER,
    owner_started_at INTEGER,
    task_json TEXT,
    origin_session_id TEXT NOT NULL DEFAULT ''
)"""

ROUTE = {'backend': 'model-router-auto', 'label': 'profile:claire', 'provider': 'nous',
         'model': 'qwen/qwen4-max:free', 'reasoning_effort': 'high', 'service_tier': 'normal'}


def entry(task_index=0, status='completed', route=ROUTE, model='qwen/qwen4-max:free', short='sa-0-42a7cfcf'):
    value = {'task_index': task_index, 'status': status, 'api_calls': 11, 'duration_seconds': 144.51,
             'summary': 'PRIVATE_SUMMARY_TEXT ' * 40, 'tool_trace': [{'tool': 'terminal'}],
             'tokens': {'input': 320840, 'output': 3609}}
    if route is not None:
        value['route'] = route
    if model is not None:
        value['model'] = model
    if short is not None:
        value['subagent_id'] = short
    return value


def ledger(home, unit='deleg_9b8c23bb', parent='segment-1', state='completed', results=None, result_json=None):
    home.mkdir(parents=True, exist_ok=True)
    path = home / 'state.db'
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA.replace('CREATE TABLE', 'CREATE TABLE IF NOT EXISTS', 1))
    if result_json is None:
        result_json = json.dumps({'results': results if results is not None else [entry()],
                                  'total_duration_seconds': 145.83, 'delegation_id': unit})
    conn.execute("INSERT OR REPLACE INTO async_delegations (delegation_id, origin_session, parent_session_id, state, dispatched_at, updated_at, result_json) VALUES (?,?,?,?,?,?,?)",
                 (unit, 'agent:main:local:dm:' + (parent or ''), parent, state, 1.0, 2.0, result_json))
    conn.commit()
    conn.close()
    return path


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


def dispatched_profile_child(r, *, automatic=True):
    """The screenshot lifecycle: an async profile delegation whose API calls this origin never sees."""
    task = {'profile': 'claire'}
    if automatic:
        task['execution'] = 'profile'
    args = {'tasks': [task]}
    pre(r, args)
    r.start(parent_session_id='segment-1', child_session_id='child-session', child_subagent_id='sa-0-42a7cfcf')
    post(r, {'status': 'dispatched', 'delegation_id': 'deleg_9b8c23bb', 'subagent_ids': ['sa-0-42a7cfcf']}, args)
    r.stop(parent_session_id='segment-1', child_session_id='child-session', child_status='completed', duration_ms=144510)


# --- adapter ---------------------------------------------------------------

def test_report_adopts_exact_unit_task_parent(tmp_path):
    home = tmp_path / 'home'
    ledger(home)
    with DelegationRouteReports(home) as reports:
        report = reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1', short='sa-0-42a7cfcf')
    assert report == {'route': {'backend': 'model-router-auto', 'label': 'profile:claire',
                                'model': 'qwen/qwen4-max:free', 'provider': 'nous'},
                      'model': 'qwen/qwen4-max:free'}
    # Scalars only: no summary, tool trace, tokens or whole record escapes.
    assert set(report) == {'route', 'model'}
    assert set(report['route']) == {'backend', 'label', 'model', 'provider'}


def test_partial_running_unit_adopts_finished_entry(tmp_path):
    home = tmp_path / 'home'
    ledger(home, state='running', result_json=json.dumps({'results': [entry()], 'partial': True}))
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1')['route']['model'] == 'qwen/qwen4-max:free'


def test_wrong_parent_unit_task_or_short_rejected(tmp_path):
    home = tmp_path / 'home'
    ledger(home)
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='other-session') is None
        assert reports.report(unit='deleg-other', task_index=0, parent='segment-1') is None
        assert reports.report(unit='deleg_9b8c23bb', task_index=1, parent='segment-1') is None
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1', short='sa-0-other') is None
        # Either side missing a short id keeps the exact unit/task/parent binding.
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is not None


def test_missing_short_on_entry_still_binds(tmp_path):
    home = tmp_path / 'home'
    ledger(home, results=[entry(short=None)])
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1', short='sa-0-42a7cfcf') is not None


def test_non_terminal_or_duplicate_entries_rejected(tmp_path):
    home = tmp_path / 'home'
    ledger(home, results=[entry(status='running')])
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None
    ledger(home, unit='deleg-dup', results=[entry(), entry()])
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg-dup', task_index=0, parent='segment-1') is None


def test_malformed_ledger_stays_unknown(tmp_path):
    home = tmp_path / 'home'
    for bad in ['{oops', '[]', '"text"', 'null', json.dumps({'results': {'0': entry()}}),
                json.dumps({'results': 'x'}), json.dumps({})]:
        ledger(home, unit='deleg-bad', result_json=bad)
        with DelegationRouteReports(home) as reports:
            assert reports.report(unit='deleg-bad', task_index=0, parent='segment-1') is None


def test_oversized_or_overfull_result_rejected(tmp_path):
    home = tmp_path / 'home'
    padding = 'x' * 2_100_000
    ledger(home, unit='deleg-big', results=[entry(), {'task_index': 9, 'padding': padding}])
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg-big', task_index=0, parent='segment-1') is None
    ledger(home, unit='deleg-many', results=[entry(task_index=i, short=f'sa-{i}') for i in range(129)])
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg-many', task_index=0, parent='segment-1') is None


def test_entry_model_fallback_and_route_model_priority(tmp_path):
    home = tmp_path / 'home'
    ledger(home, unit='deleg-fallback', results=[entry(route={**ROUTE, 'model': None})])
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg-fallback', task_index=0, parent='segment-1')['route']['model'] is None
    ledger(home, unit='deleg-final', results=[entry(route={**ROUTE, 'model': 'spare/model'}, model='qwen/qwen4-max:free')])
    with DelegationRouteReports(home) as reports:
        report = reports.report(unit='deleg-final', task_index=0, parent='segment-1')
    assert report['route']['model'] == 'spare/model' and report['model'] == 'qwen/qwen4-max:free'


def test_missing_or_unreadable_db_never_writes_body(tmp_path):
    # Scope: the DB body is never written. A non-database sentinel is not opened
    # as SQLite at all; WAL sidecar behavior on a REAL database is covered by
    # test_wal_read_never_modifies_the_database_body.
    home = tmp_path / 'home'
    home.mkdir()
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None
    assert not (home / 'state.db').exists()
    sentinel = b'PRIVATE_UNREADABLE_SENTINEL'
    (home / 'state.db').write_bytes(sentinel)
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None
    assert (home / 'state.db').read_bytes() == sentinel
    assert not (home / 'state.db-shm').exists() and not (home / 'state.db-wal').exists()


def test_missing_table_stays_unknown(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    conn = sqlite3.connect(home / 'state.db')
    conn.execute('CREATE TABLE unrelated (id TEXT)')
    conn.commit()
    conn.close()
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None


def test_symlink_home_refused(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    ledger(home)
    monkeypatch.setattr('pathlib.Path.is_symlink', lambda self: True)
    with DelegationRouteReports(home) as reports:
        assert reports.conn is None
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None


def test_invalid_task_index_types_rejected(tmp_path):
    home = tmp_path / 'home'
    ledger(home)
    with DelegationRouteReports(home) as reports:
        for bad in ['0', 0.0, -1, None, True]:
            assert reports.report(unit='deleg_9b8c23bb', task_index=bad, parent='segment-1') is None


# --- roster integration ----------------------------------------------------

@pytest.mark.parametrize('backend,label', [('model-router-auto', 'profile:claire'), ('model-router-profiles', 'claire')])
def test_async_profile_row_adopts_stored_route_report(env, backend, label):
    r, _, home = env
    dispatched_profile_child(r, automatic=backend == 'model-router-auto')
    assert rows(r)[0]['observed']['evidence'] == 'unknown'  # dispatch carries only ids
    ledger(home, results=[entry(route={**ROUTE, 'backend': backend, 'label': label})])
    row = rows(r)[0]
    assert row['status'] == 'completed'
    assert row['observed'] == {'kind': 'profile', 'slot': None, 'profile': 'claire', 'backend': backend,
                               'model': 'qwen/qwen4-max:free', 'provider': 'nous', 'evidence': 'runtime_reported'}
    # The stored report is route evidence, never the child's own API-hook observation.
    assert row.get('model') is None and row.get('provider') is None
    assert row['requested'] == {'kind': 'profile', 'profile': 'claire', 'purpose': None, 'slot': None}


def test_adopted_report_is_stable_and_not_requeried(env, monkeypatch):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home)
    assert rows(r)[0]['observed']['model'] == 'qwen/qwen4-max:free'
    calls = []
    original = DelegationRouteReports.report
    def spy(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)
    monkeypatch.setattr(DelegationRouteReports, 'report', spy)
    assert rows(r)[0]['observed']['model'] == 'qwen/qwen4-max:free'
    assert calls == []


def test_api_hook_model_is_not_replaced_by_stored_report(env):
    r, _, home = env
    args = {'tasks': [{'execution': 'model', 'purpose': 'implementation'}]}
    pre(r, args)
    r.start(parent_session_id='segment-1', child_session_id='child-session', child_subagent_id='sa-0-42a7cfcf')
    post(r, {'status': 'dispatched', 'delegation_id': 'deleg_9b8c23bb', 'subagent_ids': ['sa-0-42a7cfcf']}, args)
    r.api_pre(session_id='child-session', model='slot/model', provider='sub')
    r.stop(parent_session_id='segment-1', child_session_id='child-session', child_status='completed')
    ledger(home, results=[entry(route={**ROUTE, 'label': 'model:code-complex', 'model': 'other/model'})])
    row = rows(r)[0]
    assert row['model'] == 'slot/model' and row['provider'] == 'sub'
    assert row['observed']['evidence'] == 'unknown'  # live API evidence already answers; no stored read


def test_inline_observed_report_is_not_overwritten(env):
    r, _, home = env
    args = {'tasks': [{'execution': 'profile', 'profile': 'claire'}]}
    pre(r, args)
    inline = {'results': [{'task_index': 0, 'status': 'completed', 'subagent_id': 'sa-0-42a7cfcf',
                           'route': {**ROUTE, 'model': 'inline/model'}}]}
    post(r, inline, args)
    ledger(home)
    row = rows(r)[0]
    assert row['observed']['model'] == 'inline/model'


def test_foreign_parent_not_adopted_and_negative_cached(env):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home, parent='other-session')
    assert rows(r)[0]['observed']['evidence'] == 'unknown'
    assert ('deleg_9b8c23bb', 0) in r._route_negative


def test_unbound_or_model_rows_never_open_the_ledger(env, monkeypatch):
    r, _, home = env
    (home / 'state.db').write_bytes(b'PRIVATE_UNREADABLE_SENTINEL')
    opens = []
    original_enter = DelegationRouteReports.__enter__
    def spy(self):
        opens.append(1)
        return original_enter(self)
    monkeypatch.setattr(DelegationRouteReports, '__enter__', spy)
    pre(r, {'tasks': [{'execution': 'profile', 'profile': 'claire'}]})  # requested only, no delegation id
    assert rows(r)[0]['status'] == 'requested'
    assert opens == []
    assert (home / 'state.db').read_bytes() == b'PRIVATE_UNREADABLE_SENTINEL'


def test_invalid_backend_or_model_stays_unknown(env):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home, results=[entry(route={**ROUTE, 'backend': 'default'})])
    assert rows(r)[0]['observed']['evidence'] == 'unknown'
    # A rejected stored report is final: the unit is negative-cached, not re-read.
    assert ('deleg_9b8c23bb', 0) in r._route_negative
    from model_router.execution_roster import _observed
    assert _observed({'route': {**ROUTE, 'model': '../evil'}})['model'] is None


def test_missing_ledger_keeps_previous_behavior(env):
    r, _, home = env
    dispatched_profile_child(r)
    row = rows(r)[0]
    assert row['status'] == 'completed' and row['observed']['evidence'] == 'unknown'
    assert not (home / 'state.db').exists()


def test_continuation_row_adopts_its_own_units_report(env):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home)
    assert rows(r)[0]['observed']['model'] == 'qwen/qwen4-max:free'
    # Continue the finished child: a new row with its own delegation unit.
    args = {'action': 'continue', 'subagent_id': 'sa-0-42a7cfcf', 'message': 'more'}
    pre(r, args, tool_call_id='call-2')
    post(r, {'status': 'dispatched', 'delegation_id': 'deleg-cont', 'subagent_ids': ['sa-0-42a7cfcf']}, args, tool_call_id='call-2')
    r.start(parent_session_id='segment-1', child_session_id='child-session-2', child_subagent_id='sa-0-42a7cfcf')
    r.stop(parent_session_id='segment-1', child_session_id='child-session-2', child_status='completed')
    ledger(home, unit='deleg-cont', results=[entry(route={**ROUTE, 'model': 'cont/model'}, model='cont/model')])
    by_unit = {row['delegation_id']: row for row in rows(r)}
    assert by_unit['deleg_9b8c23bb']['observed']['model'] == 'qwen/qwen4-max:free'
    assert by_unit['deleg-cont']['observed']['model'] == 'cont/model'


# --- review regressions: lock hold, starvation, strict types, WAL ----------

def test_stringified_results_and_non_integer_task_index_rejected(tmp_path):
    home = tmp_path / 'home'
    ledger(home, unit='deleg-str', result_json=json.dumps({'results': json.dumps([entry()])}))
    ledger(home, unit='deleg-real', results=[{**entry(), 'task_index': 0.0}])
    ledger(home, unit='deleg-bool', results=[{**entry(), 'task_index': True}])
    with DelegationRouteReports(home) as reports:
        for unit in ('deleg-str', 'deleg-real', 'deleg-bool'):
            assert reports.report(unit=unit, task_index=0, parent='segment-1') is None


def test_non_object_results_element_is_skipped_not_fatal(tmp_path):
    home = tmp_path / 'home'
    # A corrupt non-object element beside a valid entry: the valid one is adopted and the
    # snapshot stays open (the CASE object-guard avoids a malformed-JSON abort).
    ledger(home, unit='deleg-mixed', result_json=json.dumps({'results': ['corrupt-string', entry()]}))
    with DelegationRouteReports(home) as reports:
        rep = reports.report(unit='deleg-mixed', task_index=0, parent='segment-1')
        assert rep is not None and rep['route']['model'] == 'qwen/qwen4-max:free'
        assert reports.conn is not None
        assert reports.unit_state(unit='deleg-mixed', parent='segment-1') == 'completed'
    ledger(home, unit='deleg-onlystr', result_json=json.dumps({'results': ['just-a-string']}))
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg-onlystr', task_index=0, parent='segment-1') is None
        assert reports.conn is not None  # fail closed, not a fatal snapshot close


def test_wal_read_never_modifies_the_database_body(tmp_path):
    home = tmp_path / 'home'
    ledger(home)
    conn = sqlite3.connect(home / 'state.db')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.close()
    body = (home / 'state.db').read_bytes()
    with DelegationRouteReports(home) as reports:
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1')['route']['model'] == 'qwen/qwen4-max:free'
    assert (home / 'state.db').read_bytes() == body
    # -shm/-wal sidecars may appear when no other connection holds a WAL DB;
    # that is not a write to the database body (asserted above).


def test_busy_error_closes_connection_for_remaining_lookups(tmp_path):
    home = tmp_path / 'home'
    ledger(home)
    ledger(home, unit='deleg-second')
    blocker = sqlite3.connect(home / 'state.db')
    blocker.execute('BEGIN EXCLUSIVE')
    try:
        with DelegationRouteReports(home) as reports:
            assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None
            assert reports.conn is None  # first busy error closed the snapshot
            start = time.monotonic()
            assert reports.report(unit='deleg-second', task_index=0, parent='segment-1') is None
            assert reports.unit_state(unit='deleg-second', parent='segment-1') is None
            assert time.monotonic() - start < 0.05  # no further lock waits
    finally:
        blocker.rollback()
        blocker.close()


def test_elapsed_deadline_stops_lookups_without_sqlite(tmp_path):
    home = tmp_path / 'home'
    ledger(home)
    with DelegationRouteReports(home) as reports:
        reports._deadline = time.monotonic() - 1
        assert reports.report(unit='deleg_9b8c23bb', task_index=0, parent='segment-1') is None
        assert reports.unit_state(unit='deleg_9b8c23bb', parent='segment-1') is None
        assert reports.conn is not None  # the deadline stops reads; it need not close


def test_locked_ledger_fails_fast_and_stays_retryable(env):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home)
    blocker = sqlite3.connect(home / 'state.db')
    blocker.execute('BEGIN EXCLUSIVE')
    try:
        start = time.monotonic()
        row = rows(r)[0]
        elapsed = time.monotonic() - start
        assert elapsed < 1.5, f'list() held up {elapsed:.2f}s behind an exclusive ledger lock'
        assert row['status'] == 'completed' and row['observed']['evidence'] == 'unknown'
        # Unreadable is NOT unresolvable: no negative cache, retry after unlock.
        assert ('deleg_9b8c23bb', 0) not in r._route_negative
    finally:
        blocker.rollback()
        blocker.close()
    assert rows(r)[0]['observed']['model'] == 'qwen/qwen4-max:free'


def test_ledger_reads_do_not_hold_the_hook_lock(env, monkeypatch):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home)
    entered, release = threading.Event(), threading.Event()
    original = DelegationRouteReports.report
    def slow(self, **kwargs):
        entered.set()
        release.wait(5)
        return original(self, **kwargs)
    monkeypatch.setattr(DelegationRouteReports, 'report', slow)
    result = {}
    def reader():
        result['rows'] = rows(r)
    t = threading.Thread(target=reader)
    t.start()
    try:
        assert entered.wait(2)
        start = time.monotonic()
        # A hook sharing self.lock must proceed while the ledger read is blocked.
        r.stop(parent_session_id='segment-1', child_session_id='unknown-session', child_status='completed')
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f'hook blocked {elapsed:.2f}s behind a ledger read'
    finally:
        release.set()
        t.join(5)
    assert result['rows'][0]['observed']['model'] == 'qwen/qwen4-max:free'


def test_newest_first_and_negative_cache_prevent_starvation(env, monkeypatch):
    r, _, home = env
    args = {'tasks': [{'execution': 'profile', 'profile': 'claire'}]}
    for i in range(41):
        pre(r, args, tool_call_id=f'call-{i}')
        post(r, {'status': 'dispatched', 'delegation_id': f'deleg-{i}', 'subagent_ids': [f'sa-{i}']}, args, tool_call_id=f'call-{i}')
    for row in r.rows.values():  # deterministic recency: deleg-40 is the newest
        row['updated_at'] = float(row['delegation_id'].split('-')[1])
    ledger(home, unit='deleg-40', results=[entry(short='sa-40')])
    opens = []
    original_enter = DelegationRouteReports.__enter__
    def spy(self):
        opens.append(1)
        return original_enter(self)
    monkeypatch.setattr(DelegationRouteReports, '__enter__', spy)
    by_unit = {row['delegation_id']: row for row in rows(r)}
    assert by_unit['deleg-40']['observed']['model'] == 'qwen/qwen4-max:free'
    assert len(opens) == 1
    rows(r)  # the remaining old rows are negative-cached (absent units)
    assert len(r._route_negative) == 40
    rows(r)  # nothing left to read: the ledger is not opened again
    assert len(opens) == 2


def test_running_unit_stays_retryable_until_its_report_lands(env):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home, state='running', result_json='null')
    assert rows(r)[0]['observed']['evidence'] == 'unknown'
    assert ('deleg_9b8c23bb', 0) not in r._route_negative
    ledger(home)  # the unit completes and the stored report lands
    assert rows(r)[0]['observed']['model'] == 'qwen/qwen4-max:free'


def test_report_still_binds_after_parent_compaction_alias(env):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home)
    r.compact(session_id='segment-2', old_session_id='segment-1')
    row = rows(r, sid='segment-2')[0]
    assert row['observed']['model'] == 'qwen/qwen4-max:free'


def test_unexpected_adapter_error_never_empties_the_roster(env, monkeypatch):
    r, _, home = env
    dispatched_profile_child(r)
    ledger(home)
    def boom(self):
        raise RuntimeError('unexpected adapter failure')
    monkeypatch.setattr(DelegationRouteReports, '__enter__', boom)
    out = rows(r)
    assert len(out) == 1 and out[0]['status'] == 'completed'
    assert out[0]['observed']['evidence'] == 'unknown'
