from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_policy_uses_native_delegation_and_no_process_jobs():
    text = (ROOT / 'skills/adaptive-coding-orchestration/SKILL.md').read_text(encoding='utf-8')
    assert 'NEW work uses the real `delegate_task`' in text
    assert 'do not poll job files, manufacture handles, adopt processes' in text
    for retired in ('coding_route(action="start")', 'Historical process jobs', '`join`', 'start_retired'):
        assert retired not in text
