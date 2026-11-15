---
name: research-manager
default_claude_code_model: claude-sonnet-5
description: |
  Coordinate deep multi-agent research and source verification. Use this skill only when the user explicitly asks "깊게 리서치해" or "깊게 조사해". Do not trigger for ordinary requests such as "리서치해", "조사해", "찾아봐", "확인해", or "비교해" unless the user includes one of the exact deep-research trigger phrases.
---

# Research Manager

- 목적: 심층 조사에 필요한 독립 근거와 반증을 종합한다.
- 읽는 시점: 명시적인 심층 조사로 이 스킬이 선택됐을 때.
- 책임: 사용자가 조사 범위·예산을 정하고 에이전트가 조사 방법과 검증을 선택한다.
- 상태: 승인 개정 실행 본문. source는 비활성 보존 원본이다.
- 관련 권위: 현재 사용자 지시와 작업 대상에 적용되는 정책·실행기 권한.

## Core Rule

Select Agent roles and source paths that provide the independent evidence, counterexamples, and coverage needed for the user's decision within the authorized scope and budget. Availability alone does not require using a path. Preserve an explicit user request for all Agents, named paths, or full coverage.

## Workflow

1. Define the research question:
   - State the decision the research must support.
   - Identify whether the topic needs current information, official documentation, implementation evidence, issue/workaround evidence, or security review.
   - Mark assumptions that must be verified.
   - Identify any requested deliverable format, filename, and destination at the start. Treat an explicitly requested file as a completion condition; use the owning project workspace unless the user specifies another destination.
2. Select useful research paths and preflight them before relying on them:
   - Codex direct analysis and local repo inspection.
   - Web research when current or external evidence is required and network access is available.
   - Existing project wrapper scripts, if present.
   - Claude Code CLI, if installed and callable.
   - Other configured Agent providers or MCP/tools exposed in the session.
   - If a path or Agent call fails, record the reason and continue through other authorized paths; report material coverage gaps and skipped required paths.
3. Assign roles instead of duplicating prompts blindly:
   - `researcher`: gather facts, official sources, issues, examples, and constraints.
   - `reviewer`: check whether the proposed approach is practical and complete.
   - `redteam`: identify security, cost, reliability, and failure risks.
   - `architect`: convert findings into an implementation or operating plan.
4. Source priority:
   - Prefer official docs, official blogs, release notes, GitHub repos, changelogs, standards, and vendor documentation.
   - Use blogs, news, community posts, and forum answers according to the claim they can support. User reviews can be direct evidence of reported experiences, but do not establish official terms or how common an experience is. Agent outputs are leads to verify against underlying sources.
   - For material claims about changing prices, policies, specifications, or promotions, record the source type, verification date, and applicable period when available. Distinguish current, expired, and unverified conditions; a report-wide date alone is insufficient when sections were checked at different times.
   - Distinguish official conditions, individual reported experiences, and recurring patterns. Repeated citations of the same underlying account do not establish a pattern. Keep recommendation strength proportional to the evidence and identify preference-based judgments.
   - When a search does not establish a claim, report that it was not confirmed in the checked sources. Do not turn missing evidence into a claim that an offering or feature does not exist.
   - Mark unsupported claims as unverified or inferred.
5. Compare results:
   - Separate facts, interpretations, recommendations, and open questions.
   - Highlight agreement between Agents/sources.
   - Highlight conflicts and explain which source is more reliable.
   - Do not treat Claude or any external Agent result as final truth.
6. Save requested deliverables and verify completion:
   - For a long investigation with a requested file, save useful interim findings as they become available and update the same report for follow-up questions within its scope. Merge findings into the relevant sections rather than appending duplicate conclusions. Choose a creation sequence suitable for the format; an empty file before research is not required.
   - If a required input, destination, or authorization prevents saving, state the blocker and continue independent permitted research. Do not claim that the file has been delivered.
   - Before delivery, verify that the file exists at the intended location, matches the requested filename and format, and contains the final synthesis. Use format-appropriate inspection and check multilingual text with an explicit encoding when needed.
   - Link to the actual file in the final response and briefly identify what was created or updated and any remaining gaps. If no file was requested, store or reference results only when useful within the authorized scope.
   - Prefer the project run store if it exists, such as `agent_outputs/runs/YYYY-MM-DD/TASK_ID/`.
   - Keep raw Agent outputs separate from Codex's final synthesis.
   - In handoff documents, include only the conclusion, key files, run IDs, blockers, and next checks.

## Agent Execution Rules

- For Claude Code CLI, prefer the project's wrapper if available; otherwise call the known working CLI path only after a small preflight.
- Remove API keys or secrets from subprocess environments unless the selected provider explicitly requires them.
- For Agent outputs, require structured summaries when possible: facts, sources, risks, recommendation, and unknowns.

## Progress, Risk, and Budget

Follow the owning project's failure-handling policy when present. Continue authorized work when new evidence, a reproduced counterexample, or a confirmed cause resolution supports progress. A changed prompt, method, or Agent alone is not progress.

Stop repeating a method that produces no progress on the same cause; diagnose it or choose an authorized alternative. Failure count alone does not end the investigation. Respect the user's explicit time, cost, and attempt budgets in their stated scope and lifetime; changing Agents or methods does not reset them.

Pause the affected action and its dependents at an actual authorization, protection, loss-risk, unresolved external-result, or budget boundary. Confirm an uncertain external result before retrying. Continue independent permitted research. Report the confirmed cause, remaining uncertainty, risk, and decision needed when the boundary prevents completion; do not create a per-attempt approval or failure ledger.

## Final Report Shape

Use this order unless the user requests a different format. Link external sources and include implementation impact for coding or workflow research:

1. Short conclusion.
2. What was checked and which Agents/sources were used.
3. Comparison table or score table when there are multiple options.
4. Conflicts, weak evidence, and unverified claims.
5. Recommended path.
6. Next actions.
