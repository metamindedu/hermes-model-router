import importlib.util
import json
from pathlib import Path
import sqlite3
import uuid

spec = importlib.util.spec_from_file_location('session_source_repair', Path(__file__).resolve().parents[1] / 'scripts/repair_routed_session_sources.py')
repairer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repairer)


def fixture(tmp_path):
    home = tmp_path / 'profiles/claire'; home.mkdir(parents=True)
    db = sqlite3.connect(home / 'state.db')
    db.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY,source TEXT,parent_session_id TEXT,model TEXT,message_count INTEGER)')
    db.execute('CREATE TABLE messages(session_id TEXT,content TEXT)')
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for sid, source in zip(ids, ['model-router-coding-route','cli','model-router-coding-route']):
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (sid, source, None, 'model', 1))
        db.execute('INSERT INTO messages VALUES (?,?)', (sid, 'TRANSCRIPT_PRESERVE_CANARY'))
    job, attempt = str(uuid.uuid4()),str(uuid.uuid4())
    directory = home / 'plugin-data/model-router/jobs' / job / 'attempts' / attempt
    directory.mkdir(parents=True)
    req = {'schema':1,'home':str(home),'profile':'claire','source':'model-router-coding-route','job_id':job,'attempt_id':attempt,'session_id':ids[0]}
    path = directory / 'attempt-request.json'; path.write_text(json.dumps(req))
    db.commit(); db.close()
    return home,ids,path,req


def test_exact_artifact_source_cas_repair_preserves_all_other_data(tmp_path):
    home, ids, path, req = fixture(tmp_path)
    dry = repairer.repair(home)
    assert dry['eligible_count'] == 1 and dry['changed_count'] == 0
    assert not (home / 'backups').exists()
    before = sqlite3.connect(home / 'state.db')
    messages = before.execute('SELECT * FROM messages').fetchall(); before.close()
    applied = repairer.repair(home,apply=True)
    assert applied['changed_count'] == 1 and applied['verified']
    backup = json.loads(Path(applied['backup']).read_text())
    assert backup['rows'] == [{'session_id':ids[0],'source':'model-router-coding-route'}]
    assert 'TRANSCRIPT' not in Path(applied['backup']).read_text()
    after = sqlite3.connect(home / 'state.db')
    assert after.execute('SELECT * FROM messages').fetchall() == messages
    for sid,expected in zip(ids,['subagent','cli','model-router-coding-route']):
        assert after.execute('SELECT source,parent_session_id,model,message_count FROM sessions WHERE id=?',(sid,)).fetchone() == (expected,None,'model',1)
    after.close()
    assert repairer.repair(home,apply=True)['changed_count'] == 0


def test_foreign_profile_home_or_mismatched_attempt_cannot_authorize_repair(tmp_path):
    home,ids,path,req = fixture(tmp_path)
    for key,value in [('profile','other'),('home',str(tmp_path)),('attempt_id',str(uuid.uuid4())),('job_id','../bad'),('session_id','../bad')]:
        path.write_text(json.dumps({**req,key:value}))
        assert repairer.repair(home,apply=True)['changed_count'] == 0
    assert not (home/'backups').exists()


def test_artifact_does_not_reclassify_unrelated_cli_row(tmp_path):
    home,ids,path,req = fixture(tmp_path)
    path.write_text(json.dumps({**req,'session_id':ids[1]}))
    assert repairer.repair(home,apply=True)['changed_count'] == 0


def test_cas_conflict_rolls_back_the_entire_source_repair(tmp_path):
    import pytest
    home, ids, path, req = fixture(tmp_path)
    second = path.parent.parent / str(uuid.uuid4()) / 'attempt-request.json'
    second.parent.mkdir()
    second.write_text(json.dumps({**req, 'attempt_id': second.parent.name, 'session_id': ids[2]}))
    db = sqlite3.connect(home / 'state.db')
    ordered = sorted([ids[0], ids[2]])
    db.execute("CREATE TRIGGER conflict_after_first AFTER UPDATE OF source ON sessions WHEN NEW.id='%s' BEGIN UPDATE sessions SET source='cli' WHERE id='%s'; END" % tuple(ordered))
    db.commit(); db.close()
    with pytest.raises(RuntimeError, match='source changed'):
        repairer.repair(home, apply=True)
    db = sqlite3.connect(home / 'state.db')
    assert [db.execute('SELECT source FROM sessions WHERE id=?', (sid,)).fetchone()[0] for sid in ordered] == ['model-router-coding-route'] * 2
    db.close()
