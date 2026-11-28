---
title: 폴백 운영 경계
created: 2026-09-30
updated: 2026-11-28
type: concept
sources: [../../FALLBACK_PLAN.md, ../../PLAN.md, ../../.private/fallback-live-audit.json]
---

# 폴백 운영 경계

예비 모델은 기존 대화나 자식 작업을 이어가기 위한 설정이다. 플러그인은 구독 소진을 이유로 다른 모델에서 작업을 처음부터 다시 실행하지 않는다.

| 범위 | 설정과 동작 |
|---|---|
| 일반 대화 | `native_fallback`은 Hermes의 대화 체인을 관리한다. 전환과 기본 모델 재시도는 Hermes 정책을 따른다. |
| 일반 위임 | `delegation_fallback`은 `delegation.fallback_providers`에 해당한다. 미설정은 Hermes 기본 규칙, `[]`는 예비 모델 없음이다. 모델이 고정된 자식은 부모 체인을 자동 상속한다고 가정하지 않는다. |
| 슬롯 위임 | `delegation.backends.model-router`와 `delegation.backends.model-router-auto`에는 각각 내장 슬롯별 체인과 비용 동의를 둔다. 기본값은 꺼짐이다. |
| 프로필 위임 | 대상 프로필의 자체 체인을 쓴다. 출발 프로필의 슬롯 체인을 적용하지 않는다. |

대화 압축과 제목 생성의 예비 모델은 각각 Hermes의 `auxiliary.<task>.fallback_chain`으로 관리한다.

## 슬롯별 비용 동의

슬롯 블록은 schema 2이며 각 내장 슬롯에 `{mode, chain, consent}`가 있다. 동의는 출발 프로필·백엔드·슬롯·정확한 체인에만 유효하다. 한 슬롯의 동의를 다른 슬롯에 복사하거나 단일 모델 백엔드의 동의를 자동 선택 백엔드에 재사용하지 않는다. 사용자지정 슬롯의 체인은 비어 있다. 슬롯 블록이 유효하지 않으면 라우팅을 거절한다.

설치나 상태 조회로 예비 모델 사용을 허용하지 않는다. 실행 중 허용된 체인으로 바뀌더라도 해당 자식의 전체 시간 제한은 다시 시작되지 않는다. 복귀 알림은 요청 경로가 복원됐다는 뜻이지 기본 모델이 정상 응답했다는 뜻은 아니다.

관련: [[task-slots]], [[native-delegation]], [[fast-inheritance]], [[index]].
