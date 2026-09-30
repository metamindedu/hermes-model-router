"""Readable task identity without forged delegates or private log forwarding."""
from types import SimpleNamespace
import pytest
from model_router.runtime_tracking import RouteRuntime
from model_router import task_presentation as view
from test_routing import _make_router, _load


def test_native_label_and_terminal_summary_are_human_readable(tmp_path):
    adopted, output, events = [], [], []
    class Registry:
        def adopt_local(self, process, **kwargs):
            adopted.append(kwargs)
            return SimpleNamespace(id='proc_123', append_output=output.append)
    runtime = RouteRuntime('parent', 'key', 'owner', Registry(), lambda *e: events.append(e) or True)
    runtime.track(SimpleNamespace(pid=42), job_id='12345678-1234-1234-1234-123456789012',
                  purpose='independent-review', cwd=str(tmp_path), title='게시 안전성 독립 검수',
                  role='HEAVYWEIGHT', model='test-heavy', provider='test-provider', profile='claire')
    assert adopted[0]['command'] == '모델 작업: 게시 안전성 독립 검수 · Heavy · test-heavy'
    assert '12345678' not in adopted[0]['command']
    text = ''.join(output)
    assert '게시 안전성 독립 검수' in text and '독립 검수' in text
    assert '대상 모델' in text and 'test-heavy' in text and 'claire' in text
    assert '123456789012' in text
    assert all(e[0] == 'status.update' for e in events)
    assert adopted[0]['notify_on_complete'] is False


@pytest.mark.parametrize('title', ['', 'x'*97, 'a\nb', 'a\x1bb', 'a\u202eb', 123])
def test_invalid_title_is_rejected_before_launch(tmp_path, monkeypatch, title):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    work = tmp_path/'work'; work.mkdir()
    with pytest.raises(ValueError):
        router.start('implementation', 'SECRET_PROMPT_CANARY', work, title=title)
    assert calls == []


def test_title_snapshot_only_not_prompt_inference(tmp_path, monkeypatch):
    router, service, root, calls = _make_router(tmp_path, monkeypatch)
    work = tmp_path/'work'; work.mkdir()
    out = router.start('implementation', 'SECRET_PROMPT_CANARY', work, title='설정 UI 수정')
    snapshot = _load(root/'profiles/claire/plugin-data/model-router/jobs'/out['job_id']/'snapshot.json')
    assert snapshot['title'] == '설정 UI 수정'
    assert out['title'] == '설정 UI 수정'
    assert 'SECRET_PROMPT_CANARY' not in snapshot['title']
    assert view.validate_title(None, 'mechanical') == '테스트 및 검증'


def test_forced_redaction_and_control_rejection():
    text = view.safe_display('token=ghp_' + 'a'*40, 160)
    assert 'a'*40 not in text
    assert view.validate_title('한글 작업명', 'plan') == '한글 작업명'


def test_maximum_title_and_seed_failure_preserve_actual_adoption(tmp_path, monkeypatch):
    assert view.validate_title('가'*96, 'plan') == '가'*96
    router, _, _, calls = _make_router(tmp_path, monkeypatch)
    adopted = []
    class Registry:
        def adopt_local(self, process, **kwargs):
            adopted.append(process)
            def fail(text): raise RuntimeError('SECRET_SEED_ERROR_CANARY')
            return SimpleNamespace(id='proc_adopted', append_output=fail)
    runtime = RouteRuntime('parent', 'key', 'task', Registry(), lambda *e: True)
    router.runtime = runtime
    work = tmp_path/'work'; work.mkdir()
    result = router.start('mechanical', 'SECRET_PROMPT_CANARY', work, title='테스트')
    assert len(calls) == len(adopted) == 1
    assert result['status'] == 'running'
    assert result['process_id'] == 'proc_adopted'
    assert result['ui_seeded'] is False
    assert result['tracking_error'] == 'DesktopSeedUnavailable'
    assert 'SECRET_SEED_ERROR_CANARY' not in str(result)


def test_sanitizer_unavailable_fails_closed(monkeypatch):
    def fail(text): raise RuntimeError('SECRET_ERROR')
    monkeypatch.setattr(view, '_force_redact', fail)
    assert 'SECRET' not in view.safe_display('SECRET_VALUE', 96)
    assert 'SECRET' not in view.validate_title('SECRET_VALUE', 'plan')
