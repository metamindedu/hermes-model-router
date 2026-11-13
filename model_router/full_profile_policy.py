"""Independent opt-in full-profile grants; no Gateway or model activity here.

This module is not registered by itself. Its caller must bind every operation to
one captured plugin manager/home. Grant writes belong only to the registered
host CLI; session-control RPCs must never call the operator methods.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .service import PROFILE_RE, Service, _FileLock

DEFAULT_POLICY = {'schema': 1, 'enabled': False, 'targets': []}


class PolicyWriteUnknown(RuntimeError):
    """A setter was entered; a failing read-back cannot prove it had no effect."""


def _name(value: Any) -> str:
    if not isinstance(value, str) or not PROFILE_RE.fullmatch(value) or value == 'keep':
        raise ValueError('invalid_profile')
    return value


def _unlinked(path: Path) -> bool:
    try:
        if not path.is_absolute() or any(p == '..' for p in path.parts):
            return False
        for node in (path, *path.parents):
            try:
                info = node.lstat()
            except FileNotFoundError:
                continue  # an atomic file replacement/unlinked O_EXCL lock is normal
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return False
            # Resolve stable directories only: Windows can temporarily deny
            # opening a regular file while another thread atomically replaces it.
            if stat.S_ISDIR(info.st_mode) and node != node.resolve(strict=False):
                return False
        return True
    except OSError:
        return False


def _root_and_origin(home: Path) -> tuple[Path, str]:
    if not _unlinked(home) or not home.is_dir():
        raise ValueError('origin_unavailable')
    if home.parent.name == 'profiles':
        root, name = home.parent.parent, _name(home.name)
    else:
        root, name = home, 'default'
    if not (home / 'config.yaml').is_file() or not _unlinked(home / 'config.yaml'):
        raise ValueError('origin_unavailable')
    return root, name


def _normalize(value: Any) -> dict:
    # Native partial settings saves recursively merge dicts, including cwd: {}.
    # A single-record list is an atomic leaf replacement (also on revocation).
    # Read the unreleased legacy dict format, but never write it again.
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            raise ValueError('invalid_policy')
        value = value[0]
    if value is None or (isinstance(value, dict) and value == DEFAULT_POLICY and type(value.get('schema')) is int and type(value.get('enabled')) is bool):
        return {**DEFAULT_POLICY, 'targets': [], 'cwd': {}, 'revision': 0}
    if not isinstance(value, dict) or set(value) not in ({'schema', 'enabled', 'targets', 'cwd'}, {'schema', 'enabled', 'targets', 'cwd', 'revision'}):
        raise ValueError('invalid_policy')
    if type(value['schema']) is not int or value['schema'] != 1 or type(value['enabled']) is not bool:
        raise ValueError('invalid_policy')
    targets, cwds = value['targets'], value['cwd']
    if not isinstance(targets, list) or len(targets) > 32 or not isinstance(cwds, dict):
        raise ValueError('invalid_policy')
    names = [_name(x) for x in targets]
    if len(set(names)) != len(names) or set(cwds) != set(names):
        raise ValueError('invalid_policy')
    if any(not isinstance(cwds[n], str) or not cwds[n] for n in names):
        raise ValueError('invalid_policy')
    revision = value.get('revision', 0)
    if type(revision) is not int or not 0 <= revision <= 2**53 - 1:
        raise ValueError('invalid_policy')
    return {'schema': 1, 'enabled': value['enabled'], 'targets': names, 'cwd': dict(cwds), 'revision': revision}


class FullProfilePolicy:
    def __init__(self, ctx, home: Path, *, service_factory=Service, scope_factory=None, alive=None):
        self.ctx = ctx
        self.home = Path(home)
        self.root, self.origin_profile = _root_and_origin(self.home)
        self.service = service_factory(root=self.root)
        self.nonce = secrets.token_hex(32)
        self.scope_factory = scope_factory
        self.alive = alive or (lambda: True)
        self.mutex = threading.RLock()

    def _check_alive(self):
        if not self.alive():
            raise PermissionError('owner_unavailable')

    @contextmanager
    def guard(self, name):
        # Linearize execution admission/approval against explicit revocation.
        # This owns only a plugin policy lock, never a Gateway runtime lock.
        self._check_alive()
        lock = self.home / 'plugin-data' / 'model-router' / '.profile-jobs-policy.lock'
        if not _unlinked(lock):
            raise ValueError('origin_unavailable')
        with self.mutex, _FileLock(lock):
            self._check_alive()
            yield self.grant(name)

    @contextmanager
    def _scope(self):
        if self.scope_factory is not None:
            with self.scope_factory(self.home):
                yield
            return
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        token = set_hermes_home_override(self.home)
        try:
            yield
        finally:
            reset_hermes_home_override(token)

    @staticmethod
    def _raw_policy(raw):
        # Mirror only the documented plugin-relative read precedence. Never
        # import a private loader or treat its last-known-good leaf as authority.
        # Missing policy means OFF; a raw/effective disagreement must refuse.
        entry = raw
        for segment in ('plugins', 'entries', 'model-router'):
            if not isinstance(entry, dict) or segment not in entry:
                return _normalize(None)
            entry = entry[segment]
        if not isinstance(entry, dict):
            return _normalize(None)
        for subtree in ('settings', 'config'):
            value = entry.get(subtree)
            if isinstance(value, dict) and 'profile_jobs' in value:
                return _normalize(value['profile_jobs'])
        return _normalize(None)

    def _get(self):
        self._check_alive()
        config = self.home / 'config.yaml'
        try:
            from .yaml_compat import yaml
            if not _unlinked(config):
                raise ValueError('linked_origin')
            before = config.read_bytes()
            if len(before) > 1024 * 1024:
                raise ValueError('oversized_origin')
            raw = yaml.safe_load(before.decode('utf-8'))
            if raw is not None and not isinstance(raw, dict):
                raise ValueError('malformed_origin')
            raw_policy = self._raw_policy(raw)
        except Exception:
            # A native readonly loader may retain last-known-good settings.
            # That fallback is not authority after an unreadable origin file.
            raise ValueError('origin_config_unavailable') from None
        with self._scope():
            policy = _normalize(self.ctx.get_config('profile_jobs', None))
        try:
            # Stable bytes alone cannot prove the public getter used them:
            # native semantic preprocessing can fall back despite valid YAML.
            # Unsupported overlays/interpolation also fail closed here rather
            # than synthesizing authority from an unverifiable effective grant.
            if policy != raw_policy:
                raise ValueError('policy_provenance_mismatch')
            if not _unlinked(config) or config.read_bytes() != before:
                raise ValueError('origin_changed')
        except Exception:
            raise ValueError('origin_config_unavailable') from None
        return policy

    def _revision(self, policy):
        raw = json.dumps({'origin': self.origin_profile, 'home': str(self.home), 'incarnation': self.nonce, 'policy': policy}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _target(self, name):
        name = _name(name)
        path = self.root if name == 'default' else self.root / 'profiles' / name
        config = path / 'config.yaml'
        if not _unlinked(path) or not _unlinked(config) or not path.is_dir() or not config.is_file():
            return None, 'target_unavailable'
        try:
            value = self.service._read_key(name, 'terminal.cwd')
            if not isinstance(value, str) or not value or value != value.strip():
                return None, 'cwd_unavailable'
            cwd = Path(value)
            if not _unlinked(cwd) or not cwd.is_dir():
                return None, 'cwd_unavailable'
            # Freeze the literal configured value; disallow traversal regardless of separator.
            if any(part == '..' for part in value.replace('\\', '/').split('/')):
                return None, 'cwd_unavailable'
            return value, None
        except (OSError, ValueError, RuntimeError):
            return None, 'target_unavailable'

    def describe(self):
        policy = self._get()
        inventory = set(self.service._discover_profiles()) | set(policy['targets'])
        rows = []
        ordered = sorted(policy['targets']) + sorted(inventory - set(policy['targets']))
        for name in ordered[:32]:
            cwd, reason = self._target(name)
            if cwd is not None and name in policy['cwd'] and cwd != policy['cwd'][name]:
                reason = 'cwd_changed'
            rows.append({'profile': name, 'cwd': cwd, 'available': reason is None, 'reason_code': reason})
        return {'schema': 1, 'origin_profile': self.origin_profile,
                'policy': {k: policy[k] for k in ('schema', 'enabled', 'targets')},
                'revision': self._revision(policy), 'targets': rows, 'supported': True,
                'reason_code': None, 'completion_delivery': 'explicit_result', 'inventory_limited': len(ordered) > 32}

    def grant(self, name):
        policy = self._get()
        name = _name(name)
        if not policy['enabled'] or name not in policy['targets']:
            raise PermissionError('grant_denied')
        cwd, reason = self._target(name)
        if reason or cwd != policy['cwd'][name]:
            raise PermissionError('grant_stale')
        return {'profile': name, 'cwd': cwd, 'revision': self._revision(policy)}

    def configure(self, params):
        if not isinstance(params, dict) or set(params) - {'session_id', 'profile', 'expected_revision', 'enabled', 'targets', 'acknowledge_scope'}:
            raise ValueError('invalid_params')
        if 'profile' in params and params['profile'] != self.origin_profile:
            raise PermissionError('origin_mismatch')
        if params.get('acknowledge_scope') is not True or type(params.get('enabled')) is not bool:
            raise ValueError('scope_acknowledgement_required')
        targets = params.get('targets')
        if not isinstance(targets, list) or len(targets) > 32 or (params['enabled'] and not targets):
            raise ValueError('invalid_targets')
        names = [_name(x) for x in targets]
        if len(names) != len(set(names)):
            raise ValueError('invalid_targets')
        # Path validation before creating any lock directory; no linked journal parent.
        lock = self.home / 'plugin-data' / 'model-router' / '.profile-jobs-policy.lock'
        if not _unlinked(lock):
            raise ValueError('origin_unavailable')
        with self.mutex, _FileLock(lock):
            self._check_alive()
            old = self._get()
            if params.get('expected_revision') != self._revision(old):
                raise ValueError('revision_conflict')
            cwds = {}
            for name in names:
                if not params['enabled'] and name in old['cwd']:
                    cwds[name] = old['cwd'][name]
                    continue
                cwd, reason = self._target(name)
                if reason:
                    raise ValueError(reason)
                cwds[name] = cwd
            new = {'schema': 1, 'enabled': params['enabled'], 'targets': names, 'cwd': cwds, 'revision': old['revision'] + 1}
            try:
                with self._scope():
                    self.ctx.set_config('profile_jobs', [new])
                if self._get() != new:
                    raise RuntimeError('policy_readback_failed')
                return self.describe()
            except Exception:
                raise PolicyWriteUnknown('policy_write_unknown') from None

    @contextmanager
    def _operator_lock(self):
        self._check_alive()
        if _root_and_origin(self.home) != (self.root, self.origin_profile):
            raise PermissionError('origin_mismatch')
        lock = self.home / 'plugin-data' / 'model-router' / '.profile-jobs-policy.lock'
        if not _unlinked(lock):
            raise ValueError('origin_unavailable')
        # Same lock as grant/admission; never reap an ambiguous crashed writer.
        with self.mutex, _FileLock(lock):
            self._check_alive()
            yield

    @staticmethod
    def _operator_targets(value):
        if not isinstance(value, list) or len(value) > 32:
            raise ValueError('invalid_targets')
        names = [_name(name) for name in value]
        if len(names) != len(set(names)):
            raise ValueError('invalid_targets')
        return names

    def _operator_snapshot(self, policy, names):
        rows = []
        for name in names:
            cwd, reason = self._target(name)
            if cwd is not None and len(cwd) > 2048:
                cwd, reason = None, 'cwd_unavailable'
            rows.append({'profile': name, 'cwd': cwd, 'available': reason is None, 'reason_code': reason})
        material = {'domain': 'model-router/profile-jobs/operator/v1', 'root': str(self.root),
                    'home': str(self.home), 'origin_profile': self.origin_profile,
                    'policy': policy, 'review_targets': rows}
        revision = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        return {'schema': 1, 'status': 'ready', 'origin_profile': self.origin_profile,
                'policy': policy, 'review_targets': rows, 'operator_revision': revision,
                'completion_delivery': 'explicit_result',
                'scope_notice': 'Only this origin grant is changed. A target uses its normal account, tools, memory and source policy; model/tool charges may apply.'}

    def operator_status(self, params):
        if not isinstance(params, dict) or set(params) != {'targets'}:
            raise ValueError('invalid_params')
        names = self._operator_targets(params['targets'])
        with self._operator_lock():
            return self._operator_snapshot(self._get(), names)

    def operator_configure(self, params):
        if not isinstance(params, dict) or set(params) != {'expected_operator_revision', 'enabled', 'targets', 'acknowledge_scope'}:
            raise ValueError('invalid_params')
        expected = params['expected_operator_revision']
        if not isinstance(expected, str) or len(expected) != 64 or any(ch not in '0123456789abcdef' for ch in expected):
            raise ValueError('invalid_revision')
        if type(params['enabled']) is not bool or params['acknowledge_scope'] is not True:
            raise ValueError('scope_acknowledgement_required')
        names = self._operator_targets(params['targets'])
        if params['enabled'] and not names:
            raise ValueError('invalid_targets')
        with self._operator_lock():
            old = self._get()
            before = self._operator_snapshot(old, names)
            if expected != before['operator_revision']:
                raise ValueError('revision_conflict')
            if not params['enabled'] and not set(names) <= set(old['targets']):
                raise ValueError('disabled_grant_expansion')
            cwds = {}
            for row in before['review_targets']:
                if params['enabled']:
                    if not row['available']:
                        raise ValueError(row['reason_code'])
                    cwds[row['profile']] = row['cwd']
                else:
                    cwds[row['profile']] = old['cwd'][row['profile']]
            desired = {'schema': 1, 'enabled': params['enabled'], 'targets': names, 'cwd': cwds, 'revision': old['revision']}
            if desired == old:
                return {**before, 'status': 'noop', 'before_operator_revision': expected, 'no_effect': True}
            if old['revision'] >= 2**53 - 1:
                raise ValueError('revision_overflow')
            desired['revision'] += 1
            try:
                with self._scope():
                    self.ctx.set_config('profile_jobs', [desired])
                actual = self._get()
                if actual != desired:
                    raise RuntimeError('policy_readback_failed')
                return {**self._operator_snapshot(actual, names), 'status': 'saved',
                        'before_operator_revision': expected, 'no_effect': False}
            except Exception:
                raise PolicyWriteUnknown('policy_write_unknown') from None


def operator_cli(ctx, home, operation, raw_body):
    """Original registered host CLI only; never register this callable as RPC/tool."""
    origin = None
    try:
        from hermes_constants import get_hermes_home
        if Path(get_hermes_home()).resolve(strict=True) != Path(home).resolve(strict=True):
            raise PermissionError('origin_mismatch')
        if raw_body == '-':
            import sys
            raw_body = sys.stdin.read(16385)
        if not isinstance(raw_body, str) or len(raw_body) > 16384:
            raise ValueError('invalid_params')
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('invalid_params')
                result[key] = value
            return result
        params = json.loads(raw_body, object_pairs_hook=unique_object)
        policy = FullProfilePolicy(ctx, home)
        origin = policy.origin_profile
        if operation == 'profile-jobs-status':
            return policy.operator_status(params)
        if operation == 'profile-jobs-configure':
            return policy.operator_configure(params)
        raise ValueError('invalid_params')
    except PolicyWriteUnknown:
        return {'schema': 1, 'origin_profile': origin, 'status': 'unknown', 'error': 'policy_write_unknown', 'no_effect': False}
    except Exception as exc:
        allowed = {'invalid_params', 'invalid_targets', 'invalid_profile', 'invalid_policy', 'invalid_revision',
                   'scope_acknowledgement_required', 'revision_conflict', 'revision_overflow', 'disabled_grant_expansion',
                   'origin_mismatch', 'origin_unavailable', 'origin_config_unavailable', 'owner_unavailable', 'target_unavailable', 'cwd_unavailable'}
        code = str(exc) if str(exc) in allowed else 'policy_busy_or_unavailable'
        return {'schema': 1, 'origin_profile': origin, 'status': 'refused', 'error': code, 'no_effect': True}
