from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_completion_does_not_reuse_legacy_join_protocol():
    text = (ROOT/'skills/adaptive-coding-orchestration/SKILL.md').read_text(encoding='utf-8')
    assert 'NEW work uses the real `delegate_task`' in text
    assert 'coding_route(action="start")' in text
    assert 'Historical process jobs only' in text
    assert 'owner-bound `join`' in text
    assert 'not native completion acknowledgement' in text
    assert 'must not automatically rejoin' in text
