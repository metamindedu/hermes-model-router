"""Bounded, read-only projection of native profile role metadata."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import stat
import unicodedata

ROLE_INTRO_INHERITANCE_SCHEMA = 1
# Obvious credential shapes only; this is not a guarantee of declassification.
_SENSITIVE = re.compile(r'(?i)(?:\b(?:api[_ -]?key|password|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+|\bbearer\s+\S+|\bsk-[a-z0-9_-]{12,}|\bgh[pousr]_[a-z0-9]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def sensitive_text(value):
    return bool(_SENSITIVE.search(value))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def clean_text(value, limit=512):
    # Controls and format characters are data, never instructions or layout.
    result = ''.join(' ' if unicodedata.category(c) in ('Cc', 'Cf', 'Cs') else c for c in value)
    return ' '.join(result.split())[:limit]


def read_bounded(path: Path, root: Path, limit=32768):
    """Return bytes and a stable component signature; no path/content in errors."""
    from .installation import _inspect
    path, root = Path(path), Path(root)
    before_info, before = _inspect(path, 'file', base=root)
    if before_info is None:
        return None, before
    if not stat.S_ISREG(before_info.st_mode) or before_info.st_nlink != 1 or before_info.st_size > limit:
        raise ValueError('unsafe_source')
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        first = os.fstat(fd)
        def identity(s):
            # Windows stat(lstat) ctime can be creation time while fstat is change time.
            # Component signatures still compare lstat before/after; handle timestamps
            # are independently checked before/after below.
            return (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns)
        handle_ctime = first.st_ctime_ns
        if identity(first) != identity(before_info) or first.st_nlink != 1 or not stat.S_ISREG(first.st_mode):
            raise ValueError('unsafe_source')
        data = b''
        while len(data) <= limit:
            part = os.read(fd, min(8192, limit + 1 - len(data)))
            if not part:
                break
            data += part
        last = os.fstat(fd)
        if len(data) > limit or identity(last) != identity(first) or last.st_ctime_ns != handle_ctime:
            raise ValueError('unsafe_source')
    finally:
        os.close(fd)
    after_info, after = _inspect(path, 'file', base=root)
    if after_info is None or before != after or identity(after_info) != identity(first):
        raise ValueError('unsafe_source')
    return data, before


def resolve(service, name):
    from .native_delegation import _profile, _inventory
    state, text, auto, reason, signature = 'unavailable', '', False, 'unsafe_profile', None
    try:
        _profile(name)
        if not _inventory(service, name):
            raise ValueError('unsafe_profile')
        raw, signature = read_bounded(service._profile_home(name) / 'profile.yaml', service.root)
        if raw is None:
            state, reason = 'missing', 'metadata_missing'
        else:
            try:
                import yaml
                tokens = yaml.scan(raw)
                alias_types = (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)
                loader = yaml.safe_load
            except ModuleNotFoundError as exc:
                if exc.name != 'yaml':
                    raise
                import hermes_yaml
                from ruamel.yaml import YAML
                from ruamel.yaml.tokens import AliasToken, AnchorToken
                tokens = YAML(typ='safe', pure=True).scan(raw.decode('utf-8-sig'))
                alias_types = (AliasToken, AnchorToken)
                loader = hermes_yaml.safe_load
            # Aliases can inflate deeply and are not needed by native metadata.
            if any(isinstance(token, alias_types) for token in tokens):
                raise ValueError('invalid_metadata')
            data = loader(raw.decode('utf-8-sig'))
            if data is None:
                data = {}
            if not isinstance(data, dict) or not isinstance(data.get('description', ''), str):
                raise ValueError('invalid_metadata')
            if sensitive_text(data.get('description', '')):
                raise ValueError('sensitive_metadata')
            text = clean_text(data.get('description', '').strip())
            auto = bool(data.get('description_auto', False))
            state, reason = ('available', None) if text else ('missing', 'description_missing')
    except Exception:
        state, text, auto, reason = 'unavailable', '', False, 'metadata_unavailable'
    source = 'profile_metadata' if state == 'available' else 'none'
    return {'schema': 1, 'state': state, 'default_description': text, 'default_source': source,
            'description_auto': auto, 'digest': digest({'v': 1, 'name': name, 'signature': signature, 'state': state, 'text': text, 'auto': auto}), 'reason_code': reason}
