# 라우팅 작업 표시와 자식 세션

슬롯·프로필 위임은 Hermes의 `delegate_task`로 실행한다. 진행 상태와 중지·추가 지시·결과 전달은 Hermes가 관리한다. 입력창의 **실행 현황**은 해당 대화에 연결된 자식만 표시한다. `execution-roster/2`의 모델 작업 행에는 슬롯 ID가 들어간다. `model-router`는 슬롯 ID를, `model-router-auto`는 `model:<슬롯>` 또는 `profile:<이름>`을 보고한다. 요청한 모델과 실제 응답 모델은 같은 증거가 아니다.

v0.18에서 별도 프로세스 실행기와 Background 활동 표시가 제거되었다. `coding_route`는 설정만 읽으며, 이전 프로세스 작업을 조회하거나 조인할 수 없다. 과거 작업 ID로 네이티브 자식을 조회하지 않는다. 게이트웨이 소유의 전체 프로필 작업은 별도 기능이다.

관련: [[execution-jobs]], [[native-delegation]], [[index]].
