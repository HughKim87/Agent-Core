# 현재 상태

- 목적: 현재 단계, 활성 설계, 차단, 승인 상태와 첫 다음 행동의 단일 정본.
- 읽는 시점: 세션을 시작할 때, 작업을 이어받을 때.
- 책임: 프로젝트 에이전트가 단계 전환 시 갱신한다.
- 상태: 활성 정본.
- 관련 권위: [Core 헌장](docs/CHARTER.md)이 목적과 보장을, [전체 구축 설계](AGENT_CORE_BUILD_BLUEPRINT.md)가 단계 지도를 소유한다.

완료된 단계의 상세는 이 문서에 남기지 않는다. Git 커밋에서 조회한다.

---

## 현재 단계

- 단계: Stage 24 — 작업 상태 Runtime 필요성 검증
- Phase: E — 실험 기능 판정
- 활성 전체 설계: [AGENT_CORE_BUILD_BLUEPRINT.md](AGENT_CORE_BUILD_BLUEPRINT.md)
- 활성 단계 설계: 없음

## 통과한 게이트

| Stage | 결과 | 증거 |
|---|---|---|
| 1 목적과 최종 책임 | pass | [docs/CHARTER.md](docs/CHARTER.md) |
| 2 Kernel 포함·제외 범위 | pass | [docs/KERNEL_SCOPE.md](docs/KERNEL_SCOPE.md) |
| 3 계층과 의존 방향 | pass | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 4 정보 유형과 정본 구조 | pass | [docs/INFORMATION_OWNERSHIP.md](docs/INFORMATION_OWNERSHIP.md) |
| 5 Agent 진입 구조 | pass | [docs/AGENT_ENTRY.md](docs/AGENT_ENTRY.md) |
| 6 권한·승인·안전 정책 | pass | [POLICY.md](POLICY.md) §6 |
| 7 작업 등급과 규칙 라우팅 | pass | [rules/rule-governance.md](rules/rule-governance.md), 라우팅 테스트 9건 |
| 8 작업 요청·범위·완료 조건 계약 | pass | [rules/work-contract.md](rules/work-contract.md) |
| 9 단계 작업 설계와 무효화 | pass | [rules/staged-work-design.md](rules/staged-work-design.md) |
| 10 현재 상태와 인수인계 | pass | [rules/handoff.md](rules/handoff.md), 상태 계약 테스트 |
| 11 문서 수명주기 | pass | [rules/document-work.md](rules/document-work.md) |
| 12 보호 데이터와 외부 효과 | pass | [rules/protected-data.md](rules/protected-data.md) |
| 13 Core 자체 변경 통제 | pass | [rules/core-change-control.md](rules/core-change-control.md) |
| 14 검증 수준과 완료 판정 | pass | [docs/VERIFICATION.md](docs/VERIFICATION.md) |
| 15 무결성·경계 검사 구현 | pass | `src/core_check/`, 결함 주입 테스트 |
| 16 파생 artifact 관리 | pass | `src/core_check/derived.py` |
| 17 실패 분류와 실패 지식 | pass | [failures/README.md](failures/README.md) |
| 18 선택적 읽기와 컨텍스트 | pass | `src/core_check/context.py` |
| 19 최소 공개 인터페이스 | pass | `src/core_check/cli.py` |
| 20 Core 자체 운영 시나리오 | pass | 시나리오 3종 실행 기록은 Git |
| 21 다중 Agent 작업 재개 | pass | 콜드 세션 2회. 기록은 Git |
| 22 통합 검증 게이트 | pass | `src/core_check/gate.py` |
| 23 실험 격리와 승격 기준 | pass | [docs/EXPERIMENTAL.md](docs/EXPERIMENTAL.md) |

## 승인 상태

- 사용자가 블루프린트의 모든 단계를 에이전트 권장안으로 진행하도록 위임했다.
- 단계 완료 시 커밋을 남긴다. push는 승인되지 않았다.
- 참고 구현은 읽기 전용이다. 변경이 필요하면 중단하고 보고한다.
- 재개 방식: `portable`. 저장소의 추적된 내용만으로 재개된다.

## 차단

없음.

## 알려진 위험

| 항목 | 내용 | 해소 시점 |
|---|---|---|
| 부분 구현 검사 | 계층 배정 검사 A7과 정본 규칙 O2·O3·O6은 아직 자동 검사가 없다 | 미정. 현재 위험은 낮다 |
| 실험 Runtime 미이식 | 작업 상태·지식 Runtime을 아직 이 저장소로 옮기지 않았다 | Stage 23~25 |
| Host 경계 미해결 | Core가 하위 디렉터리로 들어갈 때의 진입 파일 문제가 미결이다 | Stage 28 |

## 첫 다음 행동

1. `docs/EXPERIMENTAL.md` §5 의 비교 기준으로 Markdown 기준선의 실측값을 모은다.
2. 참고 구현의 작업 상태 Runtime을 같은 기준에 대입한다.
3. `채택`·`실험 유지`·`제외` 중 하나를 근거와 함께 확정하고 Kernel 범위 문서에 반영한다.
