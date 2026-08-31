"""Core 자체와 선택적 소비 계약을 한 진입점에서 검증하는 통합 게이트."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .context import STARTUP_BUDGET_CHARS, build as build_context
from .declarations import (
    consumer_contract,
    consumer_policy_path,
    declared_compatibility,
    optional_capability_installation_state,
)
from .integrity import (
    host_core_cleanliness,
    host_core_git_fingerprint,
    run_all,
    run_consumer,
)
from .primitives import CheckError, resolve_inside

FALLBACK_MIN_PYTHON = (3, 10)


def _min_python(core_root: Path) -> tuple[int, ...]:
    declared = declared_compatibility(core_root).get("python_min")
    if isinstance(declared, str):
        return tuple(int(part) for part in declared.split("."))
    return FALLBACK_MIN_PYTHON


@dataclass
class StepResult:
    name: str
    status: str
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
    contract_version: int | None = None
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed_step is None

    @property
    def failed_step(self) -> str | None:
        for step in self.steps:
            if step.required and step.status in {"fail", "not_run"}:
                return step.name
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "contract_version": self.contract_version,
            "failed_step": self.failed_step,
            "steps": [step.as_dict() for step in self.steps],
        }


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    git_metadata = root / ".git"

    def frame(value: str | bytes) -> None:
        payload = value.encode("utf-8") if isinstance(value, str) else value
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

    root_stat = root.stat()
    frame("ROOT")
    frame(f"{root_stat.st_mode:o}")
    frame(str(root_stat.st_mtime_ns))
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if git_metadata.is_dir() and (path == git_metadata or git_metadata in path.parents):
            continue
        frame(rel.as_posix())
        stat_result = path.lstat()
        frame(f"{stat_result.st_mode:o}")
        frame(str(stat_result.st_mtime_ns))
        if path.is_symlink():
            frame("LINK")
            frame(os.fsencode(os.readlink(path)))
            continue
        if path.is_dir():
            frame("DIR")
        elif path.is_file():
            frame("FILE")
            frame(path.read_bytes())
        else:
            frame("OTHER")
    return digest.hexdigest()


HostCoreBaseline = tuple[str, str, bool]


def capture_host_core_baseline(
    core_root: Path, *, require_clean: bool = False
) -> HostCoreBaseline:
    """Core tree와 Git 의미 상태를 함께 지문화한다. 호출 전 청결 판정은 별도다."""
    return tree_digest(core_root), host_core_git_fingerprint(core_root), require_clean


def host_core_baseline_status(
    core_root: Path, baseline: HostCoreBaseline
) -> tuple[bool, str]:
    if baseline[2]:
        clean, clean_detail = host_core_cleanliness(core_root)
        if not clean:
            return False, f"Host Core 사후 clean 판정 실패: {clean_detail}"
    try:
        current = capture_host_core_baseline(core_root, require_clean=baseline[2])
    except (CheckError, OSError) as exc:
        return False, f"Host Core 사후 상태를 증명할 수 없다: {exc}"
    if current != baseline:
        return False, "Core tree 또는 HEAD/index 상태가 실행 중 변경됐다"
    return True, "Core tree와 HEAD/index 상태가 실행 전후 동일하다"


def consumer_tree_digest(
    core_root: Path, consumer_root: Path, contract: dict[str, object] | None = None
) -> str:
    """보호 경로와 Core subtree를 읽지 않고 계약 표면만 지문화한다."""
    contract = contract if contract is not None else consumer_contract(core_root, consumer_root)
    paths = {
        consumer_policy_path(core_root, consumer_root),
        resolve_inside(consumer_root, contract["state"]),
    }
    for value in contract["entry_pointers"].values():
        paths.add(resolve_inside(consumer_root, value))
    for value in contract["rule_roots"]:
        paths.update(resolve_inside(consumer_root, value).rglob("*.md"))
    gitmodules = consumer_root / ".gitmodules"
    if gitmodules.is_file():
        paths.add(gitmodules)
    digest = hashlib.sha256()
    for path in sorted(paths):
        rel = path.relative_to(consumer_root)
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _preflight(core_root: Path) -> Iterable[StepResult]:
    try:
        declared = declared_compatibility(core_root)
        minimum = _min_python(core_root)
    except (CheckError, ValueError) as exc:
        yield StepResult("preflight-contract", "fail", str(exc))
        return
    if sys.version_info[: len(minimum)] < minimum:
        yield StepResult(
            "preflight-runtime",
            "fail",
            f"Python {'.'.join(map(str, minimum))} 이상이 필요하다. 현재 {sys.version.split()[0]}",
        )
        return
    missing_dependencies = [
        name for name in declared.get("required_dependencies", []) if shutil.which(name) is None
    ]
    if missing_dependencies:
        yield StepResult(
            "preflight-runtime",
            "fail",
            f"필수 실행 도구가 없다: {', '.join(missing_dependencies)}",
        )
        return
    yield StepResult(
        "preflight-runtime",
        "pass",
        f"Python {sys.version.split()[0]} / core {declared.get('core_version', '미선언')}"
        f" / tools {','.join(declared.get('required_dependencies', [])) or 'none'}",
    )
    if not (core_root / "src").is_dir():
        yield StepResult("preflight-layout", "fail", "src 디렉터리가 없다")
        return
    yield StepResult("preflight-layout", "pass")


def _integrity(core_root: Path) -> StepResult:
    report = run_all(core_root)
    if report.ok:
        return StepResult("core-integrity", "pass", f"검사 {len(report.ran)}종, 위반 0")
    messages = "; ".join(f"{finding.check}:{finding.path}" for finding in report.findings[:5])
    return StepResult("core-integrity", "fail", f"위반 {len(report.findings)}건 — {messages}")


def _consumer_integrity(core_root: Path, consumer_root: Path) -> StepResult:
    report = run_consumer(core_root, consumer_root)
    if report.ok:
        return StepResult("consumer-integrity", "pass", f"검사 {len(report.ran)}종, 위반 0")
    messages = "; ".join(f"{finding.check}:{finding.path}" for finding in report.findings[:5])
    return StepResult("consumer-integrity", "fail", f"위반 {len(report.findings)}건 — {messages}")


def _host_core_read_only_preflight(
    core_root: Path,
    contract: dict[str, object] | None,
    contract_error: CheckError | None,
) -> StepResult:
    if contract_error is not None or contract is None:
        return StepResult(
            "host-core-read-only-preflight",
            "fail",
            "소비 역할을 증명할 수 없어 Core 실행을 시작하지 않는다: "
            f"{contract_error or '계약 없음'}",
        )
    if contract["consumer_role"] != "host":
        return StepResult(
            "host-core-read-only-preflight",
            "not_applicable",
            "maintainer 역할에는 Host 전용 사전 차단을 적용하지 않는다",
            required=False,
        )
    clean, detail = host_core_cleanliness(core_root)
    return StepResult(
        "host-core-read-only-preflight",
        "pass" if clean else "fail",
        detail if clean else f"Core 검사를 시작하지 않는다: {detail}",
    )


def _startup_context(core_root: Path, consumer_root: Path) -> StepResult:
    try:
        package = build_context(core_root, consumer_root)
    except CheckError as exc:
        return StepResult("startup-context", "fail", str(exc))
    return StepResult(
        "startup-context", "pass", f"{package.chars}자 / 예산 {STARTUP_BUDGET_CHARS}자"
    )


def _tests(core_root: Path) -> StepResult:
    tests_dir = core_root / "tests"
    if not tests_dir.is_dir():
        return StepResult("regression-tests", "not_applicable", "tests 디렉터리가 없다")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(core_root / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=core_root,
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


def _optional(
    core_root: Path, *, execution_root: Path, run_internal_tests: bool
) -> StepResult:
    try:
        capabilities = declared_compatibility(core_root).get("optional_capabilities", {})
    except CheckError as exc:
        return StepResult("optional-features", "fail", str(exc))
    if not capabilities:
        return StepResult(
            "optional-features",
            "not_applicable",
            "선택 기능이 등록되지 않았다. 필수 기능 실패가 아니다",
            required=False,
        )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(core_root), str(core_root / "src"), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    installed = 0
    absent = 0
    for capability_id, declaration in sorted(capabilities.items()):
        try:
            state = optional_capability_installation_state(core_root, capability_id, declaration)
        except CheckError as exc:
            return StepResult("optional-features", "fail", str(exc))
        if state == "absent":
            absent += 1
            continue
        installed += 1
        bootstrap = (
            "import runpy,sys;"
            f"sys.path[:0]=[{str(core_root)!r},{str(core_root / 'src')!r}];"
            f"runpy.run_module({declaration['entry_module']!r},run_name='__main__',alter_sys=True)"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-I", "-c", bootstrap, "info"],
            cwd=execution_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {}
        if (
            completed.returncode != 0
            or payload.get("ok") is not True
            or payload.get("capability") != capability_id
            or payload.get("capability_version") != declaration["version"]
            or payload.get("commands") != declaration["commands"]
            or payload.get("request_schema") != declaration["request_schema"]
            or payload.get("result_schema") != declaration["result_schema"]
        ):
            detail = completed.stderr.strip() or completed.stdout.strip() or "info 결과가 선언과 다르다"
            return StepResult("optional-features", "fail", f"{capability_id}: {detail[-500:]}")
        tests_dir = core_root / declaration["entry_module"].replace(".", "/") / "tests"
        if tests_dir.is_dir() and run_internal_tests:
            tested = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(tests_dir), "-q"],
                cwd=execution_root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if tested.returncode != 0:
                return StepResult(
                    "optional-features", "fail", f"{capability_id} tests: {(tested.stderr or '')[-500:]}"
                )
    if installed == 0:
        return StepResult(
            "optional-features",
            "not_applicable",
            f"선택 기능 {absent}종이 완전히 부재한다. 필수 기능 실패가 아니다",
            required=False,
        )
    if not run_internal_tests:
        return StepResult(
            "optional-features",
            "not_applicable",
            (
                f"정적 discovery {installed}종의 선언 일치만 확인했다. "
                "기능 소비·가용성·완료 검증이 아니다"
            ),
            required=False,
        )
    return StepResult(
        "optional-features", "pass", f"공개 선택 기능 {installed}종 검증, 완전 부재 {absent}종"
    )


def _run_once(
    core_root: Path,
    consumer_root: Path | None,
    *,
    contract: dict[str, object] | None,
    before_core: str,
    before_consumer: str | None,
    host_preflight: StepResult | None,
) -> GateResult:
    try:
        version = declared_compatibility(core_root).get("contract_version")
    except CheckError:
        version = None
    result = GateResult(contract_version=version if isinstance(version, int) else None)
    result.steps.extend(_preflight(core_root))
    if result.failed_step is not None:
        result.steps.append(StepResult("core-integrity", "not_run", "preflight 실패로 실행하지 않았다"))
        result.steps.append(StepResult("regression-tests", "not_run", "preflight 실패로 실행하지 않았다"))
        if consumer_root is not None:
            result.steps.append(
                StepResult("consumer-integrity", "not_run", "preflight 실패로 실행하지 않았다")
            )
            result.steps.append(StepResult("startup-context", "not_run", "preflight 실패로 실행하지 않았다"))
        return result

    if consumer_root is not None:
        if host_preflight is None or contract is None:
            raise CheckError("검증된 소비 계약 없이 gate 실행을 시작할 수 없다")
        result.steps.append(host_preflight)
    consumer_role = str(contract["consumer_role"]) if contract is not None else None

    result.steps.append(_integrity(core_root))
    if consumer_role == "host":
        result.steps.append(
            StepResult(
                "regression-tests",
                "not_applicable",
                "Host는 검증된 Core library를 소비하므로 Core 내부 회귀 테스트를 실행하지 않는다",
                required=False,
            )
        )
    else:
        result.steps.append(_tests(core_root))
    result.steps.append(
        _optional(
            core_root,
            execution_root=consumer_root if consumer_role == "host" else core_root,
            run_internal_tests=consumer_role != "host",
        )
    )

    if consumer_root is not None:
        consumer_step = _consumer_integrity(core_root, consumer_root)
        result.steps.append(consumer_step)
        if consumer_step.status == "pass":
            result.steps.append(_startup_context(core_root, consumer_root))
        else:
            result.steps.append(
                StepResult("startup-context", "not_run", "소비 계약 실패로 실행하지 않았다")
            )
        try:
            after_consumer = consumer_tree_digest(core_root, consumer_root, contract)
        except CheckError:
            after_consumer = None
        result.steps.append(
            StepResult(
                "consumer-no-side-effects",
                "pass" if before_consumer is not None and before_consumer == after_consumer else "fail",
                "소비 계약 표면을 바꾸지 않았다"
                if before_consumer is not None and before_consumer == after_consumer
                else "소비 계약 표면의 무부작용을 확인할 수 없다",
            )
        )

    after_core = tree_digest(core_root)
    result.steps.append(
        StepResult(
            "core-no-side-effects",
            "pass" if before_core == after_core else "fail",
            "게이트가 Core를 바꾸지 않았다" if before_core == after_core else "게이트가 Core를 바꿨다",
        )
    )
    return result


def run(core_root: Path, consumer_root: Path | None = None) -> GateResult:
    """계약을 한 번 해석하고 예외·조기 반환에서도 무부작용을 판정한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve() if consumer_root is not None else None
    contract: dict[str, object] | None = None
    contract_error: CheckError | None = None
    if consumer_root is not None:
        try:
            contract = consumer_contract(core_root, consumer_root)
        except CheckError as exc:
            contract_error = exc
    host_preflight = (
        _host_core_read_only_preflight(core_root, contract, contract_error)
        if consumer_root is not None
        else None
    )
    if host_preflight is not None and host_preflight.required and host_preflight.status != "pass":
        result = GateResult(
            contract_version=(
                contract.get("contract_version")
                if contract is not None and isinstance(contract.get("contract_version"), int)
                else None
            )
        )
        result.steps.append(host_preflight)
        for name in (
            "core-integrity",
            "regression-tests",
            "optional-features",
            "consumer-integrity",
            "startup-context",
        ):
            result.steps.append(
                StepResult(name, "not_run", "Host Core 사전 판정 실패로 실행하지 않았다")
            )
        result.steps.append(
            StepResult(
                "core-no-side-effects",
                "pass",
                "사전 read-only 판정 뒤 Core 기능을 실행하지 않았다",
            )
        )
        return result

    host_baseline: HostCoreBaseline | None = None
    if contract is not None and contract["consumer_role"] == "host":
        host_baseline = capture_host_core_baseline(core_root, require_clean=True)
        before_core = host_baseline[0]
    else:
        before_core = tree_digest(core_root)
    if consumer_root is not None and contract is not None:
        try:
            before_consumer = consumer_tree_digest(core_root, consumer_root, contract)
        except CheckError:
            before_consumer = None
    else:
        before_consumer = None
    try:
        result = _run_once(
            core_root,
            consumer_root,
            contract=contract,
            before_core=before_core,
            before_consumer=before_consumer,
            host_preflight=host_preflight,
        )
    except Exception as exc:
        unchanged = tree_digest(core_root) == before_core
        detail = ""
        if host_baseline is not None:
            unchanged, detail = host_core_baseline_status(core_root, host_baseline)
        if not unchanged:
            raise CheckError(detail or "게이트 예외 중 Core tree가 변경됐다") from exc
        raise
    if not any(step.name == "core-no-side-effects" for step in result.steps):
        unchanged = tree_digest(core_root) == before_core
        result.steps.append(
            StepResult(
                "core-no-side-effects",
                "pass" if unchanged else "fail",
                "게이트가 Core를 바꾸지 않았다" if unchanged else "게이트가 Core를 바꿨다",
            )
        )
    if host_baseline is not None:
        unchanged, detail = host_core_baseline_status(core_root, host_baseline)
        side_effect = next(step for step in result.steps if step.name == "core-no-side-effects")
        side_effect.status = "pass" if unchanged else "fail"
        side_effect.detail = detail
    return result
