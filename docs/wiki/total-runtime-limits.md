# 서브 에이전트 전체 시간 제한

## 결정

일반 native 자식과 process-backed 라우팅 작업의 **전체 경과 시간**을 별도 플러그인 옵션으로 둔다. 설치된 Hermes의 `delegation.child_timeout_seconds`는 진행 신호가 없는 시간의 제한이므로 숫자 상속이나 기존 키 편집으로 두 요구를 혼합하지 않는다. Native 전체 시간 기본 0은 기존 무제한 동작을 보존하고, routed 기본 3600은 짧은 기본값/별도 900 상한으로 정상 작업을 반복 중단하던 경계를 완화한다.

## 설정 저장 경계

- 프로필별 `plugin-data/model-router/timeouts.json`을 공유 모델/폴백 schema와 분리한다. 이전 프로필 설치가 공유 settings를 계속 읽을 수 있어야 한다.
- 시간 옵션은 불러온 프로필에만 명시적으로 수정한다. 모델/Heavy·Light/폴백의 일괄 대상 선택이 시간 옵션 복사 승인이 되지 않는다.
- 기존 immutable 단일 preview/apply에 파일 digest와 독립 시간 revision을 합성한다. 다른 설정에 쓰기 전에 모든 시간 CAS를 확인하고, 부분 실패와 실제 readback을 유지한다. 수정하지 않은 시간 옵션은 읽기 전용 모델/폴백 저장으로 다시 기록하지 않는다.
- Native inactivity·모델·fallback consent·실행 중 정책은 변경하지 않는다. 새 자식/작업만 시작 시 값을 고정한다.

## 일반 native 적용 함정

- `subagent_start` observer는 자식 구성/큐 대기 전에 발생할 수 있다. 이 훅 시점이나 batch dispatch부터 전체 시간을 세면 큐 대기가 자식 실행 예산을 소모한다.
- 설치된 owned `delegate_task(action="list")`는 `started_at` 원문 대신 실제 native 등록 시각에서 계산한 `running_seconds`를 노출한다. 첫 확인에서 이 값을 사용하여 monotonic deadline을 한 번 바인딩하고, 이후 진행/조회 때 다시 시작하지 않는다.
- 실제 tool execution middleware의 부모/profile 권한과 생성 훅의 정확한 child ID를 묶는다. 비동기 spawn 응답 뒤에도 관찰하되 종료/미확인/다른 부모·profile은 조작하지 않는다. Private registry를 재작성하거나 native lifecycle을 위조하지 않는다.
- Native 소유권 검증을 거치는 정확한 자식 stop 요청을 사용한다. `interrupt_requested`는 종료 증거가 아니다. 공유 Python process나 DB를 강제로 닫지 않는다. 플러그인 unload는 자체 관찰만 정리하며 실행 중 자식 자체는 종료하지 않는다.

## 라우팅 적용 함정

- 도구 schema·CLI·Router·worker·runner·scoped agent·활동 observer의 제한이 모두 일치해야 한다. 상위 기본값을 바꾸고 내부 900 검사나 observer를 남기면 긴 작업이 여전히 실패하거나 표시가 먼저 끝난다.
- 0을 `None` process wait와 deadline 없음으로 전달한다. JSON에 Infinity/NaN 같은 대체값을 쓰지 않는다. 비유한·음수·bool은 입력 오류이다.
- 양수의 primary/fallback은 하나의 전체 deadline을 공유한다. 기존 정리 grace는 실행 예산 재시작이나 자동 재실행 승인이 아니다. 종료·route identity·semantic GO는 별도로 확인한다.
- 에이전트는 보통 호출 `timeout`을 생략한다. 작업이 작거나 읽기 전용이라는 이유로 180/300/600/900의 임의 짧은 override를 넣으면 프로필의 넉넉한 기본값을 무효화한다.

현재 배포/실행 상태와 실제 검증은 코드·설치 hash·테스트·신규 작업 evidence로 확인한다. 이 문서 자체는 실행 성공의 증거가 아니다.
