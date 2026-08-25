# Agent Core

- 목적: Agent Core의 역할, 저장소 구조, 공개 진입점을 한눈에 설명한다.
- 읽는 시점: Core의 책임과 구성요소, 사용 시작점을 처음 확인할 때.
- 책임: Core Maintainer가 구현 구조와 정본 링크에 맞게 유지한다.
- 상태: 활성 개요. 정본이 아닌 파생 표현.
- 관련 권위: [Core 헌장](docs/CHARTER.md), [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md), [계층 구조](docs/ARCHITECTURE.md).

Agent Core는 서로 다른 프로젝트와 AI 에이전트가 대화 기억에 의존하지 않고 같은 공통 규칙, 안전 경계, 시작 문맥, 완료 기준을 복원하도록 돕는 도메인 중립 기반이다.

Core는 공통 정책·규칙·계약·검증기를 제공한다. 프로젝트별 진입 파일, 도메인 정책, 현재 상태, 보호 경로, 실제 Runtime 데이터는 Core를 submodule로 연결한 **소비 저장소(Consumer)** 가 소유한다.

## 설계 경계

```text
Core 저장소                              소비 저장소
──────────────────────────────          ──────────────────────────────
공통 정책과 규칙                         AGENTS.md / CLAUDE.md
계약과 호환성 선언              <───     프로젝트 정책과 Core 소비 선언
verify / context / gate         ───>     현재 상태와 도메인 규칙 검증
선택적 shared_data Runtime      ───>     소비 저장소 내부 Runtime 데이터
```

- Core와 Consumer는 서로 다른 root와 정보 소유권을 유지한다.
- 필수 검증 커널은 선택 기능을 import하지 않으며, 선택 기능이 없어도 동작한다.
- 선언된 경로는 각 root 밖으로 나갈 수 없다.
- 보호 경로는 경계만 검사하고 존재 여부를 확인하거나 내용을 읽지 않는다.
- 외부 소비자는 문서에 선언된 CLI·결과 구조·schema만 공개 계약으로 사용한다.

정확한 계층과 허용 의존 방향은 [계층 구조](docs/ARCHITECTURE.md)가 소유한다.

## 저장소 구조

```text
Agent-Core/
├─ PROJECT_RULES.md            # L1: 공통 정책과 규칙 라우터
├─ rules/                      # L2: 행동 조건별 공통 절차와 안전 규칙
├─ docs/                       # L3: 헌장, 경계, 호환성, 소비·검증 계약
├─ src/core_check/             # L5·L6: 필수 검증 커널과 공개 CLI
│  ├─ cli.py                   # verify, context, gate 명령
│  ├─ declarations.py          # Markdown 안의 기계 판독 선언 해석
│  ├─ integrity.py             # Core·Consumer 구조 및 무결성 검사
│  ├─ context.py               # scope가 있는 시작 문맥과 fingerprint 생성
│  ├─ gate.py                  # preflight·무결성·회귀·무부작용 통합 게이트
│  ├─ registry.py              # 필수·선택 검사 등록 경계
│  ├─ derived.py               # 결정론적 파생 artifact drift 검사
│  └─ primitives.py            # L6: 경로 안전, finding, report, fingerprint
├─ experimental/shared_data/   # L7: 격리된 선택 데이터 기능
│  ├─ schemas/                 # 공개 request/result 및 payload schema
│  └─ tests/                   # 선택 기능 전용 회귀·경계 테스트
└─ tests/                      # 필수 커널의 회귀·결함 주입 테스트와 fixture
```

`src/core_check`는 Core 자체와 Consumer 계약 표면을 읽기 전용으로 검사하는 필수 경로다. `experimental/shared_data`는 source·knowledge·decision·lifecycle·evidence context·work state를 다루는 선택 경로이며, 실제 데이터는 항상 Consumer root 안에 둔다.

## 검증 흐름

| 명령 | 역할 | Consumer 필요 여부 |
|---|---|---:|
| `verify` | 선언, 문서, 링크, JSON, Python AST, 규칙 route, 계층 경계를 검사 | 선택 |
| `context` | Core 정책·Consumer 정책·현재 상태와 선택된 규칙으로 시작 문맥 및 fingerprint 생성 | 필요 |
| `gate` | preflight, 무결성, 회귀 테스트, 선택 기능, 무부작용 검사를 통합 실행 | 선택 |

Core 저장소 자체를 확인하는 최소 실행 예시는 다음과 같다.

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath 'src').Path
python -B -m core_check --core-root . verify
python -B -m core_check --core-root . gate
```

명령은 JSON을 stdout으로 반환하며 종료 상태는 성공, 계약·무결성 위반, 실행 불가를 구분한다. Consumer 연결과 선택 기능 호출을 포함한 전체 절차는 [소비자 사용 안내](docs/CONSUMER_GUIDE.md), 판정 의미는 [검증 계약](docs/VERIFICATION.md), 지원 런타임과 공개 계약은 [호환성 선언](docs/COMPATIBILITY.md)이 정본이다.

## 사용 시작점

### Core를 프로젝트에 연결할 때

1. [소비자 사용 안내](docs/CONSUMER_GUIDE.md)에서 submodule 연결과 소비 선언 형식을 확인한다.
2. Consumer root에 `AGENTS.md`, `CLAUDE.md`, 프로젝트 `PROJECT_RULES.md`, 현재 상태 문서를 둔다.
3. Core의 `verify`, `context`, `gate`를 Consumer root와 함께 실행한다.

### Core 자체를 변경할 때

1. [Core 상시 정책](PROJECT_RULES.md)에서 현재 행동에 맞는 규칙을 선택한다.
2. [Kernel 범위](docs/KERNEL_SCOPE.md)와 [계층 구조](docs/ARCHITECTURE.md)에서 배치·의존 경계를 확인한다.
3. 변경 영향에 맞는 검사를 실행하고 [검증 계약](docs/VERIFICATION.md)에 따라 완료 수준을 보고한다.

## 문서 안내

| 질문 | 정본 |
|---|---|
| Core가 해결하는 문제와 보장은 무엇인가? | [Core 헌장](docs/CHARTER.md) |
| Core와 Consumer는 무엇을 각각 소유하는가? | [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md) |
| 계층과 import·경로 경계는 어떻게 되는가? | [계층 구조](docs/ARCHITECTURE.md) |
| 무엇이 필수·선택·제외 범위인가? | [Kernel 범위](docs/KERNEL_SCOPE.md) |
| 프로젝트에 어떻게 연결하고 검증하는가? | [소비자 사용 안내](docs/CONSUMER_GUIDE.md) |
| Codex·Claude 진입 파일은 어떻게 구성하는가? | [에이전트 진입 계약](docs/AGENT_ENTRY.md) |
| 현재 공개 버전과 호환 범위는 무엇인가? | [버전과 호환성](docs/COMPATIBILITY.md) |
| 어떤 검사가 완료를 증명하는가? | [검증 계약](docs/VERIFICATION.md) |
| 선택 기능은 어떻게 격리·승격되는가? | [실험 기능 계약](docs/EXPERIMENTAL.md) |

이 README는 구조를 설명하는 개요다. 정책, 절차, 버전, 현재 상태의 정본을 복제하지 않으며 충돌할 경우 위에 연결된 각 정본을 따른다.
