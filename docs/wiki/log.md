# Wiki Log

## 2026-09-29 | create
- 사용자 승인 통합 플러그인 구조와 프로필 활성화 경계를 기록.

## 2026-09-30 | fallback-boundaries
- 폴백 관리 계약(일반 대화/코딩 라우팅 분리, OFF는 두 키 모두 비움, 승인·비용 확인)과 오류 판정 원칙을 기록.
- OpenAI Codex 구독 소진(약 101시간)으로 고정 모델 위임 자식이 전면 실패한 사건과 `scoped_fallback_chain` 상속 규칙을 기록. 위임 폴백 관리는 사용자 요청으로 후속 단계에 추가.
- 검증 환경 함정(테스터 인터프리터 ≠ 제품 런타임, 깊은 attempt 경로와 Windows 260자, 상속 `VIRTUAL_ENV` 오염)을 기록.

## 2026-09-30 | correction
- `fallback-boundaries`의 CLI 실패 자동 skip 지침을 폐기하고 실제 Hermes 환경에서 실패를 드러내는 검증 원칙으로 교정. 위임 null의 조건부 상속과 primary 쿨다운 의미를 명확히 함.
- 관측 훅은 실제 디렉터리 플러그인 로더 namespace와 SDK가 같은 인스턴스를 사용하는지 fake-home 통합 테스트로 입증해야 함. raw YAML 읽기만으로 관리형 overlay 또는 effective 설정을 검증했다고 보고하지 않음.

## 2026-09-30 | routed-session-visibility
- 네이티브 위임 위장 없이 실제 worker의 Background 추적, 현재 context 기반 부모/프로필 연결과 `subagent` 분류 경계를 기록.
- 대상 프로필 환경 생성 시 번들 Python의 런타임 import 경로를 복원해야 하는 함정과, 레포에 미반영된 설치 hotfix 보존 원칙을 기록.
- 기본 dry-run의 정확한 source-only 교정, 백업/CAS/독립 readback과 강제 중지의 artifact 미확정 경계를 기록. 실제 실행 기록은 private 작업 증거로 유지.
