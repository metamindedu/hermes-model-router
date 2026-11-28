"""Reproductions of the three independent-review boundary findings."""
from contextvars import copy_context
from types import SimpleNamespace
import json
from pathlib import Path
import errno

import pytest

from model_router import fast_inheritance as fi
from test_fast_inheritance import home, register, snap


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
