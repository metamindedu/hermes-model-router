# 작업 슬롯

위임 작업의 모델은 Heavy/Light 두 등급이 아니라 **슬롯**마다 직접 정한다. 슬롯은 운영자가 모델을 지정하는 단위이고, 목적(`purpose`)은 에이전트가 보내는 값이다. 기존 목적 이름은 그대로이므로 내장 정책은 그대로 쓴다. 단, 슬롯 도입 전 코드로 실행 중인 프로세스는 슬롯 설정을 읽지 못한다(아래 ‘함정’).

| 슬롯 | 목적 | 등급 |
|---|---|---|
| `design` | `plan` | heavy |
| `code-complex` | `implementation` | light |
| `code-simple` | `mechanical` | light |
| `verify-simple` | `preliminary-review` | light |
| `verify-complex` | `semantic-final`, `independent-review` | heavy |
| `computer-use` | `computer-use` | light |
| `advise` | `advise` (`ask_advisor` 도구만) | heavy |

`설계 · 간단` 슬롯은 일부러 두지 않았다. 간단한 설계는 메인이 직접 한다.

## 등급이 남아 있는 이유

등급(heavy/light)은 슬롯별로 나누지 않은 것들의 내부 묶음일 뿐이다: 두 개의 실행 시간 제한, watchdog 역할, 런타임 라벨(`model:heavy` / `model:light`), 그리고 한 번도 저장하지 않은 슬롯의 의미. 운영자가 모델을 고르는 대상이 아니다. 필수 검수 규칙은 목적 이름에 묶여 있으므로 슬롯 모델을 바꿔도 규칙은 그대로다.

## 저장 형식

- `settings.json`의 `routing.slots`는 선택 항목이다. 없는 슬롯은 자기 등급의 기존 `routing.heavy` / `routing.light` 선언으로 해석하므로, 건드리지 않은 설치는 이전과 똑같이 동작하고 읽을 때 아무것도 옮기지 않는다.
- 슬롯 선언은 `{follow: main|delegation|custom, custom}`이다. `main`/`delegation`은 눈에 보이는 모델 역할을 따라가는 연결이고 추상 등급을 따라가는 것이 아니다.
- 파일 schema는 어떤 프로필이든 `slots`를 가진 동안에만 3이다. 그렇지 않으면 2로 남아 슬롯을 실제로 쓰기 전까지는 이전 버전으로 되돌릴 수 있다.
- 저장소 파일은 모든 프로필이 공유한다. 한 프로필이 슬롯을 저장하면 다른 프로필에 설치된 패키지도 그 파일을 읽어야 하므로, 설치된 모든 프로필의 패키지가 슬롯을 읽을 수 있을 때만 슬롯 저장을 받는다(`slot_capabilities.blocking_profiles`).
- 슬롯을 모르는 이전 화면의 저장은 `slots` 키를 보내지 않는다. 이때 저장된 슬롯은 그대로 둔다. 빈 맵 `{}`을 보내야 지워진다.

## 슬롯별 예비 모델

- 프로필 config의 `delegation.backends.model-router[-auto]` 블록 schema 2는 슬롯 id별 `{mode, chain, consent}`이다. 동의는 슬롯 id·backend·프로필·정확한 체인에 묶인다.
- schema 1 블록(heavy/light)은 계속 유효하며 등급 단위로 적용한다. 읽을 때 다시 쓰지 않고, 그 동의를 슬롯 동의로 재사용하지 않는다. 슬롯 형태로 저장하는 순간에만 새 동의와 함께 schema 2가 된다.
- 저장된 블록이 schema 2이면 두 역할 형태의 저장은 거절한다. 이전 화면이 슬롯별 예비 모델을 조용히 지우지 못하게 하기 위해서다.
- 블록이 깨졌으면 그 블록에 이름이 없는 슬롯의 작업도 거절한다. 약속한 정책 없이 실행하지 않는다.
- 동의 계산은 설정 쪽(`native_settings`)과 실행 쪽(`native_delegation`)에 따로 있다. 둘이 같은 값을 내는지 테스트로 고정한다.

## 컴퓨터 유즈

하위 작업은 부모의 도구를 물려받고, 막히는 것은 재위임·사용자 질문·메모리·메시지 전송·예약뿐이다. 그래서 `computer-use` 목적은 화면 조작에 맞는 모델을 고르게 할 뿐 새 도구를 주지 않는다. 부모 세션에 브라우저·데스크톱 도구가 없으면 이 슬롯으로 보내도 쓸 수 없다.

## 조언 (v0.16.0)

`advise` 슬롯은 위임이 아니라 자문이다. 일하는 에이전트가 `ask_advisor(question, context)`를 부르면 같은 도구 호출 안에서 답을 받아 이어서 일한다.

- **동기 실행:** 일반 `delegate_task`는 최상위에서 항상 백그라운드로 돈다. 도구는 코어 `delegate_task(background=False)`를 등록된 `tool_execution` 미들웨어 체인(`run_tool_execution_middleware`)을 거쳐 직접 부르므로 실행 시간 제한·Fast 상속 등은 일반 위임과 같게 적용된다. 자식 하나, 실행 시간 300초, 출력 스키마(`recommendation`·`reasons`·`risks`·`confidence`)로 묶는다. 반복 횟수는 코어가 호출자 값을 무시하므로 `delegation.max_iterations`를 따른다. 질문은 목표(goal)가 아니라 컨텍스트에 넣어 `{user_id}`·`<my-button>` 같은 토큰도 코어 배치 검사를 통과한다.
- **읽기 전용:** `subagent_start`에서 이 호출의 goal과 부모 세션이 정확히 같은 자식, 그리고 goal이 조언 표식(`Advisor consultation <nonce>.`)으로 시작하는 모든 자식의 세션·서브에이전트 id를 묶고, `pre_tool_call` 훅이 그 세션의 `read_file`·`search_files`·`web_search`·`web_extract`·`skill_view`·`skills_list`·`vision_analyze` 외 모든 도구를 막는다. 압축으로 세션 id가 바뀌면 `post_compaction`으로 따라간다. 도구 호출은 세션 id 또는 task id(자식의 task id는 서브에이전트 id이며 바뀌지 않는다)로 판별한다. 그 자식에 대한 `delegate_task(action='continue')`도 공백이 섞인 id까지 막는다. 가드 자체의 내부 오류는 호스트 동작과 관계없이 차단으로 처리한다. 바인딩은 플러그인 모듈 밖의 프로세스 단위 저장소에 프로필별로 두므로 설치·활성화·업데이트·자동 적용에 따른 플러그인 재로드 뒤에도 유지된다. 언로드와 재등록 사이의 순간과 플러그인 비활성화는 보호 범위 밖이다.
- **묶지 못하면 버린다:** 자식이 시작됐는데 세션 id를 받지 못했거나, 둘 이상이 시작됐거나, 묶인 시작 없이 결과가 돌아오면 답을 버리고 `guard_unbound`로 거절한다.
- **`delegate_task`로는 못 보낸다:** 목적 enum에는 `advise`가 있지만(코어가 enum 밖 값을 거절하므로), 라우트는 진행 중인 `ask_advisor` 호출의 바로 그 goal에만 열린다. 그 밖에서는 `purpose advise runs only through the ask_advisor tool`로 거절한다.
- **같은 모델이면 건너뛴다:** `advise` 슬롯이 부모와 같은 제공자·모델로 해석되면 위임하지 않고 `skipped`를 돌려준다.
- **도구 노출:** 가드 훅 등록에 성공하고 그 프로필의 작업 분담이 켜져 있을 때만 도구가 보인다. 세션의 위임 방식이 `model-router` 또는 `model-router-auto`가 아니면 거절한다. 위임 깊이 여유가 있는 에이전트만 물을 수 있다(기본 `max_spawn_depth: 1`에서 위임된 자식은 `depth_limit`).
- 자식은 이 대화를 보지 못한다. 필요한 사실·경로·발췌는 `context`로 넘긴다. 조언은 판단 재료이지 검증된 사실이나 승인이 아니며, 필수 Heavy·독립 검수를 대신하지 않는다.

## 함정

- **업데이트 후 재시작 전에 슬롯을 저장하지 않는다.** 저장 가능 여부(`blocking_profiles`)는 디스크의 패키지만 본다. 플러그인을 업데이트했더라도 아직 재시작하지 않은 데스크톱·게이트웨이·열린 세션은 이전 코드를 메모리에 들고 있고, 첫 슬롯 저장(저장소 schema 3) 뒤에는 모든 프로필에 대해 `settings schema is invalid`로 설정 읽기와 목적 라우팅을 거절한다. 슬롯별 예비 모델 저장(config 블록 schema 2) 뒤에는 그 프로필의 작업을 거절한다. 쓰기는 일어나지 않고 재시작하면 풀린다. 설치 순서는 모든 프로필 업데이트 → 모든 Hermes 프로세스 재시작 → 첫 슬롯 저장이다. 화면은 아무 슬롯도 저장된 적이 없을 때 이 안내를 보여 준다.
- 저장 가능 여부는 preview와 apply 양쪽에서 확인한다. 어떤 프로필의 슬롯을 새로 쓰거나 바꾸는 계획만 apply에서 다시 막고, 슬롯을 지우기만 하는 저장은 막지 않는다(복구 경로).
- Hermes는 CLI 호출 하나의 출력 중 48,000자까지만 화면에 돌려준다. 프로필이 많으면 상태 전체가 이 한도를 넘으므로 화면은 `status`를 `{"paged": true}`로 불러 30,000자 이하의 묶음으로 나눠 읽고, 개정 번호·설치 식별값·프로필 목록이 모두 같을 때만 이어 붙인다. 본문 없는 `status`는 이전처럼 전체를 한 번에 돌려준다. 미리보기 응답이 40,000자를 넘으면 CLI는 각 변경의 프로필과 항목 이름만 남겨 보내고(`changes_compacted`), 저장된 계획과 apply가 쓰는 값은 그대로다.
- 슬롯을 읽을 수 있는지는 `slots.py` 파일 내용이 같은지로 판단한다. 이후 단계에서 이 파일을 바꾸면 순차 업데이트 도중에는 새 패키지와 이전 패키지가 서로를 ‘읽을 수 없음’으로 본다. v0.16.0이 `advise`를 더하며 이 파일을 바꿨으므로, 모든 프로필을 업데이트하고 재시작할 때까지 슬롯 저장이 막힌다.
- v0.16.0 이전에 저장한 슬롯별 예비 모델 블록(schema 2)은 여섯 슬롯만 가진다. 이 정확한 키 집합은 계속 유효하며 `advise`는 꺼진 것으로 읽는다(`slots.LEGACY_SLOT_SETS`). 그 밖의 불완전하거나 남는 키 집합은 이전처럼 거절한다. 그 블록에 슬롯 하나를 패치하면 일곱 슬롯 블록으로 저장된다.
- 요청 본문은 16,384자를 넘으면 백엔드가 읽기 전에 거절한다. 슬롯별 예비 모델은 대상 프로필마다 모든 슬롯(v0.16.0부터 일곱)을 보내므로 대상이 많고 예비 모델이 길면 한도에 닿는다. 화면이 보내기 전에 이유를 알리고 대상을 나눠 저장하도록 안내한다.
- 실행 경로에서 슬롯 경로가 없는 설정(`slots` 키 없음)은 슬롯 도입 전 형태로 보고 등급 경로로 해석한다. 키가 있으면 반드시 그 값을 쓴다.
- Python 테스트는 Hermes 인터프리터로 돌린다. `uv run --with pytest`만으로는 `tui_gateway` 등 코어 모듈이 없어 수집 단계에서 실패한다. pytest는 임시 경로에 따로 설치해 프로세스 안에서 `sys.path`에 추가한다(운영 환경에 설치하지 않는다).

See [[model-selection]], [[profile-boundaries]], [[fallback-boundaries]], [[total-runtime-limits]] and [[index]].
