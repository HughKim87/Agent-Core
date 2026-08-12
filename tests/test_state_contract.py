"""현재 상태 문서가 인수인계 계약을 따르는지 검사한다."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "STATE.md"

REQUIRED_SECTIONS = (
    "## 현재 단계",
    "## 직전 게이트",
    "## 승인 상태",
    "## 차단",
    "## 알려진 위험",
    "## 첫 다음 행동",
)

# 단계 수에 비례해 커지면 안 된다. 실측 기반 예산.
SIZE_BUDGET_CHARS = 3_000

# 문서에 고정하면 실제와 어긋나는 동적 수치
DYNAMIC_NUMBERS = re.compile(
    r"(추적 파일\s*\d+|untracked\s*\d+|ignored\s*\d+|커밋\s*\d+\s*개|"
    r"파일\s*\d+\s*개\s*추적|blob\s*\d+)"
)

VAGUE_ACTIONS = ("계속 진행한다", "검토한다.", "확인한다.")


class StateContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = STATE.read_text(encoding="utf-8")

    def test_required_sections_exist(self) -> None:
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, self.text, f"{section} 절이 없다")

    def test_no_dynamic_numbers(self) -> None:
        found = DYNAMIC_NUMBERS.findall(self.text)
        self.assertEqual(found, [], f"동적 수치가 고정되어 있다: {found}")

    def test_first_action_is_numbered_and_specific(self) -> None:
        tail = self.text.split("## 첫 다음 행동", 1)[1]
        actions = [l.strip() for l in tail.splitlines() if re.match(r"^\d+\.", l.strip())]
        self.assertTrue(actions, "첫 다음 행동이 번호 목록으로 없다")
        for action in actions:
            self.assertFalse(
                action.rstrip(".").endswith(VAGUE_ACTIONS),
                f"첫 다음 행동이 모호하다: {action}",
            )

    def test_single_state_owner(self) -> None:
        # 제외 판정은 저장소 뿌리 기준 상대 경로로 한다. 절대 경로로 판정하면
        # 저장소가 `tmp` 같은 이름의 디렉터리 아래에 체크아웃될 때 전부 건너뛴다.
        others = [
            p
            for p in ROOT.rglob("*.md")
            if not {".git", "tmp"} & set(p.relative_to(ROOT).parts)
            and p != STATE
            and "## 첫 다음 행동" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(others, [], "현재 상태 정본이 둘 이상이다")

    def test_no_completed_stage_history_accumulates(self) -> None:
        gates = self.text.split("## 직전 게이트", 1)[1].split("## 승인 상태", 1)[0]
        judged = [l for l in gates.splitlines() if "`pass`" in l or "`fail`" in l]
        self.assertLessEqual(
            len(judged), 1, f"직전 게이트 절에 판정이 {len(judged)}건 누적되어 있다"
        )

    def test_size_stays_within_budget(self) -> None:
        self.assertLessEqual(
            len(self.text),
            SIZE_BUDGET_CHARS,
            "현재 상태 문서가 예산을 넘었다. 완료 이력이 누적되었을 가능성이 높다",
        )


if __name__ == "__main__":
    unittest.main()
