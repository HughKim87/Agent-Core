"""L7 work event·projection·execution 포인터의 정상·경쟁·복구 회귀."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experimental.shared_data import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    EVENT_OUTCOMES,
    EXECUTION_FIELDS,
    EXECUTION_TIERS,
    REQUEST_FIELDS,
    WORK_EVENT_FIELDS,
    WORK_STATE_FIELDS,
    DesignContractError,
    DesignInvalidatedError,
    DesignRequiredError,
    ExpectationMismatchError,
    InvalidWorkTransition,
    WorkProjectionPending,
    WorkStateError,
    WorkStateService,
    WriteNotEnabledError,
    compare_request_contract,
    compute_design_fingerprint,
    create_shared_data_store,
    normalize_execution,
    replay_work_events,
)


WORK_ID = "123e4567-e89b-42d3-a456-426614174021"
STORAGE_ROOT = "runtime/work-data"
PROTECTED_PATHS = ("sealed-material", "generated-material")


def request(*, execution: dict | None = None) -> dict:
    value = {
        "desired_outcome": "요청한 결과를 검증 가능하게 완료한다.",
        "authorized_actions": ["프로젝트 파일 편집"],
        "excluded_scope": ["외부 게시"],
        "input_refs": ["fixture://neutral"],
        "protection_boundaries": ["선언된 보호 경로"],
        "required_decisions": [],
        "verification_levels": ["unit", "structure"],
    }
    if execution is not None:
        value["execution"] = execution
    return value


class Runtime:
    def __init__(self, root: Path, *, write_enabled: bool = True) -> None:
        self.store = create_shared_data_store(
            root,
            storage_root=STORAGE_ROOT,
            protected_paths=PROTECTED_PATHS,
            write_enabled=write_enabled,
        )
        if write_enabled:
            self.store.initialize()
        self.work = WorkStateService(self.store)

    def create(self, *, value: dict | None = None) -> dict:
        return self.work.create_work(
            value or request(),
            actor="user:test",
            next_action="작업 시작",
            work_id=WORK_ID,
            timestamp=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
        )


class WorkSchemaTests(unittest.TestCase):
    def test_schema_fields_and_enums_match_runtime(self) -> None:
        schemas = ROOT / "experimental/shared_data/schemas"
        request_schema = json.loads((schemas / "work-request-payload-v1.schema.json").read_text(encoding="utf-8"))
        event_schema = json.loads((schemas / "work-event-payload-v1.schema.json").read_text(encoding="utf-8"))
        state_schema = json.loads((schemas / "work-state-payload-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(request_schema["required"]), REQUEST_FIELDS)
        self.assertEqual(set(request_schema["properties"]), REQUEST_FIELDS | {"execution"})
        self.assertEqual(set(request_schema["properties"]["execution"]["required"]), EXECUTION_FIELDS)
        self.assertEqual(set(request_schema["properties"]["execution"]["properties"]["tier"]["enum"]), EXECUTION_TIERS)
        self.assertEqual(set(event_schema["required"]), WORK_EVENT_FIELDS)
        self.assertEqual(set(event_schema["properties"]), WORK_EVENT_FIELDS)
        self.assertEqual(set(event_schema["properties"]["outcome"]["enum"]), EVENT_OUTCOMES)
        self.assertEqual(set(state_schema["required"]), WORK_STATE_FIELDS)
        self.assertEqual(set(state_schema["properties"]), WORK_STATE_FIELDS)
        self.assertEqual(set(ALLOWED_TRANSITIONS["completed"]), set())


class ExecutionContractTests(unittest.TestCase):
    def test_quick_standard_and_controlled_shapes(self) -> None:
        self.assertEqual(
            normalize_execution({"tier": "quick"}),
            {"tier": "quick", "phase_id": None, "design_ref": None, "design_fingerprint": None},
        )
        self.assertEqual(normalize_execution({"tier": "standard"})["tier"], "standard")
        with self.assertRaises(DesignContractError):
            normalize_execution({"tier": "quick", "phase_id": "P1"})
        with self.assertRaises(DesignRequiredError):
            normalize_execution({"tier": "controlled"})

    def test_controlled_design_hash_change_and_boundaries_fail_before_append(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-design-") as raw_root:
            root = Path(raw_root)
            design = root / "plans" / "phase.md"
            design.parent.mkdir()
            design.write_text("phase: ready\n", encoding="utf-8")
            execution = {
                "tier": "controlled",
                "phase_id": "P1",
                "design_ref": "plans/phase.md",
                "design_fingerprint": compute_design_fingerprint(
                    "plans/phase.md", consumer_root=root
                ),
            }
            runtime = Runtime(root)
            created = runtime.create(value=request(execution=execution))
            design.write_text("phase: changed\n", encoding="utf-8")
            before, _ = runtime.store.list_events("work_events")
            with self.assertRaises(DesignInvalidatedError):
                runtime.work.transition(
                    WORK_ID,
                    expected_state_hash=created["content_hash"],
                    actor="agent:test",
                    action="start",
                    outcome="success",
                    to_status="in_progress",
                    next_action="검증",
                )
            after, _ = runtime.store.list_events("work_events")
            self.assertEqual(before, after)
            for ref in ("sealed-material/phase.md", f"{STORAGE_ROOT}/phase.md", "../phase.md"):
                with self.subTest(ref=ref), self.assertRaises(DesignContractError):
                    compute_design_fingerprint(
                        ref,
                        consumer_root=root,
                        protected_paths=PROTECTED_PATHS,
                        storage_root=STORAGE_ROOT,
                    )

    def test_request_change_requires_reapproval(self) -> None:
        previous = request()
        current = request()
        current["desired_outcome"] = "바뀐 결과"
        result = compare_request_contract(previous, current)
        self.assertTrue(result["invalidated"])
        self.assertTrue(result["reapproval_required"])
        self.assertEqual(result["changed_fields"], ["desired_outcome"])


class WorkStateTests(unittest.TestCase):
    def test_default_read_only_store_cannot_initialize_or_create(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-readonly-") as raw_root:
            runtime = Runtime(Path(raw_root), write_enabled=False)
            with self.assertRaises(WriteNotEnabledError):
                runtime.store.initialize()
            with self.assertRaises(Exception):
                runtime.create()

    def test_create_checkpoint_fail_resume_complete_and_rebuild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-flow-") as raw_root:
            runtime = Runtime(Path(raw_root))
            requested = runtime.create()
            started = runtime.work.transition(
                WORK_ID,
                expected_state_hash=requested["content_hash"],
                actor="agent:test",
                action="start",
                outcome="success",
                to_status="in_progress",
                next_action="첫 검증",
                timestamp=datetime(2026, 8, 19, 1, 1, tzinfo=UTC),
            )
            checkpoint = runtime.work.transition(
                WORK_ID,
                expected_state_hash=started["content_hash"],
                actor="agent:test",
                action="checkpoint",
                outcome="success",
                to_status="in_progress",
                completed_items=["첫 검증"],
                next_action="전체 검증",
                evidence_refs=["test://first"],
                timestamp=datetime(2026, 8, 19, 1, 2, tzinfo=UTC),
            )
            failed = runtime.work.transition(
                WORK_ID,
                expected_state_hash=checkpoint["content_hash"],
                actor="agent:test",
                action="validate",
                outcome="failure",
                to_status="failed",
                next_action="보정 후 재개",
                evidence_refs=["failure://neutral"],
                timestamp=datetime(2026, 8, 19, 1, 3, tzinfo=UTC),
            )
            resumed = runtime.work.transition(
                WORK_ID,
                expected_state_hash=failed["content_hash"],
                actor="agent:test",
                action="resume",
                outcome="success",
                to_status="in_progress",
                next_action="전체 검증",
                timestamp=datetime(2026, 8, 19, 1, 4, tzinfo=UTC),
            )
            completed = runtime.work.transition(
                WORK_ID,
                expected_state_hash=resumed["content_hash"],
                actor="agent:test",
                action="complete",
                outcome="success",
                to_status="completed",
                completed_items=["전체 검증"],
                next_action=None,
                evidence_refs=["test://pass"],
                timestamp=datetime(2026, 8, 19, 1, 5, tzinfo=UTC),
            )
            self.assertEqual(completed["payload"]["completed_items"], ["첫 검증", "전체 검증"])
            self.assertEqual(completed["payload"]["evidence_refs"], ["test://first", "failure://neutral", "test://pass"])
            self.assertIsNone(completed["payload"]["next_action"])
            self.assertEqual(runtime.work.rebuild_snapshot(WORK_ID)["payload"], completed["payload"])
            self.assertEqual(runtime.work.list_states(status="completed")[0]["id"], WORK_ID)

    def test_invalid_expected_outcome_blocker_and_completion_do_not_append(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-invalid-") as raw_root:
            runtime = Runtime(Path(raw_root))
            current = runtime.create()
            before, _ = runtime.store.list_events("work_events")
            operations = (
                dict(expected_state_hash="sha256:" + "0" * 64, outcome="success", to_status="in_progress", next_action="검증"),
                dict(expected_state_hash=current["content_hash"], outcome="failure", to_status="in_progress", next_action="검증"),
                dict(expected_state_hash=current["content_hash"], outcome="blocked", to_status="blocked", blockers=[], next_action="대기"),
                dict(expected_state_hash=current["content_hash"], outcome="success", to_status="completed", next_action=None),
            )
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaises((ExpectationMismatchError, InvalidWorkTransition)):
                    runtime.work.transition(
                        WORK_ID,
                        actor="agent:test",
                        action="invalid",
                        **operation,
                    )
            after, _ = runtime.store.list_events("work_events")
            self.assertEqual(before, after)

    def test_rejected_event_records_fact_without_changing_work_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-rejected-") as raw_root:
            runtime = Runtime(Path(raw_root))
            current = runtime.create()
            rejected = runtime.work.transition(
                WORK_ID,
                expected_state_hash=current["content_hash"],
                actor="agent:test",
                action="deny out of scope",
                outcome="rejected",
                to_status=None,
                completed_items=["무시할 완료"],
                blockers=["무시할 blocker"],
                next_action="무시할 행동",
                evidence_refs=["ignored://evidence"],
                timestamp=datetime(2026, 8, 19, 1, 1, tzinfo=UTC),
            )
            for field in ("status", "completed_items", "blockers", "next_action", "evidence_refs"):
                self.assertEqual(rejected["payload"][field], current["payload"][field])
            events, _ = runtime.store.list_events("work_events")
            self.assertEqual(events[-1]["payload"]["outcome"], "rejected")

    def test_projection_failure_preserves_event_blocks_transition_and_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-recovery-") as raw_root:
            runtime = Runtime(Path(raw_root))
            with patch.object(runtime.store, "create_record", side_effect=OSError("snapshot failure")):
                with self.assertRaises(WorkProjectionPending):
                    runtime.create()
            events, _ = runtime.store.list_events("work_events")
            self.assertEqual(len(events), 1)
            with self.assertRaises(Exception):
                runtime.work.transition(
                    WORK_ID,
                    expected_state_hash="sha256:" + "0" * 64,
                    actor="agent:test",
                    action="start",
                    outcome="success",
                    to_status="in_progress",
                    next_action="검증",
                )
            recovered = runtime.work.rebuild_snapshot(WORK_ID)
            self.assertEqual(recovered["payload"]["status"], "requested")

    def test_committed_event_with_failed_projection_requires_rebuild_before_next_transition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-pending-") as raw_root:
            runtime = Runtime(Path(raw_root))
            current = runtime.create()
            original = runtime.work.rebuild_snapshot
            with patch.object(runtime.work, "rebuild_snapshot", side_effect=OSError("projection failure")):
                with self.assertRaises(WorkProjectionPending):
                    runtime.work.transition(
                        WORK_ID,
                        expected_state_hash=current["content_hash"],
                        actor="agent:test",
                        action="start",
                        outcome="success",
                        to_status="in_progress",
                        next_action="검증",
                        timestamp=datetime(2026, 8, 19, 1, 1, tzinfo=UTC),
                    )
            with self.assertRaises(WorkProjectionPending):
                runtime.work.get_state(WORK_ID)
            rebuilt = original(WORK_ID)
            self.assertEqual(rebuilt["payload"]["status"], "in_progress")

    def test_replay_rejects_request_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-work-replay-") as raw_root:
            runtime = Runtime(Path(raw_root))
            current = runtime.create()
            events, stream_hash = runtime.store.list_events("work_events")
            bad = dict(events[0]["payload"])
            bad["action"] = "mutate"
            bad["from_status"] = "requested"
            bad["to_status"] = "in_progress"
            runtime.store.append_event("work_events", bad, expected_stream_hash=stream_hash)
            events, _ = runtime.store.list_events("work_events")
            with self.assertRaises(WorkStateError):
                replay_work_events(events, WORK_ID)
            self.assertEqual(runtime.store.get_record(WORK_ID)["content_hash"], current["content_hash"])


if __name__ == "__main__":
    unittest.main()
