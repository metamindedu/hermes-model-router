# 서브 에이전트 전체 시간 제한

| 작업 | 저장값 | 지정하지 않았을 때 |
|---|---|---|
| 내장·사용자지정 슬롯 작업 | `slot_seconds[슬롯 ID]` | 슬롯당 2시간(7200초, `DEFAULT_SLOT_SECONDS`) |
| 일반 위임·프로필 위임 | `delegate_total_seconds` | `0` (플러그인 전체 시간 제한 없음) |

슬롯 행에는 **분**으로 입력한다. 빈칸은 2시간 기본값이고 `0`은 그 슬롯의 제한을 끈다. 일반·프로필 위임 제한은 슬롯에 추가로 적용하지 않는다. 요청·반복 횟수 제한과 Hermes의 무진행 시간 제한(`delegation.child_timeout_seconds`)은 별개다.

## 저장과 조회

각 프로필의 `plugin-data/model-router/timeouts.json`은 schema 3이다. 예를 들어 아래 설정에서는 `code-simple`만 제한이 없고 `design`은 30분, 나머지 슬롯은 각각 2시간이다. 일반·프로필 위임은 제한하지 않는다.

```json
{"schema":3,"revision":1,"delegate_total_seconds":0,"slot_seconds":{"code-simple":0,"design":1800}}
```

`coding_route(action="config")`는 `slot_timeout_seconds`에 슬롯별 초 값을, `delegate_timeout_seconds`에 일반·프로필 위임의 초 값을 반환한다. 저장할 때 대상 프로필별 revision과 파일 상태를 확인한다. 프로필의 설치본 `model_router/timeouts.py`에 `SLOT_TIMEOUTS_SUPPORTED = True`가 없으면 시간 제한을 저장할 수 없다. 이전 schema나 손상된 시간 파일은 읽기 전용으로 두고 덮어쓰지 않는다.

## 실행 중 적용

- 일반적으로 `delegate_task`의 `total_timeout_seconds`는 생략한다. 실제 외부 마감이 있으면 그 작업에만 적용할 **초** 값을 지정한다. `0`은 해당 작업의 플러그인 전체 시간 제한만 끈다. `ask_advisor`는 도구 자체가 자문 호출에 300초를 명시한다.
- 각 자식은 시작할 때 예산을 고정한다. Hermes가 등록한 실행 시간부터 계산하며 큐 대기는 제외한다. 진행 신호·추가 지시·예비 모델 전환으로 시계가 다시 시작되지 않는다.
- 만료 시 플러그인은 정확한 부모가 소유한 자식에 native 중지를 요청한다. 중지 요청 수락은 실제 종료 확인이 아니다. 공유 Hermes 프로세스를 강제 종료하거나 작업을 재실행하지 않는다.

관련: [[task-slots]], [[native-delegation]], [[index]].
