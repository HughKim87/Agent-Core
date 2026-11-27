"""Compare a closeout with the previously delivered classification report."""

import argparse
import json
from pathlib import Path
import re
import sys


MARKER = "# 이 세션은 종료되었습니다"
STATES = {"pending", "approved", "completed", "deferred", "not_selected"}
ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
ROSTER_PREFIX = "분류 후보 —"


def classified_candidates(message):
    rows = [line.strip() for line in message.splitlines() if line.strip().startswith(ROSTER_PREFIX)]
    if len(rows) != 1:
        raise ValueError("분류 보고 원문에서 후보 행 하나를 확인해야 합니다.")
    roster = rows[0].removeprefix(ROSTER_PREFIX).strip()
    if roster == "없음":
        return {}
    classified = {}
    for item in roster.split(","):
        match = re.fullmatch(rf"({ID_PATTERN})\((필수|선택|근거 부족)\)", item.strip())
        if not match or match[1] in classified:
            raise ValueError("분류 보고의 후보 ID 또는 분류가 잘못됐거나 중복됐습니다.")
        classified[match[1]] = match[2] == "필수"
    return classified


def check_close(report, classified):
    if (
        not isinstance(report, dict)
        or type(report.get("review_complete")) is not bool
        or type(report.get("close_checks_passed")) is not bool
        or not isinstance(report.get("candidates"), list)
    ):
        raise ValueError("분류·종료 검사 상태와 후보 목록이 필요합니다.")

    seen = set()
    pending = []
    unfinished = []
    for candidate in report["candidates"]:
        if not isinstance(candidate, dict):
            raise ValueError("후보 형식이 올바르지 않습니다.")
        candidate_id = candidate.get("id")
        required = candidate.get("required")
        state = candidate.get("state")
        if (
            not isinstance(candidate_id, str)
            or not re.fullmatch(ID_PATTERN, candidate_id)
            or candidate_id in seen
            or type(required) is not bool
            or not isinstance(state, str)
            or state not in STATES
        ):
            raise ValueError("후보 ID, 필수 여부 또는 상태가 올바르지 않습니다.")
        if candidate_id not in classified:
            raise ValueError(f"분류 보고에 없는 후보 — {candidate_id}")
        if required != classified[candidate_id]:
            raise ValueError(f"분류 보고와 필수 여부 불일치 — {candidate_id}")
        seen.add(candidate_id)
        if required and state == "not_selected":
            raise ValueError(f"필수 후보 {candidate_id}에 사용자 결정이 필요합니다.")
        if required and state in {"completed", "deferred"}:
            reference = candidate.get("decision_ref")
            if not isinstance(reference, str) or not reference.strip():
                raise ValueError(f"필수 후보 {candidate_id}의 결정 근거가 필요합니다.")
        if required and state == "pending":
            pending.append(candidate_id)
        if state == "approved":
            unfinished.append(candidate_id)

    missing = classified.keys() - seen
    if missing:
        raise ValueError("분류 보고 후보 누락 — " + ", ".join(sorted(missing)))
    if pending:
        return 1, "결정 대기 — " + ", ".join(pending)
    if unfinished:
        return 1, "승인 작업 미완료 — " + ", ".join(unfinished)
    if not report["review_complete"] or not report["close_checks_passed"]:
        return 1, "분류 또는 종료 확인 미완료"
    return 0, MARKER


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", required=True, type=Path,
                        help="UTF-8 원문: 이번 호출에서 사용자에게 보낸 분류 보고")
    args = parser.parse_args()
    try:
        classified = classified_candidates(args.classification.read_text(encoding="utf-8-sig"))
        status, message = check_close(json.load(sys.stdin), classified)
    except (OSError, ValueError) as error:
        print(f"종료 판정 입력 오류 — {error}", file=sys.stderr)
        return 2
    print(message)
    return status


if __name__ == "__main__":
    sys.exit(main())
