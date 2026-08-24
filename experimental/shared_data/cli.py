"""공개 선택 기능 ``shared_data`` v1의 JSON stdin/stdout CLI."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
UTC = timezone.utc
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from .context import EvidenceContextService, validate_context_package
from .execution import compare_request_contract, compute_design_fingerprint
from .knowledge import KnowledgeService
from .lifecycle import LifecycleService
from .record import DataPathError, RecordValidationError
from .store import RecordIOError
from .work_state import WorkStateService
from . import create_shared_data_store


CAPABILITY_ID = "shared_data"
CAPABILITY_VERSION = 1
MAX_REQUEST_BYTES = 1_048_576
OPERATIONS = (
    "initialize",
    "source.create", "source.get", "source.list", "source.verify",
    "knowledge.create", "knowledge.get", "knowledge.list",
    "decision.create", "decision.get", "decision.list",
    "lifecycle.register", "lifecycle.transition", "lifecycle.get", "lifecycle.list",
    "lifecycle.current", "lifecycle.history", "lifecycle.rebuild",
    "lifecycle.register_existing", "lifecycle.audit",
    "context.build", "context.validate",
    "work.create", "work.get", "work.list", "work.transition", "work.rebuild",
    "execution.fingerprint", "request.compare",
)


class SharedDataCliError(ValueError):
    kind = "shared_data_cli_error"


def _emit(payload: Mapping[str, Any]) -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    json.dump(dict(payload), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SharedDataCliError(f"요청에 중복 JSON key가 있다: {key}")
        result[key] = value
    return result


def _read_request() -> tuple[str, dict[str, Any]]:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise SharedDataCliError(f"요청은 {MAX_REQUEST_BYTES} bytes 이하여야 한다")
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise SharedDataCliError("요청은 BOM·NUL 없는 strict UTF-8이어야 한다")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise SharedDataCliError("요청이 strict UTF-8이 아니다") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                SharedDataCliError(f"요청에 비유한 숫자가 있다: {item}")
            ),
        )
    except SharedDataCliError:
        raise
    except json.JSONDecodeError as exc:
        raise SharedDataCliError("요청이 유효한 JSON이 아니다") from exc
    if not isinstance(value, dict) or set(value) != {"operation", "arguments"}:
        raise SharedDataCliError("요청은 operation과 arguments만 가진 object여야 한다")
    operation = value["operation"]
    arguments = value["arguments"]
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise SharedDataCliError(f"지원하지 않는 operation: {operation}")
    if not isinstance(arguments, dict):
        raise SharedDataCliError("arguments는 object여야 한다")
    return operation, arguments


def _arguments(
    value: Mapping[str, Any], *, required: set[str] = set(), optional: set[str] = set()
) -> dict[str, Any]:
    fields = set(value)
    if not required.issubset(fields) or fields - (required | optional):
        raise SharedDataCliError(
            f"arguments field가 정확하지 않다: required={sorted(required)}, optional={sorted(optional)}"
        )
    return dict(value)


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SharedDataCliError("timestamp는 null 또는 UTC RFC3339 문자열이어야 한다")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise SharedDataCliError("timestamp는 초 정밀도 UTC RFC3339여야 한다") from exc
    return parsed


class Dispatcher:
    def __init__(
        self,
        *,
        consumer_root: Path,
        storage_root: str,
        protected_paths: list[str],
        write_enabled: bool,
    ) -> None:
        self.store = create_shared_data_store(
            consumer_root,
            storage_root=storage_root,
            protected_paths=protected_paths,
            write_enabled=write_enabled,
        )
        self.knowledge = KnowledgeService(self.store)
        self.lifecycle = LifecycleService(self.knowledge)
        self.context = EvidenceContextService(self.lifecycle)
        self.work = WorkStateService(self.store)

    def dispatch(self, operation: str, raw: Mapping[str, Any]) -> Any:
        handler_name = "_" + operation.replace(".", "_")
        handler: Callable[[Mapping[str, Any]], Any] | None = getattr(self, handler_name, None)
        if handler is None:
            raise SharedDataCliError(f"구현되지 않은 operation: {operation}")
        return handler(raw)

    def _initialize(self, raw: Mapping[str, Any]) -> Any:
        _arguments(raw)
        return self.store.initialize()

    def _source_create(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"source_kind", "locator", "evidence_role"},
            optional={"verification_status", "version_or_hash", "record_id", "timestamp"},
        )
        values["timestamp"] = _timestamp(values.get("timestamp"))
        return self.knowledge.create_source(**values)

    def _source_get(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"record_id"}, optional={"verify_local"})
        return self.knowledge.get_source(
            values["record_id"], verify_local=values.get("verify_local", False)
        )

    def _source_list(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, optional={"verify_local"})
        return self.knowledge.list_sources(verify_local=values.get("verify_local", False))

    def _source_verify(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"record_id"})
        return self.knowledge.verify_source(values["record_id"])

    def _knowledge_create(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"statement", "classification", "scope", "source_ids", "verification_status"},
            optional={"verified_by", "record_id", "timestamp"},
        )
        values["timestamp"] = _timestamp(values.get("timestamp"))
        return self.knowledge.create_knowledge(**values)

    def _knowledge_get(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"record_id"})
        return self.knowledge.get_knowledge(values["record_id"])

    def _knowledge_list(self, raw: Mapping[str, Any]) -> Any:
        _arguments(raw)
        return self.knowledge.list_knowledge()

    def _decision_create(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"payload"}, optional={"record_id", "timestamp"})
        return self.knowledge.create_decision(
            values["payload"],
            record_id=values.get("record_id"),
            timestamp=_timestamp(values.get("timestamp")),
        )

    def _decision_get(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"record_id"})
        return self.knowledge.get_decision(values["record_id"])

    def _decision_list(self, raw: Mapping[str, Any]) -> Any:
        _arguments(raw)
        return self.knowledge.list_decisions()

    def _lifecycle_register(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"target_id", "initial_state", "actor", "approval_kind", "reason"},
            optional={"source_ids", "decision_id", "timestamp"},
        )
        return self.lifecycle.register(
            values.pop("target_id"),
            source_ids=values.pop("source_ids", []),
            timestamp=_timestamp(values.pop("timestamp", None)),
            **values,
        )

    def _lifecycle_transition(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"target_id", "expected_state_hash", "action", "actor", "approval_kind", "reason"},
            optional={"source_ids", "related_target_ids", "replacement_id", "decision_id", "timestamp"},
        )
        target_id = values.pop("target_id")
        values["timestamp"] = _timestamp(values.get("timestamp"))
        return self.lifecycle.transition(target_id, **values)

    def _lifecycle_get(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"target_id"})
        return self.lifecycle.get_record(values["target_id"])

    def _lifecycle_list(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, optional={"state", "target_type"})
        return self.lifecycle.list_states(**values)

    def _lifecycle_current(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, optional={"target_type"})
        return self.lifecycle.current_records(**values)

    def _lifecycle_history(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"target_id"})
        return self.lifecycle.history(values["target_id"])

    def _lifecycle_rebuild(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"target_id"}, optional={"expected_last_event_id"})
        return self.lifecycle.rebuild_snapshot(
            values["target_id"], expected_last_event_id=values.get("expected_last_event_id")
        )

    def _lifecycle_register_existing(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"actor", "approval_kind"})
        return self.lifecycle.register_existing(**values)

    def _lifecycle_audit(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"actor"})
        return self.lifecycle.audit(**values)

    def _context_build(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"purpose"},
            optional={
                "documents", "record_ids", "candidate_documents", "search", "filters",
                "max_characters",
            },
        )
        return self.context.build(**values)

    def _context_validate(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"package"})
        validate_context_package(values["package"])
        return {"valid": True}

    def _work_create(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"request", "actor", "next_action"},
            optional={"work_id", "timestamp"},
        )
        values["timestamp"] = _timestamp(values.get("timestamp"))
        return self.work.create_work(**values)

    def _work_get(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"work_id"})
        return self.work.get_state(values["work_id"])

    def _work_list(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, optional={"status"})
        return self.work.list_states(**values)

    def _work_transition(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(
            raw,
            required={"work_id", "expected_state_hash", "actor", "action", "outcome", "to_status"},
            optional={
                "completed_items", "blockers", "next_action", "related_record_ids",
                "evidence_refs", "timestamp",
            },
        )
        work_id = values.pop("work_id")
        values["timestamp"] = _timestamp(values.get("timestamp"))
        return self.work.transition(work_id, **values)

    def _work_rebuild(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"work_id"}, optional={"expected_last_event_id"})
        return self.work.rebuild_snapshot(
            values["work_id"], expected_last_event_id=values.get("expected_last_event_id")
        )

    def _execution_fingerprint(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"design_ref"})
        return {
            "design_ref": values["design_ref"],
            "fingerprint": compute_design_fingerprint(
                values["design_ref"],
                consumer_root=self.store.root,
                protected_paths=self.store.protected_paths,
                storage_root=self.store.storage_root,
            ),
        }

    def _request_compare(self, raw: Mapping[str, Any]) -> Any:
        values = _arguments(raw, required={"previous", "current"})
        return compare_request_contract(values["previous"], values["current"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-core-shared-data")
    parser.add_argument("--consumer-root")
    parser.add_argument("--storage-root")
    parser.add_argument("--protected-path", action="append", default=[])
    parser.add_argument("--write", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="capability·operation·schema 정보를 출력한다")
    sub.add_parser("invoke", help="stdin의 JSON 요청 하나를 실행한다")
    return parser


def _info() -> dict[str, Any]:
    return {
        "ok": True,
        "capability": CAPABILITY_ID,
        "capability_version": CAPABILITY_VERSION,
        "commands": ["info", "invoke"],
        "operations": list(OPERATIONS),
        "request_schema": "experimental/shared_data/schemas/shared-data-request-v1.schema.json",
        "result_schema": "experimental/shared_data/schemas/shared-data-result-v1.schema.json",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "info":
        _emit(_info())
        return 0
    operation: str | None = None
    try:
        if not args.consumer_root or not args.storage_root:
            raise SharedDataCliError("invoke에는 --consumer-root와 --storage-root가 필요하다")
        operation, arguments = _read_request()
        dispatcher = Dispatcher(
            consumer_root=Path(args.consumer_root),
            storage_root=args.storage_root,
            protected_paths=args.protected_path,
            write_enabled=args.write,
        )
        result = dispatcher.dispatch(operation, arguments)
        _emit(
            {
                "ok": True,
                "capability": CAPABILITY_ID,
                "capability_version": CAPABILITY_VERSION,
                "operation": operation,
                "result": result,
            }
        )
        return 0
    except (RecordIOError, RecordValidationError, DataPathError, SharedDataCliError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "capability": CAPABILITY_ID,
                "capability_version": CAPABILITY_VERSION,
                "operation": operation,
                "error": str(exc),
                "kind": getattr(exc, "kind", type(exc).__name__),
                "recoverable": bool(getattr(exc, "recoverable", False)),
            }
        )
        return 1
    except Exception as exc:  # noqa: BLE001
        _emit(
            {
                "ok": False,
                "capability": CAPABILITY_ID,
                "capability_version": CAPABILITY_VERSION,
                "operation": operation,
                "error": str(exc),
                "kind": type(exc).__name__,
                "unexpected": True,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
