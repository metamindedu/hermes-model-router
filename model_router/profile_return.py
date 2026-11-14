"""Read-only completion capsules for a parent-owned native return helper.

This is a transport building block, not an admission or wake API. The controller
must first prove the normal parent-owned terminal launch and bind an exact job.
Nothing here launches work, sends a prompt, changes grants or claims delivery.
Only a short locator is emitted; visible result prose is retrieved separately
through the existing exact-parent profile_task result operation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path

from .execution_state import JobJournal, TERMINAL, identifier


class ReturnReadError(ValueError):
    """Closed error vocabulary: never leak journal content or exception paths."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{%d}" % length, value) is not None


def encode_capsule(capsule):
    """One closed, bounded locator line for the native notification tail."""
    required = {"kind", "schema", "job_id", "outcome", "result_available"}
    if (not isinstance(capsule, dict) or set(capsule) - required - {"result_sha256", "result_truncated", "reason"}
            or not required <= set(capsule) or capsule["kind"] != "model_router.profile_completion"
            or type(capsule["schema"]) is not int or capsule["schema"] != 1
            or not _hex(capsule["job_id"], 32) or not isinstance(capsule["outcome"], str)
            or capsule["outcome"] not in TERMINAL | {"unknown"}
            or type(capsule["result_available"]) is not bool):
        raise ReturnReadError("invalid_capsule")
    result_fields = {"result_sha256", "result_truncated"}
    if (capsule["result_available"] and (not result_fields <= set(capsule)
            or not _hex(capsule["result_sha256"], 64) or type(capsule["result_truncated"]) is not bool)
            or not capsule["result_available"] and bool(result_fields & set(capsule))
            or "reason" in capsule and (capsule["outcome"] != "unknown" or not isinstance(capsule["reason"], str)
                or capsule["reason"] not in {"outcome_unknown", "helper_cancelled", "wait_deadline"})
            or capsule["outcome"] == "unknown" and ("reason" not in capsule or capsule["result_available"])):
        raise ReturnReadError("invalid_capsule")
    encoded = json.dumps(capsule, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 512:
        raise ReturnReadError("capsule_too_large")
    return encoded


class ProfileResultReader:
    """Read only this source journal and one previously bound execution.

    Parent strings/digests here are integrity checks, NOT new authority. They
    must come from the controller's verified framework binding, not model text.
    """

    def __init__(self, home, origin):
        home = Path(home)
        if not home.is_absolute() or not isinstance(origin, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", origin):
            raise ReturnReadError("invalid_binding")
        self.journal = JobJournal(home, origin)

    @staticmethod
    def _capsule(job_id, outcome, *, result=None, reason=None):
        capsule = {"kind": "model_router.profile_completion", "schema": 1,
                   "job_id": job_id, "outcome": outcome,
                   "result_available": result is not None}
        if result is not None:
            capsule["result_sha256"] = hashlib.sha256(result["text"].encode("utf-8")).hexdigest()
            capsule["result_truncated"] = result["truncated"]
        if reason is not None:
            capsule["reason"] = reason
        encode_capsule(capsule)
        return capsule

    def inspect(self, job_id, parent, *, request_digest, payload_digest):
        """Return terminal/uncertain evidence, or None while genuinely pending."""
        if (not _hex(job_id, 32) or not identifier(parent)
                or not _hex(request_digest, 64) or not _hex(payload_digest, 64)):
            raise ReturnReadError("invalid_binding")
        try:
            job = self.journal.read()["jobs"].get(job_id)
        except Exception:
            raise ReturnReadError("journal_unavailable") from None
        if job is None:
            raise ReturnReadError("job_unavailable")
        if (parent not in job["parent_aliases"] or job["request_id"] != request_digest
                or job["payload_digest"] != payload_digest):
            raise ReturnReadError("binding_mismatch")
        if job["status"] in TERMINAL:
            return self._capsule(job_id, job["status"], result=job["result"])
        if job["status"] == "unknown" or job["operation_unknown"]:
            return self._capsule(job_id, "unknown", reason="outcome_unknown")
        return None

    def wait(self, job_id, parent, *, request_digest, payload_digest, deadline,
             poll_seconds=2.0, stop=None, monotonic_deadline=None):
        """Finite local wait; never retries a target submission or cancels it.

        The prepared controller chooses the explicit deadline. Wall-clock lease
        duration is pinned to monotonic time once, so clock rollback cannot
        silently renew it. A cancelled helper/expired lease reports uncertainty,
        not target cancellation or a successfully delivered business result.
        """
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds)
                or not 0 < poll_seconds <= 5 or not _hex(job_id, 32)
                or monotonic_deadline is not None and (type(monotonic_deadline) not in (int, float)
                    or not math.isfinite(monotonic_deadline))):
            raise ReturnReadError("invalid_wait")
        stop = stop if stop is not None else threading.Event()
        if monotonic_deadline is None:
            remaining = max(0.0, deadline - time.time())
            until = time.monotonic() + remaining
        else:
            until = monotonic_deadline
        while True:
            # Even cancellation/deadline receipts require the exact job binding;
            # an expired timer must not turn arbitrary caller strings into a
            # completion locator for a foreign or nonexistent job.
            capsule = self.inspect(job_id, parent, request_digest=request_digest, payload_digest=payload_digest)
            if stop.is_set():
                return self._capsule(job_id, "unknown", reason="helper_cancelled")
            if time.monotonic() >= until:
                return self._capsule(job_id, "unknown", reason="wait_deadline")
            if capsule is not None:
                return capsule
            stop.wait(min(poll_seconds, max(0.0, until - time.monotonic())))
