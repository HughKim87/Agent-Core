"""무결성 검사의 결함 탐지 검증.

각 검사가 실제로 결함을 잡는지 주입 fixture로 확인한다. 정상 상태에서 오류 0으로
통과하는 것만으로는 검사가 동작한다고 말할 수 없다.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core_check import run_all  # noqa: E402
from core_check.primitives import UnsafePathError, fingerprint, resolve_inside  # noqa: E402

DOC_HEADERS = """- 목적: 결함 주입용 표본.
- 읽는 시점: 검사 확인 시.
- 책임: 테스트.
- 상태: 표본.
- 관련 권위: 없음.
"""

ROUTER_BODY = """# 라우터 표본

{headers}
## 4. 규칙 라우팅

| 행동 | 읽을 소유자 |
|---|---|
| 표본 행동 | [표본 규칙](rules/sample.md) |

## 5. 끝
"""

STATE_BODY = """# 상태 표본

{headers}
## 첫 다음 행동

1. 아무것도 하지 않는다.
"""

RULE_BODY = """# 표본 규칙

{headers}
본문.
"""


def build_clean(root: Path) -> None:
    (root / "rules").mkdir(parents=True)
    (root / "src" / "core_check").mkdir(parents=True)
    (root / "ROUTER.md").write_text(ROUTER_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
    (root / "CURRENT.md").write_text(STATE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
    (root / "rules" / "sample.md").write_text(RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
    (root / "src" / "core_check" / "primitives.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "core_check" / "integrity.py").write_text(
        "from .primitives import VALUE\n", encoding="utf-8"
    )
    (root / "data.json").write_text('{"a": 1}\n', encoding="utf-8")


def findings_for(root: Path, check: str) -> list[str]:
    return [f.message for f in run_all(root).findings if f.check == check]


class BaselineTest(unittest.TestCase):
    def test_clean_tree_passes_with_zero_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_clean(root)
            report = run_all(root)
            self.assertTrue(report.ok, [f.as_dict() for f in report.findings])
            self.assertEqual(report.findings, [])

    def test_optional_absence_is_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_clean(root)
            report = run_all(root)
            self.assertIn("optional-checks", report.skipped)
            self.assertTrue(report.ok)


class FaultInjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        build_clean(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_broken_link(self) -> None:
        (self.root / "rules" / "sample.md").write_text(
            RULE_BODY.format(headers=DOC_HEADERS) + "\n[없는 문서](missing.md)\n", encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "markdown-links"))

    def test_detects_invalid_json(self) -> None:
        (self.root / "data.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(findings_for(self.root, "json-parse"))

    def test_detects_python_syntax_error(self) -> None:
        (self.root / "src" / "core_check" / "broken.py").write_text("def (:\n", encoding="utf-8")
        self.assertTrue(findings_for(self.root, "python-ast"))

    def test_detects_trailing_whitespace(self) -> None:
        (self.root / "data.json").write_text('{"a": 1} \n', encoding="utf-8")
        self.assertTrue(findings_for(self.root, "text-encoding"))

    def test_detects_nul_byte(self) -> None:
        (self.root / "data.json").write_bytes(b'{"a": 1}\x00\n')
        self.assertTrue(findings_for(self.root, "text-encoding"))

    def test_detects_missing_document_headers(self) -> None:
        (self.root / "rules" / "sample.md").write_text("# 헤더 없음\n\n본문만 있다.\n" * 40, encoding="utf-8")
        self.assertTrue(findings_for(self.root, "document-headers"))

    def test_detects_unrouted_rule(self) -> None:
        (self.root / "rules" / "orphan.md").write_text(
            RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "rule-routes"))

    def test_detects_duplicate_route(self) -> None:
        body = ROUTER_BODY.format(headers=DOC_HEADERS).replace(
            "| 표본 행동 | [표본 규칙](rules/sample.md) |",
            "| 표본 행동 | [표본 규칙](rules/sample.md) |\n| 중복 | [표본 규칙](rules/sample.md) |",
        )
        (self.root / "ROUTER.md").write_text(body, encoding="utf-8")
        self.assertTrue(findings_for(self.root, "rule-routes"))

    def test_detects_rule_cross_routing(self) -> None:
        (self.root / "rules" / "other.md").write_text(
            RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
        )
        (self.root / "rules" / "sample.md").write_text(
            RULE_BODY.format(headers=DOC_HEADERS) + "\n[다른 규칙](other.md)\n", encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "rule-cross-routing"))

    def test_detects_l6_importing_internal_module(self) -> None:
        (self.root / "src" / "core_check" / "primitives.py").write_text(
            "from .integrity import VALUE\n", encoding="utf-8"
        )
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("L6" in m for m in messages), messages)

    def test_detects_l5_importing_experimental(self) -> None:
        (self.root / "src" / "core_check" / "integrity.py").write_text(
            "import experimental.runtime\n", encoding="utf-8"
        )
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("L7" in m for m in messages), messages)

    def test_detects_import_cycle(self) -> None:
        pkg = self.root / "src" / "core_check"
        (pkg / "alpha.py").write_text("from .beta import X\n", encoding="utf-8")
        (pkg / "beta.py").write_text("from .alpha import Y\n", encoding="utf-8")
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("순환" in m for m in messages), messages)

    def test_detects_hardcoded_document_name(self) -> None:
        (self.root / "src" / "core_check" / "integrity.py").write_text(
            'from .primitives import VALUE\nTARGET = "CURRENT.md"\n', encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "no-hardcoded-doc-names"))

    def test_detects_duplicate_state_owner(self) -> None:
        (self.root / "SECOND.md").write_text(STATE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
        self.assertTrue(findings_for(self.root, "state-canonical-owner"))

    def test_detects_reference_to_temporary_material(self) -> None:
        (self.root / "tmp").mkdir()
        (self.root / "tmp" / "note.md").write_text("메모\n", encoding="utf-8")
        (self.root / "rules" / "sample.md").write_text(
            RULE_BODY.format(headers=DOC_HEADERS) + "\n[한시 자료](tmp/note.md)\n", encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "state-canonical-owner"))


class PrimitivesTest(unittest.TestCase):
    def test_resolve_inside_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsafePathError):
                resolve_inside(Path(tmp), "../outside")

    def test_resolve_inside_accepts_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve_inside(root, "a/b").parent.name, "a")

    def test_fingerprint_is_deterministic(self) -> None:
        self.assertEqual(fingerprint("같은 입력"), fingerprint("같은 입력"))
        self.assertNotEqual(fingerprint("가"), fingerprint("나"))


class RealRepositoryTest(unittest.TestCase):
    def test_repository_passes_with_zero_errors(self) -> None:
        report = run_all(ROOT)
        self.assertTrue(report.ok, [f.as_dict() for f in report.findings])


if __name__ == "__main__":
    unittest.main()


class DerivedArtifactTest(unittest.TestCase):
    """파생 artifact 관리의 결정론과 drift 탐지."""

    def setUp(self) -> None:
        from core_check import derived

        self.derived = derived
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        build_clean(self.root)
        if "upper" not in derived.GENERATORS:
            derived.generator("upper")(str.upper)
        (self.root / "source.md").write_text("abc\n", encoding="utf-8")
        (self.root / "derived-artifacts.json").write_text(
            '{"artifacts": [{"source": "source.md", "target": "out.txt", "generator": "upper"}]}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_artifact(self) -> None:
        entry = self.derived.load_declaration(self.root)[0]
        (self.root / "out.txt").write_text(
            self.derived.regenerate(self.root, entry), encoding="utf-8"
        )

    def test_absent_declaration_is_not_a_failure(self) -> None:
        (self.root / "derived-artifacts.json").unlink()
        self.assertEqual(findings_for(self.root, "derived-artifacts"), [])

    def test_regeneration_is_deterministic(self) -> None:
        entry = self.derived.load_declaration(self.root)[0]
        first = self.derived.regenerate(self.root, entry)
        second = self.derived.regenerate(self.root, entry)
        self.assertEqual(first, second)

    def test_regenerated_artifact_passes(self) -> None:
        self._write_artifact()
        self.assertEqual(findings_for(self.root, "derived-artifacts"), [])

    def test_detects_missing_artifact(self) -> None:
        self.assertTrue(findings_for(self.root, "derived-artifacts"))

    def test_detects_manual_edit_of_artifact(self) -> None:
        self._write_artifact()
        (self.root / "out.txt").write_text("직접 고쳤다\n", encoding="utf-8")
        self.assertTrue(findings_for(self.root, "derived-artifacts"))

    def test_detects_source_change_without_regeneration(self) -> None:
        self._write_artifact()
        (self.root / "source.md").write_text("xyz\n", encoding="utf-8")
        self.assertTrue(findings_for(self.root, "derived-artifacts"))

    def test_detects_duplicate_target(self) -> None:
        (self.root / "derived-artifacts.json").write_text(
            '{"artifacts": ['
            '{"source": "source.md", "target": "out.txt", "generator": "upper"},'
            '{"source": "source.md", "target": "out.txt", "generator": "upper"}]}\n',
            encoding="utf-8",
        )
        self._write_artifact()
        messages = findings_for(self.root, "derived-artifacts")
        self.assertTrue(any("정본이 둘 이상" in m for m in messages), messages)

    def test_detects_unknown_generator(self) -> None:
        (self.root / "derived-artifacts.json").write_text(
            '{"artifacts": [{"source": "source.md", "target": "out.txt", "generator": "없음"}]}\n',
            encoding="utf-8",
        )
        self.assertTrue(findings_for(self.root, "derived-artifacts"))

    def test_rejects_target_outside_root(self) -> None:
        with self.assertRaises(UnsafePathError):
            resolve_inside(self.root, "../escape.txt")


class ContextTest(unittest.TestCase):
    """선택적 문서 읽기의 결정론과 예산 강제."""

    def setUp(self) -> None:
        from core_check import context

        self.context = context
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        build_clean(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_required_is_router_and_state_only(self) -> None:
        package = self.context.build(self.root)
        self.assertEqual(len(package.required), 2)
        self.assertIn("ROUTER.md", package.required)
        self.assertIn("CURRENT.md", package.required)

    def test_unmatched_rule_is_excluded_with_reason(self) -> None:
        package = self.context.build(self.root)
        self.assertIn("rules/sample.md", package.excluded)
        self.assertTrue(package.excluded["rules/sample.md"])

    def test_matched_rule_is_included(self) -> None:
        package = self.context.build(self.root, ["rules/sample.md"])
        self.assertIn("rules/sample.md", package.optional)
        self.assertNotIn("rules/sample.md", package.excluded)

    def test_same_input_gives_same_digest(self) -> None:
        first = self.context.build(self.root, ["rules/sample.md"])
        second = self.context.build(self.root, ["rules/sample.md"])
        self.assertEqual(first.digest, second.digest)

    def test_different_selection_gives_different_digest(self) -> None:
        first = self.context.build(self.root)
        second = self.context.build(self.root, ["rules/sample.md"])
        self.assertNotEqual(first.digest, second.digest)

    def test_unrouted_owner_is_rejected(self) -> None:
        from core_check.primitives import CheckError

        with self.assertRaises(CheckError):
            self.context.build(self.root, ["rules/does-not-exist.md"])

    def test_budget_overflow_fails_instead_of_truncating(self) -> None:
        with self.assertRaises(self.context.ContextBudgetError):
            self.context.build(self.root, budget=10)

    def test_failure_knowledge_is_not_in_default_selection(self) -> None:
        failures = self.root / "failures"
        failures.mkdir()
        (failures / "case.md").write_text(RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
        package = self.context.build(self.root)
        self.assertIn("failures/case.md", package.excluded)

    def test_real_repository_startup_context_is_within_budget(self) -> None:
        package = self.context.build(ROOT)
        self.assertLessEqual(package.chars, self.context.STARTUP_BUDGET_CHARS)
        self.assertEqual(len(package.required), 2)


class PublicInterfaceTest(unittest.TestCase):
    """공개 인터페이스의 정상·오류·경계 동작."""

    def setUp(self) -> None:
        from core_check import cli

        self.cli = cli
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        build_clean(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *argv: str) -> tuple[int, dict]:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.cli.main(list(argv))
        return code, json.loads(buffer.getvalue())

    def test_verify_returns_zero_on_clean_tree(self) -> None:
        code, payload = self._run("--root", str(self.root), "verify")
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertTrue(payload["ok"])

    def test_verify_returns_one_on_findings(self) -> None:
        (self.root / "data.json").write_text("{broken", encoding="utf-8")
        code, payload = self._run("--root", str(self.root), "verify")
        self.assertEqual(code, self.cli.EXIT_FINDINGS)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["findings"])

    def test_missing_root_returns_two(self) -> None:
        code, payload = self._run("--root", str(self.root / "nope"), "verify")
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertIn("error", payload)

    def test_context_command_reports_selection(self) -> None:
        code, payload = self._run("--root", str(self.root), "context", "--rule", "rules/sample.md")
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertIn("rules/sample.md", payload["optional"])
        self.assertEqual(len(payload["required"]), 2)

    def test_context_rejects_unrouted_rule_with_structured_error(self) -> None:
        code, payload = self._run("--root", str(self.root), "context", "--rule", "rules/nope.md")
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertEqual(payload["kind"], "CheckError")

    def test_every_public_command_has_a_consumer_note(self) -> None:
        import inspect

        from core_check import cli

        commands = [f for name, f in vars(cli).items() if name.startswith("cmd_")]
        self.assertTrue(commands)
        for fn in commands:
            self.assertIn("소비자", inspect.getdoc(fn) or "")

    def test_no_third_party_dependency(self) -> None:
        import ast as ast_module

        stdlib = set(sys.stdlib_module_names)
        for path in sorted((ROOT / "src" / "core_check").glob("*.py")):
            tree = ast_module.parse(path.read_text(encoding="utf-8"))
            for node in ast_module.walk(tree):
                if isinstance(node, ast_module.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], stdlib, path.name)


class GateRobustnessTest(unittest.TestCase):
    """게이트 자체의 실패 처리. 자체 운영 시나리오에서 발견된 결함의 회귀."""

    def _run(self, *argv: str) -> tuple[int, dict]:
        import contextlib
        import io

        from core_check import cli

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(list(argv))
        return code, json.loads(buffer.getvalue())

    def test_unexpected_error_is_structured_not_traceback(self) -> None:
        from core_check import cli

        original = cli.run_all
        cli.run_all = lambda root: (_ for _ in ()).throw(RuntimeError("예상 못한 오류"))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                code, payload = self._run("--root", tmp, "verify")
            self.assertEqual(code, cli.EXIT_UNUSABLE)
            self.assertTrue(payload["unexpected"])
            self.assertEqual(payload["kind"], "RuntimeError")
        finally:
            cli.run_all = original

    def test_unusable_root_is_distinguished_from_findings(self) -> None:
        from core_check import cli

        with tempfile.TemporaryDirectory() as tmp:
            code, payload = self._run("--root", tmp, "context")
        self.assertEqual(code, cli.EXIT_UNUSABLE)
        self.assertNotEqual(code, cli.EXIT_FINDINGS)
        self.assertIn("error", payload)


class IntegrationGateTest(unittest.TestCase):
    """통합 게이트의 단계 결과, 상태 구분, 부작용 없음.

    실제 저장소 전체를 대상으로 게이트를 돌리면 게이트가 회귀 테스트를 하위
    프로세스로 실행하므로 이 테스트 자체가 다시 실행된다. 재진입 방지가 있어도
    시간이 배로 든다. 따라서 단위 테스트는 합성 트리만 사용하고 실제 저장소
    게이트는 CLI 종단 호출로 별도 확인한다.
    """

    def setUp(self) -> None:
        from core_check import gate

        self.gate = gate
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        build_clean(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_tree_gate_passes(self) -> None:
        result = self.gate.run(self.root)
        self.assertTrue(result.ok, result.as_dict())
        self.assertIsNone(result.failed_step)

    def test_gate_does_not_modify_working_tree(self) -> None:
        before = self.gate.tree_digest(self.root)
        self.gate.run(self.root)
        self.assertEqual(before, self.gate.tree_digest(self.root))

    def test_optional_absence_is_not_applicable_not_fail(self) -> None:
        result = self.gate.run(self.root)
        optional = [s for s in result.steps if s.name == "optional-features"][0]
        self.assertEqual(optional.status, "not_applicable")
        self.assertFalse(optional.required)
        self.assertTrue(result.ok)

    def test_not_applicable_does_not_fail_but_not_run_does(self) -> None:
        result = self.gate.run(self.root)
        regression = [s for s in result.steps if s.name == "regression-tests"][0]
        self.assertEqual(regression.status, "not_applicable")
        self.assertTrue(regression.required)
        self.assertTrue(result.ok, "not_applicable 은 실패가 아니다")

    def test_single_required_failure_fails_whole_gate(self) -> None:
        (self.root / "data.json").write_text("{broken", encoding="utf-8")
        result = self.gate.run(self.root)
        self.assertFalse(result.ok)
        self.assertEqual(result.failed_step, "integrity")

    def test_preflight_failure_marks_later_steps_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "placeholder.txt").write_text("x\n", encoding="utf-8")
            result = self.gate.run(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.failed_step, "preflight-layout")
            statuses = {s.name: s.status for s in result.steps}
            self.assertEqual(statuses["integrity"], "not_run")
            self.assertEqual(statuses["regression-tests"], "not_run")

    def test_reentry_is_blocked(self) -> None:
        import os

        (self.root / "tests").mkdir()
        os.environ[self.gate.REENTRY_FLAG] = "1"
        try:
            result = self.gate.run(self.root)
        finally:
            os.environ.pop(self.gate.REENTRY_FLAG, None)
        step = [s for s in result.steps if s.name == "regression-tests"][0]
        self.assertEqual(step.status, "not_applicable")
        self.assertIn("재진입", step.detail)

    def test_gate_result_is_reproducible(self) -> None:
        first = self.gate.run(self.root).as_dict()
        second = self.gate.run(self.root).as_dict()
        self.assertEqual(first["ok"], second["ok"])
        self.assertEqual(
            [(s["name"], s["status"]) for s in first["steps"]],
            [(s["name"], s["status"]) for s in second["steps"]],
        )


class CompatibilityTest(unittest.TestCase):
    """선언과 실제 동작의 일치."""

    def setUp(self) -> None:
        from core_check import gate

        self.gate = gate
        self.declared = gate.declared_compatibility(ROOT)

    def test_declaration_exists_and_is_complete(self) -> None:
        for key in ("core_version", "contract_version", "python_min", "required_dependencies"):
            self.assertIn(key, self.declared)

    def test_declaration_is_the_only_source(self) -> None:
        # 제외 판정은 저장소 뿌리 기준 상대 경로로 한다. 절대 경로로 판정하면
        # 저장소가 `tmp` 같은 이름의 디렉터리 아래에 체크아웃될 때 전부 건너뛴다.
        blocks = [
            p
            for p in ROOT.rglob("*.md")
            if not {".git", "tmp"} & set(p.relative_to(ROOT).parts)
            and self.gate.COMPAT_BLOCK.search(p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(len(blocks), 1, f"호환성 선언이 {len(blocks)}곳에 있다")

    def test_running_runtime_satisfies_declaration(self) -> None:
        minimum = tuple(int(p) for p in self.declared["python_min"].split("."))
        self.assertGreaterEqual(sys.version_info[: len(minimum)], minimum)

    def test_no_required_dependencies_declared_and_none_used(self) -> None:
        self.assertEqual(self.declared["required_dependencies"], [])

    def test_gate_reads_minimum_from_declaration_not_constant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_clean(root)
            (root / "docs").mkdir()
            (root / "docs" / "c.md").write_text(
                "<!-- core-compatibility:v1 -->\n```json\n"
                '{"python_min": "99.0"}\n```\n<!-- /core-compatibility -->\n',
                encoding="utf-8",
            )
            result = self.gate.run(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.failed_step, "preflight-runtime")
