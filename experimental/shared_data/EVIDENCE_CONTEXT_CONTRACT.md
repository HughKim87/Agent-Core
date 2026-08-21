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
- L7 내부 Python 경로는 공개 API가 아니다. 외부 소비자는 `shared_data` v1의 `context.build`·`context.validate` operation과 선언된 schema만 사용한다.
