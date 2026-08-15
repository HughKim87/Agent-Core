# Core 계층과 소비 경계

- 목적: Core 내부 계층, 공개 인터페이스, Core·소비 저장소 scope와 허용 의존 방향을 소유한다.
- 읽는 시점: 구성요소를 배치하거나 의존·검사 경계를 바꿀 때.
- 책임: 사용자가 계층·scope 변경을 승인하고 Core Maintainer가 경계를 유지한다.
- 상태: 활성 정본. contract v2.
- 관련 권위: [Core 헌장](CHARTER.md), [Kernel 범위](KERNEL_SCOPE.md).

---

## 1. 두 scope

| scope | 소유 내용 | 소유하지 않는 것 |
|---|---|---|
| `core` | 공통 정책·규칙·계약·검증 코드·회귀 테스트 | 특정 프로젝트 상태·도메인·보호 경로·자격 증명 |
| `consumer` | 루트 진입, 프로젝트 정책·route, 현재 상태, 보호 경로, Core gitlink | Core 공통 규칙과 Core 구현 |

검증기는 두 scope를 별도 root로 받고 상대경로를 각각의 root 안에서만 해석한다. 부모 저장소 검사에서 선언된 Core subtree를 다시 재귀 순회하지 않는다.

## 2. Core 내부 계층

| 계층 | 소유 정보 | 공개 인터페이스 |
|---|---|---|
| L1 | Core 정책과 규칙 route | Core 정책 경로와 route 표 |
| L2 | 조건부 공통 절차 | 각 규칙의 조건·행동·예외·검증 |
| L3 | 계약·정보 소유 구조 | Core·consumer 역할 선언과 문서 정본 |
| L4 | 규칙에서 도출되지 않는 최소 예외 진단 | 명시적으로 필요할 때의 링크 |
| L5 | 선언 해석, 무결성, context, 통합 gate | `verify`, `context`, `gate`와 구조화 결과 |
| L6 | 경로 안전, 오류 유형, fingerprint | 순수 함수와 예외 타입 |
| L7 | 선택적 실험 Runtime | L5 등록 인터페이스만 사용 |

## 3. 의존 방향

- L1은 Core 규칙의 유일한 Core router다. 소비 정책은 자기 scope의 도메인 route만 소유한다.
- L5는 L1~L4 파일을 데이터로 읽을 수 있지만 문서 이름을 코드 상수로 고정하지 않는다.
- L5와 L7은 서로 import하지 않는다. L7은 등록 인터페이스를 통해서만 선택 검사를 추가한다.
- L6은 어떤 내부 모듈도 import하지 않는다.
- 모든 내부 import 순환을 금지한다.
- 소비 선언의 경로는 소비 root 밖으로, Core 선언의 경로는 Core root 밖으로 나갈 수 없다.
- `protected_paths`는 경계 판정만 하고 존재 여부 확인·열거·내용 읽기를 하지 않는다.

## 4. 실험 격리

L7이 없어도 Core import, Core 자체 `verify`, Core 자체 `gate`가 성립해야 한다. 선택 기능 부재는 `not_applicable`이며 필수 실패가 아니다. L7 전체를 제거했을 때 Core 필수 보장이 줄어들면 그 기능은 격리되지 않은 것이다.

## 5. 모듈 배정

<!-- core-module-layers:v1 -->
```json
{
  "L5": [
    "src/core_check/__init__.py",
    "src/core_check/__main__.py",
    "src/core_check/cli.py",
    "src/core_check/context.py",
    "src/core_check/declarations.py",
    "src/core_check/derived.py",
    "src/core_check/gate.py",
    "src/core_check/integrity.py",
    "src/core_check/registry.py"
  ],
  "L6": [
    "src/core_check/primitives.py"
  ],
  "L7": []
}
```

모든 `src/core_check/*.py`는 정확히 한 계층에 배정된다.

## 6. 검사 가능한 경계

| ID | 검사 |
|---|---|
| A1 | L5가 L7을 import하지 않음 |
| A2 | L6가 내부 모듈을 import하지 않음 |
| A3 | 내부 import 순환 0건 |
| A4 | Core 규칙이 다른 규칙을 직접 route하지 않음 |
| A5 | 모든 Core 규칙이 Core 정책에서 정확히 한 번 route됨 |
| A6 | L5 코드에 선언된 정책 파일명이 상수로 박혀 있지 않음 |
| A7 | 모든 모듈이 정확히 한 계층에 배정됨 |
| A8 | Core 검사와 소비 검사가 서로의 root를 중복 순회하지 않음 |
| A9 | context 경로가 `core` 또는 `consumer` scope를 명시함 |

## 7. 공개 경계

외부 소비자가 의존할 수 있는 것은 다음뿐이다.

- `PROJECT_RULES.md`와 `rules/`의 공통 정책 계약
- [정보 소유 구조](INFORMATION_ARCHITECTURE.md)의 선언
- [호환성 선언](COMPATIBILITY.md)
- `core_check`의 `verify`, `context`, `gate` 명령·종료 상태·결과 구조

내부 Python 함수, 문서 배치의 설명 문구, 테스트 helper는 공개 호환성 계약이 아니다.
