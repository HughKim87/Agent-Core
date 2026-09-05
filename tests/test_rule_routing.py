"""규칙 route와 의미 재현 fixture의 구조·위생 검사.

이 모듈은 자연어 발화를 판정하지 않는다. 의미 선택은 별도의 콜드 Agent
재현으로 검증하며, 이 검사는 그 입력과 기대값이 유효한지만 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "rules"
FIXTURE = ROOT / "tests" / "fixtures" / "rule-routing-intents-v1.json"
FAILURE_FIXTURE = ROOT / "tests" / "fixtures" / "failure-stop-scenarios-v1.json"
sys.path.insert(0, str(ROOT / "src"))

from core_check.declarations import document_roles, routed_rule_paths  # noqa: E402

LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REQUIRED_KINDS = {"initial", "colloquial", "mid-task", "near-miss"}
REQUIRED_HEADERS = ("- 목적:", "- 읽는 시점:", "- 책임:", "- 상태:", "- 관련 권위:")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def routed_owners() -> list[str]:
    return routed_rule_paths(ROOT)


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

    def test_rule_governance_keeps_generalization_gate(self) -> None:
        text = read(ROOT / "rules" / "rule-governance.md")
        for fragment in (
            "## 2. Core 일반화 적합성 게이트",
            "서로 독립된 둘 이상의 실제 Consumer",
            "단일 Consumer 사건은 후보를 제기할 근거일 뿐",
            "적용되지 않는 near-miss",
            "현재 작업 문맥을 받지 않은 독립 Agent",
        ):
            self.assertIn(fragment, text)

    def test_work_contract_owns_completion_condition_reconciliation_once(self) -> None:
        heading = "### 완료 조건 대조"
        occurrences = [
            (f"rules/{path.name}", read(path).count(heading))
            for path in RULES_DIR.glob("*.md")
            if heading in read(path)
        ]
        self.assertEqual(occurrences, [("rules/work-contract.md", 1)])


class FixtureStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(read(FIXTURE))
        self.cases = self.data["cases"]

    def test_case_ids_are_unique(self) -> None:
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_selection_contract_is_exact(self) -> None:
        self.assertEqual(self.data["selection_contract"], "exact")

    def test_owner_lists_have_no_duplicates(self) -> None:
        for case in self.cases:
            for field in ("prior_owners", "expected_owners", "forbidden_owners"):
                owners = case[field]
                self.assertEqual(
                    len(owners),
                    len(set(owners)),
                    f"{case['id']} 의 {field}에 중복 소유자가 있다",
                )

    def test_referenced_owners_are_routed(self) -> None:
        routes = set(routed_owners())
        for case in self.cases:
            for owner in case["expected_owners"] + case["forbidden_owners"]:
                self.assertIn(owner, routes, f"{case['id']} 가 라우팅되지 않은 소유자를 참조한다")

    def test_expected_and_forbidden_are_disjoint(self) -> None:
        for case in self.cases:
            overlap = set(case["expected_owners"]) & set(case["forbidden_owners"])
            self.assertEqual(overlap, set(), f"{case['id']} 의 기대·금지 소유자가 겹친다")

    def test_expected_owners_are_new_for_this_transition(self) -> None:
        for case in self.cases:
            overlap = set(case["prior_owners"]) & set(case["expected_owners"])
            self.assertEqual(
                overlap,
                set(),
                f"{case['id']} 가 이미 읽은 소유자를 다시 기대한다: {sorted(overlap)}",
            )

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
        self.assertEqual(self.data["router"], f"core:{document_roles(ROOT)['core_policy']}")


class FailureStopScenarioTest(unittest.TestCase):
    """명령 창의 합성 이벤트 모델을 검사하며 정책 정본을 다시 소유하지 않는다."""

    def setUp(self) -> None:
        self.data = json.loads(read(FAILURE_FIXTURE))

    def test_fixture_contract_and_owner_metadata(self) -> None:
        self.assertEqual(self.data["fixture_version"], 3)
        self.assertEqual(self.data["evidence_level"], "synthetic-policy-model")
        self.assertIn("실제 Host Runtime 동작을 검증하지 않는다", self.data["purpose"])
        self.assertEqual(self.data["failure_limit"], 3)
        self.assertEqual(
            self.data["policy_roles"],
            {
                "canonical": "rules/failure-records.md",
                "route": "PROJECT_RULES.md",
                "delegate": "rules/work-contract.md",
                "reference": "rules/handoff.md",
            },
        )
        self.assertTrue(self.data["cases"], "failure scenarios must not be empty")
        ids = [case["id"] for case in self.data["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        required_ids = {
            "third-failure-blocks-fourth-result-attempt",
            "same-result-new-command-starts-at-zero",
            "correction-with-retry-does-not-inherit",
            "non-counting-events-do-not-consume-limit",
            "abandoned-tool-candidate-counts-once",
            "status-message-does-not-reset-active-command",
            "result-candidates-cannot-overrun-remaining-slots",
            "uncertain-external-effect-requires-state-check",
            "user-cancel-closes-command-window",
            "new-execution-command-preempts-stopped-window",
            "ordinary-result-candidates-are-serial",
        }
        self.assertTrue(required_ids <= set(ids), f"missing scenarios: {sorted(required_ids - set(ids))}")
        command_ids = [
            command["id"]
            for case in self.data["cases"]
            for command in case["commands"]
        ]
        self.assertEqual(len(command_ids), len(set(command_ids)))
        for case in self.data["cases"]:
            self.assertTrue(case["commands"], case["id"])
            for command in case["commands"]:
                self.assertIsInstance(command["opens_window"], bool)
                self.assertTrue(command["events"], command["id"])
                self.assertTrue(command["expected"], command["id"])
                self.assertEqual(len(command["events"]), len(command["expected"]), command["id"])
        self.assertNotIn("rule_fragments", self.data)

    def test_failure_policy_has_one_routed_owner(self) -> None:
        roles = self.data["policy_roles"]
        canonical = roles["canonical"]
        self.assertTrue((ROOT / canonical).is_file())
        self.assertEqual(routed_owners().count(canonical), 1)
        self.assertEqual(roles["route"], "PROJECT_RULES.md")
        self.assertNotEqual(roles["delegate"], canonical)
        self.assertNotEqual(roles["reference"], canonical)
        self.assertNotIn("(failure-records.md)", read(ROOT / roles["reference"]))

    def test_scenarios(self) -> None:
        limit = self.data["failure_limit"]
        for case in self.data["cases"]:
            for command in case["commands"]:
                count = 0
                stopped = False
                active_candidate = False
                awaiting_state_check = False
                command_open = command["opens_window"]
                actual = []
                for event in command["events"]:
                    kind = event["type"]
                    if kind in {
                        "failure",
                        "multi-gate-failure",
                        "candidate-abandoned-after-tool-error",
                    }:
                        if not command_open:
                            action = "no-command"
                        elif stopped:
                            action = "blocked"
                        elif not active_candidate:
                            action = "invalid-no-active-candidate"
                        else:
                            active_candidate = False
                            count += 1
                            if count >= limit:
                                stopped = True
                                action = "stop"
                            else:
                                action = "continue"
                    elif kind in {"result-attempt", "result-modification"}:
                        if not command_open:
                            action = "no-command"
                        elif stopped or active_candidate or awaiting_state_check:
                            action = "blocked"
                        else:
                            active_candidate = True
                            action = "allowed"
                    elif kind == "start-result-candidates":
                        remaining = max(limit - count, 0)
                        if (
                            command_open
                            and not stopped
                            and not active_candidate
                            and not awaiting_state_check
                            and event["candidates"] == 1
                            and remaining >= 1
                        ):
                            active_candidate = True
                            action = "allowed"
                        elif not command_open:
                            action = "no-command"
                        else:
                            action = "blocked"
                    elif kind == "uncertain-external-effect":
                        if not command_open:
                            action = "no-command"
                        elif stopped or not active_candidate:
                            action = "invalid-no-active-candidate"
                        else:
                            active_candidate = False
                            awaiting_state_check = True
                            action = "await-state-check"
                    elif kind == "state-check":
                        if awaiting_state_check:
                            awaiting_state_check = False
                            action = "state-checked"
                        else:
                            action = "no-pending-state"
                    elif kind == "user-cancel":
                        active_candidate = False
                        awaiting_state_check = False
                        command_open = False
                        count = 0
                        stopped = False
                        action = "closed"
                    elif kind == "new-user-execution-command":
                        active_candidate = False
                        awaiting_state_check = False
                        command_open = True
                        count = 0
                        stopped = False
                        action = "new-window"
                    elif kind == "safe-recovery":
                        action = "allowed-recovery" if command_open else "no-command"
                    elif kind == "minimal-read":
                        action = "allowed-read" if command_open else "no-command"
                    elif kind == "final-report":
                        active_candidate = False
                        awaiting_state_check = False
                        command_open = False
                        count = 0
                        stopped = False
                        action = "allowed-report"
                    elif kind in {
                        "diagnostic-miss",
                        "expected-red-test",
                        "recovered-tool-error",
                        "safe-stop",
                        "status-only",
                        "parallel-diagnostic",
                    }:
                        action = kind
                    else:
                        self.fail(
                            f"{case['id']}/{command['id']}에 알 수 없는 event type이 있다: {kind}"
                        )
                    actual.append({"count": count, "stopped": stopped, "action": action})
                self.assertEqual(actual, command["expected"], f"{case['id']}/{command['id']}")


if __name__ == "__main__":
    unittest.main()
