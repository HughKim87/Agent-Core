---
name: setup-agent-core-project
description: 명시적으로 호출했을 때만 프로젝트 이름을 바탕으로 독립 Private GitHub 저장소를 만들고, 읽기 전용 SSH 인증으로 Agent Core를 연결·검증하여 초기 구성을 게시한다. 일반적인 프로젝트 생성 요청으로 자동 실행하지 않는다.
---

# 프로젝트기본세팅

사용자가 `$setup-agent-core-project` 또는 이 스킬을 사용하라는 명시적 지시로 호출한 경우에만 실행한다. 키워드, 유사한 작업 의도, 과거 호출만으로 활성화하지 않는다. 이 스킬을 만들거나 편집하라는 요청은 프로젝트 생성 실행이 아니다.

## 결과와 작업 범위

프로젝트 이름을 GitHub 저장소 이름으로 사용하여 독립 **Private** 저장소를 만들고, 새 부모 저장소의 `main`에 Agent Core 기반 초기 설정을 게시한다. Core는 원본 원격을 가리키는 고정 커밋의 Git submodule이다. 기존 프로젝트나 Core 저장소를 부모 프로젝트로 clone·fork·템플릿 복제하지 않는다. `git submodule add`가 만드는 정식 Core checkout은 필요한 의존성 연결이다.

이 스킬의 프로젝트 구축을 명시적으로 요청하면 해당 프로젝트의 로컬 파일 생성, Git 초기화, 정확한 초기 파일의 stage·commit, Private 저장소 생성, 초기 `main` 게시를 수행 범위로 설명하고 진행한다. 사용자 지시가 계획·검토·로컬 준비에 한정되면 그 경계를 따른다. 기존 저장소 삭제, 공개 범위 변경, 다른 원격 조작, 공유 자격 증명 변경은 포함하지 않는다. 스킬 자체는 실행기의 권한 제한을 우회하지 않는다.

제품 기능, 앱 프레임워크, 패키지 설치와 도메인 디렉터리는 요청된 경우에만 추가한다.

## 1. 입력과 대상 확인

- 프로젝트 이름, 생성할 폴더, GitHub 소유자, Core 원격을 정한다. 이름이 누락되면 먼저 묻는다. 폴더와 소유자는 현재 작업 문맥 및 인증된 계정에서 합리적으로 확정할 수 있으면 사용하고 알린다.
- 사용자가 지정한 이름을 보존한다. GitHub에서 허용되지 않는 이름은 저장소용 이름을 정한 뒤 진행하며, 오탈자로 보인다는 이유로 임의 개명하지 않는다.
- 현재 폴더와 적용되는 `AGENTS.md`를 확인한다. 기존 프로젝트에 초기 설정을 덮어쓰지 않는다. 같은 작업의 부분 설정이 있으면 실제 파일·원격·커밋을 대조해 재개한다.
- `git`, `gh`, `ssh`, Core가 요구하는 Python의 가용성을 확인한다. `gh api user --jq .login`으로 인증 계정을 확인한다. 자격 증명 값은 출력하지 않는다.
- 같은 이름의 GitHub 저장소가 있는지 조회한다. 조회 오류를 저장소 부재로 간주하지 않는다. 기존 저장소가 있으면 무단으로 교체·삭제·public/private 전환하지 않는다. 이번 작업이 만든 동일 저장소이면 확인된 중단 지점부터 이어간다.

이 환경에서 사용한 Core 원격은 `git@github.com:HughKim87/Agent-Core.git`이다. 다른 사용자·환경에서는 지정된 원격 또는 기존 Core의 원격을 우선하고, 이 기본값이 맞는지 확인한다.

## 2. Core 계약과 읽기 전용 SSH를 먼저 확인

프로젝트 연결 전에 해당 Core revision의 `PROJECT_RULES.md`, `docs/CONSUMER_GUIDE.md`, `docs/COMPATIBILITY.md`, 진입 계약을 읽고 현재 작업에 route된 규칙을 따른다. 이 스킬에 적힌 예시는 Core의 최신 공개 계약을 대체하지 않는다. 기존 로컬 Core가 있으면 문서와 원격 설정을 조사할 수 있으나 파일·이력을 새 프로젝트에 복사하지 않는다. 로컬과 원격 revision이 다르면 적용할 원격 revision의 문서를 다시 확인한다.

읽기 전용 인증은 **최초 Core submodule clone 이전에** 선택한다.

1. 사용자가 요청한 기존 Core의 로컬 `core.sshCommand`, 필요한 SSH Host 설정, 승인된 키 이름·공개키를 좁게 조사한다. 개인키·토큰·Git credential 내용은 읽거나 복제하지 않는다.
2. 공개키를 `gh api repos/OWNER/Agent-Core/keys` 등의 원격 metadata와 대조하여 일치하는 Deploy Key의 `read_only: true`를 확인한다. 이 환경의 기존 키 제목은 `Agent-Core Read Only`였다. 제목이나 파일 이름만으로 권한을 확정하지 않는다.
3. 일치하는 기존 읽기 전용 키를 재사용한다. 확인할 수 없으면 읽기/쓰기 계정 키로 대체하지 말고 필요한 키·권한 정보를 요청한다. 새 키 생성·등록은 별도로 승인된 경우에만 수행한다.
4. SSH에는 해당 키, `IdentitiesOnly=yes`, `IdentityAgent=none`, `BatchMode=yes`, `StrictHostKeyChecking=yes`를 적용한다. 신뢰할 known-host 정보가 없으면 인증된 GitHub metadata의 호스트 공개키를 사용해 프로젝트의 로컬 Git metadata 영역에 둔다. 호스트 검증을 끄지 않는다.
5. `GIT_SSH_COMMAND`, `GIT_SSH` 등 실제 인증 선택을 바꾸는 환경 override를 확인한다. 최초 연결에는 선택한 SSH 명령을 일시 전달하고, 성공 후 Core clone의 로컬 `core.sshCommand`에 유지한다. 일시 환경 변수는 `finally`에서 원래 값으로 복원한다.

개인키는 원래 위치에서 SSH 인증에만 사용한다. 실제 키 경로·SSH 명령·호스트별 인증 설정은 `.gitmodules`, 정책·상태 문서, 추적 파일에 넣지 않는다. 부모 프로젝트의 GitHub 인증과 Core의 읽기 전용 인증을 분리한다.

## 3. 새 부모 저장소와 Core 연결

- 선택된 새 프로젝트 폴더에서 `git init -b main`으로 시작한다. Core 문서가 요구하는 최초 연결 후보 절차를 따른다. 부모가 없는 신규 초기 설정의 미게시 snapshot을 검증 대상으로 고정하며, 이미 운영 중인 프로젝트의 마지막 검증 상태를 후보로 덮어쓰지 않는다.
- Core는 확인한 **원격 SSH URL**에서 `git submodule add`로 연결한다. 기존 로컬 Core를 clone한 뒤 URL만 바꾸는 방식을 사용하지 않는다.
- Core origin, `.gitmodules` URL/path, 부모 submodule 설정을 대조하고 검증할 원격 commit을 detached HEAD로 고정한다. Core에 새 commit이나 cache를 만들지 않는다. Core SHA의 정본은 부모 gitlink이며 문서에 복제하지 않는다.
- 부모 Git 데이터에 다른 저장소의 `objects/info/alternates` 의존을 만들지 않는다. 다른 저장소와 이력을 공유하는 clone·reference 방식은 이 신규 부모 구성에 필요하지 않다.

소비자가 소유할 최소 구성은 현재 소비자 사용 안내를 기준으로 작성한다.

| 파일 | 역할 |
|---|---|
| `AGENTS.md` | Core 정책 → 프로젝트 정책 → 현재 상태 순서의 Markdown 포인터만 |
| `CLAUDE.md` | 동일 순서의 `@` 포인터만 |
| `PROJECT_RULES.md` | 프로젝트 범위, Private 유지 의도, `host` 소비 계약, 도메인 route |
| `SESSION_HANDOFF.md` | 현재 단계·직전 게이트·승인 상태·차단·알려진 위험·첫 다음 행동 |
| `.gitmodules` | 원본 Core SSH 원격과 submodule 상대경로 |
| `.gitignore` | 실제 보호 경로와 비밀 파일, 예상 cache·빌드 출력 제외 |
| `.gitattributes` | 추적 텍스트 UTF-8/LF 계약에 맞는 줄바꿈 설정 |

소비 계약은 실제 선택한 상대경로와 Core 계약 버전을 사용한다. 도메인 규칙이 없으면 `rule_roots: []`와 빈 route 표를 사용하고, 선택 기능은 요구가 있을 때만 선언한다. 실제 생성할 필요가 없는 빈 폴더는 만들지 않는다. 보호 경로는 선언하되 내용을 열거·읽지 않는다. `SESSION_HANDOFF.md`에는 현재 문서 계약의 메타데이터와 handoff mode를 포함하고, 아직 실행하지 않은 검사에는 `not_run`을 사용한다.

## 4. 인증·연결·소비 검증과 초기 게시

성공 응답 하나로 완료를 판단하지 않고 다음 증거를 확인한다.

- 원격 키 metadata와 실제 인증 선택을 대조한다. 선택한 SSH로 `git ls-remote`를 실행하여 Core 원격 읽기를 확인한다. 필요한 고정 commit을 그 원격에서 확보할 수 있는지 확인한다.
- Core에 `git push --dry-run --no-verify origin HEAD:refs/heads/read-only-permission-check`를 실행해 쓰기 권한 거부를 확인한다. 실제 push는 하지 않는다. 성공한 dry-run이나 일반 네트워크 오류는 읽기 전용 증거가 아니다. GitHub의 명시적인 read-only 거부가 있어야 통과다.
- 초기 파일과 Core gitlink만 정확히 stage·commit하여 부모 HEAD/index/Core revision을 일치시킨다. 최신 Core가 부모 commit을 요구하면 commit 전 gate 통과를 주장하지 않는다.
- 프로젝트 root에서 공개 소비 통합 CLI를 실행한다. 현재 Core가 승인한 bootstrap을 사용하고 Python bytecode 쓰기를 막는다. 예를 들어 Core의 `src`를 현재 프로세스 검색 경로에 두고 `python -B -m core_check --core-root core --consumer-root . gate`를 사용한다. Core 내부 helper를 import하거나 역할을 바꿔 실패를 우회하지 않는다.
- Host gate의 Core 무결성, 소비 계약, 시작 문맥, 부모 gitlink와 실행 전후 Core 불변 증거를 확인한다. Host에서 Core 내부 Maintainer 회귀를 재실행하지 않는다. `not_applicable`과 실제 기능 사용 검증을 구분한다.
- 상태를 실제 결과에 맞게 갱신하고 commit한다. 정책·상태·gitlink를 바꿨으면 최종 부모 snapshot에서 영향받는 소비 gate를 다시 실행한다. 임시 폴더 권한 때문에 검사 자체가 막히면 승인된 실행 환경으로 동일 검사를 재실행하고 원인을 구분한다.

로컬 검증을 마친 뒤 확인한 소유자/이름으로 `gh repo create OWNER/NAME --private --source . --remote origin`을 실행한다. 같은 작업에서 원격을 이미 만들었다면 대상 일치를 확인하고 중복 생성하지 않는다. `isFork: false`, `visibility: PRIVATE`, 부모 origin 목적지를 확인한다.

게시할 부모 commit OID를 고정해 그 객체만 `refs/heads/main`에 push한다. Core 재귀 push와 암묵적 태그 게시를 배제한다. 새 저장소가 비어 있어야 한다는 전제를 확인하며, 예상치 못한 원격 이력이 있으면 덮어쓰지 않는다. 성공 후 로컬 `main`의 upstream을 `origin/main`으로 연결한다.

API·네트워크 결과가 불명확하면 같은 쓰기를 재시도하기 전에 원격 상태부터 조회한다. 실패한 gate나 SSH 권한 문제를 숨긴 채 게시하지 않는다. 영향을 받지 않은 결과는 보존하고, 정확한 차단 원인과 재개 조건을 알린다.

## 5. 완료 보고

다음을 직접 조회하고 짧게 보고한다.

- Private 독립 저장소 URL과 기본 브랜치 `main`.
- 로컬 HEAD와 실제 원격 main OID 일치, 원격 tree의 Core gitlink와 실행 Core HEAD 일치.
- 기존 읽기 전용 키 재사용 여부, 원격 읽기 성공과 명시적 쓰기 거부.
- 최종 Host gate 결과와 부모·Core 작업 트리 상태.
- 남은 한계: SSH 설정은 로컬 전용이라 다른 환경에서 주입해야 함, 원격 쓰기 거부는 로컬 filesystem ACL과 별개임, 새 에이전트 세션의 실제 진입 검증 여부.

새 clone·독립 세션·filesystem 쓰기 차단을 실행하지 않았다면 해당 검증까지 완료했다고 말하지 않는다. 완료 후 추가 기능을 구현하거나 원격을 계속 변경하지 않는다.
