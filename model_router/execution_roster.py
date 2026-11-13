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
from pathlib import Path

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z", re.ASCII)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+/-]{0,127}\Z", re.ASCII)
_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z", re.ASCII)
_PURPOSES = {'implementation': 'light', 'mechanical': 'light', 'preliminary-review': 'light',
             'plan': 'heavy', 'semantic-final': 'heavy', 'independent-review': 'heavy'}
_BACKENDS = {'model-router', 'model-router-auto', 'model-router-profiles'}


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
            'profile': profile if kind == 'profile' else None, 'purpose': purpose if kind == 'model' else None}


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
            'refused': 'error', 'dispatched': 'dispatched', 'running': 'dispatched',
            'interrupted': 'interrupted', 'cancelled': 'cancelled', 'timeout': 'timeout'}.get(value, 'unknown')


class ExecutionRoster:
    def __init__(self, ctx, home):
        from hermes_constants import profile_name_for_home
        self.ctx = ctx
        self.home = Path(home).resolve(strict=False)
        self.origin_profile = _safe(profile_name_for_home(self.home))
        self.rows = {}
        self.lock = threading.RLock()
        self.rpc_supported = False

    def _owner(self):
        from hermes_constants import get_hermes_home
        return os.path.normcase(str(Path(get_hermes_home()).resolve(strict=False))) == os.path.normcase(str(self.home))

    def _event(self, root, session):
        emit = getattr(self.ctx, 'emit_to_session', None)
        if callable(emit):
            for sid in {root, session}:
                try:
                    emit(sid, 'execution.changed', {'schema': 1})
                except Exception:
                    pass

    def pre(self, tool_name='', args=None, session_id=None, conversation_id=None, tool_call_id=None, **kwargs):
        try:
            if not self._owner() or not self.origin_profile or tool_name != 'delegate_task' or not isinstance(args, dict):
                return None
            if args.get('action') not in (None, '', 'spawn'):
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
                        'status': 'requested', 'updated_at': time.time()}
                while len(self.rows) > 512:
                    self.rows.pop(next(iter(self.rows)))
            self._event(root, session)
        except Exception:
            pass
        return None

    def post(self, tool_name='', args=None, result=None, session_id=None, conversation_id=None, tool_call_id=None, **kwargs):
        try:
            if not self._owner() or tool_name != 'delegate_task' or not isinstance(args, dict):
                return None
            root, session, call = map(_safe, (conversation_id, session_id, tool_call_id))
            if not all((root, session, call)):
                return None
            if isinstance(result, str):
                if len(result) > 2_000_000:
                    return None
                result = json.loads(result)
            if not isinstance(result, dict):
                return None
            changed = False
            with self.lock:
                rows = {k[3]: v for k, v in self.rows.items() if k[:3] == (root, session, call)}
                if args.get('action') == 'list' and result.get('action') == 'list':
                    entries = result.get('subagents')
                    if isinstance(entries, list) and len(entries) <= 512:
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            sid = _safe(entry.get('subagent_id'))
                            delegation = _safe(entry.get('delegation_id'))
                            # Current model-facing native lists omit the unit id.
                            # A recyclable short child id alone is not a binding.
                            matches = [r for r in self.rows.values() if sid and r['conversation_id'] == root
                                       and delegation and r['delegation_id'] == delegation
                                       and r['subagent_id'] == sid]
                            if len(matches) == 1:
                                matches[0]['status'] = _status(entry.get('status'))
                                matches[0]['updated_at'] = time.time()
                                changed = True
                elif rows:
                    changed = self._apply(rows, result)
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
                row['status'] = _status(entry.get('status'))
                row['observed'] = _observed(entry)
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
                rows[i]['status'] = 'dispatched'
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
        elif 'results' in result:
            uid = _safe(result.get('delegation_id'))
            if uid:
                for row in rows.values():
                    row['delegation_id'] = uid
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
                         if sid in (r['conversation_id'], r['parent_session_id'])}
                if len(roots) != 1:
                    return empty
                root = roots.pop()
                empty['conversation_id'] = root
                empty['rows'] = copy.deepcopy([r for r in self.rows.values() if r['conversation_id'] == root][-128:])
            return empty
        except Exception:
            return empty


def register_execution_roster(ctx, home):
    roster = ExecutionRoster(ctx, home)
    ctx.register_hook('pre_tool_call', roster.pre)
    ctx.register_hook('post_tool_call', roster.post)
    try:
        register = getattr(ctx, 'register_rpc', None)
        if callable(register):
            register('execution.list', roster.list)
            roster.rpc_supported = True
    except Exception:
        pass
    return roster
