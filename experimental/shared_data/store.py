"""명시적 소비 경계 안에서만 동작하는 원자적 record·JSONL 저장 기반."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
UTC = timezone.utc
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator
from uuid import UUID

from .record import (
    RECORD_TYPE_PATTERN,
    DataPathError,
    DuplicateRecordError,
    RecordValidationError,
    build_record,
    compute_content_hash,
    decode_record,
    encode_record,
    normalize_protected_paths,
    normalize_relative_path,
    paths_overlap,
    resolve_consumer_path,
    validate_record,
)


EMPTY_STREAM_HASH = "sha256:" + hashlib.sha256(b"").hexdigest()


class RecordIOError(Exception):
    """결정론적 record I/O 실패의 기반 타입."""

    kind = "record_io_error"
    recoverable = False


class InputContractError(RecordIOError):
    kind = "input_error"


class WriteNotEnabledError(InputContractError):
    kind = "write_not_enabled"


class StoreNotInitializedError(InputContractError):
    kind = "not_initialized"


class RecordNotFoundError(RecordIOError):
    kind = "not_found"


class ConflictError(RecordIOError):
    kind = "conflict"
    recoverable = True


class ExpectationMismatchError(ConflictError):
    kind = "expectation_mismatch"


class ConcurrentWriteError(ConflictError):
    kind = "concurrent_write"


def stream_content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _render_time(value: datetime | None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise InputContractError("timestamp는 timezone-aware여야 한다")
    return current.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validated_names(values: Iterable[str], label: str) -> frozenset[str]:
    normalized = frozenset(values)
    for value in normalized:
        if not isinstance(value, str) or RECORD_TYPE_PATTERN.fullmatch(value) is None:
            raise InputContractError(f"{label} 값은 lower snake case여야 한다")
    return normalized


def _require_approved(value: str, approved: frozenset[str], label: str) -> None:
    if not isinstance(value, str) or RECORD_TYPE_PATTERN.fullmatch(value) is None:
        raise InputContractError(f"{label}은 lower snake case여야 한다")
    if value not in approved:
        raise InputContractError(f"승인되지 않은 {label}: {value}")


def _compact_record_bytes(record: Mapping[str, Any]) -> bytes:
    validate_record(record)
    rendered = json.dumps(
        dict(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if "\n" in rendered or "\r" in rendered:
        raise RecordValidationError("jsonl_line", "JSONL record는 한 줄이어야 한다")
    return rendered.encode("utf-8") + b"\n"


def decode_stream(data: bytes, stream_name: str) -> list[dict[str, Any]]:
    """전체 JSONL stream을 검증하고 partial·blank·duplicate를 거부한다."""

    if not data:
        return []
    if not data.endswith(b"\n"):
        raise RecordValidationError("partial_jsonl", "JSONL stream은 LF로 끝나야 한다")
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(data.splitlines(), start=1):
        if not line:
            raise RecordValidationError("blank_jsonl_line", f"빈 JSONL 줄: {line_number}")
        record = decode_record(line)
        if record["record_type"] != stream_name:
            raise RecordValidationError(
                "stream_type_mismatch",
                f"{line_number}번 줄의 유형이 stream 이름과 다르다",
            )
        if record["id"] in seen_ids:
            raise RecordValidationError("duplicate_id", f"중복 event id: {line_number}번 줄")
        seen_ids.add(record["id"])
        records.append(record)
    return records


@contextmanager
def _exclusive_lock(target: Path) -> Iterator[None]:
    lock_path = target.parent / f".{target.name}.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ConcurrentWriteError(f"쓰기 lock이 이미 있다: {lock_path.name}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write(f"pid={os.getpid()}\n")
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _atomic_replace(target: Path, data: bytes, verify: Any) -> Any:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        verified = verify(temporary_path.read_bytes())
        os.replace(temporary_path, target)
        return verified
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


class RecordStore:
    """도메인 중립 record와 append-only event의 L7 내부 진입점."""

    def __init__(
        self,
        consumer_root: Path | str,
        *,
        storage_root: Path | str,
        protected_paths: Iterable[Path | str] = (),
        approved_record_types: Iterable[str] = (),
        approved_streams: Iterable[str] = (),
        write_enabled: bool = False,
    ) -> None:
        try:
            self.root = Path(consumer_root).resolve(strict=True)
        except FileNotFoundError as exc:
            raise InputContractError("consumer root가 없다") from exc
        if not self.root.is_dir():
            raise InputContractError("consumer root는 디렉터리여야 한다")
        if not isinstance(write_enabled, bool):
            raise InputContractError("write_enabled는 boolean이어야 한다")

        try:
            self.storage_root = normalize_relative_path(storage_root, label="storage root")
            self.protected_paths = normalize_protected_paths(protected_paths)
        except DataPathError as exc:
            raise InputContractError(str(exc)) from exc
        if any(paths_overlap(self.storage_root, protected) for protected in self.protected_paths):
            raise InputContractError("storage root가 보호 경로와 겹친다")
        try:
            resolve_consumer_path(
                self.root,
                self.storage_root,
                protected_paths=self.protected_paths,
            )
        except DataPathError as exc:
            raise InputContractError(str(exc)) from exc

        self.approved_record_types = _validated_names(approved_record_types, "record type")
        self.approved_streams = _validated_names(approved_streams, "stream")
        self.write_enabled = write_enabled

    def _require_writable(self) -> None:
        if not self.write_enabled:
            raise WriteNotEnabledError("쓰기는 기본 비활성이며 명시적으로 활성화해야 한다")

    def _resolve(self, relative_path: Path | str) -> Path:
        try:
            return resolve_consumer_path(
                self.root,
                relative_path,
                protected_paths=self.protected_paths,
            )
        except DataPathError as exc:
            raise InputContractError(str(exc)) from exc

    @property
    def records_directory(self) -> Path:
        return self._resolve(self.storage_root / "records")

    @property
    def events_directory(self) -> Path:
        return self._resolve(self.storage_root / "events")

    def initialize(self) -> dict[str, str]:
        self._require_writable()
        try:
            self.records_directory.mkdir(parents=True, exist_ok=True)
            self.events_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RecordIOError(f"데이터 디렉터리를 초기화할 수 없다: {exc}") from exc
        return {
            "records": (self.storage_root / "records").as_posix(),
            "events": (self.storage_root / "events").as_posix(),
        }

    def _require_initialized(self) -> None:
        if not self.records_directory.is_dir() or not self.events_directory.is_dir():
            raise StoreNotInitializedError("record 작업 전에 저장소 초기화가 필요하다")

    def _record_relative_path(self, record_id: str) -> Path:
        try:
            parsed = UUID(record_id)
        except (ValueError, AttributeError) as exc:
            raise InputContractError("record id는 소문자 canonical UUIDv4여야 한다") from exc
        if parsed.version != 4 or str(parsed) != record_id:
            raise InputContractError("record id는 소문자 canonical UUIDv4여야 한다")
        return self.storage_root / "records" / f"{record_id}.json"

    def _stream_relative_path(self, stream_name: str) -> Path:
        _require_approved(stream_name, self.approved_streams, "stream")
        return self.storage_root / "events" / f"{stream_name}.jsonl"

    def _require_approved_record(self, record: Mapping[str, Any]) -> None:
        if record["record_type"] not in self.approved_record_types:
            raise RecordValidationError(
                "unapproved_record_type",
                f"저장 record 유형이 승인되지 않았다: {record['record_type']}",
            )

    def _read_record(self, relative_path: Path) -> dict[str, Any]:
        target = self._resolve(relative_path)
        record = decode_record(target.read_bytes())
        if target.suffix != ".json" or target.stem != record["id"]:
            raise RecordValidationError("record_address", "record 파일명과 id가 다르다")
        return record

    def _write_record(
        self,
        relative_path: Path,
        record: Mapping[str, Any],
        *,
        overwrite: bool,
    ) -> Path:
        encoded = encode_record(record)
        target = self._resolve(relative_path)
        if target.parent != self.records_directory:
            raise InputContractError("record는 설정된 records 디렉터리만 사용할 수 있다")
        if target.suffix != ".json" or target.stem != record["id"]:
            raise DuplicateRecordError("record 파일명은 record id와 같아야 한다")
        if not target.parent.is_dir():
            raise StoreNotInitializedError("records 디렉터리가 초기화되지 않았다")

        if target.exists():
            existing = decode_record(target.read_bytes())
            if not overwrite:
                raise FileExistsError(f"record가 이미 있다: {relative_path.as_posix()}")
            if existing["id"] != record["id"]:
                raise DuplicateRecordError("다른 record id를 덮어쓸 수 없다")

        verified = _atomic_replace(target, encoded, decode_record)
        if verified != dict(record):
            raise RecordValidationError("write_verification", "임시 record 재검증 결과가 다르다")
        return target

    def create_record(
        self,
        record_type: str,
        payload: Mapping[str, Any],
        *,
        record_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        self._require_writable()
        self._require_initialized()
        _require_approved(record_type, self.approved_record_types, "record type")
        if not isinstance(payload, Mapping):
            raise InputContractError("payload는 JSON object여야 한다")
        record = build_record(record_type, payload, record_id=record_id, timestamp=timestamp)
        relative = self._record_relative_path(record["id"])
        target = self._resolve(relative)
        try:
            with _exclusive_lock(target):
                self._write_record(relative, record, overwrite=False)
                if self._read_record(relative) != record:
                    raise RecordIOError("생성 후 record 재검증에 실패했다")
        except (DuplicateRecordError, FileExistsError) as exc:
            raise ConflictError(str(exc)) from exc
        return record

    def get_record(self, record_id: str) -> dict[str, Any]:
        self._require_initialized()
        relative = self._record_relative_path(record_id)
        try:
            record = self._read_record(relative)
        except FileNotFoundError as exc:
            raise RecordNotFoundError(f"record를 찾을 수 없다: {record_id}") from exc
        self._require_approved_record(record)
        return record

    def list_records(self, record_type: str) -> list[dict[str, Any]]:
        self._require_initialized()
        _require_approved(record_type, self.approved_record_types, "record type")
        records: list[dict[str, Any]] = []
        for path in sorted(self.records_directory.glob("*.json"), key=lambda item: item.name):
            record = self._read_record(path.relative_to(self.root))
            self._require_approved_record(record)
            if record["record_type"] == record_type:
                records.append(record)
        return records

    def update_record(
        self,
        record_id: str,
        payload: Mapping[str, Any],
        *,
        expected_content_hash: str,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        self._require_writable()
        self._require_initialized()
        if not isinstance(payload, Mapping):
            raise InputContractError("payload는 JSON object여야 한다")
        relative = self._record_relative_path(record_id)
        target = self._resolve(relative)
        with _exclusive_lock(target):
            try:
                current = self._read_record(relative)
            except FileNotFoundError as exc:
                raise RecordNotFoundError(f"record를 찾을 수 없다: {record_id}") from exc
            self._require_approved_record(current)
            if current["content_hash"] != expected_content_hash:
                raise ExpectationMismatchError("현재 content_hash가 expected 값과 다르다")
            updated = dict(current)
            updated["payload"] = dict(payload)
            updated["updated_at"] = _render_time(timestamp)
            updated["content_hash"] = compute_content_hash(updated)
            validate_record(updated)
            self._write_record(relative, updated, overwrite=True)
            if self._read_record(relative) != updated:
                raise RecordIOError("갱신 후 record 재검증에 실패했다")
        return updated

    def append_event(
        self,
        stream_name: str,
        payload: Mapping[str, Any],
        *,
        expected_stream_hash: str | None = None,
        event_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        self._require_writable()
        self._require_initialized()
        _require_approved(stream_name, self.approved_streams, "stream")
        if not isinstance(payload, Mapping):
            raise InputContractError("payload는 JSON object여야 한다")
        relative = self._stream_relative_path(stream_name)
        target = self._resolve(relative)
        event = build_record(stream_name, payload, record_id=event_id, timestamp=timestamp)
        with _exclusive_lock(target):
            before = target.read_bytes() if target.exists() else b""
            existing = decode_stream(before, stream_name)
            before_hash = stream_content_hash(before)
            if expected_stream_hash is not None and expected_stream_hash != before_hash:
                raise ExpectationMismatchError("현재 stream hash가 expected 값과 다르다")
            if any(item["id"] == event["id"] for item in existing):
                raise ConflictError(f"중복 event id: {event['id']}")
            after = before + _compact_record_bytes(event)
            verified = _atomic_replace(target, after, lambda data: decode_stream(data, stream_name))
            if not verified or verified[-1] != event:
                raise RecordIOError("append 후 stream 재검증에 실패했다")
            verified_bytes = target.read_bytes()
            if decode_stream(verified_bytes, stream_name) != verified:
                raise RecordIOError("교체된 stream이 검증 snapshot과 다르다")
            result_hash = stream_content_hash(verified_bytes)
            result_count = len(verified)
        return {"event": event, "stream_hash": result_hash, "count": result_count}

    def list_events(self, stream_name: str) -> tuple[list[dict[str, Any]], str]:
        self._require_initialized()
        relative = self._stream_relative_path(stream_name)
        target = self._resolve(relative)
        data = target.read_bytes() if target.exists() else b""
        return decode_stream(data, stream_name), stream_content_hash(data)
