"""Private, bounded, origin-bound job metadata. Reads never create files."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import weakref

from .full_profile_policy import _unlinked
from .service import _FileLock, _atomic_write

MAX_JOBS = 64
MAX_BYTES = 16 * 1024 * 1024
TERMINAL = frozenset({'completed', 'failed', 'cancelled'})
STATES = TERMINAL | {'preparing', 'creating', 'submitting', 'queued', 'running', 'approval_wait', 'clarify_wait', 'stop_requested', 'unknown'}
FIELDS = frozenset({'id', 'origin_profile', 'parent_session_id', 'parent_aliases', 'target_profile', 'cwd',
    'request_id', 'payload_digest', 'grant_revision', 'create_id', 'submission_id', 'target_session_id',
    'admission_id', 'execution_generation', 'gateway_profile_id', 'instance_id', 'authority_epoch',
    'observer_owner', 'status', 'reason_code', 'created_at', 'updated_at', 'result', 'pending_request',
    'operation_unknown', 'pending_operation', 'completion_delivery', 'cancel_requested'})

_LOCK_GUARD = threading.Lock()
_LOCAL_LOCKS = weakref.WeakValueDictionary()


def _mutex(path):
    with _LOCK_GUARD:
        key = os.path.normcase(str(path))
        lock = _LOCAL_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCAL_LOCKS[key] = lock
        return lock


def _publish(path, payload):
    # Windows readers in another process may briefly hold the old file. Retrying
    # these identical metadata bytes is NOT retrying a remote/model operation.
    for attempt in range(4):
        try:
            _atomic_write(path, payload)
            return
        except PermissionError:
            try:
                if path.read_bytes() == payload:
                    return
            except OSError:
                pass
            if attempt == 3:
                raise
            time.sleep(.01)


class StateError(ValueError):
    def __init__(self, code):
        self.code = code if code in ('journal_unavailable', 'journal_capacity', 'workspace_busy', 'workspace_unavailable') else 'journal_unavailable'
        super().__init__(self.code)


def identifier(value, limit=256):
    return isinstance(value, str) and 0 < len(value) <= limit and value == value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise StateError('journal_unavailable')
        result[key] = value
    return result


class JobJournal:
    def __init__(self, home: Path, origin: str):
        self.home, self.origin = Path(home), origin
        self.directory = self.home / 'plugin-data' / 'model-router'
        self.path = self.directory / 'full-profile-jobs.json'
        self.lock = self.directory / '.full-profile-jobs.lock'
        self.binding = hashlib.sha256(str(self.home).encode('utf-8')).hexdigest()
        self.mutex = _mutex(self.path)

    def _paths(self):
        if not _unlinked(self.home) or not _unlinked(self.path) or not _unlinked(self.lock):
            raise StateError('journal_unavailable')

    def present(self):
        self._paths()
        return self.path.is_file()

    def read(self) -> dict:
        with self.mutex:
            for attempt in range(4):
                try:
                    return self._read()
                except OSError:
                    if attempt == 3:
                        raise StateError('journal_unavailable') from None
                    time.sleep(.01)
        raise StateError('journal_unavailable')

    def _read(self):
        self._paths()
        if not self.path.exists():
            return {'schema': 1, 'origin_profile': self.origin, 'binding': self.binding, 'jobs': {}}
        try:
            if self.path.stat().st_size > MAX_BYTES:
                raise StateError('journal_unavailable')
            value = json.loads(self.path.read_bytes().decode('utf-8'), object_pairs_hook=_pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(StateError('journal_unavailable')))
            self.validate(value)
            return value
        except (UnicodeError, ValueError, RecursionError):
            raise StateError('journal_unavailable') from None

    def validate(self, value):
        if (not isinstance(value, dict) or set(value) != {'schema', 'origin_profile', 'binding', 'jobs'}
                or type(value['schema']) is not int or value['schema'] != 1 or value['origin_profile'] != self.origin
                or value['binding'] != self.binding or not isinstance(value['jobs'], dict) or len(value['jobs']) > MAX_JOBS):
            raise StateError('journal_unavailable')
        for key, job in value['jobs'].items():
            if (not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key) or not isinstance(job, dict)
                    or set(job) - FIELDS or job.get('id') != key or job.get('origin_profile') != self.origin
                    or not identifier(job.get('parent_session_id')) or not isinstance(job.get('parent_aliases'), list)
                    or not 1 <= len(job['parent_aliases']) <= 64 or any(not identifier(sid) for sid in job['parent_aliases'])
                    or job['parent_session_id'] not in job['parent_aliases'] or not isinstance(job.get('status'), str) or job['status'] not in STATES
                    or job.get('completion_delivery') != 'explicit_result'
                    or not isinstance(job.get('target_profile'), str) or job['target_profile'] == 'keep' or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', job['target_profile'])
                    or not isinstance(job.get('cwd'), str) or not Path(job['cwd']).is_absolute()
                    or not identifier(job.get('request_id'), 128)
                    or any(not identifier(job.get(k)) for k in ('create_id', 'submission_id', 'observer_owner'))
                    or any(job.get(k) is not None and not identifier(job[k]) for k in ('target_session_id', 'admission_id', 'gateway_profile_id', 'instance_id'))):
                raise StateError('journal_unavailable')
            if any(not isinstance(job.get(k), str) or not re.fullmatch(r'[a-f0-9]{64}', job[k]) for k in ('payload_digest', 'grant_revision')):
                raise StateError('journal_unavailable')
            if any(type(job.get(k)) not in (int, float) or not math.isfinite(job[k]) for k in ('created_at', 'updated_at')):
                raise StateError('journal_unavailable')
            if type(job.get('authority_epoch')) is not int or job['authority_epoch'] < 0 or (job.get('execution_generation') is not None and (type(job['execution_generation']) is not int or job['execution_generation'] < 0)):
                raise StateError('journal_unavailable')
            if type(job.get('operation_unknown')) is not bool or type(job.get('cancel_requested')) is not bool or job.get('pending_operation') not in (None, 'create', 'submit', 'cancel', 'steer', 'approve', 'clarify'):
                raise StateError('journal_unavailable')
            pending = job.get('pending_request')
            if pending is not None and (not isinstance(pending, dict) or set(pending) != {'kind', 'prompt_id', 'execution_generation', 'text', 'choices'}
                    or pending['kind'] not in ('approval', 'clarify') or not identifier(pending['prompt_id'])
                    or type(pending['execution_generation']) is not int or pending['execution_generation'] < 0
                    or not isinstance(pending['text'], str) or len(pending['text']) > 8192
                    or not isinstance(pending['choices'], list) or any(c not in ('once', 'deny') for c in pending['choices'])):
                raise StateError('journal_unavailable')
            result = job.get('result')
            if result is not None and (not isinstance(result, dict) or set(result) != {'text', 'truncated'}
                    or not isinstance(result['text'], str) or len(result['text']) > 16384 or type(result['truncated']) is not bool):
                raise StateError('journal_unavailable')

    def transaction(self, change):
        with self.mutex:
            return self._transaction(change)

    def _transaction(self, change):
        self._paths()
        with _FileLock(self.lock):
            value = self.read()
            before = copy.deepcopy(value)
            result = change(value['jobs'])
            self.validate(value)
            if value != before:
                payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')).encode('utf-8')
                if len(payload) > MAX_BYTES:
                    raise StateError('journal_capacity')
                self._paths()
                _publish(self.path, payload)
            return copy.deepcopy(result)


class WorkspaceClaims:
    """Root-shared plugin job exclusion, not an OS lock against other programs.

    An unknown job keeps its claim. Only exact known terminal/no-submit evidence
    releases it; there is no TTL, PID reap or automatic replay.
    """
    def __init__(self, root, binding):
        self.directory = Path(root) / 'plugin-data' / 'model-router'
        self.path = self.directory / 'full-profile-workspaces.json'
        self.lock = self.directory / '.full-profile-workspaces.lock'
        self.binding = binding
        self.mutex = _mutex(self.path)

    def _change(self, job, acquire):
        with self.mutex:
            return self._change_locked(job, acquire)

    def _change_locked(self, job, acquire):
        if not all(_unlinked(p) for p in (self.path, self.lock)):
            raise StateError('workspace_unavailable')
        key = hashlib.sha256(os.path.normcase(str(Path(job['cwd']).resolve())).encode()).hexdigest()
        owner = {'binding': self.binding, 'job_id': job['id']}
        if not acquire and not self.path.exists():
            return
        with _FileLock(self.lock):
            if self.path.exists():
                try:
                    if self.path.stat().st_size > 65536:
                        raise ValueError()
                    value = json.loads(self.path.read_text(encoding='utf-8'), object_pairs_hook=_pairs)
                    if (not isinstance(value, dict) or set(value) != {'schema', 'claims'} or type(value['schema']) is not int
                            or value['schema'] != 1 or not isinstance(value['claims'], dict) or len(value['claims']) > 128):
                        raise ValueError()
                    for token, item in value['claims'].items():
                        if (not re.fullmatch(r'[a-f0-9]{64}', token) or not isinstance(item, dict) or set(item) != {'binding', 'job_id'}
                                or not re.fullmatch(r'[a-f0-9]{64}', item['binding']) or not re.fullmatch(r'[a-f0-9]{32}', item['job_id'])):
                            raise ValueError()
                except (ValueError, TypeError, OSError):
                    raise StateError('workspace_unavailable') from None
            else:
                value = {'schema': 1, 'claims': {}}
            claims = value['claims']
            if acquire:
                if (key in claims and claims[key] != owner) or (key not in claims and len(claims) >= 128):
                    raise StateError('workspace_busy')
                if claims.get(key) == owner:
                    return
                claims[key] = owner
            elif claims.get(key) == owner:
                del claims[key]
            else:
                return
            if not all(_unlinked(p) for p in (self.path, self.lock)):
                raise StateError('workspace_unavailable')
            _publish(self.path, json.dumps(value, sort_keys=True, separators=(',', ':')).encode())

    def claim(self, job):
        self._change(job, True)

    def release(self, job):
        self._change(job, False)
