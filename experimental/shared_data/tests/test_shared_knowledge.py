"""L7 source·knowledge·decision 의미와 경계 회귀."""

from __future__ import annotations

from datetime import datetime, timezone
UTC = timezone.utc
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experimental.shared_data import (  # noqa: E402
    DECISION_APPROVAL_KINDS,
    DECISION_FIELDS,
    KNOWLEDGE_CLASSES,
    KNOWLEDGE_FIELDS,
    KNOWLEDGE_VERIFICATION_STATUSES,
    SOURCE_EVIDENCE_ROLES,
    SOURCE_FIELDS,
    SOURCE_KINDS,
    SOURCE_VERIFICATION_STATUSES,
    InputContractError,
    KnowledgeRecordError,
    RecordNotFoundError,
    KnowledgeService,
    SourceIntegrityError,
    create_knowledge_store,
)


SOURCE_ID = "123e4567-e89b-42d3-a456-426614174010"
KNOWLEDGE_ID = "123e4567-e89b-42d3-a456-426614174011"
DECISION_ID = "123e4567-e89b-42d3-a456-426614174012"
STORAGE_ROOT = "runtime/shared-knowledge"
PROTECTED_PATHS = ("private-material", "generated-material")


def service(root: Path, *, write_enabled: bool = True) -> KnowledgeService:
    store = create_knowledge_store(
        root,
        storage_root=STORAGE_ROOT,
        protected_paths=PROTECTED_PATHS,
        write_enabled=write_enabled,
    )
    if write_enabled:
        store.initialize()
    return KnowledgeService(store)


def statement_source(knowledge: KnowledgeService, *, status: str = "observed") -> dict:
    return knowledge.create_source(
        source_kind="user_statement",
        locator="request://shared-knowledge-test",
        evidence_role="primary",
        verification_status=status,
        record_id=SOURCE_ID,
        timestamp=datetime(2026, 8, 17, 1, 0, tzinfo=UTC),
    )


def decision_payload() -> dict:
    return {
        "problem": "현재 후보를 채택할지 결정한다.",
        "requirements": ["근거 보존", "승인 경계 유지"],
        "options": [
            {"label": "adopt", "impact": "현재 항목으로 채택"},
            {"label": "hold", "impact": "후보 상태 유지"},
        ],
        "selected_option": "adopt",
        "rationale": "명시된 요구조건을 모두 만족한다.",
        "impacts": ["현재 목록에 포함"],
        "source_ids": [SOURCE_ID],
        "requires_user_approval": True,
        "approval_kind": "standing_policy",
        "approved_by": "user:test-policy",
        "decided_at": "2026-08-17T01:00:00Z",
    }


class KnowledgeSchemaTests(unittest.TestCase):
    def test_schema_fields_and_enums_match_runtime(self) -> None:
        schemas = ROOT / "experimental" / "shared_data" / "schemas"
        source = json.loads((schemas / "source-payload-v1.schema.json").read_text(encoding="utf-8"))
        knowledge = json.loads((schemas / "knowledge-payload-v1.schema.json").read_text(encoding="utf-8"))
        decision = json.loads((schemas / "decision-payload-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(source["required"]), SOURCE_FIELDS)
        self.assertEqual(set(source["properties"]), SOURCE_FIELDS)
        self.assertEqual(set(source["properties"]["source_kind"]["enum"]), SOURCE_KINDS)
        self.assertEqual(
            set(source["properties"]["verification_status"]["enum"]),
            SOURCE_VERIFICATION_STATUSES,
        )
        self.assertEqual(set(source["properties"]["evidence_role"]["enum"]), SOURCE_EVIDENCE_ROLES)
        self.assertEqual(set(knowledge["required"]), KNOWLEDGE_FIELDS)
        self.assertEqual(set(knowledge["properties"]), KNOWLEDGE_FIELDS)
        self.assertEqual(set(knowledge["properties"]["classification"]["enum"]), KNOWLEDGE_CLASSES)
        self.assertEqual(
            set(knowledge["properties"]["verification_status"]["enum"]),
            KNOWLEDGE_VERIFICATION_STATUSES,
        )
        self.assertEqual(set(decision["required"]), DECISION_FIELDS)
        self.assertEqual(set(decision["properties"]), DECISION_FIELDS)
        self.assertEqual(
            set(decision["properties"]["approval_kind"]["enum"]), DECISION_APPROVAL_KINDS
        )


class SourceTests(unittest.TestCase):
    def test_local_source_create_verify_and_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-source-") as raw_root:
            root = Path(raw_root)
            target = root / "evidence" / "source.md"
            target.parent.mkdir()
            target.write_text("first bytes\n", encoding="utf-8")
            knowledge = service(root)
            created = knowledge.create_source(
                source_kind="local_document",
                locator="evidence/source.md",
                evidence_role="primary",
                record_id=SOURCE_ID,
                timestamp=datetime(2026, 8, 17, 1, 0, tzinfo=UTC),
            )
            self.assertEqual(created["payload"]["verification_status"], "verified")
            self.assertRegex(created["payload"]["version_or_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(knowledge.verify_source(SOURCE_ID)["integrity"], "match")
            target.write_text("second bytes\n", encoding="utf-8")
            self.assertEqual(knowledge.get_source(SOURCE_ID), created)
            with self.assertRaises(SourceIntegrityError):
                knowledge.verify_source(SOURCE_ID)

    def test_protected_storage_and_invalid_nonlocal_locators_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-source-boundary-") as raw_root:
            knowledge = service(Path(raw_root))
            for locator in (
                "private-material/item.md",
                "runtime/shared-knowledge/records/item.json",
                "../outside.md",
            ):
                with self.subTest(locator=locator):
                    with self.assertRaises(KnowledgeRecordError):
                        knowledge.create_source(
                            source_kind="local_document",
                            locator=locator,
                            evidence_role="primary",
                        )
            with self.assertRaises(KnowledgeRecordError):
                knowledge.create_source(
                    source_kind="web_page",
                    locator="file://local",
                    evidence_role="supporting",
                )
            with self.assertRaises(KnowledgeRecordError):
                knowledge.create_source(
                    source_kind="user_statement",
                    locator="raw user text",
                    evidence_role="primary",
                )

    def test_nonlocal_source_does_not_fetch_or_claim_integrity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-source-nonlocal-") as raw_root:
            knowledge = service(Path(raw_root))
            created = statement_source(knowledge)
            self.assertEqual(knowledge.list_sources(), [created])
            self.assertEqual(knowledge.verify_source(created["id"])["integrity"], "not_applicable")


class KnowledgeAndDecisionTests(unittest.TestCase):
    def test_verified_knowledge_create_read_list(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-knowledge-") as raw_root:
            knowledge = service(Path(raw_root))
            statement_source(knowledge)
            created = knowledge.create_knowledge(
                statement="활성 사실은 정확한 owner 하나가 소유한다.",
                classification="constraint",
                scope="정보 소유 구조",
                source_ids=[SOURCE_ID],
                verification_status="verified",
                verified_by="agent:test",
                record_id=KNOWLEDGE_ID,
            )
            self.assertEqual(knowledge.get_knowledge(KNOWLEDGE_ID), created)
            self.assertEqual(knowledge.list_knowledge(), [created])

    def test_invalid_knowledge_shapes_and_references_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-knowledge-invalid-") as raw_root:
            knowledge = service(Path(raw_root))
            statement_source(knowledge)
            cases = (
                ("first\nsecond", "candidate", None, [SOURCE_ID]),
                ("missing source", "candidate", None, []),
                ("missing verifier", "verified", None, [SOURCE_ID]),
                ("candidate overclaim", "candidate", "agent:test", [SOURCE_ID]),
                ("unknown source", "candidate", None, ["123e4567-e89b-42d3-a456-426614174099"]),
            )
            for statement, status, verifier, sources in cases:
                with self.subTest(statement=statement):
                    before = {p.relative_to(raw_root).as_posix(): p.read_bytes()
                              for p in Path(raw_root).rglob("*") if p.is_file()}
                    error = RecordNotFoundError if statement == "unknown source" else KnowledgeRecordError
                    with self.assertRaises(error):
                        knowledge.create_knowledge(
                            statement=statement,
                            classification="fact",
                            scope="neutral",
                            source_ids=sources,
                            verification_status=status,
                            verified_by=verifier,
                        )
                    after = {p.relative_to(raw_root).as_posix(): p.read_bytes()
                             for p in Path(raw_root).rglob("*") if p.is_file()}
                    self.assertEqual(after, before)

    def test_decision_create_and_approval_boundaries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-decision-") as raw_root:
            knowledge = service(Path(raw_root))
            statement_source(knowledge)
            created = knowledge.create_decision(
                decision_payload(),
                record_id=DECISION_ID,
                timestamp=datetime(2026, 8, 17, 1, 1, tzinfo=UTC),
            )
            self.assertEqual(knowledge.get_decision(DECISION_ID), created)
            self.assertEqual(knowledge.list_decisions(), [created])
            cases = []
            bad_selected = decision_payload()
            bad_selected["selected_option"] = "unknown"
            cases.append(bad_selected)
            duplicate = decision_payload()
            duplicate["options"] = [duplicate["options"][0], duplicate["options"][0]]
            cases.append(duplicate)
            bad_approval = decision_payload()
            bad_approval["approval_kind"] = "agent_in_scope"
            cases.append(bad_approval)
            future = decision_payload()
            future["decided_at"] = "2099-01-01T00:00:00Z"
            cases.append(future)
            for payload in cases:
                with self.subTest(payload=payload):
                    with self.assertRaises(KnowledgeRecordError):
                        knowledge.create_decision(
                            payload,
                            timestamp=datetime(2026, 8, 17, 1, 1, tzinfo=UTC),
                        )

    def test_service_requires_explicit_complete_store_allowlist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-allowlist-") as raw_root:
            root = Path(raw_root)
            from experimental.shared_data import RecordStore

            incomplete = RecordStore(
                root,
                storage_root=STORAGE_ROOT,
                approved_record_types={"source"},
            )
            with self.assertRaises(InputContractError):
                KnowledgeService(incomplete)


if __name__ == "__main__":
    unittest.main()
