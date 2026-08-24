"""작업 요청·event 정본과 재생 가능한 bounded 현재 snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any
from uuid import UUID, uuid4

from .execution import normalize_execution, validate_execution_contract
from .record import RecordValidationError
from .store import (
    ExpectationMismatchError,
    InputContractError,
    RecordIOError,
    RecordNotFoundError,
    RecordStore,
)


WORK_RECORD_TYPES = frozenset({"work_state"})
WORK_STREAMS = frozenset({"work_events"})
WORK_STATUSES = frozenset({"requested", "in_progress", "completed", "failed", "blocked"})
EVENT_OUTCOMES = frozenset({"success", "failure", "blocked", "rejected"})
EXPECTED_OUTCOME_BY_STATUS = {
    "requested": "success",
    "in_progress": "success",
    "completed": "success",
    "failed": "failure",
    "blocked": "blocked",
}
ALLOWED_TRANSITIONS = {
    "requested": frozenset({"in_progress", "failed", "blocked"}),
    "in_progress": frozenset({"in_progress", "completed", "failed", "blocked"}),
    "failed": frozenset({"in_progress", "blocked"}),
    "blocked": frozenset({"in_progress", "failed"}),
    "completed": frozenset(),
}
REQUEST_FIELDS = frozenset(
    {
        "desired_outcome",
        "authorized_actions",
        "excluded_scope",
        "input_refs",
        "protection_boundaries",
        "required_decisions",
        "verification_levels",
    }
)
OPTIONAL_REQUEST_FIELDS = frozenset({"execution"})
EVENT_FIELDS = frozenset(
    {
        "work_id",
        "actor",
        "action",
        "outcome",
        "from_status",
        "to_status",
        "request",
        "completed_items",
        "blockers",
        "next_action",
        "related_record_ids",
        "evidence_refs",
    }
)
STATE_FIELDS = frozenset(
    {
        "work_id",
        "request",
        "status",
        "completed_items",
        "blockers",
        "next_action",
        "related_record_ids",
        "evidence_refs",
        "last_event_id",
    }
)
WORK_EVENT_FIELDS = EVENT_FIELDS
WORK_STATE_FIELDS = STATE_FIELDS


class WorkStateError(InputContractError):
    kind = "work_state_error"


class InvalidWorkTransition(WorkStateError):
    kind = "invalid_work_transition"


class WorkProjectionPending(RecordIOError):
    kind = "work_projection_pending"
    recoverable = True


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise WorkStateError(f"{field}는 NUL 없는 비어 있지 않은 문자열이어야 한다")
    if value != value.strip():
        raise WorkStateError(f"{field} 앞뒤에는 공백을 둘 수 없다")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise WorkStateError(f"{field}는 문자열 목록이어야 한다")
    result = [_non_empty(item, field) for item in value]
    if len(result) != len(set(result)):
        raise WorkStateError(f"{field}에는 중복을 둘 수 없다")
    return result


def _string_sequence(value: Any, field: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorkStateError(f"{field}는 문자열 sequence여야 한다")
    return _string_list(list(value), field)


def _work_id(value: Any, field: str = "work_id") -> str:
    rendered = _non_empty(value, field)
    try:
        parsed = UUID(rendered)
    except (ValueError, AttributeError, TypeError) as exc:
        raise WorkStateError(f"{field}는 소문자 canonical UUIDv4여야 한다") from exc
    if parsed.version != 4 or str(parsed) != rendered:
        raise WorkStateError(f"{field}는 소문자 canonical UUIDv4여야 한다")
    return rendered


def validate_work_request(request: Mapping[str, Any]) -> dict[str, Any]:
    fields = set(request) if isinstance(request, Mapping) else set()
    if (
        not isinstance(request, Mapping)
        or not REQUEST_FIELDS.issubset(fields)
        or fields - (REQUEST_FIELDS | OPTIONAL_REQUEST_FIELDS)
    ):
        raise WorkStateError(
            f"work request에는 필수 field {sorted(REQUEST_FIELDS)}와 execution만 사용할 수 있다"
        )
    normalized: dict[str, Any] = {
        "desired_outcome": _non_empty(request["desired_outcome"], "desired_outcome")
    }
    for field in sorted(REQUEST_FIELDS - {"desired_outcome"}):
        normalized[field] = _string_list(request[field], field)
    if "execution" in request:
        normalized["execution"] = normalize_execution(request["execution"])
    return normalized


def _event_payload(
    *,
    work_id: str,
    actor: str,
    action: str,
    outcome: str,
    from_status: str | None,
    to_status: str | None,
    request: Mapping[str, Any] | None = None,
    completed_items: Sequence[str] = (),
    blockers: Sequence[str] = (),
    next_action: str | None = None,
    related_record_ids: Sequence[str] = (),
    evidence_refs: Sequence[str] = (),
) -> dict[str, Any]:
    identifier = _work_id(work_id)
    actor = _non_empty(actor, "actor")
    action = _non_empty(action, "action")
    if outcome not in EVENT_OUTCOMES:
        raise WorkStateError(f"지원하지 않는 event outcome: {outcome}")
    if from_status is not None and from_status not in WORK_STATUSES:
        raise WorkStateError("from_status가 유효하지 않다")
    if to_status is not None and to_status not in WORK_STATUSES:
        raise WorkStateError("to_status가 유효하지 않다")
    if next_action is not None:
        next_action = _non_empty(next_action, "next_action")
    return {
        "work_id": identifier,
        "actor": actor,
        "action": action,
        "outcome": outcome,
        "from_status": from_status,
        "to_status": to_status,
        "request": None if request is None else validate_work_request(request),
        "completed_items": _string_sequence(completed_items, "completed_items"),
        "blockers": _string_sequence(blockers, "blockers"),
        "next_action": next_action,
        "related_record_ids": _string_sequence(related_record_ids, "related_record_ids"),
        "evidence_refs": _string_sequence(evidence_refs, "evidence_refs"),
    }


def validate_work_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != EVENT_FIELDS:
        raise WorkStateError(f"work event field가 정확하지 않다: {sorted(EVENT_FIELDS)}")
    return _event_payload(
        work_id=payload["work_id"],
        actor=payload["actor"],
        action=payload["action"],
        outcome=payload["outcome"],
        from_status=payload["from_status"],
        to_status=payload["to_status"],
        request=payload["request"],
        completed_items=payload["completed_items"],
        blockers=payload["blockers"],
        next_action=payload["next_action"],
        related_record_ids=payload["related_record_ids"],
        evidence_refs=payload["evidence_refs"],
    )


def replay_work_events(events: Sequence[Mapping[str, Any]], work_id: str) -> dict[str, Any]:
    identifier = _work_id(work_id)
    matching = [event for event in events if event.get("payload", {}).get("work_id") == identifier]
    if not matching:
        raise RecordNotFoundError(f"work event가 없다: {identifier}")
    first = matching[0]
    payload = validate_work_event_payload(first["payload"])
    if (
        payload["action"] != "requested"
        or payload["from_status"] is not None
        or payload["to_status"] != "requested"
        or payload["outcome"] != "success"
        or payload["request"] is None
        or payload["next_action"] is None
    ):
        raise WorkStateError("첫 event는 request와 next_action을 가진 성공 requested여야 한다")
    state: dict[str, Any] = {
        "work_id": identifier,
        "request": payload["request"],
        "status": "requested",
        "completed_items": [],
        "blockers": [],
        "next_action": payload["next_action"],
        "related_record_ids": [],
        "evidence_refs": [],
        "last_event_id": first["id"],
    }
    previous_time = first["created_at"]
    for event in matching[1:]:
        if event["created_at"] < previous_time:
            raise WorkStateError("work event 시각 순서가 역행한다")
        previous_time = event["created_at"]
        item = validate_work_event_payload(event["payload"])
        if item["request"] is not None:
            raise WorkStateError("request는 첫 event 뒤에 바꿀 수 없다")
        if item["from_status"] != state["status"]:
            raise WorkStateError("event from_status가 replay 상태와 다르다")
        target = item["to_status"]
        if item["outcome"] == "rejected":
            if target is not None:
                raise WorkStateError("rejected event는 상태를 바꿀 수 없다")
            state["last_event_id"] = event["id"]
            continue
        if target not in ALLOWED_TRANSITIONS[state["status"]]:
            raise WorkStateError(f"허용되지 않은 전이: {state['status']} -> {target}")
        if item["outcome"] != EXPECTED_OUTCOME_BY_STATUS[target]:
            raise WorkStateError("outcome이 목표 상태와 다르다")
        state["status"] = target
        for field in ("completed_items", "related_record_ids", "evidence_refs"):
            for value in item[field]:
                if value not in state[field]:
                    state[field].append(value)
        state["blockers"] = item["blockers"]
        state["next_action"] = item["next_action"]
        state["last_event_id"] = event["id"]
    if state["status"] == "blocked" and not state["blockers"]:
        raise WorkStateError("blocked work에는 blocker가 필요하다")
    if state["status"] == "completed" and state["next_action"] is not None:
        raise WorkStateError("completed work에는 next_action이 없어야 한다")
    return state


class WorkStateService:
    """호출자가 구성한 RecordStore 위에서 work event와 projection만 소유한다."""

    def __init__(self, store: RecordStore) -> None:
        if not isinstance(store, RecordStore):
            raise WorkStateError("WorkStateService에는 RecordStore가 필요하다")
        missing_types = WORK_RECORD_TYPES - store.approved_record_types
        missing_streams = WORK_STREAMS - store.approved_streams
        if missing_types or missing_streams:
            raise WorkStateError(
                f"work store allowlist가 부족하다: types={sorted(missing_types)}, streams={sorted(missing_streams)}"
            )
        self.store = store

    def _events(self) -> tuple[list[dict[str, Any]], str]:
        return self.store.list_events("work_events")

    def create_work(
        self,
        request: Mapping[str, Any],
        *,
        actor: str,
        next_action: str,
        work_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = validate_work_request(request)
        if "execution" in normalized:
            normalized["execution"] = validate_execution_contract(
                self.store, normalized["execution"]
            )
        identifier = _work_id(work_id or str(uuid4()))
        events, stream_hash = self._events()
        if any(event["payload"].get("work_id") == identifier for event in events):
            raise ExpectationMismatchError(f"work가 이미 있다: {identifier}")
        event = self.store.append_event(
            "work_events",
            _event_payload(
                work_id=identifier,
                actor=actor,
                action="requested",
                outcome="success",
                from_status=None,
                to_status="requested",
                request=normalized,
                next_action=next_action,
            ),
            expected_stream_hash=stream_hash,
            timestamp=timestamp,
        )
        try:
            return self.rebuild_snapshot(identifier, expected_last_event_id=event["event"]["id"])
        except Exception as exc:
            raise WorkProjectionPending("request event는 저장됐지만 work snapshot 재구축이 남았다") from exc

    def get_state(self, work_id: str) -> dict[str, Any]:
        identifier = _work_id(work_id)
        current = self.store.get_record(identifier)
        if current["record_type"] != "work_state":
            raise WorkStateError("work_id가 work_state record를 가리키지 않는다")
        events, _ = self._events()
        authoritative = replay_work_events(events, identifier)
        if current["payload"] != authoritative:
            raise WorkProjectionPending("work snapshot이 event 정본보다 뒤처졌다")
        return current

    def list_states(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in WORK_STATUSES:
            raise WorkStateError(f"지원하지 않는 work status: {status}")
        events, _ = self._events()
        event_ids = {
            event["payload"]["work_id"]
            for event in events
            if event["payload"].get("action") == "requested"
        }
        records = self.store.list_records("work_state")
        by_id = {record["id"]: record for record in records}
        if set(by_id) != event_ids:
            raise WorkProjectionPending("work event와 snapshot 대상 목록이 다르다")
        result = [self.get_state(identifier) for identifier in sorted(event_ids)]
        return [item for item in result if status is None or item["payload"]["status"] == status]

    def transition(
        self,
        work_id: str,
        *,
        expected_state_hash: str,
        actor: str,
        action: str,
        outcome: str,
        to_status: str | None,
        completed_items: Sequence[str] = (),
        blockers: Sequence[str] = (),
        next_action: str | None = None,
        related_record_ids: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        current = self.get_state(work_id)
        if current["content_hash"] != expected_state_hash:
            raise ExpectationMismatchError("현재 work state hash가 expected 값과 다르다")
        event_time = timestamp or datetime.now(UTC)
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise WorkStateError("timestamp는 timezone-aware여야 한다")
        current_time = datetime.strptime(current["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        if event_time.astimezone(UTC).replace(microsecond=0) < current_time:
            raise InvalidWorkTransition("work event 시각은 현재 snapshot보다 이를 수 없다")
        status = current["payload"]["status"]
        if outcome == "rejected":
            if to_status is not None:
                raise InvalidWorkTransition("rejected event는 상태를 바꿀 수 없다")
        else:
            if to_status not in ALLOWED_TRANSITIONS[status]:
                raise InvalidWorkTransition(f"허용되지 않은 전이: {status} -> {to_status}")
            if outcome != EXPECTED_OUTCOME_BY_STATUS[to_status]:
                raise InvalidWorkTransition("outcome이 목표 상태와 다르다")
            if to_status == "blocked" and not blockers:
                raise InvalidWorkTransition("blocked work에는 blocker가 필요하다")
            if to_status == "completed" and next_action is not None:
                raise InvalidWorkTransition("completed work에는 next_action이 없어야 한다")
            validate_execution_contract(
                self.store, current["payload"]["request"].get("execution")
            )
        events, stream_hash = self._events()
        appended = self.store.append_event(
            "work_events",
            _event_payload(
                work_id=work_id,
                actor=actor,
                action=action,
                outcome=outcome,
                from_status=status,
                to_status=to_status,
                completed_items=completed_items,
                blockers=blockers,
                next_action=next_action,
                related_record_ids=related_record_ids,
                evidence_refs=evidence_refs,
            ),
            expected_stream_hash=stream_hash,
            timestamp=event_time,
        )
        try:
            return self.rebuild_snapshot(work_id, expected_last_event_id=appended["event"]["id"])
        except Exception as exc:
            raise WorkProjectionPending("transition event는 저장됐지만 snapshot 재구축이 남았다") from exc

    def rebuild_snapshot(
        self, work_id: str, *, expected_last_event_id: str | None = None
    ) -> dict[str, Any]:
        identifier = _work_id(work_id)
        events, _ = self._events()
        payload = replay_work_events(events, identifier)
        if expected_last_event_id is not None and payload["last_event_id"] != expected_last_event_id:
            raise WorkProjectionPending("snapshot 재구축 전에 더 최신 work event가 추가됐다")
        last = next(event for event in reversed(events) if event["payload"].get("work_id") == identifier)
        timestamp = datetime.strptime(last["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        try:
            current = self.store.get_record(identifier)
        except RecordNotFoundError:
            return self.store.create_record(
                "work_state", payload, record_id=identifier, timestamp=timestamp
            )
        if current["record_type"] != "work_state":
            raise WorkStateError("work_id가 다른 record type을 가리킨다")
        return self.store.update_record(
            identifier,
            payload,
            expected_content_hash=current["content_hash"],
            timestamp=timestamp,
        )
