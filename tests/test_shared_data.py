"""L7 공통 record·저장 기반의 정상·실패·격리 회귀."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from core_check.declarations import declared_compatibility, module_layers  # noqa: E402
from experimental.shared_data import (  # noqa: E402
    EMPTY_STREAM_HASH,
    ConcurrentWriteError,
    ConflictError,
    DataPathError,
    ExpectationMismatchError,
    InputContractError,
    RecordNotFoundError,
    RecordStore,
    RecordValidationError,
    StoreNotInitializedError,
    WriteNotEnabledError,
    build_record,
    decode_record,
    encode_record,
    resolve_consumer_path,
    validate_record,
)
from experimental.shared_data.record import REQUIRED_FIELDS, SCHEMA_VERSION  # noqa: E402


FIRST_ID = "123e4567-e89b-42d3-a456-426614174000"
SECOND_ID = "123e4567-e89b-42d3-a456-426614174001"
MISSING_ID = "123e4567-e89b-42d3-a456-426614174099"
STORAGE_ROOT = Path("runtime") / "agent-data"
PROTECTED_PATHS = ("private-source", "generated-output")


def writable_store(root: Path) -> RecordStore:
    store = RecordStore(
        root,
        storage_root=STORAGE_ROOT,
        protected_paths=PROTECTED_PATHS,
        approved_record_types={"example"},
        approved_streams={"example_events"},
        write_enabled=True,
    )
    store.initialize()
    return store


class RecordContractTests(unittest.TestCase):
    def test_schema_and_runtime_fields_agree(self) -> None:
        schema_path = (
            ROOT
            / "experimental"
            / "shared_data"
            / "schemas"
            / "common-record-v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), REQUIRED_FIELDS)
        self.assertEqual(set(schema["properties"]), REQUIRED_FIELDS)
        self.assertEqual(schema["properties"]["schema_version"]["const"], SCHEMA_VERSION)

    def test_build_encode_decode_round_trip_is_deterministic(self) -> None:
        record = build_record(
            "example",
            {"message": "중립 예제"},
            record_id=FIRST_ID,
            timestamp=datetime(2026, 8, 17, 1, 2, 3, 999, tzinfo=UTC),
        )
        encoded = encode_record(record)
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertEqual(decode_record(encoded), record)
        self.assertEqual(record["created_at"], "2026-08-17T01:02:03Z")
        self.assertEqual(encode_record(decode_record(encoded)), encoded)

    def test_v1_hash_is_compatible_with_the_legacy_neutral_fixture(self) -> None:
        record = build_record(
            "example",
            {"message": "중립 예제"},
            record_id=FIRST_ID,
            timestamp=datetime(2026, 7, 23, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            record["content_hash"],
            "sha256:4533820fa597a429c82eb1b4ab95418cb6bd9f9d380a30091b350ff4cd240360",
        )

    def test_invalid_envelope_and_hash_fail_closed(self) -> None:
        record = build_record("example", {"revision": 1}, record_id=FIRST_ID)
        cases: list[tuple[str, dict, str]] = []

        missing = dict(record)
        missing.pop("payload")
        cases.append(("missing", missing, "missing_field"))

        extra = dict(record)
        extra["unexpected"] = True
        cases.append(("extra", extra, "extra_field"))

        wrong_version = dict(record)
        wrong_version["schema_version"] = 2
        cases.append(("version", wrong_version, "unsupported_version"))

        tampered = dict(record)
        tampered["payload"] = {"revision": 2}
        cases.append(("tampered", tampered, "hash_mismatch"))

        for name, value, code in cases:
            with self.subTest(name=name):
                with self.assertRaises(RecordValidationError) as caught:
                    validate_record(value)
                self.assertEqual(caught.exception.code, code)

    def test_strict_json_boundaries_reject_utf8_bom_nul_duplicate_and_nonfinite(self) -> None:
        cases = (
            (b"\xff", "invalid_utf8"),
            (b"\xef\xbb\xbf{}", "utf8_bom"),
            (b'{"value":"\x00"}', "nul_byte"),
            (b'{"id":1,"id":2}', "duplicate_key"),
            (b'{"value":NaN}', "not_json"),
        )
        for data, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(RecordValidationError) as caught:
                    decode_record(data)
                self.assertEqual(caught.exception.code, code)

    def test_invalid_id_time_payload_and_json_values_fail_closed(self) -> None:
        with self.assertRaises(RecordValidationError) as invalid_id:
            build_record("example", {}, record_id="not-a-uuid")
        self.assertEqual(invalid_id.exception.code, "invalid_id")

        with self.assertRaises(ValueError):
            build_record("example", {}, timestamp=datetime(2026, 8, 17))

        with self.assertRaises(RecordValidationError) as payload_type:
            build_record("example", [])  # type: ignore[arg-type]
        self.assertEqual(payload_type.exception.code, "payload_type")

        with self.assertRaises(RecordValidationError) as nonfinite:
            build_record("example", {"value": float("inf")})
        self.assertEqual(nonfinite.exception.code, "not_json")

        record = build_record("example", {}, record_id=FIRST_ID)
        record["updated_at"] = "2000-01-01T00:00:00Z"
        record["content_hash"] = "sha256:" + "0" * 64
        with self.assertRaises(RecordValidationError) as order:
            validate_record(record)
        self.assertEqual(order.exception.code, "timestamp_order")


class PathBoundaryTests(unittest.TestCase):
    def test_paths_are_relative_normalized_and_inside_consumer_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="공통 데이터 경로 ") as raw_root:
            root = Path(raw_root)
            allowed = resolve_consumer_path(root, "runtime/agent-data/record.json")
            self.assertEqual(allowed, root / "runtime" / "agent-data" / "record.json")
            for candidate in (
                "../escape.json",
                "/absolute.json",
                "C:\\absolute.json",
                "C:drive-relative.json",
                "data/./record.json",
                "data//record.json",
                ".git/config",
            ):
                with self.subTest(candidate=candidate):
                    with self.assertRaises(DataPathError):
                        resolve_consumer_path(root, candidate)

    def test_declared_protected_paths_are_rejected_without_hardcoded_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-protected-") as raw_root:
            root = Path(raw_root)
            with self.assertRaises(DataPathError):
                resolve_consumer_path(
                    root,
                    "private-source/item.json",
                    protected_paths=PROTECTED_PATHS,
                )
            with self.assertRaises(DataPathError):
                resolve_consumer_path(
                    root,
                    "PRIVATE-SOURCE/item.json",
                    protected_paths=PROTECTED_PATHS,
                )

    def test_storage_root_cannot_overlap_a_protected_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-storage-boundary-") as raw_root:
            root = Path(raw_root)
            for storage_root, protected in (
                ("private-source/data", ("private-source",)),
                ("private-source", ("private-source/data",)),
                ("../outside", ()),
                (str(root / "absolute"), ()),
            ):
                with self.subTest(storage_root=storage_root):
                    with self.assertRaises(InputContractError):
                        RecordStore(
                            root,
                            storage_root=storage_root,
                            protected_paths=protected,
                        )


class RecordStoreTests(unittest.TestCase):
    def test_writes_are_disabled_by_default_and_leave_no_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-read-only-") as raw_root:
            root = Path(raw_root)
            store = RecordStore(
                root,
                storage_root=STORAGE_ROOT,
                approved_record_types={"example"},
            )
            with self.assertRaises(WriteNotEnabledError):
                store.initialize()
            with self.assertRaises(WriteNotEnabledError):
                store.create_record("example", {})
            self.assertFalse((root / STORAGE_ROOT).exists())

    def test_initialization_is_explicit_and_scoped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-init-") as raw_root:
            root = Path(raw_root)
            store = RecordStore(
                root,
                storage_root=STORAGE_ROOT,
                approved_record_types={"example"},
                approved_streams={"example_events"},
                write_enabled=True,
            )
            with self.assertRaises(StoreNotInitializedError):
                store.list_records("example")
            self.assertEqual(
                store.initialize(),
                {
                    "records": "runtime/agent-data/records",
                    "events": "runtime/agent-data/events",
                },
            )
            self.assertTrue((root / STORAGE_ROOT / "records").is_dir())
            self.assertTrue((root / STORAGE_ROOT / "events").is_dir())

    def test_create_get_list_and_expected_update(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-record-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            created = store.create_record(
                "example",
                {"revision": 1},
                record_id=FIRST_ID,
                timestamp=datetime(2026, 8, 17, 1, 0, tzinfo=UTC),
            )
            self.assertEqual(store.get_record(FIRST_ID), created)
            self.assertEqual(store.list_records("example"), [created])
            record_path = root / STORAGE_ROOT / "records" / f"{FIRST_ID}.json"
            before = record_path.read_bytes()
            with self.assertRaises(ExpectationMismatchError):
                store.update_record(
                    FIRST_ID,
                    {"revision": 2},
                    expected_content_hash="sha256:" + "0" * 64,
                )
            self.assertEqual(record_path.read_bytes(), before)
            updated = store.update_record(
                FIRST_ID,
                {"revision": 2},
                expected_content_hash=created["content_hash"],
                timestamp=datetime(2026, 8, 17, 1, 1, tzinfo=UTC),
            )
            self.assertEqual(updated["created_at"], created["created_at"])
            self.assertEqual(updated["updated_at"], "2026-08-17T01:01:00Z")
            self.assertNotEqual(updated["content_hash"], created["content_hash"])
            self.assertEqual(store.get_record(FIRST_ID), updated)

    def test_duplicate_missing_unapproved_and_corrupt_records_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-errors-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            store.create_record("example", {}, record_id=FIRST_ID)
            with self.assertRaises(ConflictError):
                store.create_record("example", {}, record_id=FIRST_ID)
            with self.assertRaises(RecordNotFoundError):
                store.get_record(MISSING_ID)
            with self.assertRaises(InputContractError):
                store.create_record("future_type", {})

            corrupt = root / STORAGE_ROOT / "records" / f"{SECOND_ID}.json"
            corrupt.write_bytes(b"{}\n")
            with self.assertRaises(RecordValidationError):
                store.list_records("example")

    def test_existing_lock_reports_concurrent_write_without_removing_foreign_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-lock-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            lock = root / STORAGE_ROOT / "records" / f".{FIRST_ID}.json.lock"
            lock.write_text("pid=external\n", encoding="ascii")
            with self.assertRaises(ConcurrentWriteError):
                store.create_record("example", {}, record_id=FIRST_ID)
            self.assertEqual(lock.read_text(encoding="ascii"), "pid=external\n")

    def test_append_list_hash_and_expected_stream_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-events-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            events, initial_hash = store.list_events("example_events")
            self.assertEqual(events, [])
            self.assertEqual(initial_hash, EMPTY_STREAM_HASH)
            first = store.append_event(
                "example_events",
                {"sequence": 1},
                expected_stream_hash=initial_hash,
                event_id=FIRST_ID,
                timestamp=datetime(2026, 8, 17, 2, 0, tzinfo=UTC),
            )
            stream_path = root / STORAGE_ROOT / "events" / "example_events.jsonl"
            before = stream_path.read_bytes()
            with self.assertRaises(ExpectationMismatchError):
                store.append_event(
                    "example_events",
                    {"sequence": 2},
                    expected_stream_hash=EMPTY_STREAM_HASH,
                    event_id=SECOND_ID,
                )
            self.assertEqual(stream_path.read_bytes(), before)
            second = store.append_event(
                "example_events",
                {"sequence": 2},
                expected_stream_hash=first["stream_hash"],
                event_id=SECOND_ID,
                timestamp=datetime(2026, 8, 17, 2, 1, tzinfo=UTC),
            )
            events, final_hash = store.list_events("example_events")
            self.assertEqual([event["payload"]["sequence"] for event in events], [1, 2])
            self.assertEqual(second["count"], 2)
            self.assertEqual(second["stream_hash"], final_hash)
            self.assertTrue(stream_path.read_bytes().endswith(b"\n"))

    def test_stream_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-corrupt-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            stream = root / STORAGE_ROOT / "events" / "example_events.jsonl"
            stream.write_bytes(b'{"partial":true}')
            with self.assertRaises(RecordValidationError) as caught:
                store.list_events("example_events")
            self.assertEqual(caught.exception.code, "partial_jsonl")

    def test_record_replace_failure_preserves_original_and_cleans_owned_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-record-failure-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            original = store.create_record("example", {"revision": 1}, record_id=FIRST_ID)
            target = root / STORAGE_ROOT / "records" / f"{FIRST_ID}.json"
            before = target.read_bytes()
            with patch(
                "experimental.shared_data.store.os.replace",
                side_effect=OSError("simulated record replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated record replace failure"):
                    store.update_record(
                        FIRST_ID,
                        {"revision": 2},
                        expected_content_hash=original["content_hash"],
                    )
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(target.parent.glob("*.tmp")), [])
            self.assertEqual(list(target.parent.glob("*.lock")), [])

    def test_stream_replace_failure_preserves_original_and_cleans_owned_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-stream-failure-") as raw_root:
            root = Path(raw_root)
            store = writable_store(root)
            first = store.append_event("example_events", {"sequence": 1}, event_id=FIRST_ID)
            target = root / STORAGE_ROOT / "events" / "example_events.jsonl"
            before = target.read_bytes()
            with patch(
                "experimental.shared_data.store.os.replace",
                side_effect=OSError("simulated stream replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated stream replace failure"):
                    store.append_event(
                        "example_events",
                        {"sequence": 2},
                        expected_stream_hash=first["stream_hash"],
                        event_id=SECOND_ID,
                    )
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(target.parent.glob("*.tmp")), [])
            self.assertEqual(list(target.parent.glob("*.lock")), [])

    def test_delete_and_move_are_not_part_of_the_surface(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-surface-") as raw_root:
            store = writable_store(Path(raw_root))
            self.assertFalse(hasattr(store, "delete_record"))
            self.assertFalse(hasattr(store, "move_record"))


class IsolationTests(unittest.TestCase):
    def test_every_l7_python_module_is_declared_in_architecture(self) -> None:
        actual = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "experimental").rglob("*.py")
        }
        self.assertEqual(set(module_layers(ROOT)["L7"]), actual)

    def test_core_check_does_not_import_experimental_runtime(self) -> None:
        for path in sorted((ROOT / "src" / "core_check").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(
                any(name == "experimental" or name.startswith("experimental.") for name in imported),
                path.name,
            )

    def test_implementation_has_no_project_domain_or_hardcoded_protected_paths(self) -> None:
        implementation = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "experimental" / "shared_data").glob("*.py"))
        ).casefold()
        for forbidden in (
            "youtube",
            "video",
            "game",
            "extension/data",
            '"inputs"',
            '"outputs"',
            '".obsidian"',
            '"backup"',
        ):
            self.assertNotIn(forbidden, implementation)

    def test_l7_runtime_uses_only_standard_library_and_its_relative_modules(self) -> None:
        standard = set(sys.stdlib_module_names)
        for path in sorted((ROOT / "experimental" / "shared_data").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split(".")[0], standard, path.name)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    self.assertIn(node.module.split(".")[0], standard, path.name)

    def test_private_implementation_is_not_published_as_optional_capability(self) -> None:
        self.assertEqual(declared_compatibility(ROOT)["optional_capabilities"], {})


if __name__ == "__main__":
    unittest.main()
