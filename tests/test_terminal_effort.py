"""Effort is display-only launch metadata, not a model identity claim."""
from types import SimpleNamespace

import pytest

from model_router.runtime_tracking import RouteRuntime
from model_router.task_presentation import terminal_seed
from test_routing import _make_router, _load


@pytest.mark.parametrize('effort', ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'])
def test_terminal_model_has_literal_effort(effort):
    text = terminal_seed(title='검증', purpose='mechanical', role='LIGHTWEIGHT',
                         model='test-model', provider='test-provider', profile='claire',
                         job_id='test-id', cwd_basename='work', reasoning=effort)
    assert f'대상 모델: test-model ({effort}) · 제공자: test-provider' in text
    assert text.splitlines()[0].endswith(f'test-model ({effort})')
    assert len(text) <= 2048


@pytest.mark.parametrize('effort', [None, '', 123, {}, [], 'HIGH', ' high ', 'secret-canary', 'high\nsecret-canary', '\x1b[31mhigh'])
def test_unknown_effort_never_echoes_untrusted_values(effort):
    text = terminal_seed(title='검증', purpose='mechanical', role='LIGHTWEIGHT',
                         model='test-model', provider='test-provider', profile='claire',
                         job_id='test-id', cwd_basename='work', reasoning=effort)
    assert '대상 모델: test-model (미지정)' in text
    assert 'secret-canary' not in text and '\x1b' not in text


@pytest.mark.parametrize('purpose,expected', [('mechanical', 'low'), ('independent-review', 'high')])
def test_router_forwards_selected_snapshot_effort_to_native_terminal(tmp_path, monkeypatch, purpose, expected):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    output, commands = [], []
    class Registry:
        def adopt_local(self, process, **kwargs):
            commands.append(kwargs['command'])
            return SimpleNamespace(id='proc_effort', append_output=output.append)
    router.runtime = RouteRuntime('parent', 'key', 'task', Registry(), lambda *a: True)
    work = tmp_path / 'work'
    work.mkdir()
    result = router.start(purpose, 'PRIVATE_PROMPT_CANARY', work, title='Effort 표시 검증')
    snapshot = _load(root / 'profiles/claire/plugin-data/model-router/jobs' / result['job_id'] / 'snapshot.json')
    selected = snapshot['model_provider_evidence']['requested'][result['route_class']]
    assert selected['reasoning'] == expected
    assert f"대상 모델: {selected['model']} ({expected})" in ''.join(output)
    assert '(' not in commands[0]  # Background rail label is intentionally unchanged.
    assert 'PRIVATE_PROMPT_CANARY' not in ''.join(output)
    assert len(calls) == 1 and result['process_id'] == 'proc_effort'
