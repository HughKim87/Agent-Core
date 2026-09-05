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
    document_roles,
    optional_capability_installation_state,
)
from .integrity import (
    host_consumer_gitlink_fingerprint,
    host_consumer_gitlink_observation_fingerprint,
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
    evidence: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "detail": self.detail,
            "evidence": self.evidence,
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


class HostObservationError(CheckError):
    """관찰한 상태가 바뀌었거나 불변성을 끝까지 확인할 수 없는 오류."""


HostCoreBaseline = tuple[str, str, bool]


@dataclass(frozen=True)
class HostConsumerBaseline:
    """Host 부모 gitlink와 Core 불변 상태를 함께 고정한 실행 기준선."""

    core_root: Path
    consumer_root: Path
    core_relative: str
    core: HostCoreBaseline
    gitlink: str
    observation: HostConsumerObservation | None


@dataclass(frozen=True)
class HostConsumerObservation:
    """유효성 판정 전 Host 부모 gitlink와 Core 상태의 진단 기준선."""

    core_root: Path
    consumer_root: Path
    core_relative: str
    core: HostCoreBaseline
    gitlink: str
    consumer_policy: Path
    consumer_policy_digest: str


def capture_host_core_baseline(
    core_root: Path, *, require_clean: bool = False
) -> HostCoreBaseline:
    """Core tree와 Git 의미 상태를 지문화하고 요청 시 clean 판정을 결속한다."""
    core_root = core_root.resolve()
    before = tree_digest(core_root), host_core_git_fingerprint(core_root)
    if not require_clean:
        return before[0], before[1], False

    clean, detail = host_core_cleanliness(core_root)
    if not clean:
        raise CheckError(f"Host Core 사전 clean 판정 실패: {detail}")
    after = tree_digest(core_root), host_core_git_fingerprint(core_root)
    if after != before:
        raise CheckError("Host Core가 사전 clean 판정 중 변경됐다")
    return after[0], after[1], True


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


def _policy_file_digest(path: Path) -> str:
    """논리 정책 entry와 symlink target·실제 내용을 함께 지문화한다."""
    path = Path(os.path.abspath(path))
    stat_result = path.lstat()
    digest = hashlib.sha256()
    values: list[bytes] = [
        str(path).encode("utf-8"),
        f"{stat_result.st_mode:o}".encode("ascii"),
        str(stat_result.st_mtime_ns).encode("ascii"),
    ]
    if path.is_symlink():
        target = path.resolve()
        target_stat = target.stat()
        values.extend(
            [
                b"SYMLINK",
                os.fsencode(os.readlink(path)),
                str(target).encode("utf-8"),
                f"{target_stat.st_mode:o}".encode("ascii"),
                str(target_stat.st_mtime_ns).encode("ascii"),
            ]
        )
    else:
        values.append(b"REGULAR")
    values.append(path.read_bytes())
    for value in values:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def capture_host_consumer_observation(
    core_root: Path,
    consumer_root: Path,
    core_relative: str,
) -> HostConsumerObservation:
    """계약 해석 전에 Host 관련 원시 상태가 안정적인지 관찰해 고정한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    core_relative = Path(core_relative).as_posix().rstrip("/")
    before_link = host_consumer_gitlink_observation_fingerprint(
        core_root, consumer_root, core_relative
    )
    core_baseline = capture_host_core_baseline(core_root, require_clean=False)
    roles = document_roles(core_root)
    policy_relative = str(roles["consumer_policy"])
    policy_path = consumer_root / policy_relative
    consumer_policy_path(core_root, consumer_root)
    before_policy = _policy_file_digest(policy_path)
    try:
        middle_link = host_consumer_gitlink_observation_fingerprint(
            core_root, consumer_root, core_relative
        )
        core_unchanged, core_detail = host_core_baseline_status(
            core_root, core_baseline
        )
        after_policy = _policy_file_digest(policy_path)
        after_link = host_consumer_gitlink_observation_fingerprint(
            core_root, consumer_root, core_relative
        )
    except (CheckError, OSError) as exc:
        raise HostObservationError(
            f"Host 관찰 기준선의 불변성을 확인할 수 없다: {exc}"
        ) from exc
    if not core_unchanged:
        raise HostObservationError(f"Host 관찰 기준선 고정 중 {core_detail}")
    if before_link != middle_link or middle_link != after_link:
        raise HostObservationError("Host 부모 gitlink가 관찰 기준선 고정 중 변경됐다")
    if before_policy != after_policy:
        raise HostObservationError("소비 역할·계약 정책이 관찰 기준선 고정 중 변경됐다")
    return HostConsumerObservation(
        core_root=core_root,
        consumer_root=consumer_root,
        core_relative=core_relative,
        core=core_baseline,
        gitlink=after_link,
        consumer_policy=policy_path,
        consumer_policy_digest=after_policy,
    )


def host_consumer_observation_status(
    observation: HostConsumerObservation,
) -> tuple[bool, str]:
    """유효 여부와 무관하게 Host 관찰 기준선이 그대로인지 판정한다."""
    try:
        before_link = host_consumer_gitlink_observation_fingerprint(
            observation.core_root,
            observation.consumer_root,
            observation.core_relative,
        )
    except (CheckError, OSError) as exc:
        return False, f"Host 부모 gitlink 관찰 상태를 증명할 수 없다: {exc}"
    try:
        before_policy = _policy_file_digest(observation.consumer_policy)
    except OSError as exc:
        return False, f"소비 역할·계약 정책 상태를 증명할 수 없다: {exc}"
    core_unchanged, core_detail = host_core_baseline_status(
        observation.core_root, observation.core
    )
    try:
        after_policy = _policy_file_digest(observation.consumer_policy)
    except OSError as exc:
        return False, f"소비 역할·계약 정책 상태를 증명할 수 없다: {exc}"
    try:
        after_link = host_consumer_gitlink_observation_fingerprint(
            observation.core_root,
            observation.consumer_root,
            observation.core_relative,
        )
    except (CheckError, OSError) as exc:
        return False, f"Host 부모 gitlink 관찰 상태를 증명할 수 없다: {exc}"
    if not core_unchanged:
        return False, core_detail
    if (
        before_policy != observation.consumer_policy_digest
        or after_policy != observation.consumer_policy_digest
    ):
        return False, "소비 역할·계약 정책이 실행 중 변경됐다"
    if before_link != observation.gitlink or after_link != observation.gitlink:
        return False, "Host 부모 gitlink 관찰 상태가 실행 중 변경됐다"
    return True, "Host 부모 gitlink와 Core 원시 상태가 관찰 전후 동일하다"


def capture_host_consumer_baseline(
    core_root: Path,
    consumer_root: Path,
    core_relative: str,
    *,
    require_clean: bool,
    expected_observation: HostConsumerObservation | None = None,
) -> HostConsumerBaseline:
    """Host gitlink와 Core 상태를 하나의 안정된 실행 기준선으로 결속한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    core_relative = Path(core_relative).as_posix().rstrip("/")
    if expected_observation is not None:
        if (
            expected_observation.core_root != core_root
            or expected_observation.consumer_root != consumer_root
            or expected_observation.core_relative != core_relative
        ):
            raise CheckError("Host 관찰 기준선의 실행 대상이 현재 요청과 다르다")
        unchanged, detail = host_consumer_observation_status(expected_observation)
        if not unchanged:
            raise CheckError(f"Host 계약 해석 중 상태가 변경됐다: {detail}")
    before_link = host_consumer_gitlink_fingerprint(
        core_root, consumer_root, core_relative
    )
    core_baseline = capture_host_core_baseline(
        core_root, require_clean=require_clean
    )
    middle_link = host_consumer_gitlink_fingerprint(
        core_root, consumer_root, core_relative
    )
    core_unchanged, core_detail = host_core_baseline_status(
        core_root, core_baseline
    )
    after_link = host_consumer_gitlink_fingerprint(
        core_root, consumer_root, core_relative
    )
    if not core_unchanged:
        raise CheckError(f"Host 결속 기준선 고정 중 {core_detail}")
    if before_link != middle_link or middle_link != after_link:
        raise CheckError("Host 부모 gitlink가 결속 기준선 고정 중 변경됐다")
    if expected_observation is not None:
        unchanged, detail = host_consumer_observation_status(expected_observation)
        if not unchanged:
            raise CheckError(f"Host 결속 기준선 고정 중 상태가 변경됐다: {detail}")
    return HostConsumerBaseline(
        core_root=core_root,
        consumer_root=consumer_root,
        core_relative=core_relative,
        core=core_baseline,
        gitlink=after_link,
        observation=expected_observation,
    )


def host_consumer_baseline_status(
    baseline: HostConsumerBaseline,
) -> tuple[bool, str]:
    """Host 부모 gitlink와 Core 상태가 결속 기준선에서 함께 불변인지 판정한다."""
    try:
        before_link = host_consumer_gitlink_fingerprint(
            baseline.core_root,
            baseline.consumer_root,
            baseline.core_relative,
        )
    except (CheckError, OSError) as exc:
        return False, f"Host 부모 gitlink 사후 상태를 증명할 수 없다: {exc}"
    core_unchanged, core_detail = host_core_baseline_status(
        baseline.core_root, baseline.core
    )
    try:
        after_link = host_consumer_gitlink_fingerprint(
            baseline.core_root,
            baseline.consumer_root,
            baseline.core_relative,
        )
    except (CheckError, OSError) as exc:
        return False, f"Host 부모 gitlink 사후 상태를 증명할 수 없다: {exc}"
    if not core_unchanged:
        return False, core_detail
    if before_link != baseline.gitlink or after_link != baseline.gitlink:
        return False, "Host 부모 gitlink 또는 실행 Core HEAD가 실행 중 변경됐다"
    if baseline.observation is not None:
        observation_unchanged, observation_detail = host_consumer_observation_status(
            baseline.observation
        )
        if not observation_unchanged:
            return False, observation_detail
    return True, "Host 부모 gitlink와 Core tree·HEAD/index 상태가 실행 전후 동일하다"


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
    consumer_root: Path,
    contract: dict[str, object] | None,
    contract_error: CheckError | None,
    entry_observation: HostConsumerObservation | None,
    observation_error: Exception | None,
) -> tuple[StepResult, HostConsumerBaseline | None]:
    if isinstance(observation_error, HostObservationError):
        return (
            StepResult(
                "host-core-read-only-preflight",
                "fail",
                f"Core 검사를 시작하지 않는다: {observation_error}",
            ),
            None,
        )
    if contract_error is not None or contract is None:
        return (
            StepResult(
                "host-core-read-only-preflight",
                "fail",
                "소비 역할을 증명할 수 없어 Core 실행을 시작하지 않는다: "
                f"{contract_error or '계약 없음'}",
            ),
            None,
        )
    if entry_observation is not None:
        unchanged, detail = host_consumer_observation_status(entry_observation)
        if not unchanged:
            return (
                StepResult(
                    "host-core-read-only-preflight",
                    "fail",
                    f"Core 검사를 시작하지 않는다: 소비 계약 해석 중 상태가 변경됐다: {detail}",
                ),
                None,
            )
    if contract["consumer_role"] != "host":
        return (
            StepResult(
                "host-core-read-only-preflight",
                "not_applicable",
                "maintainer 역할에는 Host 전용 사전 차단을 적용하지 않는다",
                required=False,
            ),
            None,
        )
    if entry_observation is None:
        return (
            StepResult(
                "host-core-read-only-preflight",
                "fail",
                "Core 검사를 시작하지 않는다: 계약 해석 전 Host 상태를 "
                f"고정할 수 없다: {observation_error or '관찰 기준선 없음'}",
            ),
            None,
        )
    try:
        baseline = capture_host_consumer_baseline(
            core_root,
            consumer_root,
            str(contract["core_path"]),
            require_clean=True,
            expected_observation=entry_observation,
        )
    except (CheckError, OSError) as exc:
        return (
            StepResult(
                "host-core-read-only-preflight",
                "fail",
                f"Core 검사를 시작하지 않는다: {exc}",
            ),
            None,
        )
    return (
        StepResult(
            "host-core-read-only-preflight",
            "pass",
            "부모 gitlink와 clean Core 상태를 하나의 실행 기준선으로 고정했다",
        ),
        baseline,
    )


def _startup_context(core_root: Path, consumer_root: Path) -> StepResult:
    try:
        package = build_context(core_root, consumer_root)
    except CheckError as exc:
        return StepResult("startup-context", "fail", str(exc))
    return StepResult(
        "startup-context", "pass", f"{package.chars}자 / 예산 {STARTUP_BUDGET_CHARS}자"
    )


_UNITTEST_RUNNER = r"""
import contextlib, json, sys, unittest
with contextlib.redirect_stdout(sys.stderr):
    suite = unittest.TestLoader().discover(sys.argv[1], pattern="test_*.py")
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
skipped = [{"test": str(test), "reason": reason} for test, reason in result.skipped]
executed = result.testsRun - len(skipped)
status = "fail" if not result.wasSuccessful() else ("pass" if executed else "not_run")
print(json.dumps({"status": status, "tests_run": result.testsRun, "executed": executed,
                  "skipped": len(skipped), "skip_reasons": skipped,
                  "failures": len(result.failures), "errors": len(result.errors),
                  "expected_failures": len(result.expectedFailures),
                  "unexpected_successes": len(result.unexpectedSuccesses)}))
sys.exit(0 if status == "pass" else 1)
"""


def _test_suite(tests_dir: Path, *, execution_root: Path, environment: dict[str, str]) -> StepResult:
    evidence: dict[str, object] = {"target": str(tests_dir), "tests_run": None, "executed": None}
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", _UNITTEST_RUNNER, str(tests_dir)],
            cwd=execution_root, env=environment, capture_output=True,
            text=True, encoding="utf-8", check=False,
        )
    except OSError as exc:
        return StepResult("regression-tests", "not_run", str(exc), evidence=evidence)
    evidence.update({"returncode": completed.returncode, "stdout": completed.stdout,
                     "stderr": completed.stderr})
    try:
        payload = json.loads(completed.stdout)
        counts = ("tests_run", "executed", "skipped", "failures", "errors",
                  "expected_failures", "unexpected_successes")
        if not isinstance(payload, dict) or any(
            type(payload.get(key)) is not int or payload[key] < 0 for key in counts
        ):
            raise ValueError("invalid test counts")
        if (not isinstance(payload.get("skip_reasons"), list)
                or len(payload["skip_reasons"]) != payload["skipped"]
                or payload["tests_run"] != payload["executed"] + payload["skipped"]):
            raise ValueError("inconsistent test counts")
        status = ("fail" if payload["failures"] or payload["errors"] or payload["unexpected_successes"]
                  else "pass" if payload["executed"] else "not_run")
        if payload.get("status") != status:
            raise ValueError("inconsistent test status")
    except (ValueError, TypeError):
        return StepResult("regression-tests", "not_run", "수행 결과가 없거나 해석할 수 없다", evidence=evidence)
    evidence.update(payload)
    if completed.returncode != (0 if status == "pass" else 1):
        status = "fail"
    detail = (f"{tests_dir}: run={payload['tests_run']}, executed={payload['executed']}, "
              f"skipped={payload['skipped']}, failures={payload['failures']}, errors={payload['errors']}")
    return StepResult("regression-tests", status, detail, evidence=evidence)


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
    return _test_suite(tests_dir, execution_root=core_root, environment=env)


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
    suites: dict[str, object] = {}
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
            tested = _test_suite(tests_dir, execution_root=execution_root, environment=environment)
            suites[capability_id] = tested.as_dict()
            if tested.status != "pass":
                return StepResult("optional-features", tested.status,
                                  f"{capability_id} tests: {tested.detail}", evidence={"suites": suites})
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
        "optional-features", "pass", f"공개 선택 기능 {installed}종 검증, 완전 부재 {absent}종",
        evidence={"suites": suites}
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
            "게이트 실행 구간에 Core tree가 변경되지 않았다"
            if before_core == after_core
            else "게이트 실행 구간에 Core tree가 변경되어 무부작용을 증명할 수 없다",
        )
    )
    return result


def run(core_root: Path, consumer_root: Path | None = None) -> GateResult:
    """계약을 한 번 해석하고 예외·조기 반환에서도 무부작용을 판정한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve() if consumer_root is not None else None
    entry_core_digest = tree_digest(core_root)
    try:
        entry_git_fingerprint = host_core_git_fingerprint(core_root)
    except (CheckError, OSError):
        entry_git_fingerprint = None
    entry_host_observation: HostConsumerObservation | None = None
    entry_host_observation_error: Exception | None = None
    if consumer_root is not None:
        try:
            entry_core_relative = core_root.relative_to(consumer_root).as_posix()
            entry_host_observation = capture_host_consumer_observation(
                core_root,
                consumer_root,
                entry_core_relative,
            )
        except (CheckError, OSError, ValueError) as exc:
            entry_host_observation_error = exc
    contract: dict[str, object] | None = None
    contract_error: CheckError | None = None
    if consumer_root is not None:
        try:
            contract = consumer_contract(core_root, consumer_root)
        except CheckError as exc:
            contract_error = exc
    host_preflight_result = (
        _host_core_read_only_preflight(
            core_root,
            consumer_root,
            contract,
            contract_error,
            entry_host_observation,
            entry_host_observation_error,
        )
        if consumer_root is not None
        else None
    )
    if host_preflight_result is None:
        host_preflight = None
        host_baseline = None
    else:
        host_preflight, host_baseline = host_preflight_result
    if host_preflight is not None and host_preflight.required and host_preflight.status != "pass":
        tree_unchanged = tree_digest(core_root) == entry_core_digest
        is_host = contract is not None and contract.get("consumer_role") == "host"
        git_unchanged = True
        if is_host:
            if entry_git_fingerprint is None:
                git_unchanged = False
            else:
                try:
                    git_unchanged = (
                        host_core_git_fingerprint(core_root) == entry_git_fingerprint
                    )
                except (CheckError, OSError):
                    git_unchanged = False
        unchanged = tree_unchanged and git_unchanged
        observation_detail = ""
        if entry_host_observation is not None:
            observation_unchanged, observation_detail = (
                host_consumer_observation_status(entry_host_observation)
            )
            unchanged = unchanged and observation_unchanged
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
                "pass" if unchanged else "fail",
                "Host 사전 판정 구간에 Core tree와 Git 의미 상태가 변경되지 않았다"
                if unchanged and is_host
                else (
                    "사전 판정 구간에 Core tree가 변경되지 않았다"
                    if unchanged
                    else (
                        "사전 판정 구간의 Core·부모 gitlink·소비 계약 "
                        "무부작용을 증명할 수 없다"
                        + (f": {observation_detail}" if observation_detail else "")
                    )
                ),
            )
        )
        return result

    if host_baseline is not None:
        before_core = host_baseline.core[0]
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
            unchanged, detail = host_consumer_baseline_status(host_baseline)
        if not unchanged:
            raise CheckError(detail or "게이트 예외 중 Core tree가 변경됐다") from exc
        raise
    if not any(step.name == "core-no-side-effects" for step in result.steps):
        unchanged = tree_digest(core_root) == before_core
        result.steps.append(
            StepResult(
                "core-no-side-effects",
                "pass" if unchanged else "fail",
                "게이트 실행 구간에 Core tree가 변경되지 않았다"
                if unchanged
                else "게이트 실행 구간에 Core tree가 변경되어 무부작용을 증명할 수 없다",
            )
        )
    if host_baseline is not None:
        unchanged, detail = host_consumer_baseline_status(host_baseline)
        side_effect = next(step for step in result.steps if step.name == "core-no-side-effects")
        side_effect.status = "pass" if unchanged else "fail"
        side_effect.detail = detail
    return result
