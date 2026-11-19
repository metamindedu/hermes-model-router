"""Fail-closed, read-only projection of this origin's stored delegation route reports.

A version-tolerant SQLite-format adapter, not a new native authority API. An
async dispatch hands the parent only ids; the per-task route report (the
backend/label/model/provider the child actually ran on) is written to the
origin's async-delegation ledger when that child finishes. Profile-routed
children converse as their target profile, so this origin's API hooks never
observe their calls and the stored report is the only origin-local model
evidence. Only scalar route metadata of an already hook-bound unit/task is
selected: no task, result, summary or transcript text, no whole JSON record,
and no other profile's home is read. Missing or malformed formats stay unknown.

The database body is never modified. Opening a WAL database read-only may
create -shm/-wal sidecar files when no other connection holds the database;
in normal operation the core already holds it. A busy/locked database closes
the connection on the first error so remaining lookups fail fast instead of
waiting, and every lookup also checks the open deadline in Python (SQLite's
progress handler alone does not bound lock waits or short statements).
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import time

_MAX_JSON = 2_000_000
_MAX_ENTRIES = 128
# The core's terminal entry vocabulary; a route report is assembled when the
# child's result is assembled, never for a still-running entry.
_TERMINAL = {'completed', 'failed', 'error', 'interrupted', 'cancelled', 'timeout'}

# One primary-key lookup; json_each filters the stored entries to the exact
# task index and json_extract keeps scalars only. Path-argument json_type /
# json_each forms reject a stringified array; the CASE object-guard skips
# non-object elements without a malformed-JSON error, and the integer-type
# guard rejects real/boolean task indexes. Duplicate task indexes or a
# non-array, oversized or malformed result never adopt (fail closed).
_REPORT = """SELECT json_extract(j.value,'$.status') AS status,
    json_extract(j.value,'$.subagent_id') AS subagent_id,
    json_extract(j.value,'$.task_index') AS task_index,
    json_extract(j.value,'$.route.backend') AS backend,
    json_extract(j.value,'$.route.label') AS label,
    json_extract(j.value,'$.route.model') AS route_model,
    json_extract(j.value,'$.route.provider') AS route_provider,
    json_extract(j.value,'$.model') AS entry_model
    FROM async_delegations, json_each(result_json,'$.results') AS j
    WHERE delegation_id=? AND parent_session_id=?
    AND length(COALESCE(result_json,''))<=? AND json_valid(COALESCE(result_json,'{}'))
    AND json_type(COALESCE(result_json,'{}'))='object'
    AND json_type(result_json,'$.results')='array'
    AND (SELECT COUNT(*) FROM json_each(result_json,'$.results'))<=?
    AND CASE WHEN j.type='object' THEN json_type(j.value,'$.task_index') END='integer'
    AND json_extract(j.value,'$.task_index')=?
    LIMIT 2"""

_STATE = """SELECT state FROM async_delegations
    WHERE delegation_id=? AND parent_session_id=?"""


class DelegationRouteReports:
    """A bounded snapshot; constructor/open never creates a missing database."""

    def __init__(self, home):
        self.home = Path(home)
        self.conn = None
        self._deadline = 0.0

    def __enter__(self):
        path = self.home / 'state.db'
        try:
            # The home is fixed by the original registration context, not RPC
            # parameters. Refuse a later path substitution/reparse point too.
            if (self.home.is_symlink() or path.is_symlink() or not path.is_file()
                    or path.resolve().parent != self.home
                    or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
                return self
            self.conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.05)
            self.conn.row_factory = sqlite3.Row
            self._deadline = time.monotonic() + .15
            self.conn.set_progress_handler(lambda: int(time.monotonic() > self._deadline), 1000)
            self.conn.execute('PRAGMA query_only=ON')
            self.conn.execute('BEGIN')
        except (OSError, ValueError, sqlite3.Error):
            self.__exit__(None, None, None)
        return self

    def __exit__(self, *args):
        if self.conn is not None:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
            self.conn = None

    def report(self, *, unit, task_index, parent, short=None):
        """The stored completion route report of one exact task, or None.

        ``unit``/``parent``/``task_index`` come from an existing hook/dispatch
        binding, never from user input. Only a terminal entry of that exact
        unit and parent is adopted; when both sides name a subagent id they
        must agree. The returned dict carries only the scalar route fields the
        roster's ``_observed`` validator already accepts. Any SQLite error
        (busy/locked included) closes the connection: remaining lookups in
        this snapshot return None immediately instead of waiting.
        """
        # Python-side deadline check: the progress handler is not called for
        # short statements and never interrupts a lock wait.
        if self.conn is None or time.monotonic() > self._deadline or type(task_index) is not int or task_index < 0:
            return None
        try:
            items = self.conn.execute(_REPORT, (unit, parent, _MAX_JSON, _MAX_ENTRIES, task_index)).fetchall()
            if len(items) != 1:
                return None
            item = items[0]
            if item['status'] not in _TERMINAL or item['task_index'] != task_index:
                return None
            stored_short = item['subagent_id']
            if short is not None and stored_short is not None and stored_short != short:
                return None
            return {'route': {'backend': item['backend'], 'label': item['label'],
                              'model': item['route_model'], 'provider': item['route_provider']},
                    'model': item['entry_model']}
        except sqlite3.Error:
            self.__exit__(None, None, None)
            return None

    def unit_state(self, *, unit, parent):
        """The ledger state of one exact unit: a state string, ``'absent'`` when
        the lookup ran and found no row, or None when unreadable. The roster
        uses this to stop re-reading rows whose unit can never produce a route
        report (pruned or finished without one); ``'running'`` units may still
        receive partial reports and stay retryable."""
        if self.conn is None or time.monotonic() > self._deadline:
            return None
        try:
            item = self.conn.execute(_STATE, (unit, parent)).fetchone()
            return item['state'] if item is not None else 'absent'
        except sqlite3.Error:
            self.__exit__(None, None, None)
            return None
