# Wiki Log

## 2026-10-02 | routing-primary-targets
- 활성 체크 목록은 여러 프로필을 켜지만 Heavy/Light는 source 하나만 저장하던 계약과 사용자 일괄 적용 기대의 불일치를 확인.
- 경로 복사 대상과 활성 상태를 분리하고, 모델-only 재저장의 암묵적 경로 덮어쓰기 방지·target별 폴백 보존·최종 상태 검증 원칙을 기록. 설치와 실제 테스트 결과는 별도 증거로 확인한다.

## 2026-10-02 | messaging-dispatch-context
- 텔레그램 후속 턴에서 native dispatcher ID는 있지만 ContextVar ID가 비어 라우팅 시작이 거부되는 경로를 재현.
- 프로필·메시징 경로가 바인딩된 호출에만 dispatcher ID를 작업 범위로 보완하는 경계와, native adoption/observer까지 동일 범위를 유지하는 테스트 원칙을 기록. 실제 설치·실행 결과는 별도 검증 증거로 판단한다.

## 2026-10-01 | single-save-and-timeout
- 사용자 요청: 미리보기를 필수 절차에서 빼고 실시간 참고 요약 + 단일 저장 버튼으로 변경. 서버 단일 계획·revision/CAS·중복 쓰기 차단은 유지.
- `body.timeout`과 SDK 세 번째 RPC 대기 인자의 서로 다른 제한, 같은 YAML을 키마다 파싱하는 지연을 조사. 정확한 bytes 비교 캐시와 반환값 복사로 외부 수정 감지를 보존한다. 실제 설치·응답 결과는 별도 검증 증거로 판단한다.

## 2026-10-01 | default-all-application-targets
- 사용자 요청: 모델·세 폴백의 초기 적용 대상을 전체 선택하며, 읽기 전용 폴백은 제외한다. 초기 체크가 복사/저장 의도가 되지 않게 유지한다.
- 사용자 확인: 라우팅 활성 상태는 전체 체크 대상이 아니며 기존 설정을 표시한다. ‘불러온 프로필만’ 의미와 수동 부분·빈 대상 보존을 문서화한다.

## 2026-10-01 | fallback-whole-page-save
- 사용자 요청으로 폴백별 동의 체크박스를 비용·동작 고지로 대체하고 메인 대화/Heavy·Light 코딩·검증/네이티브 위임 설명을 분리.
- 기존 전체 저장의 폴백 누락을 단일 계획 구성으로 수정하는 계약, 독립 대상·수정하지 않은 범위 보존·빈 대상 차단 원칙을 기록. 실제 설치/검수 완료는 별도 실행 증거로 판단한다.

## 2026-10-01 | native-background-output
- 사용자 승인: 별도 입력창 진행 UI를 폐기하고 기존 Background 상세 터미널에만 정제된 공개 활동/종료 요약을 연결한다. 아래 public-progress-ui 설계를 대체한다.
- native process 소유권, 부모/profile/runtime 고정, 공개 출력 이중 정제, 한도·실패 시 관찰만 종료하는 경계를 기록. 의미적 GO는 실행 종료와 분리한다.

## 2026-10-01 | public-progress-ui
- 입력창 위 실제 라우팅 작업의 경과 시간·최신 공개 활동 표시와 프로필/durable/runtime 부모 범위 고정을 기록.
- per-composer SDK context 부재에 따른 다중 가시 입력창 표시 억제, 완결 공개 메시지/도구 이름만 전달하는 privacy 경계, Windows atomic 인덱스 경로 길이 함정을 기록. 설치와 live 검증은 별도의 증거로 판단한다.

## 2026-10-01 | routed-resume-lineage
- `subagent` source만으로 메인 세션 재개 탐색에서 제외되지 않는 Hermes 호환성 함정을 기록. 네이티브 위임 생성 메타데이터를 첫 저장 전에 설정하고 지원되지 않는 런타임은 호출 전에 거부한다.
- 목록 표시 테스트와 재개 계보 검증을 분리하고, 실제 SessionDB 기반 부모/자식/정상 후속 대화 회귀 검증을 추가한다. 설치 hotfix와 정식 소스가 같은 내용을 유지해야 한다.

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

## 2026-09-30 | headless-subagent-launch
- 사용자 요청에 따라 공개 표시 접두어를 `서브 에이전트 작업:`으로 변경하되 네이티브 위임 lifecycle과 분리 유지.
- detached 작업자의 하위 실행기/adapter가 보이는 콘솔을 만드는 Windows 재현과 각 단계의 창 억제 경계를 기록.

## 2026-09-30 | readable-background
- 공개 표시용 작업명·대상 모델과 private 프롬프트/로그의 경계를 기록. 긴 ID는 기본 표시에서 제거하고 정제된 터미널 안내에 유지.
- 네이티브 process 소유권·중지·완료 계약과 표시 실패 시 재실행 금지 원칙을 유지. 별도 카드형은 stored/runtime ID·프로필 소유권 검증 뒤 분리.
