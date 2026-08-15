"""Core와 소비 저장소를 분리한 시작 컨텍스트 구성."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .declarations import (
    consumer_contract,
    consumer_policy_path,
    consumer_routed_rule_paths,
    core_policy_path,
    routed_rule_paths,
    walk_markdown,
)
from .primitives import CheckError, fingerprint, resolve_inside

STARTUP_BUDGET_CHARS = 20_000


class ContextBudgetError(CheckError):
    """예산을 넘었다. 임의 절단 대신 명시적으로 실패한다."""


@dataclass(frozen=True)
class ContextRef:
    scope: str
    path: str

    @property
    def identifier(self) -> str:
        return f"{self.scope}:{self.path}"

    def as_dict(self) -> dict[str, str]:
        return {"scope": self.scope, "path": self.path}


@dataclass
class ContextPackage:
    required: list[ContextRef] = field(default_factory=list)
    optional: list[ContextRef] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    chars: int = 0
    digest: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "required": [ref.as_dict() for ref in self.required],
            "optional": [ref.as_dict() for ref in self.optional],
            "excluded": dict(sorted(self.excluded.items())),
            "chars": self.chars,
            "digest": self.digest,
        }


def _ref(scope: str, root: Path, path: Path) -> ContextRef:
    return ContextRef(scope, path.relative_to(root).as_posix())


def _consumer_markdown(core_root: Path, consumer_root: Path) -> list[Path]:
    contract = consumer_contract(core_root, consumer_root)
    paths = {
        consumer_policy_path(core_root, consumer_root),
        resolve_inside(consumer_root, contract["state"]),
    }
    for value in contract["entry_pointers"].values():
        paths.add(resolve_inside(consumer_root, value))
    for value in contract["rule_roots"]:
        root = resolve_inside(consumer_root, value)
        paths.update(root.rglob("*.md"))
    return sorted(path for path in paths if path.is_file())


def build(
    core_root: Path,
    consumer_root: Path,
    matched: Iterable[str] = (),
    *,
    budget: int = STARTUP_BUDGET_CHARS,
) -> ContextPackage:
    """필수 세 문서와 현재 행동에 일치한 scoped 규칙만 선택한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    contract = consumer_contract(core_root, consumer_root)
    package = ContextPackage()

    package.required = [
        _ref("core", core_root, core_policy_path(core_root)),
        _ref("consumer", consumer_root, consumer_policy_path(core_root, consumer_root)),
        _ref("consumer", consumer_root, resolve_inside(consumer_root, contract["state"])),
    ]

    available: dict[str, ContextRef] = {}
    for path in routed_rule_paths(core_root):
        ref = ContextRef("core", Path(path).as_posix())
        available[ref.identifier] = ref
    for path in consumer_routed_rule_paths(core_root, consumer_root):
        ref = ContextRef("consumer", Path(path).as_posix())
        available[ref.identifier] = ref

    for name in matched:
        if name not in available:
            raise CheckError(f"라우팅되지 않은 scoped 소유자를 요청했다: {name}")
        package.optional.append(available[name])

    selected = {ref.identifier for ref in package.required + package.optional}
    for path in walk_markdown(core_root):
        ref = _ref("core", core_root, path)
        if ref.identifier in selected:
            continue
        if ref.path.startswith("failures/"):
            reason = "예외 진단 문서는 기본 선택과 일반 route에 포함하지 않는다"
        elif ref.path.startswith("rules/"):
            reason = "현재 행동에 Core route가 일치하지 않는다"
        else:
            reason = "Core 계약·설계 문서는 필요 시 링크로 도달한다"
        package.excluded[ref.identifier] = reason

    for path in _consumer_markdown(core_root, consumer_root):
        ref = _ref("consumer", consumer_root, path)
        if ref.identifier in selected:
            continue
        if any(ref.path == root or ref.path.startswith(f"{root.rstrip('/')}/") for root in contract["rule_roots"]):
            reason = "현재 행동에 소비 저장소 route가 일치하지 않는다"
        else:
            reason = "진입 포인터 또는 비선택 소비 문서다"
        package.excluded[ref.identifier] = reason

    texts: list[str] = []
    for ref in package.required + package.optional:
        root = core_root if ref.scope == "core" else consumer_root
        texts.append(resolve_inside(root, ref.path).read_text(encoding="utf-8"))
    joined = "\n".join(texts)
    package.chars = len(joined)
    identifiers = "\n".join(ref.identifier for ref in package.required + package.optional)
    package.digest = fingerprint(f"{identifiers}\n{joined}")

    if package.chars > budget:
        raise ContextBudgetError(
            f"시작 컨텍스트 {package.chars}자가 예산 {budget}자를 넘었다. 절단하지 않고 실패한다"
        )
    return package
