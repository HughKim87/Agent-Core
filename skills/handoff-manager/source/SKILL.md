---
name: handoff-manager
description: |
  Create, update, audit, or clean up session handoff documents so another Codex session can resume from verified project state. Use for handoff/session handoff/인수인계 requests, including reviewing handoff quality, updating SESSION_HANDOFF.md, preparing the next session, recording interruption points, and reconciling stale or duplicated handoff instructions.
---

# Handoff Manager

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
