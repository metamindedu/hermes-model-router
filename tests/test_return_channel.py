"""Real Windows transport tests; no native caller/parent delivery claims."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
if os.name != 'nt':
    pytest.skip('initial protected transport is Windows/local NTFS only', allow_module_level=True)

from model_router.return_channel import ReturnChannel, ChannelError, validate_plan
from model_router.return_channel_windows import Rejected, Security, Chain


@pytest.fixture
def channel(tmp_path):
    home = tmp_path / 'source'
    home.mkdir()
    c = ReturnChannel.create(home, uuid4().hex)
    try:
        yield c
    finally:
        c.close()


def plan(c):
    return {'schema': 1, 'return_id': c.return_id, 'generation': uuid4().hex,
        'job_id': uuid4().hex, 'origin': 'default', 'parent': 'fixture-parent',
        'request_digest': '1' * 64, 'payload_digest': '2' * 64, 'owner_id': uuid4().hex,
        'binding_digest': '3' * 64, 'command_digest': '4' * 64,
        'readiness_expires_at': time.time() + 30, 'wait_expires_at': time.time() + 60,
        'readiness_monotonic_deadline': time.monotonic() + 30, 'wait_monotonic_deadline': time.monotonic() + 60,
        'persist_on_release': False}


def challenge(p):
    return {k: p[k] for k in ('schema', 'return_id', 'generation', 'binding_digest', 'command_digest')} | {
        'process_id': 'proc-native-opaque', 'started_at': '2026-11-14T00:00:00+09:00',
        'challenge': '5' * 64, 'expires_at': p['readiness_expires_at']}


def test_protected_create_open_roundtrip_and_actual_acl(channel):
    p = plan(channel)
    with channel.lock():
        channel.write('plan', p, exclusive=True)
        assert channel.read('plan') == p
        assert channel._base_security.inspect(channel._base.handles[-1])['ace_count'] == 1
        assert channel._backend.security.inspect(channel._backend.chain.handles[-1])['protected']
    peer = ReturnChannel(channel.home, channel.return_id)
    try:
        assert peer.read('plan') == p
    finally:
        peer.close()
    with pytest.raises(OSError):
        ReturnChannel.create(channel.home, channel.return_id)
    with pytest.raises(OSError):
        channel.write('plan', p, exclusive=True)
    for bad in ('key', 'lock', '../plan', 'plan:ads'):
        with pytest.raises(ChannelError):
            channel.read(bad)


def test_open_missing_never_creates_or_repairs(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    before = list(home.rglob('*'))
    with pytest.raises(OSError):
        ReturnChannel(home, uuid4().hex)
    assert list(home.rglob('*')) == before
    for rid in ('A' * 32, '../state', '0' * 31, True):
        with pytest.raises(ChannelError):
            ReturnChannel.create(home, rid)


def test_mac_strict_schema_exact_timestamp_and_all_plan_binding(channel):
    p = plan(channel)
    channel.write('plan', p, exclusive=True)
    ch = challenge(p)
    channel.write_ready(ch)
    ready = channel.read('ready')
    assert channel.verify_ready(ch, ready)
    for field, value in [('mac', '0' * 64), ('started_at', 123.0), ('helper_pid', True),
                         ('helper_pid', 0), ('challenge', '6' * 64), ('generation', uuid4().hex),
                         ('expires_at', True), ('extra', True)]:
        damaged = dict(ready, **{field: value})
        assert not channel.verify_ready(ch, damaged), field
    tampered_plan = dict(p, parent='different-parent')
    channel.write('plan', tampered_plan)
    assert not channel.verify_ready(ch, ready)
    channel.write('plan', p)
    assert channel.verify_ready(ch, ready)
    with pytest.raises(OSError):
        channel.write_ready(ch)


def test_expired_or_numeric_started_at_refuses(channel):
    p = plan(channel)
    p['readiness_expires_at'] = time.time() - 1
    channel.write('plan', p)
    ch = challenge(p)
    with pytest.raises(ChannelError):
        channel.write_ready(ch)
    ch['started_at'] = 1.0
    with pytest.raises(ChannelError):
        channel.write_ready(ch)
    assert not channel.verify_ready(ch, {})


def test_malformed_torn_and_large_json_fail_closed(channel):
    for item in ({'x': float('nan')}, {'x': float('inf')}, {'x': 'x' * 66000}, {'x': 1 << 300}):
        with pytest.raises(Rejected):
            channel.write('state', item)
    cycle = []
    cycle.append(cycle)
    with pytest.raises(Rejected):
        channel.write('state', cycle)
    channel._backend.write_bytes('state', b'not-a-valid-frame')
    with pytest.raises(Rejected):
        channel.read('state')


def test_cross_process_ready_and_lock_timeout(channel):
    channel.write('plan', plan(channel))
    ch = challenge(channel.read('plan'))
    channel.write('challenge', ch)
    code = ('import sys; from model_router.return_channel import ReturnChannel; '
        'c=ReturnChannel(sys.argv[1],sys.argv[2]); '
        'c.write_ready(c.read("challenge")); c.close(); print("READY_WRITTEN")')
    root = str(Path(__file__).resolve().parents[1])
    clean = {k:v for k,v in os.environ.items() if k.upper() in {'PATH','PATHEXT','SYSTEMROOT','WINDIR','COMSPEC','HOME','USERPROFILE','LOCALAPPDATA','APPDATA','TMP','TEMP','TMPDIR'}}
    clean['PYTHONPATH'] = root
    clean['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-B', '-c', code, str(channel.home), channel.return_id],
        cwd=channel.home, env=clean, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, 'child failed (secret output intentionally not included)'
    assert result.stdout.strip() == 'READY_WRITTEN' and not result.stderr
    assert channel.verify_ready(ch, channel.read('ready'))
    hold_code = ('import sys; from model_router.return_channel import ReturnChannel; '
        'c=ReturnChannel(sys.argv[1],sys.argv[2]); c.read("plan"); c.close(); print("UNEXPECTED")')
    with channel.lock():
        blocked = subprocess.run([sys.executable, '-B', '-c', hold_code, str(channel.home), channel.return_id],
            cwd=channel.home, env=clean, capture_output=True, text=True, timeout=15)
    assert blocked.returncode != 0 and 'UNEXPECTED' not in blocked.stdout
    assert channel.read('plan') is not None


def test_hardlinks_and_broadened_generation_acl_refuse_before_io(channel, tmp_path):
    from model_router import return_channel_windows as w
    channel.write('state', {'original': True})
    leaf = channel.path / 'state.bin'
    linked = tmp_path / 'linked.bin'
    os.link(leaf, linked)
    before = linked.read_bytes()
    try:
        with pytest.raises(Rejected):
            channel.read('state')
        with pytest.raises(Rejected):
            channel.write('state', {'changed': True})
        assert linked.read_bytes() == before
    finally:
        linked.unlink()
    # Only this test-owned generation is broadened, never an ancestor/user dir.
    set_security = w.bind(w.A, 'SetSecurityInfo', w.DWORD, w.HANDLE, w.C.c_int,
        w.DWORD, w.P, w.P, w.P, w.P)
    sd, acl = w.P(), w.P()
    present, defaulted = w.BOOL(), w.BOOL()
    sddl = 'D:P(A;;FA;;;' + channel._backend.security.sid_text + ')(A;;GR;;;WD)'
    w.ok(w.StringToSD(sddl, 1, w.C.byref(sd), None), 'testSD')
    handle = w.opened(channel._backend.chain.path, w.READ_CONTROL | 0x40000 | 0x80, 1, directory=True)
    try:
        w.ok(w.GetDacl(sd, w.C.byref(present), w.C.byref(acl), w.C.byref(defaulted)), 'testDACL')
        rc = set_security(handle, 1, 4 | 0x80000000, None, None, acl, None)
        assert rc == 0
    finally:
        w.close(handle)
        w.LocalFree(sd)
    with pytest.raises(Rejected):
        channel.read('state')
    with pytest.raises(Rejected):
        ReturnChannel(channel.home, channel.return_id)


def test_actual_alternate_leaf_handle_is_rejected_before_data_transfer(channel, tmp_path, monkeypatch):
    from model_router import return_channel_windows as w
    channel.write('state', {'original': True})
    outside = tmp_path / 'outside.bin'
    h = w.opened(str(outside), w.GENERIC_READ | w.GENERIC_WRITE | w.READ_CONTROL,
                 1, 1, channel._backend.security.sa)
    w.close(h)
    outside.write_bytes(b'UNCHANGED_OUTSIDE')
    actual_opened = w.opened
    def redirected(path, *a, **kw):
        if str(path).endswith(chr(92) + 'state.bin'):
            return actual_opened(str(outside), *a, **kw)
        return actual_opened(path, *a, **kw)
    monkeypatch.setattr(w, 'opened', redirected)
    with pytest.raises(Rejected, match='final_path_mismatch'):
        channel.read('state')
    with pytest.raises(Rejected):
        channel.write('state', {'would_be_secret': True})
    assert outside.read_bytes() == b'UNCHANGED_OUTSIDE'
    outside.unlink()
    with pytest.raises(Rejected, match='final_path_mismatch'):
        channel.write('state', {'would_be_secret': True}, exclusive=True)
    assert outside.read_bytes() == b''


def test_native_normcased_home_alias_preserves_physical_identity(tmp_path):
    home = tmp_path / 'MiXeDHome'
    home.mkdir()
    rid = uuid4().hex
    c = ReturnChannel.create(str(home).lower(), rid)
    peer = None
    try:
        c.write('plan', plan(c), exclusive=True)
        peer = ReturnChannel(str(home).upper(), rid)
        assert peer._backend.chain.path == c._backend.chain.path
        assert peer._backend.lock_identity == c._backend.lock_identity
        assert str(c.home) == str(Path(str(home).lower())), 'protocol home spelling must not be rewritten'
        assert peer.read('plan') == c.read('plan')
    finally:
        if peer is not None:
            peer.close()
        c.close()


def test_actual_case_sensitive_parent_stays_sensitive(tmp_path):
    from model_router import return_channel_windows as w
    parent = tmp_path / 'SensitiveParent'
    parent.mkdir()
    setter = w.bind(w.K, 'SetFileInformationByHandle', w.BOOL, w.HANDLE, w.C.c_int, w.P, w.DWORD)
    h = w.opened(str(parent), w.GENERIC_READ | w.GENERIC_WRITE | w.READ_CONTROL, 1, directory=True)
    child = parent / 'ExactChild'
    enabled = False
    try:
        sensitive = w.CASE_INFO(1)
        if not setter(h, 23, w.C.byref(sensitive), w.C.sizeof(sensitive)):
            pytest.skip('test-owned case-policy control unsupported on this Windows filesystem')
        enabled = True
        assert w.case_policy(h) == 1
        child.mkdir()
        chain = w.Chain(child)
        try:
            assert chain.path.endswith('ExactChild')
        finally:
            chain.close()
        with pytest.raises(OSError):
            w.Chain(parent / 'exactchild')
    finally:
        if child.exists():
            child.rmdir()
        if enabled:
            insensitive = w.CASE_INFO(0)
            w.ok(setter(h, 23, w.C.byref(insensitive), w.C.sizeof(insensitive)), 'restore test-only case policy')
            assert w.case_policy(h) == 0
        w.close(h)


@pytest.mark.parametrize('mode', ['unsupported', 'unknown_flags'])
def test_unsupported_or_unknown_parent_case_query_fails_closed(tmp_path, monkeypatch, mode):
    from model_router import return_channel_windows as w
    home = tmp_path / 'MiXeDHome'
    home.mkdir()
    def query(handle, kind, out, size):
        if mode == 'unsupported':
            w.C.set_last_error(87)
            return False
        w.C.cast(out, w.C.POINTER(w.CASE_INFO)).contents.Flags = 2
        return True
    monkeypatch.setattr(w, 'GetInfoEx', query)
    with pytest.raises(Rejected):
        ReturnChannel.create(str(home).lower(), uuid4().hex)
    assert not list(home.iterdir()), 'no protected directory/key before parent policy admission'


def test_close_serializes_with_other_thread_operation(channel):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    def reader():
        with channel.lock():
            entered.set()
            assert release.wait(5)
    t = threading.Thread(target=reader)
    t.start()
    assert entered.wait(5)
    closer = threading.Thread(target=lambda: (channel.close(), closed.set()))
    closer.start()
    assert not closed.wait(.05)
    release.set()
    t.join(5)
    closer.join(5)
    assert not t.is_alive() and not closer.is_alive() and closed.is_set()
    with pytest.raises(ChannelError):
        channel.read('plan')
