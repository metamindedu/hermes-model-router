---
title: 세션 Fast 상속과 복귀 관측 경계
created: 2026-10-10
updated: 2026-10-10
type: concept
sources: [../../FAST_INHERITANCE_PLAN.md, ../../README.md]
---

# 세션 Fast 상속과 복귀 관측 경계

## 운영 결정

- Fast의 승인 출처는 실제 부모 세션의 선택이다. 프로필 기본값, 모델 인자나 전역 환경으로 부모 선택을 추정하지 않는다. 기본 위임과 코드 라우팅은 같은 상속 원칙을 따른다.
- 자식 시작 시점의 불변 선택을 유지한다. 이후 부모의 토글을 실행 중 자식에 소급 적용하거나 과거 자식을 찾아 재입양하지 않는다.
- 지원되는 OpenAI API/Codex 모델·전송·endpoint에서만 유료 Fast 옵션을 전달한다. 미지원·비-OpenAI 폴백에 남은 옵션은 관리 대상 요청에서 제거한다. Ultrafast를 다른 유료 등급으로 조용히 바꾸지 않는다.
- bounded auto/cold는 원래 부모 만료를 유지한다. 큐·중첩·폴백이 창을 새로 열지 않는다. 현재 core scalar의 읽기 전용 호환성 경계를 검증할 수 없으면 유료 창을 연장하지 않는다.
- 설치와 설정 화면 조회는 Fast를 켜거나 모델·폴백·비용 허용·시간 제한·프로필 활성화를 변경하지 않는다. 지원 hook/middleware가 필요한 기존 세션은 새 세션 또는 지원되는 프로필 reload 반영과 구분한다.

## 복귀 의미

native runtime-restored 알림은 메인 요청 경로가 복원됐다는 의미이지 정상 응답을 확인했다는 의미가 아니다. 일반 대화 복귀·backoff는 Hermes 코어가 소유한다. 플러그인은 private native 상태를 변경하거나 별도 복귀 정책·상시 감시·복귀 버튼을 만들지 않는다.

설정 화면의 예비 체인은 현재 대화의 실측 모델과 다르다. 라우팅 폴백 시도는 작업 중 기본 경로로 돌아가지 않으며 다음 새 작업에서 기본 경로를 다시 시도한다.

## 검증·운영 함정

- 실제 디렉터리 플러그인 로더 namespace와 등록 middleware가 동일한 상속 상태 인스턴스를 사용해야 한다. 별도 import의 동명이인 전역 상태를 성공으로 보고하지 않는다.
- 요청한 tier와 실제 제공자 처리 tier·청구는 다르다. native middleware와 실제 SDK 직렬화 MockTransport 검증은 요청 전달 증거이며 live 과금·복귀 성공 증거가 아니다.
- 테스트는 현재 PM 관리형 Python/의존성 generation을 확인한다. 과거 checkout .venv에서 pytest가 먼저 import되면 re-exec를 막으면서 다른 ABI 의존성이 활성화되어 compiled-extension 오류가 날 수 있다. 테스트 의존성을 운영 runtime에 설치하지 않는다.

관련: [[index]], [[fallback-boundaries]], [[profile-boundaries]].
