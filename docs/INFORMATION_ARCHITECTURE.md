# Core와 소비 저장소의 정보 소유 구조

- 목적: Core와 소비 저장소의 정보 유형, 단일 정본 위치, 갱신 책임을 소유한다.
- 읽는 시점: 파일을 만들거나 옮길 때, 선언·문서 역할·중복 정본을 판단할 때.
- 책임: 사용자가 소유 구조 변경을 승인하고 Core·소비 저장소 Maintainer가 각 정본을 유지한다.
- 상태: 활성 정본. `core-document-roles:v2`.
- 관련 권위: [Core 헌장](CHARTER.md), [계층과 소비 경계](ARCHITECTURE.md).

---

## 1. 원칙

- 모든 활성 사실은 scope 안에서 정본이 정확히 하나다.
- Core는 공통 사실만, 소비 저장소는 프로젝트별 사실만 소유한다.
- 현재 상태와 완료 이력은 분리한다. 상태는 소비 저장소 문서가, 완료 이력은 각 저장소 Git이 소유한다.
- Core commit SHA는 부모 저장소의 submodule gitlink만 소유한다.
- 서로 다른 프로젝트 자료를 병합할 때는 정본 흡수와 의존 해제가 검증될 때까지 원본 저장소·revision·상대경로를 복원할 수 있어야 한다.
- 실제 정보가 없으면 빈 미래 디렉터리를 만들지 않는다.

## 2. Core 역할 선언

<!-- core-document-roles:v2 -->
```json
{
  "core_policy": "PROJECT_RULES.md",
  "consumer_policy": "PROJECT_RULES.md"
}
```

`core_policy`는 Core root 기준, `consumer_policy`는 실행 시 전달된 consumer root 기준 상대경로다. 같은 파일명이어도 scope가 다르므로 서로 다른 정본이다.

## 3. Core 소유 정보

| 정보 | 정본 |
|---|---|
| 공통 최소 정책·Core route | `PROJECT_RULES.md` |
| 공통 조건부 규칙 | `rules/` |
| 목적·보장 | `docs/CHARTER.md` |
| 계층·scope 경계 | `docs/ARCHITECTURE.md` |
| 정보 소유와 선언 | 이 문서 |
| 공개 버전·호환성 | `docs/COMPATIBILITY.md` |
| 소비 절차 | `docs/CONSUMER_GUIDE.md` |
| 검증 구현 | `src/core_check/` |
| 선택 데이터 계약·구현 | `experimental/` |
| 회귀·결함 주입 | `tests/` |
| Core 완료 이력 | Core Git commit |

Core 저장소에는 자동 진입 파일, 현재 상태, 특정 Maintainer·Host 정책을 두지 않는다.

## 4. 소비 저장소 소유 정보

| 정보 | 정본 |
|---|---|
| Codex·Claude 진입 | 소비 root의 `AGENTS.md`, `CLAUDE.md` |
| 프로젝트 정책·도메인 route·소비 계약 | 소비 root의 `PROJECT_RULES.md` |
| 현재 상태 | 소비 계약의 `state` 경로 |
| 도메인 규칙 | 소비 계약의 `rule_roots` |
| 보호 경로 | 소비 계약의 `protected_paths` |
| Core 상대경로 | 소비 계약의 `core_path` |
| Core 원격·submodule path | `.gitmodules` |
| 고정 Core revision | submodule gitlink |
| 가져오거나 병합한 자료의 source lineage | 원래 Git 또는 해당 Consumer의 migration·source owner |
| 프로젝트 완료 이력 | 소비 저장소 Git commit |

소비 정책의 `agent-core-consumer:v1` 블록이 프로젝트별 경로 선언의 기계 정본이다.

## 5. Core 디렉터리 구조

```text
/
├─ PROJECT_RULES.md
├─ README.md
├─ docs/
├─ experimental/
├─ rules/
├─ src/
└─ tests/
```

저장소 루트가 Core 전체다. 배포 전용 하위 폴더나 모양이 다른 배포 브랜치를 만들지 않는다.

## 6. 복제 금지

| 사실 | 정본 | 다른 위치의 처리 |
|---|---|---|
| Core 목적 | `docs/CHARTER.md` | 링크만 함 |
| 공개 version | `docs/COMPATIBILITY.md` 선언 | 값을 복제하지 않음 |
| 사용 절차 | `docs/CONSUMER_GUIDE.md` | README는 링크만 함 |
| 소비 현재 상태 | 소비 계약의 state | Core에 복제하지 않음 |
| Core revision | submodule gitlink | 문서·JSON에 SHA를 복제하지 않음 |
| 동적 Git 상태·파일 수 | 실행 조회 | 문서에 고정하지 않음 |

## 7. 문서 수명주기

| 상태 | 의미 |
|---|---|
| 활성 정본 | 현재 판단과 행동을 직접 규율하는 단일 소유자 |
| 활성 개요 | 정본을 링크하는 파생 표현 |
| 완료 설계 | 실행이 끝난 역사적 기준. 현재 상태를 소유하지 않음 |
| 한시 자료 | 검증된 내용을 정본에 흡수한 뒤 종료할 비정본 |

새 문서는 기존 정본이 지속적 책임을 수용할 수 없을 때만 만든다. 모든 유지 문서는 목적·읽는 시점·책임·상태·관련 권위를 갖는다.

## 8. 검사 경계

- Core 역할 선언은 Core tree에서 정확히 하나여야 한다.
- 소비 계약은 선언된 소비 정책 파일 한 곳에서만 읽는다.
- 소비 검사기는 Core subtree와 `protected_paths`를 부모 문서 순회에서 제외한다.
- Core와 소비 경로는 각각의 root 밖으로 나갈 수 없다.
- 같은 상대경로는 `core`·`consumer` scope로 구분한다.
