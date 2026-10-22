# 공통 Record·저장 기반 계약

- 목적: 도메인 의미가 없는 JSON record 외피와 소비 저장소 소유의 원자적 파일 저장 불변식을 정의한다.
- 읽는 시점: L7 공통 record·event 저장을 구현·검증하거나 후속 지식·수명주기 기능을 연결할 때.
- 책임: `record.py`가 외피·경로 원시, `store.py`가 저장·동시성, `schemas/common-record-v1.schema.json`이 외피 구조를 소유한다.
- 상태: L7 구현 완료. `shared_data` v1 공개 CLI·schema가 제공하는 `available` 계약.
- 관련 권위: [Kernel 범위](../../docs/KERNEL_SCOPE.md), [계층과 공개 경계](../../docs/ARCHITECTURE.md), [호환성](../../docs/COMPATIBILITY.md).

---

## 1. 공개 상태와 소유권

- 외부 소비자는 `optional_capabilities.shared_data` v1의 `info`·`invoke`, 선언된 schema와 아래 공개 호출 명세에 의존한다. 내부 Python 모듈은 공개 API가 아니다.
- 실제 record·event·lock·임시 파일은 명시적으로 전달된 소비 root와 storage root가 소유한다.
- Core 저장소 안에 Runtime 데이터를 만들지 않는다.
- 저장 root와 보호 경로는 호출자가 소비 계약에서 주입하며 구현이 프로젝트 경로명을 하드코딩하지 않는다.
- 쓰기는 기본 비활성이다. 공개 CLI도 `--write`를 명시한 `invoke`에서만 쓰기를 열며 소비 정책의 행동 승인 자체를 대신하지 않는다.

## 2. Common Record v1

| 필드 | 계약 |
|---|---|
| `id` | 소문자 canonical UUIDv4 |
| `record_type` | 소문자 snake case이며 store의 명시 allowlist에도 포함 |
| `schema_version` | 정수 `1` |
| `created_at` | 초 정밀도 UTC RFC 3339 `Z` |
| `updated_at` | 같은 형식이며 `created_at`보다 이를 수 없음 |
| `payload` | 유한 JSON 값만 포함하는 object |
| `content_hash` | 자신을 제외한 canonical JSON의 `sha256:<64 lowercase hex>` |

입력은 BOM 없는 strict UTF-8 JSON이다. NUL, 중복 key, 비유한 숫자, 문자열이 아닌 key, 추가 외피 field와 hash 불일치를 fail-closed로 거부한다. 인코딩 결과는 정렬된 UTF-8 JSON과 마지막 LF 하나다.

## 3. 경로와 보호 경계

- 소비 root는 존재하는 디렉터리여야 한다.
- storage root와 모든 대상은 정규화된 비어 있지 않은 상대경로여야 한다.
- 절대경로, 빈 구간, `.`·`..`, NUL, root 탈출과 `.git` 구간을 거부한다.
- 보호 경로는 존재 여부를 확인하거나 열거하지 않고 문자열 경계로 먼저 차단한다.
- storage root가 보호 경로와 같거나 조상·자손 관계면 초기화 전에 거부한다.
- symlink 해석 뒤의 실제 경로도 소비 root와 보호 경계를 다시 확인한다.
- record 주소는 `<storage-root>/records/<id>.json`, event 주소는 `<storage-root>/events/<approved-stream>.jsonl`로 결정한다.

## 4. 원자 쓰기와 동시성

1. 메모리 값을 완전히 검증하고 결정론적 bytes로 만든다.
2. 대상별 배타 `.lock`을 생성한다.
3. lock 안에서 기존 record·stream과 expected hash를 검증한다.
4. 같은 디렉터리의 전용 임시 파일에 쓰고 flush·`fsync`한다.
5. 임시 bytes 전체를 재검증하고 `os.replace`로 교체한다.
6. 성공 hash·count와 사후 검증 snapshot을 lock 안에서 계산한다.
7. 정상 종료·예외 경로에서 이 호출이 만든 임시 파일과 lock의 정리를 시도한다. 데이터 교체와 사후 검증·정리의 성공은 구별한다.

| 실패 시점 | 데이터와 후속 판단 |
|---|---|
| 교체 전 검증·쓰기 또는 `os.replace` 자체 실패 | 기존 대상을 유지한다. 임시 파일·lock의 정리에도 별도 I/O 오류가 날 수 있다. |
| 교체 성공 뒤 재읽기·검증 실패 | 새 bytes가 이미 저장됐을 수 있으며 자동 rollback은 없다. 실패 응답만으로 미저장을 단정하지 않는다. |
| 호출 소유 lock 제거 실패 | 저장 성공 여부와 잔존 lock을 따로 확인한다. 다른 호출의 lock을 제거하지 않는다. |
| event 저장 뒤 상위 snapshot 생성 실패 | Lifecycle·Work 계약의 projection pending과 rebuild 절차를 따른다. 저장한 event를 취소한 것으로 해석하지 않는다. |

교체 후 오류에서는 읽기 전용 조회로 실제 record·event의 ID·내용·hash를 확인한 뒤 후속 행동을 판단한다. 확인할 수 없으면 결과를 미확정으로 남기며 자동 재시도·무조건 원본 복구를 수행하지 않는다. 이 원자 교체 절차는 모든 OS 오류의 정리 성공이나 전원 장애 내구성을 보장하지 않는다.

기존 record는 기본적으로 덮어쓰지 않는다. 갱신은 같은 ID와 정확한 `expected_content_hash`가 필요하다. 잠금 충돌과 기대값 불일치는 자동 재시도하지 않는다. 삭제·이동 API는 제공하지 않는다.

## 5. JSONL Event Stream

- 각 줄은 stream 이름과 같은 `record_type`을 가진 common-record v1이다.
- 빈 줄, 마지막 LF 누락, 중복 ID, 손상 record와 다른 유형을 거부한다.
- append 전에 기존 stream 전체를 검증한다.
- 선택적 `expected_stream_hash`가 현재 bytes와 일치할 때만 추가한다.
- 전체 새 bytes를 원자 교체하고 lock 내부에서 최종 hash와 개수를 반환한다.

## 6. 오류 경계

| 오류 | 의미 |
|---|---|
| `RecordValidationError` | 외피·JSON·hash·stream 불변식 위반 |
| `InputContractError` | root·경로·allowlist·payload 입력 위반 |
| `WriteNotEnabledError` | 기본 비활성 쓰기를 명시적으로 열지 않음 |
| `StoreNotInitializedError` | records·events 디렉터리가 준비되지 않음 |
| `RecordNotFoundError` | 결정적 ID 주소에 record가 없음 |
| `ExpectationMismatchError` | expected record·stream hash 불일치 |
| `ConcurrentWriteError` | 대상 lock이 이미 존재 |

## 7. 검증과 후속 경계

- 회귀는 격리된 임시 소비 root만 사용하고 실제 소비 데이터에 접근하지 않는다.
- 정상·손상·경쟁·교체 전 실패의 원본 보존과 교체 후 읽기·lock 정리 실패의 실제 저장 상태를 각각 확인한다. 임시 자원 정리 성공을 데이터 반영과 같은 보장으로 세지 않는다.
- schema field와 Runtime field 집합을 대조한다.
- Core 필수 패키지가 L7을 import하지 않고, 선언된 공개 entry module의 `info` 결과가 호환성 선언과 같은지 확인한다.
- 지식 유형·수명주기는 [별도 L7 계약](KNOWLEDGE_LIFECYCLE_CONTRACT.md)이 이 저장 기반 위에서 소유한다. Evidence Context와 작업 상태 Runtime도 각 계약이 의미를 소유하며 `shared_data` v1 CLI가 전송 경계만 통합한다.

## 8. 공개 호출 공통 명세

공개 실행 준비와 Consumer 검증은 [소비 가이드 §6·6A](../../docs/CONSUMER_GUIDE.md#6-검증-명령)을 따른다. `invoke`에는 검증된 Consumer와 상대 `storage-root`가 필요하며, 변경 operation에는 추가로 `--write`와 현재 행동 승인이 필요하다. record·event 조회에는 초기화된 store가 필요하다. `info`는 정적 metadata discovery이며 operation 실행·저장 초기화가 아니다.

stdin은 정확히 `{"operation":"initialize","arguments":{}}` 형태의 JSON object 하나다. 최대 1 MiB, strict UTF-8이며 BOM·NUL·중복 key·비유한 숫자를 거부한다. 아래 표의 필수 field 누락과 미지원 field는 오류다. 선택 field는 생략할 수 있으나 명시한 `null` 허용 여부는 각 field를 따른다.

| 공통 표기 | 타입·의미 |
|---|---|
| ID | 소문자 canonical UUIDv4 문자열. `record_id`·`work_id` 생성 옵션은 생략/null이면 새 UUIDv4 |
| hash | `sha256:<64 lowercase hex>` 문자열. expected hash는 마지막 조회의 해당 snapshot `content_hash` |
| timestamp | 선택적 UTC 초 정밀도 문자열(예: `2026-10-23T00:00:00Z`), 생략/null이면 현재 UTC |
| record / record[] | §2의 common-record object / 그 배열. payload는 해당 저장 schema를 따른다 |
| 문자열 목록 | JSON array. 별도 명시가 없으면 비어 있지 않은 문자열을 중복 없이 나열하며 목록 자체의 비어 있음 허용 여부는 각 명세를 따른다 |

| operation | 필수 arguments | 선택 arguments·기본값 | 쓰기 | 성공 result |
|---|---|---|---|---|
| `initialize` | 없음 | 없음 | 예 | `{"records":"<storage-root>/records","events":"<storage-root>/events"}`. 디렉터리 준비이며 기존 데이터를 초기화·삭제하지 않음 |

성공 종료 `0`의 stdout은 `ok:true`, `capability:"shared_data"`, `capability_version:1`, `operation`, `result`를 가진 object다. 각 계약 표는 이 `result` 내부를 설명한다. 예상 계약·Runtime 오류는 종료 `1`이며 `ok:false`, 같은 capability 정보, `operation`(요청 판독 전이면 null), 문자열 `error`·`kind`, boolean `recoverable`을 반환한다. 예상 밖 예외는 종료 `2`이며 `recoverable` 대신 `unexpected:true`를 반환한다. CLI 인자 파싱 오류는 이 JSON envelope 이전에 발생할 수 있다.

`recoverable:true`는 자동 재실행·복구 승인이나 미저장 보장이 아니다. §4의 교체 후 오류와 상위 계약의 event/projection pending을 먼저 구별한다. lifecycle·work의 재구축도 쓰기다.

나머지 공개 operation의 입력·결과·승인 전제는 [지식·Lifecycle §7](KNOWLEDGE_LIFECYCLE_CONTRACT.md#7-공개-operation-명세), [Evidence Context §5](EVIDENCE_CONTEXT_CONTRACT.md#5-공개-operation-명세), [작업 상태 §6](WORK_STATE_CONTRACT.md#6-공개-operation-명세)이 나누어 소유한다. 요청·결과 schema는 envelope와 operation 열거를, payload schema는 저장 구조를 소유한다. operation별 arguments·기본값·반환 의미는 이 네 문서의 공개 호출 명세가 소유한다.
