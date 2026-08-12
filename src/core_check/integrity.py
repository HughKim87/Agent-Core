"""문서·링크·Schema·코드 무결성과 계층 경계 검사.

검사 대상과 소유자는 선언에서 조회한다. 문서 이름을 상수로 박지 않는다(A6).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
import json
from pathlib import Path
import re

from .primitives import Finding, Report
from .registry import REGISTRY, register

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
ROUTING_SECTION = re.compile(r"^##\s*\d+\.\s*규칙 라우팅\s*$(.*?)^##\s", re.M | re.S)
DOC_HEADERS = ("- 목적:", "- 읽는 시점:", "- 책임:", "- 상태:", "- 관련 권위:")

# 계층 선언. 경로 접두사로 판별한다.
LAYERS = {
    "L5": ("src/core_check/integrity.py", "src/core_check/registry.py"),
    "L6": ("src/core_check/primitives.py",),
    "L7": ("experimental/",),
}

SKIP_DIRS = {".git", "tmp", "__pycache__", ".obsidian"}


def _walk(root: Path, suffix: str) -> Iterator[Path]:
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _router(root: Path) -> Path | None:
    """라우팅 절을 가진 문서를 찾는다. 이름을 상수로 두지 않는다."""
    for path in _walk(root, ".md"):
        if ROUTING_SECTION.search(path.read_text(encoding="utf-8")):
            return path
    return None


# --- 필수 검사 -------------------------------------------------------------


@register("text-encoding")
def check_text_encoding(root: Path) -> Iterable[Finding]:
    for suffix in (".md", ".py", ".json"):
        for path in _walk(root, suffix):
            raw = path.read_bytes()
            rel = _rel(root, path)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                yield Finding("text-encoding", rel, f"UTF-8 디코딩 실패: {exc}")
                continue
            if b"\x00" in raw:
                yield Finding("text-encoding", rel, "NUL 바이트가 있다")
            for number, line in enumerate(text.split("\n"), start=1):
                if line != line.rstrip():
                    yield Finding("text-encoding", rel, f"{number}행에 후행 공백이 있다")


@register("markdown-links")
def check_markdown_links(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".md"):
        rel = _rel(root, path)
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                yield Finding("markdown-links", rel, f"깨진 링크: {target}")


@register("json-parse")
def check_json_parse(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            yield Finding("json-parse", _rel(root, path), f"JSON 파싱 실패: {exc}")


@register("python-ast")
def check_python_ast(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            yield Finding("python-ast", _rel(root, path), f"구문 오류: {exc}")


@register("document-headers")
def check_document_headers(root: Path) -> Iterable[Finding]:
    """O4. 유지 문서는 최소 설명 다섯 항목을 갖는다."""
    for path in _walk(root, ".md"):
        rel = _rel(root, path)
        text = path.read_text(encoding="utf-8")
        # 포인터 전용 진입 파일과 사용자 개요는 최소 설명 대상이 아니다.
        if path.parent == root and len(text) < 2000 and not text.lstrip().startswith("- "):
            if all(h not in text for h in DOC_HEADERS):
                continue
        missing = [h for h in DOC_HEADERS if h not in text]
        if missing:
            yield Finding("document-headers", rel, f"최소 설명 누락: {' '.join(missing)}")


@register("rule-routes")
def check_rule_routes(root: Path) -> Iterable[Finding]:
    """A5. 모든 활성 규칙이 라우터에서 정확히 한 번 라우팅된다."""
    router = _router(root)
    if router is None:
        yield Finding("rule-routes", "-", "라우팅 절을 가진 문서를 찾지 못했다")
        return
    section = ROUTING_SECTION.search(router.read_text(encoding="utf-8"))
    routes = [t for t in MD_LINK.findall(section.group(1)) if t.startswith("rules/")]
    rules_dir = root / "rules"
    active = sorted(f"rules/{p.name}" for p in rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    for rule in active:
        count = routes.count(rule)
        if count != 1:
            yield Finding("rule-routes", rule, f"route 수가 {count}이다")
    for route in routes:
        if not (root / route).is_file():
            yield Finding("rule-routes", route, "고아 route")


@register("rule-cross-routing")
def check_rule_cross_routing(root: Path) -> Iterable[Finding]:
    """A4. 규칙 문서가 다른 규칙을 직접 라우팅하지 않는다."""
    rules_dir = root / "rules"
    if not rules_dir.is_dir():
        return
    for path in sorted(rules_dir.glob("*.md")):
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.endswith(".md") and "/" not in target and target != path.name:
                yield Finding(
                    "rule-cross-routing", _rel(root, path), f"다른 규칙을 직접 라우팅한다: {target}"
                )


@register("layer-boundaries")
def check_layer_boundaries(root: Path) -> Iterable[Finding]:
    """A1·A2·A3. 계층 간 import 방향과 순환."""
    graph: dict[str, set[str]] = {}
    package = root / "src" / "core_check"
    if not package.is_dir():
        return
    for path in sorted(package.glob("*.py")):
        rel = _rel(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            # 구문 오류는 python-ast 검사가 소유한다. 한 검사의 실패가 다른 검사를
            # 중단시키면 전체 결과가 원인을 숨긴다.
            continue
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                deps.add(f"src/core_check/{node.module}.py")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("experimental"):
                        deps.add("experimental/")
        graph[rel] = deps
        if rel in LAYERS["L6"] and deps:
            yield Finding("layer-boundaries", rel, f"L6이 내부 모듈을 import한다: {sorted(deps)}")
        if rel in LAYERS["L5"]:
            bad = [d for d in deps if d.startswith("experimental")]
            if bad:
                yield Finding("layer-boundaries", rel, f"L5가 L7을 import한다: {bad}")

    seen: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> Iterator[Finding]:
        if node in stack:
            yield Finding("layer-boundaries", node, f"순환 의존: {' -> '.join(stack + [node])}")
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            yield from visit(dep)
        stack.pop()

    for node in sorted(graph):
        yield from visit(node)


@register("no-hardcoded-doc-names")
def check_no_hardcoded_doc_names(root: Path) -> Iterable[Finding]:
    """A6. 검증 도구가 상위 계층 문서 이름을 상수로 갖지 않는다.

    금지 목록 자체를 상수로 두면 이 검사가 스스로를 위반한다. 따라서 대상 이름은
    저장소에서 발견해 얻는다.
    """
    package = root / "src" / "core_check"
    if not package.is_dir():
        return
    discovered: set[str] = set()
    router = _router(root)
    if router is not None:
        discovered.add(router.name)
    marker = "## 첫 다음 행동"
    for path in _walk(root, ".md"):
        text = path.read_text(encoding="utf-8")
        if marker in text:
            discovered.add(path.name)
        if router is not None and path.parent == root and len(text) < 200:
            if any(t.endswith(router.name) for t in MD_LINK.findall(text)) or router.name in text:
                discovered.add(path.name)
    for path in sorted(package.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in sorted(discovered):
            if name in text:
                yield Finding(
                    "no-hardcoded-doc-names", _rel(root, path), f"문서 이름이 상수로 있다: {name}"
                )


STATE_BUDGET_CHARS = 3_000


@register("state-size-budget")
def check_state_size(root: Path) -> Iterable[Finding]:
    """O3. 현재 상태 문서가 단계 수에 비례해 커지지 않는다."""
    marker = "## 첫 다음 행동"
    for path in _walk(root, ".md"):
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            continue
        if len(text) > STATE_BUDGET_CHARS:
            yield Finding(
                "state-size-budget",
                _rel(root, path),
                f"{len(text)}자가 예산 {STATE_BUDGET_CHARS}자를 넘었다. "
                "완료 이력이 누적되었을 가능성이 높다",
            )


@register("state-canonical-owner")
def check_state_canonical_owner(root: Path) -> Iterable[Finding]:
    """O1·O5. 현재 상태 정본이 하나이고 한시 자료를 정본으로 참조하지 않는다."""
    marker = "## 첫 다음 행동"
    owners = [_rel(root, p) for p in _walk(root, ".md") if marker in p.read_text(encoding="utf-8")]
    if len(owners) != 1:
        yield Finding("state-canonical-owner", "-", f"현재 상태 정본이 {len(owners)}개다: {owners}")
    for path in _walk(root, ".md"):
        rel = _rel(root, path)
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith("tmp/") or "/tmp/" in target:
                yield Finding("state-canonical-owner", rel, f"한시 자료를 참조한다: {target}")


# --- 실행 ------------------------------------------------------------------


def run_all(root: Path) -> Report:
    report = Report()
    for name, fn in sorted(REGISTRY.required.items()):
        report.ran.append(name)
        report.findings.extend(fn(root))
    for name, fn in sorted(REGISTRY.optional.items()):
        report.ran.append(name)
        report.findings.extend(fn(root))
    if not REGISTRY.optional:
        report.skipped["optional-checks"] = "선택 기능이 등록되지 않았다. 실패가 아니다."
    return report
