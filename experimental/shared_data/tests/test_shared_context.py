"""L7 Evidence Context의 직접 선택·검색 경계·결정론 회귀."""

from __future__ import annotations

from datetime import datetime, timezone
UTC = timezone.utc
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experimental.shared_data import (  # noqa: E402
    EvidenceContextError,
    EvidenceContextLimitError,
    EvidenceContextService,
    KnowledgeService,
    LifecycleService,
    PACKAGE_FIELDS,
    PACKAGE_VERSION,
    create_knowledge_store,
    validate_context_package,
)


STORAGE_ROOT = "runtime/evidence"
PROTECTED_PATHS = ("sealed-material", "generated-material")


def block(key: str, statement: str, *, status: str = "current") -> str:
    value = {
        "key": key,
        "kind": "knowledge",
        "status": status,
        "source_refs": ["request://context-test"],
        "payload": {
            "statement": statement,
            "classification": "fact",
            "scope": "shared-context",
            "verification_status": "verified",
        },
    }
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return (
        f"<!-- project-data:v1 kind=knowledge key={key} -->\n"
        f"```json\n{rendered}\n```\n<!-- /project-data -->\n"
    )


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
        self.context = EvidenceContextService(self.lifecycle)

    def record(self, *, current: bool, statement: str) -> dict:
        source = self.knowledge.create_source(
            source_kind="user_statement",
            locator=f"request://context/{uuid4()}",
            evidence_role="primary",
            verification_status="verified",
            record_id=str(uuid4()),
            timestamp=datetime(2026, 8, 18, tzinfo=UTC),
        )
        knowledge = self.knowledge.create_knowledge(
            statement=statement,
            classification="fact",
            scope="shared-context",
            source_ids=[source["id"]],
            verification_status="verified",
            verified_by="agent:test",
            record_id=str(uuid4()),
            timestamp=datetime(2026, 8, 18, 0, 1, tzinfo=UTC),
        )
        self.lifecycle.register(
            source["id"],
            initial_state="current",
            actor="agent:test",
            approval_kind="standing_policy",
            reason="테스트 source",
            timestamp=datetime(2026, 8, 18, 0, 2, tzinfo=UTC),
        )
        self.lifecycle.register(
            knowledge["id"],
            initial_state="current" if current else "candidate",
            actor="agent:test",
            approval_kind="standing_policy" if current else "agent_in_scope",
            reason="테스트 knowledge",
            timestamp=datetime(2026, 8, 18, 0, 3, tzinfo=UTC),
        )
        return knowledge


class EvidenceContextTests(unittest.TestCase):
    def test_schema_fields_and_runtime_fields_agree(self) -> None:
        schema = json.loads(
            (ROOT / "experimental/shared_data/schemas/context-package-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(schema["required"]), PACKAGE_FIELDS)
        self.assertEqual(set(schema["properties"]), PACKAGE_FIELDS)
        self.assertEqual(schema["properties"]["package_version"]["const"], PACKAGE_VERSION)

    def test_direct_document_and_data_key_are_deterministic_and_nonpersistent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-context-direct-") as raw_root:
            root = Path(raw_root)
            document = root / "notes" / "evidence.md"
            document.parent.mkdir()
            document.write_text("# Evidence\n\n" + block("stable-fact", "검증된 사실이다."), encoding="utf-8")
            runtime = Runtime(root)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            request = {
                "purpose": "직접 근거 선택",
                "documents": [
                    {"ref": "notes/evidence.md"},
                    {"ref": "notes/evidence.md", "data_key": "stable-fact"},
                ],
            }
            first = runtime.context.build(**request)
            second = runtime.context.build(**request)
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(first, second)
            self.assertEqual(first["fingerprint"], second["fingerprint"])
            self.assertEqual({item["kind"] for item in first["selected"]}, {"document", "document_data"})
            validate_context_package(first)
            self.assertEqual(before, after)

    def test_current_record_is_selected_and_candidate_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-context-record-") as raw_root:
            runtime = Runtime(Path(raw_root))
            current = runtime.record(current=True, statement="현재 선택할 지식이다.")
            candidate = runtime.record(current=False, statement="아직 후보인 지식이다.")
            package = runtime.context.build(
                purpose="현재 지식 선택", record_ids=[candidate["id"], current["id"]]
            )
            self.assertEqual([item["record_id"] for item in package["selected"]], [current["id"]])
            self.assertEqual(package["excluded"], [{
                "kind": "record", "ref": f"record:{candidate['id']}", "reason": "not_current"
            }])

    def test_search_uses_only_explicit_document_catalog_and_current_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-context-search-") as raw_root:
            root = Path(raw_root)
            docs = root / "notes"
            docs.mkdir()
            (docs / "listed.md").write_text(block("listed-fact", "needle listed"), encoding="utf-8")
            (docs / "unlisted.md").write_text(block("hidden-fact", "needle unlisted"), encoding="utf-8")
            runtime = Runtime(root)
            current = runtime.record(current=True, statement="needle record")
            runtime.record(current=False, statement="needle candidate")
            package = runtime.context.build(
                purpose="명시 후보 검색",
                candidate_documents=["notes/listed.md"],
                search="needle",
                filters={"scope": "shared-context"},
            )
            refs = {item["ref"] for item in package["selected"]}
            self.assertIn("notes/listed.md", refs)
            self.assertIn(f"record:{current['id']}", refs)
            self.assertNotIn("notes/unlisted.md", refs)
            self.assertFalse(any("candidate" in item["content"] for item in package["selected"]))

    def test_direct_limit_fails_and_optional_candidate_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-context-limit-") as raw_root:
            root = Path(raw_root)
            (root / "large.md").write_text("x" * 20, encoding="utf-8")
            runtime = Runtime(root)
            with self.assertRaises(EvidenceContextLimitError):
                runtime.context.build(
                    purpose="예산 실패", documents=[{"ref": "large.md"}], max_characters=10
                )
            current = runtime.record(current=True, statement="budget candidate")
            package = runtime.context.build(
                purpose="선택 후보 제외", search="budget", max_characters=1
            )
            self.assertEqual(package["selected"], [])
            self.assertEqual(package["excluded"][0]["ref"], f"record:{current['id']}")
            self.assertEqual(package["excluded"][0]["reason"], "size_limit")

    def test_protected_storage_invalid_encoding_and_malformed_blocks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-context-boundary-") as raw_root:
            root = Path(raw_root)
            runtime = Runtime(root)
            for ref in ("sealed-material/item.md", f"{STORAGE_ROOT}/item.md", "../escape.md"):
                with self.subTest(ref=ref), self.assertRaises(EvidenceContextError):
                    runtime.context.build(purpose="경계", documents=[{"ref": ref}])
            (root / "invalid.md").write_bytes(b"\xff")
            with self.assertRaises(EvidenceContextError):
                runtime.context.build(purpose="인코딩", documents=[{"ref": "invalid.md"}])
            (root / "malformed.md").write_text(
                "<!-- project-data:v1 kind=knowledge key=bad -->\n{}\n", encoding="utf-8"
            )
            with self.assertRaises(EvidenceContextError):
                runtime.context.build(
                    purpose="잘못된 block",
                    documents=[{"ref": "malformed.md", "data_key": "bad"}],
                )

    def test_fingerprint_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-context-fingerprint-") as raw_root:
            runtime = Runtime(Path(raw_root))
            package = runtime.context.build(purpose="fingerprint")
            package["purpose"] = "tampered"
            with self.assertRaises(EvidenceContextError):
                validate_context_package(package)


if __name__ == "__main__":
    unittest.main()
