# Agent Core

- 목적: Agent Core의 저장소 구조, 계층, 구성요소의 책임을 설명한다.
- 읽는 시점: Core의 내부 구조와 구성요소 관계를 확인할 때.
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

## 계층별 책임

| 계층 | 위치 | 책임 |
|---|---|---|
| L1 | `PROJECT_RULES.md` | Core 공통 정책과 규칙 선택 경로 |
| L2 | `rules/` | 조건별 작업 절차, 안전 경계, 검증 규칙 |
| L3 | `docs/` | Core·Consumer 계약, 정보 소유권, 호환성 및 구조 정본 |
| L5 | `src/core_check/` | 선언 해석, 무결성 검사, 시작 context, 통합 gate |
| L6 | `src/core_check/primitives.py` | 경로 안전, 오류·finding·report, fingerprint 원시 기능 |
| L7 | `experimental/shared_data/` | 필수 Kernel과 격리된 선택 데이터 Runtime |

## 의존 방향

```text
L1 정책 ──routes──> L2 규칙
   │
   └──────────────> L3 계약·구조 선언
                         │
L6 기반 원시 <──────── L5 검증 커널
                         │
                         └── 공개 검사 결과

L7 선택 Runtime ──> L6 기반 원시·L5 등록 경계
L5 검증 커널      -X-> L7 선택 Runtime
```

- L1은 Core 규칙의 유일한 router다.
- L5는 정책·규칙·계약을 데이터로 읽고 검사한다.
- L6은 다른 내부 모듈에 의존하지 않는다.
- L5는 L7을 import하지 않으므로 선택 계층이 없어도 필수 Kernel이 성립한다.
- L7의 실제 데이터와 파생 결과는 Core가 아닌 Consumer root에 저장된다.
- 내부 import 순환과 scope 밖 경로 해석은 허용되지 않는다.

이 README는 Core 구조만 설명하는 개요다. 세부 구조의 정본은 [계층 구조](docs/ARCHITECTURE.md), 정보 배치의 정본은 [정보 소유 구조](docs/INFORMATION_ARCHITECTURE.md)가 소유한다.
