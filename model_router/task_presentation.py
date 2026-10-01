"""Safe, bounded human-readable labels for routed jobs.

The presentation layer deliberately depends on the declared purpose and route
metadata only; it never inspects a prompt or forwards process logs/environment.
"""
from __future__ import annotations

import unicodedata
import re
from typing import Any

MAX_TITLE_CHARS = 96
MAX_TERMINAL_SEED_CHARS = 2048
DISPLAY_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
SAFE_FALLBACK_TEXT = "민감정보 보호를 위해 표시하지 않습니다."
_CREDENTIAL_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s]+@")

# Fixed Korean labels: do not infer an operation from user prompt wording.
PURPOSE_DEFAULTS = {
    "implementation": "기능 구현",
    "mechanical": "테스트 및 검증",
    "preliminary-review": "예비 검토",
    "plan": "작업 계획",
    "semantic-final": "최종 의미 검토",
    "independent-review": "독립 검수",
}
PURPOSE_LABELS = {
    "implementation": "기능 구현",
    "mechanical": "테스트 및 검증",
    "preliminary-review": "예비 검토",
    "plan": "작업 계획",
    "semantic-final": "최종 의미 검토",
    "independent-review": "독립 검수",
}
HEAVY_PURPOSES = frozenset({"plan", "semantic-final", "independent-review"})


def _has_disallowed_controls(value: str) -> bool:
    """Reject terminal controls, formatting/bidi controls, and surrogate codepoints."""
    return any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value)


def _force_redact(value: str) -> str:
    # Load Hermes' installed sanitizer at call time so import/version problems are
    # caught by safe_display's fail-closed path instead of exposing raw content.
    from agent.redact import redact_sensitive_text

    # Native redaction may leave arbitrary URL userinfo unchanged. Reject the
    # whole display input BEFORE truncation, including in the public writer.
    if _CREDENTIAL_URL.search(value):
        return SAFE_FALLBACK_TEXT
    cleaned = redact_sensitive_text(value, force=True)
    if not isinstance(cleaned, str):
        raise TypeError("sensitive-text sanitizer returned a non-string")
    if _has_disallowed_controls(cleaned):
        raise ValueError("sensitive-text sanitizer returned terminal control characters")
    return cleaned[:]


def safe_display(value: Any, limit: int = 256) -> str:
    """Return forced-redacted, control-free display text or a fixed safe fallback."""
    if not isinstance(value, str) or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return SAFE_FALLBACK_TEXT[: max(1, limit)] if isinstance(limit, int) and limit > 0 else SAFE_FALLBACK_TEXT
    try:
        cleaned = _force_redact(value).strip()
        if not cleaned and value.strip():
            return SAFE_FALLBACK_TEXT[:limit]
        return cleaned[:limit]
    except Exception:
        return SAFE_FALLBACK_TEXT[:limit]


def default_title(purpose: str) -> str:
    """Fixed purpose-derived fallback that is independent of the prompt."""
    return PURPOSE_DEFAULTS.get(purpose, "모델 작업")


def default_role(purpose: str) -> str:
    return "HEAVYWEIGHT" if purpose in HEAVY_PURPOSES else "LIGHTWEIGHT"


def role_label(role: Any, purpose: str = "") -> str:
    value = role if isinstance(role, str) else ""
    normalized = value.strip().upper()
    if normalized in {"HEAVYWEIGHT", "HEAVY"}:
        return "Heavy"
    if normalized in {"LIGHTWEIGHT", "LIGHT"}:
        return "Light"
    return "Heavy" if default_role(purpose) == "HEAVYWEIGHT" else "Light"


def validate_title(title: Any, purpose: str) -> str:
    """Validate an authored title before launch, then force-redact it for display.

    ``None`` selects a fixed Korean purpose label; blank, non-string, overlong,
    and Unicode control/format/surrogate values are rejected. No prompt text is
    accepted as an implicit title.
    """
    if title is None:
        value = default_title(purpose)
    else:
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        if not title.strip():
            raise ValueError("title must not be blank")
        if len(title) > MAX_TITLE_CHARS:
            raise ValueError(f"title must be at most {MAX_TITLE_CHARS} characters")
        if _has_disallowed_controls(title):
            raise ValueError("title must not contain control or formatting characters")
        value = title.strip()
    cleaned = safe_display(value, MAX_TITLE_CHARS)
    if not cleaned.strip():
        raise ValueError("title could not be safely displayed")
    return cleaned


def native_command(title: Any, role: Any, model: Any, purpose: str = "") -> str:
    """Build the native process card label without making a UUID its identity."""
    safe_title = safe_display(title if isinstance(title, str) else default_title(purpose), MAX_TITLE_CHARS)
    safe_model = safe_display(model if isinstance(model, str) else "미지정", 128)
    return f"서브 에이전트 작업: {safe_title} · {role_label(role, purpose)} · {safe_model}"


def terminal_seed(
    *,
    title: Any,
    purpose: Any,
    role: Any,
    model: Any,
    provider: Any,
    profile: Any,
    job_id: Any,
    cwd_basename: Any,
    reasoning: Any = None,
) -> str:
    """One bounded safe output seed; includes no prompt, logs, or environment."""
    purpose_key = purpose if isinstance(purpose, str) else ""
    label = PURPOSE_LABELS.get(purpose_key, "모델 작업")
    safe_title = safe_display(title if isinstance(title, str) else default_title(purpose_key), MAX_TITLE_CHARS)
    safe_model = safe_display(model if isinstance(model, str) else "미지정", 128)
    safe_provider = safe_display(provider if isinstance(provider, str) else "미지정", 96)
    safe_profile = safe_display(profile if isinstance(profile, str) else "default", 96)
    safe_job_id = safe_display(job_id if isinstance(job_id, str) else "미지정", 64)
    safe_cwd = safe_display(cwd_basename if isinstance(cwd_basename, str) else "미지정", 128)
    # Literal launch setting, not a claim about provider-normalized wire effort.
    effort = reasoning if isinstance(reasoning, str) and reasoning in DISPLAY_EFFORTS else "미지정"
    seed = (
        f"{native_command(safe_title, role, safe_model, purpose_key)} ({effort})\n"
        f"작업 목적: {label}\n"
        f"대상 모델: {safe_model} ({effort}) · 제공자: {safe_provider}\n"
        f"프로필: {safe_profile}\n"
        f"작업 ID: {safe_job_id}\n"
        f"작업 폴더: {safe_cwd}\n"
        "[00:00] 작업 시작\n"
        "아래에는 마지막으로 확인한 공개 활동을 기록합니다. 전체 로그가 아니며 빠른 활동은 합쳐질 수 있습니다.\n"
        "중지는 Hermes 프로세스 화면의 X 버튼을 사용하세요.\n"
        "프로세스 종료만으로 의미 검수 통과나 GO가 확정되지는 않습니다.\n"
    )
    if len(seed) <= MAX_TERMINAL_SEED_CHARS:
        return seed
    # The field limits above make this unreachable for normal inputs. Retain a
    # static fail-closed fallback if an unexpected sanitizer expands its output.
    return SAFE_FALLBACK_TEXT[:MAX_TERMINAL_SEED_CHARS]
