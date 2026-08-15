"""Core 자체와 선언된 소비 표면의 무결성 검사."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
import json
from pathlib import Path
import re

from .declarations import (
    consumer_contract,
    consumer_policy_path,
    consumer_routed_rule_paths,
    core_policy_path,
    declared_compatibility,
    document_roles,
    module_layers,
    routed_rule_paths,
)
from .primitives import CheckError, Finding, Report, resolve_inside
from .registry import REGISTRY, register

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
AT_REFERENCE = re.compile(r"(?m)^@([^\s]+\.md)\s*$")
DOC_HEADERS = ("- 목적:", "- 읽는 시점:", "- 책임:", "- 상태:", "- 관련 권위:")
STATE_SECTIONS = (
    "## 현재 단계",
    "## 직전 게이트",
    "## 승인 상태",
    "## 차단",
    "## 알려진 위험",
    "## 첫 다음 행동",
)
STATE_BUDGET_CHARS = 3_000
DYNAMIC_NUMBERS = re.compile(
    r"(추적 파일\s*\d+|untracked\s*\d+|ignored\s*\d+|커밋\s*\d+\s*개|"
    r"파일\s*\d+\s*개\s*추적|blob\s*\d+)"
)
VAGUE_ACTIONS = ("계속 진행한다", "검토한다", "확인한다")
SKIP_DIRS = {".git", "tmp", "__pycache__", ".obsidian"}


def _walk(root: Path, suffix: str) -> Iterator[Path]:
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


@register("declaration-contracts")
def check_declaration_contracts(root: Path) -> Iterable[Finding]:
    for label, loader in (
        ("Core 문서 역할", document_roles),
        ("모듈 계층", module_layers),
        ("Core 규칙 route", routed_rule_paths),
        ("호환성", declared_compatibility),
    ):
        try:
            loader(root)
        except CheckError as exc:
            yield Finding("declaration-contracts", "-", f"{label}: {exc}")


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
            for number, line in enumerate(text.splitlines(), start=1):
                if line != line.rstrip(" \t"):
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
    for path in _walk(root, ".md"):
        text = path.read_text(encoding="utf-8")
        missing = [header for header in DOC_HEADERS if header not in text]
        if missing:
            yield Finding(
                "document-headers", _rel(root, path), f"최소 설명 누락: {' '.join(missing)}"
            )


@register("rule-routes")
def check_rule_routes(root: Path) -> Iterable[Finding]:
    try:
        routes = routed_rule_paths(root)
    except CheckError as exc:
        yield Finding("rule-routes", "-", str(exc))
        return
    rules_dir = root / "rules"
    active = sorted(f"rules/{path.name}" for path in rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    for rule in active:
        count = routes.count(rule)
        if count != 1:
            yield Finding("rule-routes", rule, f"route 수가 {count}이다")
    for route in routes:
        if not (root / route).is_file():
            yield Finding("rule-routes", route, "고아 route")


@register("rule-cross-routing")
def check_rule_cross_routing(root: Path) -> Iterable[Finding]:
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
    graph: dict[str, set[str]] = {}
    package = root / "src" / "core_check"
    if not package.is_dir():
        return
    try:
        layers = module_layers(root)
    except CheckError as exc:
        yield Finding("layer-boundaries", "-", str(exc))
        return

    assignments: dict[str, list[str]] = {}
    for layer, paths in layers.items():
        for declared in paths:
            assignments.setdefault(declared, []).append(layer)
            if not (root / declared).is_file():
                yield Finding("layer-boundaries", declared, f"{layer} 배정 대상 파일이 없다")

    for path in sorted(package.glob("*.py")):
        rel = _rel(root, path)
        owners = assignments.get(rel, [])
        if len(owners) != 1:
            yield Finding("layer-boundaries", rel, f"계층 배정 수가 {len(owners)}이다: {owners}")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module:
                    deps.add(f"src/core_check/{node.module.split('.', 1)[0]}.py")
                else:
                    for alias in node.names:
                        deps.add(f"src/core_check/{alias.name.split('.', 1)[0]}.py")
        graph[rel] = deps
        layer = owners[0] if len(owners) == 1 else None
        if layer == "L6" and deps:
            yield Finding("layer-boundaries", rel, f"L6이 내부 모듈을 import한다: {sorted(deps)}")
        if layer == "L5":
            bad = [dep for dep in deps if "L7" in assignments.get(dep, [])]
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
    package = root / "src" / "core_check"
    if not package.is_dir():
        return
    try:
        roles = document_roles(root)
    except CheckError:
        return
    discovered = {Path(value).name for value in roles.values() if isinstance(value, str)}
    for path in sorted(package.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in sorted(discovered):
            if name in text:
                yield Finding(
                    "no-hardcoded-doc-names", _rel(root, path), f"문서 이름이 상수로 있다: {name}"
                )


@register("temporary-canonical-links")
def check_temporary_canonical_links(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".md"):
        rel = _rel(root, path)
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith("tmp/") or "/tmp/" in target:
                yield Finding("temporary-canonical-links", rel, f"한시 자료를 참조한다: {target}")


def _state_findings(consumer_root: Path, state: Path) -> Iterable[Finding]:
    text = state.read_text(encoding="utf-8")
    rel = _rel(consumer_root, state)
    for section in STATE_SECTIONS:
        if section not in text:
            yield Finding("consumer-state", rel, f"필수 절이 없다: {section}")
    if len(text) > STATE_BUDGET_CHARS:
        yield Finding("consumer-state", rel, f"{len(text)}자가 예산 {STATE_BUDGET_CHARS}자를 넘었다")
    if DYNAMIC_NUMBERS.search(text):
        yield Finding("consumer-state", rel, "동적 Git 수치가 문서에 고정되어 있다")
    if "## 첫 다음 행동" in text:
        tail = text.split("## 첫 다음 행동", 1)[1]
        actions = [line.strip() for line in tail.splitlines() if re.match(r"^\d+\.", line.strip())]
        if not actions:
            yield Finding("consumer-state", rel, "번호가 매겨진 첫 다음 행동이 없다")
        for action in actions:
            normalized = action.rstrip(".")
            if any(normalized.endswith(value) for value in VAGUE_ACTIONS):
                yield Finding("consumer-state", rel, f"첫 다음 행동이 모호하다: {action}")
    if "## 직전 게이트" in text and "## 승인 상태" in text:
        gates = text.split("## 직전 게이트", 1)[1].split("## 승인 상태", 1)[0]
        judged = [line for line in gates.splitlines() if "`pass`" in line or "`fail`" in line]
        if len(judged) > 1:
            yield Finding("consumer-state", rel, "직전 게이트 절에 과거 판정이 누적되어 있다")


def state_contract_findings(consumer_root: Path, state: Path) -> list[Finding]:
    """상태 계약의 독립 결함 주입 테스트용 공개 helper."""
    return list(_state_findings(consumer_root.resolve(), state.resolve()))


def _entry_targets(text: str) -> list[str]:
    targets = MD_LINK.findall(text)
    targets.extend(AT_REFERENCE.findall(text))
    return [target.replace("\\", "/") for target in targets]


def _consumer_contract_files(core_root: Path, consumer_root: Path, contract: dict[str, object]) -> list[Path]:
    files = {
        consumer_policy_path(core_root, consumer_root),
        resolve_inside(consumer_root, contract["state"]),
    }
    for value in contract["entry_pointers"].values():
        files.add(resolve_inside(consumer_root, value))
    for value in contract["rule_roots"]:
        files.update(resolve_inside(consumer_root, value).rglob("*.md"))
    gitmodules = consumer_root / ".gitmodules"
    if gitmodules.is_file():
        files.add(gitmodules)
    return sorted(path for path in files if path.is_file())


def consumer_findings(core_root: Path, consumer_root: Path) -> Iterable[Finding]:
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    try:
        contract = consumer_contract(core_root, consumer_root)
        compatibility = declared_compatibility(core_root)
    except CheckError as exc:
        yield Finding("consumer-contract", "-", str(exc))
        return

    if contract["contract_version"] != compatibility.get("contract_version"):
        yield Finding("consumer-contract", "-", "Core와 소비 계약의 contract_version이 다르다")

    core_rel = Path(contract["core_path"]).as_posix().rstrip("/")
    core_policy = core_policy_path(core_root).relative_to(core_root).as_posix()
    policy = consumer_policy_path(core_root, consumer_root).relative_to(consumer_root).as_posix()
    expected = [f"{core_rel}/{core_policy}", policy, Path(contract["state"]).as_posix()]
    for agent, value in contract["entry_pointers"].items():
        pointer = resolve_inside(consumer_root, value)
        actual = _entry_targets(pointer.read_text(encoding="utf-8"))
        if actual != expected:
            yield Finding(
                "consumer-entry", _rel(consumer_root, pointer), f"{agent} 진입 순서가 다르다: {actual}"
            )

    state = resolve_inside(consumer_root, contract["state"])
    yield from _state_findings(consumer_root, state)

    try:
        routes = consumer_routed_rule_paths(core_root, consumer_root)
    except CheckError as exc:
        yield Finding("consumer-rule-routes", policy, str(exc))
        routes = []
    active: list[str] = []
    for value in contract["rule_roots"]:
        root = resolve_inside(consumer_root, value)
        active.extend(_rel(consumer_root, path) for path in sorted(root.glob("*.md")))
    for rule in active:
        if routes.count(rule) != 1:
            yield Finding("consumer-rule-routes", rule, f"route 수가 {routes.count(rule)}이다")
    for route in routes:
        if not resolve_inside(consumer_root, route).is_file():
            yield Finding("consumer-rule-routes", route, "고아 route")

    pointers = {Path(value).as_posix() for value in contract["entry_pointers"].values()}
    for path in _consumer_contract_files(core_root, consumer_root, contract):
        rel = _rel(consumer_root, path)
        if path.suffix == ".md" and rel not in pointers:
            text = path.read_text(encoding="utf-8")
            missing = [header for header in DOC_HEADERS if header not in text]
            if missing:
                yield Finding("consumer-document-headers", rel, f"최소 설명 누락: {' '.join(missing)}")
        if path.suffix == ".md":
            for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                if not resolved.exists():
                    yield Finding("consumer-markdown-links", rel, f"깨진 링크: {target}")

    gitmodules = consumer_root / ".gitmodules"
    if not gitmodules.is_file():
        yield Finding("consumer-submodule", ".gitmodules", "Core submodule 선언 파일이 없다")
    else:
        paths = re.findall(r"(?m)^\s*path\s*=\s*(.+?)\s*$", gitmodules.read_text(encoding="utf-8"))
        normalized = {Path(value).as_posix() for value in paths}
        if Path(contract["core_path"]).as_posix() not in normalized:
            yield Finding("consumer-submodule", ".gitmodules", "core_path와 일치하는 submodule path가 없다")


def run_consumer(core_root: Path, consumer_root: Path) -> Report:
    report = Report()
    report.ran.extend(
        [
            "consumer-contract",
            "consumer-entry",
            "consumer-state",
            "consumer-rule-routes",
            "consumer-document-headers",
            "consumer-markdown-links",
            "consumer-submodule",
        ]
    )
    report.findings.extend(consumer_findings(core_root, consumer_root))
    return report


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
