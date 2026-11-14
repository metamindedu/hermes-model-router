"""Protected per-generation local transport, not an OS sandbox for its owner.

Initial implementation requires Windows/local NTFS. Unsupported hosts leave
optional automatic return unregistered; established explicit-result jobs remain
usable. No key, challenge or MAC is exposed through tool descriptors/stdout.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time

if os.name != 'nt':
    raise ImportError('return_transport_requires_windows_ntfs')

from .return_channel_windows import Chain, Primitive, Security, Rejected

RECORDS = frozenset({'plan', 'state', 'challenge', 'ready', 'activated', 'stop'})
PLAN_KEYS = frozenset({'schema', 'return_id', 'generation', 'job_id', 'origin', 'parent',
    'request_digest', 'payload_digest', 'owner_id', 'binding_digest', 'command_digest',
    'readiness_expires_at', 'wait_expires_at', 'readiness_monotonic_deadline',
    'wait_monotonic_deadline', 'persist_on_release'})
CHALLENGE_KEYS = frozenset({'schema', 'return_id', 'generation', 'binding_digest',
    'command_digest', 'process_id', 'started_at', 'challenge', 'expires_at'})
READY_KEYS = CHALLENGE_KEYS | {'helper_pid', 'mac'}


class ChannelError(ValueError):
    pass


def _hex(value, length):
    return type(value) is str and re.fullmatch('[a-f0-9]{%d}' % length, value) is not None


def _identifier(value, limit):
    return (type(value) is str and 0 < len(value) <= limit and value == value.strip()
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_plan(plan, return_id):
    if (type(plan) is not dict or set(plan) != PLAN_KEYS or type(plan['schema']) is not int
            or plan['schema'] != 1 or plan['return_id'] != return_id or not _hex(return_id, 32)
            or any(not _hex(plan[k], 32) for k in ('generation', 'job_id', 'owner_id'))
            or any(not _hex(plan[k], 64) for k in ('request_digest', 'payload_digest', 'binding_digest', 'command_digest'))
            or not _identifier(plan['parent'], 256) or type(plan['origin']) is not str
            or re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', plan['origin']) is None
            or plan['persist_on_release'] is not False
            or not _finite(plan['readiness_expires_at']) or not _finite(plan['wait_expires_at'])
            or plan['readiness_expires_at'] > plan['wait_expires_at']
            or not _finite(plan['readiness_monotonic_deadline']) or not _finite(plan['wait_monotonic_deadline'])
            or not 0 < plan['readiness_monotonic_deadline'] <= plan['wait_monotonic_deadline']):
        raise ChannelError('invalid_plan')
    return plan


def validate_challenge(plan, challenge):
    if (type(challenge) is not dict or set(challenge) != CHALLENGE_KEYS
            or type(challenge['schema']) is not int or challenge['schema'] != 1
            or any(challenge[k] != plan[k] for k in ('return_id', 'generation', 'binding_digest', 'command_digest'))
            or not _identifier(challenge['process_id'], 256) or not _identifier(challenge['started_at'], 128)
            or not _hex(challenge['challenge'], 64) or not _finite(challenge['expires_at'])
            or challenge['expires_at'] != plan['readiness_expires_at']):
        raise ChannelError('invalid_challenge')
    return challenge


class ReturnChannel:
    """One source-owned generation. Open never creates/repairs/adopts a lease."""
    def __init__(self, home, return_id, *, create=False):
        if not _hex(return_id, 32):
            raise ChannelError('invalid_return_id')
        self.home, self.return_id = Path(home), return_id
        self.path = self.home / 'plugin-data' / 'model-router' / 'return-channels' / return_id
        self._mutex = threading.RLock()
        self._closed = False
        self._base_security = self._base = self._backend = None
        try:
            self._base_security = Security()
            self._base = Chain(self.home)
            for name in ('plugin-data', 'model-router', 'return-channels'):
                protected = name == 'return-channels'
                try:
                    self._base.append(name, self._base_security if protected else None)
                except OSError as exc:
                    if not create or exc.winerror not in (2, 3):
                        raise
                    try:
                        self._base.append(name, self._base_security, create=True)
                    except OSError as raced:
                        if raced.winerror not in (80, 183):
                            raise
                        self._base.append(name, self._base_security if protected else None)
            self._backend = Primitive(self.path.parent, return_id, create=create)
            if create:
                self._backend.write_bytes('key', secrets.token_bytes(32), exclusive=True)
            if len(self._key()) != 32:
                raise ChannelError('key_unavailable')
        except BaseException:
            self.close()
            raise

    @classmethod
    def create(cls, home, return_id):
        return cls(home, return_id, create=True)

    @contextmanager
    def lock(self):
        if not self._mutex.acquire(timeout=2.0):
            raise ChannelError('channel_lock_timeout')
        try:
            if self._closed or self._backend is None:
                raise ChannelError('channel_closed')
            self._base.validate()
            self._base_security.inspect(self._base.handles[-1])
            with self._backend.lock():
                yield
        finally:
            self._mutex.release()

    def read(self, name):
        if name not in RECORDS:
            raise ChannelError('invalid_record')
        with self.lock():
            return self._backend.read(name)

    def write(self, name, value, exclusive=False):
        if name not in RECORDS or type(exclusive) is not bool:
            raise ChannelError('invalid_record')
        with self.lock():
            self._backend.write(name, value, exclusive=exclusive)

    def _key(self):
        # Private raw handle operation; never exposed through record read/write.
        key = self._backend.read_bytes('key')
        if type(key) is not bytes or len(key) != 32:
            raise ChannelError('key_unavailable')
        return key

    @staticmethod
    def _message(plan, challenge, helper_pid):
        # Closed schemas and primitive JSON bounds precede this tiny encoding.
        return json.dumps({'protocol': 'model-router-return-ready-v1', 'plan': plan,
            'challenge': challenge, 'helper_pid': helper_pid}, ensure_ascii=True,
            allow_nan=False, sort_keys=True, separators=(',', ':')).encode('ascii')

    def write_ready(self, challenge):
        with self.lock():
            plan = validate_plan(self.read('plan'), self.return_id)
            validate_challenge(plan, challenge)
            if time.time() >= challenge['expires_at']:
                raise ChannelError('readiness_expired')
            pid = os.getpid()
            mac = hmac.new(self._key(), self._message(plan, challenge, pid), hashlib.sha256).hexdigest()
            self.write('ready', dict(challenge, helper_pid=pid, mac=mac), exclusive=True)

    def verify_ready(self, challenge, ready):
        with self.lock():
            try:
                plan = validate_plan(self.read('plan'), self.return_id)
                validate_challenge(plan, challenge)
                if (type(ready) is not dict or set(ready) != READY_KEYS
                        or any(type(ready[k]) is not type(challenge[k]) or ready[k] != challenge[k] for k in CHALLENGE_KEYS)
                        or type(ready['helper_pid']) is not int or not 0 < ready['helper_pid'] <= 0xffffffff
                        or not _hex(ready['mac'], 64) or time.time() >= challenge['expires_at']):
                    return False
                expected = hmac.new(self._key(), self._message(plan, challenge, ready['helper_pid']), hashlib.sha256).hexdigest()
                return hmac.compare_digest(expected, ready['mac'])
            except (ChannelError, KeyError, TypeError, ValueError, OverflowError):
                return False

    def close(self):
        # Serializes close against all public I/O, including nested locks. A
        # crash/torn record is fail-closed, not a multi-file rollback guarantee.
        with self._mutex:
            if self._closed:
                return
            if self._backend is not None and getattr(self._backend.depth, 'value', 0):
                raise ChannelError('close_while_locked')
            self._closed = True
            try:
                if self._backend is not None:
                    self._backend.close()
            finally:
                try:
                    if self._base is not None:
                        self._base.close()
                finally:
                    if self._base_security is not None:
                        self._base_security.close()
