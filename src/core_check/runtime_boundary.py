"""선택 Runtime이 Consumer 쓰기 경계를 넘지 않게 하는 좁은 L5 인터페이스."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .declarations import consumer_contract, declared_compatibility
from .gate import (
    HostObservationError,
    HostCoreBaseline,
    HostConsumerBaseline,
    capture_host_core_baseline,
    capture_host_consumer_baseline,
    capture_host_consumer_observation,
    host_core_baseline_status,
    host_consumer_baseline_status,
    host_consumer_observation_status,
)
from .primitives import CheckError, resolve_inside


class RuntimeBoundaryError(CheckError):
    """공개 선택 Runtime을 안전한 소비 경계에서 시작할 수 없는 상태."""


@dataclass(frozen=True)
class ConsumerRuntimeBoundary:
    """검증된 Consumer Runtime 경계와 선택적인 Host Core 기준선."""

    core_root: Path
    consumer_root: Path
    write_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    host_baseline: HostConsumerBaseline | None


def _paths_overlap(first: Path, second: Path) -> bool:
    first = first.resolve()
    second = second.resolve()
    return first == second or first in second.parents or second in first.parents


def _runtime_error(message: str, exc: Exception | None = None) -> RuntimeBoundaryError:
    error = RuntimeBoundaryError(message)
    if exc is not None:
        error.__cause__ = exc
    return error


def prepare_consumer_runtime_boundary(
    core_root: Path,
    consumer_root: Path,
    *,
    capability_id: str,
    write_paths: Iterable[str | Path],
    protected_paths: Iterable[str | Path] = (),
) -> ConsumerRuntimeBoundary:
    """계약·기능·쓰기 위치를 확인한 뒤 선택 Runtime 실행 경계를 고정한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    entry_observation = None
    entry_observation_error: Exception | None = None
    try:
        entry_core_relative = core_root.relative_to(consumer_root).as_posix()
        entry_observation = capture_host_consumer_observation(
            core_root,
            consumer_root,
            entry_core_relative,
        )
    except HostObservationError as exc:
        raise _runtime_error(f"Host 관찰 기준선 검사 실패: {exc}", exc)
    except (CheckError, OSError, ValueError) as exc:
        entry_observation_error = exc
    try:
        contract = consumer_contract(core_root, consumer_root)
        compatibility = declared_compatibility(core_root)
    except (CheckError, OSError) as exc:
        raise _runtime_error(f"검증된 Consumer 계약이 필요하다: {exc}", exc)

    if entry_observation is not None:
        unchanged, detail = host_consumer_observation_status(entry_observation)
        if not unchanged:
            raise RuntimeBoundaryError(f"소비 계약 해석 중 상태가 변경됐다: {detail}")

    contract_version = contract.get("contract_version")
    active_contract_version = compatibility.get("contract_version")
    if contract_version != active_contract_version:
        raise RuntimeBoundaryError(
            "Consumer와 Core의 contract_version이 일치해야 한다: "
            f"consumer={contract_version}, core={active_contract_version}"
        )

    capabilities = compatibility.get("optional_capabilities")
    capability = capabilities.get(capability_id) if isinstance(capabilities, dict) else None
    if not isinstance(capability, dict):
        raise RuntimeBoundaryError(f"Core 공개 계약에 등록되지 않은 선택 기능이다: {capability_id}")
    available_version = capability.get("version")
    required_capabilities = contract.get("required_core_capabilities")
    minimum_version = (
        required_capabilities.get(capability_id)
        if isinstance(required_capabilities, dict)
        else None
    )
    if not isinstance(minimum_version, int) or isinstance(minimum_version, bool):
        raise RuntimeBoundaryError(
            "Consumer가 호출할 선택 기능과 최소 버전을 "
            f"required_core_capabilities에 선언해야 한다: {capability_id}"
        )
    if not isinstance(available_version, int) or available_version < minimum_version:
        raise RuntimeBoundaryError(
            f"Consumer가 요구한 {capability_id} v{minimum_version}을 Core가 제공하지 않는다"
        )

    canonical_write_paths: list[str] = []
    for candidate in write_paths:
        try:
            resolved = resolve_inside(consumer_root, candidate)
        except (CheckError, OSError) as exc:
            raise _runtime_error(f"Runtime 쓰기 경로가 Consumer 밖이다: {candidate}: {exc}", exc)
        if _paths_overlap(resolved, core_root):
            raise RuntimeBoundaryError(
                f"Runtime 쓰기 경로는 소비 계약의 core_path와 겹칠 수 없다: {candidate}"
            )
        canonical_write_paths.append(resolved.relative_to(consumer_root).as_posix())

    if not canonical_write_paths:
        raise RuntimeBoundaryError("Runtime은 하나 이상의 쓰기 경로를 선언해야 한다")

    declared_protected = contract.get("protected_paths")
    if not isinstance(declared_protected, list):
        raise RuntimeBoundaryError("Consumer protected_paths 계약이 유효하지 않다")
    try:
        core_relative = core_root.relative_to(consumer_root).as_posix()
    except ValueError as exc:
        raise _runtime_error("소비 계약의 core_path가 Consumer 밖이다", exc)
    effective_protected = tuple(sorted({
        str(value) for value in [*declared_protected, *protected_paths, core_relative]
    }))
    canonical_protected: list[tuple[str, Path]] = []
    for candidate in effective_protected:
        try:
            canonical_protected.append(
                (candidate, resolve_inside(consumer_root, candidate))
            )
        except (CheckError, OSError) as exc:
            raise _runtime_error(f"보호 경로가 Consumer 밖이다: {candidate}: {exc}", exc)
    for relative in canonical_write_paths:
        write_path = resolve_inside(consumer_root, relative)
        for protected_relative, protected_path in canonical_protected:
            if _paths_overlap(write_path, protected_path):
                raise RuntimeBoundaryError(
                    "Runtime 쓰기 경로는 보호 경로와 겹칠 수 없다: "
                    f"{relative} <-> {protected_relative}"
                )

    baseline: HostConsumerBaseline | None = None
    if contract.get("consumer_role") == "host":
        if entry_observation is None:
            raise RuntimeBoundaryError(
                "Host Core 읽기 전용 사전 검사 실패: 계약 해석 전 상태를 "
                f"고정할 수 없다: {entry_observation_error or '관찰 기준선 없음'}"
            )
        try:
            baseline = capture_host_consumer_baseline(
                core_root,
                consumer_root,
                core_relative,
                require_clean=True,
                expected_observation=entry_observation,
            )
        except (CheckError, OSError) as exc:
            raise _runtime_error(f"Host Core 읽기 전용 사전 검사 실패: {exc}", exc)

    return ConsumerRuntimeBoundary(
        core_root=core_root,
        consumer_root=consumer_root,
        write_paths=tuple(canonical_write_paths),
        protected_paths=effective_protected,
        host_baseline=baseline,
    )


def require_consumer_runtime_boundary_unchanged(
    boundary: ConsumerRuntimeBoundary,
) -> None:
    """Host Runtime이 Core tree와 Git 의미 상태를 바꾸지 않았음을 확인한다."""
    if boundary.host_baseline is None:
        return
    unchanged, detail = host_consumer_baseline_status(boundary.host_baseline)
    if not unchanged:
        raise RuntimeBoundaryError(f"Host Core 사후 불변 검사 실패: {detail}")


def capture_static_discovery_baseline(core_root: Path) -> HostCoreBaseline:
    """역할 비의존 정적 discovery 전 Core tree·Git 기준선을 잡는다."""
    try:
        return capture_host_core_baseline(core_root.resolve(), require_clean=False)
    except (CheckError, OSError) as exc:
        raise _runtime_error(f"Core 정적 discovery 기준선을 증명할 수 없다: {exc}", exc)


def require_static_discovery_unchanged(
    core_root: Path, baseline: HostCoreBaseline
) -> None:
    """정적 discovery가 dirty 여부와 무관하게 Core를 바꾸지 않았음을 확인한다."""
    unchanged, detail = host_core_baseline_status(core_root.resolve(), baseline)
    if not unchanged:
        raise RuntimeBoundaryError(f"Core 정적 discovery 사후 불변 검사 실패: {detail}")
