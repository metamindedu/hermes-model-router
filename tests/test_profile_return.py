"""Read-only return building-block contracts, not native delivery/provider E2E."""
import hashlib
import threading
import time
from types import SimpleNamespace

import pytest

from model_router.execution_state import JobJournal
from model_router.profile_return import ProfileResultReader, ReturnReadError, encode_capsule


@pytest.fixture
def bound_job(tmp_path):
    home = tmp_path / "source"
    home.mkdir()
    journal = JobJournal(home, "default")
    job = {
        "id": "1" * 32, "origin_profile": "default", "parent_session_id": "parent-fixture",
        "parent_aliases": ["parent-fixture", "compressed-parent-fixture"], "target_profile": "worker",
        "cwd": str(tmp_path / "workspace"), "request_id": "a" * 64, "payload_digest": "b" * 64,
        "grant_revision": "c" * 64, "create_id": "create-fixture", "submission_id": "submit-fixture",
        "observer_owner": "observer-fixture", "status": "running", "reason_code": None,
        "created_at": time.time(), "updated_at": time.time(), "target_session_id": "target-fixture",
        "admission_id": "admission-fixture", "execution_generation": 1,
        "gateway_profile_id": "profile-fixture", "instance_id": "instance-fixture", "authority_epoch": 1,
        "result": None, "pending_request": None, "operation_unknown": False, "pending_operation": None,
        "completion_delivery": "explicit_result", "cancel_requested": False,
    }
    journal.transaction(lambda jobs: jobs.update({job["id"]: job}))
    reader = ProfileResultReader(home, "default")
    binding = dict(job_id=job["id"], parent=job["parent_session_id"],
                   request_digest=job["request_id"], payload_digest=job["payload_digest"])
    return reader, journal, binding


def update(journal, **changes):
    journal.transaction(lambda jobs: jobs["1" * 32].update(changes))


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("has_result", [False, True])
def test_terminal_capsule_is_short_locator_not_private_prose(bound_job, status, has_result):
    reader, journal, binding = bound_job
    text = "PRIVATE_RESULT_BODY_DO_NOT_NOTIFY " + "민감한 가짜 본문 " * 900
    result = {"text": text, "truncated": True} if has_result else None
    update(journal, status=status, result=result)
    capsule = reader.inspect(**binding)
    encoded = encode_capsule(capsule)
    assert capsule["outcome"] == status and capsule["result_available"] is has_result
    assert len(encoded) <= 512 and "\n" not in encoded
    assert "PRIVATE_RESULT" not in encoded and "민감한" not in encoded
    assert "parent-fixture" not in encoded and "workspace" not in encoded
    if has_result:
        assert capsule["result_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert capsule["result_truncated"] is True
    else:
        assert "result_sha256" not in capsule


@pytest.mark.parametrize("field,value", [
    ("parent", "foreign-parent"), ("request_digest", "d" * 64), ("payload_digest", "e" * 64),
])
def test_wrong_binding_refuses_even_after_deadline_or_helper_stop(bound_job, field, value):
    reader, _, binding = bound_job
    binding[field] = value
    stop = threading.Event()
    stop.set()
    with pytest.raises(ReturnReadError, match="^binding_mismatch$"):
        reader.inspect(**binding)
    with pytest.raises(ReturnReadError, match="^binding_mismatch$"):
        reader.wait(**binding, deadline=time.time() - 1, stop=stop)


def test_existing_compression_alias_is_allowed_not_invented(bound_job):
    reader, journal, binding = bound_job
    update(journal, status="completed")
    assert reader.inspect(**(binding | {"parent": "compressed-parent-fixture"}))["outcome"] == "completed"
    with pytest.raises(ReturnReadError, match="binding_mismatch"):
        reader.inspect(**(binding | {"parent": "unobserved-next-parent"}))


@pytest.mark.parametrize("status", ["preparing", "creating", "submitting", "queued", "running", "approval_wait", "clarify_wait", "stop_requested"])
def test_nonterminal_absence_of_result_does_not_infer_completion(bound_job, status):
    reader, journal, binding = bound_job
    update(journal, status=status)
    assert reader.inspect(**binding) is None


@pytest.mark.parametrize("changes", [{"status": "unknown"}, {"operation_unknown": True}])
def test_uncertain_outcome_does_not_publish_retained_result(bound_job, changes):
    reader, journal, binding = bound_job
    update(journal, **changes, result={"text": "PRIVATE_STALE_RESULT", "truncated": False})
    capsule = reader.inspect(**binding)
    assert capsule["outcome"] == "unknown" and capsule["reason"] == "outcome_unknown"
    assert capsule["result_available"] is False
    assert "PRIVATE_STALE_RESULT" not in encode_capsule(capsule)


def test_wait_observes_actual_atomic_journal_completion(bound_job):
    reader, journal, binding = bound_job
    done = threading.Event()
    def complete():
        done.wait(.04)
        update(journal, status="completed", result={"text": "synthetic final", "truncated": False})
    thread = threading.Thread(target=complete)
    thread.start()
    try:
        capsule = reader.wait(**binding, deadline=time.time() + 5, poll_seconds=.02)
        assert capsule["outcome"] == "completed" and capsule["result_available"]
    finally:
        done.set()
        thread.join(timeout=3)
    assert not thread.is_alive()


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_or_helper_cancel_does_not_cancel_or_mutate_job(bound_job, cancel):
    reader, journal, binding = bound_job
    before = {p.relative_to(journal.home).as_posix(): p.read_bytes() for p in journal.home.rglob("*") if p.is_file()}
    stop = threading.Event()
    if cancel:
        stop.set()
    capsule = reader.wait(**binding, deadline=time.time() - 1 if not cancel else time.time() + 5, stop=stop)
    assert capsule["outcome"] == "unknown"
    assert capsule["reason"] == ("helper_cancelled" if cancel else "wait_deadline")
    assert journal.read()["jobs"][binding["job_id"]]["status"] == "running"
    assert before == {p.relative_to(journal.home).as_posix(): p.read_bytes() for p in journal.home.rglob("*") if p.is_file()}


def test_wall_clock_cannot_extend_wait_lease(bound_job, monkeypatch):
    reader, _, binding = bound_job
    import model_router.profile_return as subject
    ticks = iter([500.0, 500.0, 500.25, 501.0])
    wall_calls = []
    def wall():
        wall_calls.append(True)
        assert len(wall_calls) == 1
        return 100.0
    waits = []
    stop = SimpleNamespace(is_set=lambda: False, wait=lambda seconds: waits.append(seconds))
    monkeypatch.setattr(subject, "time", SimpleNamespace(time=wall, monotonic=lambda: next(ticks)))
    capsule = reader.wait(**binding, deadline=101, poll_seconds=.5, stop=stop)
    assert capsule["outcome"] == "unknown" and capsule["reason"] == "wait_deadline"
    assert wall_calls == [True] and waits == [.5]


def test_missing_journal_read_creates_nothing(tmp_path):
    home = tmp_path / "absent"
    reader = ProfileResultReader(home, "default")
    with pytest.raises(ReturnReadError, match="job_unavailable"):
        reader.inspect("1" * 32, "parent", request_digest="a" * 64, payload_digest="b" * 64)
    assert not home.exists()


def test_corrupt_journal_error_does_not_echo_content_or_path(bound_job):
    reader, journal, binding = bound_job
    journal.path.write_text('{"PRIVATE_SECRET_CANARY":', encoding="utf-8")
    with pytest.raises(ReturnReadError) as raised:
        reader.inspect(**binding)
    assert str(raised.value) == "journal_unavailable"


@pytest.mark.parametrize("changed", [
    {"extra": "PRIVATE_PROSE"}, {"schema": True}, {"kind": "another-kind"},
    {"outcome": []}, {"outcome": "running"}, {"result_available": 1},
    {"result_available": True}, {"result_sha256": "d" * 64},
    {"reason": "arbitrary-private-text"}, {"outcome": "unknown"},
])
def test_capsule_schema_is_closed(changed):
    capsule = {"kind": "model_router.profile_completion", "schema": 1,
               "job_id": "1" * 32, "outcome": "completed", "result_available": False}
    with pytest.raises(ReturnReadError, match="invalid_capsule"):
        encode_capsule(capsule | changed)


@pytest.mark.parametrize("deadline,poll", [(True, 1), (float("nan"), 1), (float("inf"), 1), (1, 0), (1, True), (1, 6)])
def test_invalid_wait_parameters_are_not_silently_repaired(bound_job, deadline, poll):
    reader, _, binding = bound_job
    with pytest.raises(ReturnReadError, match="invalid_wait"):
        reader.wait(**binding, deadline=deadline, poll_seconds=poll)
