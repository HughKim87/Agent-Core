"""소비 저장소가 제공하는 현재 상태 계약의 결함 주입 검사."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core_check.integrity import state_contract_findings  # noqa: E402

VALID_STATE = """# 상태 표본

- 목적: 현재 작업 상태.
- 읽는 시점: 세션 시작 시.
- 책임: 작업 에이전트.
- 상태: 활성 정본.
- 관련 권위: 소비 정책.

## 현재 단계

- 단계: 표본

## 직전 게이트

- 결과: `pass`

## 승인 상태

- 읽기 전용

## 차단

- 없음

## 알려진 위험

- 없음

## 첫 다음 행동

1. `PROJECT_RULES.md`의 선언을 파싱한다.
"""


class StateContractTest(unittest.TestCase):
    def _findings(self, text: str) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "CURRENT.md"
            state.write_text(text, encoding="utf-8")
            return state_contract_findings(root, state)

    def test_valid_consumer_state_passes(self) -> None:
        self.assertEqual(self._findings(VALID_STATE), [])

    def test_comment_markers_inside_code_spans_preserve_following_sections(self) -> None:
        for literal in ("`<!--`", "``literal ` <!--``", "`<!-- -->` <!-- actual comment -->"):
            with self.subTest(literal=literal):
                text = VALID_STATE.replace("## 차단", f"- literal: {literal}\n\n## 차단", 1)
                self.assertEqual(self._findings(text), [])

    def test_real_comment_after_code_span_still_hides_fake_sections(self) -> None:
        text = VALID_STATE.replace("## 차단", "- literal: `<!--` <!--\n## 차단", 1)
        self.assertTrue(any("## 차단" in f.message for f in self._findings(text)))

    def test_missing_required_section_is_detected(self) -> None:
        findings = self._findings(VALID_STATE.replace("## 차단", "## 다른 절"))
        self.assertTrue(any("필수 절" in finding.message for finding in findings))

    def test_dynamic_git_number_is_detected(self) -> None:
        findings = self._findings(VALID_STATE.replace("- 없음", "- 추적 파일 40", 1))
        self.assertTrue(any("동적 Git 수치" in finding.message for finding in findings))

    def test_file_count_variants_are_detected(self) -> None:
        for value in (
            "- 변경 대상 8개 파일",
            "- 변경 파일 8개",
            "- 변경된 파일은 8개다",
            "- 8개의 파일",
            "- 변경 파일: 8개",
            "- 여덟 개 경로",
            "- 변경 대상은 8개의 파일이다",
            "- 파일도 8개다",
            "- 파일은 총 8개다",
            "- 파일은 `8`개다",
            "- 파일 개수는 8개다",
            "- 경로 수는 8개다",
            "- 변경 파일 수: 8개",
        ):
            with self.subTest(value=value):
                findings = self._findings(VALID_STATE.replace("- 없음", value, 1))
                self.assertTrue(any("파일 개수" in finding.message for finding in findings))

    def test_file_count_does_not_match_profile_compound(self) -> None:
        for value in (
            "- 실행 프로파일 8개를 활성화한다",
            "- 이 파일은 8개 항목을 포함한다",
            "- 이 경로는 8개 문자로 구성된다",
            "- 이 파일 수는 8개 항목을 포함한다",
        ):
            with self.subTest(value=value):
                text = VALID_STATE.replace("- 없음", value, 1)
                self.assertFalse(
                    any("파일 개수" in finding.message for finding in self._findings(text))
                )

    def test_structured_ephemeral_failure_fields_are_detected(self) -> None:
        for field in (
            "- 실패 횟수: 2",
            "- 시도 방법: shell",
            "- 방법 순서: shell, api",
            "- 중단 상태: true",
            '- "failure_count": 2',
            "| attempted_methods | shell |",
            "- lastAttemptOrder: shell, api",
            "- stop_state: true",
            "- 실패 사건 이력: 1차 shell, 2차 api",
            "- failure_event_history: shell, api",
        ):
            with self.subTest(field=field):
                findings = self._findings(VALID_STATE.replace("- 없음", field, 1))
                self.assertTrue(any("임시 실패 상태" in finding.message for finding in findings))

    def test_general_failure_policy_text_is_not_ephemeral_state(self) -> None:
        for value in (
            "실패를 예방하는 정책을 적용한다",
            "실패 카운터 정책 검증은 아직 `not_run`이다",
            "failure counter policy verification is `not_run`",
            "현재 차단 원인은 계약 불일치다",
            "재시작 조건: 사용자가 계약을 선택한다",
        ):
            with self.subTest(value=value):
                text = VALID_STATE.replace("- 없음", f"- {value}", 1)
                self.assertFalse(
                    any("임시 실패 상태" in finding.message for finding in self._findings(text))
                )

    def test_vague_first_action_is_detected(self) -> None:
        for value in (
            "1. 확인한다.",
            "1. 계속한다.",
            "1. 다음 단계",
            "1. 다음 작업을 진행한다.",
            "1. 다음/후속 작업을 진행한다.",
            "1. `TODO`를 확인한다.",
        ):
            with self.subTest(value=value):
                findings = self._findings(
                    VALID_STATE.replace("1. `PROJECT_RULES.md`의 선언을 파싱한다.", value)
                )
                self.assertTrue(any("모호" in finding.message for finding in findings))

    def test_specific_first_action_may_end_with_check_verb(self) -> None:
        for value in (
            "1. `core/rules/handoff.md`의 필수 절을 확인한다.",
            "1. 승인 상태 절에 미승인 범위가 남아 있는지 확인한다.",
        ):
            with self.subTest(value=value):
                text = VALID_STATE.replace(
                    "1. `PROJECT_RULES.md`의 선언을 파싱한다.", value
                )
                self.assertFalse(any("모호" in finding.message for finding in self._findings(text)))

    def test_missing_numbered_action_is_detected(self) -> None:
        findings = self._findings(
            VALID_STATE.replace("1. `PROJECT_RULES.md`의 선언을 파싱한다.", "선언을 파싱한다.")
        )
        self.assertTrue(any("번호" in finding.message for finding in findings))

    def test_accumulated_gate_history_is_detected(self) -> None:
        findings = self._findings(
            VALID_STATE.replace("- 결과: `pass`", "- 첫 결과: `pass`\n- 둘째 결과: `fail`")
        )
        self.assertTrue(any("누적" in finding.message for finding in findings))

    def test_korean_accumulated_gate_history_is_detected(self) -> None:
        findings = self._findings(
            VALID_STATE.replace("- 결과: `pass`", "- 첫 판정: 통과\n- 둘째 판정: 실패")
        )
        self.assertTrue(any("누적" in finding.message for finding in findings))

    def test_two_gate_judgments_on_one_line_are_detected(self) -> None:
        findings = self._findings(
            VALID_STATE.replace(
                "- 결과: `pass`", "- 이전 판정: 통과 / 현재 판정: 실패"
            )
        )
        self.assertTrue(any("누적" in finding.message for finding in findings))

    def test_missing_gate_judgment_is_detected(self) -> None:
        findings = self._findings(VALID_STATE.replace("- 결과: `pass`", "- 결과 대기"))
        self.assertTrue(any("판정이 없다" in finding.message for finding in findings))

    def test_english_gate_token_uses_word_boundaries(self) -> None:
        for artifact in ("compass.json", "pass.json", "fail.md", "not_run.json"):
            with self.subTest(artifact=artifact):
                text = VALID_STATE.replace(
                    "- 결과: `pass`", f"- 결과: `pass`\n- 산출물: {artifact}"
                )
                self.assertFalse(
                    any("누적" in finding.message for finding in self._findings(text))
                )

    def test_korean_gate_judgment_accepts_sentence_punctuation(self) -> None:
        for judgment in ("통과.", "실패.", "통과)"):
            with self.subTest(judgment=judgment):
                text = VALID_STATE.replace("- 결과: `pass`", f"- 결과: {judgment}")
                findings = self._findings(text)
                self.assertFalse(
                    any(
                        "판정이 없다" in finding.message or "누적" in finding.message
                        for finding in findings
                    )
                )

    def test_heading_mention_does_not_satisfy_required_section(self) -> None:
        text = VALID_STATE.replace(
            "## 차단\n\n- 없음",
            "## 다른 절\n\n- 본문에서 `## 차단` 문자열을 언급한다",
        )
        findings = self._findings(text)
        self.assertTrue(any("필수 절" in finding.message for finding in findings))

    def test_completed_detail_section_is_detected(self) -> None:
        for heading in ("완료 상세", "완료 작업", "작업 이력", "과거 판정"):
            with self.subTest(heading=heading):
                findings = self._findings(VALID_STATE + f"\n## {heading}\n\n- 과거 과정\n")
                self.assertTrue(any("완료 상세" in finding.message for finding in findings))

    def test_incomplete_section_is_not_completed_history(self) -> None:
        findings = self._findings(VALID_STATE + "\n## 미완료 작업\n\n- 현재 남은 일\n")
        self.assertFalse(any("완료 상세" in finding.message for finding in findings))

    def test_fenced_heading_does_not_satisfy_required_section(self) -> None:
        text = VALID_STATE.replace(
            "## 차단\n\n- 없음",
            "## 다른 절\n\n```md\n## 차단\n```",
        )
        findings = self._findings(text)
        self.assertTrue(any("필수 절" in finding.message for finding in findings))

    def test_shorter_fence_does_not_close_longer_fence(self) -> None:
        text = VALID_STATE.replace(
            "## 차단\n\n- 없음",
            "## 다른 절\n\n````md\n```\n## 차단\n````",
        )
        findings = self._findings(text)
        self.assertTrue(any("필수 절" in finding.message for finding in findings))

    def test_indented_and_closing_hash_heading_is_valid(self) -> None:
        text = VALID_STATE.replace("## 차단", "   ## 차단 ##")
        self.assertFalse(
            any("필수 절이 없다: ## 차단" in finding.message for finding in self._findings(text))
        )

    def test_duplicate_required_sections_are_detected(self) -> None:
        for section in (
            "현재 단계", "직전 게이트", "승인 상태",
            "차단", "알려진 위험", "첫 다음 행동",
        ):
            with self.subTest(section=section):
                findings = self._findings(VALID_STATE + f"\n## {section}\n")
                self.assertTrue(any(
                    f"필수 절이 중복됐다: ## {section}" in finding.message
                    for finding in findings
                ))

    def test_fenced_examples_do_not_replace_real_declarations(self) -> None:
        declarations = (
            ("- 결과: `pass`", "판정이 없다"),
            ("1. `PROJECT_RULES.md`의 선언을 파싱한다.", "번호"),
        )
        for fence in ("```", "~~~", "````"):
            for declaration, expected in declarations:
                with self.subTest(fence=fence, declaration=declaration):
                    text = VALID_STATE.replace(
                        declaration, f"{fence}md\n{declaration}\n{fence}"
                    )
                    self.assertTrue(any(
                        expected in finding.message for finding in self._findings(text)
                    ))

    def test_fenced_examples_beside_real_declarations_are_ignored(self) -> None:
        for fence in ("```", "~~~", "````"):
            with self.subTest(fence=fence):
                text = VALID_STATE.replace(
                    "- 결과: `pass`",
                    f"- 결과: `pass`\n{fence}md\n- 예시: `fail`\n"
                    f"## 직전 게이트\n{fence}",
                ).replace(
                    "1. `PROJECT_RULES.md`의 선언을 파싱한다.",
                    f"1. `PROJECT_RULES.md`의 선언을 파싱한다.\n"
                    f"{fence}md\n1. 계속한다.\n## 첫 다음 행동\n{fence}",
                )
                self.assertEqual(self._findings(text), [])


    def test_indented_examples_do_not_replace_real_declarations(self) -> None:
        for indent in ("    ", "\t", "  \t"):
            for declaration, expected in (
                ("- 결과: `pass`", "판정이 없다"),
                ("1. `PROJECT_RULES.md`의 선언을 파싱한다.", "번호"),
            ):
                with self.subTest(indent=indent, declaration=declaration):
                    text = VALID_STATE.replace(declaration, indent + declaration)
                    self.assertTrue(any(
                        expected in finding.message for finding in self._findings(text)
                    ))

    def test_commented_examples_do_not_replace_real_declarations(self) -> None:
        for wrapper in ("<!--\n{}\n-->", "<!-- {} -->", "<!--\n{}"):
            for declaration, expected in (
                ("- 결과: `pass`", "판정이 없다"),
                ("1. `PROJECT_RULES.md`의 선언을 파싱한다.", "번호"),
            ):
                with self.subTest(wrapper=wrapper, declaration=declaration):
                    text = VALID_STATE.replace(declaration, wrapper.format(declaration))
                    self.assertTrue(any(
                        expected in finding.message for finding in self._findings(text)
                    ))

    def test_commented_headings_do_not_satisfy_required_sections(self) -> None:
        text = VALID_STATE.replace("## 차단", "<!--\n## 차단\n-->")
        self.assertTrue(any(
            "필수 절이 없다: ## 차단" in finding.message
            for finding in self._findings(text)
        ))

    def test_examples_beside_real_declarations_are_ignored(self) -> None:
        for example in (
            "    - 예시: `fail`\n    ## 직전 게이트",
            "\t- 예시: `fail`\n\t## 직전 게이트",
            "<!--\n- 예시: `fail`\n## 직전 게이트\n\u0060\u0060\u0060\n-->",
            "<!-- 예시: `fail` --> <!-- 예시: `fail` -->",
        ):
            with self.subTest(example=example):
                text = VALID_STATE.replace(
                    "- 결과: `pass`", "- 결과: `pass`\n" + example
                )
                self.assertEqual(self._findings(text), [])

    def test_comments_and_code_do_not_hide_later_real_declarations(self) -> None:
        for example in (
            "\u0060\u0060\u0060md\n<!--\n\u0060\u0060\u0060",
            "    <!--",
            "<!--\n    -->",
        ):
            with self.subTest(example=example):
                self.assertEqual(self._findings(
                    VALID_STATE.replace("- 결과: `pass`", example + "\n- 결과: `pass`")
                ), [])

    def test_inline_comments_are_ignored_without_losing_real_judgment(self) -> None:
        text = VALID_STATE.replace(
            "- 결과: `pass`", "- 결과: <!-- 예시: `fail` --> `pass` <!-- 설명 -->"
        )
        self.assertEqual(self._findings(text), [])

    def test_up_to_three_spaces_preserve_real_declarations(self) -> None:
        for indent in ("", " ", "  ", "   "):
            with self.subTest(indent=indent):
                text = VALID_STATE.replace("- 결과: `pass`", indent + "- 결과: `pass`")
                text = text.replace(
                    "1. `PROJECT_RULES.md`의 선언을 파싱한다.",
                    indent + "1. `PROJECT_RULES.md`의 선언을 파싱한다.",
                )
                self.assertEqual(self._findings(text), [])

    def test_size_budget_is_enforced(self) -> None:
        findings = self._findings(VALID_STATE + ("x" * 3_000))
        self.assertTrue(any("예산" in finding.message for finding in findings))


if __name__ == "__main__":
    unittest.main()
