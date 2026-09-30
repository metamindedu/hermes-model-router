# 라우팅 작업 표시와 자식 세션 분류

## 의미와 경계

- 코딩 라우팅은 별도 실제 프로세스에서 실행되는 작업이다. 네이티브 위임 lifecycle이나 delegate 기록을 위조하지 않고, 실제 worker를 Hermes의 기존 Background 추적기에 연결한다.
- 부모 정보는 현재 호출의 ContextVars에서 가져온다. 공유 호스트의 전역 환경 값이나 모델이 제공한 값을 부모·프로필·UI 식별자로 보충하지 않는다. 불완전한 Desktop context는 실행 전에 거부한다.
- 작업이 이미 시작된 뒤 표시 이벤트가 실패하면 degraded tracking으로 기록한다. 표시 복구를 위해 작업을 중복 실행하지 않는다. 별도 완료 모델 턴을 추가하지 않으며 결과·실제 모델 증거는 기존 작업 조회에서 확인한다.
- 새 자식은 `subagent`로 분류한다. 이는 세션 목록용 source/platform 분류이며 네이티브 delegate lifecycle 생성과는 별개다.

## 프로필 격리와 런타임 기동

- 자식 환경은 Hermes의 대상 프로필 환경·자격 정보 경로로 생성한다. 다른 프로필의 키를 상속해 실행을 성공시키지 않는다.
- 일반 자식 환경 helper는 Hermes-owned Python 경로를 제거한다. 번들 Python의 `sys.executable`로 직접 Hermes를 구동하는 worker는 가상환경 Python이 아닐 수 있다. 같은 인터프리터를 사용하는 라우팅 자식에는 이미 로드된 core와 실제 사용 중인 PM generation의 dependency 경로만 전달한다. 임의의 inherited/project `PYTHONPATH`나 새로 선택됐지만 호스트가 사용하지 않는 generation을 복사하지 않는다.
- 프로필 설치본에는 레포에 아직 반영되지 않은 운영 hotfix가 있을 수 있다. 덮어쓰기 전에 설치본과 소스를 비교하고 보존한다. Codex picker alias는 선택된 모델 identity와 wire slug를 구분해야 하며, 설치된 canonical metadata가 인정하는 alias만 해당 provider/transport에서 허용한다. 실패한 이전 증거는 수정하지 않고 새 작업으로 재검증한다.

## 기존 세션 분류 교정

`scripts/repair_routed_session_sources.py --home <정확한 프로필 home>`은 기본 dry-run이다. 실제 변경은 `--apply`로만 수행한다.

- 같은 프로필의 작업/시도 artifact로 정확한 세션 ID가 입증되고 source가 `model-router-coding-route`인 경우만 대상으로 한다.
- source before-image를 먼저 백업하고 짧은 트랜잭션의 조건부 쓰기로 `subagent`로 변경한다. CAS 충돌은 전체 롤백한다.
- 대화·부모·모델·시간·성공/실패 결과는 변경하지 않는다. 적용 후 정확한 대상을 다시 읽고 transcript/다른 필드 보존 여부를 확인한다.
- 모든 오래된 CLI 세션을 제목만 보고 자식으로 추정하거나 삭제하지 않는다.

## 설치 및 검증

- 파일 반영, 플러그인 재탐색, 현재 화면의 실제 동작은 각각 따로 확인한다. 프로필 모델·폴백·라우팅 opt-in 설정을 설치 편의상 바꾸지 않는다.
- named Desktop backend는 default home의 activation 요청을 거부할 수 있다. 기본 프로필의 지원되는 gateway plugin reload 또는 다음 정상 세션 생성을 사용한다. 공유 백엔드를 강제로 재시작하지 않는다.
- 실제 routed 작업으로 Background 표시 → 정상 완료 후 표시 해제, 새 자식의 일반 목록 제외, session-scoped `process.kill`의 실제 프로세스 트리 종료를 검증한다. 전역 `process.stop`은 다른 작업까지 죽일 수 있으므로 테스트에 사용하지 않는다.
- 강제 중지는 worker의 terminal artifact 작성을 중단할 수 있다. registry의 `killed`/실제 프로세스 부재는 중지 증거이고, artifact가 없는 작업 조회는 `unverified`로 남을 수 있다. 이를 성공으로 바꾸거나 자동 재실행하지 않는다.
