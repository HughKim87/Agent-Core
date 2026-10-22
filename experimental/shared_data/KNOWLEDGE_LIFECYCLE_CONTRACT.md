# 지식 유형·승인 기반 Lifecycle 계약

- 목적: 소비 저장소가 소유하는 출처·단일 지식 주장·결정을 불변 record로 보존하고 현재 채택·검토·대체 상태를 승인 근거가 있는 event로 추적한다.
- 읽는 시점: L7 `source`·`knowledge`·`decision` 또는 lifecycle event·snapshot을 구현·검증할 때.
- 책임: `knowledge.py`가 지식 의미·source 참조 무결성, `lifecycle.py`가 전이·승인·projection, 이 디렉터리의 payload schema가 저장 구조를 소유한다.
- 상태: L7 구현 완료. `shared_data` v1 공개 CLI·schema가 제공하는 `available` 계약.
- 관련 권위: [공통 Record·저장 기반](RECORD_STORAGE_CONTRACT.md), [Kernel 범위](../../docs/KERNEL_SCOPE.md), [계층과 공개 경계](../../docs/ARCHITECTURE.md).

---

## 1. 격리와 저장 소유권

- 공개 실행·저장·보호·쓰기 경계는 [저장 계약 §1·3·8](RECORD_STORAGE_CONTRACT.md#8-공개-호출-공통-명세), 기능별 호출은 §7을 따른다. 내부 Python 모듈은 공개 API가 아니다.
- `KnowledgeService`와 `LifecycleService`는 호출자가 구성한 같은 store를 사용한다. `create_knowledge_store`는 이 계약의 고정 type·stream allowlist만 편의상 구성한다.
- 회귀의 격리·저장 실패 검증은 [저장 계약 §7](RECORD_STORAGE_CONTRACT.md#7-검증과-후속-경계)을 따른다.
- 저장 record를 삭제·이동하거나 기존 source·knowledge·decision payload를 update하는 API는 제공하지 않는다.

## 2. 불변 지식 유형

| 유형 | 소유 정보 | 핵심 불변식 |
|---|---|---|
| `source` | 종류·locator·관찰 시각·확인 상태·증거 역할·version/hash | 원문을 복제하지 않고 로컬 bytes만 명시적으로 hash 검증 |
| `knowledge` | 한 줄 주장 하나·분류·scope·source 참조·검증 상태 | source 1개 이상, unavailable source 거부, candidate/verified 주체 일치 |
| `decision` | 문제·요구조건·선택지·선택·이유·영향·source·승인 | 선택지 2개 이상, 선택 label 일치, 사용자 필요 결정의 승인 경계 강제 |

Source 종류는 `local_document`, `local_data`, `command_result`, `web_page`, `user_statement`다. 로컬 source는 저장 root·선언된 보호 경계와 겹치지 않는 정규화된 소비 root 상대경로만 허용하고 실제 bytes의 SHA-256을 저장한다. `web_page`는 HTTP(S) locator만 기록하며 외부 fetch를 하지 않는다. `user_statement`는 원문 대신 승인된 `request://` 참조만 기록한다.

Knowledge 분류는 `fact`, `inference`, `procedure`, `constraint`, 상태는 `candidate`, `verified`다. `statement`는 줄바꿈 없는 500자 이하 주장 하나다. 지식·결정의 조회는 당시 record와 source 참조를 검증하지만 로컬 bytes를 자동 재검사하지 않는다. 로컬 source의 현재 bytes 검사는 §7의 `source.verify` 또는 `source.get/list`의 `verify_local:true`로 요청할 수 있다.

Decision 승인 종류는 `user`, `standing_policy`, `agent_in_scope`다. `requires_user_approval=true`이면 앞의 두 사용자 계열 승인만 가능하고, 결정 시각은 record 생성 시각보다 미래일 수 없다.

## 3. 상태와 승인 경계

| 상태 | 의미 |
|---|---|
| `candidate` | 현재 채택 전 후보 |
| `current` | 승인 경계를 충족한 현재 사용 가능 record |
| `review_required` | source drift·충돌·검증 사건으로 재검토 필요 |
| `superseded` | 같은 유형의 current replacement가 대체한 과거 record |
| `rejected` | 승인 검토 후 채택하지 않은 record |
| `retired` | 승인된 사용 중단 상태. 과거 current 이력을 보장하지 않음 |

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

## 7. 공개 operation 명세

공통 타입·envelope·쓰기·오류 판정은 [저장 계약 §8](RECORD_STORAGE_CONTRACT.md#8-공개-호출-공통-명세)을 따른다. 이 절의 모든 ID는 UUIDv4 문자열이다. `actor`, `reason`, `locator`, `scope`, `verified_by`는 해당 의미의 비어 있지 않은 문자열이다. 선택 ID 참조는 생략/null이면 없음이며 ID 배열은 중복 없는 배열이다. 생성 결과는 lifecycle 자동 등록을 뜻하지 않는다.

| operation | 필수 arguments | 선택 arguments·기본값 | 쓰기 | 성공 result |
|---|---|---|---|---|
| `source.create` | `source_kind`, `locator`, `evidence_role` | `verification_status`·`version_or_hash` 없음, `record_id`·`timestamp`는 공통 기본값 | 예 | source record |
| `source.get` | `record_id` | `verify_local:false` (boolean) | 아니오 | source record |
| `source.list` | 없음 | `verify_local:false` (boolean) | 아니오 | source record[] |
| `source.verify` | `record_id` | 없음 | 아니오 | `{record_id,verification_status,version_or_hash,integrity}`; 로컬 integrity는 `match`, 비로컬은 `not_applicable` |
| `knowledge.create` | `statement`, `classification`, `scope`, `source_ids`, `verification_status` | `verified_by:null`, `record_id`·`timestamp` 공통 기본값 | 예 | knowledge record |
| `knowledge.get` | `record_id` | 없음 | 아니오 | knowledge record |
| `knowledge.list` | 없음 | 없음 | 아니오 | knowledge record[] |
| `decision.create` | `payload` (아래 decision object) | `record_id`·`timestamp` 공통 기본값 | 예 | decision record |
| `decision.get` | `record_id` | 없음 | 아니오 | decision record |
| `decision.list` | 없음 | 없음 | 아니오 | decision record[] |
| `lifecycle.register` | `target_id`, `initial_state`, `actor`, `approval_kind`, `reason` | `source_ids:[]`, `decision_id:null`, `timestamp` 공통 기본값 | 예 | lifecycle_state record |
| `lifecycle.transition` | `target_id`, `expected_state_hash`, `action`, `actor`, `approval_kind`, `reason` | `source_ids:[]`, `related_target_ids:[]`, `replacement_id:null`, `decision_id:null`, `timestamp` 공통 기본값 | 예 | 대상 lifecycle_state record |
| `lifecycle.get` | `target_id` | 없음 | 아니오 | `{record:<원본 record>,lifecycle:<lifecycle_state record>}` |
| `lifecycle.list` | 없음 | `state:null`, `target_type:null` (필터 없음) | 아니오 | lifecycle_state record[] |
| `lifecycle.current` | 없음 | `target_type:null` (필터 없음) | 아니오 | current인 **원본** source·knowledge·decision record[] |
| `lifecycle.history` | `target_id` | 없음 | 아니오 | 해당 대상에 적용되는 lifecycle_events record[]; related conflict도 포함 |
| `lifecycle.rebuild` | `target_id` | `expected_last_event_id:null` | 예 | 재구축한 lifecycle_state record |
| `lifecycle.register_existing` | `actor`, `approval_kind` | 없음 | 예 | 새로 등록한 lifecycle_state record[] |
| `lifecycle.audit` | `actor` | 없음 | 예 | drift 발견 배열 `[{target_id,reason},…]` |

Source 입력의 `source_kind`와 `evidence_role`은 각각 §2의 종류와 `primary|supporting|contextual`, `verification_status`는 `observed|verified|unavailable`이다. 비로컬 status는 생략/null이면 `observed`, `version_or_hash`는 생략/null 또는 비어 있지 않은 문자열이다. 로컬 source는 실제 파일의 SHA-256을 기록하고 status를 `verified`로 정한다. 제공한 hash가 다르면 실패한다. `timestamp`가 payload의 `observed_at`와 record 생성 시각이 된다. `observed_at`을 arguments로 직접 전달하지 않는다. `get/list`의 `verify_local:true`와 `source.verify`는 로컬 bytes를 재검사하고 drift 시 오류를 반환하며 record를 갱신하지 않는다.

Knowledge는 §2의 분류와 `candidate|verified` status, source ID 1개 이상이 필요하다. candidate의 `verified_by`는 null, verified는 비어 있지 않은 문자열이어야 한다. 생성은 source 존재·종류·unavailable 여부와 로컬 hash를 확인한다. 지식·결정의 조회는 참조를 검증하지만 로컬 bytes를 자동 재검사하지 않는다.

Decision의 `payload`는 다음 field를 모두 가진 object이며 추가 field는 허용하지 않는다. `problem`, `selected_option`, `rationale`, `approved_by`는 비어 있지 않은 문자열, `requirements`·`impacts`는 비어 있지 않은 문자열 배열, `source_ids`는 1개 이상의 source ID 배열이다. `options`는 정확히 `{label,impact}` 문자열 쌍인 object 2개 이상이며 label은 중복 없고 `selected_option`과 하나가 일치해야 한다. `requires_user_approval`은 boolean, `approval_kind`는 §3의 세 종류, `decided_at`은 UTC 초 정밀도 문자열이다. §2의 승인·시각·source 검사를 통과해야 한다. CLI에서는 이들을 arguments에 펼치지 않고 아래처럼 감싼다.

```json
{"operation":"decision.create","arguments":{"payload":{"problem":"방식 선택","requirements":["재현 가능"],"options":[{"label":"A","impact":"현재 유지"},{"label":"B","impact":"검증 추가"}],"selected_option":"B","rationale":"승인 범위 내 검증","impacts":["검증 시간 증가"],"source_ids":["11111111-1111-4111-8111-111111111111"],"requires_user_approval":false,"approval_kind":"agent_in_scope","approved_by":"maintainer","decided_at":"2026-10-23T00:00:00Z"},"timestamp":"2026-10-23T00:00:00Z"}}
```

예시 source ID는 먼저 생성한 실제 source ID로 대체한다. 다음 로컬 source 예시는 `docs/input.md`가 소비 root에 존재해야 하며, 반환 payload에 `observed_at`, 계산한 `version_or_hash`, `verification_status:"verified"`가 들어간다.

```json
{"operation":"source.create","arguments":{"source_kind":"local_document","locator":"docs/input.md","evidence_role":"primary","timestamp":"2026-10-23T00:00:00Z"}}
```

Lifecycle의 `target_type`은 `source|knowledge|decision`, `state`는 §3의 여섯 상태, `initial_state`는 `candidate|current`다. action·승인·replacement·conflict 조건은 §3 표가 정본이다. `expected_state_hash`는 원본이 아닌 lifecycle snapshot hash다. 선택 `source_ids`는 실제 source 참조, `decision_id`는 current decision 참조이며, `replacement_id`는 supersede 대상과 같은 유형의 current record여야 한다. `declare_conflict`에는 자신을 제외한 같은 유형의 등록된 `related_target_ids`가 1개 이상 필요하고 다른 action에서는 빈 배열이어야 한다. `replacement_id`는 `supersede`에 필수이며 다른 transition action에는 허용하지 않는다. `expected_last_event_id`를 주면 replay의 마지막 event ID와 일치해야 한다. pending이면 쓰기 승인 하에 rebuild 후 재조회한다.

`register_existing`는 이미 등록된 대상을 중복 등록하지 않고 필요한 projection을 재구축할 수 있다. source·knowledge의 verified와 decision은 current로, 그 밖에는 candidate로 등록하므로 current 등록에 맞는 승인이 필요하다. 결과에는 이번에 새로 등록한 snapshot만 담는다. `audit`는 읽기 전용 검사가 아니다. §4의 drift 전이를 저장한다. 두 일괄 operation은 여러 대상 전체의 원자 transaction이 아니므로 중간 오류 전에 일부 event·snapshot이 반영됐을 수 있다. 실패 시 조회·history로 상태를 먼저 확인한다.
