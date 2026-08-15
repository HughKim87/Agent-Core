# Core·Consumer 경계와 의존성

- 목적: Core와 Consumer가 독립적으로 유지되도록 모든 경계 참조의 유형·소유자·방향·호환성 검증을 명시한다.
- 읽는 시점: Core↔Consumer 사이의 문서 링크, rule route, schema, Runtime import, 저장 경로, submodule 계약, 경계 테스트나 외부 도구 경로를 추가·변경·제거·감사할 때.
- 책임: 에이전트가 경계 참조를 분류하고 공개 계약과 의존 방향을 검증하며, 사용자가 새 Core 공개 계약과 외부 효과를 승인한다.
- 상태: 활성 규칙. L2 구조 경계 계층.
- 관련 권위: [상시 정책](../PROJECT_RULES.md), [Core 계층과 소비 경계](../docs/ARCHITECTURE.md), [호환성](../docs/COMPATIBILITY.md).

---

## 1. 참조 분류

경계를 넘는 참조는 다음 중 정확히 하나로 분류한다.

| 유형 | 기본 처리 |
|---|---|
| 진입·navigation | Consumer 루트 진입과 Core 공개 문서만 사용 |
| rule routing | Core 공통 route와 Consumer 도메인 route의 소유권을 분리 |
| contract·schema | 공개 owner, version, 호환·이전 절차를 명시 |
| Runtime API | Consumer에서 Core 공개 인터페이스로만 단방향 의존 |
| storage | 프로젝트 데이터와 상태는 Consumer가 소유 |
| test-only | 운영 의존이나 활성 route로 승격하지 않음 |
| 외부 tool route | 승인·최소 성공 호출·실패 비용을 확인한 뒤 채택 |

문서 링크를 Runtime 의존이라고 부르거나, 테스트 helper를 공개 API처럼 사용해 유형을 숨기지 않는다.

## 2. 허용 방향

- Core는 특정 Consumer의 코드·도메인·상태·보호 경로·저장 구조를 import하거나 소유하지 않는다.
- Consumer는 공개된 Core 정책·계약과 `verify`, `context`, `gate` 인터페이스에만 의존한다.
- Core 내부 Python 함수, 테스트 helper, 설명 문구, 우연한 파일 배치는 공개 호환성 계약이 아니다.
- 양쪽에 필요한 도메인 데이터나 schema를 Core에 복사하지 않는다. 공통 보장에 필요한 도메인 중립 계약인지 먼저 판정하고, 아니면 Consumer가 소유한다.
- Core와 Consumer 규칙 파일은 서로를 직접 route하지 않는다. 각 scope의 상위 정책이 자기 규칙을 선택한다.

## 3. 경계 변경 게이트

새 참조를 만들기 전에 다음을 확인한다.

1. 기존 공개 인터페이스로 같은 결과를 얻을 수 있는가.
2. 참조 유형, 양쪽 owner, 허용 방향, 수명과 제거·이전 경로가 무엇인가.
3. Core contract version이나 Consumer 이전이 필요한 비호환 변경인가.
4. 프로젝트별 상태·데이터·자격 증명이 Core로 새지 않는가.
5. 반대쪽 orphan scan과 양쪽 관련 회귀를 어떻게 실행할 것인가.

기존 공개 경계로 표현할 수 없으면 Consumer에서 Core 내부 구현을 우회 참조하지 않는다. 새 Core 계약이 필요하면 정확한 Core 변경 범위를 별도로 승인받는다.

## 4. 외부 도구 경로

새 외부 CLI·API·Agent·MCP server·interface route를 지속 경로로 채택하기 전에 read-only 또는 별도로 승인된 최소 성공 호출로 다음을 확인한다.

- 설치·Runtime version과 실제 명령·옵션명
- 인증 경로와 필요한 최소 권한
- 출력 구조와 오류 상태
- 실패 비용과 복구 또는 대체 경로

이미 검증된 동일 version·route·계약을 재사용할 때만 기존 근거를 사용할 수 있다. 상태 변경 호출과 비용 발생은 이 규칙만으로 승인되지 않는다.

## 5. 검증

- 모든 경계 참조에 유형, owner, 방향, 공개 계약, 회귀 검사가 있는지 확인한다.
- Core의 Consumer import와 Consumer의 비공개 Core import가 0인지 검사한다.
- Core·Consumer 문서와 규칙이 서로의 상위 router를 우회하지 않는지 확인한다.
- 변경한 쪽의 direct reference scan과 반대쪽 orphan scan을 모두 실행한다.
- 새 외부 도구 경로는 최소 호출의 대상·시점·version·결과를 확인하고 실패한 경로를 활성 경로로 남기지 않는다.
