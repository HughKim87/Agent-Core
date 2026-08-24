"""출처·단일 지식 주장·승인된 결정의 L7 내부 의미 계약."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
UTC = timezone.utc
import hashlib
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from .record import (
    DataPathError,
    normalize_relative_path,
    paths_overlap,
    resolve_consumer_path,
)
from .store import InputContractError, RecordIOError, RecordStore


KNOWLEDGE_RECORD_TYPES = frozenset({"source", "knowledge", "decision"})
SOURCE_KINDS = frozenset(
    {"local_document", "local_data", "command_result", "web_page", "user_statement"}
)
SOURCE_VERIFICATION_STATUSES = frozenset({"observed", "verified", "unavailable"})
SOURCE_EVIDENCE_ROLES = frozenset({"primary", "supporting", "contextual"})
SOURCE_FIELDS = frozenset(
    {
        "source_kind",
        "locator",
        "observed_at",
        "verification_status",
        "evidence_role",
        "version_or_hash",
    }
)
KNOWLEDGE_CLASSES = frozenset({"fact", "inference", "procedure", "constraint"})
KNOWLEDGE_VERIFICATION_STATUSES = frozenset({"candidate", "verified"})
KNOWLEDGE_FIELDS = frozenset(
    {"statement", "classification", "scope", "source_ids", "verification_status", "verified_by"}
)
DECISION_APPROVAL_KINDS = frozenset({"user", "standing_policy", "agent_in_scope"})
DECISION_FIELDS = frozenset(
    {
        "problem",
        "requirements",
        "options",
        "selected_option",
        "rationale",
        "impacts",
        "source_ids",
        "requires_user_approval",
        "approval_kind",
        "approved_by",
        "decided_at",
    }
)
DECISION_OPTION_FIELDS = frozenset({"label", "impact"})
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class KnowledgeRecordError(RecordIOError):
    """지식 payload 또는 참조 무결성이 유효하지 않다."""

    kind = "knowledge_validation"


class SourceIntegrityError(KnowledgeRecordError):
    """관찰한 로컬 source bytes와 현재 bytes가 다르다."""

    kind = "source_integrity"


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise KnowledgeRecordError(f"{field}는 NUL 없는 비어 있지 않은 문자열이어야 한다")
    return value


def _render_time(value: datetime | None) -> tuple[datetime, str]:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise InputContractError("timestamp는 timezone-aware여야 한다")
    normalized = current.astimezone(UTC).replace(microsecond=0)
    return normalized, normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise KnowledgeRecordError(f"{field}는 초 정밀도 UTC timestamp여야 한다")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise KnowledgeRecordError(f"{field}가 실제 시각이 아니다") from exc


def _uuid_list(value: Any, field: str, *, require_nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (require_nonempty and not value):
        raise KnowledgeRecordError(f"{field}는 canonical UUIDv4 문자열 목록이어야 한다")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise KnowledgeRecordError(f"{field}에는 문자열만 사용할 수 있다")
        try:
            parsed = UUID(item)
        except (ValueError, AttributeError, TypeError) as exc:
            raise KnowledgeRecordError(f"{field}는 canonical UUIDv4 문자열 목록이어야 한다") from exc
        if parsed.version != 4 or str(parsed) != item or item in normalized:
            raise KnowledgeRecordError(f"{field}에는 중복 없는 canonical UUIDv4만 사용할 수 있다")
        normalized.append(item)
    return normalized


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise KnowledgeRecordError(f"{field}는 비어 있지 않은 문자열 목록이어야 한다")
    normalized = [_non_empty(item, field) for item in value]
    if len(normalized) != len(set(normalized)):
        raise KnowledgeRecordError(f"{field}에는 중복을 사용할 수 없다")
    return normalized


def validate_source_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != SOURCE_FIELDS:
        raise KnowledgeRecordError(f"source payload field가 정확하지 않다: {sorted(SOURCE_FIELDS)}")
    source_kind = payload["source_kind"]
    status = payload["verification_status"]
    role = payload["evidence_role"]
    if source_kind not in SOURCE_KINDS:
        raise KnowledgeRecordError(f"지원하지 않는 source_kind: {source_kind}")
    if status not in SOURCE_VERIFICATION_STATUSES:
        raise KnowledgeRecordError(f"지원하지 않는 verification_status: {status}")
    if role not in SOURCE_EVIDENCE_ROLES:
        raise KnowledgeRecordError(f"지원하지 않는 evidence_role: {role}")
    locator = _non_empty(payload["locator"], "locator")
    observed_at = payload["observed_at"]
    _parse_time(observed_at, "observed_at")
    version = payload["version_or_hash"]
    if version is not None:
        version = _non_empty(version, "version_or_hash")
    if source_kind in {"local_document", "local_data"}:
        if status != "verified" or not isinstance(version, str) or SHA256_PATTERN.fullmatch(version) is None:
            raise KnowledgeRecordError("로컬 source에는 verified 상태와 SHA-256 hash가 필요하다")
    if source_kind == "web_page" and not locator.startswith(("https://", "http://")):
        raise KnowledgeRecordError("web_page locator는 http 또는 https여야 한다")
    if source_kind == "user_statement" and not locator.startswith("request://"):
        raise KnowledgeRecordError("user_statement locator는 승인된 request:// 참조여야 한다")
    return {
        "source_kind": source_kind,
        "locator": locator,
        "observed_at": observed_at,
        "verification_status": status,
        "evidence_role": role,
        "version_or_hash": version,
    }


def validate_knowledge_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != KNOWLEDGE_FIELDS:
        raise KnowledgeRecordError(f"knowledge payload field가 정확하지 않다: {sorted(KNOWLEDGE_FIELDS)}")
    statement = _non_empty(payload["statement"], "statement")
    if "\n" in statement or "\r" in statement or len(statement) > 500:
        raise KnowledgeRecordError("statement는 줄바꿈 없는 500자 이하 한 문장이어야 한다")
    classification = payload["classification"]
    if classification not in KNOWLEDGE_CLASSES:
        raise KnowledgeRecordError(f"지원하지 않는 classification: {classification}")
    scope = _non_empty(payload["scope"], "scope")
    source_ids = _uuid_list(payload["source_ids"], "source_ids")
    status = payload["verification_status"]
    if status not in KNOWLEDGE_VERIFICATION_STATUSES:
        raise KnowledgeRecordError(f"지원하지 않는 verification_status: {status}")
    verifier = payload["verified_by"]
    if status == "verified":
        verifier = _non_empty(verifier, "verified_by")
    elif verifier is not None:
        raise KnowledgeRecordError("candidate knowledge에는 verified_by를 기록할 수 없다")
    return {
        "statement": statement,
        "classification": classification,
        "scope": scope,
        "source_ids": source_ids,
        "verification_status": status,
        "verified_by": verifier,
    }


def validate_decision_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != DECISION_FIELDS:
        raise KnowledgeRecordError(f"decision payload field가 정확하지 않다: {sorted(DECISION_FIELDS)}")
    problem = _non_empty(payload["problem"], "problem")
    requirements = _string_list(payload["requirements"], "requirements")
    raw_options = payload["options"]
    if not isinstance(raw_options, list) or len(raw_options) < 2:
        raise KnowledgeRecordError("options에는 최소 두 선택지가 필요하다")
    options: list[dict[str, str]] = []
    labels: list[str] = []
    for option in raw_options:
        if not isinstance(option, Mapping) or set(option) != DECISION_OPTION_FIELDS:
            raise KnowledgeRecordError("각 option은 label과 impact만 가져야 한다")
        label = _non_empty(option["label"], "option.label")
        impact = _non_empty(option["impact"], "option.impact")
        if label in labels:
            raise KnowledgeRecordError("option label에는 중복을 사용할 수 없다")
        labels.append(label)
        options.append({"label": label, "impact": impact})
    selected = _non_empty(payload["selected_option"], "selected_option")
    if selected not in labels:
        raise KnowledgeRecordError("selected_option은 검토한 option label 중 하나여야 한다")
    rationale = _non_empty(payload["rationale"], "rationale")
    impacts = _string_list(payload["impacts"], "impacts")
    source_ids = _uuid_list(payload["source_ids"], "source_ids")
    requires_user = payload["requires_user_approval"]
    if not isinstance(requires_user, bool):
        raise KnowledgeRecordError("requires_user_approval은 boolean이어야 한다")
    approval_kind = payload["approval_kind"]
    if approval_kind not in DECISION_APPROVAL_KINDS:
        raise KnowledgeRecordError(f"지원하지 않는 approval_kind: {approval_kind}")
    if requires_user and approval_kind not in {"user", "standing_policy"}:
        raise KnowledgeRecordError("사용자 승인 필요 결정은 user 또는 standing_policy 승인이 필요하다")
    approved_by = _non_empty(payload["approved_by"], "approved_by")
    decided_at = payload["decided_at"]
    _parse_time(decided_at, "decided_at")
    return {
        "problem": problem,
        "requirements": requirements,
        "options": options,
        "selected_option": selected,
        "rationale": rationale,
        "impacts": impacts,
        "source_ids": source_ids,
        "requires_user_approval": requires_user,
        "approval_kind": approval_kind,
        "approved_by": approved_by,
        "decided_at": decided_at,
    }


class KnowledgeService:
    """호출자가 구성한 RecordStore 위에서 지식 의미와 참조만 소유한다."""

    def __init__(self, store: RecordStore) -> None:
        if not isinstance(store, RecordStore):
            raise InputContractError("KnowledgeService에는 RecordStore가 필요하다")
        missing = KNOWLEDGE_RECORD_TYPES - store.approved_record_types
        if missing:
            raise InputContractError(f"지식 store에 record type이 부족하다: {sorted(missing)}")
        self.store = store

    def _local_target(self, locator: str) -> Path:
        try:
            relative = normalize_relative_path(locator, label="source locator")
            if paths_overlap(relative, self.store.storage_root):
                raise DataPathError("source locator가 Runtime storage와 겹친다")
            return resolve_consumer_path(
                self.store.root,
                relative,
                protected_paths=self.store.protected_paths,
            )
        except DataPathError as exc:
            raise KnowledgeRecordError(str(exc)) from exc

    def _file_hash(self, target: Path) -> str:
        try:
            data = target.read_bytes()
        except OSError as exc:
            raise SourceIntegrityError("로컬 source bytes를 읽을 수 없다") from exc
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def create_source(
        self,
        *,
        source_kind: str,
        locator: str,
        evidence_role: str,
        verification_status: str | None = None,
        version_or_hash: str | None = None,
        record_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_time, rendered_time = _render_time(timestamp)
        locator = _non_empty(locator, "locator")
        if source_kind in {"local_document", "local_data"}:
            target = self._local_target(locator)
            if not target.is_file():
                raise KnowledgeRecordError("로컬 source 파일이 없다")
            actual_hash = self._file_hash(target)
            if version_or_hash is not None and version_or_hash != actual_hash:
                raise SourceIntegrityError("제공한 source hash가 현재 bytes와 다르다")
            version_or_hash = actual_hash
            verification_status = "verified"
        else:
            verification_status = verification_status or "observed"
        payload = validate_source_payload(
            {
                "source_kind": source_kind,
                "locator": locator,
                "observed_at": rendered_time,
                "verification_status": verification_status,
                "evidence_role": evidence_role,
                "version_or_hash": version_or_hash,
            }
        )
        return self.store.create_record("source", payload, record_id=record_id, timestamp=normalized_time)

    def get_source(self, record_id: str, *, verify_local: bool = False) -> dict[str, Any]:
        record = self.store.get_record(record_id)
        if record["record_type"] != "source":
            raise KnowledgeRecordError("요청한 record가 source가 아니다")
        payload = validate_source_payload(record["payload"])
        if verify_local and payload["source_kind"] in {"local_document", "local_data"}:
            try:
                target = self._local_target(payload["locator"])
            except KnowledgeRecordError as exc:
                raise SourceIntegrityError("로컬 source 경계가 현재 소비 계약과 다르다") from exc
            if not target.is_file() or self._file_hash(target) != payload["version_or_hash"]:
                raise SourceIntegrityError("로컬 source bytes가 변경됐거나 사라졌다")
        return record

    def list_sources(self, *, verify_local: bool = False) -> list[dict[str, Any]]:
        return [
            self.get_source(record["id"], verify_local=verify_local)
            for record in self.store.list_records("source")
        ]

    def verify_source(self, record_id: str) -> dict[str, Any]:
        record = self.get_source(record_id, verify_local=True)
        payload = record["payload"]
        is_local = payload["source_kind"] in {"local_document", "local_data"}
        return {
            "record_id": record_id,
            "verification_status": payload["verification_status"],
            "version_or_hash": payload["version_or_hash"],
            "integrity": "match" if is_local else "not_applicable",
        }

    def _validated_sources(self, source_ids: list[str], *, verify_local: bool) -> list[dict[str, Any]]:
        sources = [self.get_source(source_id, verify_local=verify_local) for source_id in source_ids]
        if any(source["payload"]["verification_status"] == "unavailable" for source in sources):
            raise KnowledgeRecordError("unavailable source는 지식 근거로 사용할 수 없다")
        return sources

    def create_knowledge(
        self,
        *,
        statement: str,
        classification: str,
        scope: str,
        source_ids: list[str],
        verification_status: str,
        verified_by: str | None = None,
        record_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        payload = validate_knowledge_payload(
            {
                "statement": statement,
                "classification": classification,
                "scope": scope,
                "source_ids": source_ids,
                "verification_status": verification_status,
                "verified_by": verified_by,
            }
        )
        self._validated_sources(payload["source_ids"], verify_local=True)
        return self.store.create_record("knowledge", payload, record_id=record_id, timestamp=timestamp)

    def get_knowledge(self, record_id: str) -> dict[str, Any]:
        record = self.store.get_record(record_id)
        if record["record_type"] != "knowledge":
            raise KnowledgeRecordError("요청한 record가 knowledge가 아니다")
        payload = validate_knowledge_payload(record["payload"])
        self._validated_sources(payload["source_ids"], verify_local=False)
        return record

    def list_knowledge(self) -> list[dict[str, Any]]:
        return [self.get_knowledge(record["id"]) for record in self.store.list_records("knowledge")]

    def create_decision(
        self,
        payload: Mapping[str, Any],
        *,
        record_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = validate_decision_payload(payload)
        self._validated_sources(normalized["source_ids"], verify_local=True)
        normalized_time, _ = _render_time(timestamp)
        if _parse_time(normalized["decided_at"], "decided_at") > normalized_time:
            raise KnowledgeRecordError("decided_at은 record 생성 시각보다 미래일 수 없다")
        return self.store.create_record(
            "decision", normalized, record_id=record_id, timestamp=normalized_time
        )

    def get_decision(self, record_id: str) -> dict[str, Any]:
        record = self.store.get_record(record_id)
        if record["record_type"] != "decision":
            raise KnowledgeRecordError("요청한 record가 decision이 아니다")
        payload = validate_decision_payload(record["payload"])
        self._validated_sources(payload["source_ids"], verify_local=False)
        return record

    def list_decisions(self) -> list[dict[str, Any]]:
        return [self.get_decision(record["id"]) for record in self.store.list_records("decision")]
