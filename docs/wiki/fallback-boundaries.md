---
title: 폴백 운영 경계와 2026-09-30 구독 소진 사건
created: 2026-09-30
updated: 2026-09-30
type: concept
sources: [../../FALLBACK_PLAN.md, ../../PLAN.md, ../../.private/fallback-live-audit.json]
---

# 폴백 운영 경계

Hermes에는 서로 다른 두 폴백 계층이 있고, 플러그인은 이를 **한 화면에서 분리해** 관리한다.

- **일반 대화(native)**: `fallback_providers`(현재 키)와 `fallback_model`(구 키)를 합쳐 읽는다. 같은 턴의 전환 및 다음 턴의 primary 재시도는 Hermes 런타임 정책을 따른다. 사용량 재개 시각/쿨다운이 남아 있으면 다음 턴에도 fallback을 유지할 수 있으므로, 매 턴 원래 모델로 복귀한다고 보장하지 않는다. 일부 상속형 위임·자동 보조 호출도 이 체인을 참조할 수 있다. 추론 강도는 체인 항목이 아니라 모델별 override/전역 설정에서 다시 계산된다.
- **코딩 라우팅**: `coding_route`가 시작한 작업만 해당한다. 서브에이전트 SDK 자식의 native 체인은 명시적으로 비워 일반 대화 체인과 격리하고, 승인된 동일 등급 경로로 **새 작업 시도**를 최대 한 번 실행한다. 도구 호출·부분 출력·timeout·증거 누락이 있으면 재실행하지 않는다.

OFF는 두 키를 모두 비워야 한다. `fallback_providers: []`만 쓰면 legacy `fallback_model`이 살아남아 의도와 다르게 동작할 수 있다.

## 위임(delegation)의 함정

`scoped_fallback_chain` 의미상 **provider/model을 고정한 자식은 부모 체인을 상속하지 않는다**(`pinned`면 declared가 없을 때 `None`). `delegation.fallback_providers`의 null/미설정은 기본 규칙이다. 고정하지 않은 자식만 부모를 상속하며, 고정한 자식은 부모를 상속하지 않는다. `[]`는 명시 비활성, 유효한 명시 목록은 자식의 자체 체인이다.

2026-09-30 OpenAI Codex 구독 사용한도 소진(약 101시간) 시 실제 결과: 메인 대화는 프로필 native 체인(xiaomi → deepseek)이 있었지만, `delegation.provider=openai-codex`로 고정된 서브에이전트는 폴백이 없어 **3개 병렬 작업이 동시에 HTTP 429로 실패**했다. 사용자는 위임 폴백 관리도 구현 범위에 포함하도록 선택했다. 실제 활성화와 비용 승인은 구현 요청과 별개이며 설치만으로 기존 위임 정책을 변경하지 않는다.

## 오류 판정 원칙

- stdout에 사용량 초과 문구가 있다는 이유만으로 유료 대체 경로를 호출하지 않는다. 구조화된 오류 증거, 완전한 관측·종료, 잔여 시간, 해당 경로의 승인이 모두 필요하다.
- `route_verified`는 실행 모델·제공자 동일성 증거일 뿐 의미적 승인이 아니다.
- 관측 훅은 차단기가 아니다. 증거 누락·불일치는 `unverified`로 남기고 재실행을 금지한다.

## 검증 환경 함정

- 테스트용 인터프리터(uv/conda 샌드박스)는 제품 런타임이 아니다. 설치된 `hermes` 런처의 실행 실패는 자동 skip하지 않는다. 실제 Hermes 인터프리터에서 `PYTHONPATH`/`PYTHONHOME`/`VIRTUAL_ENV` 오염을 제거하고, 필요하면 순수 Python pytest 의존성 경로만 프로세스 안에 추가해 다시 검증한다. 제품 환경에서도 실패하면 실패로 보고한다.
- 시도 아티팩트 경로(`…/jobs/<uuid>/attempts/<uuid>`)는 깊다. Windows 260자 제한 때문에 테스트는 짧은 임시 루트를 써야 한다.
- `uv run`이 만든 환경에서 `pytest`를 돌리려면 상속된 `VIRTUAL_ENV`를 지워야 한다. 남아 있으면 uv가 오염된 venv를 골라 `pydantic_core._pydantic_core` 오류를 낸다.

관련: [[index]], [[profile-boundaries]], [[SCHEMA]].
