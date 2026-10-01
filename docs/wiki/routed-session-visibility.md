# 라우팅 작업 표시와 자식 세션 분류

## 의미와 경계

- 코딩 라우팅은 별도 실제 프로세스에서 실행되는 작업이다. 네이티브 위임 lifecycle이나 delegate 기록을 위조하지 않고, 실제 worker를 Hermes의 기존 Background 추적기에 연결한다.
- 부모 정보는 현재 호출의 ContextVars에서 가져온다. 공유 호스트의 전역 환경 값이나 모델이 제공한 값을 부모·프로필·UI 식별자로 보충하지 않는다. 불완전한 Desktop context는 실행 전에 거부한다.
- 작업이 이미 시작된 뒤 표시 이벤트가 실패하면 degraded tracking으로 기록한다. 표시 복구를 위해 작업을 중복 실행하지 않는다. 별도 완료 모델 턴을 추가하지 않으며 결과·실제 모델 증거는 기존 작업 조회에서 확인한다.
- 새 자식은 `subagent`로 분류한다. 이는 세션 목록용 source/platform 분류이며 네이티브 delegate lifecycle 생성과는 별개다.
- 목록용 source와 재개용 계보 구분은 별개다. 부모가 있는 라우팅 자식은 첫 대화 저장 전에 네이티브 위임과 동일한 `_delegate_from` 생성 메타데이터를 기록해야 한다. source만 지정하면 일부 Hermes 버전의 재개 탐색이 자식을 압축 후속 대화로 오인해 메인 세션 대신 열 수 있다. 이 표시를 기록할 런타임 계약이 없으면 모델 호출 전에 실패 처리한다. 부모 없는 실행에는 임의의 부모 표시를 만들지 않는다.
- 재개 회귀 검증은 실제 `SessionDB`로 메인·자식 각각의 열기, 원래 메인 대화 보존, 정상 후속 대화 탐색까지 확인한다. 모델 호출은 격리된 fixture로 대체하고, 목록 필터 테스트만으로 재개 안전성을 판정하지 않는다.

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
- 이 source-only 도구는 누락된 위임 계보 표시를 보충하지 않는다. 새 버전 설치도 과거 DB를 자동 교정하지 않는다. 기존 메인→서브 오연결은 정확한 부모·작업 증거를 확인하고, 대상 세션/대화 백업과 전후 해시 검증을 갖춘 별도 승인 복구로 처리한다.

## Windows 콘솔 창 억제

- 최상위 작업자를 `DETACHED_PROCESS`로 실행해도 그 아래 콘솔 실행 파일이 창 없이 실행되는 것은 아니다. 실행기·scoped adapter에는 `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`을 각각 명시한다. `CREATE_NO_WINDOW`를 `DETACHED_PROCESS`와 함께 지정하면 창 억제 플래그가 무시되므로 최상위 detached 옵션과 구분한다.
- task-owned timeout 정리의 `taskkill`에도 창 억제 옵션을 명시한다. stdio, close_fds, PID/트리 소유권과 증거 계약은 유지한다. 에이전트가 도구로 별도 실행하는 외부 프로그램 전체의 창 억제는 이 변경의 보장 범위가 아니다.
- 실제 detached 부모 아래 production adapter launch seam을 실행해 콘솔 연결/가시성을 검사한다. 단순 kwargs mock만으로 창 억제 성공이라고 보고하지 않는다.

## 사람이 읽을 수 있는 작업 표시

- `coding_route.start`의 짧은 `title`은 공개 표시 메타데이터다. 비밀·개인 프롬프트·고객 자료를 넣지 않는다. 96자 제한과 제어문자 검증은 spawn 전에 수행하며, 제목은 실행 권한·모델 관측·runner identity에 쓰지 않는다.
- Background의 기본 이름은 `서브 에이전트 작업: <작업명> · Heavy/Light · <대상 모델>`이다. UUID는 기본 제목에서 빼고 터미널 안내에 남긴다. 제목을 생략한 예전 호출은 고정 한국어 용도 이름을 사용하며 프롬프트를 자동 요약하지 않는다.
- 파일 기반 private 로그를 터미널에 복사하지 않는다. 실제 채택된 process의 공개 output buffer에 정제된 시작 안내와 제한된 활동·종료 요약만 넣는다. 대상 모델과 실제 관측 모델은 별개이며, 프로세스 종료는 의미적 검수 GO가 아니다.
- 전체 process 목록이나 다른 session ID로 fallback하지 않고 네이티브 Background 중지 계약은 그대로 둔다.

## 기존 Background 출력 확장 — 현재 계약

- 입력창 위 별도 진행 목록은 폐기했다. 단일 가시 composer와 focused/primary 일치만으로 입력창 소유권이 입증되지 않았으므로 표시 조건을 완화하지 않고 UI·DOM 감시·타이머·전용 CLI/부모 인덱스 자체를 제거한다. 새 패널/가짜 delegate 이벤트로 대체하지 않는다.
- 이미 채택된 정확한 ProcessSession에만 공개 활동을 추가한다. native process ID뿐 아니라 같은 registry 객체, Popen, PID, raw owner task, session key, durable parent와 작업 snapshot의 profile/runtime을 검증한다. 실제 작업의 launch readback 전에는 활동을 전달하지 않는다.
- daemon 관찰자는 시작 ContextVars를 복사하여 기존 status.update process refresh를 발행한다. 전역 focused 대화를 추측하지 않는다. 고정 작업 아래 최대 두 시도만 읽고 크기/경로/심볼릭 링크/identity/시간을 검증하며 출력 직전 전체 활동을 다시 정제한다. private 로그·답변은 읽거나 전달하지 않는다. 요청 파일은 시도 identity 비교에만 사용하며 prompt 등은 출력하지 않는다.
- 기존 public writer는 observer 부작용, 실제 callback 인자 순서, 완결 공개 중간 메시지 정제와 trailing flush를 보존한다. 최신 스냅샷을 관찰하므로 빠른 활동은 합쳐질 수 있다. 조용한 동안 마지막 활동을 반복하거나 가짜 heartbeat를 넣지 않는다.
- 활동 기록은 줄/문자 한도를 두고 제한 안내는 한 번만 남긴다. ProcessRegistry의 종료를 관측한 뒤 공개 스냅샷을 다시 읽고 종료 확인/소요 시간을 한 번 추가한다. native kill이 reader 종료 사유를 나중에 정정할 수 있으므로 정상/실패/중지를 관찰자가 불변 판정하지 않는다. 의미적 GO/FAIL을 최종 답변에서 추론하지 않는다. private 결과 전문을 공개하지 않는다.
- 관찰 실패·한도·소유권 소실은 표시만 중단하며 모델 작업을 재시작/중지하지 않는다. worker 회수·kill·종료 코드와 알림 소유권은 native registry에 남긴다. 종료 알림과 마지막 요약의 선후관계는 보장하지 않는다. 후행 출력은 현재 호스트의 메모리 출력이며 native 보존 receipt/재시작 후 재조회에는 없을 수 있다. 보존 receipt를 임의 갱신하지 않는다.
- 오래된 progress-index와 과거 private 증거는 읽지 않고 보존한다. 코드 제거가 작업/대화 자료 삭제를 뜻하지 않는다. 새 작업에만 관찰자를 붙이며 live backend를 재시작하지 않는다.

## 설치 및 검증

- 파일 반영, 플러그인 재탐색, 현재 화면의 실제 동작은 각각 따로 확인한다. 프로필 모델·폴백·라우팅 opt-in 설정을 설치 편의상 바꾸지 않는다.
- named Desktop backend는 default home의 activation 요청을 거부할 수 있다. 기본 프로필의 지원되는 gateway plugin reload 또는 다음 정상 세션 생성을 사용한다. 공유 백엔드를 강제로 재시작하지 않는다.
- 실제 routed 작업으로 Background 표시 → 정상 완료 후 표시 해제, 새 자식의 일반 목록 제외, session-scoped `process.kill`의 실제 프로세스 트리 종료를 검증한다. 전역 `process.stop`은 다른 작업까지 죽일 수 있으므로 테스트에 사용하지 않는다.
- 강제 중지는 worker의 terminal artifact 작성을 중단할 수 있다. registry의 `killed`/실제 프로세스 부재는 중지 증거이고, artifact가 없는 작업 조회는 `unverified`로 남을 수 있다. 이를 성공으로 바꾸거나 자동 재실행하지 않는다.
