"""검사 등록 인터페이스.

실험 Runtime은 이 인터페이스에 자기 검사를 등록한다. 검증 도구는 실험 Runtime을
import하지 않는다. 의존 방향을 역전시켜 실험 계층 없이도 Kernel 검증이 성립하게 한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from .primitives import Finding

CheckFn = Callable[[Path], Iterable[Finding]]


class CheckRegistry:
    """이름으로 구분되는 검사 모음."""

    def __init__(self) -> None:
        self._required: dict[str, CheckFn] = {}
        self._optional: dict[str, CheckFn] = {}

    def add_required(self, name: str, fn: CheckFn) -> None:
        if name in self._required or name in self._optional:
            raise ValueError(f"검사 이름이 중복된다: {name}")
        self._required[name] = fn

    def add_optional(self, name: str, fn: CheckFn) -> None:
        if name in self._required or name in self._optional:
            raise ValueError(f"검사 이름이 중복된다: {name}")
        self._optional[name] = fn

    @property
    def required(self) -> dict[str, CheckFn]:
        return dict(self._required)

    @property
    def optional(self) -> dict[str, CheckFn]:
        return dict(self._optional)


REGISTRY = CheckRegistry()


def register(name: str, *, required: bool = True) -> Callable[[CheckFn], CheckFn]:
    def decorate(fn: CheckFn) -> CheckFn:
        if required:
            REGISTRY.add_required(name, fn)
        else:
            REGISTRY.add_optional(name, fn)
        return fn

    return decorate
