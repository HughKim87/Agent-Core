# 버전과 호환성

- 목적: 지원 런타임, 공개 계약 버전, 호환·비호환 변경과 이전 절차를 단일 선언으로 소유한다.
- 읽는 시점: Core를 연결·갱신하거나 공개 인터페이스를 바꿀 때.
- 책임: Core Maintainer가 선언과 구현을 일치시키고 사용자가 비호환 변경을 승인한다.
- 상태: 활성 정본. Core 0.3.0 / contract 2.
- 관련 권위: [Core 상시 정책](../PROJECT_RULES.md), [공개 경계](ARCHITECTURE.md).

---

## 1. 기계 판독 선언

<!-- core-compatibility:v1 -->
```json
{
  "core_version": "0.3.0",
  "contract_version": 2,
  "python_min": "3.10",
  "required_dependencies": [],
  "optional_dependencies": ["git"],
  "optional_capabilities": {
    "shared_data": {
      "version": 1,
      "entry_module": "experimental.shared_data",
      "commands": ["info", "invoke"],
      "request_schema": "experimental/shared_data/schemas/shared-data-request-v1.schema.json",
      "result_schema": "experimental/shared_data/schemas/shared-data-result-v1.schema.json",
      "schemas": [
        "experimental/shared_data/schemas/common-record-v1.schema.json",
        "experimental/shared_data/schemas/source-payload-v1.schema.json",
        "experimental/shared_data/schemas/knowledge-payload-v1.schema.json",
        "experimental/shared_data/schemas/decision-payload-v1.schema.json",
        "experimental/shared_data/schemas/lifecycle-event-payload-v1.schema.json",
        "experimental/shared_data/schemas/lifecycle-state-payload-v1.schema.json",
        "experimental/shared_data/schemas/context-package-v1.schema.json",
        "experimental/shared_data/schemas/work-request-payload-v1.schema.json",
        "experimental/shared_data/schemas/work-event-payload-v1.schema.json",
        "experimental/shared_data/schemas/work-state-payload-v1.schema.json"
      ]
    }
  }
}
```
<!-- /core-compatibility -->

이 블록이 버전의 유일한 정본이다.

## 2. 의미

| 필드 | 의미 | 변경 시점 |
|---|---|---|
| `core_version` | 배포되는 Core 저장소 단위 | 검증된 Core release마다 |
| `contract_version` | CLI·선언·규칙 계약의 세대 | 소비자 이전이 필요한 비호환 변경 |
| `python_min` | 필수 검증의 최소 Python | 하위 런타임 지원을 종료할 때 |
| `required_dependencies` | Core 자체 필수 경로가 호출하는 외부 실행 도구 이름 | 필수 도구를 추가·제거할 때 |
| `optional_dependencies` | 역할별 소비 경계에서 조건부로 요구할 수 있는 외부 실행 도구 이름 | 조건부 도구를 추가·제거할 때 |
| `optional_capabilities` | 실제 제공되는 선택 기능의 ID·버전·명령·schema | 선택 기능을 공개하거나 호환 경계를 바꿀 때 |

## 3. contract 2 공개 계약

- Core 내부 자동 진입 파일과 현재 상태를 제공하지 않는다.
- 소비 저장소가 `agent-core-consumer:v1` 선언과 진입·정책·상태를 제공한다.
- 소비 계약의 선택 필드 `required_core_capabilities`는 기능 ID별 최소 양의 정수 버전을 선언한다. key가 없거나 빈 객체인 기존 Host는 선택 기능 요구가 없고 정적 discovery 외의 선택 기능을 호출할 권한도 없다.
- CLI는 `--core-root`와 `--consumer-root`를 구분한다.
- `context` 문서 경로는 `scope`와 `path` 객체로 반환한다.
- `verify`, `context`, `gate` 명령과 종료 상태 0·1·2를 제공한다.
- v2 동안 `--root`는 `--core-root`의 deprecated alias다.

## 3A. 선택 기능 공개 경계

- `optional_capabilities`에 없는 기능은 흡수가 승인됐더라도 아직 공개 기능이 아니다.
- 선택 기능은 기본 비활성이며 명시적 호출만 허용한다.
- 각 항목은 기능 ID, 계약 버전, 공개 명령과 schema 경로를 함께 선언해야 한다.
- 내부 Python module 경로와 참고 구현의 이름은 공개 계약이 아니다.
- 실제 Runtime 데이터와 결과는 소비 저장소가 소유하며 Core 저장소에 쓰지 않는다.
- 선택 기능이 없으면 필수 gate는 `not_applicable`로 처리하고 계속 성립해야 한다.

`shared_data` v1은 격리 모드(`python -B -I`)에서 실행 중인 Core root와 `src`만 module 검색 경로 맨 앞에 넣고 선언된 `experimental.shared_data` entry의 `info|invoke`를 실행하는 bootstrap만 공개한다. `invoke`는 JSON request v1을 stdin으로 하나 받아 JSON result v1을 stdout으로 하나 반환한다. 세부 operation과 데이터 구조는 선언된 schema가 소유한다. bare module 실행과 `experimental.shared_data` 아래 구현 모듈의 직접 import는 공개 계약이 아니다.

`info`는 역할·Consumer 입력·Runtime storage와 무관하고 쓰기 가능 경로를 열지 않는 정적 discovery다. Core tree·Git 의미 상태의 전후 불변을 정상·예외 경로 모두에서 증명하며 dirty Core에서도 실행할 수 있지만 기능 소비·가용성·완료 성공 근거가 아니다. Git 기준선을 증명할 수 없으면 fail-closed한다.

`shared_data invoke`는 verified Consumer 계약, Core와 정확히 같은 `contract_version`, Consumer의 `required_core_capabilities.shared_data` 최소 버전 선언을 요구한다. Runtime storage가 계약의 `core_path`와 겹치거나 Consumer 밖이면 dispatch 전에 실패한다. 통과한 storage는 Consumer 상대 canonical 경로로 dispatch되고 `core_path`는 내부 보호 경로에 합산되어 각 storage 해석 때 다시 검사된다. Host 역할에서는 계약 해석 전 소비 정책·부모 gitlink·Core 관찰, 부모 HEAD·index gitlink와 Core HEAD 일치, 기능 실행 전 clean, 실행 후 결속 불변을 함께 요구한다. 순수 `verify`는 불일치 gitlink를 실행 허가로 쓰지 않고 finding으로 진단한다. 다만 Core 내부 entry import 전에 일어나는 revision 교체는 Consumer 소유 외부 launcher 또는 immutable checkout이 별도로 닫아야 한다.

## 4. 호환·비호환

| 호환 변경 | 비호환 변경 |
|---|---|
| 규칙 문구 보강, 검사 추가, 오류 설명 개선, 결과 필드 추가 | 명령 제거·개명, 종료 상태 의미 변경, 필드 제거, 선언 schema 변경, route trigger 축소 |

비호환 변경은 `contract_version` 상승과 이전 절차 없이는 수용하지 않는다.

## 5. v1에서 v2 이전

1. 부모 소비 저장소에 Core 전체를 submodule로 연결한다.
2. 부모 루트가 `AGENTS.md`, `CLAUDE.md`, `PROJECT_RULES.md`, `SESSION_HANDOFF.md`를 소유하게 한다.
3. 부모 정책에 소비 계약 선언, 도메인 route, 보호 경로를 둔다.
4. Core 내부 진입·상태 문서에 대한 의존을 제거한다.
5. 기존 `--root` 호출을 Core 자체는 `--core-root`, 소비 통합은 `--consumer-root`로 바꾼다.
6. 소비 통합 gate를 통과한 뒤 부모의 submodule gitlink를 갱신한다.

## 6. 의존성과 텍스트

- Core 자체 필수 경로의 Python package 의존성은 표준 라이브러리뿐이고 필수 외부 실행 도구는 없다.
- `git` CLI는 선택 의존성이다. 선택 기능이 설치되지 않은 Core 자체 검증에는 필요하지 않지만, 설치된 선택 기능이 Git-backed 정적 discovery를 공개하면 그 기능의 `optional-features` 검사에 필요하다. 또한 소비 계약의 submodule revision과 `host`의 Core clean 상태를 증명하는 역할별 소비 gate에서는 필수다. 필요한 경로에서 `git`이 없으면 기준을 증명할 수 없으므로 fail-closed한다.
- Host clean 증명은 검사 중 content 변환을 실행하지 않는다. tracked 경로에 `filter`, `working-tree-encoding` 또는 `ident` attribute가 필요하면 해당 checkout은 Host gate에서 지원하지 않고 fail-closed한다.
- Host clean 증명의 tracked 일반 파일 내용은 Git 줄바꿈 정규화 전의 실제 worktree bytes로 HEAD blob과 대조한다. 따라서 `git status`가 clean이어도 checkout bytes가 다르면 실패한다.
- 선택 기능이 없어도 필수 검증이 통과해야 한다.
- 추적 텍스트 표준은 UTF-8과 LF다.
- LF와 CRLF는 정상 줄 종료로 해석하고 실제 후행 공백·탭만 위반으로 판정한다.

## 7. 복구

- Core revision은 submodule gitlink가 소유한다.
- 검증 실패 시 부모 gitlink를 마지막 검증 commit으로 되돌린다.
- 저장소 안에 백업 사본이나 SHA 복제 문서를 만들지 않는다.
- `--root` alias 제거는 다음 계약 세대의 별도 비호환 변경이다.
