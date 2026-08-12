# Agent Core 이식성 — BND01 결합 전수 분류표

- 목적: `core/**`가 호스트(김실버유튜브)에 결합된 지점을 전수 확정하고, 각 지점의 BND02 분류와 목표 상태를 고정한다.
- 읽는 시점: Agent Core 저장소 분리·submodule 전환 작업의 승인 범위를 판단할 때.
- 책임: 프로젝트 에이전트가 유지하고, `core/**` 변경은 사용자가 각 범위를 승인한다.
- 상태: 활성 작업 문서. 승인 대기.
- 관련 권위: `PROJECT_RULES.md`, `core/rules/boundary-routing-and-dependency.md`(BND01·BND02·BND03), `core/rules/core-change-control.md`, `core/rules/rule-governance.md`, `core/docs/INFORMATION_ARCHITECTURE.md`
- 측정일: 2026-08-11 / `core/**` 수정 0건 (읽기 전용 스캔)

---

## 1. 판정 기준

이 표의 기준은 새로 만든 것이 아니라 이미 프로젝트가 소유한 조항이다.

| 조항 | 이 표에서 쓰는 방식 |
|---|---|
| BND01 검증 | *"foundation·extension Markdown 사이의 직접 navigation link와 rule route가 0개"* — 이식성 판정의 기존 소유자. 새 게이트를 만들지 않는다 |
| BND02 | 참조를 `navigation`/`rule-routing`/`machine-schema`/`runtime-api`/`storage`/`test-only`로 분류하고 종류마다 다른 해법을 쓴다 |
| BND03 | 양쪽이 함께 필요한 schema는 한쪽에 복사하지 않고 중립 interface owner를 둔다 → 매니페스트 스키마는 Core, 값은 호스트 |
| rule-governance 14행 | 도메인 어휘에 의존하는 것은 도메인 extension에 속한다 → 목표 E |
| INFORMATION_ARCHITECTURE §4 | 층 소유는 배치 계약이 이미 소유 → 매니페스트는 층을 재선언하지 않고 호스트마다 달라지는 **값만** 갖는다 |
| core-change-control 승인 게이트 | 변경 후 통과해야 할 최종 관문. 게이트 자체도 결합 대상(목표 F) |

---

## 2. 전체 집계

| 목표 | 내용 | 건수 | 파일 |
|---|---|---:|---:|
| **A** | 변경 불필요 | 10 | 4 |
| **B** | 역할 선언 치환 | 111 | 25 |
| **C** | storage 매니페스트화 | 84 | 20 |
| **D** | 호스트 이름 제거 | 26 | 1 |
| **E** | 도메인 이전·삭제 | 52 | 13 |
| **F** | 게이트 명령 일반화 | 2 | 1 |
| | **합계** | **285** | **39** |

BND02 분류별:

| BND02 | 건수 | 비고 |
|---|---:|---|
| `test-only` | 165 | `core/tests` 전용. 활성 owner나 routing source가 될 수 없다 (BND01 예외) |
| `navigation` | 39 | `core/docs` 계약이 호스트 문서·경로를 이름으로 지목 |
| `rule-routing` | 29 | `core/rules`의 Authority 선언과 도메인 라우팅 |
| `storage` | 27 | 저장 경로 계약·상수 |
| `-` | 23 | 분류 대상 아님 (역할어·도메인 어휘) |
| `runtime-api` | 2 | 승인 게이트 명령 |

---

## 3. 영역별 분포

| 영역 | A | B | C | D | E | F | 합계 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `core/README.md` | 0 | 3 | 0 | 0 | 2 | 0 | **5** |
| `core/docs` | 0 | 31 | 10 | 0 | 6 | 0 | **47** |
| `core/failures` | 0 | 1 | 0 | 0 | 2 | 0 | **3** |
| `core/rules` | 8 | 29 | 0 | 0 | 1 | 2 | **40** |
| `core/src` | 0 | 4 | 17 | 0 | 0 | 0 | **21** |
| `core/tests` | 2 | 43 | 57 | 26 | 41 | 0 | **169** |

**읽는 법:** `core/tests`가 169건으로 전체의 59%다. 결합의 무게중심은 `core/src`(21건)가 아니라 테스트와 계약 문서에 있다.

---

## 4. 파일별 승인 범위

`A`(변경 불필요)만 있는 파일은 제외했다. 아래가 `core-change-control.md` 절차에서 승인을 요청할 정확한 경로 목록이다.

| 건수 | 목표 | 파일 |
|---:|---|---|
| 57 | B C D E | `core/tests/test_rule_routing.py` |
| 38 | B E | `core/tests/fixtures/rule-routing-intents-v1.json` |
| 23 | B C E | `core/docs/INFORMATION_ARCHITECTURE.md` |
| 22 | B C E | `core/tests/test_maintenance.py` |
| 21 | B C | `core/tests/test_file_data_foundation.py` |
| 13 | C | `core/tests/test_record_io.py` |
| 10 | B | `core/rules/rule-governance.md` |
| 7 | B | `core/docs/obsidian/OBSIDIAN_REVIEW_CONTRACT.md` |
| 7 | C | `core/src/file_data/cli.py` |
| 5 | B E | `core/README.md` |
| 5 | B C | `core/docs/WORK_STATE_CONTRACT.md` |
| 5 | B E | `core/rules/boundary-routing-and-dependency.md` |
| 5 | B C | `core/src/file_data/maintenance.py` |
| 5 | C | `core/tests/test_knowledge_types.py` |
| 4 | B F | `core/rules/core-change-control.md` |
| 4 | B C | `core/src/file_data/document_data.py` |
| 4 | C | `core/tests/test_context.py` |
| 4 | C | `core/tests/test_lifecycle.py` |
| 3 | C | `core/docs/RECORD_IO_CONTRACT.md` |
| 3 | B | `core/rules/staged-work-design.md` |
| 3 | B C | `core/src/file_data/store.py` |
| 2 | C E | `core/docs/CONTEXT_PACKAGE_CONTRACT.md` |
| 2 | C E | `core/docs/KNOWLEDGE_LIFECYCLE_CONTRACT.md` |
| 2 | C E | `core/docs/KNOWLEDGE_TYPES_CONTRACT.md` |
| 2 | B E | `core/docs/MAINTENANCE_AUTOMATION_CONTRACT.md` |
| 2 | B | `core/rules/document-work.md` |
| 2 | B | `core/rules/failure-records.md` |
| 2 | B | `core/rules/file-extraction.md` |
| 2 | C | `core/src/file_data/record.py` |
| 2 | B C | `core/tests/test_execution.py` |
| 1 | C | `core/docs/FILE_DATA_CONTRACT.md` |
| 1 | B | `core/failures/README.md` |
| 1 | E | `core/failures/canonical-owner-and-document-drift.md` |
| 1 | E | `core/failures/scope-and-authority-boundaries.md` |
| 1 | B | `core/rules/cross-validation.md` |
| 1 | B | `core/rules/file-cleanup.md` |
| 1 | B | `core/rules/user-data-work.md` |
| 1 | B | `core/rules/version-control.md` |
| 1 | E | `core/tests/test_export.py` |

**파일 39개 / 참조 275건**

---

## 5. 목표별 상세

### A. 변경 불필요 — 10건 / 4파일

`extension`이 경로가 아니라 역할어로 쓰인 자리다. 예: `rule-governance.md`의 *"Keep domain procedure with its extension owner"*. 이식성과 무관하므로 손대지 않는다.

### B. 역할 선언 치환 — 111건 / 25파일

호스트 고유 이름을 매니페스트가 선언한 역할 조회로 바꾼다.

| 현재 이름 | 건수 | 목표 |
|---|---:|---|
| `PROJECT_RULES.md` | 47 | 매니페스트 `policy_document` |
| `SESSION_HANDOFF.md` | 28 | 매니페스트 `state_document` |
| `extension/README.md` | 16 | 선언된 도메인 진입점 |
| `AGENTS.md` | 7 | 매니페스트 `entry_documents` |
| `extension/work/CORE_CHANGE_FAILURES.md` | 2 | 선언된 도메인 owner 경로 |
| `extension/work/` | 2 | 선언된 도메인 owner 경로 |
| `extension/docs/*.md` | 1 | 선언된 도메인 owner 경로 |
| `extension/docs/` | 1 | 선언된 도메인 owner 경로 |
| `extension/schemas/` | 1 | 선언된 도메인 owner 경로 |
| `extension/src/` | 1 | 선언된 도메인 owner 경로 |
| `extension/tests/` | 1 | 선언된 도메인 owner 경로 |
| `extension/examples/` | 1 | 선언된 도메인 owner 경로 |

`core/src`에도 4건 있다 — 코드가 호스트 문서명을 알고 있다(`store.py`의 루트 판정, `document_data.py`·`maintenance.py`).

### C. storage 매니페스트화 — 84건 / 20파일

`extension/data/**`와 `"extension"` 상수를 `runtime_data_root` 조회로 바꾼다.

**같은 사실이 세 곳에 있다.** `core/docs/RECORD_IO_CONTRACT.md`가 *"기록 경로는 `extension/data/records/<id>.json`"* 이라고 계약하고, `core/src/file_data/record.py:256`이 같은 문자열로 예외를 던지고, `core/tests`가 같은 경로로 fixture를 만든다. **세 곳을 같은 체크포인트에서 함께 바꾼다.** 코드만 바꾸면 `core/failures/canonical-owner-and-document-drift.md`가 이미 기록한 실패를 재현한다.

| 영역 | 건수 |
|---|---:|
| `core/docs` | 10 |
| `core/src` | 17 |
| `core/tests` | 57 |

### D. 호스트 이름 제거 — 26건 / 1파일

전부 `core/tests/test_rule_routing.py`다. `ainotebook` 15 · `AINOTEBOOK` 8 · `김실버유튜브` 1 · `extension/work/AINOTEBOOK_WORKTREE_STATE.md` 2.

정규식으로 `PROJECT_RULES.md`의 워크스페이스 분기를 파싱해 상태 문서를 고르는 구조다. 매니페스트 `state_document` 선언 검증으로 대체하면 `PROJECT_RULES.md`의 `root_name == "ainotebook"` 분기도 함께 사라진다.

**단, 매니페스트를 브랜치마다 다른 값으로 커밋하면 `main` ↔ `codex/ainotebook` 병합 때마다 충돌한다.** 분기를 없애는 게 아니라 더 위험한 자리로 옮기는 것이므로, worktree 키 맵을 한 파일에 두어 브랜치 간 파일 내용이 동일하도록 한다.

### E. 도메인 이전·삭제 — 52건 / 13파일

| 대상 | 건수 | 처분 |
|---|---:|---|
| `core/tests/fixtures/rule-routing-intents-v1.json` | 38 | YouTube·Premiere 도메인 케이스를 `extension/tests/`로 이전 |
| `core/tests/test_maintenance.py` | 일부 | `extension/src/youtube_domain/broken.py` 등 도메인 fixture 이전 |
| `core/docs` 계약 6곳 · `core/rules` 1곳 · `core/failures` 2곳 · `core/README.md` 2곳 | 11 | "영상"·"YouTube" 어휘 삭제 (rule-governance 14행) |

`rule-governance.md` 41–44행에 따라 route를 바꾸면 intent fixture 4종(initial·colloquial·mid-task·near-miss, 필요시 composed)을 새로 만들고 **fresh-session semantic replay를 통과해야 활성화된다.** 이 의무가 작업량의 상당 부분이다.

### F. 게이트 명령 일반화 — 2건 / 1파일

`core/rules/core-change-control.md`의 승인 게이트가 `extension/src`·`extension/tests`를 문자로 박고 있다.

```powershell
$env:PYTHONPATH = ((Resolve-Path 'core/src').Path, (Resolve-Path 'extension/src').Path, (Resolve-Path 'core/tests').Path -join ';')
python -m unittest discover -s extension/tests -q
```
**이것이 실제 차단 지점이다.** `extension/`이라는 이름의 디렉터리가 없는 호스트에서는 이 게이트가 실행되지 않고, 게이트가 실행되지 않으면 그 호스트에서는 core 변경을 승인할 방법 자체가 없다. 매니페스트 `extensions[].path` 순회로 조립해야 한다.

---

## 6. 실행 순서

실행 빈도 순이다. `core/src`는 측정상 한 번도 실행된 적이 없고(`extension/data` 부재, 저장소 전체 `.jsonl` 0건, CLI 34개 중 규칙 라우팅 1개), `core/rules`·`core/docs`는 매 세션 로드된다.

| # | 범위 | 목표 | 종류 |
|---:|---|---|---|
| 1 | `core/rules/core-change-control.md` | F | **core change — 승인 필요** |
| 2 | 호스트 루트 매니페스트 + `core/schemas/host-manifest-v1.schema.json` | — | 호스트 변경 + core 신규 파일 |
| 3 | `core/rules/*.md` 6파일 · `core/docs/*.md` 9파일 | B·E | **core change — 승인 필요** |
| 4 | `core/src/file_data/*.py` 5파일 | B·C | **core change — 승인 필요** |
| 5 | `core/tests/*` 9파일 + fixture | B·C·D·E | **core change — 승인 필요** |
| 6 | BND01 검증을 실행 가능한 검사로 구현 | — | core change |
| 7 | 승인 게이트 전체 통과 + semantic replay | — | 검증 |
| 8 | `git subtree split -P core -b dist` → `agent-core` 저장소 | — | 저장소 |
| 9 | 호스트 submodule 전환, 게이트 재통과 | — | 구조 |
| 10 | 두 번째 호스트 clean clone 게이트 통과 | — | **요구 2 실증 = 완료 판정** |

2번은 `core/schemas/`에 새 파일을 만드는 것이므로 이것도 core change다. 승인 없이 착수 가능한 단계는 없다.

---

## 7. 재현

이 표는 결정적 스캔의 파생 표현이다. 스캔 스크립트는 이 문서와 같은 폴더의 `scan.py`·`classify.py`이며, 같은 트리에서 재실행하면 같은 285건이 나온다.

- 대상: `core/**`의 `.md`·`.py`·`.json` 39개 파일
- 검출: 호스트 문서명 4종 · `extension/` 리터럴 경로 · 호스트 이름 3종 · 도메인 어휘 8종 · 역할어
- `__pycache__` 제외
