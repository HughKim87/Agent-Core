---
name: handoff-manager
description: "명시적으로 호출했을 때 대상 프로젝트의 검증된 상태를 인수인계 문서로 작성·점검한다. Core 연결은 필요하지 않으며 프로젝트 없는 채팅 분석은 대상이 아니다."
---

# Handoff Manager

- 목적: 검증된 프로젝트 상태를 다음 세션에 전달한다.
- 읽는 시점: 사용자가 이 스킬을 명시적으로 호출했을 때.
- 책임: 프로젝트는 현재 상태와 정책을, 이 스킬은 작성·점검 절차를 소유한다.
- 상태: PC 공통 스킬. 대상 프로젝트가 필요하고 Core 연결은 선택이다.
- 관련 권위: 현재 사용자 요청과 대상 프로젝트에 이미 적용되는 정책.

## 실행 문맥

사용자의 명시적 스킬 호출에만 실행한다. 일반 인수인계 요청이나 스킬 수정·점검은 실행 호출이 아니다. 대상 프로젝트 root를 현재 문맥에서 확인하고 불명확하면 대상만 묻는다. 프로젝트 없는 채팅에서는 프로젝트를 임의 생성하지 않는다.

대상에 이미 존재하는 진입·정책·현재 상태만 읽는다. Core가 없어도 아래 절차를 실행할 수 있다. Core·extension·AGENTS.md·PROJECT_RULES.md의 설치나 생성을 전제하지 않는다. 상태 파일이 없으면 대상 프로젝트 안에서 아래 기본 파일을 작성하되 기존 프로젝트 정책의 형식·보존 위치를 우선한다.

Prepare a concise, evidence-backed handoff that lets the next session resume without relying on chat memory.

## Workflow

1. Read controlling instructions completely.
   - Read project entrypoints, applicable global/project rules, document-maintenance rules, and the existing handoff.
   - Read stage or tool instructions only when they control the active work.
2. Select one state source.
   - Prefer `SESSION_HANDOFF.md` unless the user names another file.
   - Treat any `NEXT_SESSION_TASK.md` as a derived execution view, not a second state source.
3. Gather current evidence.
   - Record the current goal and scope, source inputs, implementation state, completed work, interruption point, first unstarted action, blockers, risks, decisions, and relevant artifacts.
4. Verify claims before writing.
   - Confirm referenced files exist and identify the actual latest usable version from content and timestamps, not filenames alone.
   - Compare counts, durations, statuses, and verification levels with primary outputs or reports.
   - Inspect validation surfaces far enough to confirm they support the claimed review action. Do not call a page playback-capable if it only shows metadata.
   - Distinguish generated, parsed, structure-validated, tool-validated, app-validated, and user-approved states.
   - Treat automatic audit success as a limited check, not content or user approval.
   - Scan linked guides and reports for stale or superseded instructions and label them accordingly.
5. Keep only resumable unresolved state.
   - Retain the current unresolved cause, required decision, and restart condition; never record or carry forward failure counts, attempted methods or order, a failure ledger, or stop state.
6. Separate and deduplicate.
   - Keep project-specific facts, paths, run IDs, decisions, blockers, and next actions in the handoff.
   - Link to general operating rules instead of copying them. Keep a short task-specific warning only when it prevents an immediate repeated mistake.
   - Mark historical artifacts whose instructions are no longer active.
7. Write the handoff with concise sections.
   - Include purpose and read order, current goal, key terms, source inputs, resume checkpoint, implementation/completed work, verification state, active blockers/risks, important artifacts, next actions, and a next-session start prompt.
   - Give every important artifact a complete project-relative path and a status such as active, historical, superseded, or pending verification.
   - If a derived next-task document is kept, state its role, when to read it, and retention/expiry condition within its first 10 lines. Do not duplicate current state there.
8. Back up according to controlling rules.
   - If project rules require a backup, create it in the required location before editing.
   - If project rules prohibit duplicate backups, do not create one; report `no backup — project rules use version control`.
   - If no project rule exists, create `temp/backups/YYYY-MM-DD/original_filename.bak_YYYY-MM-DD_HHMM` under the workspace.
9. Verify after writing.
   - Re-read every changed file and check for NUL bytes and expected sections.
   - Check referenced paths, document size limits, single-source consistency, and conflicts with linked instructions.
   - Run available project document checks and diff checks. Record any unresolved validation issue as an active blocker; do not report a clean handoff when checks fail.
10. Report the result.
   - List changed files, verification performed, remaining gaps, backup path or backup-policy reason, dedupe decisions, and unapplied instruction proposals.

## Safety Rules

- Do not publish, commit, open pull requests, or modify external systems unless explicitly requested.
- Do not delete or overwrite project-specific context without clear authorization.
- Do not trust external Agent output as final truth; label it as an Agent result or verification target.
