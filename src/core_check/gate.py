"""Core Kernel 통합 검증 게이트.

하나의 진입점으로 preflight, 무결성 검사, 회귀 테스트를 실행한다.
필수 단계 실패와 선택 기능 부재를 서로 다른 상태로 구분한다.
게이트 자체는 작업 트리를 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .context import STARTUP_BUDGET_CHARS, build as build_context
from .integrity import run_all
from .primitives import CheckError

SKIP_DIRS = {".git", "__pycache__", ".obsidian"}
COMPAT_BLOCK = re.compile(
    r"<!--\s*core-compatibility:v1\s*-->\s*```json\s*(.*?)```", re.S
)
FALLBACK_MIN_PYTHON = (3, 10)


def declared_compatibility(root: Path) -> dict[str, object]:
    """지원 버전 선언을 조회한다. 값을 코드에 다시 적지 않는다."""
    for path in sorted((root / "docs").glob("*.md")) if (root / "docs").is_dir() else []:
        match = COMPAT_BLOCK.search(path.read_text(encoding="utf-8"))
        if match:
            return json.loads(match.group(1))
    return {}


def _min_python(root: Path) -> tuple[int, ...]:
    declared = declared_compatibility(root).get("python_min")
    if isinstance(declared, str):
        return tuple(int(part) for part in declared.split("."))
    return FALLBACK_MIN_PYTHON


@dataclass
class StepResult:
    name: str
    status: str  # pass | fail | not_run | not_applicable
    detail: str = ""
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "detail": self.detail,
        }


@dataclass
class GateResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed_step is None

    @property
    def failed_step(self) -> str | None:
        """실패로 보는 것은 `fail`과 `not_run`이다.

        `not_applicable`은 이유가 기록된 정당한 비해당이므로 실패가 아니다.
        반면 `not_run`은 실행하지 않은 것이므로 통과가 아니다.
        """
        for step in self.steps:
            if step.required and step.status in {"fail", "not_run"}:
                return step.name
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "failed_step": self.failed_step,
            "steps": [s.as_dict() for s in self.steps],
        }


def tree_digest(root: Path) -> str:
    """추적 대상 파일의 내용 지문. 게이트가 트리를 바꿨는지 확인한다."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not path.is_file():
            continue
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _preflight(root: Path) -> Iterable[StepResult]:
    minimum = _min_python(root)
    if sys.version_info[: len(minimum)] < minimum:
        yield StepResult(
            "preflight-runtime",
            "fail",
            f"Python {'.'.join(map(str, minimum))} 이상이 필요하다. 현재 {sys.version.split()[0]}",
        )
        return
    declared = declared_compatibility(root)
    label = declared.get("core_version", "미선언")
    yield StepResult(
        "preflight-runtime", "pass", f"Python {sys.version.split()[0]} / core {label}"
    )

    if not (root / "src").is_dir():
        yield StepResult("preflight-layout", "fail", "src 디렉터리가 없다")
        return
    yield StepResult("preflight-layout", "pass")


def _integrity(root: Path) -> StepResult:
    report = run_all(root)
    if report.ok:
        return StepResult("integrity", "pass", f"검사 {len(report.ran)}종, 위반 0")
    messages = "; ".join(f"{f.check}:{f.path}" for f in report.findings[:5])
    return StepResult("integrity", "fail", f"위반 {len(report.findings)}건 — {messages}")


def _startup_context(root: Path) -> StepResult:
    try:
        package = build_context(root)
    except CheckError as exc:
        return StepResult("startup-context", "fail", str(exc))
    return StepResult(
        "startup-context", "pass", f"{package.chars}자 / 예산 {STARTUP_BUDGET_CHARS}자"
    )


REENTRY_FLAG = "CORE_CHECK_IN_GATE"


def _tests(root: Path) -> StepResult:
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return StepResult("regression-tests", "not_applicable", "tests 디렉터리가 없다")
    if os.environ.get(REENTRY_FLAG) == "1":
        # 게이트가 실행한 테스트 안에서 게이트를 다시 부르면 무한 재귀가 된다.
        # 회귀 테스트는 이미 바깥 게이트가 실행 중이므로 여기서는 건너뛴다.
        return StepResult(
            "regression-tests", "not_applicable", "게이트 안에서 호출되어 재진입을 막았다"
        )
    env = os.environ.copy()
    env[REENTRY_FLAG] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode == 0:
        tail = (completed.stderr or "").strip().splitlines()
        return StepResult("regression-tests", "pass", tail[-2] if len(tail) > 1 else "OK")
    return StepResult("regression-tests", "fail", (completed.stderr or "")[-500:])


def _optional(root: Path) -> StepResult:
    from .registry import REGISTRY

    if not REGISTRY.optional:
        return StepResult(
            "optional-features",
            "not_applicable",
            "선택 기능이 등록되지 않았다. 필수 기능 실패가 아니다",
            required=False,
        )
    return StepResult(
        "optional-features", "pass", f"{len(REGISTRY.optional)}종 등록", required=False
    )


def run(root: Path) -> GateResult:
    root = root.resolve()
    before = tree_digest(root)

    result = GateResult()
    result.steps.extend(_preflight(root))
    if result.failed_step is not None:
        result.steps.append(StepResult("integrity", "not_run", "preflight 실패로 실행하지 않았다"))
        result.steps.append(StepResult("startup-context", "not_run", "preflight 실패로 실행하지 않았다"))
        result.steps.append(StepResult("regression-tests", "not_run", "preflight 실패로 실행하지 않았다"))
        return result

    result.steps.append(_integrity(root))
    result.steps.append(_startup_context(root))
    result.steps.append(_tests(root))
    result.steps.append(_optional(root))

    after = tree_digest(root)
    result.steps.append(
        StepResult(
            "no-side-effects",
            "pass" if before == after else "fail",
            "게이트가 작업 트리를 바꾸지 않았다" if before == after else "게이트가 작업 트리를 바꿨다",
        )
    )
    return result
