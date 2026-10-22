"""공개 workflow 자산과 제한된 진입 템플릿 형식의 구조·결함 검사.

검사 helper는 test-only다. YAML 전체 문법, 실제 제품 parser, Agent의 의미
선택·행동 또는 설치 성공을 증명하지 않는다. 합성 경로 예제도 별도로 구분한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from urllib.parse import quote, unquote
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core_check.integrity import (  # noqa: E402
    check_document_headers,
    check_markdown_links,
    check_skill_source_integrity,
)
REQUIRED_NAMES = {"handoff-manager", "setup-agent-core-project", "session-close"}
BLOCK = re.compile(
    r"<!-- core-workflow-entries:v1 -->\n(.*?)\n<!-- /core-workflow-entries -->", re.S
)
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
PLACEHOLDER = "{{WORKFLOW_LINK}}"
HEADERS = ("- 목적:", "- 읽는 시점:", "- 책임:", "- 상태:", "- 관련 권위:")


def entries(root: Path) -> list[list[str]]:
    text = (root / "docs/COMPATIBILITY.md").read_text(encoding="utf-8")
    blocks = BLOCK.findall(text)
    if len(blocks) != 1:
        raise ValueError("공개 workflow 표는 정확히 하나여야 한다")
    rows = []
    for line in blocks[0].splitlines()[2:]:
        if not line.startswith("|") or not line.endswith("|"):
            raise ValueError("workflow 표 행 형식이 다르다")
        cells = [cell.strip().strip("`") for cell in line[1:-1].split("|")]
        if len(cells) != 5:
            raise ValueError("workflow 표 열 수가 다르다")
        rows.append(cells)
    return rows


def inside_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise ValueError(f"배포 파일이 없다: {relative}")
    return path


def read_asset(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw or b"\r" in raw:
        raise ValueError(f"UTF-8/LF 자산 형식 위반: {path.name}")
    text = raw.decode("utf-8")
    if any(line != line.rstrip(" \t") for line in text.splitlines()):
        raise ValueError(f"후행 공백: {path.name}")
    return text


def scalar(value: str):
    # Published templates deliberately use a small, dependency-free YAML subset.
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith('"'):
        parsed = json.loads(value)
        if isinstance(parsed, str):
            return parsed
    if re.fullmatch(r"[a-z][a-z0-9-]*", value):
        return value
    raise ValueError("지원하지 않는 템플릿 scalar")


def frontmatter(text: str) -> tuple[dict, str]:
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if match is None:
        raise ValueError("진입 frontmatter 경계가 없다")
    fields = {}
    for line in match[1].splitlines():
        field = re.fullmatch(r"([a-z][a-z-]*): (.+)", line)
        if field is None or field[1] in fields:
            raise ValueError("중복 또는 지원하지 않는 frontmatter")
        fields[field[1]] = scalar(field[2])
    return fields, match[2]


def openai_fields(text: str) -> dict:
    sections = {}
    current = None
    for line in text.splitlines():
        section = re.fullmatch(r"(interface|policy):", line)
        if section:
            current = section[1]
            if current in sections:
                raise ValueError("중복 Codex section")
            sections[current] = {}
            continue
        field = re.fullmatch(r"  ([a-z_]+): (.+)", line)
        if current is None or field is None or field[1] in sections[current]:
            raise ValueError("지원하지 않는 Codex 메타데이터")
        sections[current][field[1]] = scalar(field[2])
    if set(sections.get("policy", {})) != {"allow_implicit_invocation"}:
        raise ValueError("Codex 호출 정책 누락 또는 알 수 없는 필드")
    if set(sections.get("interface", {})) - {"display_name", "short_description", "default_prompt"}:
        raise ValueError("지원하지 않는 Codex interface")
    if any(not isinstance(value, str) for value in sections.get("interface", {}).values()):
        raise ValueError("Codex interface는 문자열이어야 한다")
    return sections


def validate_assets(root: Path) -> list[str]:
    """Validate public assets; faults are findings, not successful omissions."""
    findings = [item.message for item in check_skill_source_integrity(root)]
    try:
        rows = entries(root)
        if len(rows) != len(REQUIRED_NAMES) or {row[0] for row in rows} != REQUIRED_NAMES:
            raise ValueError("세 필수 workflow의 공개 목록이 다르다")
    except (OSError, UnicodeError, ValueError) as exc:
        return [str(exc)]
    for name, workflow_rel, codex_rel, claude_rel, invocation in rows:
        try:
            expected = [
                f"skills/{name}/WORKFLOW.md",
                f"skills/{name}/codex/SKILL.md.in",
                f"skills/{name}/claude/SKILL.md.in",
            ]
            if [workflow_rel, codex_rel, claude_rel] != expected:
                raise ValueError("공개 경로와 workflow owner가 다르다")
            automatic = False  # Three published skills are explicit-only.
            if invocation != ("허용" if automatic else "직접 호출"):
                raise ValueError("공개 호출 정책 불일치")
            workflow = inside_file(root, workflow_rel)
            workflow_text = read_asset(workflow)
            if any(header not in workflow_text for header in HEADERS):
                raise ValueError("공통 본문 최소 설명 누락")
            for link in LINK.findall(workflow_text):
                if not link.startswith(("https://", "http://", "#")):
                    inside_file(root, (workflow.parent / unquote(link.split("#", 1)[0])).relative_to(root).as_posix())
            active_link, = LINK.findall(workflow_text)[1:]
            active = inside_file(root, (workflow.parent / unquote(active_link)).relative_to(root).as_posix())
            for link in LINK.findall(active.read_text(encoding="utf-8")):
                if not link.startswith(("https://", "http://", "#")):
                    inside_file(root, (active.parent / unquote(link.split("#", 1)[0])).relative_to(root).as_posix())
            descriptions = []
            bodies = []
            for host, relative in (("codex", codex_rel), ("claude", claude_rel)):
                template = read_asset(inside_file(root, relative))
                fields, body = frontmatter(template)
                allowed = {"name", "description"}
                if host == "claude":
                    allowed.add("disable-model-invocation")
                if set(fields) != allowed or fields["name"] != name:
                    raise ValueError(f"{host} frontmatter 계약 불일치")
                description = fields["description"]
                if not isinstance(description, str) or not 1 <= len(description) <= 1024:
                    raise ValueError("description 형식 위반")
                if host == "claude" and fields["disable-model-invocation"] is not (not automatic):
                    raise ValueError("Claude 호출 정책 불일치")
                if LINK.findall(body) != [PLACEHOLDER] or template.count(PLACEHOLDER) != 1:
                    raise ValueError("단일 workflow 포인터가 아니다")
                if re.findall(r"\{\{.*?\}\}", template) != [PLACEHOLDER]:
                    raise ValueError("알 수 없는 템플릿 치환 항목")
                if "!`" in template or "```" in body:
                    raise ValueError("얇은 포인터에 실행/공통 본문이 포함됐다")
                descriptions.append(description)
                bodies.append(body)
            if descriptions[0] != descriptions[1] or bodies[0] != bodies[1]:
                raise ValueError("양 도구의 discovery 설명·본문 포인터가 다르다")
            metadata = root / Path(codex_rel).parent / "agents/openai.yaml"
            config = openai_fields(read_asset(metadata))
            if config["policy"]["allow_implicit_invocation"] is not automatic:
                raise ValueError("Codex 호출 정책 불일치")
        except (OSError, UnicodeError, ValueError) as exc:
            findings.append(f"{name}: {exc}")
    for discovered in (root / ".agents/skills", root / ".claude/skills"):
        if discovered.exists():
            findings.append("Core 내부에 native 스킬 발견 경로가 있다")
    return findings


class SkillAssetsTest(unittest.TestCase):
    def test_published_assets(self):
        self.assertEqual(validate_assets(ROOT), [])

    def test_faults_are_detected(self):
        mutations = {
            "missing-workflow": ("skills/session-close/WORKFLOW.md", None),
            "missing-source": ("skills/session-close/source/SKILL.md", None),
            "missing-reference": ("skills/session-close/source/references/design.md", None),
            "missing-current": ("skills/session-close/current/SKILL.md", None),
            "missing-setup-current": ("skills/setup-agent-core-project/current/SKILL.md", None),
            "missing-current-reference": ("skills/session-close/current/references/design.md", None),
            "changed-source": ("skills/session-close/source/SKILL.md", b"changed original"),
            "missing-template": ("skills/handoff-manager/claude/SKILL.md.in", None),
            "missing-openai": ("skills/setup-agent-core-project/codex/agents/openai.yaml", None),
            "wrong-handoff-codex-policy": ("skills/handoff-manager/codex/agents/openai.yaml", ("false", "true")),
            "wrong-handoff-claude-policy": ("skills/handoff-manager/claude/SKILL.md.in", ("true", "false")),
            "wrong-codex-policy": ("skills/session-close/codex/agents/openai.yaml", ("false", "true")),
            "wrong-claude-policy": ("skills/session-close/claude/SKILL.md.in", ("true", "false")),
            "missing-pointer": ("skills/handoff-manager/codex/SKILL.md.in", (PLACEHOLDER, "missing.md")),
            "extra-placeholder": ("skills/handoff-manager/codex/SKILL.md.in", (PLACEHOLDER, "{{OTHER}}")),
            "dynamic-command": ("skills/session-close/codex/SKILL.md.in", ("Core workflow entry", "!`command` Core workflow entry")),
            "unknown-field": ("skills/session-close/codex/SKILL.md.in", ("name: session-close", "name: session-close\nallowed-tools: shell")),
            "unknown-yaml": ("skills/handoff-manager/codex/agents/openai.yaml", ("policy:", "dependencies:")),
            "duplicate-field": ("skills/session-close/claude/SKILL.md.in", ("name: session-close", "name: session-close\nname: session-close")),
            "broken-reference": ("skills/handoff-manager/WORKFLOW.md", ("source/SKILL.md", "source/absent.md")),
            "foreign-owner": ("docs/COMPATIBILITY.md", ("skills/handoff-manager/WORKFLOW.md", "skills/session-close/WORKFLOW.md")),
            "invalid-encoding": ("skills/handoff-manager/codex/SKILL.md.in", b"\xff"),
            "bad-template-eol": ("skills/handoff-manager/claude/SKILL.md.in", ("---\n", "---\r\n")),
        }
        with tempfile.TemporaryDirectory(prefix="core-skills-faults-") as directory:
            for label, (relative, change) in mutations.items():
                with self.subTest(label=label):
                    fixture = Path(directory) / label
                    shutil.copytree(ROOT / "skills", fixture / "skills")
                    shutil.copytree(ROOT / "docs", fixture / "docs")
                    shutil.copyfile(ROOT / "PROJECT_RULES.md", fixture / "PROJECT_RULES.md")
                    path = fixture / relative
                    if change is None:
                        path.unlink()
                    elif isinstance(change, bytes):
                        path.write_bytes(change)
                    else:
                        text = path.read_text(encoding="utf-8")
                        self.assertIn(change[0], text)
                        path.write_bytes(text.replace(*change, 1).encode("utf-8"))
                    self.assertTrue(validate_assets(fixture), label)

    def test_entry_link_examples_for_nested_spaced_core(self):
        # Synthetic file navigation only; no product loader or installer is run.
        with tempfile.TemporaryDirectory(prefix="core-skills-links-") as directory:
            consumer = Path(directory) / "consumer root"
            for core_relative in ("core", "vendor/core shared"):
                core = consumer / core_relative
                for name in sorted(REQUIRED_NAMES):
                    workflow = core / "skills" / name / "WORKFLOW.md"
                    workflow.parent.mkdir(parents=True, exist_ok=True)
                    workflow.write_bytes((ROOT / "skills" / name / "WORKFLOW.md").read_bytes())
                    shutil.copytree(ROOT / "skills" / name / "source", workflow.parent / "source")
                    current = ROOT / "skills" / name / "current"
                    if current.exists():
                        shutil.copytree(current, workflow.parent / "current")
                    targets = []
                    for host, folder in (("codex", ".agents"), ("claude", ".claude")):
                        native = consumer / folder / "skills" / name / "SKILL.md"
                        native.parent.mkdir(parents=True, exist_ok=True)
                        relative = Path(os.path.relpath(workflow, native.parent)).as_posix()
                        uri = quote(relative, safe="/.-")
                        source = ROOT / "skills" / name / host / "SKILL.md.in"
                        native.write_bytes(source.read_text(encoding="utf-8").replace(PLACEHOLDER, uri).encode("utf-8"))
                        _, body = frontmatter(native.read_text(encoding="utf-8"))
                        link, = LINK.findall(body)
                        self.assertNotIn(PLACEHOLDER, link)
                        target = (native.parent / unquote(link)).resolve()
                        self.assertEqual(target, workflow.resolve())
                        self.assertEqual(target.read_bytes(), workflow.read_bytes())
                        source_link, = LINK.findall(target.read_text(encoding="utf-8"))[1:]
                        original = (target.parent / unquote(source_link)).resolve()
                        expected = ROOT / "skills" / name / ("current/SKILL.md" if current.exists() else "source/SKILL.md")
                        self.assertEqual(original.read_bytes(), expected.read_bytes())
                        if name == "session-close":
                            reference = original.parent / "references/design.md"
                            self.assertEqual(reference.read_bytes(), (expected.parent / "references/design.md").read_bytes())
                        targets.append(target)
                    self.assertEqual(targets[0], targets[1])

    def test_all_source_files_are_manifested(self):
        manifest = json.loads((ROOT / "skills/SOURCES.json").read_text(encoding="utf-8"))
        actual = {
            path.relative_to(ROOT).as_posix()
            for name in REQUIRED_NAMES
            for path in (ROOT / "skills" / name / "source").rglob("*")
            if path.is_file()
        }
        self.assertEqual(set(manifest["files"]), actual)
        self.assertEqual(list(check_skill_source_integrity(ROOT)), [])
        self.assertEqual(list(check_markdown_links(ROOT)), [])

    def test_only_verified_originals_are_exempt_from_document_headers(self):
        with tempfile.TemporaryDirectory(prefix="core-skills-headers-") as directory:
            fixture = Path(directory)
            shutil.copytree(ROOT / "skills", fixture / "skills")
            original_rel = "skills/handoff-manager/source/SKILL.md"
            findings = list(check_document_headers(fixture))
            self.assertFalse(any(item.path == original_rel for item in findings))
            ordinary = fixture / "ordinary.md"
            ordinary.write_bytes(b"# A Core document with missing ownership fields\n")
            impostor = fixture / "skills/handoff-manager/source/unregistered.md"
            impostor.write_bytes(b"# Unregistered source-like document\n")
            findings = {item.path for item in check_document_headers(fixture)}
            self.assertIn("ordinary.md", findings)
            self.assertIn(impostor.relative_to(fixture).as_posix(), findings)
            original = fixture / original_rel
            original.write_bytes(original.read_bytes() + b"\nchanged\n")
            self.assertTrue(list(check_skill_source_integrity(fixture)))
            self.assertIn(original_rel, {item.path for item in check_document_headers(fixture)})

    def test_source_manifest_errors_do_not_create_header_exemptions(self):
        with tempfile.TemporaryDirectory(prefix="core-skills-manifest-") as directory:
            fixture = Path(directory)
            shutil.copytree(ROOT / "skills", fixture / "skills")
            index = fixture / "skills/SOURCES.json"
            valid = index.read_text(encoding="utf-8")
            ordinary = fixture / "ordinary.md"
            ordinary.write_bytes(b"# Not a preserved skill source\n")
            for damaged in (
                "not json",
                valid.replace('"format_version": 1', '"format_version": true'),
                valid.replace('"format_version": 1', '"format_version": 1, "format_version": 1'),
                valid.replace("skills/handoff-manager/source/SKILL.md", "ordinary.md"),
                valid.replace("skills/handoff-manager/source/SKILL.md", "skills/handoff-manager/source/../../outside.md"),
                valid.replace("skills/handoff-manager/source/SKILL.md", "skills/handoff-manager/source/./SKILL.md"),
            ):
                with self.subTest(manifest=damaged[:50]):
                    index.write_bytes(damaged.encode("utf-8"))
                    self.assertTrue(list(check_skill_source_integrity(fixture)))
                    self.assertIn("ordinary.md", {item.path for item in check_document_headers(fixture)})
            index.unlink()
            self.assertTrue(list(check_skill_source_integrity(fixture)))
            self.assertIn(
                "skills/handoff-manager/source/SKILL.md",
                {item.path for item in check_document_headers(fixture)},
            )


if __name__ == "__main__":
    unittest.main()
