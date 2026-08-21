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
- 호출자가 소비 root·storage root·보호 경계와 `write_enabled=true`를 명시해야만 초기화·event·snapshot 쓰기가 가능하다. Core에는 Runtime 데이터를 저장하지 않는다.
- 보호 데이터 원문, 전체 명령 출력, 채팅 전문과 동적 Git 상태를 저장하지 않고 승인된 참조만 기록한다.

## 2. 불변 요청과 실행 포인터

첫 `requested` event만 다음을 소유하며 후속 event에서 바꿀 수 없다.

- `desired_outcome`, `authorized_actions`, `excluded_scope`
- `input_refs`, `protection_boundaries`, `required_decisions`, `verification_levels`
- 선택적 `execution`: `quick`, `standard`, `controlled`

`quick`과 `standard`는 영구 단계 설계 포인터를 저장하지 않는다. `controlled`는 `phase_id`, 소비 root 상대 `design_ref`, 승인 당시 `design_fingerprint`가 모두 필요하다. 생성·전이 직전에 현재 파일 bytes를 다시 hash하며 보호 경계·Runtime storage·root 밖 파일은 읽지 않는다. hash가 달라지면 event를 append하기 전에 재승인 필요 오류로 실패한다.

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
3. 해당 work event를 처음부터 replay해 snapshot을 쓴다.
4. event 뒤 projection 쓰기가 실패하면 event를 보존하고 `WorkProjectionPending`을 반환한다.
5. pending 동안 새 전이를 거부하며 `rebuild_snapshot` 성공 뒤 재개한다.

snapshot은 요청, 현재 상태, 중복 없는 완료 항목·관련 ID·근거, 현재 blocker·다음 행동과 마지막 event ID만 가진다. 과거 event 본문을 누적 복제하지 않는다.

## 5. 제외

- subprocess, 도메인 workflow, 모델·브라우저·네트워크 호출, 자동 승인·자동 재시도는 구현하지 않는다.
- handoff 문서를 자동 편집하거나 완료 work를 시작 context에 자동 삽입하지 않는다.
- 내부 Python 경로는 공개 API가 아니다. 외부 소비자는 `shared_data` v1의 `work.*`·`execution.fingerprint`·`request.compare` operation과 선언된 schema만 사용한다.
