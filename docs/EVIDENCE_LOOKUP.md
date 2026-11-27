# 선택적 근거 조회

- 목적: 작업 방향을 정하기 전에 문서 참조와 Python 코드의 영향 범위를 좁힌다.
- 읽는 시점: Consumer에서 공용 조회 기능을 선택하거나 복원할 때.
- 책임: Core는 조회 계약과 검사를 제공하고 Consumer는 설치·실행 파일·조회 범위·로컬 색인을 관리한다.
- 상태: 선택 기능 v1. 기본 비활성.
- 관련 권위: [선택 Runtime 공개 경계](COMPATIBILITY.md#3a-선택-runtime-공개-경계).

## 언제 사용하는가

- Obsidian은 문서 이동이나 변경 전에 관련 Markdown 참조를 찾을 때 유용하다.
- Graphify는 Python 정의의 호출 관계가 수정·검증 범위를 바꿀 때 유용하다.
- 필요한 파일이 분명하면 해당 원문을 직접 읽는다. 도구 응답으로 정책의 권위나 요청의 승인 범위를 결정하지 않는다.

## 설치와 활성화

지정한 도구만 공식 배포처에서 설치한다. 실제 검증 대상은 [Obsidian 1.15.1](https://github.com/obsidianmd/obsidian-releases/releases/tag/v1.15.1)의 Windows 공개 설치본과 [Graphify 0.9.120](https://pypi.org/project/graphifyy/0.9.120/)의 Windows CPython 3.12 환경이다. Obsidian은 `Obsidian.exe`와 같은 폴더의 `Obsidian.com`을 쓴다. Graphify는 사용자 또는 Consumer가 만든 가상환경의 Python을 사용한다. 패키지는 `uv pip install --python <환경 Python> graphifyy==0.9.120`으로 설치할 수 있다. 사용 환경의 버전과 다운로드 무결성은 해당 Consumer가 기록한다. 앱과 패키지, 개인 Vault, 실행 파일의 절대경로를 Core에 저장하지 않는다.

사용을 선택한 Consumer만 소비 정책의 `required_core_capabilities`에 `"evidence_lookup": 1`을 추가한다. 두 도구는 호출마다 하나를 선택한다. Consumer의 `.gitignore`에 실제 캐시 경로를 넣는다. 이전에 추적된 파일이 그 경로에 있으면 캐시로 사용할 수 없다. 캐시는 입력을 바탕으로 다시 만들 수 있다.

## 호출과 결과

소비 루트에서 고정한 Core 경로와 `src`를 격리 Python의 import 경로에 두고 아래 공개 진입을 실행한다. `info`는 계약 조회, `invoke`는 UTF-8 JSON 하나를 표준 입력으로 받아 결과 하나를 표준 출력으로 반환한다. `<core 경로>`는 Consumer가 고정한 checkout 경로다. Host는 [읽기 전용 실행 기준](CONSUMER_GUIDE.md#host의-core-읽기-전용-실행)에 맞게 검증된 checkout을 제공한다.

```text
python -B -I -c "import runpy,sys; from pathlib import Path; p=Path(sys.argv.pop(1)).resolve(); sys.path[:0]=[str(p),str(p/'src')]; runpy.run_module('experimental.evidence_lookup',run_name='__main__',alter_sys=True)" <core 경로> invoke --consumer-root .
```

```json
{"tool":"obsidian","target":"docs/policy.md","source_roots":["docs"],"executable":null,"cache":".agent-core-local/evidence"}
```

`executable`에 설치한 실행 파일의 절대경로를 지정한다. 값을 `null`로 두거나 조회가 실패하면 Obsidian은 추적 Markdown의 인라인 링크, Graphify는 추적 Python의 심볼 정의를 조회하는 방식으로 이어간다. 대체 결과는 `backend`와 `fallback_reason`으로 구분한다. 대체 Python 결과는 **정의 후보**이며 호출 관계를 반환하지 않는다. 결과가 비어 있거나 `partial`·`truncated`이면 검색 범위와 한계를 함께 확인한다.

`source_roots`는 Consumer 상대 파일 또는 디렉터리의 목록이다. Git 추적 입력 및 요청한 확장자만 읽고 보호 경로를 제외한다. 별도 승인된 Core 유지보수를 하는 Maintainer는 명시적으로 Core의 문서·규칙·소스 근거를 조회할 수 있다. Host 실행은 해당 범위를 열지 않는다. 캐시, 로그와 임시 사본은 Consumer의 Git 제외 경로 안에서 생성한다. Graphify는 로컬 코드 전용 모드로 실행하고, Obsidian은 임시 Vault와 프로필을 사용한다.

Graphify 요청에 `"include_call_sites": true`를 추가하면 같은 입력에서 직접 검색한 호출 후보를 `call_sites`로 받는다. `matches`에는 원래 이름과 `from … import … as …`로 가져온 이름의 호출 위치가 포함된다. 같은 이름을 어디서 가져왔는지 원문에서 확인한다. `incomplete`는 입력 누락, Python 구문 오류, 결과 제한에 대한 표시다. 색인 밖의 파일, 대입으로 만든 별칭, 동적 호출은 영향이 예상될 때 관련 원문에서 따로 확인한다. Core의 런타임 경계 변경을 검토하는 Maintainer는 `core/experimental/evidence_lookup/__main__.py`와 `core/experimental/shared_data/cli.py`에 해당하는 파일을 각각 명시할 수 있다. 두 파일의 상위 디렉터리는 이 예외에 포함하지 않는다.
