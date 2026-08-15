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

## 2. 판정값

| 값 | 의미 | 필수 게이트 처리 |
|---|---|---|
| `pass` | 실행했고 통과 | 성공 후보 |
| `fail` | 실행했고 실패 | 전체 실패 |
| `not_run` | 실행하지 않음 | 전체 실패 |
| `not_applicable` | 이유가 있는 비해당 | 비실패 |

## 3. Core 자체 gate

소비 저장소 없이 다음을 검증한다.

- 런타임·layout preflight
- Core 역할·호환성 선언
- 문서·링크·JSON·Python AST·텍스트
- 규칙 route와 모듈 계층
- 회귀·결함 주입 테스트
- 실행 전후 Core tree 무부작용

Core 자체 gate 통과만으로 Host 사용 가능성이나 read-only push 거부를 주장하지 않는다.

## 4. 소비 통합 gate

`--consumer-root`를 지정하면 Core 자체 gate에 다음을 추가한다.

- 소비 계약 버전·역할·상대경로
- 진입 포인터의 대상과 순서
- 소비 상태 구조와 크기 예산
- 소비 규칙 route
- `.gitmodules`의 Core path
- Core·consumer scope가 있는 context와 fingerprint
- 보호 경로를 제외한 소비 계약 표면의 무부작용

실제 gitlink 객체, Deploy Key fetch·push 권한, Codex·Claude 행동은 별도 통합·실제 사용 검증이 소유한다.

## 5. 위험별 최소 수준

| 작업 | 최소 증거 |
|---|---|
| `quick` | `parsed` |
| `standard` | `structure-validated` |
| 정책·규칙 변경 | 구조·route 검사 + 관련 결함 주입 |
| 검증 도구 변경 | `unit-tested` + 정상·오류·수행 불가 경계 |
| Core release 후보 | Core gate + commit snapshot clean clone |
| 소비 연결 후보 | 소비 gate + 부모·submodule Git 상태 대조 |
| 범용 Host 사용 주장 | 서로 다른 실제 Host 2개 + `cross-agent` |

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
3. 실행하지 않은 검사와 이유
4. 현재 checkout·commit snapshot·실제 사용 중 어느 수준인지
5. 알려진 한계와 다음 게이트

필수 검사 중 `fail` 또는 `not_run`이 있으면 다음 단계로 전환하지 않는다.
