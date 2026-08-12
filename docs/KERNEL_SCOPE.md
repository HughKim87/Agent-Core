# Kernel 범위 — 포함과 제외 분류

- 목적: 참고 구현의 모든 구성요소를 `필수 Kernel`, `검증된 선택 기능`, `실험 기능`, `제외 기능` 중 하나로 판정하고 그 근거를 소유한다.
- 읽는 시점: 어떤 구성요소를 1차 Core에 넣을지 판단할 때, 그리고 그 판정의 근거를 확인할 때.
- 책임: 사용자가 범위 변경을 승인하고 프로젝트 에이전트가 판정 근거를 유지한다.
- 상태: 활성 정본. Stage 2 성공 게이트 통과.
- 관련 권위: [Core 헌장](CHARTER.md) §7의 판정 기준 C1~C5.

---

## 1. 측정 기준일과 근거

- 측정일: 2026-08-13
- 대상: 참고 구현의 `core/**`, 루트 정책 문서, `scripts/`, 패키지 설정
- 방식: 읽기 전용 스캔. 참고 구현 변경 0건, 테스트 미실행

C3(실제 소비자 존재)의 판정에 사용한 측정 결과는 다음과 같다.

| 측정 항목 | 결과 |
|---|---|
| 실행 시 생성되는 데이터 디렉터리 | 존재하지 않음 |
| record·event 파일 | 0건 |
| `.jsonl` 파일 | 0건 |
| 기록 저장소의 프로덕션 쓰기 | 의도적으로 차단됨 |
| CLI 명령 수 | 34개 |
| CLI 명령 중 Core 외부 소비자가 확인된 것 | 0개 |
| Schema 11종의 Core 외부 소비자 | 0개 (자기 계약 문서·자기 테스트·검증기만 참조) |
| 검증 게이트가 실제로 import 하는 Core 모듈 | `maintenance`, `document_data` 2개 |

## 2. 판정 단위

**판정 단위는 파일이 아니라 기능이다.** 참고 구현에는 한 파일이 필수 기능과 실험 기능을 함께 담은 사례가 있다(§4). 파일 단위로 판정하면 실험 기능이 필수 기능에 업혀 Kernel에 들어온다.

## 3. 전수 분류

### 3.1 규칙

| 구성요소 | 판정 | 근거 |
|---|---|---|
| core-change-control | 필수 Kernel | G3. 단 게이트 명령이 호스트 디렉터리 이름을 문자로 포함해 C1 미충족 상태이며 일반화가 선행 조건이다 |
| rule-governance | 필수 Kernel | G1·G6. 규칙 발견 가능성과 라우팅 유일성의 소유자 |
| staged-work-design | 필수 Kernel | P4. 다단계 작업의 재개 가능성 |
| document-work | 필수 Kernel | P2·P3. 문서 증식 억제 |
| failure-records | 필수 Kernel | G5 |
| version-control | 필수 Kernel | G3. Git 쓰기 경계 |
| user-data-work | 필수 Kernel | G3. 보호 데이터. 단 보호 경로 이름의 일반화 필요 |
| boundary-routing-and-dependency | 필수 Kernel (축소 적용) | C1을 강제하는 유일한 장치. BND01~BND04는 Host가 없는 1차 Core에서 Core 내부 계층 경계로 축소 적용하고, 영역 간 적용은 Stage 28로 연기한다. BND05는 즉시 적용 |
| file-extraction | 검증된 선택 기능 | 실사용 근거는 있으나 Kernel 시작·검증 경로에 필요하지 않다 |
| file-cleanup | 검증된 선택 기능 | 동일 |
| cross-validation | 검증된 선택 기능 | P1과 관련되나 Kernel 필수 경로가 아니다 |

### 3.2 계약 문서

| 구성요소 | 판정 | 근거 |
|---|---|---|
| INFORMATION_ARCHITECTURE | 필수 Kernel | Stage 4의 직접 입력 |
| MAINTENANCE_AUTOMATION_CONTRACT | 필수 Kernel (부분) | 검증 게이트의 실제 소비자 존재. 단 지식 재평가 조항은 실험으로 분리 |
| CONTEXT_PACKAGE_CONTRACT | 검증된 선택 기능 | 소비자가 도메인 경유로만 존재. Stage 18이 판정 |
| FILE_DATA_CONTRACT | 실험 기능 | C3 미충족 |
| RECORD_IO_CONTRACT | 실험 기능 | C3 미충족 |
| WORK_STATE_CONTRACT | 실험 기능 | C3 미충족. Stage 24가 판정 |
| KNOWLEDGE_TYPES_CONTRACT | 실험 기능 | C3 미충족. Stage 25가 판정 |
| KNOWLEDGE_LIFECYCLE_CONTRACT | 실험 기능 | C3 미충족. Stage 25가 판정 |
| OBSIDIAN_REVIEW_CONTRACT | 제외 | 특정 외부 도구에 종속되며 P1~P4를 직접 개선하지 않는다. 보호 경로 비노출 원칙은 Stage 12가 흡수한다 |

### 3.3 Schema

| 구성요소 | 판정 | 근거 |
|---|---|---|
| context-package-v1 | 검증된 선택 기능 | 컨텍스트 기능과 등급을 공유 |
| common-record-v1 | 실험 기능 | 외부 소비자 0 |
| source-payload-v1 | 실험 기능 | 외부 소비자 0 |
| knowledge-payload-v1 | 실험 기능 | 외부 소비자 0 |
| decision-payload-v1 | 실험 기능 | 외부 소비자 0 |
| failure-knowledge-payload-v1 | 실험 기능 | 해결 실패의 정본은 Markdown이므로 payload 표현은 중복 정본 위험이 있다 |
| lifecycle-state-payload-v1 | 실험 기능 | 외부 소비자 0 |
| lifecycle-event-payload-v1 | 실험 기능 | 외부 소비자 0 |
| work-request-payload-v1 | 실험 기능 | 외부 소비자 0 |
| work-state-payload-v1 | 실험 기능 | 외부 소비자 0 |
| work-event-payload-v1 | 실험 기능 | 외부 소비자 0 |

### 3.4 구현

| 구성요소 | 판정 | 근거 |
|---|---|---|
| 문서·링크·Schema·AST 무결성 검사 | 필수 Kernel | 검증 게이트의 실제 소비자. Stage 15 |
| 파생 artifact 소유자 검증 | 필수 Kernel | 검증 게이트의 실제 소비자. Stage 16 |
| 경로 안전 판정 | 필수 Kernel | 보호 경로 강제의 최소 기반 |
| 단계 설계 fingerprint 검증 | 검증된 선택 기능 | Stage 9의 무효화 게이트를 직접 지원하나 현재 실험 Runtime에 결합되어 있다 |
| 컨텍스트 구성 | 검증된 선택 기능 | Stage 18이 판정 |
| 내보내기·호환성 manifest | 검증된 선택 기능 | Stage 26이 판정 |
| 기록 저장소 | 실험 기능 | 프로덕션 쓰기 차단, 데이터 0건 |
| 작업 상태 Runtime | 실험 기능 | Stage 24가 판정 |
| 지식·결정 Runtime | 실험 기능 | Stage 25가 판정 |
| 수명주기 Runtime | 실험 기능 | Stage 25가 판정 |
| source drift·중복 탐지 | 실험 기능 | 지식 Runtime에 종속 |
| CLI 34개 명령 | 제외 (대부분) | 외부 소비자 0. Stage 19가 실제 소비자 있는 최소 표면만 다시 정의한다 |

### 3.5 실패 지식

| 구성요소 | 판정 |
|---|---|
| 원인별 해결 실패 사례 6건 | 필수 Kernel (G5). 도메인 어휘가 포함된 2건은 이전 시 정제한다 |

### 3.6 회귀 테스트

테스트는 검증 대상 기능의 등급을 그대로 상속한다. 필수 Kernel 기능의 테스트는 필수이고, 실험 기능의 테스트는 실험 격리 영역으로 함께 이동한다.

### 3.7 제외

| 구성요소 | 근거 |
|---|---|
| 도메인 워크플로 전체 | C1 미충족 |
| 시작 정책의 특정 저장소 이름 분기 | C1 미충족. 호스트 이름이 정책에 결합됨 |
| 도메인 작업 위임 조항 | C1 미충족 |
| 패키지명의 호스트 프로젝트 이름 | C1 미충족 |
| Obsidian 검토 계약 | 도구 종속. §3.2 참조 |
| 정기 자동 보고 | C2·C3 미충족. 이미 폐기된 방향 |
| 배포 브랜치·submodule | Stage 28로 연기 |

## 4. 숨은 의존성 검사 결과

Stage 2 검증 방법 3의 결과다. **제외·보류 대상이 필수 기능의 숨은 의존성인 사례가 1건 있다.**

참고 구현의 모듈 의존 방향은 다음과 같다.

```
유지보수 검증 ──> 컨텍스트 ──> 지식 ──> 기록 저장소
      │              │          │
      │              └──> 수명주기 ──┘
      └──> 파생 artifact ──> 기록 저장소
```

**문제:** 실제 소비자가 확인된 유일한 모듈(유지보수 검증)이 실험 등급인 지식·수명주기·기록 저장소를 전이적으로 끌어온다. 파생 artifact 검증도 기록 저장소에 의존한다.

**영향:** 실험 기능을 제거하면 필수 Kernel이 import 단계에서 실패한다. 즉 현재 구현 상태로는 §3의 분류를 그대로 파일 이동에 적용할 수 없다.

**처분:** 유지보수 검증을 두 기능으로 분해한다.

| 분해 후 기능 | 등급 | 의존 |
|---|---|---|
| 문서·링크·Schema·AST·보호 경로·Git 상태 검사 | 필수 Kernel | 경로 안전 판정만 |
| source drift·중복·컨텍스트 재평가 | 실험 기능 | 지식·수명주기 Runtime |

파생 artifact 검증의 기록 저장소 의존은 쓰기 계약이 아니라 오류 유형 참조이므로, 오류 유형을 필수 계층으로 올려 해소한다.

**이 처분은 Stage 3의 계층 경계와 의존 방향 설계가 반드시 해결해야 할 제약이다.** Stage 3에서 이 분해가 성립하지 않으면 Stage 2의 분류를 다시 판정한다.

## 5. 필수 Kernel만 남겼을 때의 작업 흐름

Stage 2 검증 방법 2의 결과다. 필수 Kernel만으로 아래 흐름이 성립한다.

| 흐름 | 담당 필수 구성요소 |
|---|---|
| 에이전트가 시작해 정책 정본에 도달 | 진입 문서, 상시 정책, rule-governance |
| 현재 작업에 필요한 규칙만 선택 | rule-governance, 라우팅 테이블 |
| 현재 상태를 읽고 첫 다음 행동을 확인 | 현재 상태 문서, staged-work-design |
| 위험 행동에서 정지 | core-change-control, user-data-work, version-control |
| 변경 후 무결성 검증 | 문서·링크·Schema·AST 검사, 파생 artifact 검증 |
| 실패를 기록하고 재사용 | failure-records, 실패 지식 6건 |
| 다른 에이전트가 재개 | 현재 상태 문서, staged-work-design |

**미충족 없음.** 실험 기능이 하나도 없어도 헌장 §4의 G1~G6을 시도할 수 있다. 단 G6(재현성)의 컨텍스트 부분은 검증된 선택 기능인 컨텍스트 구성이 담당하므로, 1차 Core에서 G6은 규칙 선택의 재현성까지만 보장한다.

## 6. 집계

| 등급 | 규칙 | 문서 | Schema | 구현 | 실패 | 계 |
|---|---:|---:|---:|---:|---:|---:|
| 필수 Kernel | 8 | 2 | 0 | 3 | 6 | 19 |
| 검증된 선택 | 3 | 1 | 1 | 3 | 0 | 8 |
| 실험 | 0 | 5 | 10 | 4 | 0 | 19 |
| 제외 | 0 | 1 | 0 | 1 | 0 | 2 |

`MAINTENANCE_AUTOMATION_CONTRACT`와 유지보수 검증 구현은 §4에 따라 분해되므로 두 등급에 걸친다. 위 표에서는 주 등급으로 계상했다.

## 7. 미확정으로 남기는 항목

판단이 갈릴 수 있어 근거와 함께 열어 둔다.

| 항목 | 쟁점 | 판정 시점 |
|---|---|---|
| 단계 설계 fingerprint | Stage 9의 게이트를 직접 지원하므로 필수일 수 있으나 현재 실험 Runtime에 결합 | Stage 9 |
| 컨텍스트 구성 | G6의 완전한 달성에 필요하나 실사용 소비자가 도메인 경유뿐 | Stage 18 |
| 실패 지식의 구조화 표현 | Markdown 정본과 payload schema 중복 정본 위험 | Stage 17 |
| 내보내기 manifest | Host 없이는 소비자가 없으나 Stage 26 호환성 관리에 필요할 수 있음 | Stage 26 |
