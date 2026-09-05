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

Core 자체 검사(유지보수자와 Core 자체 검증용):

```powershell
python -B -m core_check --core-root <CORE_PATH> verify
python -B -m core_check --core-root <CORE_PATH> gate
```

소비 통합 검사(`host`가 사용할 수 있는 유일한 검증 진입점):

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

### Host의 Core 읽기 전용 실행

`host`는 Core를 라이브러리 입력으로만 사용한다. Core 안에서 명령을 실행하거나 Core를 현재 작업 디렉터리, cache, 임시 경로, 로그 경로 또는 출력 경로로 사용하지 않는다. 모든 쓰기 가능 경로는 소비 root 안에 명시한다. 이 저장소의 Python 참조 구현은 bytecode cache를 막기 위해 `-B`를 사용하지만, 상위 불변식은 특정 실행기가 아니라 Core와 쓰기 경계의 완전한 분리다.

Consumer는 wrapper·adapter·명시적 출력 인자·read-only mount/ACL 중 자기 환경에 맞는 통합 경계를 선택한다. 예를 들어 `<HOST_WORK_ROOT>`를 소비 root 안에 두고 Core 공개 CLI에는 읽기 전용 `--core-root`를, 산출물에는 `<HOST_WORK_ROOT>` 아래 경로를 전달할 수 있다. 출력 경로를 분리할 수 없는 도구는 Core에 실행하지 않는다. 공개 계약과 호환되는 최소 Consumer 입력을 따로 만들더라도 이를 Core 복사본이나 대체 배포물로 사용하지 않는다.

Host의 `context`, `gate`와 기능 사용은 계약 해석 전 소비 정책·부모 gitlink·Core 원시 상태 관찰, 부모 HEAD·index gitlink와 실행 Core HEAD 일치, Core clean을 하나의 결속 기준선으로 통과해야 한다. 순수 read-only `verify`는 dirty Core·어긋난 gitlink·잘못된 submodule 선언의 원인을 finding으로 진단할 수 있지만 기능 Runtime을 실행하지 않고 원시 상태의 전후 불변만 대조하며, 결과가 `1`이면 소비·완료 성공 근거가 아니다. Host gate는 Maintainer 소유의 Core 내부 회귀를 소비 완료의 필수 검사로 다시 실행하지 않는다. 별도의 격리된 read-only 진단을 실행할 수는 있지만 Maintainer 회귀 근거를 대신하지 않는다.

관찰 중 확인한 정책·gitlink·Core 변경이나 시작한 관찰의 불변성을 끝까지 확인하지 못한 오류는 후속 Maintainer 역할로 무시하지 않는다. 처음부터 Host 관찰을 시작할 수 없는 정상 Maintainer 경로와 이 실패를 구분한다.

현재 Git 기반 참조 검사는 HEAD와 index의 직접 일치, index 우회 flag, 실제 worktree bytes와 HEAD blob의 일치, tracked entry type·mode·symlink target, untracked·ignored 항목과 빈 directory를 확인한다. 따라서 Git의 줄바꿈 정규화로 `git status`가 clean이어도 실제 bytes가 다르면 실패한다. `filter`·`working-tree-encoding`·`ident` content 변환 attribute가 필요한 checkout은 hashing 전에 fail-closed한다. nested gitlink는 같은 기준으로 재귀 검사한다. 실행 뒤에는 실제 Git metadata directory만 제외한 tree의 내용·구조·지속 mtime과 HEAD·index·local config 지문을 대조한다. Git 기준이나 사후 불변을 증명할 수 없으면 검증은 실패다.

정책과 gate는 위반을 중단·탐지한다. 실제 쓰기 syscall 자체를 차단해야 하는 Host 실행 환경은 `core_path`를 read-only mount 또는 동등한 filesystem ACL로 제공해야 하며, 그 강제가 없으면 “물리적으로 쓰기 불가”라고 주장할 수 없다.

Core 내부 Python entry를 import한 뒤에 시작하는 관찰 기준선만으로는 import 직전·직후의 clean revision 교체를 증명할 수 없다. 범용 Host 완료를 주장하려면 Consumer가 소유한 Core 외부 launcher가 gitlink와 불변 checkout을 먼저 고정한 뒤 import하거나, 실행 전체를 immutable/read-only checkout에서 시작해야 한다. 현재 in-Core 참조 CLI만으로 이 부트스트랩 구간이 닫혔다고 주장하지 않는다.

## 6A. 선택 기능 `shared_data` v1

선택 데이터 Runtime의 공개 entry는 Core root와 `src`를 격리된 Python module 검색 경로의 맨 앞에 두는 아래 bootstrap이다. Consumer의 같은 이름 package가 Core module을 shadow하지 못하도록 `-I` 없이 bare module로 실행하지 않는다.

```powershell
$coreRoot = (Resolve-Path -LiteralPath '<CORE_PATH>').Path
$coreJson = ConvertTo-Json $coreRoot -Compress
$srcJson = ConvertTo-Json (Join-Path $coreRoot 'src') -Compress
$bootstrap = "import runpy,sys;sys.path[:0]=[$coreJson,$srcJson];runpy.run_module('experimental.shared_data',run_name='__main__',alter_sys=True)"
python -B -I -c $bootstrap info
```

`info`는 기능 버전, 공개 명령, operation과 request/result schema 경로만 반환하는 역할 비의존 정적 discovery다. 정상·예외 경로 모두에서 Core tree·Git 의미 상태의 전후 불변을 증명하고 쓰기 경로를 열지 않으므로 dirty Core에서도 실행할 수 있지만, 기능 소비·가용성·완료의 성공 근거는 아니다. Git 기준선을 증명할 수 없으면 실패한다. 실제 호출은 소비 root·Runtime storage root·보호 경계를 명시하고 request v1 JSON 하나를 stdin으로 보낸다.

따라서 Host gate가 `info` 선언 일치를 확인해도 `optional-features`는 `not_applicable`로 기록한다. Consumer 계약 검사는 요구 기능의 설치 구조·최소 버전을 별도로 확인하고, 실제 기능 완료 근거가 필요하면 아래 verified `invoke` 결과를 사용한다.

`invoke`는 계약 해석 전 소비 정책·부모 gitlink·Core 상태를 관찰하고 실행 중인 Core와 `--consumer-root`의 소비 계약을 대조한다. 계약 버전은 Core와 정확히 같아야 하고, Consumer가 `required_core_capabilities.shared_data`에 호출할 최소 버전을 선언해야 한다. storage root가 계약의 `core_path`와 겹치거나 Consumer 밖이면 `--write` 여부와 관계없이 Dispatcher 생성 전에 거부한다. 통과한 storage는 Consumer 상대 canonical 경로로만 Dispatcher에 전달하고, 계약의 `core_path`를 내부 보호 경로에 자동 합산해 각 storage 경로 해석 때 다시 검사한다. 계약에 선언된 보호 경로와 호출 보호 경로도 함께 합산되며, Host 역할은 부모 HEAD·index gitlink와 Core HEAD 일치, Core clean, 소비 정책·gitlink·Core의 전후 불변까지 통과해야 한다.

```powershell
$request = '{"operation":"source.list","arguments":{}}'
$request | python -B -I -c $bootstrap `
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

Host는 Core commit을 만들거나 Core 원격에 push하지 않으며 Core 안의 어떤 로컬 파일도 만들거나 바꾸지 않는다. Maintainer도 사용자 승인과 전체 게이트 없이 push하지 않는다.

## 8. 원격 권한과 자격 증명

- Maintainer clone은 승인된 쓰기 권한이 있는 원격 자격 증명을 사용할 수 있다.
- Host clone은 사용하는 원격 공급자가 지원하는 read-only 자격 증명·접근 제어를 사용한다.
- 같은 PC에서도 각 clone의 로컬 `core.sshCommand`로 서로 다른 키를 선택할 수 있다.
- 개인키, 토큰, `core.sshCommand`, 사용자별 키 경로는 저장소에 추적하지 않는다.
- 정책은 보안 경계가 아니다. 실제 push 허용·거부는 원격 권한으로 검증한다.

## 9. 실패와 복구

- submodule 초기화 실패: `.gitmodules`와 gitlink가 같은 commit에 있는지 확인하고 `git submodule update --init --recursive`를 다시 실행한다.
- 계약 버전 불일치: Core의 [호환성 문서](COMPATIBILITY.md)에 따라 소비 파일을 먼저 이전한다.
- gate 실패: gitlink를 갱신하지 않고 실패한 검사와 경로를 교정한다.
- Host Core 변경 감지: 변경을 폐기하지 말고 정확한 diff를 보존해 Maintainer 작업으로 이관한다.
- 자격 증명 노출 의심: 저장소 이력에 복제하지 말고 해당 자격 증명을 폐기·교체한 뒤 원격 접근을 재검증한다.

실제 삭제·복구·키 폐기는 각 소비 저장소 정책과 사용자 승인 경계를 따른다.
