"""무결성 검사의 결함 탐지 검증.

각 검사가 실제로 결함을 잡는지 주입 fixture로 확인한다. 정상 상태에서 오류 0으로
통과하는 것만으로는 검사가 동작한다고 말할 수 없다.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core_check import run_all  # noqa: E402
from core_check.integrity import run_consumer  # noqa: E402
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

<!-- core-rule-routes:v1 -->
| 행동 | 읽을 소유자 |
|---|---|
| 표본 행동 | [표본 규칙](rules/sample.md) |
<!-- /core-rule-routes:v1 -->

## 5. 끝
"""

STATE_BODY = """# 상태 표본

{headers}
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

1. 아무것도 하지 않는다.
"""

RULE_BODY = """# 표본 규칙

{headers}
본문.
"""

DOCUMENT_ROLES_BODY = """# 문서 역할 표본

{headers}
<!-- core-document-roles:v2 -->
```json
{{
  "core_policy": "ROUTER.md",
  "consumer_policy": "PROJECT_RULES.md"
}}
```
"""

COMPATIBILITY_BODY = """# 호환성 표본

{headers}
<!-- core-compatibility:v1 -->
```json
{{
  "core_version": "0.2.0",
  "contract_version": 2,
  "python_min": "3.10",
  "required_dependencies": [],
  "optional_dependencies": [],
  "optional_capabilities": {{}}
}}
```
"""

CONSUMER_POLICY_BODY = """# 소비 정책 표본

{headers}
<!-- agent-core-consumer:v1 -->
```json
{{
  "contract_version": 2,
  "consumer_role": "host",
  "core_path": "core",
  "state": "CURRENT.md",
  "entry_pointers": {{
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md"
  }},
  "rule_roots": ["rules"],
  "protected_paths": ["private"]
}}
```
<!-- /agent-core-consumer:v1 -->

<!-- core-rule-routes:v1 -->
| 행동 | 읽을 소유자 |
|---|---|
| 소비 행동 | [소비 규칙](rules/project.md) |
<!-- /core-rule-routes:v1 -->
"""


def layers_body(layers: dict[str, list[str]]) -> str:
    payload = json.dumps(layers, ensure_ascii=False, indent=2)
    return f"""# 계층 배정 표본

{DOC_HEADERS}
<!-- core-module-layers:v1 -->
```json
{payload}
```
"""


def write_layers(root: Path, layers: dict[str, list[str]]) -> None:
    (root / "docs" / "ARCHITECTURE.md").write_text(layers_body(layers), encoding="utf-8")


def build_clean(root: Path) -> None:
    (root / "rules").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "src" / "core_check").mkdir(parents=True)
    (root / "ROUTER.md").write_text(ROUTER_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
    (root / "docs" / "OWNERSHIP.md").write_text(
        DOCUMENT_ROLES_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
    )
    (root / "docs" / "COMPATIBILITY.md").write_text(
        COMPATIBILITY_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
    )
    (root / "rules" / "sample.md").write_text(RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
    (root / "src" / "core_check" / "primitives.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "core_check" / "integrity.py").write_text(
        "from .primitives import VALUE\n", encoding="utf-8"
    )
    write_layers(
        root,
        {
            "L5": ["src/core_check/integrity.py"],
            "L6": ["src/core_check/primitives.py"],
            "L7": [],
        },
    )
    (root / "data.json").write_text('{"a": 1}\n', encoding="utf-8")


def build_consumer(base: Path) -> tuple[Path, Path]:
    consumer = base / "consumer"
    core = consumer / "core"
    consumer.mkdir(parents=True)
    build_clean(core)
    (consumer / "rules").mkdir()
    (consumer / "rules" / "project.md").write_text(
        RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
    )
    (consumer / "PROJECT_RULES.md").write_text(
        CONSUMER_POLICY_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
    )
    (consumer / "CURRENT.md").write_text(
        STATE_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
    )
    (consumer / "AGENTS.md").write_text(
        "# Agent Entry\n\n[Core](core/ROUTER.md)\n[Policy](PROJECT_RULES.md)\n[State](CURRENT.md)\n",
        encoding="utf-8",
    )
    (consumer / "CLAUDE.md").write_text(
        "# Claude Entry\n\n@core/ROUTER.md\n@PROJECT_RULES.md\n@CURRENT.md\n",
        encoding="utf-8",
    )
    (consumer / ".gitmodules").write_text(
        '[submodule "core"]\n\tpath = core\n\turl = https://example.invalid/core.git\n',
        encoding="utf-8",
    )
    return core, consumer


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

    def test_accepts_lf_and_crlf_line_endings(self) -> None:
        (self.root / "lf.json").write_bytes(b'{\n  "a": 1\n}\n')
        (self.root / "crlf.json").write_bytes(b'{\r\n  "a": 1\r\n}\r\n')
        self.assertEqual(findings_for(self.root, "text-encoding"), [])

    def test_detects_trailing_whitespace_before_crlf(self) -> None:
        (self.root / "data.json").write_bytes(b'{"a": 1} \r\n')
        self.assertTrue(findings_for(self.root, "text-encoding"))

    def test_detects_nul_byte(self) -> None:
        (self.root / "data.json").write_bytes(b'{"a": 1}\x00\n')
        self.assertTrue(findings_for(self.root, "text-encoding"))

    def test_detects_missing_document_headers(self) -> None:
        (self.root / "rules" / "sample.md").write_text("# 헤더 없음\n\n본문만 있다.\n" * 40, encoding="utf-8")
        self.assertTrue(findings_for(self.root, "document-headers"))

    def test_detects_missing_headers_on_short_root_document(self) -> None:
        (self.root / "README.md").write_text("# 짧은 개요\n", encoding="utf-8")
        self.assertTrue(findings_for(self.root, "document-headers"))

    def test_clean_core_documents_have_required_headers(self) -> None:
        self.assertEqual(findings_for(self.root, "document-headers"), [])

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
        (self.root / "src" / "core_check" / "runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
        write_layers(
            self.root,
            {
                "L5": ["src/core_check/integrity.py"],
                "L6": ["src/core_check/primitives.py"],
                "L7": ["src/core_check/runtime.py"],
            },
        )
        (self.root / "src" / "core_check" / "integrity.py").write_text(
            "from .runtime import VALUE\n", encoding="utf-8"
        )
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("L7" in m for m in messages), messages)

    def test_detects_import_cycle(self) -> None:
        pkg = self.root / "src" / "core_check"
        (pkg / "alpha.py").write_text("from .beta import X\n", encoding="utf-8")
        (pkg / "beta.py").write_text("from .alpha import Y\n", encoding="utf-8")
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("순환" in m for m in messages), messages)

    def test_detects_unassigned_module(self) -> None:
        (self.root / "src" / "core_check" / "unassigned.py").write_text("VALUE = 3\n", encoding="utf-8")
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("배정 수가 0" in m for m in messages), messages)

    def test_detects_duplicate_module_assignment(self) -> None:
        write_layers(
            self.root,
            {
                "L5": ["src/core_check/integrity.py"],
                "L6": ["src/core_check/primitives.py", "src/core_check/integrity.py"],
                "L7": [],
            },
        )
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("배정 수가 2" in m for m in messages), messages)

    def test_detects_hardcoded_document_name(self) -> None:
        (self.root / "src" / "core_check" / "integrity.py").write_text(
            'from .primitives import VALUE\nTARGET = "ROUTER.md"\n', encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "no-hardcoded-doc-names"))

    def test_detects_duplicate_core_role_declaration(self) -> None:
        (self.root / "SECOND.md").write_text(
            DOCUMENT_ROLES_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "declaration-contracts"))

    def test_human_headings_do_not_define_policy_role(self) -> None:
        router = (self.root / "ROUTER.md").read_text(encoding="utf-8").replace(
            "## 4. 규칙 라우팅", "## 행동 소유자"
        )
        (self.root / "ROUTER.md").write_text(router, encoding="utf-8")
        self.assertEqual(findings_for(self.root, "declaration-contracts"), [])
        self.assertEqual(findings_for(self.root, "rule-routes"), [])

    def test_detects_reference_to_temporary_material(self) -> None:
        (self.root / "tmp").mkdir()
        (self.root / "tmp" / "note.md").write_text("메모\n", encoding="utf-8")
        (self.root / "rules" / "sample.md").write_text(
            RULE_BODY.format(headers=DOC_HEADERS) + "\n[한시 자료](tmp/note.md)\n", encoding="utf-8"
        )
        self.assertTrue(findings_for(self.root, "temporary-canonical-links"))


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
    """Core·consumer scope 선택의 결정론과 예산 강제."""

    def setUp(self) -> None:
        from core_check import context

        self.context = context
        self.tmp = tempfile.mkdtemp()
        self.core, self.consumer = build_consumer(Path(self.tmp))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_required_is_core_policy_consumer_policy_and_state(self) -> None:
        package = self.context.build(self.core, self.consumer)
        self.assertEqual(len(package.required), 3)
        self.assertEqual(
            [ref.identifier for ref in package.required],
            ["core:ROUTER.md", "consumer:PROJECT_RULES.md", "consumer:CURRENT.md"],
        )

    def test_unmatched_rule_is_excluded_with_reason(self) -> None:
        package = self.context.build(self.core, self.consumer)
        self.assertIn("core:rules/sample.md", package.excluded)
        self.assertIn("consumer:rules/project.md", package.excluded)

    def test_matched_rule_is_included(self) -> None:
        package = self.context.build(self.core, self.consumer, ["core:rules/sample.md"])
        self.assertEqual([ref.identifier for ref in package.optional], ["core:rules/sample.md"])
        self.assertNotIn("core:rules/sample.md", package.excluded)

    def test_same_input_gives_same_digest(self) -> None:
        first = self.context.build(self.core, self.consumer, ["consumer:rules/project.md"])
        second = self.context.build(self.core, self.consumer, ["consumer:rules/project.md"])
        self.assertEqual(first.digest, second.digest)

    def test_different_selection_gives_different_digest(self) -> None:
        first = self.context.build(self.core, self.consumer)
        second = self.context.build(self.core, self.consumer, ["core:rules/sample.md"])
        self.assertNotEqual(first.digest, second.digest)

    def test_unrouted_owner_is_rejected(self) -> None:
        from core_check.primitives import CheckError

        with self.assertRaises(CheckError):
            self.context.build(self.core, self.consumer, ["core:rules/does-not-exist.md"])

    def test_budget_overflow_fails_instead_of_truncating(self) -> None:
        with self.assertRaises(self.context.ContextBudgetError):
            self.context.build(self.core, self.consumer, budget=10)

    def test_failure_knowledge_is_not_in_default_selection(self) -> None:
        failures = self.core / "failures"
        failures.mkdir()
        (failures / "case.md").write_text(RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
        package = self.context.build(self.core, self.consumer)
        self.assertIn("core:failures/case.md", package.excluded)

    def test_startup_context_is_within_budget(self) -> None:
        package = self.context.build(self.core, self.consumer)
        self.assertLessEqual(package.chars, self.context.STARTUP_BUDGET_CHARS)
        self.assertEqual(len(package.required), 3)


class ConsumerContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.core, self.consumer = build_consumer(Path(self.tmp))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_consumer_contract_passes(self) -> None:
        report = run_consumer(self.core, self.consumer)
        self.assertTrue(report.ok, [finding.as_dict() for finding in report.findings])

    def test_contract_version_mismatch_is_detected(self) -> None:
        policy = self.consumer / "PROJECT_RULES.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace('"contract_version": 2', '"contract_version": 99'),
            encoding="utf-8",
        )
        self.assertFalse(run_consumer(self.core, self.consumer).ok)

    def test_entry_order_mismatch_is_detected(self) -> None:
        (self.consumer / "AGENTS.md").write_text(
            "# Entry\n\n[Policy](PROJECT_RULES.md)\n[Core](core/ROUTER.md)\n[State](CURRENT.md)\n",
            encoding="utf-8",
        )
        findings = run_consumer(self.core, self.consumer).findings
        self.assertTrue(any(finding.check == "consumer-entry" for finding in findings))

    def test_protected_path_is_not_read(self) -> None:
        private = self.consumer / "private"
        private.mkdir()
        (private / "secret.txt").write_text("do-not-read\n", encoding="utf-8")
        report = run_consumer(self.core, self.consumer)
        self.assertTrue(report.ok, [finding.as_dict() for finding in report.findings])

    def test_protected_path_cannot_overlap_rule_root(self) -> None:
        policy = self.consumer / "PROJECT_RULES.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                '"protected_paths": ["private"]',
                '"protected_paths": ["rules/private"]',
            ),
            encoding="utf-8",
        )
        findings = run_consumer(self.core, self.consumer).findings
        self.assertTrue(any(finding.check == "consumer-contract" for finding in findings))


class FailureAbsorptionTest(unittest.TestCase):
    """실패 예방책은 규칙·테스트가 소유하고 예외 문서는 최소 정보만 갖는다."""

    def test_each_existing_failure_case_is_absorbed_or_has_one_nonobvious_residue(self) -> None:
        cases = sorted((ROOT / "failures").glob("*.md"))
        cases = [path for path in cases if path.name != "README.md"]
        for path in cases:
            text = path.read_text(encoding="utf-8")
            if "- 상태: 흡수 완료, 종료 대기." in text:
                owners = [line for line in text.splitlines() if line.startswith("- 예방 소유자:")]
                self.assertEqual(len(owners), 1, path.name)
                self.assertNotIn("## 예방", text, path.name)
            elif "- 상태: 최소 유지." in text:
                residues = [line for line in text.splitlines() if line.startswith("- 비자명 잔여:")]
                self.assertEqual(len(residues), 1, path.name)
            else:
                self.fail(f"{path.name}의 흡수·최소 유지 판정이 없다")


@unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 commit snapshot fixture를 건너뛴다")
class CommitSnapshotTest(unittest.TestCase):
    """작업 트리 통과가 완료 commit snapshot 통과를 대신하지 못한다."""

    def test_clean_clone_exposes_worktree_only_route_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            clone = base / "clone"
            root.mkdir()
            build_clean(root)

            def git(*args: str, cwd: Path = root) -> None:
                subprocess.run(
                    [shutil.which("git") or "git", *args],
                    cwd=cwd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

            git("init", "--quiet")
            git("config", "user.name", "Core Snapshot Test")
            git("config", "user.email", "core-snapshot@example.invalid")
            git("add", ".")
            git("commit", "--quiet", "-m", "baseline")

            router = (root / "ROUTER.md").read_text(encoding="utf-8").replace(
                "<!-- /core-rule-routes:v1 -->",
                "| 작업 트리 전용 | [늦게 추가된 규칙](rules/late.md) |\n<!-- /core-rule-routes:v1 -->",
            )
            (root / "ROUTER.md").write_text(router, encoding="utf-8")
            (root / "rules" / "late.md").write_text(
                RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8"
            )
            self.assertTrue(run_all(root).ok)

            git("add", "ROUTER.md")
            git("commit", "--quiet", "-m", "broken candidate")
            git("clone", "--quiet", str(root), str(clone), cwd=base)

            report = run_all(clone)
            self.assertFalse(report.ok)
            self.assertTrue(
                any(f.check in {"markdown-links", "rule-routes"} for f in report.findings),
                [f.as_dict() for f in report.findings],
            )


class PublicInterfaceTest(unittest.TestCase):
    """공개 인터페이스의 정상·오류·경계 동작."""

    def setUp(self) -> None:
        from core_check import cli

        self.cli = cli
        self.tmp = tempfile.mkdtemp()
        self.core, self.consumer = build_consumer(Path(self.tmp))

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
        code, payload = self._run("--core-root", str(self.core), "verify")
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["contract_version"], 2)
        self.assertEqual(payload["scope"], "core")

    def test_deprecated_root_alias_still_verifies_core(self) -> None:
        code, payload = self._run("--root", str(self.core), "verify")
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertTrue(payload["ok"])

    def test_verify_returns_one_on_findings(self) -> None:
        (self.core / "data.json").write_text("{broken", encoding="utf-8")
        code, payload = self._run("--core-root", str(self.core), "verify")
        self.assertEqual(code, self.cli.EXIT_FINDINGS)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["findings"])

    def test_missing_root_returns_two(self) -> None:
        code, payload = self._run("--core-root", str(self.core / "nope"), "verify")
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertIn("error", payload)

    def test_context_command_reports_selection(self) -> None:
        code, payload = self._run(
            "--core-root",
            str(self.core),
            "--consumer-root",
            str(self.consumer),
            "context",
            "--rule",
            "core:rules/sample.md",
        )
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertIn({"scope": "core", "path": "rules/sample.md"}, payload["optional"])
        self.assertEqual(len(payload["required"]), 3)

    def test_context_rejects_unrouted_rule_with_structured_error(self) -> None:
        code, payload = self._run(
            "--core-root",
            str(self.core),
            "--consumer-root",
            str(self.consumer),
            "context",
            "--rule",
            "core:rules/nope.md",
        )
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertEqual(payload["kind"], "CheckError")

    def test_context_requires_consumer_root(self) -> None:
        code, payload = self._run("--core-root", str(self.core), "context")
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertEqual(payload["kind"], "CheckError")

    def test_verify_can_include_consumer_contract(self) -> None:
        code, payload = self._run(
            "--core-root", str(self.core), "--consumer-root", str(self.consumer), "verify"
        )
        self.assertEqual(code, self.cli.EXIT_OK)
        self.assertEqual(payload["scope"], "core+consumer")

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
        self.assertEqual(result.failed_step, "core-integrity")

    def test_preflight_failure_marks_later_steps_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "placeholder.txt").write_text("x\n", encoding="utf-8")
            result = self.gate.run(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.failed_step, "preflight-contract")
            statuses = {s.name: s.status for s in result.steps}
            self.assertEqual(statuses["core-integrity"], "not_run")
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

    def test_consumer_gate_passes_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            before_core = self.gate.tree_digest(core)
            before_consumer = self.gate.consumer_tree_digest(core, consumer)
            result = self.gate.run(core, consumer)
            self.assertTrue(result.ok, result.as_dict())
            self.assertEqual(before_core, self.gate.tree_digest(core))
            self.assertEqual(before_consumer, self.gate.consumer_tree_digest(core, consumer))


class CompatibilityTest(unittest.TestCase):
    """선언과 실제 동작의 일치."""

    def setUp(self) -> None:
        from core_check import gate

        self.gate = gate
        self.declared = gate.declared_compatibility(ROOT)

    def test_declaration_exists_and_is_complete(self) -> None:
        for key in (
            "core_version",
            "contract_version",
            "python_min",
            "required_dependencies",
            "optional_capabilities",
        ):
            self.assertIn(key, self.declared)

    def test_no_optional_capability_is_public_before_implementation(self) -> None:
        self.assertEqual(self.declared["optional_capabilities"], {})

    def test_declaration_is_the_only_source(self) -> None:
        from core_check.declarations import COMPAT_BLOCK

        # 제외 판정은 저장소 뿌리 기준 상대 경로로 한다. 절대 경로로 판정하면
        # 저장소가 `tmp` 같은 이름의 디렉터리 아래에 체크아웃될 때 전부 건너뛴다.
        blocks = [
            p
            for p in ROOT.rglob("*.md")
            if not {".git", "tmp"} & set(p.relative_to(ROOT).parts)
            and COMPAT_BLOCK.search(p.read_text(encoding="utf-8"))
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
            compatibility = root / "docs" / "COMPATIBILITY.md"
            compatibility.write_text(
                compatibility.read_text(encoding="utf-8").replace(
                    '"python_min": "3.10"', '"python_min": "99.0"'
                ),
                encoding="utf-8",
            )
            result = self.gate.run(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.failed_step, "preflight-runtime")
