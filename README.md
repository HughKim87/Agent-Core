# Agent Core

- 목적: Core의 사람용 개요와 정본 진입 링크를 제공한다.
- 읽는 시점: 저장소의 역할과 다음에 읽을 정본을 처음 확인할 때.
- 책임: 프로젝트 에이전트가 정본 링크와 현재 범위 표현을 유지한다.
- 상태: 활성 개요. 정본이 아닌 파생 표현.
- 관련 권위: [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md), [현재 상태](SESSION_HANDOFF.md).

서로 다른 프로젝트와 서로 다른 AI 에이전트가 대화 기억에 의존하지 않고 동일한 규칙·현재 상태·안전 경계·완료 기준을 파일에서 복원해 사용하게 하는 도메인 중립 운영 기반이다.

이 문서는 사람이 읽는 개요이며 정본이 아니다. 각 사실의 정본은 아래 링크가 소유한다.

## 어디를 읽어야 하는가

| 알고 싶은 것 | 정본 |
|---|---|
| 지금 무엇이 진행 중인가 | [SESSION_HANDOFF.md](SESSION_HANDOFF.md) |
| 이 저장소에서 일하는 규칙 | [PROJECT_RULES.md](PROJECT_RULES.md) |
| Core가 무엇을 보장하고 보장하지 않는가 | [docs/CHARTER.md](docs/CHARTER.md) |
| 무엇이 Core에 들어가고 무엇이 빠지는가 | [docs/KERNEL_SCOPE.md](docs/KERNEL_SCOPE.md) |
| 내부 계층과 의존 방향 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 어떤 정보가 어디에 있어야 하는가 | [docs/INFORMATION_ARCHITECTURE.md](docs/INFORMATION_ARCHITECTURE.md) |
| 완료된 최초 구축 설계와 단계별 성공 조건 | [AGENT_CORE_BUILD_BLUEPRINT.md](AGENT_CORE_BUILD_BLUEPRINT.md) |

## 에이전트로 시작하는 경우

[AGENTS.md](AGENTS.md) 또는 [CLAUDE.md](CLAUDE.md)가 진입점이며 둘 다 [PROJECT_RULES.md](PROJECT_RULES.md)를 가리킨다. 진입 파일에는 정책이나 상태가 들어 있지 않다.

전용 진입 파일을 사용하지 않는 에이전트는 [PROJECT_RULES.md](PROJECT_RULES.md)를 끝까지 읽고, 이어 [SESSION_HANDOFF.md](SESSION_HANDOFF.md)를 끝까지 읽은 뒤 현재 요청에 일치하는 규칙만 선택한다.

## 현재 상태

독립 Core 1차 완료와 내부 품질 마감이 끝났다. 정확한 현재 단계와 게이트는 [SESSION_HANDOFF.md](SESSION_HANDOFF.md), 완료 조건은 [완료 판정](docs/COMPLETION.md)이 소유한다. Host 프로젝트 연결, 배포 방식, submodule은 별도 요청과 범위 확정이 필요한 후속 작업이다.
