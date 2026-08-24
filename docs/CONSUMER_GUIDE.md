# Agent Core 소비자 사용 안내

- 목적: Maintainer·Host 저장소가 Agent Core를 submodule로 연결하고 버전을 고정·갱신·검증·복구하는 절차를 소유한다.
- 읽는 시점: Core를 처음 연결할 때, clone·update·검증·복구할 때, Maintainer와 Host 권한 차이를 확인할 때.
- 책임: Core Maintainer가 공개 계약과 명령의 일치를 유지하고 소비 저장소 Maintainer가 자기 저장소 설정을 유지한다.
- 상태: 활성 절차 정본. contract v2.
- 관련 권위: [정보 소유 구조](INFORMATION_ARCHITECTURE.md), [에이전트 진입 계약](AGENT_ENTRY.md), [버전과 호환성](COMPATIBILITY.md).

---

## 1. 역할 선택

| 역할 | Core fetch | Core 수정·push | 사용 목적 |
|---|---:|---:|---|
| `maintainer` | 허용 | 사용자 승인과 쓰기 권한이 있을 때 허용 | Core 자체 개선 |
| `host` | 허용 | 금지 | 실제 프로젝트에서 검증된 Core 사용 |

Host에서 Core 변경 필요성을 발견하면 submodule을 수정하지 말고 Maintainer 작업으로 이관한다.

## 2. 필요한 소비 저장소 파일

소비 저장소 루트가 다음을 소유한다.

- `AGENTS.md`: Codex 포인터
- `CLAUDE.md`: Claude 포인터
- `PROJECT_RULES.md`: 프로젝트 정책, 도메인 route, 소비 계약 선언
- `SESSION_HANDOFF.md`: 현재 상태
- `rules/`: 도메인 규칙이 실제로 있을 때만 생성
- `.gitmodules`: Core 원격과 submodule 경로
- submodule gitlink: 고정한 Core commit SHA의 유일한 정본

Core SHA를 다른 문서나 선언에 다시 적지 않는다.

## 3. Core 연결

소비 저장소 루트에서 원하는 상대경로를 정해 Core 저장소 전체를 submodule로 추가한다.

```powershell
git submodule add <AGENT_CORE_REMOTE> <CORE_PATH>
git submodule update --init --recursive
```

`CORE_PATH`는 저장소 안쪽의 상대경로여야 한다. 개인키·토큰·사용자별 절대경로를 저장소 파일에 기록하지 않는다.

이미 Core가 연결된 저장소를 clone할 때는 다음 중 하나를 사용한다.

```powershell
git clone --recurse-submodules <CONSUMER_REMOTE>
```

또는 일반 clone 뒤 다음을 실행한다.

```powershell
git submodule update --init --recursive
```

## 4. 소비 계약 선언

소비 저장소의 `PROJECT_RULES.md`에 다음 선언을 정확히 하나 둔다.

<!-- agent-core-consumer:v1 -->
```json
{
  "contract_version": 2,
  "consumer_role": "host",
  "core_path": "core",
  "state": "SESSION_HANDOFF.md",
  "entry_pointers": {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md"
  },
  "required_core_capabilities": {},
  "rule_roots": ["rules"],
  "protected_paths": []
}
```
<!-- /agent-core-consumer:v1 -->

- `consumer_role`은 `maintainer` 또는 `host`다.
- `required_core_capabilities`는 필요한 선택 기능의 최소 버전만 선언한다. 요구가 없으면 생략하거나 빈 객체로 둔다. 예: `{"shared_data": 1}`.
- `rule_roots`가 없으면 빈 배열로 둔다. 빈 미래 디렉터리를 만들지 않는다.
- `protected_paths`는 보호해야 하는 상대경로만 선언한다. 검사기는 그 경로를 읽거나 열거하지 않는다.
- `protected_paths`는 Core, 정책, 상태, 진입 포인터, `rule_roots`와 겹칠 수 없다. 겹치면 보호 경계를 지킬 수 없으므로 계약 오류다.
- `core_path`는 `.gitmodules`의 path 및 실제 Core 위치와 같아야 한다.

`PROJECT_RULES.md`에는 규칙 route 블록도 정확히 하나 둔다. 도메인 규칙이 없으면 다음처럼 빈 표를 유지한다.

```markdown
<!-- core-rule-routes:v1 -->
| 행동 | 읽을 소유자 |
|---|---|
<!-- /core-rule-routes:v1 -->
```

## 5. 진입 파일

`AGENTS.md`와 `CLAUDE.md`는 정책을 복제하지 않고 다음 세 대상만 같은 순서로 가리킨다.

1. `<CORE_PATH>/PROJECT_RULES.md`
2. `PROJECT_RULES.md`
3. `SESSION_HANDOFF.md`

Codex 포인터는 세 대상의 Markdown 링크, Claude 포인터는 세 대상의 `@` 참조를 사용한다. 실제 경로는 소비 계약과 일치시킨다.

## 6. 검증 명령

소비 저장소 루트에서 Core의 `src`를 현재 PowerShell의 Python module 검색 경로에 추가한 뒤 공개 CLI를 실행한다.

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath '<CORE_PATH>/src').Path
```

Core 자체 검사:

```powershell
python -B -m core_check --core-root <CORE_PATH> verify
python -B -m core_check --core-root <CORE_PATH> gate
```

소비 통합 검사:

```powershell
python -B -m core_check --core-root <CORE_PATH> --consumer-root . verify
python -B -m core_check --core-root <CORE_PATH> --consumer-root . context
python -B -m core_check --core-root <CORE_PATH> --consumer-root . gate
```

| 종료 코드 | 의미 |
|---:|---|
| `0` | 실행한 모든 필수 검사 통과 |
| `1` | 계약 또는 무결성 위반 발견 |
| `2` | 경로·선언·파싱 문제로 검사 수행 불가 |

`not_run`이 있는 결과는 성공이 아니다.

## 6A. 선택 기능 `shared_data` v1

선택 데이터 Runtime을 사용할 때만 Core root와 `src`를 함께 Python module 검색 경로에 둔다.

```powershell
$coreRoot = (Resolve-Path -LiteralPath '<CORE_PATH>').Path
$env:PYTHONPATH = ($coreRoot, (Join-Path $coreRoot 'src') -join ';')
python -B -m experimental.shared_data info
```

`info`는 기능 버전, 공개 명령, operation과 request/result schema 경로를 반환한다. 실제 호출은 소비 root·Runtime storage root·보호 경계를 명시하고 request v1 JSON 하나를 stdin으로 보낸다.

```powershell
$request = '{"operation":"source.list","arguments":{}}'
$request | python -B -m experimental.shared_data `
  --consumer-root . `
  --storage-root runtime/agent-core `
  --protected-path private-material `
  invoke
```

- 읽기 호출은 `--write` 없이 실행한다.
- `initialize`, `*.create`, lifecycle/work 전이·재구축처럼 데이터를 바꾸는 호출은 현재 행동이 소비 정책에서 승인된 경우에만 `--write`를 추가한다.
- `--write`는 기술적 쓰기 잠금을 열 뿐 사용자 승인이나 원격 권한을 만들지 않는다.
- storage root와 보호 경로는 소비 root 상대경로다. 보호 경로의 존재를 확인하거나 내용을 전달하지 않는다.
- request는 BOM·NUL 없는 strict UTF-8 JSON이며 최대 1 MiB다. stdout은 result v1 JSON 하나이고 종료 코드는 성공 `0`, 계약·Runtime 거부 `1`, 실행 불가 `2`다.
- 공개 operation과 payload 구조는 [호환성 선언](COMPATIBILITY.md)이 가리키는 schema가 정본이다. `experimental.shared_data.*` 내부 Python import에는 의존하지 않는다.

## 7. Core 버전 갱신

1. 소비 저장소 작업 트리를 깨끗하게 만든다.
2. Core submodule에서 가져올 원격 commit을 fetch한다.
3. 검증된 Core commit을 checkout한다.
4. 소비 통합 gate를 실행한다.
5. 부모 저장소에서 변경된 gitlink만 검토·commit한다.

Host는 Core commit을 만들거나 Core 원격에 push하지 않는다. Maintainer도 사용자 승인과 전체 게이트 없이 push하지 않는다.

## 8. 권한과 키

- Maintainer clone은 쓰기 가능한 Core Deploy Key를 사용할 수 있다.
- Host clone은 읽기 전용 Core Deploy Key를 사용한다.
- 같은 PC에서도 각 clone의 로컬 `core.sshCommand`로 서로 다른 키를 선택할 수 있다.
- 개인키, 토큰, `core.sshCommand`, 사용자별 키 경로는 저장소에 추적하지 않는다.
- 정책은 보안 경계가 아니다. 실제 push 허용·거부는 원격 권한으로 검증한다.

## 9. 실패와 복구

- submodule 초기화 실패: `.gitmodules`와 gitlink가 같은 commit에 있는지 확인하고 `git submodule update --init --recursive`를 다시 실행한다.
- 계약 버전 불일치: Core의 [호환성 문서](COMPATIBILITY.md)에 따라 소비 파일을 먼저 이전한다.
- gate 실패: gitlink를 갱신하지 않고 실패한 검사와 경로를 교정한다.
- Host Core 변경 감지: 변경을 폐기하지 말고 정확한 diff를 보존해 Maintainer 작업으로 이관한다.
- 키 노출 의심: 저장소 이력에 복제하지 말고 해당 키를 폐기·교체한 뒤 원격 접근을 재검증한다.

실제 삭제·복구·키 폐기는 각 소비 저장소 정책과 사용자 승인 경계를 따른다.
