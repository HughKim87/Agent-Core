# Agent Core

- 목적: Agent Core의 사람용 개요와 정본·사용 안내 진입 링크를 제공한다.
- 읽는 시점: Core의 역할과 사용 시작점을 처음 확인할 때.
- 책임: Core Maintainer가 개요와 정본 링크를 유지한다.
- 상태: 활성 개요. 정본이 아닌 파생 표현.
- 관련 권위: [Core 헌장](docs/CHARTER.md), [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md).

Agent Core는 서로 다른 프로젝트와 AI 에이전트가 대화 기억에 의존하지 않고 공통 규칙·안전 경계·완료 기준을 복원하게 하는 도메인 중립 기반이다.

Core 저장소는 공통 정책, 규칙, 계약, 검증기와 명시적으로 공개된 선택 기능을 제공한다. 프로젝트의 진입 파일, 도메인 정책, 현재 상태, 보호 경로와 실제 Runtime 데이터는 Core를 submodule로 사용하는 소비 저장소가 소유한다.

## 시작하기

Agent Core를 Host로 사용하는 저장소는 [소비자 사용 안내](docs/CONSUMER_GUIDE.md)에 따라 저장소의 진입 파일과 소비 계약을 구성한다.

- 실제 저장소에 연결하고 갱신·검증하는 방법: [소비자 사용 안내](docs/CONSUMER_GUIDE.md)
- Core가 해결하는 문제와 보장: [Core 헌장](docs/CHARTER.md)
- Core와 소비 저장소의 정보 소유권: [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md)
- Codex·Claude 진입 파일 계약: [에이전트 진입 계약](docs/AGENT_ENTRY.md)
- 공개 버전과 호환성: [버전과 호환성](docs/COMPATIBILITY.md)
- 필수·선택·흡수 예정 범위: [Kernel 범위](docs/KERNEL_SCOPE.md)
- 검증 수준과 완료 판정: [검증 계약](docs/VERIFICATION.md)

이 README는 절차나 현재 상태의 정본이 아니다. 설치·운영 절차는 소비자 사용 안내가, 각 프로젝트의 현재 상태는 해당 소비 저장소가 소유한다.
