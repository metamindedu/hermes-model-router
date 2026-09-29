# Hermes Model Router

Hermes Desktop의 **모델 및 라우팅** 페이지에서 프로필별 모델과 코딩 작업의 Heavy/Light 경로를 관리하는 네이티브 플러그인입니다. 설정 관리와 라우팅 사용 여부는 별개입니다.

## 사용

1. 사이드바 **모델 및 라우팅**을 엽니다.
2. 기준 프로필의 설정을 불러오거나 **OpenAI / Non-OpenAI 프리셋**으로 네 모델 역할을 한 번에 채운 뒤, 필요하면 개별 값을 편집합니다. 프리셋 선택만으로 실제 설정은 바뀌지 않습니다.
3. **모델 설정 적용 대상**은 화면을 처음 열거나 연결 범위가 바뀔 때 **모든 프로필이 선택**됩니다. **전체 선택 / 전체 해제**로 일괄 조정할 수 있습니다. 사용자가 해제한 선택은 기준 프로필 변경이나 상태 새로고침으로 다시 확대하지 않습니다. 라우팅만 변경하려면 모델 적용 대상을 전체 해제하세요.
4. **코딩 라우팅 사용 프로필**에서 스킬/전용 라우팅을 사용할 프로필을 선택합니다.
5. Heavy는 메인 모델, Light는 서브에이전트 모델을 따라가는 것이 기본이며 별도 지정도 가능합니다.
6. 변경 미리보기에서 대상 프로필과 전후 값을 확인하고 적용합니다. 적용 중에는 중복 요청하지 않습니다.

저장한 설정과 실제 프로필 설정이 다른 경우 drift로 표시합니다. 실행 중인 세션의 모델/도구는 즉시 바뀐다고 가정하지 않습니다. 변경 후 코딩 작업은 새 세션에서 시작하세요.

## 모델 프리셋

기존 BAT 백업에 선언되어 있던 값을 그대로 옮긴 템플릿입니다. 최신 모델 자동 추천이 아니며, 선택 후 직접 수정할 수 있습니다. 값이 템플릿과 달라지면 사용자 지정으로 표시합니다.

| 역할 | OpenAI (`openai-codex`) | Non-OpenAI |
|---|---|---|
| 기본 대화 | `gpt-6-astra-900k` · `medium` | `xiaomi` / `mimo-v2.6-pro` · `max` |
| 작업 위임 | `gpt-6-luna-900k` · `max` | `deepseek` / `deepseek-flash` · `max` |
| 대화 압축 | `gpt-6-luna-900k` · `medium` | `deepseek` / `deepseek-flash` · `medium` |
| 제목 생성 | `gpt-6-luna` · `none` | `deepseek` / `deepseek-flash` · `none` |

프리셋은 **네 모델 역할의 편집값만** 채웁니다. 모델 적용 대상, 라우팅 활성 목록, 별도로 지정한 Heavy/Light 경로와 대체 모델·비용 허용 설정은 바꾸지 않습니다. 따라서 별도 라우팅 모델을 지정해 둔 경우 고급 라우팅 설정도 확인하세요. 제공자 인증은 기존 Hermes 설정을 사용하며 프리셋에 자격 증명은 포함하지 않습니다.

## 경계

- 모델 관리 UI는 설치된 프로필에서 사용할 수 있지만 코딩 라우팅은 선택한 프로필에서만 활성화됩니다.
- 기존 일반 `delegate_task`는 자동 교체하지 않습니다. 동봉 스킬은 Heavy 필수 검수를 `coding_route`의 명시적 목적에 따라 실행하도록 안내합니다.
- `semantic-final`, `independent-review`는 Heavy 경로입니다. Light 예비 검수로 대신하지 않습니다.
- `route_verified`는 실제 모델·제공자 증거이며 코드의 의미적 GO가 아닙니다. 최종 판정은 검수 내용과 후보를 함께 확인해야 합니다.
- 유료 대체 경로는 명시적으로 설정·허용한 경우에만 사용합니다. 임의 모델/제공자 변환을 하지 않습니다.
- API key/OAuth 정보는 기존 Hermes 인증 저장소를 그대로 사용합니다. UI나 플러그인 설정에 저장하지 않습니다.
- Hermes 코어 및 전역 delegation 설정을 작업별로 바꾸지 않습니다.

## 패키지

UI, 설정 서비스, 라우팅 작업 실행기, 동봉 스킬을 한 패키지로 배포합니다. `compat/adaptive-coding-orchestration`은 기존 bare skill 자동 탐색을 위한 작은 진입점입니다. 실제 정책은 `model-router:adaptive-coding-orchestration`에 있습니다.

초기 프로필 범위는 `docs/profile-audit.json`의 실제 스킬 탐색 결과를 보존합니다. 새 프로필은 라우팅 OFF가 기본입니다. Desktop UI는 앱 수준에서 공유되지만 런타임 도구와 작업 파일은 호출 프로필에 귀속됩니다.

## 개발 및 검증

```bash
uv run --no-project --with pytest --with pyyaml --with fastapi --with httpx python -B -m pytest tests -q -p no:cacheprovider
node --test tests/test_desktop.mjs
hermes plugins doctor . --ci
```

설정 파일은 Hermes base의 `plugin-data/model-router/settings.json`입니다. 프로필 `config.yaml`은 지원되는 `hermes config set` 명령으로만 투영합니다. 미리보기 토큰은 변경 시점의 revision과 대상 설정 digest에 묶이고, 적용 전에 다시 확인합니다. 부분 실패는 부분 실패로 기록하며 다른 작업의 설정을 자동 롤백하지 않습니다.

Desktop 화면은 인증된 `cli.exec` RPC와 플러그인 등록 CLI `hermes --profile <name> model-router status|preview|apply`를 사용합니다. 따라서 새 REST 경로 마운트를 위해 현재 대화를 끊고 백엔드를 재시작할 필요가 없습니다. 이 경로는 셸 문자열이 아니라 명시적 argv 배열이며, REST API와 같은 서비스를 사용합니다. 쓰기 실패 후 다른 전송 경로로 자동 재시도하지 않습니다.

CLI `cli.py status|preview|apply|route|job-status`도 동일한 서비스/실행기를 사용합니다. Python에는 PyYAML이 필요하며, 활성 Hermes 환경에서 실행하거나 격리된 `uv run --no-project --with pyyaml python cli.py ...`를 사용할 수 있습니다. 호출 프로필은 `HERMES_HOME`으로 명시합니다. `initialize`는 최초 관리자가 기존 설정을 가져올 때만 사용합니다.

## 설치와 복구

`scripts/install_local.py --root <Hermes base> --routing-profiles <names...>`는 쓰기 없는 계획 출력입니다. `--apply`는 검수 완료된 패키지를 각 프로필에 복사하고 플러그인/스킬 활성화 설정만 변경합니다. 모델 설정은 변경하지 않으며 프로필별 백업과 설치 receipt를 남깁니다. 기존 설치가 있으면 명시적 업데이트 없이 덮어쓰지 않습니다.

설치 후 Desktop의 네이티브 플러그인 활성화/재검색 경로로 UI를 연결합니다. Python 도구는 다음 세션에 반영되는 경우가 있습니다. 실행 중 작업을 끊기 위해 전체 앱/게이트웨이를 재시작하지 않습니다.

기존 `hermes-set-all-models.bat`는 설정 원본에서 제외하고 같은 UI를 여는 호환 바로가기로 전환합니다. 원본 BAT와 이전 스킬은 전환 전 백업합니다. 복구 시에는 백업 당시와 현재의 변경을 비교하고, 해당 플러그인만 비활성화/제거하세요. 설정 파일 전체를 무조건 덮어쓰지 마세요.
