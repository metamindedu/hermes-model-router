# 다른 PC에서 설치하기

이 저장소는 Hermes 본체의 포크가 아니라, 독립적인 **Model Router 플러그인**입니다. NousResearch의 공식 Hermes를 설치한 다음 이 패키지를 추가합니다. 기존 PC의 인증 정보, 프로필 설정, 대화 DB, 작업 기록은 포함하지 않습니다.

## 1. 준비

- Hermes의 네이티브 플러그인 설치와 Desktop의 통합 패키지 탐색을 지원하는 버전을 사용합니다.
- 새 PC에서 원하는 모델 제공자를 Hermes의 정상 설정/로그인 절차로 인증합니다. 이 플러그인은 제공자 인증을 대신하거나 이전 PC의 인증 정보를 복사하지 않습니다.
- 이 저장소는 비공개이므로 GitHub 계정 `metamindedu` 또는 저장소 접근 권한이 있는 계정으로 로그인합니다. GitHub CLI가 설치되어 있다면 터미널에서 다음을 실행하고 브라우저/기기 인증 절차를 따릅니다.

```text
gh auth login
gh auth status
```

토큰을 저장소 URL, 명령 예시, 문서에 붙이지 않습니다. Hermes의 비공개 GitHub 설치 경로는 GitHub CLI의 저장된 로그인이나 기존 Git 인증을 사용할 수 있습니다.

## 2. 사용할 프로필에 설치

기본 프로필에 설치하는 명령은 다음과 같습니다.

```text
hermes --profile default plugins install metamindedu/hermes-model-router
```

설치 도중 출처 신뢰 확인, 플러그인 활성화, Python 의존성 준비를 묻는 경우 내용을 확인한 뒤 동의합니다. Python 의존성은 `PyYAML`이며 Hermes의 의존성 관리 경로를 사용합니다. `--enable`을 붙여도 의존성 동의 절차까지 생략하는 것은 아닙니다. 동의를 거부하거나 비대화형으로 실행하면 설치만 되고 비활성 상태로 남을 수 있습니다.

프로필별로 Python 플러그인이 설치됩니다. 예를 들어 **이미 존재하는** `coding` 프로필에서도 사용하려면 별도로 설치합니다.

```text
hermes --profile coding plugins install metamindedu/hermes-model-router
```

설치와 **코딩 라우팅 사용 여부**는 별개입니다. 이 안내는 존재하지 않는 프로필을 만들거나 다른 프로필에 자동 설치하지 않습니다. 반복 설치에 `--force`를 습관적으로 붙이지 마세요.

### 특정 검증 버전에 고정하기

최신 `main` 대신 확인한 **40자리 전체 커밋 SHA**를 사용하면 같은 버전을 설치할 수 있습니다.

```text
hermes --profile default plugins install metamindedu/hermes-model-router --ref <40자리-전체-커밋-SHA>
```

꺾쇠 부분은 실제 SHA로 바꿉니다. 고정 설치의 버전 변경은 새 SHA를 명시해야 하며, 일반 `plugins update`가 임의로 고정을 이동시키지 않습니다.

## 3. Desktop 활성화와 최초 설정

1. Hermes Desktop의 **Capabilities → Plugins**에서 새 패키지를 탐색합니다. 필요하면 **Rescan**을 사용합니다.
2. **Model Router / 모델 및 라우팅**의 Desktop UI를 활성화합니다. Python 플러그인의 활성화와 Desktop UI 활성화는 서로 다른 스위치입니다. `desktop/plugin.js`를 수동으로 다른 폴더에 복사할 필요는 없습니다.
3. 사이드바의 **모델 및 라우팅** 페이지를 엽니다. 설치 직후 코딩 라우팅은 기본적으로 OFF입니다.
4. 새 PC의 실제 제공자·모델 설정을 확인합니다. Heavy와 Light는 서로 다른 경로여야 합니다. 기존 프리셋은 편집용 템플릿이지 최신 모델 제공 여부를 보장하는 목록이 아닙니다.
5. 코딩 라우팅을 사용할 **플러그인이 설치된 프로필**을 선택합니다. 모델을 바꾸지 않고 라우팅만 켜려면 **모델 설정 적용 대상 → 전체 해제**를 사용합니다. 미리보기의 변경 대상/값을 확인하고 적용합니다.
6. 추가 비용이 발생할 수 있는 폴백은 기본 동작으로 가정하지 말고 별도로 확인합니다.
7. 적용 후 해당 프로필의 **새 세션**을 시작합니다. 진행 중 대화의 모델/도구가 즉시 바뀐다고 가정하지 않습니다.

프로필의 모델·폴백 설정과 작업 자료는 그 PC의 Hermes 홈에 보관됩니다. 저장소에 개인 `config.yaml`, `.env`, `auth.json`, `state.db`를 넣지 마세요.

## 4. 설치 확인

```text
hermes --profile default plugins list
hermes --profile default plugins doctor model-router --ci
hermes --profile default model-router status
```

이름 있는 프로필에서는 `default` 대신 해당 이름을 넣습니다. 설치 식별자는 저장소 이름 `hermes-model-router`가 아니라 manifest의 **`model-router`**입니다.

라우팅 OFF 상태에서 Doctor가 `coding_route`가 등록되지 않았다는 경고를 내는 것은 게이트의 정상 동작일 수 있습니다. Doctor의 종료 코드와 실제 오류를 함께 확인합니다. 라우팅을 켠 뒤 새 세션에서 `coding_route`와 동봉 스킬이 표시되는지, 실제 작업 중 `Background`가 표시되고 자식 세션이 일반 목록에서 제외되는지 확인합니다. 모델·제공자 검증과 작업 내용의 성공은 서로 별개입니다.

## 5. 업데이트와 제거

고정하지 않은 설치는 다음 명령으로 업데이트합니다.

```text
hermes --profile default plugins update model-router
```

고정된 설치는 새 후보의 전체 SHA를 확인하고, 진행 중인 라우팅 작업이 없는 시점에 명시적으로 버전을 바꿉니다.

```text
hermes --profile default plugins install metamindedu/hermes-model-router --force --ref <새-40자리-전체-커밋-SHA>
```

각 설치 프로필을 따로 업데이트합니다. 개인 설정은 소스 패키지와 별도지만, 업데이트 전 기존 설정과 플러그인 설치를 백업해 두세요. 작업 결과가 불명확한 경우 모델 작업을 자동으로 다시 실행하지 않습니다.

제거하려면 라우팅을 먼저 끄고 진행 중 작업을 확인한 뒤 해당 프로필에서 플러그인을 비활성화/제거합니다. 이 저장소의 `scripts/install_local.py`는 최초 PC의 운영 전환용 도구이므로 다른 PC의 일반 설치에는 사용하지 않습니다. 기존 설정 전체를 복사하거나 덮어쓰지 마세요.

## 공식 참고

- 플러그인 설치·비공개 저장소 인증·커밋 고정: https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins/
- 통합 Desktop/Python 패키지와 두 활성화 스위치: https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk/#one-package-both-sdks
