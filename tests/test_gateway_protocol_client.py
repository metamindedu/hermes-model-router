import json
import threading
import time
from pathlib import Path

import pytest
from websockets.sync.server import serve

from model_router import gateway_protocol_client as gp

CAPS = ['session-authority-v1', 'durable-admission-v1', 'event-replay-v1']
DESC = {'profile_id': 'opaque', 'instance_id': 'instance', 'authority_epoch': 3,
        'capabilities': CAPS[1:], 'session_create': {'sources': ['tool'], 'parameters': ['cwd', 'request_id', 'source']}}


@pytest.fixture
def setup_client(tmp_path, monkeypatch):
    root = tmp_path / 'home'
    home = root / 'profiles' / 'worker'
    home.mkdir(parents=True)
    servers = []
    def make(handler, mutate=None):
        server = serve(handler, '127.0.0.1', 0, subprotocols=[gp._PROTOCOL])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        origin = 'http://127.0.0.1:%d' % server.socket.getsockname()[1]
        payload = {'state': 'ready', 'client_code_sha': 'sha', 'endpoint': {
            'profile_id': 'opaque', 'instance_id': 'instance', 'authority_epoch': 3,
            'runtime_protocol': 1, 'api_origin': origin, 'supervisor': 'none', 'capabilities': CAPS,
            'control_home': str(root), 'code_sha': 'sha'}, 'url': origin.replace('http:', 'ws:') + '/api/ws',
            'protocol': gp._PROTOCOL, 'protocols': [gp._PROTOCOL, gp._TICKET + 'fixture'], 'ticket': 'fixture'}
        if mutate:
            mutate(payload)
        def runner(argv, env, timeout):
            assert argv[-5:-2] == ['gateway', 'attach', '--json']
            assert '--start' not in argv and '--recover' not in argv
            assert env['HERMES_HOME'] == str(root)
            assert 'PARENT_TEST_SECRET' not in env
            return json.dumps(payload).encode()
        monkeypatch.setenv('PARENT_TEST_SECRET', 'never-pass')
        monkeypatch.setattr(gp, '_run_attach', runner)
        return lambda: gp.GatewayProtocolClient.connect(profile='worker', home=home, root=root, timeout=3)
    yield make, root, home
    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=3)
        assert not thread.is_alive()


def respond(ws, request, result):
    ws.send(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}))


def handler(ws):
    first = json.loads(ws.recv())
    assert first['method'] == 'runtime.describe'
    respond(ws, first, DESC)
    request = json.loads(ws.recv())
    ws.send(json.dumps({'jsonrpc': '2.0', 'method': 'session.event', 'params': {'sequence': 1}}))
    respond(ws, request, {'session_id': 'native-id'})


def test_real_socket_and_notification(setup_client, monkeypatch):
    make, _, _ = setup_client
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    client = make(handler)()
    assert client.profile_id == 'opaque' and client.instance_id == 'instance' and client.authority_epoch == 3
    assert client.call('session.info', {'session_id': 'native-id'}) == {'session_id': 'native-id'}
    assert client.drain_events()[0]['method'] == 'session.event'
    assert client.drain_events() == []
    client.close()


def test_refusal_is_sanitized(setup_client):
    def server(ws):
        req = json.loads(ws.recv()); respond(ws, req, DESC)
        req = json.loads(ws.recv())
        ws.send(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32001, 'message': 'secret address', 'data': {'reason': 'permission_denied'}}}))
    client = setup_client[0](server)()
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('prompt.submit', {})
    assert str(exc.value) == 'remote_refused' and exc.value.sent and not exc.value.ambiguous
    client.close()


def test_timeout_and_dead_socket_are_ambiguous(setup_client):
    def server(ws):
        req = json.loads(ws.recv()); respond(ws, req, DESC)
        ws.recv(); time.sleep(.3)
    client = setup_client[0](server)()
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('prompt.submit', {}, timeout=.05)
    assert exc.value.code == 'rpc_timeout' and exc.value.sent and exc.value.ambiguous
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('prompt.submit', {})
    assert not exc.value.sent


@pytest.mark.parametrize('mutation', [
    lambda p: p['endpoint'].update(profile_id='wrong'),
    lambda p: p['endpoint'].update(capabilities=['session-authority-v1']),
    lambda p: p['endpoint'].update(control_home='C:/outside'),
    lambda p: p.update(url=p['url']+'?ticket=leak'),
    lambda p: p.update(client_code_sha='other'),
    lambda p: p['endpoint'].update(api_origin='http://localhost:1234'),
])
def test_attach_refuses_mismatched_identity_capabilities_or_origin(setup_client, mutation):
    def server(ws):
        try:
            req = json.loads(ws.recv()); respond(ws, req, DESC)
        except Exception:
            pass
    with pytest.raises(gp.GatewayProtocolError):
        setup_client[0](server, mutation)()


def test_bad_json_duplicate_rejected(setup_client):
    def server(ws):
        req = json.loads(ws.recv()); respond(ws, req, DESC)
        ws.recv(); ws.send('{"jsonrpc":"2.0","id":2,"id":2,"result":{}}')
    client = setup_client[0](server)()
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('session.info', {})
    assert exc.value.ambiguous


def test_invalid_local_paths_and_methods(setup_client):
    _, root, home = setup_client
    with pytest.raises(gp.GatewayProtocolError):
        gp.GatewayProtocolClient.connect(profile='../worker', home=home, root=root)
    with pytest.raises(gp.GatewayProtocolError):
        gp.GatewayProtocolClient.connect(profile='default', home=home, root=root)
    client = gp.GatewayProtocolClient(None)
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('runtime.restart', {})
    assert not exc.value.sent


def test_bounded_capture_and_clean_environment(tmp_path, monkeypatch):
    # Real isolated subprocess, not the Hermes CLI or any live owner.
    import sys
    with pytest.raises(gp.GatewayProtocolError) as exc:
        gp._run_attach([sys.executable, '-c', 'print("x" * 1100000)'], {}, 5)
    assert exc.value.code == 'attach_unavailable'


def test_public_cli_refuses_absent_isolated_owner(tmp_path):
    root = tmp_path / 'isolated-cli-home'
    root.mkdir()
    argv, env = gp._command('default', root, 2.0)
    assert argv.count('--profile') == 1
    assert '--start' not in argv and '--recover' not in argv
    with pytest.raises(gp.GatewayProtocolError) as exc:
        gp._run_attach(argv, env, 15)
    assert exc.value.code == 'attach_unavailable'


def test_source_native_create_descriptor():
    from gateway.session_policy import CREATE_FIELDS, SURFACES
    assert 'tool' in SURFACES
    assert {'source', 'cwd', 'request_id'} <= set(CREATE_FIELDS)


def test_event_gap_and_ticket_erasure(setup_client):
    def server(ws):
        req = json.loads(ws.recv()); respond(ws, req, DESC)
        req = json.loads(ws.recv())
        for n in range(260):
            ws.send(json.dumps({'jsonrpc': '2.0', 'method': 'session.event', 'params': {'n': n}}))
        respond(ws, req, {})
    client = setup_client[0](server)()
    assert 'Sec-WebSocket-Protocol' not in client._ws.request.headers
    assert client._ws.protocol.available_subprotocols is None
    client.call('session.info', {})
    events = client.drain_events()
    assert len(events) == 257 and events[-1]['method'] == 'transport.event_gap'
    assert client.drain_events() == []
    client.close()


def test_dead_socket_not_retried(setup_client):
    def server(ws):
        req = json.loads(ws.recv()); respond(ws, req, DESC)
        ws.recv(); ws.close()
    client = setup_client[0](server)()
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('prompt.submit', {})
    assert exc.value.sent and exc.value.ambiguous
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('prompt.submit', {})
    assert not exc.value.sent


def test_bad_literal_path_and_oversized_request(setup_client):
    _, root, home = setup_client
    with pytest.raises(gp.GatewayProtocolError):
        gp.GatewayProtocolClient.connect(profile='worker', home=str(root) + '/profiles/../profiles/worker', root=root)
    client = gp.GatewayProtocolClient(None)
    with pytest.raises(gp.GatewayProtocolError) as exc:
        client.call('prompt.submit', {'text': 'x' * (gp._LIMIT + 1)})
    assert exc.value.code == 'request_too_large' and not exc.value.sent

