"""Reproductions of the three independent-review boundary findings."""
from contextvars import copy_context
from types import SimpleNamespace
import json
from pathlib import Path
import errno

import pytest

from model_router import fast_inheritance as fi, scoped_agent, attempt_observer
from test_fast_inheritance import home, register, snap
from test_scoped_agent import attempt, _write_fast_job_snapshot, _emit_api_events


@pytest.mark.parametrize('extra_override', [False, True])
def test_paid_tier_is_not_added_to_a_different_final_wire_model(extra_override):
    request = {'model': 'gpt-6-astra', 'messages': [], 'service_tier': 'stale'}
    if extra_override:
        request['extra_body'] = {'model': 'unsupported-model', 'service_tier': 'stale'}
    else:
        request['model'] = 'unsupported-model'
    result = fi.apply_fast_snapshot(
        request, snap('priority'), model='gpt-6-astra', provider='openai-api',
        base_url='https://api.openai.com/v1', api_mode='chat_completions',
    )
    assert 'service_tier' not in result
    assert 'service_tier' not in result.get('extra_body', {})


@pytest.mark.parametrize('loss', ['ttl', 'cap'])
def test_real_dispatch_provenance_keeps_stale_paid_hints_blocked_after_cache_loss(monkeypatch, home, loss):
    parent = SimpleNamespace(session_id='root-A', service_tier=None)
    ctx, controller = register(monkeypatch, home, parent)
    execute = next(cb for kind, cb in ctx.middleware if kind == 'tool_execution')
    start = ctx.hooks['subagent_start'][0]
    llm = next(cb for kind, cb in ctx.middleware if kind == 'llm_request')
    now = [100.0]
    monkeypatch.setattr(controller, '_now', lambda: now[0])
    if loss == 'cap':
        monkeypatch.setattr(fi, 'MAX_CHILD_BINDINGS', 1)
    creator_context = []
    def dispatch():
        start(parent_session_id='root-A', child_session_id='child-A', child_subagent_id='native-A')
        creator_context.append(copy_context())
    execute(tool_name='delegate_task', args={}, session_id='root-A', next_call=dispatch)
    assert len(controller._children) == 1, 'Fixture must actually create a binding through dispatch'
    if loss == 'cap':
        execute(tool_name='delegate_task', args={}, session_id='root-A',
                next_call=lambda: start(parent_session_id='root-A', child_session_id='child-B', child_subagent_id='native-B'))
    else:
        now[0] += fi.BINDING_TTL_SECONDS + 1
    child = SimpleNamespace(session_id='child-A', _parent_session_id='root-A', _subagent_id='native-A',
                            platform='subagent', service_tier=None, model='gpt-6-astra', provider='openai-api',
                            base_url='https://api.openai.com/v1', api_mode='chat_completions')
    monkeypatch.setattr(fi, '_get_active_parent', lambda: child)
    request = {'model': child.model, 'service_tier': 'stale', 'speed': 'fast',
               'extra_body': {'service_tier': 'stale', 'speed': 'fast', 'keep': 1}}
    # Native execution uses a copy_context snapshot of its creation dispatch.
    result = creator_context[0].run(lambda: llm(
        request=request, session_id=child.session_id, model=child.model, provider=child.provider,
        base_url=child.base_url, api_mode=child.api_mode,
    ))
    assert result is not None, 'Previously authorized child must not fail open after cache cleanup'
    assert 'service_tier' not in result['request'] and 'speed' not in result['request']
    assert result['request']['extra_body'] == {'keep': 1}


def _normal_fast_job(attempt):
    value = {'schema': 1, 'profile': 'claire', 'origin_session_id': 'host-parent',
             'parent_session_id': 'host-parent', 'mode': 'normal', 'expires_at': None}
    _write_fast_job_snapshot(attempt, value, 'host-parent')
    # The attempted downgrade omits fast_snapshot and keeps legacy schema1.
    assert attempt['request']['schema'] == 1
    return value


def test_fast_job_cannot_downgrade_to_legacy_attempt_before_runtime(attempt):
    _normal_fast_job(attempt)
    prepared = []
    result = scoped_agent.run_attempt(attempt['request'], dependencies={'prepare_runtime': lambda request: prepared.append(request)})
    assert result['error']['kind'] == 'initialization_error'
    assert prepared == []


def test_observer_rejects_schema_downgrade_for_a_fast_job(attempt, monkeypatch):
    _normal_fast_job(attempt)
    monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
    monkeypatch.setenv('HERMES_PROFILE', 'claire')
    monkeypatch.setenv('MODEL_ROUTER_ATTEMPT_REQUEST', str(attempt['request_path']))
    _emit_api_events(attempt)
    observed = attempt_observer.snapshot()
    assert observed['observed_routes'] == []
    assert observed['evidence_complete'] is False


def _check_legacy_boundary(attempt, monkeypatch, consumer, *, rejected):
    if consumer == 'adapter':
        if rejected:
            prepared = []
            result = scoped_agent.run_attempt(attempt['request'], dependencies={
                'prepare_runtime': lambda request: prepared.append(request),
            })
            assert result['error']['kind'] == 'initialization_error'
            assert prepared == []
        else:
            validated, _, _ = scoped_agent._validate_request(attempt['request'], attempt['request_path'])
            assert validated['schema'] == 1
    else:
        attempt_observer.reset_for_tests()
        monkeypatch.setenv('HERMES_HOME', str(attempt['home']))
        monkeypatch.setenv('HERMES_PROFILE', 'claire')
        monkeypatch.setenv('MODEL_ROUTER_ATTEMPT_REQUEST', str(attempt['request_path']))
        _emit_api_events(attempt)
        observed = attempt_observer.snapshot()
        assert bool(observed['observed_routes']) is not rejected
        if rejected:
            assert observed['evidence_complete'] is False
        attempt_observer.reset_for_tests()


@pytest.mark.parametrize('consumer', ['adapter', 'observer'])
@pytest.mark.parametrize('error_kind', ['permission', 'io'])
def test_legacy_snapshot_metadata_error_cannot_masquerade_as_missing(attempt, monkeypatch, consumer, error_kind):
    _normal_fast_job(attempt)
    target = attempt['attempt_dir'].parent.parent / 'snapshot.json'
    original_lstat, original_exists, original_symlink = Path.lstat, Path.exists, Path.is_symlink
    def broken_lstat(path, *args, **kwargs):
        if path == target:
            if error_kind == 'permission':
                raise PermissionError(errno.EACCES, 'fixture metadata denied')
            raise OSError(errno.EIO, 'fixture metadata I/O failure')
        return original_lstat(path, *args, **kwargs)
    # Model pathlib's lossy boolean helpers without hiding unrelated path errors.
    monkeypatch.setattr(Path, 'exists', lambda path: False if path == target else original_exists(path))
    monkeypatch.setattr(Path, 'is_symlink', lambda path: False if path == target else original_symlink(path))
    monkeypatch.setattr(Path, 'lstat', broken_lstat)
    _check_legacy_boundary(attempt, monkeypatch, consumer, rejected=True)


@pytest.mark.parametrize('consumer', ['adapter', 'observer'])
@pytest.mark.parametrize('snapshot_present', [False, True])
def test_unambiguous_missing_and_normal_legacy_snapshot_stay_compatible(attempt, monkeypatch, consumer, snapshot_present):
    target = attempt['attempt_dir'].parent.parent / 'snapshot.json'
    if snapshot_present:
        target.write_text(json.dumps({'schema': 1, 'job_id': attempt['request']['job_id'], 'profile': 'claire'}), encoding='utf-8')
    else:
        with pytest.raises(FileNotFoundError):
            target.lstat()
    _check_legacy_boundary(attempt, monkeypatch, consumer, rejected=False)


@pytest.mark.parametrize('consumer', ['adapter', 'observer'])
@pytest.mark.parametrize('error_kind', ['permission', 'utf8'])
def test_legacy_snapshot_unreadable_or_invalid_utf8_fails_closed(attempt, monkeypatch, consumer, error_kind):
    target = attempt['attempt_dir'].parent.parent / 'snapshot.json'
    if error_kind == 'utf8':
        target.write_bytes(b'\xff\xfe\x00')
    else:
        target.write_text(json.dumps({'schema': 1, 'job_id': attempt['request']['job_id'], 'profile': 'claire'}), encoding='utf-8')
        original_read_text = Path.read_text
        def broken_read_text(path, *args, **kwargs):
            if path == target:
                raise PermissionError(errno.EACCES, 'fixture read denied')
            return original_read_text(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'read_text', broken_read_text)
    _check_legacy_boundary(attempt, monkeypatch, consumer, rejected=True)
