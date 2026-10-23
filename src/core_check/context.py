"""Core와 소비 저장소를 분리한 시작 컨텍스트 구성."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .declarations import (
    consumer_contract,
    consumer_contract_files,
    consumer_read_text,
    consumer_policy_path,
    consumer_routed_rule_paths,
    core_policy_path,
    routed_rule_paths,
    walk_markdown,
)
from .primitives import CheckError, Finding, WARNING_REVIEW_GUIDANCE, fingerprint, resolve_inside

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
    budget: int | None = None
    diagnostics: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "required": [ref.as_dict() for ref in self.required],
            "optional": [ref.as_dict() for ref in self.optional],
            "excluded": dict(sorted(self.excluded.items())),
            "chars": self.chars,
            "digest": self.digest,
            "budget": self.budget,
            "review_threshold": STARTUP_BUDGET_CHARS,
            "warning_count": len(self.diagnostics),
            "diagnostics": [finding.as_dict() for finding in self.diagnostics],
            "assessment_scope": "context-selection-and-size",
            "review_guidance": WARNING_REVIEW_GUIDANCE if self.diagnostics else None,
        }


def _ref(scope: str, root: Path, path: Path) -> ContextRef:
    return ContextRef(scope, path.relative_to(root).as_posix())


def _consumer_markdown(core_root: Path, consumer_root: Path) -> list[Path]:
    contract = consumer_contract(core_root, consumer_root)
    return consumer_contract_files(core_root, consumer_root, contract, include_gitmodules=False)


def build(
    core_root: Path,
    consumer_root: Path,
    matched: Iterable[str] = (),
    *,
    budget: int | None = None,
) -> ContextPackage:
    """필수 세 문서와 현재 행동에 일치한 scoped 규칙만 선택한다."""
    if budget is not None and (type(budget) is not int or budget <= 0):
        raise ContextBudgetError("시작 컨텍스트 예산은 양의 정수여야 한다")
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    contract = consumer_contract(core_root, consumer_root)
    package = ContextPackage(budget=budget)

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

    for name in dict.fromkeys(matched):
        if name not in available:
            raise CheckError(f"라우팅되지 않은 scoped 소유자를 요청했다: {name}")
        package.optional.append(available[name])

    selected = {ref.identifier for ref in package.required + package.optional}
    for path in walk_markdown(core_root):
        ref = _ref("core", core_root, path)
        if ref.identifier in selected:
            continue
        if ref.path.startswith("failures/"):
            reason = "별도 실패 사건 문서는 Core gate가 거부하며 시작 문맥에 포함하지 않는다"
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
        if ref.scope == "consumer":
            texts.append(consumer_read_text(core_root, consumer_root, contract, root / ref.path))
        else:
            texts.append(resolve_inside(root, ref.path).read_text(encoding="utf-8"))
    joined = "\n".join(texts)
    package.chars = len(joined)
    identifiers = "\n".join(ref.identifier for ref in package.required + package.optional)
    package.digest = fingerprint(f"{identifiers}\n{joined}")

    if budget is not None and package.chars > budget:
        raise ContextBudgetError(
            f"시작 컨텍스트 {package.chars}자가 예산 {budget}자를 넘었다. 절단하지 않고 실패한다"
        )
    if package.chars > STARTUP_BUDGET_CHARS:
        package.diagnostics.append(Finding(
            "startup-context", "-",
            f"시작 컨텍스트 {package.chars}자가 길이 검토 기준 {STARTUP_BUDGET_CHARS}자를 넘었다. "
            "필요한 정책·재개 정보의 누락 없이 중복과 라우팅 범위를 검토한다. "
            "내용의 충분성과 실제 실행 환경의 용량은 별도로 확인한다",
            severity="warning",
        ))
    return package
