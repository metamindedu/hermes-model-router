---
title: 라우팅 시작 단계의 Hermes 호환성
created: 2026-10-11
updated: 2026-10-11
type: concept
sources: [../../PLAN.md, ../../README.md]
---

# 라우팅 시작 단계의 Hermes 호환성

## 운영 결정과 함정

- Hermes가 번들 Tirith를 폐기한 호스트에서는 `tools.tirith_security`가 없다. 플러그인이 이를 무조건 import하면 모델 호출·도구 실행 전에 라우팅 자식의 시작이 실패한다. Fast 요청 정책 오류와 시작 호환성 오류를 구분한다.
- 정확한 optional 모듈의 `ModuleNotFoundError.name`만 허용한다. 부모 패키지나 다른 dependency 누락, symbol/import/loader 오류와 initializer 실패까지 삼키는 넓은 예외 처리는 사용하지 않는다. legacy 호스트에서는 원래 initializer와 시작 순서를 유지한다.
- 호환성 처리는 플러그인 시작 코드에 한정한다. Hermes 코어·인증·승인·모델·Fast·폴백·시간 제한 설정을 바꾸거나 실패한 고객 작업을 자동으로 재실행하지 않는다.
- 실제 copied-plugin bootstrap와 오류 전파 회귀를 함께 확인한다. AST 분기 테스트만으로 전체 실행 또는 live 모델 응답을 증명하지 않는다.
- 설치된 시작 파일은 새 scoped attempt의 fresh process가 읽는다. 기존 객체의 소급 교체나 모든 프로필의 모델 호출 성공을 설치 readback만으로 주장하지 않는다.
- 로컬 hotfix 설치, GitHub 릴리스, 공식 카탈로그의 exact-SHA pin은 별개의 상태다. SHA 갱신은 새 PR과 maintainer 병합을 거쳐야 하며 제출·CI 통과를 카탈로그 반영 완료로 표현하지 않는다.

관련: [[fast-inheritance]], [[index]].
