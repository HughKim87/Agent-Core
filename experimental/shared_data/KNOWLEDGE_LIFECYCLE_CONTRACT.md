# 지식 유형·승인 기반 Lifecycle 계약

- 목적: 소비 저장소가 소유하는 출처·단일 지식 주장·결정을 불변 record로 보존하고 현재 채택·검토·대체 상태를 승인 근거가 있는 event로 추적한다.
- 읽는 시점: L7 `source`·`knowledge`·`decision` 또는 lifecycle event·snapshot을 구현·검증할 때.
- 책임: `knowledge.py`가 지식 의미·source 참조 무결성, `lifecycle.py`가 전이·승인·projection, 이 디렉터리의 payload schema가 저장 구조를 소유한다.
- 상태: L7 구현 완료. `shared_data` v1 공개 CLI·schema가 제공하는 `available` 계약.
- 관련 권위: [공통 Record·저장 기반](RECORD_STORAGE_CONTRACT.md), [Kernel 범위](../../docs/KERNEL_SCOPE.md), [계층과 공개 경계](../../docs/ARCHITECTURE.md).

---

## 1. 격리와 저장 소유권

- 외부 소비자는 `optional_capabilities.shared_data` v1의 `info`·`invoke` 명령과 선언된 schema에만 의존한다. 내부 Python 모듈은 공개 API가 아니다.
- 호출자는 `RecordStore`의 소비 root·storage root·보호 경로·쓰기 활성화를 명시한다. Core 저장소에는 Runtime 데이터를 만들지 않는다.
- `KnowledgeService`와 `LifecycleService`는 호출자가 구성한 같은 store를 사용한다. `create_knowledge_store`는 이 계약의 고정 type·stream allowlist만 편의상 구성한다.
- 실제 회귀는 격리된 임시 소비 root에서만 수행한다. 보호 경로의 존재 확인·열거·읽기는 하지 않는다.
- 저장 record를 삭제·이동하거나 기존 source·knowledge·decision payload를 update하는 API는 제공하지 않는다.

## 2. 불변 지식 유형

| 유형 | 소유 정보 | 핵심 불변식 |
|---|---|---|
| `source` | 종류·locator·관찰 시각·확인 상태·증거 역할·version/hash | 원문을 복제하지 않고 로컬 bytes만 명시적으로 hash 검증 |
| `knowledge` | 한 줄 주장 하나·분류·scope·source 참조·검증 상태 | source 1개 이상, unavailable source 거부, candidate/verified 주체 일치 |
| `decision` | 문제·요구조건·선택지·선택·이유·영향·source·승인 | 선택지 2개 이상, 선택 label 일치, 사용자 필요 결정의 승인 경계 강제 |

Source 종류는 `local_document`, `local_data`, `command_result`, `web_page`, `user_statement`다. 로컬 source는 저장 root·선언된 보호 경계와 겹치지 않는 정규화된 소비 root 상대경로만 허용하고 실제 bytes의 SHA-256을 저장한다. `web_page`는 HTTP(S) locator만 기록하며 외부 fetch를 하지 않는다. `user_statement`는 원문 대신 승인된 `request://` 참조만 기록한다.

Knowledge 분류는 `fact`, `inference`, `procedure`, `constraint`, 상태는 `candidate`, `verified`다. `statement`는 줄바꿈 없는 500자 이하 주장 하나다. 조회는 당시 record와 참조 존재를 보존하고, 현재 로컬 bytes 일치는 `verify_source`에서만 다시 검사한다.

Decision 승인 종류는 `user`, `standing_policy`, `agent_in_scope`다. `requires_user_approval=true`이면 앞의 두 사용자 계열 승인만 가능하고, 결정 시각은 record 생성 시각보다 미래일 수 없다.

## 3. 상태와 승인 경계

| 상태 | 의미 |
|---|---|
| `candidate` | 현재 채택 전 후보 |
| `current` | 승인 경계를 충족한 현재 사용 가능 record |
| `review_required` | source drift·충돌·검증 사건으로 재검토 필요 |
| `superseded` | 같은 유형의 current replacement가 대체한 과거 record |
| `rejected` | 승인 검토 후 채택하지 않은 record |
| `retired` | 한때 current였으나 더 이상 사용하지 않는 record |

`superseded`, `rejected`, `retired`는 terminal이다. 원본을 되살리거나 덮어쓰지 않고 새 record와 새 lifecycle을 만든다.

| action | 허용 전이 | 승인 |
|---|---|---|
| `register` | 없음 → candidate/current | current는 user·standing_policy |
| `request_review` | candidate/current → review_required | agent_in_scope 가능 |
| `approve_current` | candidate/review_required → current | user·standing_policy |
| `declare_conflict` | candidate/current/review_required → review_required | agent_in_scope 가능, 같은 유형의 등록된 모든 대상 |
| `supersede` | candidate/current/review_required → superseded | user·standing_policy, 같은 유형의 current replacement |
| `reject` | candidate/review_required → rejected | user·standing_policy |
| `retire` | current/review_required → retired | user·standing_policy |

모든 기존 대상 전이는 정확한 snapshot `content_hash`를 요구한다. source·replacement·decision·conflict 참조는 event append 전에 실제 record type과 lifecycle 상태를 검사한다.

## 4. Event 정본과 Projection 복구

- `lifecycle_events` JSONL stream이 전이 정본이다. `lifecycle_state` record는 언제든 event replay로 재구축할 수 있는 projection이다.
- 최초 register event가 `state_record_id`를 한 번 정하며 이후 primary event에서 바뀔 수 없다. 이 ID와 stream의 expected hash가 동시 등록과 오래된 전이를 거부한다.
- `declare_conflict` event 하나가 primary와 모든 related target에 적용된다. 양쪽 원본은 유지되고 replay가 각 대상을 `review_required`로 만든다.
- event append 뒤 각 snapshot을 재구축한다. snapshot 쓰기가 실패해도 이미 저장된 event를 되돌리거나 성공으로 숨기지 않고 `LifecycleProjectionPending`을 반환한다.
- projection이 event 정본보다 뒤처진 동안 새 전이를 거부한다. `rebuild_snapshot` 성공 뒤에만 후속 전이가 가능하다.
- `audit`는 명시적으로 등록된 로컬 source bytes만 검사하고 drift source와 이를 참조하는 활성 knowledge·decision을 `review_required`로 전환한다. 외부 fetch·자동 승인·자동 병합은 없다.

## 5. Schema와 오류 경계

- `schemas/source-payload-v1.schema.json`
- `schemas/knowledge-payload-v1.schema.json`
- `schemas/decision-payload-v1.schema.json`
- `schemas/lifecycle-event-payload-v1.schema.json`
- `schemas/lifecycle-state-payload-v1.schema.json`

Schema는 payload의 저장 구조를, Python 검증기는 canonical UUIDv4·실제 시각·교차 필드·참조·hash·전이·승인 조건을 추가로 검사한다. 오류는 입력·승인·전이 위반, source 무결성 실패, expected hash 경쟁, event commit 뒤 projection 보류를 구분한다.

## 6. 제외와 후속

- 실패 Markdown projection과 실패 전용 lifecycle은 흡수하지 않는다. 실패 경험은 활성 규칙·회귀와 원래 Git lineage가 소유한다.
- Evidence Context package는 [Evidence Context 계약](EVIDENCE_CONTEXT_CONTRACT.md)이, 작업 상태 Runtime은 [작업 상태 계약](WORK_STATE_CONTRACT.md)이 소유한다. Maintainer의 기존 `file_data` 의존 전환은 이 계약에 포함하지 않는다.
- 이 기능은 [호환성 선언](../../docs/COMPATIBILITY.md)의 `shared_data` v1에 등록된 `available` 선택 기능이다. 실제 소비는 선언된 공개 CLI와 Consumer 경계 검증을 사용하며 내부 모듈 import는 공개 계약이 아니다.
