"""Core 무결성 검사.

L5 검증 도구 계층. L6 기반 원시(`primitives`)만 의존하며 실험 Runtime을 import하지 않는다.
"""

from .primitives import CheckError, Finding, resolve_inside
from .registry import CheckRegistry, register
from .integrity import run_all
from . import context as context  # noqa: F401  검사 등록을 위해 import 한다
from . import derived  # noqa: F401  검사 등록을 위해 import 한다

__all__ = [
    "CheckError",
    "CheckRegistry",
    "Finding",
    "register",
    "resolve_inside",
    "run_all",
]
