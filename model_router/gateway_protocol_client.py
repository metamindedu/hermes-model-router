"""Bounded public-CLI authenticated viewer for an already running Gateway."""
from __future__ import annotations

import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from typing import NoReturn
from urllib.parse import urlsplit

from .service import Service, PROFILE_RE

_PROTOCOL = 'hermes-gateway-v1'
_TICKET = 'hermes-gateway-ticket.'
_LIMIT = 1024 * 1024
_METHODS = frozenset({'runtime.describe', 'session.create', 'session.resume', 'session.events.since',
    'session.info', 'prompt.submit', 'prompt.receipt', 'prompt.cancel', 'session.steer',
    'approval.respond', 'clarify.respond'})
_REQUIRED = {'durable-admission-v1', 'event-replay-v1'}


class GatewayProtocolError(Exception):
    def __init__(self, code, *, ambiguous=False, sent=False):
        self.code = code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,48}', code) else 'unavailable'
        self.ambiguous = bool(ambiguous)
        self.sent = bool(sent)
        self.reason: str | None = None
        super().__init__(self.code)


def _fail(code='unavailable', *, sent=False, ambiguous=False) -> NoReturn:
    raise GatewayProtocolError(code, sent=sent, ambiguous=ambiguous) from None


def _path(path):
    if not isinstance(path, (str, os.PathLike)) or '..' in str(path).replace('\\', '/').split('/') or '.' in str(path).replace('\\', '/').split('/'):
        _fail('invalid_path')
    p = Path(path)
    if not p.is_absolute() or any(part in ('.', '..') for part in p.parts):
        _fail('invalid_path')
    try:
        for node in (p, *p.parents):
            st = node.lstat()
            if node.is_symlink() or getattr(st, 'st_file_attributes', 0) & 0x400:
                _fail('invalid_path')
        if not p.is_dir() or p != p.resolve(strict=True):
            _fail('invalid_path')
    except OSError:
        _fail('invalid_path')
    return p


def _budget(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 120:
        _fail('invalid_timeout')
    return float(value)


def _object(raw):
    def pairs(items):
        d = {}
        for key, value in items:
            if key in d:
                raise ValueError('duplicate')
            d[key] = value
        return d
    if not isinstance(raw, (str, bytes)) or len(raw) > _LIMIT:
        raise ValueError('size')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise ValueError('object')
    return value


def _run_attach(argv, env, timeout):
    """Capture bounded bytes in memory; neither stream ever enters a log or file."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, shell=False)
    except Exception:
        _fail('attach_unavailable')
    chunks = [bytearray(), bytearray()]
    overflow = threading.Event()
    def read(pipe, dest):
        try:
            while True:
                part = pipe.read(8192)
                if not part:
                    break
                if len(dest) + len(part) > _LIMIT:
                    overflow.set()
                    proc.kill()
                    break
                dest.extend(part)
        except Exception:
            overflow.set()
    threads = [threading.Thread(target=read, args=(pipe, dest), daemon=True)
               for pipe, dest in zip((proc.stdout, proc.stderr), chunks)]
    for thread in threads:
        thread.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        for thread in threads:
            thread.join(timeout=1)
        _fail('attach_timeout')
    for thread in threads:
        thread.join(timeout=1)
    if any(thread.is_alive() for thread in threads) or overflow.is_set() or proc.returncode != 0:
        _fail('attach_unavailable')
    return bytes(chunks[0])


def _command(profile, root, timeout):
    svc = Service(root=root)
    paths = svc._loaded_cli_paths()
    suffix = ['--profile', profile, 'gateway', 'attach', '--json', '--timeout', str(timeout)]
    try:
        argv = svc._command(profile, 'gateway', 'attach', '--json', '--timeout', str(timeout))
        if paths:
            if argv != [sys.executable, '-m', 'hermes_cli.main', *suffix]:
                _fail('launcher_unavailable')
            if not Path(sys.executable).is_absolute() or not Path(sys.executable).is_file():
                _fail('launcher_unavailable')
            if any(not Path(p).is_absolute() or not Path(p).is_dir() for p in paths):
                _fail('launcher_unavailable')
        else:
            stable = root / 'bin' / ('hermes.exe' if os.name == 'nt' else 'hermes')
            if _path(stable.parent) != root / 'bin' or stable.is_symlink() or not stable.is_file() or getattr(stable.lstat(), 'st_file_attributes', 0) & 0x400 or stable.resolve() != stable or argv != [str(stable), *suffix]:
                _fail('launcher_unavailable')
    except GatewayProtocolError:
        raise
    except Exception:
        _fail('launcher_unavailable')
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'HOME',
            'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL') if k in os.environ}
    env['HERMES_HOME'] = str(root)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if paths:
        env['PYTHONPATH'] = os.pathsep.join(paths)
    return argv, env


def _attach_info(payload, root, home):
    try:
        if payload.get('state') != 'ready':
            raise ValueError()
        e = payload['endpoint']
        if not isinstance(e, dict) or e['runtime_protocol'] != 1 or type(e['runtime_protocol']) is not int:
            raise ValueError()
        if not all(isinstance(e[k], str) and 0 < len(e[k]) <= 512 for k in ('profile_id', 'instance_id')):
            raise ValueError()
        if type(e['authority_epoch']) is not int or e['authority_epoch'] <= 0:
            raise ValueError()
        if e['supervisor'] not in {'none', 'systemd', 'launchd', 'windows', 'external'}:
            raise ValueError()
        caps = e['capabilities']
        if not isinstance(caps, list) or not all(isinstance(x, str) for x in caps) or not (_REQUIRED | {'session-authority-v1'}) <= set(caps):
            raise ValueError()
        control = e.get('control_home')
        if control is not None and _path(control) not in {root, home}:
            raise ValueError()
        if payload.get('client_code_sha') and payload['client_code_sha'] != e.get('code_sha'):
            raise ValueError()
        origin = e['api_origin']
        u = urlsplit(origin)
        if u.scheme not in {'http', 'https'} or not u.hostname or not u.port or u.username is not None or u.password is not None or u.path or u.query or u.fragment or not ipaddress.ip_address(u.hostname).is_loopback:
            raise ValueError()
        url = ('wss:' if u.scheme == 'https' else 'ws:') + origin[len(u.scheme)+1:] + '/api/ws'
        ticket = payload['ticket']
        if not isinstance(ticket, str) or not re.fullmatch(r'[A-Za-z0-9_.~-]{1,4096}', ticket):
            raise ValueError()
        if payload['url'] != url or payload['protocol'] != _PROTOCOL or payload['protocols'] != [_PROTOCOL, _TICKET + ticket]:
            raise ValueError()
        return e, url, [_PROTOCOL, _TICKET + ticket]
    except (KeyError, TypeError, ValueError, GatewayProtocolError):
        _fail('invalid_attach')


class GatewayProtocolClient:
    def __init__(self, websocket):
        self._ws = websocket
        self._lock = threading.RLock()
        self._events = []
        self._event_bytes = 0
        self._gap = False
        self._sequence = 0
        self._closed = False
        self.description = {}
        self.profile_id = ''
        self.instance_id = ''
        self.authority_epoch = 0

    @classmethod
    def connect(cls, *, profile: str, home: Path, root: Path, timeout: float = 15):
        timeout = _budget(timeout)
        if not isinstance(profile, str) or not PROFILE_RE.fullmatch(profile):
            _fail('invalid_profile')
        root, home = _path(root), _path(home)
        if home != (root if profile == 'default' else root / 'profiles' / profile):
            _fail('invalid_path')
        argv, env = _command(profile, root, timeout)
        try:
            payload = _object(_run_attach(argv, env, timeout))
            endpoint, url, protocols = _attach_info(payload, root, home)
        except GatewayProtocolError:
            raise
        except Exception:
            _fail('invalid_attach')
        del payload
        ws = None
        try:
            from websockets.sync.client import connect
            # The library can log raw handshake headers at DEBUG, including the ticket.
            quiet = logging.Logger('gateway_transport_silent')
            quiet.disabled = True
            ws = connect(url, subprotocols=protocols, proxy=None, open_timeout=timeout,
                         close_timeout=1, max_size=_LIMIT, compression=None, logger=quiet)
            # websockets retains the opening request and offered protocols after handshake.
            if ws.request is None:
                _fail('invalid_protocol')
            del ws.request.headers['Sec-WebSocket-Protocol']
            ws.protocol.available_subprotocols = None
        except Exception:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            _fail('connection_unavailable')
        finally:
            del protocols
        client = cls(ws)
        try:
            if ws.subprotocol != _PROTOCOL:
                _fail('invalid_protocol')
            description = client.call('runtime.describe', {}, timeout=timeout)
            if any(description.get(k) != endpoint[k] for k in ('profile_id', 'instance_id', 'authority_epoch')) or type(description.get('authority_epoch')) is not int:
                _fail('identity_mismatch')
            caps = description.get('capabilities')
            desc = description.get('session_create')
            if not isinstance(caps, list) or not all(isinstance(x, str) for x in caps) or not _REQUIRED <= set(caps):
                _fail('capability_mismatch')
            if not isinstance(desc, dict) or not isinstance(desc.get('sources'), list) or not all(isinstance(x, str) for x in desc['sources']) or 'tool' not in desc['sources'] or not isinstance(desc.get('parameters'), list) or not all(isinstance(x, str) for x in desc['parameters']) or not {'source', 'cwd', 'request_id'} <= set(desc['parameters']):
                _fail('capability_mismatch')
            client.description = description
            client.profile_id = endpoint['profile_id']
            client.instance_id = endpoint['instance_id']
            client.authority_epoch = endpoint['authority_epoch']
            return client
        except GatewayProtocolError:
            client.close()
            raise
        except Exception:
            client.close()
            _fail('invalid_describe')

    def call(self, method: str, params: dict, timeout: float = 10) -> dict:
        timeout = _budget(timeout)
        if not isinstance(method, str) or method not in _METHODS or not isinstance(params, dict):
            _fail('invalid_request')
        with self._lock:
            if self._closed:
                _fail('closed')
            self._sequence += 1
            rid = self._sequence
            try:
                raw = json.dumps({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params}, allow_nan=False, separators=(',', ':'))
                if len(raw.encode('utf-8')) > _LIMIT:
                    _fail('request_too_large')
            except GatewayProtocolError:
                raise
            except Exception:
                _fail('invalid_request')
            timer_guard = threading.Lock()
            timer_state = {'done': False, 'expired': False}
            def expire():
                with timer_guard:
                    if not timer_state['done']:
                        timer_state['expired'] = True
                        try:
                            self._ws.socket.shutdown(socket.SHUT_RDWR)
                        except Exception:
                            pass
            timer = threading.Timer(timeout, expire)
            timer.daemon = True
            deadline = time.monotonic() + timeout
            timer.start()
            try:
                self._ws.send(raw)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    frame = _object(self._ws.recv(timeout=remaining))
                    if frame.get('jsonrpc') != '2.0':
                        raise ValueError()
                    if 'method' in frame:
                        if not isinstance(frame['method'], str):
                            raise ValueError()
                        size = len(json.dumps(frame, ensure_ascii=True))
                        if len(self._events) >= 256 or self._event_bytes + size > _LIMIT:
                            self._gap = True
                        else:
                            self._events.append(frame)
                            self._event_bytes += size
                        continue
                    if type(frame.get('id')) is not int or frame['id'] != rid:
                        raise ValueError()
                    if 'error' in frame and 'result' not in frame:
                        error = frame['error']
                        data = error.get('data') if isinstance(error, dict) else None
                        reason = data.get('reason') if isinstance(data, dict) else None
                        if reason is None and isinstance(error, dict):
                            reason = error.get('message')
                        known = reason in ('invalid_params', 'permission_denied', 'not_found', 'stale_generation', 'revision_conflict')
                        exc = GatewayProtocolError('remote_refused', sent=True, ambiguous=not known)
                        exc.reason = reason if known else None
                        raise exc from None
                    if 'result' not in frame or 'error' in frame or not isinstance(frame['result'], dict):
                        raise ValueError()
                    return frame['result']
            except GatewayProtocolError:
                raise
            except TimeoutError:
                self.close()
                _fail('rpc_timeout', sent=True, ambiguous=True)
            except Exception:
                self.close()
                _fail('connection_lost', sent=True, ambiguous=True)
            finally:
                with timer_guard:
                    timer_state['done'] = True
                    expired = timer_state['expired']
                timer.cancel()
                if expired:
                    self.close()
                    _fail('rpc_timeout', sent=True, ambiguous=True)

    def drain_events(self) -> list[dict]:
        with self._lock:
            events, self._events = self._events, []
            self._event_bytes = 0
            if self._gap:
                events.append({'jsonrpc': '2.0', 'method': 'transport.event_gap', 'params': {}})
                self._gap = False
            return events

    def close(self) -> None:
        # Wake this viewer's bounded RPC receive before taking its lock. Never
        # signal, restart or stop the shared Gateway process.
        try:
            self._ws.socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._ws.close()
                except Exception:
                    pass
