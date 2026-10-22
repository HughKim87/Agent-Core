# 작업 상태·실행 호환 Runtime 계약

- 목적: 사용자 요청, 승인·제외 범위, 작업 사건과 개별 작업의 현재 상태를 세션 기억과 독립적으로 재구성한다.
- 읽는 시점: L7 work request·event·snapshot 또는 controlled 단계 설계 포인터를 구현·검증할 때.
- 책임: `work_state.py`가 event 정본·전이·projection, `execution.py`가 실행 등급·설계 fingerprint, work schema가 저장 구조를 소유한다.
- 상태: L7 구현 완료. 기본 비활성이며 `shared_data` v1 공개 CLI·schema가 제공하는 `available` 계약.
- 관련 권위: [공통 Record·저장](RECORD_STORAGE_CONTRACT.md), [단계 작업 설계](../../rules/staged-work-design.md), [보호 데이터](../../rules/protected-data.md).

---

## 1. 소유권과 비활성 기본값

- 프로젝트 전체 현재 단계와 첫 다음 행동의 정본은 소비 저장소의 활성 handoff다. Work Runtime은 여러 세션에서 구조화 재개가 필요한 개별 작업에만 사용한다.
- `work_events` JSONL stream이 추가 전용 정본이고 같은 work ID의 `work_state`는 event replay로 재구축 가능한 bounded projection이다.
- 공통 실행·Consumer 저장·보호·명시 쓰기 경계는 [저장 계약 §8](RECORD_STORAGE_CONTRACT.md#8-공개-호출-공통-명세)을 따른다. Work 쓰기도 기본 비활성이며 Core에는 Runtime 데이터를 저장하지 않는다.
- 보호 데이터 원문, 전체 명령 출력, 채팅 전문과 동적 Git 상태를 저장하지 않고 승인된 참조만 기록한다.

## 2. 불변 요청과 실행 포인터

첫 `requested` event가 다음 요청을 소유하며 후속 event에서 의미를 바꿀 수 없다.

- `desired_outcome`, `authorized_actions`, `excluded_scope`
- `input_refs`, `protection_boundaries`, `required_decisions`, `verification_levels`
- 선택적 `execution`: `quick`, `standard`, `controlled`

`quick`과 `standard`는 영구 단계 설계 포인터를 저장하지 않는다. `controlled`는 `phase_id`, 소비 root 상대 `design_ref`, 검토한 내용의 `design_fingerprint`가 모두 필요하다. 생성·전이 직전에 현재 파일 bytes를 다시 hash하며 보호 경계·Runtime storage·root 밖 파일은 읽지 않는다. hash 차이는 내용 revision 변경이므로 event append 전에 `design_invalidated` 오류로 변경 검토를 요구한다. 오류 이름은 호환성을 위해 유지하며 그 자체가 재승인 판정은 아니다.

공개 `request.compare`는 previous·current 각각에 작업 생성과 같은 work request 필수 field·type·execution 검증과 정규화를 적용한다. 빈 object·array·null·미지원 field는 쓰기 없이 구조화된 계약 오류로 거부한다. 비교는 설계 파일의 현재 내용이나 사용자 승인을 검증하는 작업이 아니다.

`request.compare`는 요청 field 또는 실행 등급·단계·설계 경로가 바뀌면 `invalidated`와 `reapproval_required`를 반환한다. 같은 단계·경로의 fingerprint만 바뀌면 두 값은 false이고 `design_review_required`는 true다. 이는 내용 검토 필요 판정이며 의미가 같다는 자동 승인이나 증명이 아니다.

승인된 목표·범위·권한·성공 조건이 유지되는 서식·설명·검증 근거 갱신은 `work.refresh_design`으로 같은 작업에서 이어 간다. 호출자는 `work_id`, `expected_state_hash`, `actor`, 현재 파일과 일치하는 `reviewed_fingerprint`, 명시적 `decisions_unchanged: true`, 비어 있지 않은 `evidence_refs`와 선택적 `timestamp`를 제공한다. Runtime은 호출자의 의미 검토를 추론하지 않는다. 결정이 달라졌다면 이 operation을 사용할 수 없으며 작업 계약과 필요한 승인을 다시 확정한다.

`refresh_design`은 미완료 controlled 작업에만 허용한다. 추가 전용 검토 event는 갱신된 request 포인터와 근거를 기록하되 최초 요청 event, 다른 요청 field, 상태·진행·blocker·다음 행동을 보존한다. replay도 fingerprint 외 변경을 거부한다. 일반 `work.transition`에서는 예약 action `requested`와 `refresh_design`을 사용할 수 없다.

## 3. 전이와 승인 사실

| 현재 | 허용 다음 상태 |
|---|---|
| `requested` | `in_progress`, `failed`, `blocked` |
| `in_progress` | `in_progress`, `completed`, `failed`, `blocked` |
| `failed` | `in_progress`, `blocked` |
| `blocked` | `in_progress`, `failed` |
| `completed` | 없음 |

- `blocked`에는 blocker가 필요하고 `completed`에는 `next_action`이 없어야 한다.
- `in_progress → in_progress`는 완료 항목·근거·다음 행동 checkpoint다.
- expected snapshot hash가 다르거나 event 시각이 현재 snapshot보다 이르면 append하지 않는다.
- `rejected` outcome은 거부 사실을 event에 남기되 상태·진행·blocker·다음 행동을 바꾸지 않는다.
- 이 Runtime은 사용자 승인 여부를 추론하거나 외부 행동을 실행하지 않는다. actor·action·outcome은 호출자가 승인 경계 안에서 기록하는 사실이다.

## 4. 복구와 경쟁

1. 전이 전에 현재 snapshot과 전체 event replay가 같은지 확인한다.
2. 허용 전이·execution fingerprint·expected stream hash를 확인하고 event를 원자 append한다.
3. snapshot의 expected hash를 먼저 확보한 뒤 해당 work event를 처음부터 replay해 쓴다. 동시 생성·갱신 충돌은 거부하며 더 최신 projection의 hash로 오래된 replay를 덮어쓰지 않는다.
4. event 뒤 projection 쓰기가 실패하면 event를 보존하고 `WorkProjectionPending`을 반환한다.
5. pending 동안 새 전이를 거부하며 `rebuild_snapshot` 성공 뒤 재개한다.

snapshot은 요청, 현재 상태, 중복 없는 완료 항목·관련 ID·근거, 현재 blocker·다음 행동과 마지막 event ID만 가진다. 과거 event 본문을 누적 복제하지 않는다.

## 5. 제외

- subprocess, 도메인 workflow, 모델·브라우저·네트워크 호출, 자동 승인·자동 재시도는 구현하지 않는다.
- handoff 문서를 자동 편집하거나 완료 work를 시작 context에 자동 삽입하지 않는다.
- 내부 Python 경로는 공개 API가 아니다. 외부 소비자는 `shared_data` v1의 `work.*`·`execution.fingerprint`·`request.compare`, 선언된 schema와 §6의 호출 명세를 사용한다.

## 6. 공개 operation 명세

공통 타입·envelope·오류·쓰기 경계는 [저장 계약 §8](RECORD_STORAGE_CONTRACT.md#8-공개-호출-공통-명세)을 따른다. `actor`, `action`, `next_action`은 해당 의미의 비어 있지 않은 문자열이며 선택 `next_action`은 null도 허용한다. 진행 항목·blocker·근거는 중복 없는 문자열 배열이고 `related_record_ids`도 중복 없는 비어 있지 않은 문자열 배열이다.

| operation | 필수 arguments | 선택 arguments·기본값 | 쓰기 | 성공 result |
|---|---|---|---|---|
| `work.create` | `request` (아래 object), `actor`, `next_action` | `work_id`·`timestamp` 공통 기본값 | 예 | requested 상태의 work_state record |
| `work.get` | `work_id` | 없음 | 아니오 | work_state record |
| `work.list` | 없음 | `status:null` (필터 없음) | 아니오 | work_state record[] |
| `work.transition` | `work_id`, `expected_state_hash`, `actor`, `action`, `outcome`, `to_status` | `completed_items:[]`, `blockers:[]`, `related_record_ids:[]`, `evidence_refs:[]`, `next_action:null`, `timestamp` 공통 기본값 | 예 | 전이 후 work_state record |
| `work.rebuild` | `work_id` | `expected_last_event_id:null` | 예 | 재구축한 work_state record |
| `work.refresh_design` | `work_id`, `expected_state_hash`, `actor`, `reviewed_fingerprint`, `decisions_unchanged`, `evidence_refs` | `timestamp` 공통 기본값 | 예 | 설계 fingerprint를 갱신한 work_state record |
| `execution.fingerprint` | `design_ref` (소비 상대 파일 경로 문자열) | 없음 | 아니오 | `{design_ref,fingerprint}`; 전달한 ref와 현재 bytes의 SHA-256 |
| `request.compare` | `previous`, `current` (각각 아래 request object) | 없음 | 아니오 | `{invalidated,reapproval_required,design_review_required,changed_fields,previous_execution,current_execution}` |

Request는 `desired_outcome` 문자열과 `authorized_actions`, `excluded_scope`, `input_refs`, `protection_boundaries`, `required_decisions`, `verification_levels` 문자열 배열이 모두 필수이며 추가 field는 선택 `execution`뿐이다. 배열은 비어 있을 수 있다. `execution`을 생략할 수 있으나 null을 넣지 않는다. 넣으면 `{tier,phase_id?,design_ref?,design_fingerprint?}` object이며 tier는 `quick|standard|controlled`다. quick/standard의 세 포인터는 생략/null, controlled는 모두 비어 있지 않아야 한다. fingerprint는 공통 hash 타입이다. 정규화 결과는 생략한 포인터를 null로 갖는다.

`status` 필터와 `to_status`는 §3의 다섯 상태다. 일반 전이는 action `requested`·`refresh_design`을 거부한다. outcome은 `success|failure|blocked|rejected`로, in_progress/completed는 success, failed는 failure, blocked는 blocked와 짝을 이룬다. rejected일 때는 필수 `to_status:null`을 전달하고 진행 정보를 보존한다. 일반 전이의 빈 선택 목록·null next_action은 이전 blocker·다음 행동을 그대로 유지한다는 뜻이 아니므로 이번 상태에 필요한 값을 전달한다. 완료 항목·관련 ID·근거는 누적 중복 제거된다. §3의 전이·blocker·시각 조건을 함께 충족해야 한다.

`expected_state_hash`는 현재 work snapshot의 `content_hash`, `expected_last_event_id`는 제공 시 해당 work의 마지막 event ID와 일치해야 한다. get/list도 event 정본과 snapshot 불일치를 오류로 반환한다. pending은 §4의 rebuild 후 재조회하며 실패 응답을 event 미저장으로 간주하지 않는다. work_state payload는 `work_id`, `request`, `status`, `completed_items`, `blockers`, `next_action`, `related_record_ids`, `evidence_refs`, `last_event_id`를 갖는다. [저장 schema](schemas/work-state-payload-v1.schema.json)가 각 field 구조를 소유한다.

`work.refresh_design`에는 현재 파일 bytes와 같은 새 `reviewed_fingerprint`, 정확히 boolean true인 `decisions_unchanged`, 검토 근거 1개 이상의 `evidence_refs`가 필요하다. 기존 fingerprint와 같거나 완료·비controlled 작업이면 거부한다. 실제 의미 검토·승인은 호출자의 책임이다. 예시 ID·hash·근거는 실제 조회·검토 결과로 대체한다.

```json
{"operation":"work.refresh_design","arguments":{"work_id":"11111111-1111-4111-8111-111111111111","expected_state_hash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","actor":"maintainer","reviewed_fingerprint":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","decisions_unchanged":true,"evidence_refs":["docs/review.md#설계-검토"]}}
```

`request.compare`의 세 판정은 boolean, `changed_fields`는 바뀐 request field 이름 배열, 두 execution 값은 정규화 object 또는 실행 지정이 없으면 null이다. 설계 hash만 바뀌었는지와 요청 의미 field가 바뀌었는지는 §2 기준으로 구분한다. 다음은 쓰기나 설계 파일 읽기를 하지 않는 비교이며 세 판정은 모두 false, `changed_fields`는 빈 배열이다. 실제 재승인 필요 여부를 호출 자체가 승인하지 않는다.

```json
{"operation":"request.compare","arguments":{"previous":{"desired_outcome":"문서 검토","authorized_actions":["읽기"],"excluded_scope":[],"input_refs":[],"protection_boundaries":[],"required_decisions":[],"verification_levels":["정적 검사"]},"current":{"desired_outcome":"문서 검토","authorized_actions":["읽기"],"excluded_scope":[],"input_refs":[],"protection_boundaries":[],"required_decisions":[],"verification_levels":["정적 검사"]}}}
```
