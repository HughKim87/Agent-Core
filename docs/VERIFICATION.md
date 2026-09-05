# 검증 수준과 완료 판정

- 목적: Core 자체 검증과 소비 통합 검증의 수준·게이트·보고 한계를 소유한다.
- 읽는 시점: 변경 전 검증을 설계하거나 완료를 판정·보고할 때.
- 책임: 에이전트가 실제 도달 수준을 기록하고 사용자가 최종 확인을 소유한다.
- 상태: 활성 정본. contract v2.
- 관련 권위: [Core 상시 정책](../PROJECT_RULES.md) §9, [호환성](COMPATIBILITY.md).

---

## 1. 검증 수준

| 수준 | 의미 |
|---|---|
| `generated` | 결과물을 만들었음 |
| `parsed` | 형식을 기계가 읽을 수 있음 |
| `structure-validated` | 선언·링크·schema·AST·경계 검사 통과 |
| `unit-tested` | 격리된 정상·결함 주입 검사 통과 |
| `integrated` | Core와 소비 구성요소를 연결한 gate 통과 |
| `self-operated` | 실제 작업에서 처음부터 끝까지 사용 |
| `cross-agent` | 다른 에이전트가 대화 없이 같은 상태를 복원 |
| `user-confirmed` | 사용자가 원하는 결과임을 확인 |

상위 이름이 하위 검사를 자동으로 포함하지 않는다. 실제 실행한 증거를 각각 기록한다.

기계 검사는 명시한 형식과 검사 사례의 결과를 증명한다. 자연어 의미는 원문·적용 조건·반례에 대한 검토로, 실제 동작은 대상 구현을 실행한 근거로 구분한다. 검사 안에서 재구현한 합성 행동 모델의 통과를 대상 Agent·Runtime의 동작 증거로 쓰지 않는다.

## 2. 판정값

| 값 | 의미 | 필수 게이트 처리 |
|---|---|---|
| `pass` | 실행했고 통과 | 성공 후보 |
| `fail` | 실행했고 실패 | 전체 실패 |
| `not_run` | 선택된 검사를 실행하지 않음 | 필수 게이트면 전체 실패. 선택되지 않은 검사는 게이트로 기록하지 않음 |
| `not_applicable` | 이유가 있는 비해당 | 비실패 |

## 3. Core 자체 gate

Core 자체 gate가 선택된 작업에서는 소비 저장소 없이 다음을 검증한다.

- 런타임·layout preflight
- Core 역할·호환성 선언
- 문서·링크·JSON·Python AST·텍스트
- 규칙 route와 모듈 계층
- 회귀·결함 주입 테스트
- 실행 전후 Core tree 무부작용

Core 자체 gate 통과만으로 Host 사용 가능성이나 read-only push 거부를 주장하지 않는다.

## 4. 소비 통합 gate

소비 계약이나 연결 표면이 변경되어 소비 통합 gate를 선택한 작업에서는 `--consumer-root`를 지정한다. 이를 생략한 `verify`·`gate`는 Core 자체 검사일 뿐 Host 보호나 소비 완료의 근거가 아니다. `maintainer`는 Core 자체 gate와 아래 소비 검사를 함께 실행한다. `host` 소비 gate는 검증된 Core library의 구조·공개 계약을 읽기 전용으로 검사하되 Maintainer가 소유하는 Core 내부 회귀를 소비 완료의 필수 검사로 다시 실행하지 않는다. 별도의 격리된 read-only 진단은 허용되지만 Maintainer 근거를 대신하지 않는다.

Host의 순수 `verify`는 dirty Core나 어긋난 부모 gitlink를 읽기만 해 원인을 finding으로 보고할 수 있다. 이 경로는 선택 기능 Runtime을 실행하지 않고 유효성 판정 전의 부모 gitlink 원시 상태와 Core tree·revision·index가 진단 전후 동일함을 증명하며, 발견이 있으면 소비 성공이 아니라 진단 실패 상태를 반환한다. 역할·Consumer 입력·Runtime storage에 무관한 정적 metadata discovery도 같은 전후 불변을 증명하고 쓰기 가능 경로를 열지 않을 때만 clean 사전 조건의 near-miss이며 기능 소비·완료 근거가 아니다. `context`, `gate`와 실제 기능 실행은 clean 기준과 부모 HEAD·index gitlink 및 실행 Core HEAD 일치를 하나의 결속 기준선으로 먼저 통과해야 한다.

Host gate가 선택 기능의 `info`와 호환성 선언 일치를 읽더라도 해당 `optional-features` 단계는 `not_applicable`이며 기능 소비·가용성·완료의 `pass`로 승격하지 않는다. 요구 기능의 설치 구조와 버전은 Consumer 계약 검사가 별도로 판정하고, 실제 기능 사용은 verified Consumer 경계의 `invoke`로 검증한다.

- 소비 계약 버전·역할·상대경로
- 진입 포인터의 대상과 순서
- 소비 상태 구조와 크기 예산
- 소비 규칙 route
- `.gitmodules`의 Core path
- Host의 부모 HEAD·index gitlink object와 실행 Core HEAD 일치, 계약 해석 전 관찰 기준선 및 실행 전후 결속 기준선 불변. 관찰 도중 역할이 바뀌거나 관찰 완료에 실패하면 후속 역할로 차단을 우회하지 않음
- Core·consumer scope가 있는 context와 fingerprint
- Host 소비 실행 전 HEAD·index·tracked raw worktree bytes/type/mode와 untracked·ignored·추가 directory 청결. `git status`의 content 정규화 결과에 의존하지 않으며, nested gitlink에도 같은 기준을 재귀 적용하고 `filter`·`working-tree-encoding`·`ident` content 변환 attribute는 hashing 전에 거부
- 보호 경로를 제외한 소비 계약 표면의 무부작용
- 실제 Git metadata directory만 제외하고 submodule `.git` pointer·빈 directory·entry type·mode·symlink target·cache·ignored 파일과 지속 mtime을 포함한 실행 전후 Core tree 및 HEAD·index·local Git config 무부작용

실제 Host checkout의 파일시스템 강제 read-only, 원격 자격 증명의 fetch·push 권한, Codex·Claude 행동은 별도 통합·실제 사용 검증이 소유한다.

## 5. 위험별 최소 수준

| 작업 | 최소 증거 |
|---|---|
| `quick` | `parsed` |
| `standard` | `structure-validated` |
| 의미가 유지되는 문구·설명 변경 | 대상 형식·링크 확인 + 요청 scope와 diff 대조 |
| 활성 Core 규칙 의미 변경 | 대상 구조·링크 + 변경 조건·반례 대조 + 상위 라우터가 선택한 규칙 거버넌스의 일반화·독립 감사 |
| 활성 route·trigger 변경 | route 구조 + 관련 의도 fixture. 의미 재현 주장은 독립 Agent 절차 추가 |
| 실행 정책·검사 판정 변경 | 직접 영향받는 정상·오류·경계 검사 |
| 검증 도구 변경 | `unit-tested` + 정상·오류·수행 불가 경계 |
| Core release 후보 | Core gate + commit snapshot clean clone |
| 소비 연결 후보 | 소비 gate + 부모·submodule Git 상태 대조 |
| 범용 Host 사용 주장 | 서로 다른 실제 Host 2개 + `cross-agent` |

### 검증 선택 방법

1. 사용자가 요청한 결과와 완료 주장을 한 문장으로 정한다.
2. 실제 변경 경로와 영향을 받는 동작·계약만 식별한다.
3. 위 표에서 그 결과를 증명하는 가장 작은 증거를 선택한다.
4. 실행 중 새 위험 신호가 확인되면 관련 검사를 추가한다.
5. 추가 검사가 요청 범위·시간·산출물을 실질적으로 넓히면 실행 전에 이유와 범위를 보고한다.

검증 수준은 품질을 재현하기 위한 선택 방법이며 가능한 모든 검사를 누적하는 목록이 아니다. 전체 gate나 clean clone을 더 많이 실행했다는 사실만으로 단순 작업의 품질이 높아지지 않는다.

## 6. 확대 보고 금지

- 합성 fixture는 `synthetic`으로 표시한다.
- 현재 checkout 통과를 commit snapshot 통과로 표현하지 않는다.
- 첫 Host 통과를 범용 Host 검증으로 표현하지 않는다.
- 정책상 금지를 실제 원격 권한 거부로 표현하지 않는다.
- 실행하지 않은 환경·Python·Agent 검사를 지원 범위로 선언하지 않는다.

## 7. 완료 보고

완료 보고는 다음을 포함한다.

1. 변경한 정확한 scope와 경로
2. 실행한 검사와 결과
3. 완료 주장에 필요하지만 실행하지 못한 검사와 이유
4. 현재 checkout·commit snapshot·실제 사용 중 어느 수준인지
5. 알려진 한계와 현재 계약에 남은 필수 검증. 남은 조건이 없으면 해당 범위의 종료를 명시

선택된 필수 검사 중 `fail` 또는 `not_run`이 있으면 그 검사가 증명하는 다음 단계로 전환하지 않는다.
