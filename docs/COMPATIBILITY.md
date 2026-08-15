# 버전과 호환성

- 목적: 지원 런타임, 공개 계약 버전, 호환·비호환 변경과 이전 절차를 단일 선언으로 소유한다.
- 읽는 시점: Core를 연결·갱신하거나 공개 인터페이스를 바꿀 때.
- 책임: Core Maintainer가 선언과 구현을 일치시키고 사용자가 비호환 변경을 승인한다.
- 상태: 활성 정본. Core 0.2.0 / contract 2.
- 관련 권위: [Core 상시 정책](../PROJECT_RULES.md), [공개 경계](ARCHITECTURE.md).

---

## 1. 기계 판독 선언

<!-- core-compatibility:v1 -->
```json
{
  "core_version": "0.2.0",
  "contract_version": 2,
  "python_min": "3.10",
  "required_dependencies": [],
  "optional_dependencies": []
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

## 3. contract 2 공개 계약

- Core 내부 자동 진입 파일과 현재 상태를 제공하지 않는다.
- 소비 저장소가 `agent-core-consumer:v1` 선언과 진입·정책·상태를 제공한다.
- CLI는 `--core-root`와 `--consumer-root`를 구분한다.
- `context` 문서 경로는 `scope`와 `path` 객체로 반환한다.
- `verify`, `context`, `gate` 명령과 종료 상태 0·1·2를 제공한다.
- v2 동안 `--root`는 `--core-root`의 deprecated alias다.

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

- 필수 의존성은 Python 표준 라이브러리뿐이다.
- 선택 기능이 없어도 필수 검증이 통과해야 한다.
- 추적 텍스트 표준은 UTF-8과 LF다.
- LF와 CRLF는 정상 줄 종료로 해석하고 실제 후행 공백·탭만 위반으로 판정한다.

## 7. 복구

- Core revision은 submodule gitlink가 소유한다.
- 검증 실패 시 부모 gitlink를 마지막 검증 commit으로 되돌린다.
- 저장소 안에 백업 사본이나 SHA 복제 문서를 만들지 않는다.
- `--root` alias 제거는 다음 계약 세대의 별도 비호환 변경이다.
