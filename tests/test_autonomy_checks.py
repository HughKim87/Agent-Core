"""공개 검사에서 의미 검토 진단과 확정 계약 실패의 경계를 검증한다."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_integrity import build_consumer
from core_check import cli, gate
from core_check.context import ContextBudgetError
from core_check.primitives import CheckError


class AutonomyChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.core, self.consumer = build_consumer(Path(self.tmp.name))
        self.args = ["--core-root", str(self.core), "--consumer-root", str(self.consumer)]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, command: str, *options: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main([*self.args, command, *options])
        return code, json.loads(output.getvalue())

    def _long_state_with_expression_variations(self) -> None:
        state = self.consumer / "CURRENT.md"
        text = state.read_text(encoding="utf-8").replace(
            "1. `CURRENT.md`의 현재 단계 절을 파싱한다.",
            "1. Parse the declaration in `PROJECT_RULES.md` and report missing fields.",
        )
        # A required decision set can be large without being a schema violation.
        decisions = "\n".join(
            f"- 입력 조건 {number}: 승인된 대상의 호환성·실패 복구 조건과 확인할 근거를 유지한다. "
            "명시적인 사용자 제외 범위는 변경하지 않는다."
            for number in range(350)
        )
        text = text.replace("## 승인 상태", decisions + "\n\n## 승인 상태")
        state.write_text(text + "\n## 완료 기준\n\n- 현재 결과의 성공 조건을 확인한다.\n", encoding="utf-8")

    def test_long_state_and_expression_variations_are_visible_in_verify_and_gate(self) -> None:
        self._long_state_with_expression_variations()
        code, verified = self._run("verify")
        self.assertEqual(code, cli.EXIT_OK, verified)
        self.assertEqual(verified["error_count"], 0)
        self.assertGreaterEqual(verified["warning_count"], 3)
        self.assertEqual(verified["semantic_review"], "not_assessed")
        self.assertIsInstance(verified["review_guidance"], str)
        self.assertTrue(verified["review_guidance"])
        self.assertTrue(all(f["severity"] == "warning" for f in verified["findings"]))

        code, checked = self._run("gate")
        self.assertEqual(code, cli.EXIT_OK, checked)
        consumer = next(s for s in checked["steps"] if s["name"] == "consumer-integrity")
        self.assertEqual(consumer["evidence"]["findings"], verified["findings"])
        self.assertEqual(consumer["evidence"]["review_guidance"], verified["review_guidance"])
        self.assertIn("검토 경고", consumer["detail"])
        self.assertNotIn("위반 0", consumer["detail"])
        self.assertEqual(consumer["evidence"]["assessment_scope"], "structure-and-diagnostics")
        context = next(s for s in checked["steps"] if s["name"] == "startup-context")
        self.assertEqual(context["status"], "pass")
        self.assertGreater(context["evidence"]["chars"], 20_000)
        self.assertTrue(context["evidence"]["diagnostics"])
        self.assertTrue(context["evidence"]["review_guidance"])
        self.assertGreater(checked["warning_count"], verified["warning_count"])

    def test_context_and_gate_only_enforce_explicit_budget_and_do_not_truncate(self) -> None:
        self._long_state_with_expression_variations()
        code, package = self._run("context")
        self.assertEqual(code, cli.EXIT_OK, package)
        self.assertIsNone(package["budget"])
        self.assertGreater(package["chars"], package["review_threshold"])
        self.assertEqual(package["warning_count"], len(package["diagnostics"]))
        self.assertTrue(package["review_guidance"])
        code, exact = self._run("context", "--budget", str(package["chars"]))
        self.assertEqual(code, cli.EXIT_OK, exact)
        self.assertEqual((package["chars"], package["digest"], package["required"]),
                         (exact["chars"], exact["digest"], exact["required"]))
        code, rejected = self._run("context", "--budget", str(package["chars"] - 1))
        self.assertEqual(code, cli.EXIT_UNUSABLE, rejected)
        self.assertEqual(rejected["kind"], "ContextBudgetError")
        code, exact_gate = self._run("gate", "--budget", str(package["chars"]))
        self.assertEqual(code, cli.EXIT_OK, exact_gate)
        code, rejected_gate = self._run("gate", "--budget", str(package["chars"] - 1))
        self.assertEqual(code, cli.EXIT_FINDINGS, rejected_gate)
        self.assertEqual(rejected_gate["failed_step"], "startup-context")

    def test_gate_budget_validation_rejects_invalid_or_unbound_limits(self) -> None:
        for value in (0, -1, True, 1.5, "20"):
            with self.subTest(value=value), self.assertRaisesRegex(ContextBudgetError, "양의 정수"):
                gate.run(self.core, self.consumer, budget=value)
        code, rejected = self._run("gate", "--budget", "0")
        self.assertEqual(code, cli.EXIT_UNUSABLE, rejected)
        self.assertEqual(rejected["kind"], "ContextBudgetError")
        with self.assertRaisesRegex(CheckError, "consumer-root"):
            gate.run(self.core, budget=100_000)

    def test_alternate_document_description_and_reference_link_are_review_diagnostics(self) -> None:
        (self.core / "README.md").write_text(
            "# Overview\n\nPurpose: project guidance.\nRead during setup.\n"
            "Owner: maintainer.\nStatus: active.\nAuthority: project policy.\n", encoding="utf-8",
        )
        policy = self.core / "ROUTER.md"
        policy.write_text(policy.read_text(encoding="utf-8").replace(
            "<!-- /core-rule-routes:v1 -->",
            "| 다른 행동 | [다른 규칙](rules/other.md) |\n<!-- /core-rule-routes:v1 -->",
        ), encoding="utf-8")
        sample = self.core / "rules" / "sample.md"
        (sample.parent / "other.md").write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        sample.write_text(sample.read_text(encoding="utf-8") +
                          "\n책임 비교를 위한 [참고](other.md).\n", encoding="utf-8")
        code, verified = self._run("verify")
        self.assertEqual(code, cli.EXIT_OK, verified)
        diagnostics = {f["check"] for f in verified["findings"] if f["severity"] == "warning"}
        self.assertEqual(diagnostics, {"document-headers", "rule-cross-routing"})

    def test_real_contract_and_protected_path_failures_still_block_with_warnings(self) -> None:
        self._long_state_with_expression_variations()
        state = self.consumer / "CURRENT.md"
        state.write_text(state.read_text(encoding="utf-8").replace("## 차단", "## 다른 절"), encoding="utf-8")
        code, verified = self._run("verify")
        self.assertEqual(code, cli.EXIT_FINDINGS, verified)
        self.assertGreater(verified["error_count"], 0)
        self.assertGreater(verified["warning_count"], 0)
        self.assertTrue(verified["review_guidance"])
        code, checked = self._run("gate")
        self.assertEqual(code, cli.EXIT_FINDINGS, checked)
        self.assertEqual(checked["failed_step"], "consumer-integrity")
        consumer = next(s for s in checked["steps"] if s["name"] == "consumer-integrity")
        self.assertTrue(consumer["evidence"]["review_guidance"])
        self.assertEqual(next(s for s in checked["steps"] if s["name"] == "startup-context")["status"], "not_run")
        policy = self.consumer / "PROJECT_RULES.md"
        policy.write_text(policy.read_text(encoding="utf-8").replace(
            '"protected_paths": ["private"]', '"protected_paths": ["../outside"]',
        ), encoding="utf-8")
        code, verified = self._run("verify")
        self.assertEqual(code, cli.EXIT_UNUSABLE, verified)
        self.assertFalse(verified["ok"])

    def test_subprocess_cli_emits_success_and_warnings_without_python_cache(self) -> None:
        self._long_state_with_expression_variations()
        source = str(Path(__file__).resolve().parents[1] / "src")
        runner = f"import runpy,sys; sys.path.insert(0, {source!r}); runpy.run_module('core_check', run_name='__main__')"
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", runner, *self.args, "verify"],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(completed.returncode, cli.EXIT_OK, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertGreater(payload["warning_count"], 0)
        self.assertEqual(payload["error_count"], 0)
        self.assertTrue(payload["review_guidance"])

    def test_sufficient_expression_is_not_rewritten_to_clear_a_warning(self) -> None:
        state = self.consumer / "CURRENT.md"
        state.write_text(state.read_text(encoding="utf-8").replace(
            "1. `CURRENT.md`의 현재 단계 절을 파싱한다.",
            "1. Parse the consumer contract in PROJECT_RULES.md and report missing fields.",
        ), encoding="utf-8")
        original = state.read_bytes()
        code, result = self._run("verify")
        self.assertEqual(code, cli.EXIT_OK, result)
        self.assertGreater(result["warning_count"], 0)
        self.assertTrue(result["review_guidance"])
        self.assertEqual(result["semantic_review"], "not_assessed")
        self.assertEqual(state.read_bytes(), original)

    def test_actual_quality_repair_clears_diagnostics_without_changing_checker_policy(self) -> None:
        # This test supplies the semantic repair; the checker does not act as an AI.
        state = self.consumer / "CURRENT.md"
        policy = self.consumer / "PROJECT_RULES.md"
        original_state = state.read_text(encoding="utf-8")
        original_policy = policy.read_text(encoding="utf-8")
        state.write_text(original_state.replace(
            "1. `CURRENT.md`의 현재 단계 절을 파싱한다.", "1. 계속 진행한다.",
        ), encoding="utf-8")
        policy.write_text(original_policy.replace("- 목적: 결함 주입용 표본.\n", ""), encoding="utf-8")
        before_state, before_policy = state.read_bytes(), policy.read_bytes()
        code, before = self._run("verify")
        self.assertEqual(code, cli.EXIT_OK, before)
        self.assertEqual({f["check"] for f in before["findings"]},
                         {"consumer-state", "consumer-document-headers"})
        self.assertTrue(before["review_guidance"])
        self.assertEqual((state.read_bytes(), policy.read_bytes()), (before_state, before_policy))
        # Restore the required purpose and an executable, targeted next action.
        state.write_text(original_state, encoding="utf-8")
        policy.write_text(original_policy, encoding="utf-8")
        code, after = self._run("verify")
        self.assertEqual(code, cli.EXIT_OK, after)
        self.assertEqual(after["findings"], [])
        self.assertIsNone(after["review_guidance"])
        self.assertEqual(after["semantic_review"], "not_assessed")
        code, context = self._run("context")
        self.assertEqual(code, cli.EXIT_OK, context)
        self.assertEqual(context["diagnostics"], [])
        self.assertIsNone(context["review_guidance"])


if __name__ == "__main__":
    unittest.main()
