"""결정론적 파생 artifact의 선언과 drift 검사.

파생 artifact는 인간 정본에서 결정론적으로 만들어진다. 직접 수정하지 않고 정본에서
다시 만든다. 선언이 없으면 이 검사는 대상 없음으로 통과한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import json
from pathlib import Path

from .primitives import CheckError, Finding, fingerprint, resolve_inside
from .registry import register

DECLARATION = "derived-artifacts.json"

# 생성기 이름 → 정본 텍스트를 artifact 텍스트로 바꾸는 순수 함수
GENERATORS: dict[str, Callable[[str], str]] = {}


def generator(name: str) -> Callable[[Callable[[str], str]], Callable[[str], str]]:
    def decorate(fn: Callable[[str], str]) -> Callable[[str], str]:
        if name in GENERATORS:
            raise ValueError(f"생성기 이름이 중복된다: {name}")
        GENERATORS[name] = fn
        return fn

    return decorate


def load_declaration(root: Path) -> list[dict[str, str]]:
    path = root / DECLARATION
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CheckError(f"{DECLARATION} 파싱 실패: {exc}") from exc
    entries = data.get("artifacts", [])
    if not isinstance(entries, list):
        raise CheckError(f"{DECLARATION} 의 artifacts 가 목록이 아니다")
    return entries


def regenerate(root: Path, entry: dict[str, str]) -> str:
    source = resolve_inside(root, entry["source"])
    if not source.is_file():
        raise CheckError(f"정본이 없다: {entry['source']}")
    name = entry["generator"]
    if name not in GENERATORS:
        raise CheckError(f"등록되지 않은 생성기: {name}")
    return GENERATORS[name](source.read_text(encoding="utf-8"))


@register("derived-artifacts")
def check_derived_artifacts(root: Path) -> Iterable[Finding]:
    try:
        entries = load_declaration(root)
    except CheckError as exc:
        yield Finding("derived-artifacts", DECLARATION, str(exc))
        return

    seen_targets: set[str] = set()
    for entry in entries:
        missing = [k for k in ("source", "target", "generator") if k not in entry]
        if missing:
            yield Finding("derived-artifacts", DECLARATION, f"선언 항목 누락: {missing}")
            continue

        target_name = entry["target"]
        if target_name in seen_targets:
            yield Finding("derived-artifacts", target_name, "같은 artifact에 정본이 둘 이상이다")
            continue
        seen_targets.add(target_name)

        try:
            expected = regenerate(root, entry)
        except CheckError as exc:
            yield Finding("derived-artifacts", target_name, str(exc))
            continue

        target = resolve_inside(root, target_name)
        if not target.is_file():
            yield Finding("derived-artifacts", target_name, "artifact가 없다. 정본에서 재생성해야 한다")
            continue

        actual = target.read_text(encoding="utf-8")
        if fingerprint(actual) != fingerprint(expected):
            yield Finding(
                "derived-artifacts",
                target_name,
                f"정본과 다르다. 정본 {entry['source']} 에서 재생성해야 한다",
            )
