# Agent Core

- 목적: Agent Core의 정본 문서와 저장소 구조를 안내한다.
- 읽는 시점: Core가 해결하는 문제와 전체 구조를 빠르게 파악할 때.
- 책임: Core Maintainer가 목적·구조의 정본과 일치하도록 유지한다.
- 상태: 활성 개요. 정본이 아닌 파생 표현.
- 관련 권위: [Core 헌장](docs/CHARTER.md), [Kernel 범위](docs/KERNEL_SCOPE.md), [계층 구조](docs/ARCHITECTURE.md), [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md).

## 목적

[Core 헌장](docs/CHARTER.md)의 §1~2가 해결하는 문제와 목적을 소유한다.

## 설계 의도

[Core 헌장 §6](docs/CHARTER.md#6-설계-원칙)의 원칙, [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md)의 정본 배치, [계층 구조](docs/ARCHITECTURE.md)의 Core·Consumer 경계를 따른다.

## 저장소 구조

| 위치 | 역할 |
|---|---|
| `PROJECT_RULES.md` | Core 공통 정책과 행동별 규칙 선택 경로 |
| `rules/` | 작업 상황별 공통 절차, 안전 경계와 검증 규칙 |
| `skills/` | 원본 내용과 참고 자료를 보존한 스킬 패키지 및 Codex·Claude 진입 |
| `docs/` | Core의 목적, 범위, 구조, 정보 소유권과 호환성 정본 |
| `src/core_check/` | 선언과 경계를 해석하고 검사하는 필수 검증 Kernel |
| `experimental/shared_data/` | 필수 Kernel과 격리된 선택적 공통 데이터 계약과 Runtime |
| `tests/` | 필수 정책·계약·검증기의 회귀 및 결함 주입 검사 |

구조와 의존 방향의 세부 정본은 [계층 구조](docs/ARCHITECTURE.md), Core와 Consumer가 소유하는 정보의 정본은 [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md)가 제공한다.

공통 스킬의 제공 범위와 호출 정책은 [공개 스킬 계약](docs/COMPATIBILITY.md#3b-공통-workflow-진입-계약)이, Consumer 연결 절차는 [소비 안내](docs/CONSUMER_GUIDE.md#10-공통-스킬-진입-구성)가 소유한다. 자산의 존재와 실제 도구에서의 발견·실행 검증은 구분한다.
