from contextlib import nullcontext
from pathlib import Path
import copy
import json
import pytest

from model_router.full_profile_policy import FullProfilePolicy


class Context:
    def __init__(self, home):
        self.home = home
        self._value = None
        self.writes = 0
    @property
    def value(self):
        return self._value
    @value.setter
    def value(self, value):
        # A settings-writer fixture must update the same raw authority record
        # as its getter; an unrelated in-memory cache is not permission.
        self._value = copy.deepcopy(value)
        config = {'plugins': {'entries': {'model-router': {'settings': {'profile_jobs': value}}}}}
        (self.home / 'config.yaml').write_text(json.dumps(config), encoding='utf-8')
    def get_config(self, key, default=None):
        assert key == 'profile_jobs'
        return copy.deepcopy(self.value) if self.value is not None else default
    def set_config(self, key, value):
        assert key == 'profile_jobs'
        self.value = copy.deepcopy(value)
        self.writes += 1


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / 'hermes'
    target = root / 'profiles' / 'worker'
    target.mkdir(parents=True)
    (root / 'config.yaml').write_text('{}', encoding='utf-8')
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    (target / 'config.yaml').write_text('terminal:\n  cwd: '+str(cwd).replace('\\', '/')+'\n', encoding='utf-8')
    ctx = Context(root)
    make = lambda: FullProfilePolicy(ctx, root, scope_factory=lambda home: nullcontext())
    return ctx, make, cwd, target


def test_inert_default_and_explicit_grant(setup):
    ctx, make, cwd, _ = setup
    p = make()
    before = p.describe()
    assert before['origin_profile'] == 'default'
    assert before['policy'] == {'schema': 1, 'enabled': False, 'targets': []}
    assert ctx.writes == 0
    with pytest.raises(PermissionError):
        p.grant('worker')
    after = p.configure({'expected_revision': before['revision'], 'enabled': True, 'targets': ['worker'], 'acknowledge_scope': True})
    assert after['policy']['targets'] == ['worker']
    assert Path(p.grant('worker')['cwd']) == cwd
    assert ctx.writes == 1
    assert after['completion_delivery'] == 'explicit_result'


def test_incarnation_stale_revision_and_origin_assertion(setup):
    ctx, make, _, _ = setup
    first, replacement = make(), make()
    old = first.describe()['revision']
    assert old != replacement.describe()['revision']
    args = {'expected_revision': old, 'enabled': True, 'targets': ['worker'], 'acknowledge_scope': True}
    with pytest.raises(ValueError, match='revision_conflict'):
        replacement.configure(args)
    with pytest.raises(PermissionError):
        first.configure({**args, 'profile': 'worker'})
    assert ctx.writes == 0


def test_changed_cwd_revokes_grant(setup):
    _, make, _, target = setup
    p = make()
    p.configure({'expected_revision': p.describe()['revision'], 'enabled': True, 'targets': ['worker'], 'acknowledge_scope': True})
    other = target.parent.parent.parent / 'other'
    other.mkdir()
    (target / 'config.yaml').write_text('terminal:\n  cwd: '+str(other).replace('\\', '/')+'\n', encoding='utf-8')
    with pytest.raises(PermissionError, match='grant_stale'):
        p.grant('worker')
    assert next(x for x in p.describe()['targets'] if x['profile'] == 'worker')['reason_code'] == 'cwd_changed'


def test_invalid_config_and_scope_acknowledgement_fail_closed(setup):
    ctx, make, _, _ = setup
    p = make()
    with pytest.raises(ValueError):
        p.configure({'expected_revision': p.describe()['revision'], 'enabled': True, 'targets': ['worker'], 'acknowledge_scope': False})
    ctx.value = {'schema': 1, 'enabled': True, 'targets': ['worker']}
    with pytest.raises(ValueError):
        p.grant('worker')
    assert ctx.writes == 0
