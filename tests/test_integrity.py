"""무결성 검사의 결함 탐지 검증.

각 검사가 실제로 결함을 잡는지 주입 fixture로 확인한다. 정상 상태에서 오류 0으로
통과하는 것만으로는 검사가 동작한다고 말할 수 없다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core_check import run_all  # noqa: E402
import core_check.integrity as integrity_module  # noqa: E402
from core_check.integrity import (  # noqa: E402
    host_core_cleanliness,
    host_core_git_fingerprint,
    run_consumer,
)
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

1. `CURRENT.md`의 현재 단계 절을 파싱한다.
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
  "consumer_role": "maintainer",
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


def declare_optional_shared_data(
    root: Path, *, partial: bool = False, installed: bool = False
) -> None:
    capability = {
        "shared_data": {
            "version": 1,
            "entry_module": "experimental.shared_data",
            "commands": ["info", "invoke"],
            "request_schema": "experimental/shared_data/schemas/request.json",
            "result_schema": "experimental/shared_data/schemas/result.json",
            "schemas": ["experimental/shared_data/schemas/common.json"],
        }
    }
    compatibility = root / "docs" / "COMPATIBILITY.md"
    compatibility.write_text(
        compatibility.read_text(encoding="utf-8").replace(
            '"optional_capabilities": {}',
            '"optional_capabilities": ' + json.dumps(capability, ensure_ascii=False),
        ),
        encoding="utf-8",
    )
    if partial and installed:
        raise ValueError("partial과 installed는 함께 사용할 수 없다")
    if partial or installed:
        module = root / "experimental" / "shared_data"
        module.mkdir(parents=True)
        (module / "__main__.py").write_text("\n", encoding="utf-8")
    if installed:
        schemas = root / "experimental" / "shared_data" / "schemas"
        schemas.mkdir()
        for name in ("request.json", "result.json", "common.json"):
            (schemas / name).write_text("{}\n", encoding="utf-8")


def build_clean(root: Path) -> None:
    (root / "rules").mkdir(parents=True)
    (root / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
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


def set_consumer_role(consumer: Path, role: str) -> None:
    policy = consumer / "PROJECT_RULES.md"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            '"consumer_role": "maintainer"', f'"consumer_role": "{role}"'
        ),
        encoding="utf-8",
    )


def refresh_raw_worktree_from_index(root: Path) -> None:
    staged = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    for record in (value for value in staged.split(b"\0") if value):
        header, separator, raw_relative = record.partition(b"\t")
        fields = header.split()
        if not separator or len(fields) != 3 or fields[0] not in {b"100644", b"100755"}:
            continue
        blob = subprocess.run(
            ["git", "cat-file", "blob", fields[1].decode("ascii")],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        root.joinpath(*raw_relative.decode("utf-8").split("/")).write_bytes(blob)
    subprocess.run(
        ["git", "add", "-A"],
        cwd=root,
        capture_output=True,
        check=True,
    )


def initialize_clean_git(root: Path) -> None:
    commands = (
        ["git", "init", "--quiet"],
        ["git", "config", "core.autocrlf", "false"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "user.name=Core Test",
            "-c",
            "user.email=core-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
    )
    for command in commands:
        subprocess.run(command, cwd=root, capture_output=True, check=True)
    refresh_raw_worktree_from_index(root)


def add_nested_gitlink(core: Path, base: Path) -> Path:
    source = base / "nested-source"
    source.mkdir()
    (source / ".gitignore").write_bytes(b"cache/\n")
    (source / "nested.txt").write_bytes(b"nested\n")
    initialize_clean_git(source)
    subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "--quiet",
            str(source),
            "nested",
        ],
        cwd=core,
        capture_output=True,
        check=True,
    )
    nested = core / "nested"
    subprocess.run(
        ["git", "config", "core.autocrlf", "false"],
        cwd=nested,
        capture_output=True,
        check=True,
    )
    refresh_raw_worktree_from_index(nested)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Core Test",
            "-c",
            "user.email=core-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-am",
            "nested fixture",
        ],
        cwd=core,
        capture_output=True,
        check=True,
    )
    return nested


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

    def test_declared_optional_capability_may_be_completely_absent(self) -> None:
        from core_check.declarations import declared_compatibility

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_clean(root)
            declare_optional_shared_data(root)
            declared = declared_compatibility(root)
            self.assertIn("shared_data", declared["optional_capabilities"])


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

    def test_allows_completely_absent_experimental_l7_group(self) -> None:
        write_layers(
            self.root,
            {
                "L5": ["src/core_check/integrity.py"],
                "L6": ["src/core_check/primitives.py"],
                "L7": [
                    "experimental/shared_data/__init__.py",
                    "experimental/shared_data/__main__.py",
                ],
            },
        )
        self.assertEqual(findings_for(self.root, "layer-boundaries"), [])

    def test_detects_partial_experimental_l7_group(self) -> None:
        module = self.root / "experimental" / "shared_data"
        module.mkdir(parents=True)
        (module / "__init__.py").write_text("\n", encoding="utf-8")
        write_layers(
            self.root,
            {
                "L5": ["src/core_check/integrity.py"],
                "L6": ["src/core_check/primitives.py"],
                "L7": [
                    "experimental/shared_data/__init__.py",
                    "experimental/shared_data/__main__.py",
                ],
            },
        )
        messages = findings_for(self.root, "layer-boundaries")
        self.assertTrue(any("배정 대상 파일이 없다" in message for message in messages), messages)

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

    def test_duplicate_selection_is_idempotent(self) -> None:
        single = self.context.build(self.core, self.consumer, ["consumer:rules/project.md"])
        duplicate = self.context.build(
            self.core,
            self.consumer,
            ["consumer:rules/project.md", "consumer:rules/project.md"],
        )
        self.assertEqual(single.optional, duplicate.optional)
        self.assertEqual(single.chars, duplicate.chars)
        self.assertEqual(single.digest, duplicate.digest)

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

    def test_forbidden_failure_document_is_not_in_default_selection(self) -> None:
        failures = self.core / "failures"
        failures.mkdir()
        (failures / "case.md").write_text(RULE_BODY.format(headers=DOC_HEADERS), encoding="utf-8")
        package = self.context.build(self.core, self.consumer)
        self.assertEqual(
            package.excluded["core:failures/case.md"],
            "별도 실패 사건 문서는 Core gate가 거부하며 시작 문맥에 포함하지 않는다",
        )

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

    def _require_capabilities(self, capabilities: object) -> None:
        policy = self.consumer / "PROJECT_RULES.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                '"protected_paths": ["private"]',
                '"required_core_capabilities": '
                + json.dumps(capabilities, ensure_ascii=False)
                + ',\n  "protected_paths": ["private"]',
            ),
            encoding="utf-8",
        )

    def test_clean_consumer_contract_passes(self) -> None:
        report = run_consumer(self.core, self.consumer)
        self.assertTrue(report.ok, [finding.as_dict() for finding in report.findings])

    def test_host_without_git_fails_closed(self) -> None:
        set_consumer_role(self.consumer, "host")
        with patch("core_check.integrity.subprocess.run", side_effect=OSError("git unavailable")):
            report = run_consumer(self.core, self.consumer)
        finding = [f for f in report.findings if f.check == "consumer-core-read-only"][0]
        self.assertIn("Git 상태를 실행할 수 없다", finding.message)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_assume_unchanged_flag_fails_closed(self) -> None:
        set_consumer_role(self.consumer, "host")
        initialize_clean_git(self.core)
        subprocess.run(
            ["git", "update-index", "--assume-unchanged", "data.json"],
            cwd=self.core,
            capture_output=True,
            check=True,
        )
        (self.core / "data.json").write_text('{"hidden": true}\n', encoding="utf-8")
        findings = run_consumer(self.core, self.consumer).findings
        finding = [f for f in findings if f.check == "consumer-core-read-only"][0]
        self.assertIn("index 우회 flag", finding.message)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_stat_cache_cannot_hide_same_size_blob_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "f.txt"
            target.write_bytes(b"aaaa")
            stamp = 946_684_800_000_000_000
            os.utime(target, ns=(stamp, stamp))
            commands = (
                ["git", "init", "--quiet"],
                ["git", "config", "core.autocrlf", "false"],
                ["git", "config", "core.trustctime", "false"],
                ["git", "config", "core.checkStat", "minimal"],
                ["git", "add", "-A"],
                [
                    "git",
                    "-c",
                    "user.name=Core Test",
                    "-c",
                    "user.email=core-test@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
            )
            for command in commands:
                subprocess.run(command, cwd=root, capture_output=True, check=True)
            target.write_bytes(b"bbbb")
            os.utime(target, ns=(stamp, stamp))
            clean, detail = host_core_cleanliness(root)
            self.assertFalse(clean)
            self.assertIn("tracked blob 내용이 HEAD와 다르다: f.txt", detail)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_rejects_clean_status_checkout_with_different_raw_eol_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            checkout = base / "checkout"
            source.mkdir()
            (source / "f.txt").write_bytes(b"a\nb\n")
            initialize_clean_git(source)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "core.autocrlf=true",
                    "clone",
                    "--quiet",
                    str(source),
                    str(checkout),
                ],
                cwd=base,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "core.autocrlf", "true"],
                cwd=checkout,
                capture_output=True,
                check=True,
            )
            self.assertEqual((checkout / "f.txt").read_bytes(), b"a\r\nb\r\n")
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=checkout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            self.assertEqual(status.stdout, "")
            clean, detail = host_core_cleanliness(checkout)
            self.assertFalse(clean)
            self.assertIn("tracked blob 내용이 HEAD와 다르다: f.txt", detail)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_batches_content_attribute_lookup_for_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_bytes(b"a\n")
            (root / "b.txt").write_bytes(b"b\n")
            initialize_clean_git(root)
            with patch.object(
                integrity_module,
                "_run_host_git",
                wraps=integrity_module._run_host_git,
            ) as run_git:
                clean, detail = host_core_cleanliness(root)
            self.assertTrue(clean, detail)
            attribute_calls = [
                call
                for call in run_git.call_args_list
                if len(call.args) > 1 and call.args[1] == "check-attr"
            ]
            self.assertEqual(len(attribute_calls), 1)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_rejects_external_clean_filter_before_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "core"
            root.mkdir()
            (root / ".gitattributes").write_bytes(b"f.txt filter=evil\n")
            (root / "f.txt").write_bytes(b"safe\n")
            marker = base / "filter-ran.txt"
            filter_script = base / "filter.py"
            filter_script.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "data = sys.stdin.buffer.read()\n"
                "Path(sys.argv[1]).write_text('ran', encoding='utf-8')\n"
                "sys.stdout.buffer.write(data)\n",
                encoding="utf-8",
            )
            initialize_clean_git(root)
            filter_command = f'"{sys.executable}" "{filter_script}" "{marker}"'
            subprocess.run(
                ["git", "config", "filter.evil.clean", filter_command],
                cwd=root,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "filter.evil.required", "true"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            clean, detail = host_core_cleanliness(root)
            self.assertFalse(clean)
            self.assertIn("content 변환 가능성", detail)
            self.assertFalse(marker.exists(), "unsafe clean filter가 hash 전에 실행됐다")

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_rejects_ident_content_transformation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitattributes").write_text("f.txt ident\n", encoding="utf-8")
            (root / "f.txt").write_text("$Id$\n", encoding="utf-8")
            initialize_clean_git(root)
            clean, detail = host_core_cleanliness(root)
            self.assertFalse(clean)
            self.assertIn("ident=set", detail)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_extra_empty_directory_fails_closed(self) -> None:
        set_consumer_role(self.consumer, "host")
        initialize_clean_git(self.core)
        (self.core / "empty-cache").mkdir()
        findings = run_consumer(self.core, self.consumer).findings
        finding = [f for f in findings if f.check == "consumer-core-read-only"][0]
        self.assertIn("Git이 소유하지 않는 directory", finding.message)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_git_environment_cannot_redirect_cleanliness_check(self) -> None:
        set_consumer_role(self.consumer, "host")
        initialize_clean_git(self.core)
        mirror = Path(self.tmp) / "clean-mirror"
        build_clean(mirror)
        initialize_clean_git(mirror)
        (self.core / "data.json").write_text('{"dirty": true}\n', encoding="utf-8")
        with patch.dict(
            os.environ,
            {"GIT_DIR": str(mirror / ".git"), "GIT_WORK_TREE": str(mirror)},
        ):
            findings = run_consumer(self.core, self.consumer).findings
        finding = [f for f in findings if f.check == "consumer-core-read-only"][0]
        self.assertIn("data.json", finding.message)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_core_must_be_its_own_git_toplevel(self) -> None:
        set_consumer_role(self.consumer, "host")
        initialize_clean_git(self.consumer)
        findings = run_consumer(self.core, self.consumer).findings
        finding = [f for f in findings if f.check == "consumer-core-read-only"][0]
        self.assertIn("Git top-level이 core_root와 다르다", finding.message)

    def test_contract_version_mismatch_is_detected(self) -> None:
        policy = self.consumer / "PROJECT_RULES.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace('"contract_version": 2', '"contract_version": 99'),
            encoding="utf-8",
        )
        self.assertFalse(run_consumer(self.core, self.consumer).ok)

    def test_invalid_contract_reports_only_executed_check(self) -> None:
        policy = self.consumer / "PROJECT_RULES.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                '"consumer_role": "maintainer"', '"consumer_role": "invalid"'
            ),
            encoding="utf-8",
        )
        report = run_consumer(self.core, self.consumer)
        self.assertEqual(report.ran, ["consumer-contract"])
        self.assertEqual(
            set(report.skipped),
            {
                "consumer-core-read-only",
                "consumer-capabilities",
                "consumer-entry",
                "consumer-state",
                "consumer-rule-routes",
                "consumer-document-headers",
                "consumer-markdown-links",
                "consumer-submodule",
            },
        )
        self.assertTrue(all("실행하지 않았다" in reason for reason in report.skipped.values()))

    def test_missing_required_capability_key_keeps_existing_host_compatible(self) -> None:
        self.assertTrue(run_consumer(self.core, self.consumer).ok)

    def test_installed_required_capability_passes(self) -> None:
        declare_optional_shared_data(self.core, installed=True)
        self._require_capabilities({"shared_data": 1})
        report = run_consumer(self.core, self.consumer)
        self.assertTrue(report.ok, [finding.as_dict() for finding in report.findings])

    def test_absent_required_capability_fails(self) -> None:
        declare_optional_shared_data(self.core)
        self._require_capabilities({"shared_data": 1})
        findings = run_consumer(self.core, self.consumer).findings
        self.assertTrue(
            any(finding.check == "consumer-capabilities" for finding in findings),
            [finding.as_dict() for finding in findings],
        )

    def test_required_capability_version_must_be_positive(self) -> None:
        self._require_capabilities({"shared_data": 0})
        findings = run_consumer(self.core, self.consumer).findings
        self.assertTrue(any(finding.check == "consumer-contract" for finding in findings))

    def test_required_capability_version_must_be_available(self) -> None:
        declare_optional_shared_data(self.core, installed=True)
        self._require_capabilities({"shared_data": 2})
        findings = run_consumer(self.core, self.consumer).findings
        self.assertTrue(
            any(
                finding.check == "consumer-capabilities" and "요구 버전" in finding.message
                for finding in findings
            ),
            [finding.as_dict() for finding in findings],
        )

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
    """실패 예방책은 규칙·테스트만 소유하고 사건 문서는 남기지 않는다."""

    def test_failure_event_documents_are_not_kept(self) -> None:
        cases = sorted((ROOT / "failures").glob("*.md"))
        self.assertEqual(cases, [], [path.name for path in cases])


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

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_verify_diagnoses_dirty_core_but_context_rejects_use(self) -> None:
        set_consumer_role(self.consumer, "host")
        initialize_clean_git(self.core)
        (self.core / "data.json").write_text('{"changed": true}\n', encoding="utf-8")
        code, payload = self._run(
            "--core-root", str(self.core), "--consumer-root", str(self.consumer), "verify"
        )
        self.assertEqual(code, self.cli.EXIT_FINDINGS)
        self.assertTrue(
            any(finding["check"] == "consumer-core-read-only" for finding in payload["findings"])
        )

        code, payload = self._run(
            "--core-root", str(self.core), "--consumer-root", str(self.consumer), "context"
        )
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertIn("Host Core 읽기 전용 사전 검사 실패", payload["error"])

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_verify_checks_core_after_unexpected_error(self) -> None:
        set_consumer_role(self.consumer, "host")
        initialize_clean_git(self.core)

        def mutate_then_fail(root: Path):
            (root / "unexpected-cache").mkdir()
            raise RuntimeError("simulated failure")

        with patch.object(self.cli, "run_all", side_effect=mutate_then_fail):
            code, payload = self._run(
                "--core-root", str(self.core), "--consumer-root", str(self.consumer), "verify"
            )
        self.assertEqual(code, self.cli.EXIT_UNUSABLE)
        self.assertEqual(payload["kind"], "CheckError")
        self.assertIn("Core tree 또는 HEAD/index 상태가 실행 중 변경", payload["error"])

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
    프로세스로 실행한다. 따라서 단위 테스트는 합성 트리만 사용하고 실제 저장소
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

    def test_tree_digest_includes_bytecode_cache(self) -> None:
        before = self.gate.tree_digest(self.root)
        cache = self.root / "__pycache__"
        cache.mkdir()
        (cache / "created.pyc").write_bytes(b"cache")
        self.assertNotEqual(before, self.gate.tree_digest(self.root))

    def test_tree_digest_includes_empty_directory(self) -> None:
        before = self.gate.tree_digest(self.root)
        (self.root / "empty-cache").mkdir()
        self.assertNotEqual(before, self.gate.tree_digest(self.root))

    def test_tree_digest_includes_submodule_git_pointer(self) -> None:
        pointer = self.root / ".git"
        pointer.write_text("gitdir: first\n", encoding="utf-8")
        before = self.gate.tree_digest(self.root)
        pointer.write_text("gitdir: second\n", encoding="utf-8")
        self.assertNotEqual(before, self.gate.tree_digest(self.root))

    def test_tree_digest_excludes_actual_git_metadata_directory(self) -> None:
        metadata = self.root / ".git"
        metadata.mkdir()
        internal = metadata / "index"
        internal.write_bytes(b"first")
        before = self.gate.tree_digest(self.root)
        internal.write_bytes(b"second")
        self.assertEqual(before, self.gate.tree_digest(self.root))

    def test_tree_digest_includes_persistent_mtime_change(self) -> None:
        target = self.root / "data.json"
        before = self.gate.tree_digest(self.root)
        current = target.stat()
        os.utime(target, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000))
        self.assertNotEqual(before, self.gate.tree_digest(self.root))

    def test_optional_absence_is_not_applicable_not_fail(self) -> None:
        result = self.gate.run(self.root)
        optional = [s for s in result.steps if s.name == "optional-features"][0]
        self.assertEqual(optional.status, "not_applicable")
        self.assertFalse(optional.required)
        self.assertTrue(result.ok)

    def test_declared_optional_capability_complete_absence_is_not_applicable(self) -> None:
        declare_optional_shared_data(self.root)
        result = self.gate.run(self.root)
        optional = [s for s in result.steps if s.name == "optional-features"][0]
        self.assertEqual(optional.status, "not_applicable")
        self.assertFalse(optional.required)
        self.assertTrue(result.ok, result.as_dict())

    def test_declared_optional_capability_partial_installation_fails_preflight(self) -> None:
        declare_optional_shared_data(self.root, partial=True)
        result = self.gate.run(self.root)
        self.assertFalse(result.ok)
        self.assertEqual(result.failed_step, "preflight-contract")
        self.assertIn("부분 설치", result.steps[0].detail)

    def test_host_optional_info_is_discovery_not_completion_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            declare_optional_shared_data(core, installed=True)
            capability = self.gate.declared_compatibility(core)["optional_capabilities"][
                "shared_data"
            ]
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "ok": True,
                        "capability": "shared_data",
                        "capability_version": capability["version"],
                        "commands": capability["commands"],
                        "request_schema": capability["request_schema"],
                        "result_schema": capability["result_schema"],
                    }
                ),
                stderr="",
            )
            with patch.object(self.gate.subprocess, "run", return_value=completed) as invoked:
                result = self.gate._optional(
                    core, execution_root=consumer, run_internal_tests=False
                )
            self.assertEqual(result.status, "not_applicable")
            self.assertFalse(result.required)
            self.assertIn("기능 소비·가용성·완료 검증이 아니다", result.detail)
            self.assertEqual(invoked.call_count, 1)
            self.assertEqual(invoked.call_args.kwargs["cwd"], consumer)
            command = invoked.call_args.args[0]
            self.assertIn("-I", command)
            self.assertIn("runpy.run_module", command[command.index("-c") + 1])

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

    def test_external_environment_cannot_skip_regression_failure(self) -> None:
        import os

        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_failure.py").write_text(
            "import unittest\n\n"
            "class FailureTest(unittest.TestCase):\n"
            "    def test_failure(self):\n"
            "        self.fail('injected regression')\n",
            encoding="utf-8",
        )
        flag = "CORE_CHECK_IN_GATE"
        previous = os.environ.get(flag)
        os.environ[flag] = "1"
        try:
            result = self.gate.run(self.root)
        finally:
            if previous is None:
                os.environ.pop(flag, None)
            else:
                os.environ[flag] = previous
        step = [s for s in result.steps if s.name == "regression-tests"][0]
        self.assertEqual(step.status, "fail")
        self.assertFalse(result.ok)

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

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_gate_passes_with_clean_core_git_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)
            result = self.gate.run(core, consumer)
            self.assertTrue(result.ok, result.as_dict())
            preflight = [s for s in result.steps if s.name == "host-core-read-only-preflight"][0]
            self.assertEqual(preflight.status, "pass")
            regression = [s for s in result.steps if s.name == "regression-tests"][0]
            self.assertEqual(regression.status, "not_applicable")
            self.assertFalse(regression.required)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_gate_detects_head_only_change_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)

            def commit_without_tree_change(*args, **kwargs):
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=Core Test",
                        "-c",
                        "user.email=core-test@example.invalid",
                        "-c",
                        "commit.gpgsign=false",
                        "commit",
                        "--quiet",
                        "--allow-empty",
                        "-m",
                        "unexpected",
                    ],
                    cwd=core,
                    capture_output=True,
                    check=True,
                )
                return self.gate.StepResult(
                    "optional-features", "not_applicable", "fixture", required=False
                )

            with patch.object(self.gate, "_optional", side_effect=commit_without_tree_change):
                result = self.gate.run(core, consumer)
            side_effect = [s for s in result.steps if s.name == "core-no-side-effects"][0]
            self.assertEqual(side_effect.status, "fail")
            self.assertIn("HEAD/index", side_effect.detail)
            self.assertFalse(result.ok)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_nested_gitlink_rejects_ignored_cache_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            core, consumer = build_consumer(base)
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)
            nested = add_nested_gitlink(core, base)
            clean, detail = host_core_cleanliness(core)
            self.assertTrue(clean, detail)
            cache = nested / "cache"
            cache.mkdir()
            (cache / "created.pyc").write_bytes(b"cache")
            clean, detail = host_core_cleanliness(core)
            self.assertFalse(clean)
            self.assertIn("tracked gitlink가 clean하지 않다", detail)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_nested_gitlink_rejects_extra_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            core, consumer = build_consumer(base)
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)
            nested = add_nested_gitlink(core, base)
            clean, detail = host_core_cleanliness(core)
            self.assertTrue(clean, detail)
            (nested / "unexpected-empty-cache").mkdir()
            clean, detail = host_core_cleanliness(core)
            self.assertFalse(clean)
            self.assertIn("tracked gitlink가 clean하지 않다", detail)
            self.assertIn("Git이 소유하지 않는 directory", detail)

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_nested_gitlink_head_change_updates_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            core, consumer = build_consumer(base)
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)
            nested = add_nested_gitlink(core, base)
            before = host_core_git_fingerprint(core)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Core Test",
                    "-c",
                    "user.email=core-test@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--quiet",
                    "--allow-empty",
                    "-m",
                    "nested unexpected",
                ],
                cwd=nested,
                capture_output=True,
                check=True,
            )
            self.assertNotEqual(before, host_core_git_fingerprint(core))

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_consumer_baseline_precedes_optional_execution_and_role_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)

            def mutate_consumer_role(*args, **kwargs):
                policy = consumer / "PROJECT_RULES.md"
                policy.write_text(
                    policy.read_text(encoding="utf-8").replace(
                        '"consumer_role": "host"', '"consumer_role": "maintainer"'
                    ),
                    encoding="utf-8",
                )
                return self.gate.StepResult(
                    "optional-features", "not_applicable", "fixture", required=False
                )

            with patch.object(self.gate, "_optional", side_effect=mutate_consumer_role):
                result = self.gate.run(core, consumer)
            regression = [s for s in result.steps if s.name == "regression-tests"][0]
            consumer_side_effect = [
                s for s in result.steps if s.name == "consumer-no-side-effects"
            ][0]
            self.assertEqual(regression.status, "not_applicable")
            self.assertFalse(regression.required)
            self.assertEqual(consumer_side_effect.status, "fail")

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_gate_blocks_tracked_core_change_before_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            set_consumer_role(consumer, "host")
            initialize_clean_git(core)
            (core / "data.json").write_text('{"changed": true}\n', encoding="utf-8")
            result = self.gate.run(core, consumer)
            self.assertEqual(result.failed_step, "host-core-read-only-preflight")
            statuses = {step.name: step.status for step in result.steps}
            self.assertEqual(statuses["regression-tests"], "not_run")

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host read-only fixture를 건너뛴다")
    def test_host_gate_blocks_ignored_cache_before_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            set_consumer_role(consumer, "host")
            (core / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
            initialize_clean_git(core)
            cache = core / "__pycache__"
            cache.mkdir()
            (cache / "created.pyc").write_bytes(b"cache")
            result = self.gate.run(core, consumer)
            self.assertEqual(result.failed_step, "host-core-read-only-preflight")
            preflight = [s for s in result.steps if s.name == "host-core-read-only-preflight"][0]
            self.assertIn("!! __pycache__/", preflight.detail)

    def test_invalid_consumer_contract_blocks_core_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            core, consumer = build_consumer(Path(tmp))
            policy = consumer / "PROJECT_RULES.md"
            policy.write_text(
                policy.read_text(encoding="utf-8").replace(
                    '"consumer_role": "maintainer"', '"consumer_role": "invalid"'
                ),
                encoding="utf-8",
            )
            with patch.object(self.gate, "_tests", side_effect=AssertionError("must not run")):
                result = self.gate.run(core, consumer)
            self.assertEqual(result.failed_step, "host-core-read-only-preflight")
            statuses = {step.name: step.status for step in result.steps}
            self.assertEqual(statuses["regression-tests"], "not_run")
            self.assertEqual(statuses["core-no-side-effects"], "pass")


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

    def test_declared_optional_capability_has_a_complete_public_boundary(self) -> None:
        from core_check.declarations import optional_capability_installation_state

        capability = self.declared["optional_capabilities"]["shared_data"]
        self.assertEqual(capability["version"], 1)
        self.assertEqual(capability["commands"], ["info", "invoke"])
        self.assertTrue(capability["schemas"])
        state = optional_capability_installation_state(ROOT, "shared_data", capability)
        self.assertIn(state, {"installed", "absent"})
        if state == "installed":
            for field in ("request_schema", "result_schema"):
                self.assertTrue((ROOT / capability[field]).is_file())

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

    def test_dependencies_are_declared_by_role(self) -> None:
        self.assertEqual(self.declared["required_dependencies"], [])
        self.assertEqual(self.declared["optional_dependencies"], ["git"])

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

    def test_gate_fails_when_declared_runtime_tool_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_clean(root)
            compatibility = root / "docs" / "COMPATIBILITY.md"
            compatibility.write_text(
                compatibility.read_text(encoding="utf-8").replace(
                    '"required_dependencies": []',
                    '"required_dependencies": ["missing-core-tool"]',
                ),
                encoding="utf-8",
            )
            with patch.object(self.gate.shutil, "which", return_value=None):
                result = self.gate.run(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.failed_step, "preflight-runtime")
            self.assertIn("missing-core-tool", result.steps[0].detail)
