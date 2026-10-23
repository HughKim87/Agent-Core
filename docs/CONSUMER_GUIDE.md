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

현재 배포 Core revision의 별도 정본을 문서·선언에 만들지 않는다. 특정 검증 snapshot의 revision·hash는 [정보 소유 구조](INFORMATION_ARCHITECTURE.md#6-복제-금지)에 따라 검증 대상 식별 근거로 보존할 수 있다.

## 3. Core 연결

최초 연결은 §7의 격리된 후보 Consumer에서 시작한다. 그 후보 root에서 원하는 상대경로를 정해 Core 저장소 전체를 submodule로 추가한다.

Host가 SSH로 연결할 때는 최초 `submodule add` 전에 §8의 절차로 기존 read-only 인증을 선택한다. 아직 생성되지 않은 submodule에는 로컬 설정을 넣을 수 없으므로 최초 clone에 사용할 인증을 먼저 전달하고, 연결 후 해당 clone의 로컬 설정에 유지한다.

```powershell
git submodule add <AGENT_CORE_REMOTE> <CORE_PATH>
git submodule update --init --recursive
```

`CORE_PATH`는 저장소 안쪽의 상대경로여야 한다. 개인키·토큰·사용자별 절대경로를 저장소 파일에 기록하지 않는다. §4·5의 소비 입력과 `.gitmodules`·gitlink를 후보 부모 commit에 포함한 다음 §7의 후보 gate·실제 반영·반영 후 gate를 수행한다. 부모 HEAD에 gitlink가 없는 최초 연결 상태는 Host 소비 완료 상태가 아니다.

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

선택된 필수 검사가 `not_run`이면 그 완료 수준의 성공이 아니다. 길이·표현의 검토 경고만 있으면 성공 코드 `0`일 수 있으며 결과의 경고와 미평가 의미 범위를 함께 확인한다. 구조 통과가 내용의 충분성이나 실제 Agent 업무 성공을 뜻하지 않는다.

새 revision을 checkout하거나 gitlink만 stage한 상태의 Host gate는 revision 불일치로 실패한다. `verify`는 그 원인을 finding으로 보여줄 수 있지만 종료 코드 `1`을 후보 통과로 해석하지 않는다. 갱신 절차와 각 gate의 검증 대상은 §7을 따른다.

`context --rule`은 반복 지정할 수 있다. 기본 20,000자는 길이 검토 기준이며 초과만으로 실패하지 않는다. 실제 실행 환경·작업의 문자 한도를 정하려면 `context --budget 40000` 또는 `gate --budget 40000`처럼 양의 정수 예산을 명시한다. 명시 한도 초과는 절단 없이 거부한다. `context`의 문맥 구성 오류는 종료 코드 `2`, gate의 시작 문맥 단계 실패는 `1`이다. 동일 입력·선택에서 충분한 예산만 달라지면 내용·scope·fingerprint는 같다.

```powershell
python -B -m core_check --core-root <CORE_PATH> --consumer-root . context --rule core:rules/work-contract.md --rule core:rules/staged-work-design.md --budget 40000
```


### 상태 검사 진단

상태의 의미·필수 절·재개 원칙은 [현재 상태와 세션 인수인계](../rules/handoff.md)가 소유한다. `verify`의 `consumer-state` finding은 소비 상대 파일 경로와 확정 오류 또는 검토 경고의 조건을 제공한다. 제목·판정·첫 행동의 실제 위치를 확인할 수 있으면 메시지에 원문 행 번호를 표시한다. 누락된 절에는 존재하지 않는 행 번호를 붙이지 않는다.

`직전 게이트`는 바로 앞 판정 하나를 담는다. 이 절에 단위 검사 `pass`와 실제 사용 `not_run`을 함께 적으면 두 판정으로 인식한다. 실제 직전 판정은 그대로 두고, 별도 미검증은 `알려진 위험`에서 설명한다. 아직 검사하지 않았다면 직전 판정으로 `not_run`을 쓸 수 있으며 통과를 위해 `pass`로 바꾸지 않는다.

다음은 단위 검사와 실제 사용의 증거를 구별한 형식 예시다. 예시의 판정은 실제 프로젝트 검사 결과가 아니므로 자기 작업의 확인된 상태로 작성한다.

<!-- consumer-state-example -->
```markdown
# 소비 상태 예시

- 목적: 현재 작업의 재개 지점을 전달한다.
- 읽는 시점: Core 정책과 소비 정책을 읽은 뒤.
- 책임: 소비 작업 에이전트.
- 상태: 형식 설명용 예시.
- 관련 권위: 소비 정책의 상태 선언.
- handoff mode: `same-workspace`.

## 현재 단계

- 현재 작업: 단위 검사 이후 실제 사용 검증 준비.

## 직전 게이트

- `pass` — 선택한 단위 검사를 실행해 통과했다.

## 승인 상태

- 실제 사용 검증은 별도 작업 범위에서 진행한다.

## 차단

- 실제 사용 검증의 범위를 정해야 한다.

## 알려진 위험

- 실제 사용 검증은 `not_run`이며 단위 검사로 대신하지 않는다.

## 첫 다음 행동

1. 소비 정책의 승인 범위와 실제 사용 검증의 대상·판정 조건을 확인한다.
```

현재 기계 검사는 필수 절의 누락·중복, 판정 개수와 번호 행동 누락 같은 구조 오류를 확인한다. 상태 길이·제목·수치·행동 표현의 패턴은 문맥 검토 경고로 제공한다. 코드 fence·들여쓰기 예제·주석은 실제 제목·판정·행동 선언을 대신하지 않는다. 제목 패턴 일치나 형식 통과만으로 자연어 의미·Git 사실·실제 재개 가능성을 판정하지 않는다. 오류·경고를 보존한 공개 `verify` 결과를 원문에 대조하고 선택한 최종 gate를 실행한다. 메시지 문구는 내부 함수나 별도 상태 API의 공개 근거가 아니다.

### Host의 Core 읽기 전용 실행

`host`는 Core를 라이브러리 입력으로만 사용한다. Core 안에서 명령을 실행하거나 Core를 현재 작업 디렉터리, cache, 임시 경로, 로그 경로 또는 출력 경로로 사용하지 않는다. 프로젝트 보존·작업 경로는 상시 정책의 프로젝트 산출물 저장 경계를 따르고, 공개 Runtime에 전달하는 쓰기 경로는 소비 root 안에 명시한다. 승인된 외부 내보내기와 도구의 일시적 자원도 Core 경로를 사용할 수 없다. 이 저장소의 Python 참조 구현은 bytecode cache를 막기 위해 `-B`를 사용하지만, 상위 불변식은 특정 실행기가 아니라 Core와 쓰기 경계의 완전한 분리다.

Consumer는 wrapper·adapter·명시적 출력 인자·read-only mount/ACL 중 자기 환경에 맞는 통합 경계를 선택한다. 예를 들어 `<HOST_WORK_ROOT>`를 소비 root 안에 두고 Core 공개 CLI에는 읽기 전용 `--core-root`를, 산출물에는 `<HOST_WORK_ROOT>` 아래 경로를 전달할 수 있다. 출력 경로를 분리할 수 없는 도구는 Core에 실행하지 않는다. 공개 계약과 호환되는 최소 Consumer 입력을 따로 만들더라도 이를 Core 복사본이나 대체 배포물로 사용하지 않는다.

Host의 `context`, `gate`와 기능 사용은 계약 해석 전 소비 정책·부모 gitlink·Core 원시 상태 관찰, 부모 HEAD·index gitlink와 실행 Core HEAD 일치, Core clean을 하나의 결속 기준선으로 통과해야 한다. 순수 read-only `verify`는 dirty Core·어긋난 gitlink·잘못된 submodule 선언의 원인을 finding으로 진단할 수 있지만 기능 Runtime을 실행하지 않고 원시 상태의 전후 불변만 대조하며, 결과가 `1`이면 소비·완료 성공 근거가 아니다. Host gate는 Maintainer 소유의 Core 내부 회귀를 소비 완료의 필수 검사로 다시 실행하지 않는다. 별도의 격리된 read-only 진단을 실행할 수는 있지만 Maintainer 회귀 근거를 대신하지 않는다.

관찰 중 확인한 정책·gitlink·Core 변경이나 시작한 관찰의 불변성을 끝까지 확인하지 못한 오류는 후속 Maintainer 역할로 무시하지 않는다. 처음부터 Host 관찰을 시작할 수 없는 정상 Maintainer 경로와 이 실패를 구분한다.

검사 대상과 세부 판정은 [검증 계약 §4](VERIFICATION.md#4-소비-통합-gate)를 따른다. `git status`의 clean만으로 원시 bytes 일치를 증명할 수 없으며, Git 기준이나 실행 후 불변을 증명하지 못하면 실패다.

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

`info`의 정적 discovery 조건은 [호환성 §3A](COMPATIBILITY.md#3a-선택-runtime-공개-경계)를 따른다. dirty Core에서도 조회할 수 있지만 기능 소비·가용성·완료의 성공 근거는 아니다. 실제 호출은 소비 root·Runtime storage root·보호 경계를 명시하고 request v1 JSON 하나를 stdin으로 보낸다.

따라서 Host gate가 `info` 선언 일치를 확인해도 `optional-features`는 `not_applicable`로 기록한다. Consumer 계약 검사는 요구 기능의 설치 구조·최소 버전을 별도로 확인하고, 실제 기능 완료 근거가 필요하면 아래 verified `invoke` 결과를 사용한다.

`invoke` 전에 소비 계약 버전과 `required_core_capabilities.shared_data` 최소 버전을 맞추고 [호환성 §3A](COMPATIBILITY.md#3a-선택-runtime-공개-경계)의 verified Consumer 조건을 충족한다. storage는 Consumer 내부이며 Core·보호 경로와 겹치지 않아야 한다. 계약과 호출의 보호 경로는 함께 적용된다. Host는 §6의 clean·gitlink 결속·실행 전후 불변 조건도 충족해야 한다.

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
- 공개 호출의 입력·결과·쓰기 전제는 [호환성 선언 §3A](COMPATIBILITY.md#3a-선택-runtime-공개-경계)가 연결한 네 계약 문서, envelope·저장 payload 구조는 선언된 schema가 정본이다. `experimental.shared_data.*` 내부 Python import에는 의존하지 않는다.

## 7. Core 버전 갱신

### 후보와 실제 소비 반영

이 절의 fetch·checkout은 사용자가 승인한 소비 배포이며, [Core 정책 §8](../PROJECT_RULES.md#8-core-불변)과 [변경 통제 §3](../rules/core-change-control.md#3-core-변경의-정의)의 범위에서 수행한다. Core 소비·검증 실행을 멈춘 상태에서 revision을 맞춘 뒤 새 기준선으로 소비 gate를 확인한다. Core 파일을 직접 편집하거나 가변 산출물을 만드는 일반 Host 작업과 구별한다.

Host 소비 완료에는 부모 HEAD·index gitlink와 실행 Core HEAD의 일치가 필요하다. 따라서 실제 소비 저장소에서 새 Core를 checkout한 뒤 부모 commit 전에 gate를 통과시키려는 순서는 성립하지 않는다. stage만 추가해도 부모 HEAD와 index가 달라 실패한다. 아래 절차는 검증 대상인 후보 부모 snapshot을 먼저 만들며, 기존 gate의 결속 조건을 유지한다.

### 변경 영향에 따른 경로 선택

문서 갱신의 조건·실패 경계는 [Core 변경 통제](../rules/core-change-control.md#5-조건과-행동)를 따른다. 고정 목표 Core는 Maintainer에서 공개 구조·링크 검사를 한 번 수행하고 변경 의미에 필요한 감사·검증을 완료한다. 각 Consumer의 `core_path`·진입·정책·상태·규칙·요구 기능을 실제 입력으로 유지하며 가벼운 사전 확인 뒤 실제 `main` pull·승인된 부모 gitlink 반영·Core 무결성·브랜치/포인터 결속으로 Core 갱신을 판정하고 실제 Host gate는 별도로 기록한다. 이 경우 다음 일반 절차의 2~4번인 임시 Consumer 복제·후보 commit·후보 gate와 별도 사전 전체 verify는 생략한다. 사전 확인은 전체 소비 적합성을 증명하지 않으며 소비 준비 완료는 실제 gate가 판정한다.

기존 `docs/*.md`·`rules/*.md` 본문 수정이라도 호환성·문서 역할/계층 선언이나 route가 달라지면 일반 경로다. Core 상위 정책·실행 코드·스킬·schema·속성·파일 추가/삭제/이동·종류/모드 변경도 일반 경로다. 문서 확장자만 검사해 문서 경로로 분류하지 않는다. 원격·배포 계약·Core 안전 경계의 변경은 적용 전후 상태를 구분해 중단·재계획한다. 현재 요청·이번 revision 영향과 무관한 프로젝트 문서 오류는 동일 실제 입력의 이전·목표 Core 공개 검사 결과를 비교해 확인하고, Core 갱신을 계속하며 Host 실패를 별도로 보고한다. 이 비교는 문서 실패 때만 추가한다. 새 회귀·관련성 불명확·Core 안전 검사 실패는 계속 차단하며 자동 복구하지 않는다.

### 일반 갱신 절차

1. 각 실제 Core의 승인된 `origin/main`에서 조회·fetch한 객체를 후보 revision으로 고정하고, Maintainer의 검증 근거와 호환성을 확인한다. 로컬 Maintainer에만 있는 commit을 최신 원격 대신 사용하지 않는다. 반영할 소비 입력·Git 쓰기·임시 자원의 범위를 정하고 실제 소비 저장소는 마지막 검증 상태에 둔다. 무관한 변경을 임의로 삭제하거나 commit하지 않는다.
2. 승인된 임시 공간에 고정한 소비 부모 snapshot의 별도 clone과 전체 Core submodule을 준비한다. 최초 연결이면 §3~5의 승인된 입력을 이 후보에서 구성한다. 미커밋 소비 입력을 반영하기로 했다면 정확한 경로와 bytes를 후보에 포함한다. 보호 자료를 읽거나 복제할 권한은 이 절차에서 생기지 않는다.
3. 후보 Core에서 검증된 revision을 fetch·checkout한다. §10의 공개 스킬 목록·native 등록 대조로 신규 진입과 필요한 이전 파일을 판정한다. 후보 부모에서 변경된 gitlink·소비 계약·승인된 native 진입 파일만 검토·commit한다. 이 commit은 검사할 입력의 고정점이며 소비 완료나 배포 승인 근거가 아니다. 새 Core commit을 Host에서 만드는 절차도 아니다.
4. 후보의 부모 HEAD·index·Core가 모두 새 revision을 가리키는 상태에서 §6의 Host 소비 gate를 실행한다. 후보의 정책·진입·상태·route·기능 요구는 실제 반영할 입력과 같아야 한다. 유효한 가짜 상태로 바꾸어 통과시키지 않는다. 실패하면 위 경로 선택의 기존 프로젝트 문서 오류인지 판정한다. 그 외 실패는 실제 소비 저장소를 이전 상태에 유지하고 후보 원인을 해결한다.
5. 통과한 후보와 실제 반영할 입력을 다시 대조한다. 실제 부모·입력이 준비 이후 달라졌으면 영향받은 후보 근거를 다시 검증한다. 각 실제 `core_path` 저장소의 `main`에서 `origin main`을 fast-forward pull한다. pull 뒤 revision이 후보와 달라지면 부모 gitlink 갱신과 소비 실행을 보류하고 바뀐 revision의 후보를 다시 검증한다. 실제 Core를 후보의 detached 상태 그대로 복제해 종료하지 않는다. 승인된 소비 작업에서 검증한 gitlink와 소비 파일만 실제 부모 commit에 반영한다. 후보 commit을 그대로 반영할지 동일 변경을 별도 commit으로 만들지는 Consumer가 정한다.
6. 실제 Core의 브랜치가 `main`이고 upstream이 `origin/main`인지 확인한다. HEAD·`main`·pull로 확인한 `origin/main`·검증한 revision·부모 HEAD/index gitlink의 일치와 Core 청결·무결성·불변으로 Core 갱신을 보고하고 §6의 실제 Host gate 결과를 구분해 기록한다. 전체 소비 완료에는 Host gate 통과도 필요하다. `status --short --branch`, pull 결과와 검증한 revision을 근거에 포함한다. 후보 gate 통과만으로 실제 환경의 결과를 대신하지 않는다. Core 안전 실패는 후속 적용을 중단하고 §9의 승인된 복구 경로를 따른다.

기존 연결을 갱신하는 격리된 일회성 후보에서만 다음 detached checkout 순서를 사용할 수 있다. `CONSUMER_SNAPSHOT`과 `VERIFIED_CORE_COMMIT`은 사전에 확인한 고정 객체이며, 후자는 실제 Core의 승인된 `origin/main`에서 받은 객체여야 한다. 경로·Git 쓰기·정리 범위는 소비 작업에서 정한다. 아래 `git add` 예시는 스킬 목록 대조 후 gitlink만 바뀌는 경우다. 계약 이전이나 신규 스킬 등록이 필요하면 승인된 소비 파일·native 진입도 명시적으로 포함한다.

```powershell
git clone --no-checkout <CONSUMER_SOURCE> <CANDIDATE_ROOT>
git -C <CANDIDATE_ROOT> checkout --detach <CONSUMER_SNAPSHOT>
git -C <CANDIDATE_ROOT> submodule update --init --recursive
git -C <CANDIDATE_ROOT>/<CORE_PATH> fetch origin <VERIFIED_CORE_COMMIT>
git -C <CANDIDATE_ROOT>/<CORE_PATH> checkout --detach <VERIFIED_CORE_COMMIT>
git -C <CANDIDATE_ROOT> add -- <CORE_PATH>
git -C <CANDIDATE_ROOT> commit -m "Validate Core update candidate"
```

그다음 후보 root를 작업 디렉터리로 하고 §6의 Python 검색 경로와 `--consumer-root .`를 사용해 gate를 실행한다. 임시 작업·출력은 후보 Consumer가 소유하며 Core 안에 만들지 않는다. 후보 생성·commit 권한이나 필요한 입력이 없으면 검증은 `not_run`이다. `verify`의 불일치 finding 무시, Host 역할 변경, 내부 helper 호출로 gate를 우회하지 않는다.

후보 clone은 연결·갱신을 위한 한시 검증 자원이며 Core 배포 사본이나 상시 Runtime으로 유지하지 않는다. 종료 시 승인된 정확한 임시 대상만 정리한다. 일반 작업에 후보 clone을 요구하지 않는다. 실제 filesystem read-only 강제와 import 이전 경계의 한계는 §6을 따른다.

Host의 Core 파일 교체는 위의 승인된 revision 배포에 한정한다. 일반 소비·검증 실행에서는 Core에 직접·간접 쓰기를 하지 않으며, Core 내용의 임의 편집·새 Core commit·Core 원격 push는 허용하지 않는다. Maintainer의 push에는 별도 사용자 승인과 해당 후보에 선택된 필수 검증의 통과가 필요하다. 전체 회귀·commit snapshot clean clone은 release·packaging·재현성 등 실제 주장에 따라 [검증 계약](VERIFICATION.md#5-위험별-최소-수준)에서 선택한다.

### 실제 프로젝트의 main 갱신과 완료 확인

실제 Core에서는 원격 대상·로컬 변경·로컬 고유 commit·현재 브랜치·`main` 및 upstream을 먼저 확인하고 다음 순서로 갱신한다. 명령이 실패하면 후속 반영을 진행하지 않는다. `main`이 없으면 확인한 `origin/main`에서 `git switch --track -c main origin/main`으로 구성할 수 있다. 다른 upstream·분기 이력·인증 실패는 기존 이력과 설정을 보존해 보고하며 reset·강제 checkout·로컬 대체 원본으로 우회하지 않는다.

```powershell
git -C <CONSUMER_ROOT>/<CORE_PATH> switch main
git -C <CONSUMER_ROOT>/<CORE_PATH> pull --ff-only --no-rebase --no-tags --no-recurse-submodules origin main
```

pull 결과가 후보와 같은 revision인지 확인하고 승인된 부모 commit 반영과 실제 Host gate를 완료한 뒤 아래 출력을 대조한다. `symbolic-ref`는 성공하며 `main`을 반환해야 하고, upstream은 `origin/main`이어야 한다. 나머지 객체 ID는 검증한 revision과 모두 같아야 한다. `status --short --branch`는 `main...origin/main`의 청결 상태여야 한다. commit ID만 같거나 소비 gate만 통과한 detached HEAD는 최신화 완료가 아니다. 고정 revision 복원·일반 clone은 이 최신화 완료와 구분한다.

```powershell
git -C <CONSUMER_ROOT>/<CORE_PATH> symbolic-ref --short HEAD
git -C <CONSUMER_ROOT>/<CORE_PATH> rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git -C <CONSUMER_ROOT>/<CORE_PATH> rev-parse HEAD refs/heads/main refs/remotes/origin/main
git -C <CONSUMER_ROOT>/<CORE_PATH> status --short --branch
git -C <CONSUMER_ROOT> ls-tree HEAD -- <CORE_PATH>
git -C <CONSUMER_ROOT> ls-files --stage -- <CORE_PATH>
```

## 8. 원격 권한과 자격 증명

- Maintainer clone은 승인된 쓰기 권한이 있는 원격 자격 증명을 사용할 수 있다.
- Host clone은 사용하는 원격 공급자가 지원하는 read-only 자격 증명·접근 제어를 사용한다.
- 같은 PC에서도 각 clone의 로컬 `core.sshCommand`로 서로 다른 키를 선택할 수 있다.
- 개인키, 토큰, `core.sshCommand`, 사용자별 키 경로는 저장소에 추적하지 않는다.
- 정책은 보안 경계가 아니다. 실제 push 허용·거부는 원격 권한으로 검증한다.

### 기존 read-only SSH 인증으로 최초 연결

다음은 §3의 최초 연결 명령에 기존 SSH 인증을 전달하는 PowerShell 예시다. 후보 Consumer root에서 실행하며, placeholder는 승인된 기존 키 경로, SSH 원격, Core 상대경로로 대체한다. 키를 새로 만들거나 권한을 확대하는 예시가 아니다. HTTPS 등 다른 인증 방식을 쓰는 Consumer에 SSH를 강제하지 않는다.

기존 키가 지정되었다면 사용자에게 경로를 다시 묻기 전에 승인 범위 안의 로컬 연결 설정과 키 이름을 확인할 수 있다. read-only 여부를 확인할 때는 개인 키 내용을 읽지 않고 승인된 공개키와 원격 권한 metadata를 대조한다. 로컬 파일 이름이나 SSH 연결 성공만으로 원격 쓰기 거부를 입증했다고 하지 않는다. 이 확인은 보호 데이터 접근이나 원격 변경에 대한 승인을 대신하지 않는다.

```powershell
$readOnlySshCommand = 'ssh -i "<READ_ONLY_KEY_PATH>" -o IdentitiesOnly=yes -o BatchMode=yes'
$hadSshCommand = Test-Path Env:GIT_SSH_COMMAND
$previousSshCommand = $env:GIT_SSH_COMMAND
try {
    $env:GIT_SSH_COMMAND = $readOnlySshCommand
    git submodule add <AGENT_CORE_REMOTE> <CORE_PATH>
    if ($LASTEXITCODE -ne 0) { throw 'Core submodule add failed' }
    git submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw 'Core submodule initialization failed' }
    git -C <CORE_PATH> config --local core.sshCommand $readOnlySshCommand
    if ($LASTEXITCODE -ne 0) { throw 'Core local SSH configuration failed' }
}
finally {
    if ($hadSshCommand) {
        $env:GIT_SSH_COMMAND = $previousSshCommand
    }
    else {
        Remove-Item Env:GIT_SSH_COMMAND -ErrorAction SilentlyContinue
    }
}
```

호출 구간의 환경 설정은 성공·실패 모두에서 복원한다. 선택한 SSH 명령은 submodule의 로컬 Git 설정에만 남기며 `.gitmodules`, 정책, 상태, 보고서에는 실제 키 경로나 명령 값을 기록하지 않는다. 로컬 설정은 다른 clone으로 전달되지 않으므로 각 실행 환경에서 소비 검증 전에 별도로 제공한다. `GIT_SSH_COMMAND` 등 환경 override가 있으면 로컬 Git 설정보다 우선할 수 있으므로 실제 실행에서 선택되는 인증도 확인한다. 이 예시는 인증 선택만 다루며 후보 commit·gate·실제 반영은 §7을 그대로 따른다.

## 9. 실패와 복구

- submodule 초기화 실패: `.gitmodules`와 gitlink가 같은 commit에 있는지 확인하고 `git submodule update --init --recursive`를 다시 실행한다.
- 계약 버전 불일치: Core의 [호환성 문서](COMPATIBILITY.md)에 따라 소비 파일을 먼저 이전한다.
- 후보 gate 실패: 실제 소비 부모를 갱신하지 않고 후보의 실패한 검사와 입력을 교정한다.
- 반영 후 gate 실패: 소비·게시를 중단한다. 현재 사용자 변경을 보존하고, 정확한 복구가 승인된 경우 마지막 검증된 부모 gitlink·소비 입력과 Core checkout을 함께 복원해 소비 gate를 확인한다. 후보 검증 통과를 실제 반영 성공으로 바꾸지 않는다.
- Host Core 변경 감지: 변경을 폐기하지 말고 정확한 diff를 보존해 Maintainer 작업으로 이관한다.
- 자격 증명 노출 의심: 저장소 이력에 복제하지 말고 해당 자격 증명을 폐기·교체한 뒤 원격 접근을 재검증한다.

실제 삭제·복구·키 폐기는 각 소비 저장소 정책과 사용자 승인 경계를 따른다.

## 10. 공통 스킬 진입 구성

이 절은 [공개 스킬 계약](COMPATIBILITY.md#3b-공통-workflow-진입-계약)의 배포 자산을 Consumer native 포인터로 구성하는 절차다. 배포 자산이 있어도 설치와 실제 도구 사용을 완료한 것은 아니다. Agent가 초기 구성·Core 갱신을 수행할 때 공개 목록을 발견·대조하고 승인된 범위의 native 진입을 등록한다. 파일 감시·백그라운드 자동 설치나 스킬 본문 실행을 뜻하지 않는다.

### 10.1 대상과 설치 범위

1. 설치할 Consumer root와 그 계약의 실제 `core_path`, 사용할 Core revision, native 진입의 정확한 경로를 확인한다. 설치가 현재 승인 범위에 포함되어야 하며 새 환경·자격 증명·패키지를 추가하지 않는다.
2. 선택한 revision의 §3B 공개 workflow 표와 설치 목록을 읽고 `project` 항목만 등록한다. `common`·`internal`·미분류 항목은 프로젝트 native 등록에서 제외한다. 선택된 항목의 이름·공통 진입·양 도구 템플릿·호출 정책과 실제 파일을 대조한다. 현재 항목 수로 목록을 고정하거나 SOURCES.json·재귀 SKILL.md 탐색을 배포 목록으로 사용하지 않는다. 도구 선택과 등록 위임은 §10.4를 따른다.
3. 진입 파일과 부모 경로의 실제 해석이 해당 Consumer 내부에 있고 Core·보호 경로와 겹치지 않는지 확인한다. 루트 정책 포인터와 state 경로는 그대로 유지한다.
4. 같은 이름의 개인·프로젝트 설치가 있으면 실제 선택 출처와 내용을 대조한다. 기존 파일·디렉터리는 자동 덮어쓰기·삭제·이동하지 않는다. 교체가 필요하면 고유 내용·복구·정확한 처분 범위를 확인한다. 두 도구의 동명 우선순위를 같다고 가정하지 않는다.

신규 Consumer 구성 전에 setup 스킬을 사용할 때는 사용자가 선택한 Core의 WORKFLOW 진입을 명시적으로 읽고 연결된 실행 정본을 사용할 수 있다. 아직 없는 소비 계약이나 native 진입을 먼저 요구하지 않는다. 이는 설치 완료나 일반 프로젝트 생성 요청에 대한 자동 호출을 뜻하지 않는다.

### 10.2 얇은 포인터 구체화

공개 표 중 설치 목록에서 `project`로 분류된 각 스킬에 대해 다음 출력만 승인된 Consumer 안에 만든다. Core 본문은 복사하지 않으며 symlink·junction·새 설치 CLI는 요구하지 않는다.

| 도구 | 입력 | Consumer 출력 |
|---|---|---|
| Codex | 해당 `codex/SKILL.md.in` | `.agents/skills/<name>/SKILL.md` |
| Codex | 해당 `codex/agents/openai.yaml` | `.agents/skills/<name>/agents/openai.yaml` |
| Claude Code | 해당 `claude/SKILL.md.in` | `.claude/skills/<name>/SKILL.md` |

`{{WORKFLOW_LINK}}`만 native `SKILL.md`의 부모에서 **선택한 Core의 해당 공통 본문**까지 가는 상대경로로 치환한다. 경로 구분자는 `/`로 표현하고 공백·괄호·비ASCII 등 URI 특수 문자는 percent-encoding한다. 개인 절대경로나 고정 `core/` 이름을 삽입하지 않는다. `../`는 여기서 navigation 링크의 일부이며 소비 계약의 root 내부 상대경로 선언과 다른 유형이다. 해석한 링크의 최종 파일은 계약의 Core root와 정확한 workflow owner 안에 있어야 한다.

native 파일에는 discovery 메타데이터와 공통 진입 포인터만 남긴다. `WORKFLOW.md`가 선택한 실행 본문과 그 상대 참고 자료로 이어지는 경로를 확인한다. 실제 실행 본문 위치는 선택한 revision의 각 `WORKFLOW.md`에서 확인한다. 보존 원본 트리·내용·줄바꿈은 SOURCES.json 식별과 동일하게 유지하고, native 어댑터만 UTF-8/LF로 구체화한다. 사용자 승인 개정을 Core 일반 기본값에 맞춘 임의 수정과 혼동하지 않으며 보존 원본을 개정 본문과 동시에 적용하지 않는다. 각 제품의 명시적 native 호출을 실행 본문의 해당 스킬 직접 호출로 연결한다. Core revision은 부모 gitlink가 소유하며 치환되지 않은 토큰이나 잘못된 경로는 연결 성공이 아니다.

### 10.3 연결·이전 검증

- 양쪽 native frontmatter와 Codex 메타데이터를 해당 도구가 실제 수용하는지 확인한다. 텍스트 구조 검사는 제품 parser의 실행을 대신하지 않는다.
- 각 도구에서 선택된 출처와 native→WORKFLOW→실행 본문의 경로·내용이 같은지 확인한다. 참고 자료는 실행 본문 기준으로 읽고 current가 선택됐으면 source로 대체하지 않는다. 실행 본문에 도달할 수 없으면 과거 절차로 대신하지 않는다. 개정 전 제품 검증을 개정 후 행동 검증으로 재사용하지 않는다.
- 일반 종료 발언·인수인계 요청·프로젝트 생성 요청·스킬 수정 요청에서 직접 호출 전용 스킬이 자동 실행되지 않는지, 사용자의 명시적 스킬 선택에서는 지정 정책을 따르는지 별도로 관측한다.
- 비표준·중첩·공백 포함 `core_path`에서 상대 링크를 확인한다. 파일 navigation 합성 예제와 실제 새 도구 세션 검증을 구분한다.
- Host 실행과 산출물은 기존 소비·저장 경계와 실행 전후 Core 불변을 지킨다. 실제 상태·검증 출력은 Consumer가 소유한다.

Core gitlink 갱신 시 원본 식별·참고 자료·진입 계약·호출 메타데이터를 대조하고 필요한 포인터 갱신을 같은 이전 범위에 포함한다. 원본 문제는 근거와 영향으로 보고할 수 있지만 이를 이유로 임의 수정하거나 내용 검열을 새 배포 게이트로 추가하지 않는다. 같은 계약의 원본이 정상 연결되고 실제 선택·참조가 확인되기 전에는 기존 개인 설치의 이전을 완료로 선언하거나 원본을 제거하지 않는다.

공식 형식·발견 경로 근거는 [Codex 스킬 문서](https://learn.chatgpt.com/docs/build-skills), [Claude Code 스킬 문서](https://code.claude.com/docs/en/skills)다. 이 텍스트 계약은 로컬 Codex·Claude Code의 프로젝트 진입을 대상으로 한다. 다른 웹·클라우드·계정 동기화·플러그인 배포를 자동 지원으로 확대하지 않으며 실제 version·호출·결과에 맞춰 검증 수준을 보고한다.


### 10.4 초기 구성·revision 갱신의 등록 대조

대상 도구는 Consumer의 기존 명시적 선택·제외와 이번 작업 범위를 따른다. 선택을 확정할 근거가 없으면 설치 대상 도구를 확인한다. setup-agent-core-project로 신규 구성하는 경우에는 그 스킬이 소유한 도구 선택 기본값을 적용하며, 이를 모든 Consumer의 기본값으로 확대하지 않는다. 스킬 등록을 포함하도록 위임된 Core 갱신에서는 선택한 도구의 신규 공개 진입을 추가하며 파일마다 재승인을 요구하지 않는다. Core revision만 갱신하도록 지정된 경우에는 스킬 차이를 보고하고 등록은 수행하지 않는다.

초기 구성에서는 native 진입을 초기 소비 snapshot에 포함한다. revision 갱신에서는 §7의 후보 입력을 고정하기 전에 선택한 새 Core의 공개 목록과 Consumer 등록을 대조하고, 다음 처분을 실제 반영할 파일 범위에 포함한다. 도구 선택·갱신 시 등록 유지·제외는 Consumer의 기존 선언 또는 이번 지시를 사용하며 새 Core 전역 설정·Consumer schema 필드를 만들지 않는다.

| 대조 결과 | 처리 |
|---|---|
| 공개 항목은 있고 선택한 도구의 진입이 없음 | 등록이 승인된 범위이면 §10.2로 신규 파일을 만든다. 기존 디렉터리 안의 동명 파일도 먼저 대조하며 사용자 자료를 덮어쓰지 않는다. |
| 진입·메타데이터·링크가 동일 | 쓰지 않고 기존 등록을 재사용한다. 재실행으로 중복 폴더·다른 이름의 스킬을 만들지 않는다. |
| 진입이 있으나 내용·호출 정책·선택 공급자가 다름 | 정확한 차이와 영향, 필요한 이전 파일을 보고한다. 변경이 승인된 범위에서만 갱신하며 수동 수정이나 다른 공급자의 파일을 자동 교체하지 않는다. |
| 기존 등록의 공급자가 새 공개 목록에서 사라짐 | stale 등록으로 보고한다. 제거·개명은 정확한 대상 승인을 따른다. |
| 사용자가 도구·스킬 설치를 제외함 | 제외를 유지하고 미등록을 설치 성공이나 오류로 포장하지 않는다. |

추가한 진입의 상대 URI·미치환 토큰 부재·frontmatter·Codex 메타데이터·호출 정책과 WORKFLOW→실행 본문→참고자료 연결을 검사한다. 개인/다른 공급자와의 충돌은 프로젝트 파일 검사만으로 해결됐다고 하지 않는다. 실제 제품에서 선택한 경로와 직접 호출을 확인한 범위만 보고하고, 설치되지 않은 제품·로그인 차단·직접 입력 미검증은 구조 검사와 분리한다. 스킬을 등록하는 작업 자체가 등록된 스킬의 업무 실행을 허용하지 않는다.

설치 산출물은 Consumer가 소유하며 Host의 Core tree는 전후 불변이어야 한다. Core의 공개 목록을 늘리면 배포 자산·호환성·관련 검사도 함께 맞춘다. 이 절차는 공개 목록을 가진 Core 스킬의 프로젝트 등록 계약이며 extension의 임의 폴더를 등록 대상으로 승격하지 않는다. extension도 자동 발견하려면 해당 extension의 공개 배포 목록·도구별 진입 계약과 연결·갱신 소유자가 먼저 있어야 한다.

## 11. PC 공통 스킬 설치

Core 연결 프로젝트에서 `install-common-skills`를 요청하면 공개 설치 목록의 `common` 항목만 사용자의 개인용 위치에 설치·갱신한다. §10의 프로젝트 포인터 등록과 별도 절차다. 프로젝트 구성·Core 갱신·스킬 제작만으로 개인 설치를 자동 실행하지 않는다. 사용할 제품과 실제 사용자 스킬 root를 확인하며 이 설치기 자체와 기존 프로젝트 스킬은 공통 설치 대상이 아니다.

실행 본문과 [관리 도구](../skills/install-common-skills/current/scripts/manage_common_skills.py)가 설치 계획·실행을 소유한다. 읽기 전용 계획을 만들고 정확한 `plan_id`와 대상·범위를 대조한 후 승인된 설치 요청 안에서 적용한다. 새 패키지를 준비·검증한 뒤 구버전을 교체하고 관리 파일만 정리한다. 사용자 수정·동명 공급자·영수증 이상·미등록 파일은 충돌로 보존하며 다른 정상 항목만 처리할 수 있다. 더 최신인 설치본은 내리지 않고, 공개 목록에서 사라진 이름을 자동 삭제하지 않는다. 분류·개명·폐기에 따른 기존 설치 이전은 별도 정확한 범위를 확인한다.

개인 설치본은 선택한 프로젝트 Core가 없어도 동작하는 패키지다. 프로젝트 한 곳의 Core 갱신이 다른 PC 설치본을 자동 갱신하지 않으며 스킬 버전과 파일 해시로 명시적 재실행 때 비교한다. 재실행의 정상 동일 상태는 no-op이다. 설치 root가 Core·프로젝트 native·보호 경로와 겹치지 않게 하고, Host에서는 읽기 전용 기준과 전후 Core 불변을 증명한다. 설치 영수증과 실제 설치본은 사용자 환경이 소유하며 Core나 Consumer에 개인 절대경로·설치 상태 정본을 저장하지 않는다.

검증은 설치 파일·영수증·패키지 내부 참고자료와 실제 제품의 발견·선택을 구분한다. 모의 설치나 파일 존재만으로 제품 호출 성공을 주장하지 않는다. 개인 설치가 완료돼도 분석 스킬의 업무 실행이나 Core 반영은 승인되지 않는다.
