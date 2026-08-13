"""선택적 문서 읽기와 시작 컨텍스트 구성.

전체 트리를 읽지 않고 현재 작업에 필요한 정본만 결정론적으로 고른다.
같은 입력은 같은 목록과 같은 지문을 만든다. 예산을 넘으면 임의로 자르지 않고 실패한다.

소비자: 통합 검증 게이트가 시작 컨텍스트의 크기 한계를 강제할 때 사용한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .declarations import role_path, routed_rule_paths, walk_markdown
from .primitives import CheckError, Finding, fingerprint, resolve_inside
from .registry import register

# 시작 문맥 예산. 정책 + 현재 상태만으로 이 값을 넘으면 문서 구조에 문제가 있다.
STARTUP_BUDGET_CHARS = 20_000


class ContextBudgetError(CheckError):
    """예산을 넘었다. 임의 절단 대신 명시적으로 실패한다."""


@dataclass
class ContextPackage:
    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    chars: int = 0
    digest: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "required": list(self.required),
            "optional": list(self.optional),
            "excluded": dict(sorted(self.excluded.items())),
            "chars": self.chars,
            "digest": self.digest,
        }


def find_router(root: Path) -> Path:
    return role_path(root, "policy")


def find_state(root: Path) -> Path:
    return role_path(root, "state")


def routed_rules(root: Path) -> list[str]:
    return routed_rule_paths(root)


def build(root: Path, matched: Iterable[str] = (), *, budget: int = STARTUP_BUDGET_CHARS) -> ContextPackage:
    """시작 컨텍스트를 만든다.

    필수: 라우터와 현재 상태. 선택: 현재 행동에 일치한 규칙만.
    """
    root = root.resolve()
    package = ContextPackage()

    for path in (find_router(root), find_state(root)):
        package.required.append(path.relative_to(root).as_posix())

    available = set(routed_rules(root))
    for name in matched:
        if name not in available:
            raise CheckError(f"라우팅되지 않은 소유자를 요청했다: {name}")
        package.optional.append(name)

    # 기본 선택에서 제외하는 것
    for path in walk_markdown(root):
        rel = path.relative_to(root).as_posix()
        if rel in package.required or rel in package.optional:
            continue
        if rel.startswith("failures/"):
            package.excluded[rel] = "해결 실패 지식은 해당 영역 진입 시에만 검색한다"
        elif rel.startswith("rules/"):
            package.excluded[rel] = "현재 행동에 route가 일치하지 않는다"
        else:
            package.excluded[rel] = "계약·설계 문서는 필요 시 링크로 도달한다"

    texts = []
    for rel in package.required + package.optional:
        texts.append(resolve_inside(root, rel).read_text(encoding="utf-8"))
    joined = "\n".join(texts)
    package.chars = len(joined)
    package.digest = fingerprint("\n".join(package.required + package.optional) + "\n" + joined)

    if package.chars > budget:
        raise ContextBudgetError(
            f"시작 컨텍스트 {package.chars}자가 예산 {budget}자를 넘었다. 절단하지 않고 실패한다"
        )
    return package


@register("startup-context-budget")
def check_startup_context(root: Path) -> Iterable[Finding]:
    """시작 문맥이 단계 수에 비례해 커지지 않는지 확인한다."""
    try:
        build(root)
    except ContextBudgetError as exc:
        yield Finding("startup-context-budget", "-", str(exc))
    except CheckError as exc:
        yield Finding("startup-context-budget", "-", f"컨텍스트를 만들 수 없다: {exc}")
