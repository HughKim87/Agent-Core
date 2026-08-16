"""엄격한 공통 JSON record 외피와 소비 root 경로 안전 원시."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
from typing import Any
from uuid import UUID, uuid4


SCHEMA_VERSION = 1
REQUIRED_FIELDS = frozenset(
    {
        "id",
        "record_type",
        "schema_version",
        "created_at",
        "updated_at",
        "payload",
        "content_hash",
    }
)
RESERVED_SEGMENTS = frozenset({".git"})
RECORD_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class RecordValidationError(ValueError):
    """record bytes나 field가 common-record v1을 위반한다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DataPathError(ValueError):
    """경로가 소비 root·보호 경계 계약을 위반한다."""


class DuplicateRecordError(ValueError):
    """기존 주소에 다른 record identity를 쓰려 한다."""


def _canonical_body_bytes(record: Mapping[str, Any]) -> bytes:
    body = dict(record)
    body.pop("content_hash", None)
    try:
        rendered = json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RecordValidationError("not_json", "record에 JSON이 아닌 값이 있다") from exc
    return rendered.encode("utf-8")


def compute_content_hash(record: Mapping[str, Any]) -> str:
    """`content_hash`를 제외한 canonical JSON의 SHA-256을 계산한다."""

    return "sha256:" + hashlib.sha256(_canonical_body_bytes(record)).hexdigest()


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise RecordValidationError(
            "invalid_timestamp",
            f"{field}는 초 정밀도 UTC RFC 3339 timestamp여야 한다",
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise RecordValidationError("invalid_timestamp", f"{field}가 실제 시각이 아니다") from exc


def _validate_json_value(value: Any, location: str = "record") -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise RecordValidationError("nul_character", f"{location}에 NUL 문자가 있다")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecordValidationError("not_json", f"{location}에 비유한 숫자가 있다")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RecordValidationError("not_json", f"{location}에 문자열이 아닌 key가 있다")
            _validate_json_value(key, f"{location}.<key>")
            _validate_json_value(item, f"{location}.{key}")
        return
    raise RecordValidationError("not_json", f"{location}에 지원하지 않는 값이 있다")


def validate_record(record: Mapping[str, Any]) -> None:
    """메모리 record를 엄격한 common-record v1 계약으로 검증한다."""

    if not isinstance(record, Mapping):
        raise RecordValidationError("root_type", "record root는 JSON object여야 한다")
    if any(not isinstance(key, str) for key in record):
        raise RecordValidationError("not_json", "record field 이름은 문자열이어야 한다")
    fields = set(record)
    missing = REQUIRED_FIELDS - fields
    extra = fields - REQUIRED_FIELDS
    if missing:
        raise RecordValidationError("missing_field", f"필수 field가 없다: {sorted(missing)}")
    if extra:
        raise RecordValidationError("extra_field", f"허용되지 않은 field가 있다: {sorted(extra)}")

    record_id = record["id"]
    if not isinstance(record_id, str):
        raise RecordValidationError("invalid_id", "id는 소문자 canonical UUIDv4여야 한다")
    try:
        parsed_id = UUID(record_id)
    except (ValueError, AttributeError) as exc:
        raise RecordValidationError("invalid_id", "id는 소문자 canonical UUIDv4여야 한다") from exc
    if parsed_id.version != 4 or str(parsed_id) != record_id:
        raise RecordValidationError("invalid_id", "id는 소문자 canonical UUIDv4여야 한다")

    record_type = record["record_type"]
    if not isinstance(record_type, str) or RECORD_TYPE_PATTERN.fullmatch(record_type) is None:
        raise RecordValidationError("invalid_record_type", "record_type은 lower snake case여야 한다")

    version = record["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise RecordValidationError("unsupported_version", f"schema_version은 {SCHEMA_VERSION}이어야 한다")

    created = _parse_timestamp(record["created_at"], "created_at")
    updated = _parse_timestamp(record["updated_at"], "updated_at")
    if updated < created:
        raise RecordValidationError("timestamp_order", "updated_at은 created_at보다 이를 수 없다")

    if not isinstance(record["payload"], dict):
        raise RecordValidationError("payload_type", "payload는 JSON object여야 한다")
    _validate_json_value(dict(record))

    content_hash = record["content_hash"]
    if not isinstance(content_hash, str) or HASH_PATTERN.fullmatch(content_hash) is None:
        raise RecordValidationError("invalid_hash", "content_hash 형식이 유효하지 않다")
    expected = compute_content_hash(record)
    if not hmac.compare_digest(content_hash, expected):
        raise RecordValidationError("hash_mismatch", "content_hash가 canonical record body와 다르다")


def build_record(
    record_type: str,
    payload: Mapping[str, Any],
    *,
    record_id: str | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """새 common-record v1을 만들고 즉시 검증한다."""

    if not isinstance(payload, Mapping):
        raise RecordValidationError("payload_type", "payload는 JSON object여야 한다")
    now = timestamp or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timestamp는 timezone-aware여야 한다")
    rendered = now.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    record: dict[str, Any] = {
        "id": record_id or str(uuid4()),
        "record_type": record_type,
        "schema_version": SCHEMA_VERSION,
        "created_at": rendered,
        "updated_at": rendered,
        "payload": dict(payload),
    }
    record["content_hash"] = compute_content_hash(record)
    validate_record(record)
    return record


def encode_record(record: Mapping[str, Any]) -> bytes:
    """검증된 record를 마지막 LF 하나가 있는 결정론적 UTF-8 JSON으로 만든다."""

    validate_record(record)
    rendered = json.dumps(
        dict(record),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    return f"{rendered}\n".encode("utf-8")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecordValidationError("duplicate_key", f"중복 JSON key: {key}")
        result[key] = value
    return result


def decode_record(data: bytes) -> dict[str, Any]:
    """BOM 없는 strict UTF-8 JSON을 해석하고 중복 key와 record 계약을 검증한다."""

    if data.startswith(b"\xef\xbb\xbf"):
        raise RecordValidationError("utf8_bom", "UTF-8 BOM은 허용되지 않는다")
    if b"\x00" in data:
        raise RecordValidationError("nul_byte", "record bytes에 NUL이 있다")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RecordValidationError("invalid_utf8", "record가 strict UTF-8이 아니다") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                RecordValidationError("not_json", f"비유한 숫자는 허용되지 않는다: {value}")
            ),
        )
    except RecordValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise RecordValidationError("invalid_json", "record가 유효한 JSON이 아니다") from exc
    if not isinstance(value, dict):
        raise RecordValidationError("root_type", "record root는 JSON object여야 한다")
    validate_record(value)
    return value


def normalize_relative_path(value: Path | str, *, label: str = "path") -> Path:
    """두 경로 구분자를 해석하되 정규화되지 않은 상대경로는 거부한다."""

    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise DataPathError(f"{label}는 비어 있지 않은 상대경로여야 한다")
    windows_path = PureWindowsPath(raw)
    if Path(raw).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise DataPathError(f"{label}에 절대경로를 사용할 수 없다")
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DataPathError(f"{label}는 정규화된 상대경로여야 한다")
    if any(part.casefold() in RESERVED_SEGMENTS for part in parts):
        raise DataPathError(f"{label}가 예약된 저장소 경계를 지난다")
    return Path(*parts)


def _path_key(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _is_same_or_descendant(candidate: Path, parent: Path) -> bool:
    candidate_key = _path_key(candidate)
    parent_key = _path_key(parent)
    return len(candidate_key) >= len(parent_key) and candidate_key[: len(parent_key)] == parent_key


def paths_overlap(first: Path, second: Path) -> bool:
    """두 정규화 상대경로가 같거나 조상·자손 관계인지 반환한다."""

    return _is_same_or_descendant(first, second) or _is_same_or_descendant(second, first)


def normalize_protected_paths(values: Iterable[Path | str]) -> tuple[Path, ...]:
    normalized = {normalize_relative_path(value, label="protected path") for value in values}
    return tuple(sorted(normalized, key=lambda item: item.as_posix().casefold()))


def _reject_protected(candidate: Path, protected_paths: Iterable[Path]) -> None:
    if any(_is_same_or_descendant(candidate, protected) for protected in protected_paths):
        raise DataPathError("path가 선언된 보호 경계 안을 가리킨다")


def resolve_consumer_path(
    consumer_root: Path | str,
    relative_path: Path | str,
    *,
    protected_paths: Iterable[Path | str] = (),
) -> Path:
    """보호 경로를 먼저 차단하고 소비 root 안쪽의 경로만 반환한다."""

    try:
        root = Path(consumer_root).resolve(strict=True)
    except FileNotFoundError as exc:
        raise DataPathError("consumer root가 없다") from exc
    if not root.is_dir():
        raise DataPathError("consumer root는 디렉터리여야 한다")
    candidate = normalize_relative_path(relative_path)
    protected = normalize_protected_paths(protected_paths)
    _reject_protected(candidate, protected)

    target = (root / candidate).resolve(strict=False)
    try:
        resolved_relative = target.relative_to(root)
    except ValueError as exc:
        raise DataPathError("path가 consumer root 밖으로 나간다") from exc
    if resolved_relative == Path("."):
        raise DataPathError("path가 consumer root 자체를 가리킬 수 없다")
    resolved_normalized = normalize_relative_path(resolved_relative)
    _reject_protected(resolved_normalized, protected)
    return target
