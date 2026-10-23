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

## 3A. 선택 Runtime 공개 경계

- `optional_capabilities`에 없는 기능은 흡수가 승인됐더라도 아직 공개 기능이 아니다.
- 선택 기능은 기본 비활성이며 명시적 호출만 허용한다.
- 각 항목은 기능 ID, 계약 버전, 공개 명령과 schema 경로를 함께 선언해야 한다.
- 내부 Python module 경로와 참고 구현의 이름은 공개 계약이 아니다.
- 실제 Runtime 데이터와 결과는 소비 저장소가 소유하며 Core 저장소에 쓰지 않는다.
- 선택 기능이 없으면 필수 gate는 `not_applicable`로 처리하고 계속 성립해야 한다.

`shared_data` v1은 격리 모드(`python -B -I`)에서 실행 중인 Core root와 `src`만 module 검색 경로 맨 앞에 넣고 선언된 `experimental.shared_data` entry의 `info|invoke`를 실행하는 bootstrap만 공개한다. `invoke`는 JSON request v1을 stdin으로 하나 받아 JSON result v1을 stdout으로 하나 반환한다. 요청·결과 schema는 envelope와 operation 열거를, payload schema는 저장 구조를 소유한다. operation별 arguments·기본값·성공 결과·쓰기와 승인 전제는 [저장 공통 명세](../experimental/shared_data/RECORD_STORAGE_CONTRACT.md#8-공개-호출-공통-명세), [지식·Lifecycle 명세](../experimental/shared_data/KNOWLEDGE_LIFECYCLE_CONTRACT.md#7-공개-operation-명세), [Evidence Context 명세](../experimental/shared_data/EVIDENCE_CONTEXT_CONTRACT.md#5-공개-operation-명세), [작업 상태 명세](../experimental/shared_data/WORK_STATE_CONTRACT.md#6-공개-operation-명세)가 소유한다. bare module 실행과 `experimental.shared_data` 아래 구현 모듈의 직접 import는 공개 계약이 아니다.

`info`는 역할·Consumer 입력·Runtime storage와 무관하고 쓰기 가능 경로를 열지 않는 정적 discovery다. Core tree·Git 의미 상태의 전후 불변을 정상·예외 경로 모두에서 증명하며 dirty Core에서도 실행할 수 있지만 기능 소비·가용성·완료 성공 근거가 아니다. Git 기준선을 증명할 수 없으면 fail-closed한다.

`shared_data invoke`는 verified Consumer 계약, Core와 정확히 같은 `contract_version`, Consumer의 `required_core_capabilities.shared_data` 최소 버전 선언을 요구한다. Runtime storage가 계약의 `core_path`와 겹치거나 Consumer 밖이면 dispatch 전에 실패한다. 통과한 storage는 Consumer 상대 canonical 경로로 dispatch되고 `core_path`는 내부 보호 경로에 합산되어 각 storage 해석 때 다시 검사된다. Host는 clean Core, 부모 HEAD·index gitlink와 실행 Core HEAD 일치, 계약 해석 전 관찰과 실행 후 결속 불변을 요구한다. 원시 bytes·Git 검사 세부사항과 순수 `verify` 진단의 예외는 [검증 계약 §4](VERIFICATION.md#4-소비-통합-gate)가 소유하며 진단을 실행 허가·소비 완료로 해석하지 않는다. 다만 Core 내부 entry import 전에 일어나는 revision 교체는 Consumer 소유 외부 launcher 또는 immutable checkout이 별도로 닫아야 한다.

## 3B. 공통 workflow 진입 계약

Core workflow entry v1은 아래 공통 진입과 도구별 discovery 템플릿의 계약이다. 기존 보존 스킬의 원본과 참고 자료는 각 `source/` 트리에 그대로 보존한다. 새로 작성한 스킬은 `current/`에 실행 본문을 둘 수 있으며 존재하지 않는 보존 원본을 만들지 않는다. `WORKFLOW.md`는 실행 본문 하나를 연결한다. 선택된 본문 기준의 상대 참고자료를 읽고, 승인 개정이 선택되면 source는 비활성 보존 자료로 유지하며 동시에 적용하지 않는다. 원본을 공통 규칙으로 승격하거나 일반 Core 절차에 맞춰 수정하지 않는다. 배포 자산은 필수 제공하고 실행·Consumer 설치는 선택이다. 신규 setup의 도구 선택 기본값은 그 스킬이 소유하며 Core 공통 기본값이 아니다. 기존 갱신은 Consumer가 위임한 등록 범위·도구 선택·명시적 제외를 따른다. 자동 선택 표시는 스킬 발견/선택 정책이며 기존 사용자 승인·실행기 권한을 바꾸지 않는다.

<!-- core-workflow-entries:v1 -->
| 스킬 | 공통 본문 | Codex 템플릿 | Claude Code 템플릿 | 자동 선택 |
|---|---|---|---|---|
| `handoff-manager` | `skills/handoff-manager/WORKFLOW.md` | `skills/handoff-manager/codex/SKILL.md.in` | `skills/handoff-manager/claude/SKILL.md.in` | 직접 호출 |
| `setup-agent-core-project` | `skills/setup-agent-core-project/WORKFLOW.md` | `skills/setup-agent-core-project/codex/SKILL.md.in` | `skills/setup-agent-core-project/claude/SKILL.md.in` | 직접 호출 |
| `session-close` | `skills/session-close/WORKFLOW.md` | `skills/session-close/codex/SKILL.md.in` | `skills/session-close/claude/SKILL.md.in` | 직접 호출 |
| `review-chat-session` | `skills/review-chat-session/WORKFLOW.md` | `skills/review-chat-session/codex/SKILL.md.in` | `skills/review-chat-session/claude/SKILL.md.in` | 허용 |
| `install-common-skills` | `skills/install-common-skills/WORKFLOW.md` | `skills/install-common-skills/codex/SKILL.md.in` | `skills/install-common-skills/claude/SKILL.md.in` | 허용 |
<!-- /core-workflow-entries -->

Codex 템플릿 옆의 `agents/openai.yaml`도 배포 자산이며 `allow_implicit_invocation`을 소유한다. Claude Code 템플릿은 `disable-model-invocation`을 소유한다. 양쪽은 같은 공통 본문을 읽으며 공통 절차를 native 진입에 복제하지 않는다. 이 계약은 기존 `optional_capabilities` JSON·Runtime API·schema와 분리한다. 설치 분류·개인용 패키지 명세는 아래 공개 설치 목록이 소유하며 Consumer schema에는 필드를 추가하지 않는다.

지원 템플릿은 단순 YAML frontmatter와 Markdown 포인터를 사용한다. scalar는 JSON 호환 double-quoted 문자열, 단순 이름, `true`/`false`만 사용하고 Codex 메타데이터는 `interface`와 `policy` 두 단계 mapping으로 제한한다. `SKILL.md.in`의 유일한 치환 항목은 `{{WORKFLOW_LINK}}`다. 실제 설치·치환·호환 검사 절차는 [소비 안내](CONSUMER_GUIDE.md#10-공통-스킬-진입-구성)가 소유한다.

이 진입 형식의 제한은 Core가 생성하는 어댑터에만 적용한다. 보존된 원본 frontmatter·본문·고유 절차에 이 subset이나 Core 문서 형식을 강제하지 않는다. `skills/SOURCES.json` format_version 1의 `files`는 `skills/<name>/source/<원본 상대경로>`별 SHA-256이다. 확인된 source 파일만 일반 문서 헤더 검사와 구분하고 원본 bytes·누락·경로 이상은 별도 무결성 검사로 보고한다. source 영역의 Git `-text` 속성으로 줄바꿈 bytes도 보존한다.

원본 보관은 원본의 도구·서비스·환경 값을 Core 전역 기본값으로 채택하는 일이 아니다. Core 내부 native 발견 경로나 별도 Runtime 의존도 만들지 않는다. 스킬 문제를 분석·보고할 수 있으나 단순한 Core 기본 절차와의 차이를 수정·차단 사유로 삼지 않는다. 어댑터 구조·원본 bytes 검사는 실제 두 도구의 parser·발견·읽기·행동을 증명하지 않는다. 원본이나 진입 경로·호출 의미를 바꾸려면 현재 사용자 범위와 §4의 호환성·이전을 대조한다.

### 설치 분류와 공통 설치 패키지

[설치 목록](../skills/INSTALLATION.json) format 1이 스킬별 설치 분류의 단일 정본이다. 위 표의 “공통 workflow”는 도구 간 본문 공유를 뜻하며 PC 공통 설치를 뜻하지 않는다. 공개 workflow 이름은 설치 목록에 정확히 하나씩 분류하며 미분류 항목을 설치 대상으로 추측하지 않는다.

| scope | 정의 | 설치 선택 |
|---|---|---|
| `common` | 프로젝트·Git·Core 연결 없이 작업 목적을 완성하는 개인용 스킬 | PC 사용자 범위에 필요한 본문·자료를 포함한 독립 패키지 설치. 프로젝트 native 등록 제외 |
| `project` | 프로젝트를 생성·운영·검증·인계하거나 Core 연결을 전제로 하는 스킬 | Consumer의 native 진입으로만 등록. 개인용 공통 설치 제외 |
| `internal` | 독립 호출 대상이 아닌 보조 자료 | native 진입과 공통 설치 모두 제외. 참조하는 패키지의 필요한 자료로만 포함 가능 |

원본 보관 위치, 설치 scope, 실행에 필요한 역할·환경은 서로 다른 정보다. 여러 프로젝트에서 재사용된다는 사실만으로 `common`이 되지 않는다. 프로젝트 생성은 기존 프로젝트 없이 시작할 수 있어도 목적이 프로젝트 구성이므로 `project`다. Core 연결·Maintainer 역할 등 실행 전제는 해당 스킬 본문이 소유한다. 내부 자료는 파일 확장자나 폴더 이름으로 개별 스킬로 승격하지 않는다.

설치 목록은 `format_version`, `provider`, `skills`를 갖는다. `skills`의 key는 공개 이름이며 각 항목의 `scope`는 위 세 값 중 하나다. `project`·`internal` 항목은 scope만 선언한다. `common` 항목은 안정 버전 `MAJOR.MINOR.PATCH`인 `version`, 설치 상대경로→Core 원본 상대경로의 `files`, `codex`·`claude`별 추가 파일인 `agent_files`를 선언한다. source는 같은 스킬 owner 안의 명시 파일만 허용하며 재귀 폴더 복사는 하지 않는다. 설치 `SKILL.md`와 상대 참고자료는 설치본 내부에서 완결돼야 한다. 새 common 패키지는 내용·호출 정책·파일 구성이 바뀔 때 스킬 버전을 올린다. 이 버전은 Core 저장소 release 버전과 별개이며 Core revision의 정본을 복제하지 않는다.

설치 영수증 `.agent-core-install.json` format 1은 사용자 설치 폴더 안에 `provider`, `name`, `agent`, 스킬 `version`, 설치 파일별 SHA-256인 `files`를 보존한다. 로컬 관리 식별이며 신뢰·권한의 증명은 아니다. 비교·교체·보존 절차는 [소비 안내 §11](CONSUMER_GUIDE.md#11-pc-공통-스킬-설치)가 소유한다. 분류 변경은 설치 위치의 자동 이동·삭제 승인이 아니며, 기존 설치·발견 출처와 고유 내용을 확인한 명시적 이전이 필요하다.

## 4. 호환·비호환

| 호환 변경 | 비호환 변경 |
|---|---|
| 규칙 문구 보강, 검사 추가, 오류 설명 개선, 결과 필드 추가 | 명령 제거·개명, 종료 상태 의미 변경, 필드 제거, 선언 schema 변경, route trigger 축소 |

비호환 변경은 `contract_version` 상승과 이전 절차 없이는 수용하지 않는다.

고정 재시도 수치·명령 창·일률 직렬 실행처럼 특정 Consumer의 운영 기본값은 Core 공통 보장의 정본이 아니다. 그 제한을 사용하던 Consumer는 자기 정책과 합성 검사에 같은 기본값을 명시해 유지한다. Core의 명시 예산 준수·무진전 중단·불명확한 외부 결과 확인·취소·승인 경계는 계속 적용된다. 이 소유권 정정은 route trigger나 CLI·schema 세대를 축소·변경하지 않는다.

## 5. v1에서 v2 이전

1. 부모 소비 저장소에 Core 전체를 submodule로 연결한다.
2. 부모 루트가 `AGENTS.md`, `CLAUDE.md`, `PROJECT_RULES.md`, `SESSION_HANDOFF.md`를 소유하게 한다.
3. 부모 정책에 소비 계약 선언, 도메인 route, 보호 경로를 둔다.
4. Core 내부 진입·상태 문서에 대한 의존을 제거한다.
5. 기존 `--root` 호출을 Core 자체는 `--core-root`, 소비 통합은 `--consumer-root`로 바꾼다.
6. [소비 안내](CONSUMER_GUIDE.md) §7에 따라 이전할 소비 파일과 Core gitlink를 격리된 후보 부모 snapshot에 고정하고 Host 소비 gate를 실행한다. 통과한 입력을 승인된 실제 소비 작업에서 반영한 뒤, 실제 부모 HEAD·index·Core가 일치하는 상태의 소비 gate로 완료를 확인한다.

## 6. 의존성과 텍스트

- Core 자체 필수 경로의 Python package 의존성은 표준 라이브러리뿐이고 필수 외부 실행 도구는 없다.
- `git` CLI는 선택 의존성이다. 선택 기능이 설치되지 않은 Core 자체 검증에는 필요하지 않지만, 설치된 선택 기능이 Git-backed 정적 discovery를 공개하면 그 기능의 `optional-features` 검사에 필요하다. 또한 소비 계약의 submodule revision과 `host`의 Core clean 상태를 증명하는 역할별 소비 gate에서는 필수다. 필요한 경로에서 `git`이 없으면 기준을 증명할 수 없으므로 fail-closed한다.
- Host clean 증명은 검사 중 content 변환을 실행하지 않는다. tracked 경로에 `filter`, `working-tree-encoding` 또는 `ident` attribute가 필요하면 해당 checkout은 Host gate에서 지원하지 않고 fail-closed한다.
- Host clean 증명의 tracked 일반 파일 내용은 Git 줄바꿈 정규화 전의 실제 worktree bytes로 HEAD blob과 대조한다. 따라서 `git status`가 clean이어도 checkout bytes가 다르면 실패한다.
- 선택 기능이 없어도 필수 검증이 통과해야 한다.
- Core 유지 문서와 생성한 진입 텍스트 표준은 UTF-8과 LF다. 보존된 스킬 원본은 §3B의 식별 bytes와 Git `-text` 속성을 따라 줄바꿈도 원본 그대로 유지한다.
- LF와 CRLF는 정상 줄 종료로 해석하고 실제 후행 공백·탭만 위반으로 판정한다.

## 7. 복구

- Core revision은 submodule gitlink가 소유한다.
- 복구는 [소비 안내](CONSUMER_GUIDE.md#9-실패와-복구)를 따른다. 후보 gate 실패에서는 실제 Consumer를 유지한다. 실제 반영 후 실패에서는 소비·게시를 중단하고 사용자 변경을 보존하며, 정확한 복구가 승인된 경우에만 마지막 검증된 부모 gitlink·소비 입력과 Core checkout을 함께 복원한다.
- 저장소 안에 백업 사본이나 SHA 복제 문서를 만들지 않는다.
- `--root` alias 제거는 다음 계약 세대의 별도 비호환 변경이다.
