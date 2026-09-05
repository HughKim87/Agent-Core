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
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise CheckError(f"{DECLARATION} 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckError(f"{DECLARATION} root는 object여야 한다")
    entries = data.get("artifacts", [])
    if not isinstance(entries, list):
        raise CheckError(f"{DECLARATION} 의 artifacts 가 목록이 아니다")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise CheckError(f"{DECLARATION} artifacts[{index}]는 object여야 한다")
        for key in ("source", "target", "generator"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise CheckError(f"{DECLARATION} artifacts[{index}].{key}는 비어 있지 않은 문자열이어야 한다")
        for key in ("source", "target"):
            try:
                if "\0" in entry[key] or Path(entry[key]).is_absolute():
                    raise ValueError("relative path required")
                resolve_inside(root, entry[key])
            except (ValueError, OSError) as exc:
                raise CheckError(f"{DECLARATION} artifacts[{index}].{key} 경로가 유효하지 않다") from exc
    return entries


def regenerate(root: Path, entry: dict[str, str]) -> str:
    source = resolve_inside(root, entry["source"])
    if not source.is_file():
        raise CheckError(f"정본이 없다: {entry['source']}")
    name = entry["generator"]
    if name not in GENERATORS:
        raise CheckError(f"등록되지 않은 생성기: {name}")
    try:
        source_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CheckError(f"정본을 읽을 수 없다: {entry['source']}") from exc
    return GENERATORS[name](source_text)


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

        try:
            actual = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            yield Finding("derived-artifacts", target_name, "artifact를 UTF-8 텍스트로 읽을 수 없다")
            continue
        if fingerprint(actual) != fingerprint(expected):
            yield Finding(
                "derived-artifacts",
                target_name,
                f"정본과 다르다. 정본 {entry['source']} 에서 재생성해야 한다",
            )
