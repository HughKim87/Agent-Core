"""지식 원본을 바꾸지 않는 승인 기반 lifecycle event와 projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .knowledge import KnowledgeService, SourceIntegrityError
from .store import (
    ConflictError,
    ExpectationMismatchError,
    InputContractError,
    RecordNotFoundError,
    RecordStore,
)


LIFECYCLE_RECORD_TYPES = frozenset({"lifecycle_state"})
LIFECYCLE_STREAMS = frozenset({"lifecycle_events"})
TARGET_TYPES = frozenset({"source", "knowledge", "decision"})
LIFECYCLE_STATES = frozenset(
    {"candidate", "current", "review_required", "superseded", "rejected", "retired"}
)
TERMINAL_STATES = frozenset({"superseded", "rejected", "retired"})
APPROVAL_KINDS = frozenset({"agent_in_scope", "user", "standing_policy"})
CURRENT_APPROVAL_KINDS = frozenset({"user", "standing_policy"})
ACTIONS = frozenset(
    {"register", "request_review", "approve_current", "declare_conflict", "supersede", "reject", "retire"}
)
EVENT_FIELDS = frozenset(
    {
        "target_id",
        "target_type",
        "state_record_id",
        "actor",
        "action",
        "from_state",
        "to_state",
        "reason",
        "approval_kind",
        "source_ids",
        "related_target_ids",
        "replacement_id",
        "decision_id",
    }
)
STATE_FIELDS = frozenset(
    {
        "target_id",
        "target_type",
        "state",
        "revision",
        "last_event_id",
        "conflict_ids",
        "superseded_by",
        "last_reason",
        "last_actor",
        "last_approval_kind",
        "last_source_ids",
        "last_decision_id",
    }
)


class LifecycleError(InputContractError):
    """Lifecycle payload·참조·projection 계약 위반."""


class InvalidLifecycleTransition(LifecycleError):
    """현재 상태에서 허용되지 않거나 승인이 부족한 전이다."""


class LifecycleProjectionPending(LifecycleError):
    """정본 event는 commit됐지만 재구축 가능한 snapshot 반영이 남았다."""


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise LifecycleError(f"{field}는 NUL 없는 비어 있지 않은 문자열이어야 한다")
    return value.strip()


def _uuid(value: Any, field: str) -> str:
    rendered = _non_empty(value, field)
    try:
        parsed = UUID(rendered)
    except (ValueError, AttributeError, TypeError) as exc:
        raise LifecycleError(f"{field}는 UUID여야 한다") from exc
    if parsed.version != 4 or str(parsed) != rendered:
        raise LifecycleError(f"{field}는 소문자 canonical UUIDv4여야 한다")
    return rendered


def _uuid_list(values: Any, field: str) -> list[str]:
    if not isinstance(values, list):
        raise LifecycleError(f"{field}는 목록이어야 한다")
    normalized = [_uuid(value, field) for value in values]
    if len(normalized) != len(set(normalized)):
        raise LifecycleError(f"{field}에는 중복을 사용할 수 없다")
    return normalized


def _optional_uuid(value: Any, field: str) -> str | None:
    return None if value is None else _uuid(value, field)


def _choice(value: Any, allowed: frozenset[str], field: str) -> str:
    rendered = _non_empty(value, field)
    if rendered not in allowed:
        raise LifecycleError(f"{field} 허용값: {sorted(allowed)}")
    return rendered


def validate_lifecycle_event_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != EVENT_FIELDS:
        raise LifecycleError(f"lifecycle event field가 정확하지 않다: {sorted(EVENT_FIELDS)}")
    normalized = {
        "target_id": _uuid(payload["target_id"], "target_id"),
        "target_type": _choice(payload["target_type"], TARGET_TYPES, "target_type"),
        "state_record_id": _uuid(payload["state_record_id"], "state_record_id"),
        "actor": _non_empty(payload["actor"], "actor"),
        "action": _choice(payload["action"], ACTIONS, "action"),
        "from_state": None
        if payload["from_state"] is None
        else _choice(payload["from_state"], LIFECYCLE_STATES, "from_state"),
        "to_state": _choice(payload["to_state"], LIFECYCLE_STATES, "to_state"),
        "reason": _non_empty(payload["reason"], "reason"),
        "approval_kind": _choice(payload["approval_kind"], APPROVAL_KINDS, "approval_kind"),
        "source_ids": _uuid_list(payload["source_ids"], "source_ids"),
        "related_target_ids": _uuid_list(payload["related_target_ids"], "related_target_ids"),
        "replacement_id": _optional_uuid(payload["replacement_id"], "replacement_id"),
        "decision_id": _optional_uuid(payload["decision_id"], "decision_id"),
    }
    if normalized["target_id"] in normalized["related_target_ids"]:
        raise LifecycleError("related_target_ids에는 target_id를 넣을 수 없다")
    if normalized["action"] == "declare_conflict":
        if not normalized["related_target_ids"]:
            raise InvalidLifecycleTransition("declare_conflict에는 related_target_ids가 필요하다")
    elif normalized["related_target_ids"]:
        raise InvalidLifecycleTransition("related_target_ids는 declare_conflict에만 사용할 수 있다")
    return normalized


def validate_lifecycle_state_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != STATE_FIELDS:
        raise LifecycleError(f"lifecycle state field가 정확하지 않다: {sorted(STATE_FIELDS)}")
    revision = payload["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise LifecycleError("revision은 1 이상의 정수여야 한다")
    return {
        "target_id": _uuid(payload["target_id"], "target_id"),
        "target_type": _choice(payload["target_type"], TARGET_TYPES, "target_type"),
        "state": _choice(payload["state"], LIFECYCLE_STATES, "state"),
        "revision": revision,
        "last_event_id": _uuid(payload["last_event_id"], "last_event_id"),
        "conflict_ids": _uuid_list(payload["conflict_ids"], "conflict_ids"),
        "superseded_by": _optional_uuid(payload["superseded_by"], "superseded_by"),
        "last_reason": _non_empty(payload["last_reason"], "last_reason"),
        "last_actor": _non_empty(payload["last_actor"], "last_actor"),
        "last_approval_kind": _choice(
            payload["last_approval_kind"], APPROVAL_KINDS, "last_approval_kind"
        ),
        "last_source_ids": _uuid_list(payload["last_source_ids"], "last_source_ids"),
        "last_decision_id": _optional_uuid(payload["last_decision_id"], "last_decision_id"),
    }


def _transition_target(action: str, current: str | None, requested: str, replacement_id: str | None) -> str:
    if action == "register":
        if current is not None or requested not in {"candidate", "current"}:
            raise InvalidLifecycleTransition("register는 선행 상태 없이 candidate/current로만 가능하다")
        return requested
    if current is None:
        raise InvalidLifecycleTransition("전이 전에 대상을 등록해야 한다")
    if current in TERMINAL_STATES:
        raise InvalidLifecycleTransition(f"terminal 상태는 전이할 수 없다: {current}")
    rules = {
        "request_review": ({"candidate", "current"}, "review_required"),
        "approve_current": ({"candidate", "review_required"}, "current"),
        "declare_conflict": ({"candidate", "current", "review_required"}, "review_required"),
        "supersede": ({"candidate", "current", "review_required"}, "superseded"),
        "reject": ({"candidate", "review_required"}, "rejected"),
        "retire": ({"current", "review_required"}, "retired"),
    }
    allowed, expected = rules[action]
    if current not in allowed or requested != expected:
        raise InvalidLifecycleTransition(f"허용되지 않은 전이: {current} --{action}--> {requested}")
    if action == "supersede" and replacement_id is None:
        raise InvalidLifecycleTransition("supersede에는 replacement_id가 필요하다")
    if action != "supersede" and replacement_id is not None:
        raise InvalidLifecycleTransition("replacement_id는 supersede에만 사용할 수 있다")
    return requested


def _requires_current_approval(action: str, to_state: str) -> bool:
    return action in {"approve_current", "supersede", "reject", "retire"} or (
        action == "register" and to_state == "current"
    )


def _event_applies(payload: Mapping[str, Any], target_id: str) -> bool:
    return payload["target_id"] == target_id or (
        payload["action"] == "declare_conflict" and target_id in payload["related_target_ids"]
    )


def lifecycle_state_record_id(target_id: str, events: Sequence[Mapping[str, Any]]) -> str:
    identifier = _uuid(target_id, "target_id")
    owned = [
        validate_lifecycle_event_payload(event["payload"])
        for event in events
        if event.get("payload", {}).get("target_id") == identifier
    ]
    if not owned or owned[0]["action"] != "register":
        raise LifecycleError(f"대상의 최초 register event가 없다: {identifier}")
    state_record_id = owned[0]["state_record_id"]
    if any(payload["state_record_id"] != state_record_id for payload in owned):
        raise LifecycleError("대상의 state_record_id가 lifecycle history에서 바뀌었다")
    return state_record_id


def replay_lifecycle_events(target_id: str, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    identifier = _uuid(target_id, "target_id")
    matching: list[tuple[Mapping[str, Any], dict[str, Any], bool]] = []
    for event in events:
        payload = validate_lifecycle_event_payload(event["payload"])
        if _event_applies(payload, identifier):
            matching.append((event, payload, payload["target_id"] == identifier))
    if not matching:
        raise LifecycleError(f"대상의 lifecycle event가 없다: {identifier}")
    lifecycle_state_record_id(identifier, events)

    current: dict[str, Any] | None = None
    target_type: str | None = None
    conflict_ids: list[str] = []
    for index, (event, payload, is_primary) in enumerate(matching):
        if target_type is None:
            target_type = payload["target_type"]
        elif target_type != payload["target_type"]:
            raise LifecycleError("lifecycle history에서 target_type이 바뀌었다")
        current_state = None if current is None else current["state"]
        if is_primary:
            if payload["from_state"] != current_state:
                raise InvalidLifecycleTransition("event from_state가 replay 상태와 다르다")
            action = payload["action"]
            related_ids = payload["related_target_ids"]
            replacement_id = payload["replacement_id"]
        else:
            if payload["action"] != "declare_conflict" or current_state is None:
                raise InvalidLifecycleTransition("관련 conflict event보다 먼저 대상을 등록해야 한다")
            action = "declare_conflict"
            related_ids = [payload["target_id"]]
            replacement_id = None
        _transition_target(action, current_state, payload["to_state"], replacement_id)
        if _requires_current_approval(action, payload["to_state"]):
            if payload["approval_kind"] not in CURRENT_APPROVAL_KINDS:
                raise InvalidLifecycleTransition("current·terminal 전이에는 사용자 계열 승인이 필요하다")
        if action == "declare_conflict":
            conflict_ids = list(dict.fromkeys([*conflict_ids, *related_ids]))
        current = {
            "target_id": identifier,
            "target_type": payload["target_type"],
            "state": payload["to_state"],
            "revision": index + 1,
            "last_event_id": event["id"],
            "conflict_ids": conflict_ids,
            "superseded_by": replacement_id if action == "supersede" else None,
            "last_reason": payload["reason"],
            "last_actor": payload["actor"],
            "last_approval_kind": payload["approval_kind"],
            "last_source_ids": payload["source_ids"],
            "last_decision_id": payload["decision_id"],
        }
    assert current is not None
    return validate_lifecycle_state_payload(current)


class LifecycleService:
    """Lifecycle event를 정본으로, lifecycle_state record를 projection으로 관리한다."""

    def __init__(self, knowledge: KnowledgeService) -> None:
        if not isinstance(knowledge, KnowledgeService):
            raise InputContractError("LifecycleService에는 KnowledgeService가 필요하다")
        self.knowledge = knowledge
        self.store: RecordStore = knowledge.store
        missing_records = LIFECYCLE_RECORD_TYPES - self.store.approved_record_types
        missing_streams = LIFECYCLE_STREAMS - self.store.approved_streams
        if missing_records or missing_streams:
            raise InputContractError(
                f"lifecycle store allowlist가 부족하다: records={sorted(missing_records)}, "
                f"streams={sorted(missing_streams)}"
            )

    def _events(self) -> tuple[list[dict[str, Any]], str]:
        events, stream_hash = self.store.list_events("lifecycle_events")
        for event in events:
            validate_lifecycle_event_payload(event["payload"])
        return events, stream_hash

    def _base_record(self, target_id: str) -> dict[str, Any]:
        record = self.store.get_record(_uuid(target_id, "target_id"))
        if record["record_type"] not in TARGET_TYPES:
            raise LifecycleError(f"지원하지 않는 lifecycle target type: {record['record_type']}")
        return record

    def _authoritative_state(
        self, target_id: str, events: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any] | None:
        if not any(_event_applies(validate_lifecycle_event_payload(event["payload"]), target_id) for event in events):
            return None
        return replay_lifecycle_events(target_id, events)

    def _projection_or_none(
        self, target_id: str, events: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any] | None:
        state_id = lifecycle_state_record_id(target_id, events)
        try:
            record = self.store.get_record(state_id)
        except RecordNotFoundError:
            return None
        if record["record_type"] != "lifecycle_state":
            raise LifecycleError("state_record_id가 lifecycle_state를 가리키지 않는다")
        validate_lifecycle_state_payload(record["payload"])
        return record

    def get_state(self, target_id: str) -> dict[str, Any]:
        identifier = _uuid(target_id, "target_id")
        base = self._base_record(identifier)
        events, _ = self._events()
        authoritative = self._authoritative_state(identifier, events)
        if authoritative is None:
            raise LifecycleError(f"lifecycle 대상이 등록되지 않았다: {identifier}")
        if authoritative["target_type"] != base["record_type"]:
            raise LifecycleError("lifecycle target_type이 base record와 다르다")
        projection = self._projection_or_none(identifier, events)
        if projection is None or projection["payload"] != authoritative:
            raise LifecycleProjectionPending(f"lifecycle snapshot 재구축이 필요하다: {identifier}")
        return projection

    def get_record(self, target_id: str) -> dict[str, Any]:
        return {"record": self._base_record(target_id), "lifecycle": self.get_state(target_id)}

    def register(
        self,
        target_id: str,
        *,
        initial_state: str,
        actor: str,
        approval_kind: str,
        reason: str,
        source_ids: Sequence[str] = (),
        decision_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        base = self._base_record(target_id)
        events, _ = self._events()
        if self._authoritative_state(base["id"], events) is not None:
            raise LifecycleError(f"lifecycle 대상이 이미 등록됐다: {base['id']}")
        return self._append_and_rebuild(
            base,
            expected_state_hash=None,
            action="register",
            to_state=initial_state,
            actor=actor,
            approval_kind=approval_kind,
            reason=reason,
            source_ids=source_ids,
            decision_id=decision_id,
            timestamp=timestamp,
        )

    def transition(
        self,
        target_id: str,
        *,
        expected_state_hash: str,
        action: str,
        actor: str,
        approval_kind: str,
        reason: str,
        source_ids: Sequence[str] = (),
        related_target_ids: Sequence[str] = (),
        replacement_id: str | None = None,
        decision_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        action = _choice(action, ACTIONS - {"register"}, "action")
        targets = {
            "request_review": "review_required",
            "approve_current": "current",
            "declare_conflict": "review_required",
            "supersede": "superseded",
            "reject": "rejected",
            "retire": "retired",
        }
        return self._append_and_rebuild(
            self._base_record(target_id),
            expected_state_hash=expected_state_hash,
            action=action,
            to_state=targets[action],
            actor=actor,
            approval_kind=approval_kind,
            reason=reason,
            source_ids=source_ids,
            related_target_ids=related_target_ids,
            replacement_id=replacement_id,
            decision_id=decision_id,
            timestamp=timestamp,
        )

    def _append_and_rebuild(
        self,
        base: Mapping[str, Any],
        *,
        expected_state_hash: str | None,
        action: str,
        to_state: str,
        actor: str,
        approval_kind: str,
        reason: str,
        source_ids: Sequence[str] = (),
        related_target_ids: Sequence[str] = (),
        replacement_id: str | None = None,
        decision_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        events, stream_hash = self._events()
        authoritative = self._authoritative_state(base["id"], events)
        projection = None if authoritative is None else self._projection_or_none(base["id"], events)
        if authoritative is not None:
            if projection is None or projection["payload"] != authoritative:
                raise LifecycleProjectionPending("전이 전에 lifecycle snapshot 재구축이 필요하다")
            if projection["content_hash"] != expected_state_hash:
                raise ExpectationMismatchError("현재 lifecycle state hash가 expected 값과 다르다")
            state_record_id = projection["id"]
        else:
            if action != "register":
                raise InvalidLifecycleTransition("전이 전에 대상을 등록해야 한다")
            if expected_state_hash is not None:
                raise ExpectationMismatchError("미등록 대상에는 expected state hash를 사용할 수 없다")
            state_record_id = str(uuid4())
        from_state = None if authoritative is None else authoritative["state"]

        event_timestamp = timestamp or datetime.now(UTC)
        if event_timestamp.tzinfo is None or event_timestamp.utcoffset() is None:
            raise LifecycleError("timestamp는 timezone-aware여야 한다")
        event_timestamp = event_timestamp.astimezone(UTC).replace(microsecond=0)
        applicable_events = [
            event
            for event in events
            if _event_applies(validate_lifecycle_event_payload(event["payload"]), base["id"])
        ]
        if applicable_events:
            last_time = datetime.strptime(
                applicable_events[-1]["created_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
            if event_timestamp < last_time:
                raise InvalidLifecycleTransition("lifecycle event 시각은 이전 event보다 이를 수 없다")

        payload = validate_lifecycle_event_payload(
            {
                "target_id": base["id"],
                "target_type": base["record_type"],
                "state_record_id": state_record_id,
                "actor": actor,
                "action": action,
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
                "approval_kind": approval_kind,
                "source_ids": list(source_ids),
                "related_target_ids": list(related_target_ids),
                "replacement_id": replacement_id,
                "decision_id": decision_id,
            }
        )
        _transition_target(action, from_state, to_state, payload["replacement_id"])
        if _requires_current_approval(action, to_state) and payload["approval_kind"] not in CURRENT_APPROVAL_KINDS:
            raise InvalidLifecycleTransition("current·terminal 전이에는 user 또는 standing_policy 승인이 필요하다")

        for source_id in payload["source_ids"]:
            if self._base_record(source_id)["record_type"] != "source":
                raise LifecycleError("source_ids는 source record를 가리켜야 한다")
        for related_id in payload["related_target_ids"]:
            related = self._base_record(related_id)
            if related["record_type"] != base["record_type"]:
                raise LifecycleError("conflict 대상은 같은 record type이어야 한다")
            related_state = self._authoritative_state(related_id, events)
            if related_state is None:
                raise InvalidLifecycleTransition("conflict 대상은 먼저 등록해야 한다")
            related_projection = self._projection_or_none(related_id, events)
            if related_projection is None or related_projection["payload"] != related_state:
                raise LifecycleProjectionPending("conflict 대상 snapshot 재구축이 필요하다")
            _transition_target("declare_conflict", related_state["state"], "review_required", None)
        if payload["replacement_id"] is not None:
            if payload["replacement_id"] == base["id"]:
                raise InvalidLifecycleTransition("대상은 자기 자신으로 대체할 수 없다")
            replacement = self._base_record(payload["replacement_id"])
            if replacement["record_type"] != base["record_type"]:
                raise LifecycleError("replacement는 같은 record type이어야 한다")
            replacement_state = self._authoritative_state(replacement["id"], events)
            if replacement_state is None or replacement_state["state"] != "current":
                raise InvalidLifecycleTransition("replacement는 lifecycle current여야 한다")
        if payload["decision_id"] is not None:
            decision = self._base_record(payload["decision_id"])
            if decision["record_type"] != "decision":
                raise LifecycleError("decision_id는 decision record를 가리켜야 한다")
            decision_state = self._authoritative_state(decision["id"], events)
            if decision_state is None or decision_state["state"] != "current":
                raise InvalidLifecycleTransition("decision_id는 lifecycle current decision이어야 한다")

        appended = self.store.append_event(
            "lifecycle_events",
            payload,
            expected_stream_hash=stream_hash,
            timestamp=event_timestamp,
        )
        affected = [base["id"], *payload["related_target_ids"]]
        try:
            for target_id in affected:
                self.rebuild_snapshot(target_id, expected_last_event_id=appended["event"]["id"])
        except Exception as exc:
            raise LifecycleProjectionPending(
                "lifecycle event는 저장됐지만 snapshot 재구축이 남았다"
            ) from exc
        return self.get_state(base["id"])

    def rebuild_snapshot(
        self, target_id: str, *, expected_last_event_id: str | None = None
    ) -> dict[str, Any]:
        base = self._base_record(target_id)
        events, _ = self._events()
        payload = replay_lifecycle_events(base["id"], events)
        if payload["target_type"] != base["record_type"]:
            raise LifecycleError("lifecycle target_type이 base record와 다르다")
        if expected_last_event_id is not None and payload["last_event_id"] != expected_last_event_id:
            raise LifecycleError("lifecycle replay가 기대 event에서 끝나지 않았다")
        state_id = lifecycle_state_record_id(base["id"], events)
        event = next(item for item in reversed(events) if item["id"] == payload["last_event_id"])
        timestamp = datetime.strptime(event["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        try:
            current = self.store.get_record(state_id)
        except RecordNotFoundError:
            current = None
        if current is None:
            try:
                return self.store.create_record(
                    "lifecycle_state", payload, record_id=state_id, timestamp=timestamp
                )
            except ConflictError:
                current = self.store.get_record(state_id)
        if current["record_type"] != "lifecycle_state":
            raise LifecycleError("state_record_id가 lifecycle_state를 가리키지 않는다")
        return self.store.update_record(
            state_id,
            payload,
            expected_content_hash=current["content_hash"],
            timestamp=timestamp,
        )

    def history(self, target_id: str) -> list[dict[str, Any]]:
        identifier = _uuid(target_id, "target_id")
        events, _ = self._events()
        return [
            event
            for event in events
            if _event_applies(validate_lifecycle_event_payload(event["payload"]), identifier)
        ]

    def list_states(
        self, *, state: str | None = None, target_type: str | None = None
    ) -> list[dict[str, Any]]:
        if state is not None:
            state = _choice(state, LIFECYCLE_STATES, "state")
        if target_type is not None:
            target_type = _choice(target_type, TARGET_TYPES, "target_type")
        events, _ = self._events()
        records = self.store.list_records("lifecycle_state")
        registered_ids = {
            event["payload"]["target_id"]
            for event in events
            if event["payload"]["action"] == "register"
        }
        projections_by_target: dict[str, dict[str, Any]] = {}
        for record in records:
            payload = validate_lifecycle_state_payload(record["payload"])
            target_id = payload["target_id"]
            if target_id in projections_by_target:
                raise LifecycleError("한 대상에 lifecycle_state projection이 둘 이상 있다")
            projections_by_target[target_id] = record
        for target_id in registered_ids:
            authoritative = replay_lifecycle_events(target_id, events)
            projection = projections_by_target.get(target_id)
            if (
                projection is None
                or projection["id"] != lifecycle_state_record_id(target_id, events)
                or projection["payload"] != authoritative
            ):
                raise LifecycleProjectionPending(
                    f"목록 선택 전에 lifecycle snapshot 재구축이 필요하다: {target_id}"
                )
        orphaned = set(projections_by_target) - registered_ids
        if orphaned:
            raise LifecycleError("register event가 없는 lifecycle_state projection이 있다")
        return [
            record
            for record in records
            if (state is None or record["payload"]["state"] == state)
            and (target_type is None or record["payload"]["target_type"] == target_type)
        ]

    def current_records(self, *, target_type: str | None = None) -> list[dict[str, Any]]:
        return [
            self._base_record(state["payload"]["target_id"])
            for state in self.list_states(state="current", target_type=target_type)
        ]

    def _recommended_initial_state(self, record: Mapping[str, Any]) -> str:
        if record["record_type"] in {"source", "knowledge"}:
            return "current" if record["payload"]["verification_status"] == "verified" else "candidate"
        return "current"

    def register_existing(self, *, actor: str, approval_kind: str) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for target_type in ("source", "knowledge", "decision"):
            for record in self.store.list_records(target_type):
                events, _ = self._events()
                if self._authoritative_state(record["id"], events) is not None:
                    try:
                        self.get_state(record["id"])
                    except LifecycleProjectionPending:
                        self.rebuild_snapshot(record["id"])
                    continue
                initial = self._recommended_initial_state(record)
                created.append(
                    self.register(
                        record["id"],
                        initial_state=initial,
                        actor=actor,
                        approval_kind=approval_kind if initial == "current" else "agent_in_scope",
                        reason="기존 검증 상태를 보존한 lifecycle 등록",
                    )
                )
        return created

    def _dependency_source_ids(self, record: Mapping[str, Any]) -> list[str]:
        return list(record["payload"]["source_ids"]) if record["record_type"] in {"knowledge", "decision"} else []

    def audit(self, *, actor: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        drifted_sources: set[str] = set()
        for state in self.list_states():
            if state["payload"]["state"] in TERMINAL_STATES:
                continue
            record = self._base_record(state["payload"]["target_id"])
            reason: str | None = None
            if record["record_type"] == "source" and record["payload"]["source_kind"] in {
                "local_document",
                "local_data",
            }:
                try:
                    self.knowledge.get_source(record["id"], verify_local=True)
                except SourceIntegrityError as exc:
                    reason = str(exc)
                    drifted_sources.add(record["id"])
            if reason is not None:
                findings.append({"target_id": record["id"], "reason": reason})
                if state["payload"]["state"] != "review_required":
                    self.transition(
                        record["id"],
                        expected_state_hash=state["content_hash"],
                        action="request_review",
                        actor=actor,
                        approval_kind="agent_in_scope",
                        reason=reason,
                    )
        for state in self.list_states():
            if state["payload"]["state"] in TERMINAL_STATES | {"review_required"}:
                continue
            record = self._base_record(state["payload"]["target_id"])
            affected = sorted(set(self._dependency_source_ids(record)) & drifted_sources)
            if affected:
                reason = "참조한 source에 재검토가 필요하다: " + ", ".join(affected)
                findings.append({"target_id": record["id"], "reason": reason})
                self.transition(
                    record["id"],
                    expected_state_hash=state["content_hash"],
                    action="request_review",
                    actor=actor,
                    approval_kind="agent_in_scope",
                    reason=reason,
                    source_ids=affected,
                )
        return findings
