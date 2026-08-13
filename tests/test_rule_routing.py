"""규칙 route와 의미 재현 fixture의 구조·위생 검사.

이 모듈은 자연어 발화를 판정하지 않는다. 의미 선택은 별도의 콜드 Agent
재현으로 검증하며, 이 검사는 그 입력과 기대값이 유효한지만 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "POLICY.md"
RULES_DIR = ROOT / "rules"
FIXTURE = ROOT / "tests" / "fixtures" / "rule-routing-intents-v1.json"

ROUTING_SECTION = re.compile(r"^## 4\. 규칙 라우팅\s*$(.*?)^## ", re.M | re.S)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REQUIRED_KINDS = {"initial", "colloquial", "mid-task", "near-miss"}
REQUIRED_HEADERS = ("- 목적:", "- 읽는 시점:", "- 책임:", "- 상태:", "- 관련 권위:")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def routed_owners() -> list[str]:
    match = ROUTING_SECTION.search(read(ROUTER))
    if match is None:
        raise AssertionError("POLICY.md 에서 규칙 라우팅 절을 찾지 못했다")
    return [t for t in LINK.findall(match.group(1)) if t.startswith("rules/")]


def active_rules() -> list[str]:
    if not RULES_DIR.is_dir():
        return []
    return sorted(f"rules/{p.name}" for p in RULES_DIR.glob("*.md"))


class RoutingCompletenessTest(unittest.TestCase):
    def test_every_active_rule_is_routed_exactly_once(self) -> None:
        routes = routed_owners()
        for rule in active_rules():
            self.assertEqual(routes.count(rule), 1, f"{rule} 의 route 수가 1이 아니다")

    def test_no_orphan_route(self) -> None:
        for route in routed_owners():
            self.assertTrue((ROOT / route).is_file(), f"{route} 가 존재하지 않는다")

    def test_router_is_unique(self) -> None:
        others = [
            p
            for p in RULES_DIR.glob("*.md")
            if any(t.startswith("rules/") for t in LINK.findall(read(p)))
        ]
        self.assertEqual(others, [], "규칙 파일이 다른 규칙을 직접 라우팅한다")

    def test_rule_shape(self) -> None:
        for rule in active_rules():
            text = read(ROOT / rule)
            for header in REQUIRED_HEADERS:
                self.assertIn(header, text, f"{rule} 에 {header} 항목이 없다")


class FixtureStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(read(FIXTURE))
        self.cases = self.data["cases"]

    def test_case_ids_are_unique(self) -> None:
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_referenced_owners_are_routed(self) -> None:
        routes = set(routed_owners())
        for case in self.cases:
            for owner in case["expected_owners"] + case["forbidden_owners"]:
                self.assertIn(owner, routes, f"{case['id']} 가 라우팅되지 않은 소유자를 참조한다")

    def test_expected_and_forbidden_are_disjoint(self) -> None:
        for case in self.cases:
            overlap = set(case["expected_owners"]) & set(case["forbidden_owners"])
            self.assertEqual(overlap, set(), f"{case['id']} 의 기대·금지 소유자가 겹친다")

    def test_every_routed_rule_has_required_kinds(self) -> None:
        for rule in routed_owners():
            kinds = {
                c["kind"]
                for c in self.cases
                if rule in c["expected_owners"] or rule in c["forbidden_owners"]
            }
            self.assertTrue(
                REQUIRED_KINDS <= kinds,
                f"{rule} 에 누락된 케이스 종류: {sorted(REQUIRED_KINDS - kinds)}",
            )

    def test_has_composed_case_with_multiple_expected_owners(self) -> None:
        composed = [c for c in self.cases if c["kind"] == "composed"]
        self.assertTrue(composed, "둘 이상의 route가 필요한 composed 케이스가 없다")
        for case in composed:
            self.assertGreaterEqual(
                len(case["expected_owners"]),
                2,
                f"{case['id']} 가 여러 기대 소유자를 갖지 않는다",
            )

    def test_fixture_is_not_a_router(self) -> None:
        self.assertNotIn("router_owner", self.data)
        self.assertEqual(self.data["router"], "POLICY.md")


if __name__ == "__main__":
    unittest.main()
