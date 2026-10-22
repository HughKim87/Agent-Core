# Evidence Context package 계약

- 목적: 소비자가 명시한 Markdown 문서·`data_key`와 현재 L7 지식을 문자 예산 안에서 하나의 결정론적 근거 package로 결합한다.
- 읽는 시점: L7 Evidence Context를 구현·검증하거나 공개 기능 승격을 판단할 때.
- 책임: `context.py`가 경로·선택·예산·fingerprint를, `schemas/context-package-v1.schema.json`이 출력 구조를 소유한다.
- 상태: L7 구현 완료. `shared_data` v1 공개 CLI·schema가 제공하는 `available` 계약.
- 관련 권위: [지식·Lifecycle 계약](KNOWLEDGE_LIFECYCLE_CONTRACT.md), [보호 데이터](../../rules/protected-data.md), [계층과 공개 경계](../../docs/ARCHITECTURE.md).

---

## 1. 입력과 탐색 경계

- 직접 선택은 `{ref, data_key?}` 문서 항목과 L7 record ID다.
- 문서 ref는 소비 root 상대 Markdown 경로여야 하고 Runtime storage·선언된 보호 경계·소비 root 밖을 가리킬 수 없다.
- `data_key`는 같은 문서의 fenced `project-data:v1` block에서 정확히 하나만 찾아야 한다.
- 검색·filter는 호출자가 `candidate_documents`로 명시한 문서의 `current` block과 lifecycle이 `current`인 L7 record만 대상으로 한다.
- 저장소 전체 자동 순회, 보호 경로 존재 확인, FTS·vector·graph·외부 fetch는 하지 않는다.

## 2. 선택과 예산

- 직접 선택을 먼저 처리한다. 직접 선택 내용이 `max_characters`를 넘으면 `EvidenceContextLimitError`로 실패하며 일부 package를 반환하지 않는다.
- 검색·filter 후보가 남은 예산을 넘으면 package의 `excluded`에 `size_limit` 사유를 남기고 다음 후보를 평가한다.
- lifecycle이 `current`가 아닌 직접 record는 내용을 싣지 않고 `not_current`로 제외한다. 명시한 문서 data block은 상태와 함께 직접 선택할 수 있다.
- 중복 항목은 한 번만 선택하고 출력은 안정된 key 순서로 정렬한다.

## 3. 비영구 결정론

- package는 `package_version`, `purpose`, `settings`, `selected`, `excluded`, `metrics`, `fingerprint`를 가진다.
- fingerprint는 fingerprint field를 제외한 canonical JSON의 SHA-256이다. 현재 시각·난수·호스트 절대경로는 포함하지 않는다.
- package를 Core나 소비 Runtime에 저장하는 API는 제공하지 않는다. 동일한 bytes·record 상태·요청에는 동일 package가 나온다.
- 문서 내용은 strict UTF-8·BOM 없음·NUL 없음이어야 하고 JSON block은 중복 key와 비유한 숫자를 거부한다.

## 4. 제외

- 실패 Markdown과 과거 failure record의 자동 검색은 포함하지 않는다. 예방 지식은 활성 규칙·회귀가 소유한다.
- work-state 의미와 실행, 네트워크 전송, 모델 호출은 포함하지 않는다. `shared_data` CLI는 이 계약의 입력·출력을 전달할 뿐 새 의미를 소유하지 않는다.
- L7 내부 Python 경로는 공개 API가 아니다. 외부 소비자는 `shared_data` v1의 `context.build`·`context.validate`, 선언된 schema와 §5의 호출 명세를 사용한다.

## 5. 공개 operation 명세

공통 envelope·오류·실행 경계는 [저장 계약 §8](RECORD_STORAGE_CONTRACT.md#8-공개-호출-공통-명세)을 따른다. 두 operation 모두 Runtime 쓰기를 하지 않는다.

| operation | 필수 arguments | 선택 arguments·기본값 | 쓰기 | 성공 result |
|---|---|---|---|---|
| `context.build` | `purpose` (앞뒤 공백·NUL 없는 비어 있지 않은 문자열) | `documents:[]`, `record_ids:[]`, `candidate_documents:[]`, `search:null`, `filters:null`, `max_characters:12000` | 아니오 | context-package v1 object |
| `context.validate` | `package` (context-package object) | 없음 | 아니오 | `{"valid":true}` |

`documents`는 `{ref,data_key?}` object 배열이다. `ref`는 §1의 소비 상대 Markdown 경로 문자열, `data_key`는 생략/null이면 파일 전체, 문자열이면 해당 block을 선택한다. `record_ids`는 UUIDv4 문자열 배열이며 각 대상은 등록된 lifecycle이 필요하다. `candidate_documents`는 검색할 Markdown ref 문자열 배열이다. `search`는 생략/null 또는 앞뒤 공백 없는 비어 있지 않은 문자열이며 내용의 대소문자 무시 부분 일치다. `filters`는 생략/null 또는 object로 `kind`, `record_type`, `state`, `data_kind`, `status`, `scope`, `verification_status`, `evidence_role`만 허용하며 값은 앞뒤 공백 없는 비어 있지 않은 문자열이다. filter는 모두 정확히 일치해야 한다. `max_characters`는 boolean이 아닌 1 이상의 정수다.

검색어나 비어 있지 않은 filter가 있을 때만 후보 탐색을 수행한다. 문서는 명시한 candidate 안의 current block, record는 current lifecycle 대상에서 선택한다. 직접 선택과 예산·제외 동작은 §2를 따른다. 누락 파일·잘못된 block·읽을 수 없는 record/lifecycle·직접 선택 예산 초과는 오류다. `context.validate`는 전달한 package의 구조·metrics 값의 비음수 정수 타입·fingerprint 일관성을 검사하며 원본 파일이나 현재 lifecycle을 다시 조회하지 않는다.

반환 package의 `package_version`은 1, `purpose`는 요청 목적, `settings`는 정규화된 search·filters·max_characters·candidate_documents다. `selected`는 `kind`, `ref`, `reason`, `content`, `characters`를 가진 항목 배열이며 document_data는 `data_key`, `data_kind`, `status`, `source_refs`, `data`를, record는 `record_id`, `record_type`, `state`, `data`를 추가한다. `excluded`는 `kind`, `ref`, `reason` 등 제외 항목 배열이다. `metrics`는 `selected_items`, `selected_characters`, `excluded_items` 정수이고 `fingerprint`는 §3의 hash다. 전체 출력 구조는 [context-package schema](schemas/context-package-v1.schema.json)를 따른다.

예를 들어 `{"operation":"context.build","arguments":{"purpose":"검토","documents":[{"ref":"docs/input.md","data_key":"sample"}],"max_characters":12000}}`은 다음 형식의 block을 명시적으로 선택한다. marker와 JSON의 kind/key가 같고 문서 안 key가 유일해야 한다. `source_refs`는 중복 없는 문자열 배열, `payload`는 object다.

````markdown
<!-- project-data:v1 kind=evidence key=sample -->
```json
{"key":"sample","kind":"evidence","status":"current","source_refs":[],"payload":{"statement":"검토 근거"}}
```
<!-- /project-data -->
````
