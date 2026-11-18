"""Large settings bodies staged in pieces; parse memo and read scope used by status."""
import json
import os
import pytest
from model_router import staged_body as sb
from model_router.yaml_compat import yaml, _PARSED


def _stage_all(home, text, size=5000):
    stage_id = 'a' * 32
    pieces = [text[i:i + size] for i in range(0, len(text), size)]
    for index, chunk in enumerate(pieces):
        assert sb.stage(home, {'id': stage_id, 'index': index, 'total': len(pieces), 'chunk': chunk}) == {'staged': True, 'index': index}
    return {'staged': {'id': stage_id, 'total': len(pieces), 'length': sb.utf16_length(text)}}


def test_pieces_assemble_to_the_exact_body_and_are_removed(tmp_path):
    body = {'expected_revision': 3, 'updates': [{'profile': f'p{i}', 'note': '설명 "quoted" \\ 😀' * 40} for i in range(30)]}
    text = json.dumps(body, ensure_ascii=False)
    reference = _stage_all(tmp_path, text)
    # The page counts UTF-16 units: every emoji is two.
    assert reference['staged']['length'] == len(text) + text.count('😀')
    assert sb.is_reference(reference)
    assert sb.assemble(tmp_path, reference) == body
    assert not list((tmp_path / sb.STAGE_RELATIVE).glob('*.part'))


def test_missing_piece_wrong_length_and_nested_reference_are_refused(tmp_path):
    text = json.dumps({'k': 'v' * 12000})
    reference = _stage_all(tmp_path, text)
    os.unlink(tmp_path / sb.STAGE_RELATIVE / f"{'a' * 32}.001.part")
    with pytest.raises(ValueError):
        sb.assemble(tmp_path, reference)
    reference = _stage_all(tmp_path, text)
    reference['staged']['length'] += 1
    with pytest.raises(ValueError):
        sb.assemble(tmp_path, reference)
    nested = json.dumps({'staged': {'id': 'b' * 32, 'total': 2, 'length': 10}}) + ' ' * 6000
    with pytest.raises(ValueError):
        sb.assemble(tmp_path, _stage_all(tmp_path, nested))


@pytest.mark.parametrize('body', [
    {'id': 'A' * 32, 'index': 0, 'total': 2, 'chunk': 'x'},
    {'id': 'a' * 32, 'index': 2, 'total': 2, 'chunk': 'x'},
    {'id': 'a' * 32, 'index': 0, 'total': 1, 'chunk': 'x'},
    {'id': 'a' * 32, 'index': 0, 'total': 2, 'chunk': ''},
    {'id': 'a' * 32, 'index': 0, 'total': 2, 'chunk': 'x' * (sb.CHUNK_LIMIT + 1)},
    {'id': '../' + 'a' * 29, 'index': 0, 'total': 2, 'chunk': 'x'},
    {'id': 'a' * 32, 'index': 0, 'total': 2, 'chunk': 'x', 'extra': 1},
])
def test_invalid_pieces_are_refused(tmp_path, body):
    with pytest.raises(ValueError):
        sb.stage(tmp_path, body)


def test_abandoned_pieces_expire(tmp_path, monkeypatch):
    sb.stage(tmp_path, {'id': 'c' * 32, 'index': 0, 'total': 2, 'chunk': 'x'})
    old = tmp_path / sb.STAGE_RELATIVE / f"{'c' * 32}.000.part"
    past = old.stat().st_mtime - sb.TTL_SECONDS - 5
    os.utime(old, (past, past))
    sb.stage(tmp_path, {'id': 'd' * 32, 'index': 0, 'total': 2, 'chunk': 'y'})
    assert not old.exists()


def test_parse_memo_returns_independent_copies_of_the_same_content():
    _PARSED.clear()
    first = yaml.safe_load('a:\n  b: [1, 2]\n')
    first['a']['b'].append(3)
    assert yaml.safe_load('a:\n  b: [1, 2]\n') == {'a': {'b': [1, 2]}}
    assert yaml.safe_load('a: 2\n') == {'a': 2}
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load('a: [\n')


def test_read_scope_memoizes_only_inside_the_scope():
    from model_router.service import read_scope, scoped
    calls = []
    compute = lambda: calls.append(1) or ['x']
    scoped('k', compute); scoped('k', compute)
    assert len(calls) == 2
    with read_scope():
        value = scoped('k', compute)
        value.append('mutated')
        assert scoped('k', compute) == ['x']
    assert len(calls) == 3


@pytest.mark.skipif(os.name != 'nt', reason='directory junctions are Windows-only')
def test_a_linked_staging_directory_is_refused_before_any_write_or_removal(tmp_path):
    import subprocess
    home = tmp_path / 'home'
    outside = tmp_path / 'outside'
    (home / 'plugin-data').mkdir(parents=True)
    outside.mkdir()
    keep = outside / f"{'e' * 32}.000.part"
    keep.write_text('outside', encoding='utf-8')
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(home / 'plugin-data' / 'model-router'), str(outside)], check=True, capture_output=True)
    with pytest.raises(Exception):
        sb.stage(home, {'id': 'e' * 32, 'index': 1, 'total': 2, 'chunk': 'x'})
    with pytest.raises(Exception):
        sb.assemble(home, {'staged': {'id': 'e' * 32, 'total': 2, 'length': 10}})
    assert keep.read_text(encoding='utf-8') == 'outside'
    assert sorted(p.name for p in outside.iterdir()) == [keep.name]


def test_raw_config_memo_never_caches_a_different_read(tmp_path, monkeypatch):
    from model_router import effective_config as ec
    from hermes_cli import config_backend
    monkeypatch.setattr(ec, '_RAW_READS', None)
    config = tmp_path / 'config.yaml'
    config.write_text('a: 1\n', encoding='utf-8')
    def racing_read(path):
        # The host read sees other content than the bytes the memo keyed (A -> B -> A).
        return {'a': 'B'}
    monkeypatch.setattr(config_backend, 'get_config_backend', lambda: config_backend.FileBackend())
    read = ec._memoized_raw_reader(racing_read)
    assert read(config) == {'a': 1}
    first = read(config); first['a'] = 'mutated'
    assert read(config) == {'a': 1}
    config.write_text('a: 2\n', encoding='utf-8')
    assert read(config) == {'a': 2}
    assert read(tmp_path / 'missing.yaml') == {}


@pytest.mark.skipif(os.name != 'nt', reason='directory junctions are Windows-only')
def test_a_directory_swapped_after_inspection_stops_reads_and_cleanup(tmp_path, monkeypatch):
    import shutil
    import subprocess
    home = tmp_path / 'home'
    home.mkdir()
    reference = _stage_all(home, json.dumps({'k': 'v' * 12000}))
    staged = home / sb.STAGE_RELATIVE
    outside = tmp_path / 'outside'
    shutil.copytree(staged, outside)
    original = sb._read_piece
    def swap_then_read(path, base):
        if staged.is_dir() and not staged.is_junction():
            shutil.rmtree(staged)
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(staged), str(outside)], check=True, capture_output=True)
        return original(path, base)
    monkeypatch.setattr(sb, '_read_piece', swap_then_read)
    with pytest.raises(Exception):
        sb.assemble(home, reference)
    assert len(list(outside.glob('*.part'))) == reference['staged']['total'], 'nothing outside was removed'


def test_a_directory_change_detected_during_cleanup_fails_the_assembly(tmp_path, monkeypatch):
    reference = _stage_all(tmp_path, json.dumps({'k': 'v' * 12000}))
    calls = {'n': 0}
    original = sb._Verified.check
    def check(self):
        calls['n'] += 1
        if calls['n'] > reference['staged']['total'] + 3:  # passes the reads and the scan, then fails
            raise ValueError('stage directory changed')
        return original(self)
    monkeypatch.setattr(sb._Verified, 'check', check)
    with pytest.raises(ValueError, match='stage directory changed'):
        sb.assemble(tmp_path, reference)
