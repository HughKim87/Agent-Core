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

    def test_missing_required_section_is_detected(self) -> None:
        findings = self._findings(VALID_STATE.replace("## 차단", "## 다른 절"))
        self.assertTrue(any("필수 절" in finding.message for finding in findings))

    def test_dynamic_git_number_is_detected(self) -> None:
        findings = self._findings(VALID_STATE.replace("- 없음", "- 추적 파일 40", 1))
        self.assertTrue(any("동적 Git 수치" in finding.message for finding in findings))

    def test_vague_first_action_is_detected(self) -> None:
        findings = self._findings(
            VALID_STATE.replace("1. `PROJECT_RULES.md`의 선언을 파싱한다.", "1. 확인한다.")
        )
        self.assertTrue(any("모호" in finding.message for finding in findings))

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

    def test_size_budget_is_enforced(self) -> None:
        findings = self._findings(VALID_STATE + ("x" * 3_000))
        self.assertTrue(any("예산" in finding.message for finding in findings))


if __name__ == "__main__":
    unittest.main()
