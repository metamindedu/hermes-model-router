import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from model_router import job_progress as progress
from model_router import routing, task_presentation


def store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / 'profiles' / 'claire'
    home.mkdir(parents=True)
    service = SimpleNamespace(base=tmp_path, active_profile=lambda: 'claire')
    monkeypatch.setattr(routing, '_pid_alive', lambda pid: pid == 111)
    monkeypatch.setattr(task_presentation, '_force_redact', lambda text: text.replace('SECRET_CANARY', '[REDACTED]'))
    return home, service


def job(home, parent='parent-1', ui='runtime-1', pid=111, state=None):
    job_id, attempt_id = str(uuid4()), str(uuid4())
    directory = home / 'plugin-data/model-router/jobs' / job_id
    snapshot = {'schema':1, 'job_id':job_id, 'profile':'claire',
        'parent_session_id':parent, 'ui_session_id':ui,
        'title':'작업', 'purpose':'mechanical', 'route_class':'LIGHTWEIGHT',
        'model_provider_evidence':{'requested':{'LIGHTWEIGHT':{'model':'model-1'}}}}
    launch = {'worker_pid':pid, 'process_id':'proc_' + job_id,
              'launched_at':datetime.now(timezone.utc).isoformat()}
    store(directory/'snapshot.json',snapshot)
    store(directory/'launch.json',launch)
    if state is not None:store(directory/'state.json',state)
    progress.index_job(home,snapshot,launch)
    return directory,snapshot,launch,attempt_id


def get(service,parent='parent-1',ui='runtime-1'):
    return progress.progress_for_parent(service,{'parent_session_id':parent,'ui_session_id':ui})


def test_exact_parent_profile_and_runtime_scope(setup):
    home,service=setup
    first=job(home)
    job(home,parent='other-parent')
    job(home,ui='old-runtime')
    out=get(service)
    assert len(out['jobs'])==1
    assert out['jobs'][0]['job_id']==first[1]['job_id']
    assert out['jobs'][0]['status']=='running'
    assert out['jobs'][0]['activity']=='응답 대기 중'
    assert out['profile']=='claire'
    assert get(service,parent='unknown')['jobs']==[]


def test_progress_identity_only_public_text_and_latest_attempt(setup):
    home,service=setup
    directory,snapshot,launch,attempt=job(home)
    store(directory/'prompt.txt',{'private':'NEVER_READ_PROMPT'})
    store(directory/'runner-result.json',{'answer':'NEVER_READ_RESULT'})
    public={**{k:snapshot[k] for k in ['job_id','profile','parent_session_id']},
            'schema':1,'attempt_id':attempt,'updated_at':1,'activity':'SECRET_CANARY tool activity'}
    store(directory/'attempts'/attempt/'public-progress.json',public)
    out=get(service)
    assert out['jobs'][0]['activity']=='[REDACTED] tool activity'
    assert 'NEVER_READ' not in json.dumps(out)
    other=str(uuid4())
    store(directory/'attempts'/other/'public-progress.json',{**public,'attempt_id':other,'updated_at':2,'activity':'Second event'})
    assert get(service)['jobs'][0]['activity']=='Second event'
    store(directory/'attempts'/other/'public-progress.json',{**public,'attempt_id':other,'updated_at':3,'profile':'other','activity':'FOREIGN'})
    assert 'FOREIGN' not in json.dumps(get(service))


def test_index_and_snapshot_cross_checks(setup):
    home,service=setup
    directory,snapshot,launch,_=job(home)
    store(directory/'launch.json',{**launch,'process_id':'proc_foreign'})
    assert get(service)['jobs']==[]
    store(directory/'launch.json',launch)
    store(directory/'snapshot.json',{**snapshot,'profile':'other'})
    assert get(service)['jobs']==[]


def test_bounded_payloads_and_controls(setup):
    home,service=setup
    directory,snapshot,launch,attempt=job(home)
    public={**snapshot,'schema':1,'attempt_id':attempt,'updated_at':1,'activity':'X'*6000}
    store(directory/'attempts'/attempt/'public-progress.json',public)
    assert get(service)['jobs'][0]['activity']=='응답 대기 중'
    store(directory/'snapshot.json',{**snapshot,'title':'bad\x1btitle'})
    assert get(service)['jobs']==[]


def test_terminal_not_semantic_go_and_row_limit(setup):
    home,service=setup
    now=datetime.now(timezone.utc).isoformat()
    job(home,pid=222,state={'status':'finished','finished_at':now,'worker_exit_code':0,'runner_exit_code':0})
    row=get(service)['jobs'][0]
    assert row['status']=='completed'
    assert row['finished_at'] is not None
    assert 'GO' not in json.dumps(row)
    for _ in range(progress.MAX_ROWS+2):job(home)
    out=get(service)
    assert len(out['jobs'])==progress.MAX_ROWS
    assert out['has_more'] is True


@pytest.mark.parametrize('body',[{}, {'parent_session_id':'../escape','ui_session_id':'x'},
    {'parent_session_id':'a','ui_session_id':'b','profile':'other'},
    {'parent_session_id':'a','ui_session_id':'b\n'}])
def test_bad_scope_fails_closed(setup,body):
    with pytest.raises(ValueError):progress.progress_for_parent(setup[1],body)


def test_latest_registration_survives_index_capacity(setup, monkeypatch):
    home, service = setup
    monkeypatch.setattr(progress, 'MAX_INDEX', 3)
    for _ in range(4):
        directory, snapshot, launch, _attempt = job(home, pid=222, state={
            'status':'finished', 'finished_at':'2020-01-01T00:00:00Z',
            'worker_exit_code':0, 'runner_exit_code':0})
    newest = job(home)
    assert get(service)['jobs'][0]['job_id'] == newest[1]['job_id']
    # Persistent index is bounded, not an unbounded directory whose first
    # enumeration slice can permanently exclude the newest active job.
    path = progress._index_root(home, 'parent-1', 'runtime-1') / 'index.json'
    assert len(json.loads(path.read_text())['jobs']) <= 3


def test_concurrent_index_registration_is_not_lost(setup):
    from concurrent.futures import ThreadPoolExecutor
    home, service = setup
    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(lambda _n: job(home), range(8)))
    assert {row['job_id'] for row in get(service)['jobs']} == {row[1]['job_id'] for row in created}


def test_corrupt_manifest_refuses_overwrite_and_fails_closed(setup):
    home, service = setup
    job(home)
    path = progress._index_root(home, 'parent-1', 'runtime-1') / 'index.json'
    path.write_text('{broken', encoding='utf-8')
    assert get(service)['jobs'] == []
    with pytest.raises(ValueError):
        job(home)
    assert path.read_text() == '{broken'


def test_symlink_directory_denied(setup,tmp_path):
    home,service=setup
    directory,snapshot,launch,_=job(home)
    index=progress._index_root(home,'parent-1','runtime-1')
    foreign=tmp_path/'foreign';foreign.mkdir()
    old=index.with_name(index.name+'-original')
    index.rename(old)
    try:index.symlink_to(foreign,target_is_directory=True)
    except OSError:
        pytest.skip('platform denies test symlink creation')
    with pytest.raises(ValueError):get(service)
