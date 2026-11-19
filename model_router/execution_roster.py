"""Passive, in-memory metadata observer for native delegate_task calls.

No task text or result text is retained. Runtime reports are not response verification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from .delegation_reports import DelegationRouteReports
from .slots import PURPOSE_SLOTS

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z", re.ASCII)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+/-]{0,127}(?:\[[A-Za-z0-9._-]{1,32}\])?\Z", re.ASCII)
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z", re.ASCII)
_PURPOSES = {'implementation': 'light', 'mechanical': 'light', 'preliminary-review': 'light',
             'plan': 'heavy', 'semantic-final': 'heavy', 'independent-review': 'heavy', 'computer-use': 'light'}
_BACKENDS = {'model-router', 'model-router-auto', 'model-router-profiles'}


# input = uncached prompt; cache_read/cache_write = cached prompt; output includes reasoning where the
# provider counts it there.
_TOKEN_BUCKETS = ('input', 'cache_read', 'cache_write', 'output')

# Stored route-report lookups per roster read, newest rows first; permanently
# unresolvable units are negative-cached so the cap cannot starve recent work.
_MAX_STORED_ROUTE_LOOKUPS = 32
_MAX_ROUTE_NEGATIVE = 256


def _safe(value):
    return value if isinstance(value, str) and '..' not in value and _SAFE.fullmatch(value) else None


def _requested(task):
    task = task if isinstance(task, dict) else {}
    raw_purpose = task.get('purpose')
    purpose = raw_purpose if isinstance(raw_purpose, str) and raw_purpose in _PURPOSES else None
    profile = task.get('profile')
    profile = profile if isinstance(profile, str) and _PROFILE.fullmatch(profile) else None
    execution = task.get('execution')
    kind = 'unknown'
    if execution in (None, 'model') and purpose and 'profile' not in task:
        kind = 'model'
    elif execution in (None, 'profile') and profile and 'purpose' not in task:
        kind = 'profile'
    return {'kind': kind, 'role': _PURPOSES[purpose] if kind == 'model' and purpose else None,
            'profile': profile if kind == 'profile' else None, 'purpose': purpose if kind == 'model' else None,
            'slot': PURPOSE_SLOTS[purpose] if kind == 'model' and purpose else None}


def _observed(entry):
    out = {'kind': 'unknown', 'role': None, 'profile': None, 'backend': None,
           'model': None, 'provider': None, 'evidence': 'unknown'}
    route = entry.get('route')
    if not isinstance(route, dict) or route.get('backend') not in _BACKENDS:
        return out
    out['backend'] = route['backend']
    model = route.get('model') or entry.get('model')
    out['model'] = model if isinstance(model, str) and '..' not in model and _MODEL.fullmatch(model) else None
    out['provider'] = _safe(route.get('provider'))
    label = route.get('label')
    if label in ('model:heavy', 'model:light'):
        out['kind'], out['role'] = 'model', label[6:]
    elif isinstance(label, str) and label.startswith('profile:') and _PROFILE.fullmatch(label[8:]):
        out['kind'], out['profile'] = 'profile', label[8:]
    out['evidence'] = 'runtime_reported'
    return out


def _status(value):
    return {'completed': 'completed', 'failed': 'error', 'error': 'error',
            'refused': 'error', 'dispatched': 'dispatched', 'queued': 'queued', 'running': 'running',
            'interrupted': 'interrupted', 'cancelled': 'cancelled', 'timeout': 'timeout'}.get(value, 'unknown')


# 'ended': the run stopped but its outcome could not be attributed (see _resolve_stops). Desktop shows it
# as unknown unless the native roster reports the run.
_TERMINAL = {'completed', 'error', 'interrupted', 'cancelled', 'timeout', 'ended'}


def _set_status(row, status):
    if row['status'] not in _TERMINAL and status != 'unknown':
        row['status'] = status


# Plugin reload (``hermes plugins install --force``, ``reload-plugins``) unloads every hook, evicts the
# ``hermes_plugins.<slug>.*`` modules and calls register() again inside the SAME gateway process while
# native children keep running. The roster state therefore lives in a process-global holder under a
# stable, plugin-owned module name that the loader never evicts, keyed by the profile home. The newest
# registration owns it; an earlier instance becomes inert so a hook it still holds can never count
# twice. Only plain ids/counters/model ids are kept (never task or result text) and nothing is
# written to disk. A state of another schema, or one that fails validation, is discarded: rows then
# read as unknown rather than being attributed to the wrong run.
_HOLDER_MODULE = 'hermes_model_router_runtime_state'
_STATE_SCHEMA = 'execution-roster/1'
_HOLDER_LOCK = threading.Lock()
_ROW_KEYS = frozenset({'id', 'execution_mode', 'requested', 'observed', 'conversation_id', 'parent_session_id',
                       'tool_call_id', 'task_index', 'subagent_id', 'delegation_id', 'async_unit_id',
                       'native_call_delegation_id', 'status', 'updated_at'})
_CHILD_KEYS = frozenset({'parent', 'session', 'short', 'child_session_id', 'started_at', 'activity_at', 'status'})
_PENDING_KEYS = frozenset({'sid', 'parent', 'original', 'child_session'})
_STATUSES = frozenset({'requested', 'unknown', 'dispatched', 'queued', 'running'}) | _TERMINAL


def _empty_state():
    return {'rows': {}, 'children': {}, 'aliases': {}, 'continuing': {}}


def _row_key(key):
    return (isinstance(key, tuple) and len(key) == 4 and all(isinstance(k, str) for k in key[:3])
            and type(key[3]) is int)


def _valid_state(state):
    try:
        if not isinstance(state, dict) or set(state) != {'rows', 'children', 'aliases', 'continuing'}:
            return False
        rows, children, aliases, continuing = (state[k] for k in ('rows', 'children', 'aliases', 'continuing'))
        if not all(isinstance(x, dict) for x in (rows, children, aliases, continuing)):
            return False
        if len(rows) > 512 or len(children) > 512 or len(aliases) > 512 or len(continuing) > 128:
            return False
        for key, row in rows.items():
            if (not _row_key(key) or not isinstance(row, dict) or not _ROW_KEYS <= set(row)
                    or row['status'] not in _STATUSES or not isinstance(row['requested'], dict)
                    or row['requested'].get('kind') not in ('model', 'profile', 'unknown')
                    or not isinstance(row['observed'], dict) or 'evidence' not in row['observed']):
                return False
        for key, child in children.items():
            if (not isinstance(key, str) or not isinstance(child, dict) or not _CHILD_KEYS <= set(child)
                    or child['status'] not in _STATUSES):
                return False
            for field in ('tool_count', 'api_call_count'):
                if child.get(field) is not None and type(child[field]) is not int:
                    return False
            tokens = child.get('tokens')
            if tokens is not None and (not isinstance(tokens, dict) or set(tokens) != set(_TOKEN_BUCKETS)
                                       or any(type(v) is not int for v in tokens.values())):
                return False
            if not isinstance(child.get('models', []), list):
                return False
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in aliases.items()):
            return False
        return all(_row_key(k) and isinstance(p, dict) and set(p) == _PENDING_KEYS for k, p in continuing.items())
    except Exception:
        return False


def _holder():
    import sys
    import types
    with _HOLDER_LOCK:
        # _HOLDER_LOCK is recreated by every reload, so first creation must itself be atomic:
        # setdefault keeps whichever module/dict/lock a concurrent reload published first.
        candidate = types.ModuleType(_HOLDER_MODULE, 'Hermes Model Router in-process state (survives plugin reload).')
        module = sys.modules.setdefault(_HOLDER_MODULE, candidate)
        if not isinstance(module, types.ModuleType):
            sys.modules[_HOLDER_MODULE] = module = candidate
        # Another plugin version may share this module: each entry carries its schema and is re-validated.
        if not isinstance(module.__dict__.setdefault('execution_roster', {}), dict):
            module.__dict__['execution_roster'] = {}
        if not isinstance(module.__dict__.setdefault('lock', threading.RLock()), type(threading.RLock())):
            module.__dict__['lock'] = threading.RLock()
        return module


def _adopt_state(home, take_over):
    """Bind a new roster to the shared state of ``home``; ``take_over(entry)`` constructs it.

    Every earlier instance of this home is retired (inert) once the new one owns the entry."""
    module = _holder()
    key = os.path.normcase(str(Path(home).resolve(strict=False)))
    with module.lock:
        entry = module.execution_roster.get(key)
        compatible = (isinstance(entry, dict) and entry.get('schema') == _STATE_SCHEMA
                      and isinstance(entry.get('lock'), type(threading.RLock())))
        if compatible:
            # Wait for an in-flight hook of the previous instance before checking the state it mutates;
            # the new owner is installed while that lock is still held.
            with entry['lock']:
                if _valid_state(entry.get('state')):
                    roster = take_over(entry)
                    entry['owner'] = roster
                    return roster
        if isinstance(entry, dict):
            entry['owner'] = None  # retire the previous instance before its state is dropped
        entry = {'schema': _STATE_SCHEMA, 'lock': threading.RLock(), 'state': _empty_state()}
        roster = take_over(entry)
        entry['owner'] = roster
        module.execution_roster[key] = entry
        return roster


class ExecutionRoster:
    def __init__(self, ctx, home, *, shared=None):
        from hermes_constants import profile_name_for_home
        self.ctx = ctx
        self.home = Path(home).resolve(strict=False)
        self.origin_profile = _safe(profile_name_for_home(self.home))
        # ``shared`` is the process-global entry (register_execution_roster); a bare construction keeps
        # private state and is always live.
        self._shared = shared
        state = shared['state'] if shared is not None else _empty_state()
        self.rows = state['rows']
        self.children = state['children']
        self.aliases = state['aliases']
        # action='continue' rebuilds a finished child under the same subagent_id AND session id.
        # new row key -> {sid, parent, original, child_session}, until its subagent_start or a refusal.
        self.continuing = state['continuing']
        self.lock = shared['lock'] if shared is not None else threading.RLock()
        self.rpc_supported = False
        # The unadmitted research adapter (execution_metadata) is never imported
        # here; disposable prototype fixtures may inject a factory explicitly.
        # Separately, list() reads scalar route reports from THIS origin's
        # async-delegation ledger for already hook-bound rows (delegation_reports):
        # read-only, fail-closed, outside the hook lock. See PLAN.md / SECURITY.md.
        self._metadata_factory: Callable[[Path], Any] | None = None
        # Per-instance optimization only (not shared holder state): units that can
        # never produce a route report are not re-read on every poll.
        self._route_negative: OrderedDict = OrderedDict()

    def _live(self):
        # A reload registers a new instance on the same shared state; this one then stays inert.
        return self._shared is None or self._shared.get('owner') is self

    def _owner(self):
        from hermes_constants import get_hermes_home
        if not self._live():
            return False
        return os.path.normcase(str(Path(get_hermes_home()).resolve(strict=False))) == os.path.normcase(str(self.home))

    def _event(self, root, session):
        emit = getattr(self.ctx, 'emit_to_session', None)
        if callable(emit):
            for sid in {root, session}:
                try:
                    emit(sid, 'execution.changed', {'schema': 1})
                except Exception:
                    pass

    def _same_session(self, a, b):
        def canonical(s):
            seen = set()
            while s in self.aliases and s not in seen:
                seen.add(s)
                s = self.aliases[s]
            return s
        return bool(a and b and canonical(a) == canonical(b))

    def _child(self, session):
        matches = [c for c in self.children.values() if self._same_session(c['session'], session)]
        if any(c.get('ambiguous') for c in matches):
            return None
        return matches[0] if len(matches) == 1 else None

    def _reconcile(self, selected=None):
        # Activity ticks touch one child; do not rescan every finished child on
        # every tool/API call as the bounded history fills up.
        for child in ([selected] if selected is not None else self.children.values()):
            # A continued row keeps the values of its own run. A continuation row binds only to the
            # run its own subagent_start began (run_for), never to the previous run's counters.
            matches = [r for r in self.rows.values() if r['subagent_id'] == child['short']
                       and r['delegation_id'] and not r.get('continued_by')
                       and (not r.get('continued_from') or child.get('run_for') == r['id'])
                       and self._same_session(r['parent_session_id'], child['parent'])]
            siblings = [c for c in self.children.values() if c['short'] == child['short']
                        and self._same_session(c['parent'], child['parent'])]
            if len(matches) != 1 or len(siblings) != 1 or child.get('ambiguous'):
                continue
            row = matches[0]
            if row.get('child_session_id') and not self._same_session(row['child_session_id'], child['session']):
                continue
            self._copy_child(row, child)

    @staticmethod
    def _copy_child(row, child):
        for field in ('child_session_id', 'started_at', 'activity_at', 'last_tool', 'tool_count',
                      'api_call_count', 'duration_seconds', 'model', 'provider'):
            if field in child:
                row[field] = child[field]
        if child.get('tokens'):
            row['tokens'] = dict(child['tokens'])
        if child.get('models'):
            row['models'] = copy.deepcopy(child['models'])
            row['models_truncated'] = bool(child.get('models_truncated'))
        _set_status(row, child.get('status', 'dispatched'))
        row['updated_at'] = time.time()

    def _restart_for_continuation(self, child, session, parent, short):
        # Core rebuilds a continued child under its subagent_id and its (possibly compacted) session.
        pending = [key for key, p in self.continuing.items() if p['sid'] == short
                   and self._same_session(p['parent'], parent)
                   and (p['child_session'] is None or self._same_session(p['child_session'], session))]
        if len(pending) != 1 or pending[0] not in self.rows:
            return
        p = self.continuing.pop(pending[0])
        original = next((r for r in self.rows.values() if r['id'] == p['original']), None)
        if original is not None and not (original.get('child_session_id') and
                                         not self._same_session(original['child_session_id'], child['session'])):
            self._copy_child(original, child)  # the previous run's final values stay with its row
        # Core continues only a finished child, so a stop not yet observed belongs to an earlier run
        # (grouped batch stops wait for siblings). Earlier unsettled runs and stops that arrived before
        # this restart carry over; every held stop predates this run, so none of them is this run's.
        earlier = list(child.get('earlier_runs', []))
        held = [dict(h, earlier=True) for h in child.get('held_stops', [])]
        if child.get('status') not in _TERMINAL and original is not None:
            earlier.append(original['id'])
        now = time.time()
        kept = {key: child[key] for key in ('parent', 'session', 'short')}
        child.clear()
        child.update(kept, child_session_id=session, started_at=now, activity_at=now, tool_count=None,
                     api_call_count=None, status='queued', run_for=self.rows[pending[0]]['id'],
                     run_monotonic=time.monotonic())
        if earlier:
            child['earlier_runs'] = earlier[-16:]
            child['held_stops'] = held[-17:]
            self._resolve_stops(child)

    def start(self, parent_session_id=None, child_session_id=None, child_subagent_id=None, **kwargs):
        try:
            parent, session, short = map(_safe, (parent_session_id, child_session_id, child_subagent_id))
            if not self._owner() or not all((parent, session, short)):
                return None
            with self.lock:
                existing = self.children.get(session)
                if existing is None and self.continuing:
                    existing = self._child(session)  # a continuation may restart on a compacted session id
                if existing is None:
                    now = time.time()
                    self.children[session] = {'parent': parent, 'session': session, 'short': short,
                                              'child_session_id': session, 'started_at': now,
                                              'activity_at': now, 'tool_count': None, 'api_call_count': None,
                                              'status': 'queued'}
                    while len(self.children) > 512:
                        self.children.pop(next(iter(self.children)))
                elif existing['short'] != short or not self._same_session(existing['parent'], parent):
                    existing['ambiguous'] = True
                elif not existing.get('ambiguous'):
                    self._restart_for_continuation(existing, session, parent, short)
                self._reconcile()
                self._notify_parent(parent)
        except Exception:
            pass
        return None

    def _notify_parent(self, parent):
        for row in self.rows.values():
            if self._same_session(row['parent_session_id'], parent):
                self._event(row['conversation_id'], parent)
                for alias in self.aliases:
                    if self._same_session(alias, parent):
                        self._event(row['conversation_id'], alias)
                break

    def _bind_stored_session(self, child, session):
        """Use ONLY after the origin DB proves this child's compression chain."""
        if not _safe(session):
            return False
        if not self._same_session(child['session'], session):
            # Do not let a stored alias merge independent children or a parent
            # conversation, even when malformed metadata names that same id.
            if session in self.aliases or any(
                    other is not child and self._same_session(other['session'], session)
                    for other in self.children.values()):
                return False
            if any(self._same_session(session, x) for row in self.rows.values()
                   for x in (row['parent_session_id'], row['conversation_id'])):
                return False
            self.aliases[session] = child['session']
            while len(self.aliases) > 512:
                self.aliases.pop(next(iter(self.aliases)))
        child['child_session_id'] = session
        return True

    def _stored_child(self, parent, session):
        if self._metadata_factory is None:
            return None
        candidates = [c for c in self.children.values()
                      if not c.get('ambiguous') and self._same_session(c['parent'], parent)]
        with self._metadata_factory(self.home) as metadata:
            matches = [c for c in candidates
                       if metadata.lineage(c['session'], session, c['parent'], c['short'])]
        if len(matches) == 1 and self._bind_stored_session(matches[0], session):
            return matches[0]
        return None

    def _refresh_stored_terminal(self, rows):
        # Native grouped stop hooks wait for every sibling; native per-child
        # cleanup records settle earlier. Read only exact already-bound rows.
        if self._metadata_factory is None:
            return
        with self._metadata_factory(self.home) as metadata:
            for row in rows:
                if row['status'] in _TERMINAL or not row.get('delegation_id'):
                    continue
                child = self._child(row.get('child_session_id'))
                if not child or not self._same_session(child['parent'], row['parent_session_id']):
                    continue
                terminal = metadata.terminal(short=child['short'], unit=row['delegation_id'],
                    parent=child['parent'], original=child['session'], started_at=child['started_at'])
                if terminal and self._bind_stored_session(child, terminal['session_id']):
                    child['status'] = _status(terminal['status'])
                    child['activity_at'] = terminal['stopped_at']
                    self._reconcile(child)

    def _route_pending(self, pairs):
        # In-memory only, under the lock: lookup keys for already hook-bound rows
        # that still lack a model from every live source. Newest rows first, and
        # units negative-cached as permanently unresolvable are never re-read, so
        # the per-read cap cannot starve recent work behind old dead rows.
        pending = []
        for key, row in pairs:
            if not row.get('delegation_id') or type(row.get('task_index')) is not int:
                continue
            if row.get('model') or (row.get('observed') or {}).get('model'):
                continue
            if (row['delegation_id'], row['task_index']) in self._route_negative:
                continue
            pending.append((key, row['delegation_id'], row['task_index'],
                            row['parent_session_id'], row.get('subagent_id'), row.get('updated_at') or 0.0))
        pending.sort(key=lambda item: item[5], reverse=True)
        return pending[:_MAX_STORED_ROUTE_LOOKUPS]

    def _read_stored_routes(self, pending):
        # An async dispatch result carries only ids; the per-task route report lands
        # in the origin's stored delegation ledger when the child finishes. A
        # profile-routed child converses as its target profile, so this origin's API
        # hooks never see its calls and the stored report is the only origin-local
        # model evidence. Reads happen OUTSIDE the shared hook lock: a busy ledger
        # must never hold up pre_tool_call or API hooks. Scalars only, fail closed.
        out = []
        if not pending:
            return out
        try:
            with DelegationRouteReports(self.home) as reports:
                for key, unit, idx, parent, short, _ts in pending:
                    entry = reports.report(unit=unit, task_index=idx, parent=parent, short=short)
                    observed = _observed(entry) if entry is not None else None
                    if observed is not None and (observed['evidence'] == 'unknown' or not observed.get('model')):
                        observed, entry = None, None
                    state = None
                    if entry is None and reports.conn is not None:
                        state = reports.unit_state(unit=unit, parent=parent)
                    out.append((key, observed, state))
        except Exception:
            pass
        return out

    def _apply_stored_routes(self, results):
        # Under the lock again: re-check live evidence before adopting — a hook may
        # have answered while the ledger was read. Never touch row.model/provider
        # (the API-hook source); the stored report is route evidence only.
        for key, observed, state in results:
            row = self.rows.get(key)
            if row is None:
                continue
            adopted = False
            if observed is not None and not row.get('model') and not (row.get('observed') or {}).get('model'):
                row['observed'] = observed
                row['updated_at'] = time.time()
                adopted = True
            if not adopted and state is not None and state != 'running':
                # Pruned ('absent') or finished without a usable route: this unit can
                # never produce one. Stop re-reading it (bounded; oldest evicted).
                self._route_negative[(row.get('delegation_id'), row.get('task_index'))] = None
                while len(self._route_negative) > _MAX_ROUTE_NEGATIVE:
                    self._route_negative.popitem(last=False)

    @staticmethod
    def _child_stop(child, status, duration):
        if child.get('status') not in _TERMINAL and status in _TERMINAL:
            child['status'] = status
            if duration is not None:
                child['duration_seconds'] = duration
        child['activity_at'] = time.time()

    def _settle_original(self, original_id, status, duration):
        original = next((r for r in self.rows.values() if r['id'] == original_id), None)
        if original is not None and status in _TERMINAL:
            _set_status(original, status)
            if duration is not None:
                original['duration_seconds'] = duration
            original['updated_at'] = time.time()

    def _resolve_stops(self, child):
        # The stop hook does not say which run stopped. A held stop is known to be an earlier run's only
        # on evidence: it predates this run's restart, its duration exceeds this run's age, or this run
        # was active after it. Outcomes are attributed only when that evidence makes them unambiguous.
        earlier, held = child.get('earlier_runs', []), child.get('held_stops', [])
        known = [h for h in held if h['earlier']]
        if earlier and known:
            if len(earlier) == 1:
                self._settle_original(earlier.pop(), known[0]['status'], known[0]['duration'])
                held.remove(known[0])
            elif len(known) == len(earlier):
                shared = {h['status'] for h in known}
                outcome = next(iter(shared)) if len(shared) == 1 else 'ended'
                for run in earlier:
                    self._settle_original(run, outcome, None)
                earlier.clear()
                for h in known:
                    held.remove(h)
        if earlier and len(held) == len(earlier) + 1:
            # Every run has stopped and nothing ties a stop to a run: report only a shared outcome.
            shared = {h['status'] for h in held}
            outcome = shared.pop() if len(shared) == 1 else 'ended'
            for run in earlier:
                self._settle_original(run, outcome, None)
            earlier.clear()
            held.clear()
            self._child_stop(child, outcome, None)
        if not earlier:
            for h in held:
                self._child_stop(child, h['status'], h['duration'])
            held.clear()
        if not earlier:
            child.pop('earlier_runs', None)
        if not held:
            child.pop('held_stops', None)

    def _hold_stop(self, child, status, duration):
        age = time.monotonic() - child['run_monotonic'] if 'run_monotonic' in child else time.time() - child['started_at']
        earlier = duration is not None and duration > age + 2.0
        child.setdefault('held_stops', []).append({'status': status, 'duration': duration, 'earlier': earlier})
        self._resolve_stops(child)

    def _current_run_active(self, child):
        # Activity of this run after a held stop proves that stop was an earlier run's.
        if child.get('earlier_runs') and child.get('held_stops'):
            for h in child['held_stops']:
                h['earlier'] = True
            self._resolve_stops(child)

    def stop(self, parent_session_id=None, child_session_id=None, child_status=None, duration_ms=None, **kwargs):
        try:
            parent, session = map(_safe, (parent_session_id, child_session_id))
            if not self._owner() or not parent or not session:
                return None
            with self.lock:
                child = self._child(session) or self._stored_child(parent, session)
                if child and self._same_session(child['parent'], parent):
                    duration = duration_ms / 1000 if type(duration_ms) in (int, float) and 0 <= duration_ms < 1e12 else None
                    status = _status(child_status)
                    if child.get('earlier_runs'):
                        self._hold_stop(child, status, duration)
                    else:
                        self._child_stop(child, status, duration)
                    self._reconcile(child)
                    self._notify_parent(parent)
        except Exception:
            pass
        return None

    def compact(self, session_id=None, old_session_id=None, **kwargs):
        try:
            new, old = map(_safe, (session_id, old_session_id))
            if not self._owner() or not new or not old or new == old:
                return None
            with self.lock:
                known = any(self._same_session(old, r['parent_session_id']) or
                            self._same_session(old, r['conversation_id']) for r in self.rows.values())
                known = known or self._child(old) is not None
                collision = any(self._same_session(new, x) for x in self.aliases) or any(
                    self._same_session(new, x) for c in self.children.values() for x in (c['session'], c['parent']))
                collision = collision or any(self._same_session(new, x) for r in self.rows.values()
                                             for x in (r['conversation_id'], r['parent_session_id']))
                if known and not collision:
                    self.aliases[new] = old
                    while len(self.aliases) > 512:
                        self.aliases.pop(next(iter(self.aliases)))
                    child = self._child(new)
                    if child:
                        child['child_session_id'] = new
                    self._reconcile()
                    self._notify_parent(new if not child else child['parent'])
        except Exception:
            pass
        return None

    def _activity(self, session_id, tool_name=None, model=None, provider=None, api=False):
        if not self._owner():
            return
        session = _safe(session_id)
        with self.lock:
            child = self._child(session) if session else None
            if not child or child.get('status') in _TERMINAL:
                return
            self._current_run_active(child)
            if child.get('status') in _TERMINAL:
                return
            _set_status(child, 'running')
            child['activity_at'] = time.time()
            if api:
                child['api_call_count'] = (child.get('api_call_count') or 0) + 1
                if isinstance(model, str) and '..' not in model and _MODEL.fullmatch(model):
                    # One pair per call. The first call runs the routed model; a later
                    # different pair is Hermes' spare-model switch (fallback chain).
                    pair = {'model': model, 'provider': provider if _safe(provider) else None}
                    child['model'], child['provider'] = pair['model'], pair['provider']
                    # Transitions, not distinct pairs: A -> B -> A stays visible. Bounded: the
                    # first pair and the latest three are kept.
                    models = child.setdefault('models', [])
                    if not models or models[-1] != pair:
                        models.append(pair)
                        if len(models) > 4:
                            del models[1]
                            child['models_truncated'] = True
            elif _safe(tool_name):
                child['last_tool'] = tool_name
                child['tool_count'] = (child.get('tool_count') or 0) + 1
            self._reconcile(child)
            self._notify_parent(child['parent'])

    def api_pre(self, session_id=None, model=None, provider=None, **kwargs):
        try:
            self._activity(session_id, model=model, provider=provider, api=True)
        except Exception:
            pass
        return None

    def api_post(self, session_id=None, usage=None, **kwargs):
        # Host-normalized token buckets of one API call (CanonicalUsage); summed per child.
        try:
            if not self._owner() or not isinstance(usage, dict):
                return None
            session = _safe(session_id)
            buckets = {}
            for key in _TOKEN_BUCKETS:
                value = usage.get(f'{key}_tokens', 0)
                if type(value) is not int or value < 0 or value > 10**12:
                    return None
                buckets[key] = value
            with self.lock:
                child = self._child(session) if session else None
                if not child:
                    return None
                if child.get('status') not in _TERMINAL:
                    self._current_run_active(child)  # a usage report means this run was still executing
                tokens = child.setdefault('tokens', dict.fromkeys(_TOKEN_BUCKETS, 0))
                for key, value in buckets.items():
                    tokens[key] = min(tokens[key] + value, 10**15)
                self._reconcile(child)
                self._notify_parent(child['parent'])
        except Exception:
            pass
        return None

    def pre(self, tool_name='', args=None, session_id=None, conversation_id=None, tool_call_id=None, **kwargs):
        try:
            self._activity(session_id, tool_name=tool_name)
            if not self._owner() or not self.origin_profile or tool_name != 'delegate_task' or not isinstance(args, dict):
                return None
            action = args.get('action')
            if action == 'continue':
                return self._pre_continue(args, session_id, conversation_id, tool_call_id)
            if action not in (None, '', 'spawn'):
                return None
            root, session, call = map(_safe, (conversation_id, session_id, tool_call_id))
            if not all((root, session, call)):
                return None
            tasks = args.get('tasks')
            if isinstance(tasks, str) and len(tasks) <= 65536:
                try:
                    tasks = json.loads(tasks)
                except (ValueError, TypeError):
                    return None
            # Core's legacy goal normalization discards top-level route selectors.
            if (tasks is None or tasks == []) and isinstance(args.get('goal'), str) and args['goal'].strip():
                tasks = [{}]
            if not isinstance(tasks, list) or not tasks or len(tasks) > 128:
                return None
            with self.lock:
                for i, task in enumerate(tasks):
                    key = (root, session, call, i)
                    if key in self.rows:
                        continue
                    digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()
                    self.rows[key] = {'id': digest, 'execution_mode': 'native', 'requested': _requested(task),
                        'observed': _observed({}), 'conversation_id': root, 'parent_session_id': session,
                        'tool_call_id': call, 'task_index': i, 'subagent_id': None, 'delegation_id': None,
                        'async_unit_id': None, 'native_call_delegation_id': None,
                        'status': 'requested', 'updated_at': time.time()}
                while len(self.rows) > 512:
                    self.rows.pop(next(iter(self.rows)))
            self._event(root, session)
        except Exception:
            pass
        return None

    def _pre_continue(self, args, session_id, conversation_id, tool_call_id):
        # A continuation runs on the original child's route, so it inherits that row's request.
        root, session, call = map(_safe, (conversation_id, session_id, tool_call_id))
        sid = _safe(args.get('subagent_id'))
        if not all((root, session, call, sid)):
            return None
        with self.lock:
            key = (root, session, call, 0)
            if key in self.rows:
                return None
            # Only a child of this parent session (or its compaction lineage) can be continued here.
            originals = [r for r in self.rows.values() if r['conversation_id'] == root
                         and r['subagent_id'] == sid and r['delegation_id'] and not r.get('continued_by')
                         and self._same_session(r['parent_session_id'], session)]
            if len(originals) != 1:
                return None
            original = originals[0]
            self._reconcile()  # settle the previous run before its row stops following the child
            digest = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()
            self.rows[key] = {'id': digest, 'execution_mode': 'native', 'requested': copy.deepcopy(original['requested']),
                'observed': _observed({}), 'conversation_id': root, 'parent_session_id': session,
                'tool_call_id': call, 'task_index': 0, 'subagent_id': None, 'delegation_id': None,
                'async_unit_id': None, 'native_call_delegation_id': None, 'continued_from': original['id'],
                'status': 'requested', 'updated_at': time.time()}
            original['continued_by'] = digest
            for stale in [k for k, p in self.continuing.items() if p['sid'] == sid
                          and self._same_session(p['parent'], session)]:
                self.continuing.pop(stale)  # a never-started earlier attempt
            self.continuing[key] = {'sid': sid, 'parent': session, 'original': original['id'],
                                    'child_session': original.get('child_session_id')}
            while len(self.continuing) > 128:
                self.continuing.pop(next(iter(self.continuing)))
            while len(self.rows) > 512:
                self.rows.pop(next(iter(self.rows)))
        self._event(root, session)
        return None

    def _post_continue(self, root, session, call, args, result):
        with self.lock:
            key = (root, session, call, 0)
            row = self.rows.get(key)
            if row is None or not row.get('continued_from'):
                return False
            sid = _safe(args.get('subagent_id'))
            sids = result.get('subagent_ids')
            accepted = (result.get('status') == 'dispatched' and isinstance(sids, list) and len(sids) == 1
                        and _safe(sids[0]) == sid) or isinstance(result.get('results'), list)
            if not accepted:
                # Refused: the original row stays the one that run's evidence belongs to.
                self.continuing.pop(key, None)
                self.rows.pop(key, None)
                for other in self.rows.values():
                    if other.get('continued_by') == row['id']:
                        other.pop('continued_by', None)
                self._reconcile()  # pick up anything the original missed while it was set aside
                return True
            # The pending restart stays until its subagent_start, whichever hook arrives first.
            self._apply({0: row}, result)
            if row['subagent_id'] is None and sid:
                row['subagent_id'] = sid
            self._reconcile()
            return True

    def post(self, tool_name='', args=None, result=None, session_id=None, conversation_id=None, tool_call_id=None, **kwargs):
        try:
            if not self._owner() or tool_name != 'delegate_task' or not isinstance(args, dict):
                return None
            root, session, call = map(_safe, (conversation_id, session_id, tool_call_id))
            if not all((root, session, call)):
                return None
            parsed = result if isinstance(result, dict) else None
            if isinstance(result, str) and len(result) <= 2_000_000:
                try:
                    loaded = json.loads(result)
                except Exception:
                    loaded = None
                if isinstance(loaded, dict):
                    parsed = loaded
            # The core's terminal post_tool_call carries status/error_type for cancelled, timed-out
            # or abandoned calls whose result is plain text (no JSON payload). Use that terminal
            # failure status as an auxiliary signal so an unbound requested row never lingers active.
            hook_status = _status(kwargs.get('status'))
            if args.get('action') == 'continue':
                if parsed is not None and self._post_continue(root, session, call, args, parsed):
                    self._event(root, session)
                return None
            changed = False
            with self.lock:
                rows = {k[3]: v for k, v in self.rows.items() if k[:3] == (root, session, call)}
                if parsed is not None and args.get('action') == 'list' and parsed.get('action') == 'list':
                    entries = parsed.get('subagents')
                    if isinstance(entries, list) and len(entries) <= 512:
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            sid = _safe(entry.get('subagent_id'))
                            delegation = _safe(entry.get('delegation_id'))
                            # Current model-facing native lists omit the unit id.
                            # A recyclable short child id alone is not a binding.
                            matches = [r for r in self.rows.values() if sid and r['conversation_id'] == root
                                       and delegation and r.get('native_call_delegation_id', r['delegation_id']) == delegation
                                       and r['subagent_id'] == sid]
                            if len(matches) == 1:
                                _set_status(matches[0], _status(entry.get('status')))
                                matches[0]['updated_at'] = time.time()
                                changed = True
                elif rows:
                    if parsed is not None:
                        if (isinstance(parsed.get('error'), str) and parsed.get('status') != 'dispatched'
                                and not any(isinstance(parsed.get(f), list) for f in ('results', 'refused', 'inline_results'))):
                            # Whole-call refusal (e.g. routing refused before any dispatch): settle the
                            # still-unbound requested rows so a refused request never lingers as active.
                            # A row that already dispatched keeps its own evidence; a late top-level error
                            # never overwrites it. Per-task refusals ride the 'refused' list through _apply.
                            for row in rows.values():
                                if row['status'] == 'requested' and not row.get('delegation_id') and not row.get('subagent_id'):
                                    _set_status(row, 'error')
                                    row['updated_at'] = time.time()
                                    changed = True
                        else:
                            changed = self._apply(rows, parsed)
                    # Terminal failure hook status (cancel/timeout/abandon), with or without a payload,
                    # settles only the still-unbound requested rows; dispatched/bound rows keep evidence.
                    if hook_status in ('error', 'interrupted', 'cancelled', 'timeout'):
                        for row in rows.values():
                            if row['status'] == 'requested' and not row.get('delegation_id') and not row.get('subagent_id'):
                                _set_status(row, hook_status)
                                row['updated_at'] = time.time()
                                changed = True
                    self._reconcile()
            if changed:
                self._event(root, session)
        except Exception:
            pass
        return None

    def _apply(self, rows, result):
        changed = False
        # Exact task-index correlation only; duplicates invalidate the entire group.
        for field in ('results', 'refused', 'inline_results'):
            entries = result.get(field, [])
            if not isinstance(entries, list) or len(entries) > 128:
                continue
            indices = [e.get('task_index') if isinstance(e, dict) else None for e in entries]
            if any(type(i) is not int or i not in rows for i in indices) or len(set(indices)) != len(indices):
                continue
            for entry, i in zip(entries, indices):
                row = rows[i]
                _set_status(row, _status(entry.get('status')))
                observed = _observed(entry)
                if observed['evidence'] != 'unknown':
                    row['observed'] = observed
                row['updated_at'] = time.time()
                changed = True
        if result.get('status') == 'dispatched':
            refused = result.get('refused', [])
            inline = result.get('inline_results', [])
            def indexes(entries):
                if not isinstance(entries, list) or len(entries) > 128:
                    return None
                ids = [e.get('task_index') if isinstance(e, dict) else None for e in entries]
                if any(type(i) is not int or i not in rows for i in ids) or len(set(ids)) != len(ids):
                    return None
                return set(ids)
            r, inline_ids = indexes(refused), indexes(inline)
            if r is None or inline_ids is None or r & inline_ids:
                return changed
            accepted = sorted(set(rows) - r - inline_ids)
            for i in accepted:
                _set_status(rows[i], 'dispatched')
                rows[i]['updated_at'] = time.time()
                changed = True
            # Core's subagent_ids includes inline-fallback children too; do not guess in that case.
            sids = result.get('subagent_ids')
            count = result.get('count')
            count_ok = count is None or (type(count) is int and count == len(accepted))
            if count_ok and not inline_ids and isinstance(sids, list) and len(sids) == len(accepted):
                valid = [_safe(s) for s in sids]
                if all(valid) and len(set(valid)) == len(valid):
                    for i, sid in zip(accepted, valid):
                        rows[i]['subagent_id'] = sid
            units = result.get('units')
            mapping = {}
            if units is None:
                uid = _safe(result.get('delegation_id'))
                if uid:
                    mapping = {i: uid for i in accepted}
            elif isinstance(units, list) and len(units) <= 128:
                good = True
                unit_ids = set()
                for unit in units:
                    uid = _safe(unit.get('delegation_id')) if isinstance(unit, dict) else None
                    members = unit.get('task_indexes') if isinstance(unit, dict) else None
                    if not uid or uid in unit_ids or not isinstance(members, list) or not members:
                        good = False
                        break
                    unit_ids.add(uid)
                    for i in members:
                        if type(i) is not int or i not in accepted or i in mapping:
                            good = False
                            break
                        mapping[i] = uid
                if not good or set(mapping) != set(accepted):
                    mapping = {}
            for i, uid in mapping.items():
                rows[i]['delegation_id'] = uid
                rows[i]['async_unit_id'] = uid
                rows[i]['native_call_delegation_id'] = _safe(result.get('delegation_id'))
        elif 'results' in result:
            uid = _safe(result.get('delegation_id'))
            if uid:
                for row in rows.values():
                    row['delegation_id'] = uid
                    row['async_unit_id'] = uid
                    row['native_call_delegation_id'] = uid
        return changed

    def list(self, params, *, session_id=None, **kwargs):
        empty = {'schema': 1, 'origin_profile': self.origin_profile, 'conversation_id': None,
                 'rows': [], 'supported': self.rpc_supported}
        if not self.rpc_supported:
            empty['reason'] = 'rpc_unavailable'
        try:
            if not self._owner() or not isinstance(params, dict) or set(params) - {'session_id', 'profile'}:
                return empty
            # Gateway may include an assertion for shared-owner routing. It is
            # never used to select a home or expand the authorized session.
            if 'profile' in params and params['profile'] != self.origin_profile:
                return empty
            sid = _safe(session_id)
            if not sid or ('session_id' in params and params['session_id'] != sid):
                return empty
            with self.lock:
                roots = {r['conversation_id'] for r in self.rows.values()
                         if any(self._same_session(sid, x) for x in (r['conversation_id'], r['parent_session_id']))}
                if len(roots) != 1:
                    return empty
                root = roots.pop()
                empty['conversation_id'] = root
                pairs = [(k, r) for k, r in self.rows.items() if r['conversation_id'] == root][-128:]
                selected = [r for _, r in pairs]
                self._refresh_stored_terminal(selected)
                pending = self._route_pending(pairs)
            # Ledger reads stay outside the shared hook lock (busy-DB hold time).
            results = self._read_stored_routes(pending)
            with self.lock:
                try:
                    self._apply_stored_routes(results)
                except Exception:
                    pass
                empty['rows'] = copy.deepcopy(selected)
            return empty
        except Exception:
            return empty


def register_execution_roster(ctx, home):
    roster = _adopt_state(home, lambda entry: ExecutionRoster(ctx, home, shared=entry))
    ctx.register_hook('pre_tool_call', roster.pre)
    ctx.register_hook('post_tool_call', roster.post)
    ctx.register_hook('subagent_start', roster.start)
    ctx.register_hook('subagent_stop', roster.stop)
    ctx.register_hook('post_compaction', roster.compact)
    ctx.register_hook('pre_api_request', roster.api_pre)
    ctx.register_hook('post_api_request', roster.api_post)
    try:
        register = getattr(ctx, 'register_rpc', None)
        if callable(register):
            register('execution.list', roster.list)
            roster.rpc_supported = True
    except Exception:
        pass
    return roster
