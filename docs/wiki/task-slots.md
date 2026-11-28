# 작업 슬롯

에이전트는 작업의 목적(`purpose`)을 보내고, 프로필은 그 목적에 해당하는 슬롯의 모델과 전체 실행 시간 제한을 정한다. 모든 슬롯에 같은 선택 규칙이 적용된다.

| 슬롯 | 목적 |
|---|---|
| `design` | `plan` |
| `code-complex` | `implementation` |
| `code-simple` | `mechanical` |
| `verify-simple` | `preliminary-review` |
| `verify-complex` | `semantic-final`, `independent-review` |
| `computer-use` | `computer-use` |
| `advise` | `advise` (`ask_advisor` 전용) |

간단한 설계는 메인이 직접 한다. `preliminary-review`는 필수 계획이나 최종 의미 검토·독립 검수를 대신하지 않는다. `computer-use`는 화면 조작에 쓸 모델을 선택할 뿐 부모에게 없는 도구를 부여하지 않는다.

## 모델과 실행 시간

각 슬롯 행에서 ‘기본 대화 모델과 같게’(`follow: main`) 또는 ‘직접 지정’(`follow: custom`)을 고른다. 설정한 적 없는 슬롯은 해당 프로필의 현재 Main 모델을 쓴다. `main`은 다음 실행에서 변경된 Main 모델을 따라가고, `custom`은 직접 지정한 모델을 유지한다.

같은 행에 전체 실행 시간 제한을 **분**으로 입력한다. 빈칸이면 2시간(7200초), `0`이면 그 슬롯에 대한 플러그인 전체 시간 제한이 없다. 일반 위임·프로필 위임 시간은 별도다. 자세한 내용은 [[total-runtime-limits]]를 참고한다.

## 저장 형식

기본 Hermes 루트의 `plugin-data/model-router/settings.json`은 모든 프로필이 공유한다. schema 5의 최상위 키는 `schema`, `revision`, `custom_slots`, `profiles`다. `profiles[이름]`은 `models`, `routing: {enabled, slots}`, `native_fallback`, `delegation_fallback`, `fallback_consent: {native, delegation}`을 담는다. 슬롯 선언은 `routing.slots[슬롯 ID]`에 저장한다. 이전 형식은 읽거나 자동 변환하지 않는다. 설정 화면은 오류를 표시하고 라우팅을 거절한다. v0.17에서 올리는 절차는 [설치 안내](../../INSTALL.md)에 있다.

## 사용자지정 슬롯

운영자는 **사용자지정 슬롯**에서 최대 4개를 정의한다. `custom_slots`는 `{id, label, description}`의 순서 있는 목록이다. 정의는 프로필 공용이지만 모델과 시간 제한은 프로필별이다. 이미지·영상 생성기 대신 해당 작업을 맡을 에이전트 모델을 고르는 설정이다.

- `id`: `custom:` 뒤에 영문 소문자·숫자·하이픈 2~32자. 첫 글자는 영문 소문자나 숫자다. ID가 그대로 목적이 되며 저장 후 바꿀 수 없다.
- `label`: 1~24자. `description`: 한 줄 1~120자. 앞뒤 공백이나 제어·서식 문자는 허용하지 않는다. 이름과 설명은 에이전트에게 지시가 아닌 작업 범위로 전달한다.
- 정의는 `custom-slots-preview` → `apply`로 저장한다. 삭제하면 모든 프로필에서 그 슬롯의 모델 선언도 함께 제거한다. 새 목적 목록은 새 세션부터 보이며 이미 지운 목적은 실행 시 거절한다.

## 예비 모델과 자문

`delegation.backends.model-router`와 `delegation.backends.model-router-auto`의 schema 2 블록은 각 내장 슬롯에 `{mode, chain, consent}`를 둔다. 동의는 프로필·백엔드·슬롯·정확한 체인에 묶인다. 사용자지정 슬롯은 예비 모델 없이 실행한다. [[fallback-boundaries]] 참고.

`advise` 슬롯은 위임이 아니라 자문이다. 일하는 에이전트가 `ask_advisor(question, context)`를 부르면 같은 도구 호출 안에서 답을 받아 이어서 일한다.

- **동기 실행:** 일반 `delegate_task`는 최상위에서 항상 백그라운드로 돈다. 도구는 코어 `delegate_task(background=False)`를 등록된 `tool_execution` 미들웨어 체인(`run_tool_execution_middleware`)을 거쳐 직접 부르므로 실행 시간 제한·Fast 상속 등은 일반 위임과 같게 적용된다. 자식 하나, 실행 시간 300초, 출력 스키마(`recommendation`·`reasons`·`risks`·`confidence`)로 묶는다. 반복 횟수는 코어가 호출자 값을 무시하므로 `delegation.max_iterations`를 따른다. 질문은 목표(goal)가 아니라 컨텍스트에 넣어 `{user_id}`·`<my-button>` 같은 토큰도 코어 배치 검사를 통과한다.
- **읽기 전용:** `subagent_start`에서 이 호출의 goal과 부모 세션이 정확히 같은 자식, 그리고 goal이 조언 표식(`Advisor consultation <nonce>.`)으로 시작하는 모든 자식의 세션·서브에이전트 id를 묶고, `pre_tool_call` 훅이 그 세션의 `read_file`·`search_files`·`web_search`·`web_extract`·`skill_view`·`skills_list`·`vision_analyze` 외 모든 도구를 막는다. 압축으로 세션 id가 바뀌면 `post_compaction`으로 따라간다. 도구 호출은 세션 id 또는 task id(자식의 task id는 서브에이전트 id이며 바뀌지 않는다)로 판별한다. 그 자식에 대한 `delegate_task(action='continue')`도 공백이 섞인 id까지 막는다. 가드 자체의 내부 오류는 호스트 동작과 관계없이 차단으로 처리한다. 바인딩은 플러그인 모듈 밖의 프로세스 단위 저장소에 프로필별로 두므로 설치·활성화·업데이트·자동 적용에 따른 플러그인 재로드 뒤에도 유지된다. 언로드와 재등록 사이의 순간과 플러그인 비활성화는 보호 범위 밖이다.
- **묶지 못하면 버린다:** 자식이 시작됐는데 세션 id를 받지 못했거나, 둘 이상이 시작됐거나, 묶인 시작 없이 결과가 돌아오면 답을 버리고 `guard_unbound`로 거절한다.
- **`delegate_task`로는 못 보낸다:** 목적 enum에는 `advise`가 있지만(코어가 enum 밖 값을 거절하므로), 라우트는 진행 중인 `ask_advisor` 호출의 바로 그 goal에만 열린다. 그 밖에서는 `purpose advise runs only through the ask_advisor tool`로 거절한다.
- **같은 모델이면 건너뛴다:** `advise` 슬롯이 부모와 같은 제공자·모델로 해석되면 위임하지 않고 `skipped`를 돌려준다.
- **도구 노출:** 가드 훅 등록에 성공하고 그 프로필의 작업 분담이 켜져 있을 때만 도구가 보인다. 세션의 위임 방식이 `model-router` 또는 `model-router-auto`가 아니면 거절한다. 위임 깊이 여유가 있는 에이전트만 물을 수 있다(기본 `max_spawn_depth: 1`에서 위임된 자식은 `depth_limit`).
- 자식은 이 대화를 보지 못한다. 필요한 사실·경로·발췌는 `context`로 넘긴다. 조언은 판단 재료이지 검증된 사실이나 승인이 아니며, 필수 최종 의미 검토나 독립 검수를 대신하지 않는다.

관련: [[model-selection]], [[native-delegation]], [[index]].
