"""Core 문서 역할, 규칙 route, 모듈 계층 선언 해석기.

사람용 제목이나 특정 문서 이름을 코드에 고정하지 않고 기계 판독 선언을 찾는다.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import re

from .primitives import CheckError, resolve_inside

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DOCUMENT_ROLES_BLOCK = re.compile(
    r"<!--\s*core-document-roles:v1\s*-->\s*```json\s*(.*?)```", re.S
)
MODULE_LAYERS_BLOCK = re.compile(
    r"<!--\s*core-module-layers:v1\s*-->\s*```json\s*(.*?)```", re.S
)
RULE_ROUTES_BLOCK = re.compile(
    r"<!--\s*core-rule-routes:v1\s*-->(.*?)<!--\s*/core-rule-routes:v1\s*-->", re.S
)
SKIP_DIRS = {".git", "tmp", "__pycache__", ".obsidian"}


def walk_markdown(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _single_json_declaration(root: Path, pattern: re.Pattern[str], label: str) -> dict[str, object]:
    matches: list[tuple[Path, str]] = []
    for path in walk_markdown(root):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            matches.append((path, match.group(1)))
    if len(matches) != 1:
        raise CheckError(f"{label} 선언이 {len(matches)}개다")
    path, payload = matches[0]
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CheckError(f"{path.relative_to(root).as_posix()}의 {label} JSON이 잘못됐다: {exc}") from exc
    if not isinstance(value, dict):
        raise CheckError(f"{label} 선언은 객체여야 한다")
    return value


def document_roles(root: Path) -> dict[str, object]:
    roles = _single_json_declaration(root, DOCUMENT_ROLES_BLOCK, "문서 역할")
    for role in ("policy", "state"):
        value = roles.get(role)
        if not isinstance(value, str) or not value:
            raise CheckError(f"문서 역할 {role}이 유효한 경로가 아니다")
        if not resolve_inside(root, value).is_file():
            raise CheckError(f"문서 역할 {role}의 파일이 없다: {value}")
    pointers = roles.get("entry_pointers")
    if not isinstance(pointers, list) or not all(isinstance(p, str) and p for p in pointers):
        raise CheckError("문서 역할 entry_pointers는 경로 배열이어야 한다")
    for pointer in pointers:
        if not resolve_inside(root, pointer).is_file():
            raise CheckError(f"진입 포인터 파일이 없다: {pointer}")
    return roles


def module_layers(root: Path) -> dict[str, list[str]]:
    raw = _single_json_declaration(root, MODULE_LAYERS_BLOCK, "모듈 계층")
    layers: dict[str, list[str]] = {}
    for layer in ("L5", "L6", "L7"):
        paths = raw.get(layer)
        if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
            raise CheckError(f"모듈 계층 {layer}는 경로 배열이어야 한다")
        layers[layer] = list(paths)
    return layers


def role_path(root: Path, role: str) -> Path:
    value = document_roles(root).get(role)
    if not isinstance(value, str):
        raise CheckError(f"문서 역할이 없다: {role}")
    return resolve_inside(root, value)


def routed_rule_paths(root: Path) -> list[str]:
    policy = role_path(root, "policy")
    matches = list(RULE_ROUTES_BLOCK.finditer(policy.read_text(encoding="utf-8")))
    if len(matches) != 1:
        raise CheckError(f"정책의 규칙 route 선언이 {len(matches)}개다")
    return [target for target in MD_LINK.findall(matches[0].group(1)) if target.startswith("rules/")]
