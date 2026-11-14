"""Documented Win32 protected local transport. No Hermes imports or target calls.
Same-token malicious code, privileged writers and kernel/filesystem attacks excluded.
Only local NTFS; all chain handles live until close; no path-based secret I/O.
"""
from __future__ import annotations
import contextlib
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import struct
import threading
import time

if os.name != 'nt':
    raise RuntimeError('Windows required')
K = C.WinDLL('kernel32', use_last_error=True)
A = C.WinDLL('advapi32', use_last_error=True)
P = C.c_void_p
DWORD = W.DWORD
HANDLE = W.HANDLE
BOOL = W.BOOL
LPDWORD = C.POINTER(DWORD)
INVALID = C.c_void_p(-1).value
READ_CONTROL = 0x20000
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
DIR_FLAGS = 0x02000000 | 0x00200000
FILE_FLAGS = 0x00200000
FA = 0x1f01ff
MAX_BYTES = 65536

class SA(C.Structure):
    _fields_ = [('length', DWORD), ('sd', P), ('inherit', BOOL)]
class INFO(C.Structure):
    _fields_ = [('attrs', DWORD), ('created', W.FILETIME), ('accessed', W.FILETIME),
                ('written', W.FILETIME), ('volume', DWORD), ('size_hi', DWORD),
                ('size_lo', DWORD), ('links', DWORD), ('index_hi', DWORD), ('index_lo', DWORD)]
class ACL_SIZE(C.Structure):
    _fields_ = [('count', DWORD), ('used', DWORD), ('free', DWORD)]
class ACE_HEAD(C.Structure):
    _fields_ = [('type', W.BYTE), ('flags', W.BYTE), ('size', W.WORD), ('mask', DWORD)]
class OVERLAPPED(C.Structure):
    _fields_ = [('internal', C.c_size_t), ('internal_high', C.c_size_t),
                ('offset', DWORD), ('offset_high', DWORD), ('event', HANDLE)]

def bind(dll, name, result, *args):
    f = getattr(dll, name)
    f.restype, f.argtypes = result, list(args)
    return f

CreateFile = bind(K, 'CreateFileW', HANDLE, W.LPCWSTR, DWORD, DWORD, P, DWORD, DWORD, HANDLE)
CloseHandle = bind(K, 'CloseHandle', BOOL, HANDLE)
CreateDirectory = bind(K, 'CreateDirectoryW', BOOL, W.LPCWSTR, P)
GetInfo = bind(K, 'GetFileInformationByHandle', BOOL, HANDLE, C.POINTER(INFO))
GetType = bind(K, 'GetFileType', DWORD, HANDLE)
GetFinal = bind(K, 'GetFinalPathNameByHandleW', DWORD, HANDLE, W.LPWSTR, DWORD, DWORD)
GetVolume = bind(K, 'GetVolumeInformationByHandleW', BOOL, HANDLE, W.LPWSTR, DWORD, LPDWORD, LPDWORD, LPDWORD, W.LPWSTR, DWORD)
GetHandleInfo = bind(K, 'GetHandleInformation', BOOL, HANDLE, LPDWORD)
ReadFile = bind(K, 'ReadFile', BOOL, HANDLE, P, DWORD, LPDWORD, P)
WriteFile = bind(K, 'WriteFile', BOOL, HANDLE, P, DWORD, LPDWORD, P)
SetPointer = bind(K, 'SetFilePointerEx', BOOL, HANDLE, C.c_longlong, P, DWORD)
SetEnd = bind(K, 'SetEndOfFile', BOOL, HANDLE)
Flush = bind(K, 'FlushFileBuffers', BOOL, HANDLE)
LockFile = bind(K, 'LockFileEx', BOOL, HANDLE, DWORD, DWORD, DWORD, DWORD, C.POINTER(OVERLAPPED))
UnlockFile = bind(K, 'UnlockFileEx', BOOL, HANDLE, DWORD, DWORD, DWORD, C.POINTER(OVERLAPPED))
LocalFree = bind(K, 'LocalFree', P, P)
GetCurrentProcess = bind(K, 'GetCurrentProcess', HANDLE)
GetCurrentThread = bind(K, 'GetCurrentThread', HANDLE)
OpenToken = bind(A, 'OpenProcessToken', BOOL, HANDLE, DWORD, C.POINTER(HANDLE))
OpenThreadToken = bind(A, 'OpenThreadToken', BOOL, HANDLE, DWORD, BOOL, C.POINTER(HANDLE))
GetTokenInfo = bind(A, 'GetTokenInformation', BOOL, HANDLE, C.c_int, P, DWORD, LPDWORD)
SidToString = bind(A, 'ConvertSidToStringSidW', BOOL, P, C.POINTER(P))
StringToSD = bind(A, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', BOOL, W.LPCWSTR, DWORD, C.POINTER(P), LPDWORD)
GetSecurity = bind(A, 'GetSecurityInfo', DWORD, HANDLE, C.c_int, DWORD, C.POINTER(P), P, C.POINTER(P), P, C.POINTER(P))
SDControl = bind(A, 'GetSecurityDescriptorControl', BOOL, P, C.POINTER(W.WORD), LPDWORD)
GetDacl = bind(A, 'GetSecurityDescriptorDacl', BOOL, P, C.POINTER(BOOL), C.POINTER(P), C.POINTER(BOOL))
GetOwner = bind(A, 'GetSecurityDescriptorOwner', BOOL, P, C.POINTER(P), C.POINTER(BOOL))
IsValidSD = bind(A, 'IsValidSecurityDescriptor', BOOL, P)
IsValidAcl = bind(A, 'IsValidAcl', BOOL, P)
IsValidSid = bind(A, 'IsValidSid', BOOL, P)
GetLengthSid = bind(A, 'GetLengthSid', DWORD, P)
EqualSid = bind(A, 'EqualSid', BOOL, P, P)
GetAclInfo = bind(A, 'GetAclInformation', BOOL, P, P, DWORD, C.c_int)
GetAce = bind(A, 'GetAce', BOOL, P, DWORD, C.POINTER(P))

class Rejected(Exception):
    pass

def ok(value, api):
    if not value:
        raise C.WinError(C.get_last_error(), api)
    return value

def own(h):
    if h == INVALID or h is None:
        raise C.WinError(C.get_last_error(), 'CreateFileW')
    try:
        flags = DWORD()
        ok(GetHandleInfo(h, C.byref(flags)), 'GetHandleInformation')
        if flags.value & 1:
            raise Rejected('inheritable_handle')
        return h
    except BaseException:
        CloseHandle(h)
        raise

def close(h):
    # No process-global handle history or racy post-close numeric-handle probe.
    # Each owning object tracks its handles; the kernel can reuse closed values.
    ok(CloseHandle(h), 'CloseHandle')

def opened(path, access=READ_CONTROL | 0x80, share=1, disposition=3, sa=None, directory=False):
    return own(CreateFile(str(path), access, share, C.byref(sa) if sa is not None else None,
                          disposition, DIR_FLAGS if directory else FILE_FLAGS, None))

def info(h, directory=None):
    out = INFO()
    ok(GetInfo(h, C.byref(out)), 'GetFileInformationByHandle')
    if GetType(h) != 1:
        raise Rejected('not_disk')
    if out.attrs & 0x400:
        raise Rejected('reparse')
    if directory is not None and bool(out.attrs & 0x10) != directory:
        raise Rejected('wrong_object_type')
    if directory is False and out.links != 1:
        raise Rejected('hardlink_count')
    if out.attrs & (0x1000 | 0x40000):
        raise Rejected('offline_or_recall')
    return out

def identity(h):
    i = info(h)
    return (i.volume, i.index_hi, i.index_lo)

def final_guid(h):
    buf = C.create_unicode_buffer(32768)
    n = ok(GetFinal(h, buf, len(buf), 1), 'GetFinalPathNameByHandleW')
    if n >= len(buf) or not re.match(r'^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', buf.value):
        raise Rejected('not_volume_guid')
    return buf.value

class Security:
    def __init__(self):
        self.sd = P()
        thread_token = HANDLE()
        if OpenThreadToken(GetCurrentThread(), 8, True, C.byref(thread_token)):
            own(thread_token.value)
            close(thread_token.value)
            raise Rejected('impersonation_unsupported')
        if C.get_last_error() != 1008:
            raise C.WinError(C.get_last_error(), 'OpenThreadToken')
        token = HANDLE()
        ok(OpenToken(GetCurrentProcess(), 8, C.byref(token)), 'OpenProcessToken')
        own(token.value)
        try:
            size = DWORD()
            GetTokenInfo(token, 1, None, 0, C.byref(size))
            if not 0 < size.value < 4096:
                raise Rejected('token_size')
            self.token_data = C.create_string_buffer(size.value)
            ok(GetTokenInfo(token, 1, self.token_data, size, C.byref(size)), 'GetTokenInformation')
            self.sid = P.from_buffer(self.token_data).value
            ok(IsValidSid(self.sid), 'IsValidSid')
            sid_text = P()
            ok(SidToString(self.sid, C.byref(sid_text)), 'ConvertSidToStringSidW')
            try:
                self.sid_text = C.wstring_at(sid_text)
            finally:
                LocalFree(sid_text)
            ok(StringToSD('O:' + self.sid_text + 'D:P(A;;FA;;;' + self.sid_text + ')', 1,
                          C.byref(self.sd), None), 'ConvertStringSecurityDescriptorToSecurityDescriptorW')
            self.sa = SA(C.sizeof(SA), self.sd, False)
        finally:
            close(token.value)

    def close(self):
        if self.sd:
            if LocalFree(self.sd):
                raise RuntimeError('LocalFree')
            self.sd = P()

    def inspect(self, h):
        owner, dacl, sd = P(), P(), P()
        rc = GetSecurity(h, 1, 1 | 4, C.byref(owner), None, C.byref(dacl), None, C.byref(sd))
        if rc:
            raise C.WinError(rc, 'GetSecurityInfo')
        try:
            if not IsValidSD(sd):
                raise Rejected('invalid_sd')
            control, rev = W.WORD(), DWORD()
            ok(SDControl(sd, C.byref(control), C.byref(rev)), 'GetSecurityDescriptorControl')
            if (control.value & 0x1004) != 0x1004 or control.value & (0x1 | 0x8 | 0x100):
                raise Rejected('unprotected_or_defaulted_dacl')
            defaulted, present, acl = BOOL(), BOOL(), P()
            own_sid = P()
            ok(GetOwner(sd, C.byref(own_sid), C.byref(defaulted)), 'GetSecurityDescriptorOwner')
            if defaulted.value or not own_sid or not IsValidSid(own_sid) or not EqualSid(own_sid, self.sid):
                raise Rejected('wrong_owner')
            ok(GetDacl(sd, C.byref(present), C.byref(acl), C.byref(defaulted)), 'GetSecurityDescriptorDacl')
            if not present.value or not acl or defaulted.value:
                raise Rejected('null_or_absent_dacl')
            if not IsValidAcl(acl):
                raise Rejected('invalid_acl')
            size = ACL_SIZE()
            ok(GetAclInfo(acl, C.byref(size), C.sizeof(size), 2), 'GetAclInformation')
            if size.count != 1:
                raise Rejected('extra_or_empty_aces')
            ace = P()
            ok(GetAce(acl, 0, C.byref(ace)), 'GetAce')
            if not ace.value:
                raise Rejected('missing_ace')
            head = ACE_HEAD.from_address(ace.value)
            if head.type != 0 or head.flags != 0 or head.mask != FA or head.size < 16:
                raise Rejected('ace_type_flags_or_mask')
            sid = ace.value + 8
            if not IsValidSid(sid) or GetLengthSid(sid) + 8 != head.size or not EqualSid(sid, self.sid):
                raise Rejected('wrong_ace_sid')
            return {'owner_matches_token': True, 'control': hex(control.value), 'ace_count': size.count,
                    'ace_flags': head.flags, 'ace_mask': hex(head.mask), 'protected': True}
        finally:
            if LocalFree(sd):
                raise RuntimeError('LocalFree')

def segment(s):
    if not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', s):
        raise Rejected('bad_component')
    if s.endswith('.') or s.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}:
        raise Rejected('bad_component')
    return s

FILE_CASE_SENSITIVE_INFO_CLASS = 23  # Computed from MS_ENUM, SDK public enum.
FILE_CS_FLAG_CASE_SENSITIVE_DIR = 1  # Microsoft winnt.h definition.
class CASE_INFO(C.Structure):
    _fields_ = [('Flags', DWORD)]
GetInfoEx = bind(K, 'GetFileInformationByHandleEx', BOOL, HANDLE, C.c_int, P, DWORD)

def case_policy(h):
    out = CASE_INFO()
    if not GetInfoEx(h, FILE_CASE_SENSITIVE_INFO_CLASS, C.byref(out), C.sizeof(out)):
        raise Rejected('case_query_unavailable:' + str(C.get_last_error()))
    if out.Flags & ~FILE_CS_FLAG_CASE_SENSITIVE_DIR:
        raise Rejected('case_query_unknown_flags')
    return out.Flags

class Chain:
    def __init__(self, path):
        self.handles, self.entries = [], []
        raw = str(path).replace('/', '\\')
        if not re.match(r'^[A-Za-z]:\\', raw) or len(raw) > 8192:
            raise Rejected('local_absolute_path_required')
        components = raw[3:].split('\\')
        for name in components:
            segment(name)
        try:
            root = opened('\\\\?\\' + raw[:3], directory=True)
            self.handles.append(root)
            info(root, True)
            volume_path = final_guid(root)
            if not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', volume_path):
                raise Rejected('root_not_volume_root')
            pinned_root = opened(volume_path, directory=True)
            self.handles.append(pinned_root)
            if identity(root) != identity(pinned_root):
                raise Rejected('volume_root_identity_changed')
            fs = C.create_unicode_buffer(64)
            serial, maximum, flags = DWORD(), DWORD(), DWORD()
            ok(GetVolume(pinned_root, None, 0, C.byref(serial), C.byref(maximum), C.byref(flags), fs, len(fs)), 'GetVolumeInformationByHandleW')
            if fs.value != 'NTFS' or not flags.value & 8:
                raise Rejected('local_ntfs_persistent_acls_required')
            self.volume = {'filesystem': fs.value, 'persistent_acls': True, 'guid_root': volume_path}
            self.path = volume_path.rstrip('\\')
            self.root_anchors = [(h, final_guid(h), identity(h)) for h in self.handles]
            if any(actual != volume_path for _, actual, _ in self.root_anchors):
                raise Rejected('volume_root_final_changed')
            self.edge_policies = []
            for name in components:
                self.append(name)
        except BaseException:
            self.close()
            raise

    def append(self, name, security=None, create=False):
        name = segment(name)  # Unchanged bounded ASCII-only component domain.
        self.validate()
        parent = self.handles[-1]
        parent_path = self.path
        parent_id = identity(parent)
        policy = case_policy(parent)  # Unsupported query fails, never assumes zero.
        target = parent_path + '\\' + name
        if create:
            ok(CreateDirectory(target, C.byref(security.sa)), 'CreateDirectoryW')
        h = opened(target, directory=True)
        try:
            info(h, True)
            if security is not None:
                security.inspect(h)
            actual = final_guid(h)
            actual_parent, actual_name = actual.rsplit('\\', 1)
            # Never fold a complete path: actual handle must be one direct child
            # of the ALREADY canonical pinned parent in this same GUID lineage.
            if actual_parent != parent_path:
                raise Rejected('parent_final_path_mismatch')
            segment(actual_name)
            if actual_name != name:
                if policy & FILE_CS_FLAG_CASE_SENSITIVE_DIR:
                    raise Rejected('case_sensitive_name_mismatch')
                if len(actual_name) != len(name) or actual_name.lower() != name.lower():
                    raise Rejected('child_name_not_case_alias')
            ident = identity(h)
            if ident[0] != parent_id[0]:
                raise Rejected('child_volume_mismatch')
            self.validate()  # Rechecks all pinned ancestors after actual open.
            if identity(parent) != parent_id or final_guid(parent).rstrip('\\') != parent_path:
                raise Rejected('parent_identity_or_final_changed')
            if case_policy(parent) != policy:
                raise Rejected('case_policy_changed')
            if identity(h) != ident or final_guid(h) != actual:
                raise Rejected('child_identity_or_final_changed')
        except BaseException:
            close(h)
            raise
        self.handles.append(h)
        self.entries.append((actual, h, ident))
        self.edge_policies.append((parent, policy))
        self.path = actual  # Adopt actual handle spelling; preserve exact ID.
        return h

    def validate(self):
        for h, expected, ident in self.root_anchors:
            info(h, True)
            if final_guid(h) != expected or identity(h) != ident:
                raise Rejected('volume_root_identity_or_final_changed')
        for expected, h, ident in self.entries:
            info(h, True)
            if final_guid(h) != expected:
                raise Rejected('final_path_mismatch')
            if identity(h) != ident:
                raise Rejected('identity_changed')
        for parent, policy in self.edge_policies:
            if case_policy(parent) != policy:
                raise Rejected('case_policy_changed')

    def close(self):
        for h in reversed(self.handles):
            close(h)
        self.handles.clear()
        self.entries.clear()
        if hasattr(self, 'edge_policies'):
            self.edge_policies.clear()

class Primitive:
    """Compatible lock/read/write/path/close surface, not a full ReturnChannel.
    This proof opens an exact prepared generation path; creation pins base first.
    """
    def __init__(self, base, generation, create=False):
        self.security = Security()
        self.chain = None
        self.lock_handle = None
        self.path = Path(base) / segment(generation)
        self.thread_lock = threading.RLock()
        self.depth = threading.local()
        self.closed = False
        try:
            self.chain = Chain(base)
            self.chain.append(generation, self.security, create)
            target = self.chain.path + '\\lock.bin'
            self.lock_handle = opened(target, GENERIC_READ | GENERIC_WRITE | READ_CONTROL, 3,
                                      1 if create else 3, self.security.sa if create else None)
            info(self.lock_handle, False)
            self.security.inspect(self.lock_handle)
            if final_guid(self.lock_handle) != target:
                raise Rejected('final_path_mismatch')
            self.lock_identity = identity(self.lock_handle)
        except BaseException:
            self.close()
            raise

    def validate(self):
        if self.closed:
            raise Rejected('closed')
        self.chain.validate()
        self.security.inspect(self.chain.handles[-1])
        info(self.lock_handle, False)
        self.security.inspect(self.lock_handle)
        if final_guid(self.lock_handle) != self.chain.path + '\\lock.bin':
            raise Rejected('final_path_mismatch')
        if identity(self.lock_handle) != self.lock_identity:
            raise Rejected('lock_identity_changed')

    @contextlib.contextmanager
    def lock(self, timeout=2.0):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 2.0:
            raise Rejected('invalid_lock_timeout')
        deadline = time.monotonic() + timeout
        if not self.thread_lock.acquire(timeout=timeout):
            raise Rejected('thread_lock_timeout')
        outer = getattr(self.depth, 'value', 0) == 0
        acquired = False
        ov = OVERLAPPED()
        try:
            self.validate()
            if outer:
                while not LockFile(self.lock_handle, 3, 0, 1, 0, C.byref(ov)):
                    err = C.get_last_error()
                    if err != 33:
                        raise C.WinError(err, 'LockFileEx')
                    if time.monotonic() >= deadline:
                        raise Rejected('lock_timeout')
                    time.sleep(0.01)
                acquired = True
            self.depth.value = getattr(self.depth, 'value', 0) + 1
            try:
                self.validate()
                yield
            finally:
                self.depth.value -= 1
        finally:
            if acquired:
                ok(UnlockFile(self.lock_handle, 0, 1, 0, C.byref(ov)), 'UnlockFileEx')
            self.thread_lock.release()

    def file(self, name):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', name) or name == 'lock':
            raise Rejected('bad_record_name')
        return self.chain.path + '\\' + name + '.bin'

    def write_bytes(self, name, data, exclusive=False):
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise Rejected('write_bound')
        with self.lock():
            target = self.file(name)
            try:
                h = opened(target, GENERIC_READ | GENERIC_WRITE | READ_CONTROL, 1, 1, self.security.sa)
            except OSError as e:
                if e.winerror not in (80, 183) or exclusive:
                    raise
                h = opened(target, GENERIC_READ | GENERIC_WRITE | READ_CONTROL, 1)
            try:
                info(h, False)
                self.security.inspect(h)
                if final_guid(h) != target:
                    raise Rejected('final_path_mismatch')
                before = identity(h)
                ok(SetPointer(h, 0, None, 0), 'SetFilePointerEx')
                done = DWORD()
                buf = C.create_string_buffer(data)
                ok(WriteFile(h, buf, len(data), C.byref(done), None), 'WriteFile')
                if done.value != len(data):
                    raise Rejected('short_write')
                ok(SetEnd(h), 'SetEndOfFile')
                ok(Flush(h), 'FlushFileBuffers')
                if identity(h) != before:
                    raise Rejected('identity_changed')
                self.security.inspect(h)
            finally:
                close(h)

    def read_bytes(self, name):
        with self.lock():
            try:
                h = opened(self.file(name), GENERIC_READ | READ_CONTROL, 1)
            except OSError as e:
                if e.winerror == 2:
                    return None
                raise
            try:
                i = info(h, False)
                self.security.inspect(h)
                if final_guid(h) != self.file(name):
                    raise Rejected('final_path_mismatch')
                size = (i.size_hi << 32) | i.size_lo
                if size > MAX_BYTES:
                    raise Rejected('read_bound')
                before = identity(h)
                buf = C.create_string_buffer(MAX_BYTES + 1)
                done = DWORD()
                ok(ReadFile(h, buf, MAX_BYTES + 1, C.byref(done), None), 'ReadFile')
                if done.value != size or done.value > MAX_BYTES:
                    raise Rejected('changed_size_or_bound')
                if identity(h) != before:
                    raise Rejected('identity_changed')
                self.security.inspect(h)
                return buf.raw[:done.value]
            finally:
                close(h)

    def write(self, name, obj, exclusive=False):
        # Bound the caller's object before serializing; do not let a small file
        # limit conceal an unbounded JSON allocation or a cyclic object walk.
        stack, nodes, chars = [(obj, 0)], 0, 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if depth > 16 or nodes > 4096:
                raise Rejected('json_structure_bound')
            if isinstance(value, str):
                chars += len(value)
            elif value is None or type(value) is bool:
                pass
            elif type(value) is int:
                if value.bit_length() > 256:
                    raise Rejected('json_integer_bound')
            elif type(value) is float:
                if not math.isfinite(value):
                    raise Rejected('json_constant')
            elif type(value) is dict:
                if len(value) > 4096:
                    raise Rejected('json_structure_bound')
                for key, item in value.items():
                    if type(key) is not str:
                        raise Rejected('json_key_type')
                    chars += len(key)
                    stack.append((item, depth + 1))
            elif type(value) is list:
                if len(value) > 4096:
                    raise Rejected('json_structure_bound')
                stack.extend((item, depth + 1) for item in value)
            else:
                raise Rejected('json_type')
            if chars > MAX_BYTES - 40:
                raise Rejected('json_bound')
        encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))
        chunks, total = [], 0
        for chunk in encoder.iterencode(obj):
            total += len(chunk)
            if total > MAX_BYTES - 40:
                raise Rejected('json_bound')
            chunks.append(chunk)
        data = ''.join(chunks).encode('ascii')
        frame = b'WPR1' + struct.pack('<I', len(data)) + hashlib.sha256(data).digest() + data
        self.write_bytes(name, frame, exclusive)

    def read(self, name):
        data = self.read_bytes(name)
        if data is None:
            return None
        if len(data) < 40 or data[:4] != b'WPR1' or struct.unpack('<I', data[4:8])[0] != len(data) - 40 or hashlib.sha256(data[40:]).digest() != data[8:40]:
            raise Rejected('torn_or_invalid_frame')
        def unique(pairs):
            result = {}
            for k, v in pairs:
                if k in result:
                    raise Rejected('duplicate_json_key')
                result[k] = v
            return result
        try:
            value = json.loads(data[40:].decode('ascii'), object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(Rejected('json_constant')))
            stack = [(value, 0)]
            count = 0
            while stack:
                item, depth = stack.pop()
                count += 1
                if depth > 16 or count > 4096:
                    raise Rejected('json_structure_bound')
                if type(item) is float and not math.isfinite(item):
                    raise Rejected('json_constant')
                if type(item) is int and item.bit_length() > 256:
                    raise Rejected('json_integer_bound')
                if isinstance(item, dict):
                    stack.extend((v, depth + 1) for v in item.values())
                elif isinstance(item, list):
                    stack.extend((v, depth + 1) for v in item)
            return value
        except (UnicodeError, ValueError, RecursionError) as e:
            raise Rejected('invalid_json') from e

    def close(self):
        with self.thread_lock:
            if self.closed:
                return
            if getattr(self.depth, 'value', 0):
                raise Rejected('close_while_locked')
            self.closed = True
            try:
                if self.lock_handle is not None:
                    close(self.lock_handle)
                    self.lock_handle = None
            finally:
                try:
                    if self.chain:
                        self.chain.close()
                finally:
                    self.security.close()
