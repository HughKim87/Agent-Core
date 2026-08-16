# 공통 Record·저장 기반 계약

- 목적: 도메인 의미가 없는 JSON record 외피와 소비 저장소 소유의 원자적 파일 저장 불변식을 정의한다.
- 읽는 시점: L7 공통 record·event 저장을 구현·검증하거나 후속 지식·수명주기 기능을 연결할 때.
- 책임: `record.py`가 외피·경로 원시, `store.py`가 저장·동시성, `schemas/common-record-v1.schema.json`이 외피 구조를 소유한다.
- 상태: L7 내부 구현 완료. 공개 호환성에는 아직 등록되지 않은 `implemented_private` 계약.
- 관련 권위: [Kernel 범위](../../docs/KERNEL_SCOPE.md), [계층과 공개 경계](../../docs/ARCHITECTURE.md), [호환성](../../docs/COMPATIBILITY.md).

---

## 1. 공개 상태와 소유권

- 이 기능은 `optional_capabilities`에 등록되지 않았으므로 외부 소비자의 공개 API가 아니다.
- 실제 record·event·lock·임시 파일은 명시적으로 전달된 소비 root와 storage root가 소유한다.
- Core 저장소 안에 Runtime 데이터를 만들지 않는다.
- 저장 root와 보호 경로는 호출자가 소비 계약에서 주입하며 구현이 프로젝트 경로명을 하드코딩하지 않는다.
- 쓰기는 기본 비활성이고 `write_enabled=True`를 명시한 내부 호출만 가능하다. 공개 쓰기 승인은 후속 CLI 계약이 별도로 소유한다.

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
7. 실패하면 이 호출이 만든 임시 파일과 lock을 제거하고 기존 대상을 유지한다.

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
- 정상·손상·경쟁·replace 실패 경로에서 원본 보존과 임시 파일 정리를 확인한다.
- schema field와 Runtime field 집합을 대조한다.
- Core 필수 패키지가 L7을 import하지 않고 `optional_capabilities`가 비어 있는지 확인한다.
- 지식 유형·수명주기·Evidence Context·공개 CLI는 후속 단계가 소유하며 이 계약에 선행 구현하지 않는다.
