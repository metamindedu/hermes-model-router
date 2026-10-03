from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import pytest

from model_router.timeouts import (
    DEFAULT_DELEGATE_TOTAL_SECONDS,
    DEFAULT_ROUTED_TOTAL_SECONDS,
    read_timeouts,
    timeout_digest,
    timeout_status,
    validate_seconds,
    write_timeouts,
)


def expected_defaults() -> dict[str, object]:
    return {
        "schema": 1,
        "revision": 0,
        "delegate_total_seconds": 0.0,
        "routed_total_seconds": 3600.0,
    }


def profile_home(root: Path, profile: str) -> Path:
    return root / "profiles" / profile


def make_home(root: Path, profile: str = "claire") -> Path:
    home = profile_home(root, profile)
    home.mkdir(parents=True)
    return home


def timeout_path(home: Path) -> Path:
    return home / "plugin-data" / "model-router" / "timeouts.json"


def test_defaults_are_independent_and_missing_read_is_read_only(tmp_path):
    home = tmp_path / "profiles" / "claire"

    value = read_timeouts(home)

    assert value == expected_defaults()
    assert DEFAULT_DELEGATE_TOTAL_SECONDS == 0
    assert DEFAULT_ROUTED_TOTAL_SECONDS == 3600
    assert timeout_digest(home) == "MISSING"
    assert not home.exists()


def test_profile_homes_are_isolated_and_use_the_exact_local_path(tmp_path):
    root = tmp_path / "hermes"
    claire = make_home(root, "claire")
    morgan = make_home(root, "morgan")
    values = {"delegate_total_seconds": 7200, "routed_total_seconds": 86400.5}

    written = write_timeouts(
        claire,
        values,
        expected_digest="MISSING",
        expected_revision=0,
    )

    assert written == {
        "schema": 1,
        "revision": 1,
        "delegate_total_seconds": 7200.0,
        "routed_total_seconds": 86400.5,
    }
    assert timeout_path(claire).is_file()
    assert not timeout_path(morgan).exists()
    assert read_timeouts(morgan) == expected_defaults()
    assert json.loads(timeout_path(claire).read_text(encoding="utf-8")) == written


def test_validate_seconds_accepts_zero_and_unclamped_long_finite_budgets():
    assert validate_seconds(0) == 0.0
    assert validate_seconds(0.0) == 0.0
    assert validate_seconds(7200) == 7200.0
    assert validate_seconds(86400.5) == 86400.5


@pytest.mark.parametrize(
    "value",
    [True, False, None, "1", float("nan"), float("inf"), float("-inf"), -0.1, -1],
)
def test_validate_seconds_rejects_non_numeric_non_finite_and_negative_values(value):
    with pytest.raises(ValueError):
        validate_seconds(value)


def test_validate_seconds_rejects_integer_too_large_for_finite_float():
    with pytest.raises(ValueError):
        validate_seconds(10**10000)


def test_read_and_digest_fail_closed_for_corrupt_or_unsupported_existing_files(tmp_path):
    home = make_home(tmp_path)
    path = timeout_path(home)
    path.parent.mkdir(parents=True)

    for payload in (
        b"{not-json",
        b'{"schema":2,"revision":0,"delegate_total_seconds":0,"routed_total_seconds":3600}',
    ):
        path.write_bytes(payload)
        with pytest.raises(RuntimeError):
            read_timeouts(home)
        with pytest.raises(RuntimeError):
            timeout_digest(home)

        before = path.read_bytes()
        status = timeout_status(home)
        assert status["editable"] is False
        assert status["warnings"]
        assert status["revision"] is None
        assert status["delegate_total_seconds"] is None
        assert status["routed_total_seconds"] is None
        assert path.read_bytes() == before


def test_read_rejects_invalid_revision_and_value_schema(tmp_path):
    home = make_home(tmp_path)
    path = timeout_path(home)
    path.parent.mkdir(parents=True)
    for payload in (
        {"schema": 1, "revision": True, "delegate_total_seconds": 0, "routed_total_seconds": 3600},
        {"schema": 1, "revision": -1, "delegate_total_seconds": 0, "routed_total_seconds": 3600},
        {"schema": 1, "revision": 0, "delegate_total_seconds": True, "routed_total_seconds": 3600},
        {"schema": 1, "revision": 0, "delegate_total_seconds": 0, "routed_total_seconds": float("nan")},
        {"schema": 1, "revision": 0, "delegate_total_seconds": 0, "routed_total_seconds": 3600, "extra": 1},
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RuntimeError):
            read_timeouts(home)


def test_unavailable_enforcement_is_read_only_with_safe_defaults(tmp_path):
    home = tmp_path / "profile"

    status = timeout_status(home, enforcement_available=False)

    assert {key: status[key] for key in expected_defaults()} == expected_defaults()
    assert status["editable"] is False
    assert status["warnings"]
    assert not home.exists()


def test_timeout_digest_is_sha256_of_exact_valid_file_bytes(tmp_path):
    home = make_home(tmp_path)
    path = timeout_path(home)
    path.parent.mkdir(parents=True)
    payload = b'{"schema":1,"revision":0,"delegate_total_seconds":0,"routed_total_seconds":3600}\n'
    path.write_bytes(payload)

    digest = timeout_digest(home)

    assert digest == hashlib.sha256(payload).hexdigest()
    assert timeout_digest(home) == digest


def test_stale_digest_or_revision_rejects_write_without_overwrite(tmp_path):
    home = make_home(tmp_path)
    initial = write_timeouts(
        home,
        {"delegate_total_seconds": 0, "routed_total_seconds": 7200},
        expected_digest="MISSING",
        expected_revision=0,
    )
    path = timeout_path(home)
    before = path.read_bytes()
    current_digest = timeout_digest(home)

    with pytest.raises(RuntimeError):
        write_timeouts(
            home,
            {"delegate_total_seconds": 30, "routed_total_seconds": 7200},
            expected_digest="MISSING",
            expected_revision=initial["revision"],
        )
    with pytest.raises(RuntimeError):
        write_timeouts(
            home,
            {"delegate_total_seconds": 30, "routed_total_seconds": 7200},
            expected_digest=current_digest,
            expected_revision=0,
        )

    assert path.read_bytes() == before


def test_changed_write_increments_revision_and_returns_exact_readback(tmp_path):
    home = make_home(tmp_path)
    values = {"delegate_total_seconds": 3600, "routed_total_seconds": 7200.25}

    result = write_timeouts(home, values, expected_digest="MISSING", expected_revision=0)

    assert result["revision"] == 1
    assert result == read_timeouts(home)
    assert timeout_digest(home) == hashlib.sha256(timeout_path(home).read_bytes()).hexdigest()
    assert result["delegate_total_seconds"] == 3600.0
    assert result["routed_total_seconds"] == 7200.25


def test_noop_preserves_existing_revision_and_exact_file_bytes(tmp_path):
    home = make_home(tmp_path)
    first = write_timeouts(
        home,
        {"delegate_total_seconds": 0, "routed_total_seconds": 7200},
        expected_digest="MISSING",
        expected_revision=0,
    )
    path = timeout_path(home)
    before = path.read_bytes()

    result = write_timeouts(
        home,
        {"delegate_total_seconds": 0.0, "routed_total_seconds": 7200.0},
        expected_digest=timeout_digest(home),
        expected_revision=first["revision"],
    )

    assert result == first
    assert path.read_bytes() == before


def test_noop_on_missing_defaults_does_not_create_timeout_file(tmp_path):
    home = tmp_path / "missing-profile"

    result = write_timeouts(
        home,
        {"delegate_total_seconds": 0, "routed_total_seconds": 3600},
        expected_digest="MISSING",
        expected_revision=0,
    )

    assert result == expected_defaults()
    assert not timeout_path(home).exists()


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"delegate_total_seconds": 0},
        {"delegate_total_seconds": 0, "routed_total_seconds": 1, "extra": 3},
        {"delegate_total_seconds": True, "routed_total_seconds": 1},
        {"delegate_total_seconds": 0, "routed_total_seconds": math.inf},
        {"delegate_total_seconds": -1, "routed_total_seconds": 1},
    ],
)
def test_write_requires_exact_valid_timeout_fields(tmp_path, values):
    home = make_home(tmp_path)

    with pytest.raises(ValueError):
        write_timeouts(home, values, expected_digest="MISSING", expected_revision=0)

    assert not timeout_path(home).exists()


def _make_symlink(link: Path, target: Path, *, directory: bool = True) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except NotImplementedError:
        pytest.skip("symlinks are unavailable in this environment")
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise


def test_existing_ancestor_symlink_is_rejected_without_touching_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    _make_symlink(linked_parent, outside)
    home = linked_parent / "profile"

    with pytest.raises(RuntimeError):
        read_timeouts(home)
    with pytest.raises(RuntimeError):
        write_timeouts(
            home,
            {"delegate_total_seconds": 10, "routed_total_seconds": 3600},
            expected_digest="MISSING",
            expected_revision=0,
        )

    assert not timeout_path(outside / "profile").exists()


def test_symlinked_store_components_and_store_file_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    home = make_home(tmp_path, "plugin-data-link")
    _make_symlink(home / "plugin-data", outside)
    with pytest.raises(RuntimeError):
        read_timeouts(home)

    home2 = make_home(tmp_path, "router-link")
    plugin_data = home2 / "plugin-data"
    plugin_data.mkdir()
    _make_symlink(plugin_data / "model-router", outside)
    with pytest.raises(RuntimeError):
        read_timeouts(home2)

    home3 = make_home(tmp_path, "file-link")
    path3 = timeout_path(home3)
    path3.parent.mkdir(parents=True)
    outside_file = outside / "outside.json"
    outside_file.write_text("outside", encoding="utf-8")
    _make_symlink(path3, outside_file, directory=False)
    with pytest.raises(RuntimeError):
        read_timeouts(home3)
    assert outside_file.read_text(encoding="utf-8") == "outside"


def test_parent_traversal_in_home_path_is_rejected(tmp_path):
    escaped_home = tmp_path / "profiles" / ".." / "outside-profile"

    with pytest.raises(RuntimeError):
        read_timeouts(escaped_home)


def test_foreign_profile_write_does_not_modify_other_profile_file(tmp_path):
    root = tmp_path / "hermes"
    current = make_home(root, "claire")
    foreign = make_home(root, "morgan")
    foreign_payload = b'{"schema":1,"revision":9,"delegate_total_seconds":4,"routed_total_seconds":8}\n'
    foreign_path = timeout_path(foreign)
    foreign_path.parent.mkdir(parents=True)
    foreign_path.write_bytes(foreign_payload)

    write_timeouts(
        current,
        {"delegate_total_seconds": 15, "routed_total_seconds": 3600},
        expected_digest="MISSING",
        expected_revision=0,
    )

    assert foreign_path.read_bytes() == foreign_payload
    assert read_timeouts(foreign)["revision"] == 9
