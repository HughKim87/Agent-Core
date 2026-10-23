# 검증 수준과 완료 판정

- 목적: Core 자체 검증과 소비 통합 검증의 수준·게이트·보고 한계를 소유한다.
- 읽는 시점: 변경 전 검증을 설계하거나 완료를 판정·보고할 때.
- 책임: 에이전트가 실제 도달 수준을 기록하고 사용자가 최종 확인을 소유한다.
- 상태: 활성 정본. contract v2.
- 관련 권위: [Core 상시 정책](../PROJECT_RULES.md) §9, [호환성](COMPATIBILITY.md).

---

## 1. 검증 수준

| 수준 | 의미 |
|---|---|
| `generated` | 결과물을 만들었음 |
| `parsed` | 형식을 기계가 읽을 수 있음 |
| `structure-validated` | 선언·링크·schema·AST·경계 검사 통과 |
| `unit-tested` | 격리된 정상·결함 주입 검사 통과 |
| `integrated` | Core와 소비 구성요소를 연결한 gate 통과 |
| `self-operated` | 실제 작업에서 처음부터 끝까지 사용 |
| `cross-agent` | 다른 에이전트가 대화 없이 같은 상태를 복원 |
| `user-confirmed` | 사용자가 원하는 결과임을 확인 |

상위 이름이 하위 검사를 자동으로 포함하지 않는다. 실제 실행한 증거를 각각 기록한다.

기계 검사는 명시한 형식과 검사 사례의 결과를 증명한다. 길이·문체·표제·단어 일치 같은 휴리스틱은 검토 신호이며, 그것만으로 의미 위반이나 완료 실패를 확정하지 않는다. `verify`·`context`·`gate`는 성공 여부와 별도로 경고 진단을 보존한다. 구조 통과나 경고 부재는 자연어 의미 통과가 아니다. 자연어 의미는 원문·적용 조건·반례에 대한 검토로, 실제 동작은 대상 구현을 실행한 근거로 구분한다. 검사 안에서 재구현한 합성 행동 모델의 통과를 대상 Agent·Runtime의 동작 증거로 쓰지 않는다.

대상 구현이 생성한 출력을 골든 기대값으로 삼아 의미적 정확성의 검증 근거로 사용할 때는 명세·공식 벡터·수작업 계산·독립 참조 중 적합한 근거로 핵심 사례의 의미를 확인한다. 같은 구현의 출력과 일치한다는 사실만으로 정확성을 입증하지 않는다.

| 검증 대상 | 적합한 근거와 한계 |
|---|---|
| 규칙 route | 링크·유일성·fixture 구조와 기대값을 숨긴 콜드 의미 재현을 별도 판정 |
| 자연어 규칙 | 보장·적용·near-miss·owner의 독립 감사. 문장·제목·도메인 어휘 검사는 구조 또는 잔재 탐지 보조 |
| 입력·실행 경계 | 실제 production 경로의 정상·위반·near-miss와 거부 전후 부작용 확인. 정상 작업의 불필요한 중단·재승인도 대조 |
| schema | field·enum drift 대조와 type·범위·교차 field·실제 request 거부를 구분 |
| 완료·재개 | 수행·skip·실패·수행 불가와 검증한 bytes/snapshot을 보존. 추적 여부만으로 portable을 주장하지 않음 |
| 합성 운영 모델 | 명시된 가정의 일관성만 검사. Consumer의 구체 예산은 Consumer tests가 소유 |

### 경고의 문맥 검토와 자율 보완

경고는 오류도 내용 품질 통과도 아니다. Agent는 요청 결과에 관련된 경고의 원문과 적용되는 요구·승인·제약을 대조한다. 관련성 판단에 필요한 최소 조사부터 수행하며 보호 경계와 명시 예산을 유지한다. 검사 대상 밖의 결과나 경고가 없는 내용도 요청의 완료 조건에 맞춰 확인한다.

| 문맥 판정 | 행동과 완료 근거 |
|---|---|
| 표현·길이가 달라도 필요한 정보와 실행 대상·판정 조건이 충분함 | 내용을 유지하고 진행한다. 경고를 없애기 위한 축약·표제 교체나 재승인은 요구하지 않는다 |
| 요청 결과의 실제 누락·모호함·불필요한 이력 또는 이번 변경의 회귀가 확인됨 | 기존 승인 안의 가역적 보완을 스스로 수행하고 영향받은 내용과 검사를 재확인한다. 확인된 기준을 충족하면 경고가 남아도 진행할 수 있다 |
| 관련성·의미가 불명확함 | 안전한 조사로 판단을 좁힌다. 필수 보장이나 완료 판단을 바꾸는 중요한 불확실성이 남으면 그에 의존하는 행동·완료 주장만 보류한다. 필요한 정보·결정이 사용자에게만 있을 때 질문한다 |
| 승인 밖의 변경이 필요하거나 현재 결과와 무관한 기존 문제임 | 승인 밖 변경은 실행하지 않고 필요한 결정 또는 별도 개선을 보고한다. 현재 완료 조건을 충족한 독립 결과까지 보류하지 않는다 |

경고의 수·존재나 정규식 일치만으로 보류·재승인·완료를 판정하지 않는다. 확정된 안전·경로·역할·계약 위반과 명시 예산 실패는 이 절로 완화하지 않는다. 검사를 삭제하거나 임계값을 늘리고 필요한 정보를 버리는 방식으로 보완을 대신하지 않는다. 의미가 충분한 대체 표현의 선택은 허용된다.

판정 근거는 기존 검증·완료 응답·상태 중 재검토에 필요한 최소 위치에 요약할 수 있다. 별도 원장이나 모든 경고의 정형 보고서를 만들 필요는 없다. 기계 출력의 `review_guidance`는 이 절의 판단을 돕는 안내이며 Agent의 검토 실행·판정을 증명하지 않는다. 검사기는 경고를 자동 수정하거나 내용 품질의 통과로 승격하지 않는다.

## 2. 판정값

| 값 | 의미 | 필수 게이트 처리 |
|---|---|---|
| `pass` | 실행했고 통과 | 성공 후보 |
| `fail` | 실행했고 실패 | 전체 실패 |
| `not_run` | 선택된 검사를 실행하지 않음 | 필수 게이트면 전체 실패. 선택되지 않은 검사는 게이트로 기록하지 않음 |
| `not_applicable` | 이유가 있는 비해당 | 비실패 |

회귀 suite의 `evidence`는 대상, 원본 stdout/stderr·returncode와 `tests_run`, `executed`, `skipped`, `skip_reasons`, `failures`, `errors`, `expected_failures`, `unexpected_successes`, `status`를 보존한다. 선택 Runtime의 suite도 같은 판정을 사용한다. `executed`는 성공·실패·오류·expected failure·unexpected success 또는 non-skip subTest 결과가 관측된 test method 실행 수다. 같은 method의 여러 subTest는 method 수를 늘리지 않는다. `tests_run = executed + unexecuted_methods`이며 `skipped`는 method·subTest·fixture skip 사건의 합이다. 각 수는 `skipped_methods`, `skipped_subtests`, `fixture_skips`로 분리하고 non-skip subTest callback 수는 `subtests_executed`로 보존한다. skip 이전의 임의 assertion 수행 여부는 unittest 결과 callback으로 입증하지 않는다. 필수 Core 및 설치된 Runtime의 tests 디렉터리 부재는 Maintainer에서 `not_run`이다. 전부 skip이거나 빈 suite, 실행 불가·조기 종료로 결과를 확보하지 못한 경우는 `not_run`이며 pass가 아니다. 일부 skip이 있는 pass는 실제 수행된 검사에 한하며 skip 경계의 실증을 뜻하지 않는다. 수행 수치를 확보하지 못한 경우 알려지지 않은 수치를 0회 실행 증거로 꾸미지 않는다.

Maintainer wrapper는 원본 subprocess 출력과 표시용 tail을 별도로 보존한다. 전후 비교는 HEAD/index와 tracked·nonignored worktree bytes/type, 재귀 gitlink를 포함한 fingerprint를 사용하며 ignored 데이터나 실제 ACL의 불변까지 증명하지 않는다.

## 3. Core 자체 gate

Core 자체 gate가 선택된 작업에서는 소비 저장소 없이 다음을 검증한다.

- 런타임·layout preflight
- Core 역할·호환성 선언
- 문서·링크·JSON·Python AST·텍스트
- 규칙 route와 모듈 계층
- 회귀·결함 주입 테스트
- 실행 전후 Core tree 무부작용

Core 자체 gate 통과만으로 Host 사용 가능성이나 read-only push 거부를 주장하지 않는다.

## 4. 소비 통합 gate

Core 갱신 완료는 [소비 안내 §7](CONSUMER_GUIDE.md#7-core-버전-갱신)의 `main` 브랜치·`origin/main` 추적·실제 pull·revision 결속과 Core 자체 무결성·청결·실행 전후 불변으로 판정한다. 실제 Host gate도 실행하되 전체 소비 준비 판정과 별도로 보고한다. 현재 요청·이번 revision 영향과 무관한 기존 프로젝트 문서 오류는 같은 실제 입력의 이전·목표 Core 공개 검사 결과로 확인하고 Core 갱신을 차단하지 않는다. 새 회귀·분류/관련성 불명확·Core 안전 실패는 계속 차단한다. Host gate의 실패를 pass로 바꾸거나 소비 준비 완료로 주장하지 않는다. 기존 Host gate가 브랜치·원격 최신성을 자동 검사한다고 주장하지 않으며 고정 revision 복원·일회성 후보 검증은 최신화 완료와 구분한다.

[소비 안내 §7](CONSUMER_GUIDE.md#변경-영향에-따른-경로-선택)의 문서 갱신 조건을 충족하면 고정 Core의 공개 구조·링크 검사 한 번과 변경 의미에 필요한 검증을 근거로, 각 Consumer의 가벼운 사전 확인 뒤 실제 Host gate를 한 번 실행한다. 격리 후보 gate·별도 사전 전체 verify를 중복 실행하지 않으며, 실제 gate의 기존 판정·전후 불변과 브랜치·gitlink 완료 조건은 유지한다. 가벼운 사전 확인 통과는 전체 소비 적합성 통과가 아니다. 문서 경로가 아니면 후보와 실제 소비를 각각 검증한다.

소비 계약이나 연결 표면이 변경되어 소비 통합 gate를 선택한 작업에서는 `--consumer-root`를 지정한다. 이를 생략한 `verify`·`gate`는 Core 자체 검사일 뿐 Host 보호나 소비 완료의 근거가 아니다. `maintainer`는 Core 자체 gate와 아래 소비 검사를 함께 실행한다. `host` 소비 gate는 검증된 Core library의 구조·공개 계약을 읽기 전용으로 검사하되 Maintainer가 소유하는 Core 내부 회귀를 소비 완료의 필수 검사로 다시 실행하지 않는다. 별도의 격리된 read-only 진단은 허용되지만 Maintainer 근거를 대신하지 않는다.

Host의 순수 `verify`는 dirty Core나 어긋난 부모 gitlink를 읽기만 해 원인을 finding으로 보고할 수 있다. 이 경로는 선택 기능 Runtime을 실행하지 않고 유효성 판정 전의 부모 gitlink 원시 상태와 Core tree·revision·index가 진단 전후 동일함을 증명하며, 발견이 있으면 소비 성공이 아니라 진단 실패 상태를 반환한다. 역할·Consumer 입력·Runtime storage에 무관한 정적 metadata discovery도 같은 전후 불변을 증명하고 쓰기 가능 경로를 열지 않을 때만 clean 사전 조건의 near-miss이며 기능 소비·완료 근거가 아니다. `context`, `gate`와 실제 기능 실행은 clean 기준과 부모 HEAD·index gitlink 및 실행 Core HEAD 일치를 하나의 결속 기준선으로 먼저 통과해야 한다.

Host gate가 선택 기능의 `info`와 호환성 선언 일치를 읽더라도 해당 `optional-features` 단계는 `not_applicable`이며 기능 소비·가용성·완료의 `pass`로 승격하지 않는다. 요구 기능의 설치 구조와 버전은 Consumer 계약 검사가 별도로 판정하고, 실제 기능 사용은 verified Consumer 경계의 `invoke`로 검증한다.

- 소비 계약 버전·역할·상대경로
- 진입 포인터의 대상과 순서
- 소비 상태의 필수 정보·구조 검사와 길이 진단
- 소비 규칙 route
- `.gitmodules`의 Core path
- Host의 부모 HEAD·index gitlink object와 실행 Core HEAD 일치, 계약 해석 전 관찰 기준선 및 실행 전후 결속 기준선 불변. 관찰 도중 역할이 바뀌거나 관찰 완료에 실패하면 후속 역할로 차단을 우회하지 않음
- Core·consumer scope가 있는 context와 fingerprint
- Host 소비 실행 전 HEAD·index·tracked raw worktree bytes/type/mode와 untracked·ignored·추가 directory 청결. `git status`의 content 정규화 결과에 의존하지 않으며, nested gitlink에도 같은 기준을 재귀 적용하고 `filter`·`working-tree-encoding`·`ident` content 변환 attribute는 hashing 전에 거부
- 보호 경로를 제외한 소비 계약 표면의 무부작용
- 실제 Git metadata directory만 제외하고 submodule `.git` pointer·빈 directory·entry type·mode·symlink target·cache·ignored 파일과 지속 mtime을 포함한 실행 전후 Core tree 및 HEAD·index·local Git config 무부작용

기본 시작 문맥 20,000자는 축약·소유권 검토를 위한 진단 기준이며 자동 실패나 절단 조건이 아니다. 실제 실행 환경·작업 예산을 `context --budget` 또는 `gate --budget`으로 명시하면 그 양의 문자 한도는 실패 조건으로 적용하고 내용을 절단하지 않는다. 예산 준수는 필요한 정보를 버리거나 보호·완료 기준을 낮출 권한이 아니다. 경로·보호·역할·계약·필수 정보의 확정된 위반은 길이·표현 경고와 구분해 계속 실패 처리한다.

실제 Host checkout의 파일시스템 강제 read-only, 원격 자격 증명의 fetch·push 권한, Codex·Claude 행동은 별도 통합·실제 사용 검증이 소유한다.

## 5. 위험별 최소 수준

| 작업 | 최소 증거 |
|---|---|
| `quick` | `parsed` |
| `standard` | `structure-validated` |
| 의미가 유지되는 문구·설명 변경 | 대상 형식·링크 확인 + 요청 scope와 diff 대조 |
| 활성 Core 규칙 의미 변경 | 대상 구조·링크 + 변경 조건·반례 대조 + 상위 라우터가 선택한 규칙 거버넌스의 일반화·독립 감사 |
| 활성 route·trigger 의미 변경 | route 구조 + 관련 의도 fixture + 규칙 거버넌스의 독립 Agent 의미 재현. 의미가 유지되는 링크·서식 수정은 구조·링크 확인 |
| 실행 정책·검사 판정 변경 | 직접 영향받는 정상·오류·경계 검사 |
| 검증 도구 변경 | `unit-tested` + 정상·오류·수행 불가 경계 |
| Core release 후보 | Core gate + commit snapshot clean clone |
| 소비 연결 후보 | 소비 gate + 부모·submodule Git 상태 대조 |
| 범용 Host 사용 주장 | 서로 다른 실제 Host 2개 + `cross-agent` |

### 검증 선택 방법

1. 사용자가 요청한 결과와 완료 주장을 한 문장으로 정한다.
2. 실제 변경 경로와 영향을 받는 동작·계약만 식별한다.
3. 위 표에서 그 결과를 증명하는 가장 작은 증거를 선택한다.
4. 실행 중 새 위험 신호가 확인되면 관련 검사를 추가한다.
5. 추가 검사가 요청 범위·시간·산출물을 실질적으로 넓히면 실행 전에 이유와 범위를 보고한다.

검증 수준은 품질을 재현하기 위한 선택 방법이며 가능한 모든 검사를 누적하는 목록이 아니다. 전체 gate나 clean clone을 더 많이 실행했다는 사실만으로 단순 작업의 품질이 높아지지 않는다.

방법 선택·제한·검사 판정을 바꾸면 같은 결과·품질·안전 기준을 충족하는 정상 작업과 위반·near-miss를 함께 검증한다. 승인 안의 대체 방법, 필요한 인접 변경, 충돌 없는 독립 실행이 불필요한 승인·중단 없이 완료되는지 대조하고, 성공 조건 축소·보호 경계 우회는 계속 거부되는지 확인한다. 시간·질문 수·도구 호출 수는 개선 효과를 살피는 진단 정보이며 새로운 공통 고정 상한이 아니다. 합성 사례와 실제 Agent 행동의 증거 수준은 구분한다.

규칙 후보의 작성·검토와 활성화 완료를 구분한다. 필수 독립 감사나 의미 재현이 미실시이면 그 검증이 필요한 활성화·수용만 보류하고 후보 작성·구조 확인의 실제 결과를 보고할 수 있다. route 의미 재현은 변경된 선택 경계와 영향받는 조합·near-miss를 포함한 집합에 적용하며, 전체 라우터 영향 또는 영향 범위 불명확 시 전체 집합으로 확대한다.

## 6. 확대 보고 금지

- 합성 fixture는 `synthetic`으로 표시한다.
- 현재 checkout 통과를 commit snapshot 통과로 표현하지 않는다.
- 첫 Host 통과를 범용 Host 검증으로 표현하지 않는다.
- 정책상 금지를 실제 원격 권한 거부로 표현하지 않는다.
- 실행하지 않은 환경·Python·Agent 검사를 지원 범위로 선언하지 않는다.

## 7. 완료 보고

완료 보고는 다음을 포함한다.

1. 변경한 정확한 scope와 경로
2. 실행한 검사와 결과
3. 완료 주장에 필요하지만 실행하지 못한 검사와 이유
4. 현재 checkout·commit snapshot·실제 사용 중 어느 수준인지
5. 알려진 한계와 현재 계약에 남은 필수 검증. 남은 조건이 없으면 해당 범위의 종료를 명시

선택된 필수 검사 중 `fail` 또는 `not_run`이 있으면 그 검사가 증명하는 다음 단계로 전환하지 않는다.
