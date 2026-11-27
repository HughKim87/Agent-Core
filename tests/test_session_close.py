"""Exercise the output used by the session-close workflow."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/session-close/current/scripts/check_close.py"
MARKER = "# 이 세션은 종료되었습니다"


class SessionCloseTest(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.classification = Path(folder.name) / "classification.md"

    def publish(self, roster):
        self.classification.write_text(
            "분류 보고\n\n분류 후보 — " + roster + "\n\n후보별 관측과 승인 요청.\n", encoding="utf-8"
        )

    def run_check(self, candidates, *, review_complete=True, close_checks_passed=True):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--classification", str(self.classification)],
            input=json.dumps({
                "review_complete": review_complete,
                "close_checks_passed": close_checks_passed,
                "candidates": candidates,
            }),
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_no_approval_and_no_reply_keeps_required_candidates_pending(self):
        self.publish("C1(필수), C2(필수), E1(필수), E2(선택)")
        result = self.run_check([
            {"id": "C1", "required": True, "state": "pending"},
            {"id": "C2", "required": True, "state": "pending"},
            {"id": "E1", "required": True, "state": "pending"},
            {"id": "E2", "required": False, "state": "not_selected"},
        ])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "결정 대기 — C1, C2, E1")
        self.assertNotIn(MARKER, result.stdout + result.stderr)

    def test_partial_deferral_leaves_other_candidates_pending(self):
        self.publish("C1(필수), C2(필수)")
        result = self.run_check([
            {"id": "C1", "required": True, "state": "deferred", "decision_ref": "user-message-1"},
            {"id": "C2", "required": True, "state": "pending"},
        ])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "결정 대기 — C2")
        self.assertNotIn(MARKER, result.stdout + result.stderr)

    def test_no_required_decision_and_explicit_deferral_allow_close(self):
        for roster, candidates in (
            ("없음", []),
            ("E2(선택)", [{"id": "E2", "required": False, "state": "not_selected"}]),
            ("E2(근거 부족)", [{"id": "E2", "required": False, "state": "not_selected"}]),
            ("C1(필수)", [{"id": "C1", "required": True, "state": "deferred", "decision_ref": "user-message-1"}]),
            ("C1(필수)", [{"id": "C1", "required": True, "state": "completed", "decision_ref": "user-message-1"}]),
        ):
            with self.subTest(roster=roster, candidates=candidates):
                self.publish(roster)
                result = self.run_check(candidates)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), MARKER)

    def test_approved_work_or_close_checks_incomplete(self):
        self.publish("C1(필수)")
        approved = self.run_check([{"id": "C1", "required": True, "state": "approved"}])
        self.publish("없음")
        for result in (approved, self.run_check([], review_complete=False), self.run_check([], close_checks_passed=False)):
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(MARKER, result.stdout + result.stderr)

    def test_required_candidate_cannot_be_silently_dropped_or_deferred(self):
        self.publish("C1(필수)")
        for candidate in (
            {"id": "C1", "required": True, "state": "not_selected"},
            {"id": "C1", "required": True, "state": "deferred"},
            {"id": f"C1\n{MARKER}", "required": True, "state": "pending"},
        ):
            with self.subTest(candidate=candidate):
                result = self.run_check([candidate])
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(MARKER, result.stdout + result.stderr)

    def test_original_report_controls_membership_and_requirement(self):
        self.publish("C1(필수), C2(필수)")
        done = {"id": "C1", "required": True, "state": "completed", "decision_ref": "user-1"}
        for candidates, reason in (
            ([done], "후보 누락 — C2"),
            ([], "후보 누락 — C1, C2"),
            ([done, {"id": "C2", "required": False, "state": "not_selected"}], "필수 여부 불일치 — C2"),
            ([done, {"id": "E1", "required": False, "state": "not_selected"}], "보고에 없는 후보 — E1"),
        ):
            with self.subTest(reason=reason):
                result = self.run_check(candidates)
                self.assertEqual(result.returncode, 2)
                self.assertIn(reason, result.stderr)
                self.assertNotIn(MARKER, result.stdout + result.stderr)
        both_done = self.run_check([dict(done, id="C2"), done])
        self.assertEqual(both_done.returncode, 0)

    def test_missing_or_ambiguous_classification_never_counts_as_empty(self):
        self.assertEqual(self.run_check([]).returncode, 2)
        for source in ("오래된 자유 형식 보고", "분류 후보 — 없음\n분류 후보 —", "분류 후보 — 없음\n분류 후보 — C1(필수)",
                       "분류 후보 — C1(필수), C1(선택)", "분류 후보 — C1(미분류)"):
            with self.subTest(source=source):
                self.classification.write_text(source, encoding="utf-8")
                result = self.run_check([])
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(MARKER, result.stdout + result.stderr)
