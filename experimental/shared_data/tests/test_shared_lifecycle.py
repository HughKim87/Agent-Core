"""L7 승인 lifecycle의 replay·경쟁·복구 회귀."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
UTC = timezone.utc
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experimental.shared_data import (  # noqa: E402
    ACTIONS,
    APPROVAL_KINDS,
    EVENT_FIELDS,
    LIFECYCLE_STATES,
    STATE_FIELDS,
    TARGET_TYPES,
    ConflictError,
    ExpectationMismatchError,
    InvalidLifecycleTransition,
    KnowledgeService,
    LifecycleError,
    LifecycleProjectionPending,
    LifecycleService,
    create_knowledge_store,
    lifecycle_state_record_id,
    replay_lifecycle_events,
)


STORAGE_ROOT = "runtime/shared-lifecycle"
PROTECTED_PATHS = ("private-material", "generated-material")


class Runtime:
    def __init__(self, root: Path) -> None:
        self.store = create_knowledge_store(
            root,
            storage_root=STORAGE_ROOT,
            protected_paths=PROTECTED_PATHS,
            write_enabled=True,
        )
        self.store.initialize()
        self.knowledge = KnowledgeService(self.store)
        self.lifecycle = LifecycleService(self.knowledge)

    def source(self, *, status: str = "verified", locator: str | None = None) -> dict:
        identifier = str(uuid4())
        return self.knowledge.create_source(
            source_kind="user_statement",
            locator=locator or f"request://lifecycle/{identifier}",
            evidence_role="primary",
            verification_status=status,
            record_id=identifier,
        )

    def decision(self, source_id: str) -> dict:
        return self.knowledge.create_decision(
            {
                "problem": "대상을 재검토할지 결정한다.",
                "requirements": ["원본 보존"],
                "options": [
                    {"label": "review", "impact": "검토 필요로 전환"},
                    {"label": "keep", "impact": "현재 유지"},
                ],
                "selected_option": "review",
                "rationale": "관찰한 사건에 따라 검토가 필요하다.",
                "impacts": ["검토 전 현재 목록에서 제외"],
                "source_ids": [source_id],
                "requires_user_approval": True,
                "approval_kind": "standing_policy",
                "approved_by": "user:test-policy",
                "decided_at": datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            record_id=str(uuid4()),
        )


class LifecycleSchemaTests(unittest.TestCase):
    def test_schema_fields_and_enums_match_runtime(self) -> None:
        schemas = ROOT / "experimental" / "shared_data" / "schemas"
        event = json.loads(
            (schemas / "lifecycle-event-payload-v1.schema.json").read_text(encoding="utf-8")
        )
        state = json.loads(
            (schemas / "lifecycle-state-payload-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(event["required"]), EVENT_FIELDS)
        self.assertEqual(set(event["properties"]), EVENT_FIELDS)
        self.assertEqual(set(state["required"]), STATE_FIELDS)
        self.assertEqual(set(state["properties"]), STATE_FIELDS)
        self.assertEqual(set(event["properties"]["action"]["enum"]), ACTIONS)
        self.assertEqual(set(event["properties"]["approval_kind"]["enum"]), APPROVAL_KINDS)
        self.assertEqual(set(event["properties"]["target_type"]["enum"]), TARGET_TYPES)
        self.assertEqual(set(state["properties"]["state"]["enum"]), LIFECYCLE_STATES)


class LifecycleTransitionTests(unittest.TestCase):
    def test_stale_rebuild_cannot_overwrite_newer_projection(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Runtime(Path(raw))
            source = runtime.source()
            current = runtime.lifecycle.register(source["id"], initial_state="candidate",
                actor="agent:test", approval_kind="agent_in_scope", reason="register")
            rival = LifecycleService(runtime.knowledge)
            original = runtime.lifecycle._events
            latest = []
            calls = 0
            def interleave():
                nonlocal calls
                captured = original()
                calls += 1
                # The second read follows capture of the projection CAS baseline.
                if calls == 2:
                    latest.append(rival.transition(source["id"], expected_state_hash=current["content_hash"],
                        action="request_review", actor="agent:rival", approval_kind="agent_in_scope", reason="review"))
                return captured
            with patch.object(runtime.lifecycle, "_events", side_effect=interleave):
                with self.assertRaises(ExpectationMismatchError):
                    runtime.lifecycle.rebuild_snapshot(source["id"])
            self.assertEqual(runtime.lifecycle.get_state(source["id"])["payload"], latest[0]["payload"])

    def test_current_registration_requires_user_approval_and_owns_stable_snapshot_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-register-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source()
            with self.assertRaises(InvalidLifecycleTransition):
                runtime.lifecycle.register(
                    source["id"],
                    initial_state="current",
                    actor="agent:test",
                    approval_kind="agent_in_scope",
                    reason="승인 없는 current 등록",
                )
            state = runtime.lifecycle.register(
                source["id"],
                initial_state="current",
                actor="agent:test",
                approval_kind="standing_policy",
                reason="상시 정책 승인",
            )
            events, _ = runtime.store.list_events("lifecycle_events")
            self.assertEqual(state["id"], events[0]["payload"]["state_record_id"])
            self.assertEqual(state["id"], lifecycle_state_record_id(source["id"], events))
            self.assertEqual(runtime.lifecycle.rebuild_snapshot(source["id"]), state)

    def test_review_and_approval_preserve_append_only_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-review-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source(status="observed")
            candidate = runtime.lifecycle.register(
                source["id"],
                initial_state="candidate",
                actor="agent:test",
                approval_kind="agent_in_scope",
                reason="관찰 후보",
            )
            review = runtime.lifecycle.transition(
                source["id"],
                expected_state_hash=candidate["content_hash"],
                action="request_review",
                actor="agent:test",
                approval_kind="agent_in_scope",
                reason="확인 필요",
            )
            with self.assertRaises(InvalidLifecycleTransition):
                runtime.lifecycle.transition(
                    source["id"],
                    expected_state_hash=review["content_hash"],
                    action="approve_current",
                    actor="agent:test",
                    approval_kind="agent_in_scope",
                    reason="무권한 승인",
                )
            current = runtime.lifecycle.transition(
                source["id"],
                expected_state_hash=review["content_hash"],
                action="approve_current",
                actor="user:test",
                approval_kind="user",
                reason="사용자 검토 완료",
            )
            self.assertEqual(current["payload"]["revision"], 3)
            history = runtime.lifecycle.history(source["id"])
            self.assertEqual(
                [event["payload"]["action"] for event in history],
                ["register", "request_review", "approve_current"],
            )
            self.assertEqual(replay_lifecycle_events(source["id"], history), current["payload"])

    def test_expected_hash_terminal_and_time_boundaries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-boundary-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source()
            now = datetime.now(UTC).replace(microsecond=0)
            state = runtime.lifecycle.register(
                source["id"],
                initial_state="current",
                actor="agent:test",
                approval_kind="standing_policy",
                reason="현재 등록",
                timestamp=now,
            )
            with self.assertRaises(ExpectationMismatchError):
                runtime.lifecycle.transition(
                    source["id"],
                    expected_state_hash="sha256:" + "0" * 64,
                    action="retire",
                    actor="user:test",
                    approval_kind="user",
                    reason="오래된 기대값",
                )
            with self.assertRaises(InvalidLifecycleTransition):
                runtime.lifecycle.transition(
                    source["id"],
                    expected_state_hash=state["content_hash"],
                    action="request_review",
                    actor="agent:test",
                    approval_kind="agent_in_scope",
                    reason="과거 event",
                    timestamp=now - timedelta(seconds=1),
                )
            retired = runtime.lifecycle.transition(
                source["id"],
                expected_state_hash=state["content_hash"],
                action="retire",
                actor="user:test",
                approval_kind="user",
                reason="사용 종료",
                timestamp=now,
            )
            with self.assertRaises(InvalidLifecycleTransition):
                runtime.lifecycle.transition(
                    source["id"],
                    expected_state_hash=retired["content_hash"],
                    action="request_review",
                    actor="agent:test",
                    approval_kind="agent_in_scope",
                    reason="terminal 복귀",
                )

    def test_supersede_preserves_old_record_and_selects_current_replacement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-supersede-") as raw_root:
            runtime = Runtime(Path(raw_root))
            old = runtime.source()
            replacement = runtime.source()
            old_state = runtime.lifecycle.register(
                old["id"],
                initial_state="current",
                actor="agent:test",
                approval_kind="standing_policy",
                reason="기존 current",
            )
            runtime.lifecycle.register(
                replacement["id"],
                initial_state="current",
                actor="agent:test",
                approval_kind="standing_policy",
                reason="개정 current",
            )
            superseded = runtime.lifecycle.transition(
                old["id"],
                expected_state_hash=old_state["content_hash"],
                action="supersede",
                actor="user:test",
                approval_kind="user",
                reason="새 출처로 대체",
                replacement_id=replacement["id"],
            )
            self.assertEqual(superseded["payload"]["superseded_by"], replacement["id"])
            self.assertEqual(runtime.store.get_record(old["id"]), old)
            self.assertEqual(
                [record["id"] for record in runtime.lifecycle.current_records(target_type="source")],
                [replacement["id"]],
            )

    def test_conflict_uses_one_event_and_marks_both_registered_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-conflict-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source()
            first = runtime.knowledge.create_knowledge(
                statement="첫 주장이 현재다.",
                classification="fact",
                scope="test",
                source_ids=[source["id"]],
                verification_status="verified",
                verified_by="user:test",
                record_id=str(uuid4()),
            )
            second = runtime.knowledge.create_knowledge(
                statement="둘째 주장이 현재다.",
                classification="fact",
                scope="test",
                source_ids=[source["id"]],
                verification_status="verified",
                verified_by="user:test",
                record_id=str(uuid4()),
            )
            runtime.lifecycle.register_existing(actor="agent:test", approval_kind="standing_policy")
            before, _ = runtime.store.list_events("lifecycle_events")
            first_state = runtime.lifecycle.get_state(first["id"])
            runtime.lifecycle.transition(
                first["id"],
                expected_state_hash=first_state["content_hash"],
                action="declare_conflict",
                actor="agent:test",
                approval_kind="agent_in_scope",
                reason="양립할 수 없는 주장",
                related_target_ids=[second["id"]],
            )
            after, _ = runtime.store.list_events("lifecycle_events")
            self.assertEqual(len(after), len(before) + 1)
            for target, other in ((first, second), (second, first)):
                state = runtime.lifecycle.get_state(target["id"])
                self.assertEqual(state["payload"]["state"], "review_required")
                self.assertIn(other["id"], state["payload"]["conflict_ids"])
                self.assertEqual(runtime.store.get_record(target["id"]), target)
                self.assertEqual(runtime.lifecycle.history(target["id"])[-1]["id"], after[-1]["id"])

    def test_event_can_reference_a_current_approved_decision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-decision-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source()
            decision = runtime.decision(source["id"])
            runtime.lifecycle.register_existing(actor="agent:test", approval_kind="standing_policy")
            state = runtime.lifecycle.get_state(source["id"])
            updated = runtime.lifecycle.transition(
                source["id"],
                expected_state_hash=state["content_hash"],
                action="request_review",
                actor="agent:test",
                approval_kind="agent_in_scope",
                reason="승인된 결정 적용",
                decision_id=decision["id"],
            )
            self.assertEqual(updated["payload"]["last_decision_id"], decision["id"])

    def test_register_existing_is_idempotent_and_preserves_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-existing-") as raw_root:
            runtime = Runtime(Path(raw_root))
            observed = runtime.source(status="observed")
            verified = runtime.source(status="verified")
            created = runtime.lifecycle.register_existing(
                actor="agent:test", approval_kind="standing_policy"
            )
            self.assertEqual(len(created), 2)
            self.assertEqual(runtime.lifecycle.get_state(observed["id"])["payload"]["state"], "candidate")
            self.assertEqual(runtime.lifecycle.get_state(verified["id"])["payload"]["state"], "current")
            self.assertEqual(
                runtime.lifecycle.register_existing(actor="agent:test", approval_kind="standing_policy"),
                [],
            )


class LifecycleRecoveryTests(unittest.TestCase):
    def test_concurrent_projection_creation_cannot_overwrite_winner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Runtime(Path(raw))
            source = runtime.source()
            with patch.object(runtime.store, "create_record", side_effect=OSError("projection failure")):
                with self.assertRaises(LifecycleProjectionPending):
                    runtime.lifecycle.register(source["id"], initial_state="candidate", actor="agent:test",
                        approval_kind="agent_in_scope", reason="register")
            rival = LifecycleService(runtime.knowledge)
            original = runtime.store.create_record
            winner = []
            def interleave(*args, **kwargs):
                with patch.object(runtime.store, "create_record", original):
                    initial = rival.rebuild_snapshot(source["id"])
                    winner.append(rival.transition(source["id"], expected_state_hash=initial["content_hash"],
                        actor="agent:rival", action="request_review", approval_kind="agent_in_scope", reason="review"))
                return original(*args, **kwargs)
            with patch.object(runtime.store, "create_record", side_effect=interleave):
                with self.assertRaises(ConflictError):
                    runtime.lifecycle.rebuild_snapshot(source["id"])
            self.assertEqual(runtime.lifecycle.get_state(source["id"]), winner[0])

    def test_committed_event_blocks_new_transition_until_projection_rebuild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-recovery-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source(status="observed")
            state = runtime.lifecycle.register(
                source["id"],
                initial_state="candidate",
                actor="agent:test",
                approval_kind="agent_in_scope",
                reason="후보 등록",
            )
            original_update = runtime.store.update_record
            with patch.object(runtime.store, "update_record", side_effect=OSError("simulated projection failure")):
                with self.assertRaises(LifecycleProjectionPending):
                    runtime.lifecycle.transition(
                        source["id"],
                        expected_state_hash=state["content_hash"],
                        action="request_review",
                        actor="agent:test",
                        approval_kind="agent_in_scope",
                        reason="검토 사건",
                    )
            self.assertEqual(
                [event["payload"]["action"] for event in runtime.lifecycle.history(source["id"])],
                ["register", "request_review"],
            )
            with self.assertRaises(LifecycleProjectionPending):
                runtime.lifecycle.get_state(source["id"])
            with self.assertRaises(LifecycleProjectionPending):
                runtime.lifecycle.current_records()
            with self.assertRaises(LifecycleProjectionPending):
                runtime.lifecycle.transition(
                    source["id"],
                    expected_state_hash=state["content_hash"],
                    action="approve_current",
                    actor="user:test",
                    approval_kind="user",
                    reason="projection 전에 후속 전이",
                )
            with patch.object(runtime.store, "update_record", wraps=original_update):
                rebuilt = runtime.lifecycle.rebuild_snapshot(source["id"])
            self.assertEqual(rebuilt["payload"]["state"], "review_required")
            self.assertEqual(runtime.lifecycle.get_state(source["id"]), rebuilt)

    def test_local_source_drift_marks_source_and_dependents_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-audit-") as raw_root:
            root = Path(raw_root)
            target = root / "evidence" / "source.md"
            target.parent.mkdir()
            target.write_text("version one\n", encoding="utf-8")
            runtime = Runtime(root)
            source = runtime.knowledge.create_source(
                source_kind="local_document",
                locator="evidence/source.md",
                evidence_role="primary",
                record_id=str(uuid4()),
            )
            knowledge = runtime.knowledge.create_knowledge(
                statement="출처는 version one이다.",
                classification="fact",
                scope="test",
                source_ids=[source["id"]],
                verification_status="verified",
                verified_by="agent:test",
                record_id=str(uuid4()),
            )
            runtime.lifecycle.register_existing(actor="agent:test", approval_kind="standing_policy")
            target.write_text("version two\n", encoding="utf-8")
            findings = runtime.lifecycle.audit(actor="agent:audit")
            self.assertEqual({item["target_id"] for item in findings}, {source["id"], knowledge["id"]})
            lengths = {
                source["id"]: len(runtime.lifecycle.history(source["id"])),
                knowledge["id"]: len(runtime.lifecycle.history(knowledge["id"])),
            }
            runtime.lifecycle.audit(actor="agent:audit")
            self.assertEqual(len(runtime.lifecycle.history(source["id"])), lengths[source["id"]])
            self.assertEqual(len(runtime.lifecycle.history(knowledge["id"])), lengths[knowledge["id"]])

    def test_conflict_requires_same_type_and_registered_related_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lifecycle-invalid-conflict-") as raw_root:
            runtime = Runtime(Path(raw_root))
            source = runtime.source()
            other = runtime.knowledge.create_knowledge(
                statement="다른 유형의 주장이다.",
                classification="fact",
                scope="test",
                source_ids=[source["id"]],
                verification_status="verified",
                verified_by="agent:test",
                record_id=str(uuid4()),
            )
            runtime.lifecycle.register(
                source["id"],
                initial_state="current",
                actor="agent:test",
                approval_kind="standing_policy",
                reason="source 등록",
            )
            state = runtime.lifecycle.get_state(source["id"])
            with self.assertRaises(LifecycleError):
                runtime.lifecycle.transition(
                    source["id"],
                    expected_state_hash=state["content_hash"],
                    action="declare_conflict",
                    actor="agent:test",
                    approval_kind="agent_in_scope",
                    reason="잘못된 유형",
                    related_target_ids=[other["id"]],
                )
            self.assertEqual(runtime.lifecycle.get_state(source["id"]), state)


if __name__ == "__main__":
    unittest.main()
