"""Operator snapshots are distinct from process-local execution revisions."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from test_full_profile_policy import setup
from model_router.full_profile_policy import PolicyWriteUnknown


def body(snapshot, *, enabled=True, targets=None):
    return {'expected_operator_revision': snapshot['operator_revision'], 'enabled': enabled,
            'targets': [r['profile'] for r in snapshot['review_targets']] if targets is None else targets,
            'acknowledge_scope': True}


def test_snapshot_survives_process_incarnation_and_exact_write_readback(setup):
    ctx, make, cwd, _ = setup
    first, second = make(), make()
    before = first.operator_status({'targets': ['worker']})
    assert first.describe()['revision'] != second.describe()['revision']
    assert before == second.operator_status({'targets': ['worker']})
    saved = second.operator_configure(body(before))
    assert saved['status'] == 'saved' and saved['no_effect'] is False
    assert saved['policy']['revision'] == 1 and ctx.writes == 1
    assert make().operator_status({'targets': ['worker']})['operator_revision'] == saved['operator_revision']
    assert saved['review_targets'][0]['cwd'] == str(cwd).replace('\\', '/')


def test_same_snapshot_competition_has_one_writer(setup):
    ctx, make, _, _ = setup
    snapshot = make().operator_status({'targets': ['worker']})
    barrier = threading.Barrier(2)
    def save(_):
        p = make(); barrier.wait()
        try:
            return p.operator_configure(body(snapshot))['status']
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save, range(2))) == ['revision_conflict', 'saved']
    assert ctx.writes == 1


def test_cwd_change_between_review_and_configure_is_not_silently_regranted(setup):
    ctx, make, cwd, target = setup
    snapshot = make().operator_status({'targets': ['worker']})
    other = cwd.parent / 'other-work'; other.mkdir()
    (target / 'config.yaml').write_text('terminal:\n  cwd: '+str(other).replace('\\', '/')+'\n', encoding='utf-8')
    with pytest.raises(ValueError, match='revision_conflict'):
        make().operator_configure(body(snapshot))
    assert ctx.writes == 0
    current = make().operator_status({'targets': ['worker']})
    assert current['review_targets'][0]['cwd'] == str(other).replace('\\', '/')
    assert make().operator_configure(body(current))['status'] == 'saved'


def test_noop_and_counter_fence_block_aba(setup):
    ctx, make, _, _ = setup
    p = make()
    empty = p.operator_status({'targets': []})
    assert p.operator_configure(body(empty, enabled=False))['status'] == 'noop'
    assert ctx.writes == 0
    old = p.operator_status({'targets': ['worker']})
    p.operator_configure(body(old))
    off = p.operator_status({'targets': []})
    p.operator_configure(body(off, enabled=False))
    assert ctx.value[0]['revision'] == 2
    with pytest.raises(ValueError, match='revision_conflict'):
        make().operator_configure(body(old))
    assert ctx.writes == 2


@pytest.mark.parametrize('extra', [{'human': True}, {'operator': True}, {'session_id': 'foreign'}, {'profile': 'worker'}, {'home': '/other'}, {'command': 'do not execute'}])
def test_cli_payload_cannot_supply_authority_or_owner(setup, extra):
    ctx, make, _, _ = setup
    p = make(); snapshot = p.operator_status({'targets': ['worker']})
    with pytest.raises(ValueError, match='invalid_params'):
        p.operator_configure({**body(snapshot), **extra})
    assert ctx.writes == 0


@pytest.mark.parametrize('targets', [['worker', 'worker'], ['../worker'], [' worker'], ['keep'], [None], ['worker'] * 33, 'worker'])
def test_invalid_targets_are_literal_refusals(setup, targets):
    ctx, make, _, _ = setup
    with pytest.raises(ValueError):
        make().operator_status({'targets': targets})
    assert ctx.writes == 0


def test_disabled_policy_cannot_expand_or_refresh_cwds(setup):
    ctx, make, _, _ = setup
    p = make(); snapshot = p.operator_status({'targets': ['worker']})
    with pytest.raises(ValueError, match='disabled_grant_expansion'):
        p.operator_configure(body(snapshot, enabled=False))
    p.operator_configure(body(snapshot))
    old_cwd = ctx.value[0]['cwd'].copy()
    p.operator_configure(body(p.operator_status({'targets': ['worker']}), enabled=False))
    assert ctx.value[0]['cwd'] == old_cwd and ctx.value[0]['enabled'] is False


def test_overflow_refuses_before_setter(setup):
    ctx, make, _, _ = setup
    ctx.value = {'schema': 1, 'enabled': False, 'targets': [], 'cwd': {}, 'revision': 2**53-1}
    p = make(); snapshot = p.operator_status({'targets': ['worker']})
    with pytest.raises(ValueError, match='revision_overflow'):
        p.operator_configure(body(snapshot))
    assert ctx.writes == 0


def test_setter_failure_after_effect_is_unknown_never_retried(setup, monkeypatch):
    ctx, make, _, _ = setup
    p = make(); snapshot = p.operator_status({'targets': ['worker']})
    setter = ctx.set_config
    def uncertain(key, value):
        setter(key, value)
        raise RuntimeError('PRIVATE_DIAGNOSTIC')
    monkeypatch.setattr(ctx, 'set_config', uncertain)
    with pytest.raises(PolicyWriteUnknown, match='^policy_write_unknown$'):
        p.operator_configure(body(snapshot))
    assert ctx.writes == 1
    assert make().operator_status({'targets': ['worker']})['policy']['enabled'] is True


def test_selected_review_is_not_truncated_by_inventory(setup, monkeypatch):
    _, make, _, _ = setup
    p = make()
    monkeypatch.setattr(p.service, '_discover_profiles', lambda: ['default'] + [f'p{i}' for i in range(40)] + ['worker'])
    snapshot = p.operator_status({'targets': ['worker']})
    assert [row['profile'] for row in snapshot['review_targets']] == ['worker']


def test_ambiguous_stale_lock_is_not_reaped(setup, monkeypatch):
    import model_router.full_profile_policy as module
    from model_router.service import _FileLock, ServiceError
    ctx, make, _, _ = setup
    p = make(); lock = p.home / 'plugin-data/model-router/.profile-jobs-policy.lock'
    lock.parent.mkdir(parents=True)
    locked = '{"pid":-1,"time":0,"token":"synthetic-stale-owner"}'
    lock.write_text(locked, encoding='utf-8')
    monkeypatch.setattr(module, '_FileLock', lambda path: _FileLock(path, timeout=.02))
    with pytest.raises(ServiceError):
        p.operator_status({'targets': []})
    assert lock.read_text(encoding='utf-8') == locked and ctx.writes == 0


@pytest.mark.parametrize('malformed', ['broken: [', '[1,2]', 'scalar'])
def test_last_known_good_getter_is_not_permission_after_bad_origin_config(setup, malformed):
    ctx, make, _, _ = setup
    p = make(); reviewed = p.operator_status({'targets': ['worker']})
    p.operator_configure(body(reviewed))
    (p.home / 'config.yaml').write_text(malformed, encoding='utf-8')
    with pytest.raises(ValueError, match='^origin_config_unavailable$'):
        p.grant('worker')
    assert ctx.writes == 1


def test_origin_change_during_effective_read_is_refused(setup, monkeypatch):
    ctx, make, _, _ = setup
    p = make(); getter = ctx.get_config
    def racing(key, default=None):
        value = getter(key, default)
        (p.home / 'config.yaml').write_text('{"unrelated_changed":true}', encoding='utf-8')
        return value
    monkeypatch.setattr(ctx, 'get_config', racing)
    with pytest.raises(ValueError, match='^origin_config_unavailable$'):
        p.operator_status({'targets': []})
    assert ctx.writes == 0

