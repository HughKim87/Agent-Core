# Agent Core

- 목적: Core의 사람용 개요와 정본 진입 링크를 제공한다.
- 읽는 시점: 저장소의 역할과 다음에 읽을 정본을 처음 확인할 때.
- 책임: 프로젝트 에이전트가 정본 링크와 현재 범위 표현을 유지한다.
- 상태: 활성 개요. 정본이 아닌 파생 표현.
- 관련 권위: [정보 소유 구조](docs/INFORMATION_OWNERSHIP.md), [현재 상태](STATE.md).

서로 다른 프로젝트와 서로 다른 AI 에이전트가 대화 기억에 의존하지 않고 동일한 규칙·현재 상태·안전 경계·완료 기준을 파일에서 복원해 사용하게 하는 도메인 중립 운영 기반이다.

이 문서는 사람이 읽는 개요이며 정본이 아니다. 각 사실의 정본은 아래 링크가 소유한다.

## 어디를 읽어야 하는가

| 알고 싶은 것 | 정본 |
|---|---|
| 지금 무엇이 진행 중인가 | [STATE.md](STATE.md) |
| 이 저장소에서 일하는 규칙 | [POLICY.md](POLICY.md) |
| Core가 무엇을 보장하고 보장하지 않는가 | [docs/CHARTER.md](docs/CHARTER.md) |
| 무엇이 Core에 들어가고 무엇이 빠지는가 | [docs/KERNEL_SCOPE.md](docs/KERNEL_SCOPE.md) |
| 내부 계층과 의존 방향 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 어떤 정보가 어디에 있어야 하는가 | [docs/INFORMATION_OWNERSHIP.md](docs/INFORMATION_OWNERSHIP.md) |
| 전체 구축 계획과 단계별 성공 조건 | [AGENT_CORE_BUILD_BLUEPRINT.md](AGENT_CORE_BUILD_BLUEPRINT.md) |

## 에이전트로 시작하는 경우

[AGENTS.md](AGENTS.md) 또는 [CLAUDE.md](CLAUDE.md)가 진입점이며 둘 다 [POLICY.md](POLICY.md)를 가리킨다. 진입 파일에는 정책이나 상태가 들어 있지 않다.

## 현재 상태

독립 Core의 내부 개선과 완료 재검증이 끝났다. 정확한 현재 상태는 [STATE.md](STATE.md), 판정 근거는 [완료 판정](docs/COMPLETION.md)과 [최종 개선 보고서](docs/CORE_IMPROVEMENT_FINAL_REPORT_2026-08-14.md)가 소유한다. Host 프로젝트 연결, 배포 방식, submodule은 별도 요청과 범위 확정이 필요한 후속 작업이다.
