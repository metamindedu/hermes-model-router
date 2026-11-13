"""Current raw grants must agree with the original public native context getter.

Synthetic homes and substituted target transport only; no Gateway/provider use.
"""
import copy
import json
import time
from contextlib import contextmanager

import pytest

from model_router.full_profile_policy import FullProfilePolicy, PolicyWriteUnknown
from model_router.profile_jobs import ProfileJobs, JobError
from test_profile_jobs import Gateway


@contextmanager
def native_policy(tmp_path, *, subtree='settings', envelope=True):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.plugins import PluginContext, PluginManifest
    root = tmp_path / 'home'
    worker = root / 'profiles/worker'
    worker.mkdir(parents=True)
    cwd = tmp_path / 'workspace'; cwd.mkdir()
    (worker / 'config.yaml').write_text(json.dumps({'terminal': {'cwd': str(cwd)}}), encoding='utf-8')
    grant = {'schema': 1, 'enabled': True, 'targets': ['worker'], 'cwd': {'worker': str(cwd)}, 'revision': 1}
    initial = {'model': {'provider': 'openrouter', 'default': 'offline-fixture'},
               'plugins': {'entries': {'model-router': {subtree: {'profile_jobs': [grant] if envelope else grant}}}}}
    cfg = root / 'config.yaml'; cfg.write_text(json.dumps(initial), encoding='utf-8')
    token = set_hermes_home_override(root)
    manager = None
    try:
        ctx = PluginContext(PluginManifest(name='model-router'), None)
        policy = FullProfilePolicy(ctx, root)
        # Positive control primes the real loader's last-known-good value.
        assert policy.grant('worker')['profile'] == 'worker'
        assert policy.operator_status({'targets': ['worker']})['policy']['enabled'] is True
        gateway = Gateway()
        manager = ProfileJobs(ctx, root, client_factory=gateway.factory, alive=lambda: True, poll_seconds=.02)
        yield ctx, policy, manager, gateway, initial, cfg
    finally:
        if manager is not None:
            manager.close()
            for thread in manager.threads.values():
                thread.join(timeout=3)
                assert not thread.is_alive()
        reset_hermes_home_override(token)


def revoke(initial, *, subtree='settings', envelope=True):
    raw = copy.deepcopy(initial)
    off = {'schema': 1, 'enabled': False, 'targets': [], 'cwd': {}, 'revision': 2}
    raw['plugins']['entries']['model-router'][subtree]['profile_jobs'] = [off] if envelope else off
    # Valid JSON/YAML, but native legacy-turn preprocessing fails and serves LKG.
    raw.update(max_turns=3, agent=5)
    return raw


@pytest.mark.parametrize('subtree', ['settings', 'config'])
@pytest.mark.parametrize('envelope', [True, False])
def test_real_native_fallback_cannot_authorize_raw_revocation(tmp_path, subtree, envelope):
    from hermes_cli.config import load_config_readonly
    with native_policy(tmp_path, subtree=subtree, envelope=envelope) as (ctx, policy, manager, gateway, initial, cfg):
        cfg.write_text(json.dumps(revoke(initial, subtree=subtree, envelope=envelope)), encoding='utf-8')
        assert type(load_config_readonly()).__name__ == 'FailedConfigRead'
        for operation in [lambda: policy.grant('worker'),
                          lambda: policy.operator_status({'targets': ['worker']}),
                          lambda: manager.start({'action': 'start', 'profile': 'worker', 'request_id': 'revoked-start',
                                                 'goal': 'SYNTHETIC_ONLY'}, 'parent', 'parent')]:
            with pytest.raises(ValueError, match='^origin_config_unavailable$'):
                operation()
        with pytest.raises(ValueError, match='^origin_config_unavailable$'):
            with policy.guard('worker'):
                pytest.fail('revoked authority entered the admission guard')
        assert gateway.calls == []
        assert not manager.journal.path.exists()  # refused before reservation


@pytest.mark.parametrize('remove', ['leaf', 'entry', 'plugins'])
def test_missing_raw_grant_does_not_inherit_last_known_good_authority(tmp_path, remove):
    with native_policy(tmp_path) as (_, policy, manager, gateway, initial, cfg):
        raw = copy.deepcopy(initial)
        if remove == 'leaf':
            raw['plugins']['entries']['model-router']['settings'].pop('profile_jobs')
        elif remove == 'entry':
            raw['plugins']['entries'].pop('model-router')
        else:
            raw.pop('plugins')
        raw.update(max_turns=3, agent=5)
        cfg.write_text(json.dumps(raw), encoding='utf-8')
        with pytest.raises(ValueError, match='^origin_config_unavailable$'):
            policy.grant('worker')
        assert gateway.calls == [] and not manager.journal.path.exists()


def test_real_native_fallback_raw_revocation_prevents_existing_job_steer(tmp_path):
    with native_policy(tmp_path) as (_, policy, manager, gateway, initial, cfg):
        job = manager.start({'action': 'start', 'profile': 'worker', 'request_id': 'healthy-start',
                             'goal': 'SYNTHETIC_ONLY'}, 'parent', 'parent')
        deadline = time.monotonic() + 5
        record = {}
        while time.monotonic() < deadline:
            record = manager.journal.read()['jobs'][job['id']]
            if record['status'] == 'running' and record['admission_id']:
                break
            time.sleep(.01)
        assert record['status'] == 'running' and record['admission_id']
        assert sum(method == 'session.create' for method, _ in gateway.calls) == 1
        assert sum(method == 'prompt.submit' for method, _ in gateway.calls) == 1
        cfg.write_text(json.dumps(revoke(initial)), encoding='utf-8')
        with pytest.raises(JobError, match='^control_refused$'):
            manager.control('parent', {'job_id': job['id'], 'operation': 'steer', 'text': 'SYNTHETIC_ONLY'})
        assert not any(method == 'session.steer' for method, _ in gateway.calls)


def test_native_setter_unknown_is_not_reported_as_successful_revocation(tmp_path):
    from model_router.yaml_compat import yaml
    with native_policy(tmp_path) as (_, policy, _, gateway, initial, cfg):
        broken = copy.deepcopy(initial); broken.update(max_turns=3, agent=5)
        cfg.write_text(json.dumps(broken), encoding='utf-8')
        snapshot = policy.operator_status({'targets': []})
        with pytest.raises(PolicyWriteUnknown, match='^policy_write_unknown$'):
            policy.operator_configure({'expected_operator_revision': snapshot['operator_revision'],
                'enabled': False, 'targets': [], 'acknowledge_scope': True})
        # The setter did NOT save revocation. Do not invent successful raw OFF.
        raw = yaml.safe_load(cfg.read_text(encoding='utf-8'))
        assert raw['plugins']['entries']['model-router']['settings']['profile_jobs'][0]['enabled'] is True
        assert policy.grant('worker')['profile'] == 'worker'
        assert gateway.calls == []


@pytest.mark.parametrize('phase', ['connect', 'created'])
def test_native_raw_revocation_is_rechecked_before_create_and_submit(tmp_path, phase):
    with native_policy(tmp_path) as (_, policy, manager, gateway, initial, cfg):
        revoked = json.dumps(revoke(initial))
        if phase == 'connect':
            def factory(**kwargs):
                cfg.write_text(revoked, encoding='utf-8')
                return gateway.factory(**kwargs)
            manager.client_factory = factory
        else:
            def after_create(method, params):
                if method == 'session.create':
                    cfg.write_text(revoked, encoding='utf-8')
            gateway.phase_check = after_create
        job = manager.start({'action': 'start', 'profile': 'worker', 'request_id': 'recheck-' + phase,
                             'goal': 'SYNTHETIC_ONLY'}, 'parent', 'parent')
        thread = manager.threads[job['id']]
        thread.join(timeout=5)
        assert not thread.is_alive()
        record = manager.journal.read()['jobs'][job['id']]
        assert record['status'] in ('failed', 'unknown') and record['admission_id'] is None
        assert sum(method == 'session.create' for method, _ in gateway.calls) == (1 if phase == 'created' else 0)
        assert not any(method == 'prompt.submit' for method, _ in gateway.calls)


def test_raw_settings_null_masks_legacy_config_grant_without_read_migration(tmp_path):
    with native_policy(tmp_path, subtree='config') as (_, policy, _, gateway, initial, cfg):
        raw = copy.deepcopy(initial)
        raw['plugins']['entries']['model-router']['settings'] = {'profile_jobs': None}
        text = json.dumps(raw); cfg.write_text(text, encoding='utf-8')
        with pytest.raises(PermissionError, match='^grant_denied$'):
            policy.grant('worker')
        assert policy.operator_status({'targets': []})['policy']['enabled'] is False
        assert cfg.read_text(encoding='utf-8') == text and gateway.calls == []
