"""단계 설계의 정본을 복제하지 않는 실행 등급·fingerprint 포인터."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .record import DataPathError, normalize_relative_path, paths_overlap, resolve_consumer_path
from .store import InputContractError, RecordStore


EXECUTION_TIERS = frozenset({"quick", "standard", "controlled"})
EXECUTION_FIELDS = frozenset({"tier", "phase_id", "design_ref", "design_fingerprint"})
DESIGN_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_POINTER_FIELDS = ("phase_id", "design_ref", "design_fingerprint")


class DesignContractError(InputContractError):
    kind = "design_contract_error"


class DesignRequiredError(DesignContractError):
    kind = "design_required"


class DesignInvalidatedError(DesignContractError):
    kind = "design_invalidated"


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DesignContractError(f"{field}는 NUL 없는 비어 있지 않은 문자열이어야 한다")
    if value != value.strip():
        raise DesignContractError(f"{field} 앞뒤에는 공백을 둘 수 없다")
    return value


def _nullable(value: Any, field: str) -> str | None:
    return None if value is None else _non_empty(value, field)


def normalize_execution(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or "tier" not in value or set(value) - EXECUTION_FIELDS:
        raise DesignContractError(f"execution은 tier와 다음 field만 가져야 한다: {sorted(EXECUTION_FIELDS)}")
    tier = _non_empty(value["tier"], "execution.tier")
    if tier not in EXECUTION_TIERS:
        raise DesignContractError(f"지원하지 않는 execution tier: {tier}")
    normalized = {
        "tier": tier,
        "phase_id": _nullable(value.get("phase_id"), "execution.phase_id"),
        "design_ref": _nullable(value.get("design_ref"), "execution.design_ref"),
        "design_fingerprint": _nullable(
            value.get("design_fingerprint"), "execution.design_fingerprint"
        ),
    }
    fingerprint = normalized["design_fingerprint"]
    if fingerprint is not None and DESIGN_HASH_PATTERN.fullmatch(fingerprint) is None:
        raise DesignContractError("execution.design_fingerprint는 sha256:<64 lowercase hex>여야 한다")
    pointers = [normalized[field] for field in _POINTER_FIELDS]
    if tier in {"quick", "standard"} and any(pointers):
        raise DesignContractError(f"{tier} execution은 영구 단계 설계 포인터를 가질 수 없다")
    if tier == "controlled" and any(item is None for item in pointers):
        raise DesignRequiredError(
            "controlled execution에는 phase_id, design_ref, design_fingerprint가 모두 필요하다"
        )
    return normalized


def request_execution(request: Mapping[str, Any]) -> dict[str, Any] | None:
    value = request.get("execution")
    return None if value is None else normalize_execution(value)


def compute_design_fingerprint(
    source: Mapping[str, Any] | bytes | str | Path,
    *,
    consumer_root: Path | str | None = None,
    protected_paths: Iterable[Path | str] = (),
    storage_root: Path | str | None = None,
) -> str:
    """JSON·bytes 또는 명시한 소비 root 상대 파일 bytes의 SHA-256을 계산한다."""

    if isinstance(source, Mapping):
        try:
            data = json.dumps(
                dict(source),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise DesignContractError("설계 object가 유효한 JSON이 아니다") from exc
    elif isinstance(source, bytes):
        data = source
    else:
        if consumer_root is None:
            raise DesignContractError("설계 경로를 hash하려면 consumer_root가 필요하다")
        try:
            relative = normalize_relative_path(source, label="design ref")
            if storage_root is not None and paths_overlap(
                relative, normalize_relative_path(storage_root, label="storage root")
            ):
                raise DataPathError("design ref가 Runtime storage와 겹친다")
            target = resolve_consumer_path(
                consumer_root, relative, protected_paths=protected_paths
            )
        except DataPathError as exc:
            raise DesignContractError(str(exc)) from exc
        if not target.is_file():
            raise DesignRequiredError(f"단계 설계 문서가 없다: {relative.as_posix()}")
        try:
            data = target.read_bytes()
        except OSError as exc:
            raise DesignRequiredError(f"단계 설계 문서를 읽을 수 없다: {relative.as_posix()}") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_execution_contract(
    store: RecordStore,
    execution: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """controlled 단계에서 현재 설계 bytes가 검토한 revision과 같은지 확인한다."""

    if execution is None:
        return None
    if not isinstance(store, RecordStore):
        raise DesignContractError("execution 검증에는 RecordStore가 필요하다")
    normalized = normalize_execution(execution)
    if normalized["tier"] != "controlled":
        return normalized
    actual = compute_design_fingerprint(
        normalized["design_ref"],
        consumer_root=store.root,
        protected_paths=store.protected_paths,
        storage_root=store.storage_root,
    )
    if actual != normalized["design_fingerprint"]:
        raise DesignInvalidatedError(
            "단계 설계 revision이 바뀌어 변경 검토가 필요하다. 승인된 결정이 같으면 "
            "work.refresh_design으로 검토 근거와 새 fingerprint를 기록하고, "
            "목표·권한·성공 조건이 바뀌면 작업 계약을 다시 확정한다"
        )
    return normalized


def compare_request_contract(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    fields = (
        "desired_outcome",
        "authorized_actions",
        "excluded_scope",
        "input_refs",
        "protection_boundaries",
        "required_decisions",
        "verification_levels",
    )
    changed = [field for field in fields if previous.get(field) != current.get(field)]
    previous_execution = request_execution(previous)
    current_execution = request_execution(current)
    revision_only = (
        previous_execution is not None and current_execution is not None
        and previous_execution["tier"] == current_execution["tier"] == "controlled"
        and all(previous_execution[key] == current_execution[key] for key in ("phase_id", "design_ref"))
        and previous_execution["design_fingerprint"] != current_execution["design_fingerprint"]
    )
    invalidated = bool(changed) or (previous_execution != current_execution and not revision_only)
    if previous_execution != current_execution:
        changed.append("execution")
    return {
        "invalidated": invalidated,
        "reapproval_required": invalidated,
        "design_review_required": revision_only,
        "changed_fields": changed,
        "previous_execution": previous_execution,
        "current_execution": current_execution,
    }
