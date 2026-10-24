"""Launcher test isolation must never choose an unrelated named profile."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import tempfile

from hermes_constants import set_hermes_home_override, reset_hermes_home_override
import test_integration


def test_launcher_scratch_fallback_stays_in_current_home(tmp_path, monkeypatch):
    home = tmp_path / 'current-home'
    expected = home / 'cache/scratch'
    used = []
    monkeypatch.delenv('TMPDIR', raising=False)
    monkeypatch.setenv('HERMES_HOME', str(home))
    # Capture the attempted directory without making any real fallback directory.
    monkeypatch.setattr(Path, 'mkdir', lambda *a, **k: None)
    def temporary_file(*a, **kwargs):
        used.append(Path(kwargs['dir']))
        return BytesIO()
    monkeypatch.setattr(tempfile, 'TemporaryFile', temporary_file)
    monkeypatch.setattr(test_integration.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    token = set_hermes_home_override(home)
    try:
        result = test_integration.run_launcher(['fixture-only'], env={})
        assert result.returncode == 0
        assert used == [expected, expected]
    finally:
        reset_hermes_home_override(token)
