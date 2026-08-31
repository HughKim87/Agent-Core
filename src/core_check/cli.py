"""Agent Core 공개 CLI 계약 v2.

종료 상태
    0  모든 필수 검사 통과
    1  하나 이상의 필수 검사 실패
    2  검사 수행 자체가 불가능
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .context import build as build_context
from .declarations import consumer_contract, declared_compatibility
from .gate import (
    HostCoreBaseline,
    capture_host_core_baseline,
    host_core_baseline_status,
    run as run_gate,
)
from .integrity import host_core_cleanliness, run_all, run_consumer
from .primitives import CheckError, Report

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNUSABLE = 2


def _emit(payload: dict[str, object]) -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _version(core_root: Path) -> int:
    value = declared_compatibility(core_root).get("contract_version")
    if not isinstance(value, int):
        raise CheckError("contract_version이 정수가 아니다")
    return value


def _merge(core: Report, consumer: Report) -> Report:
    merged = Report()
    merged.ran.extend(f"core:{name}" for name in core.ran)
    merged.ran.extend(f"consumer:{name}" for name in consumer.ran)
    merged.findings.extend(core.findings)
    merged.findings.extend(consumer.findings)
    merged.skipped.update({f"core:{key}": value for key, value in core.skipped.items()})
    merged.skipped.update({f"consumer:{key}": value for key, value in consumer.skipped.items()})
    return merged


def _host_core_baseline(
    core_root: Path, consumer_root: Path | None, *, require_clean: bool
) -> HostCoreBaseline | None:
    if consumer_root is None:
        return None
    contract = consumer_contract(core_root, consumer_root)
    if contract["consumer_role"] != "host":
        return None
    clean, detail = host_core_cleanliness(core_root)
    if require_clean and not clean:
        raise CheckError(f"Host Core 읽기 전용 사전 검사 실패: {detail}")
    return capture_host_core_baseline(core_root, require_clean=require_clean)


def _require_host_core_unchanged(
    core_root: Path, baseline: HostCoreBaseline | None
) -> None:
    if baseline is None:
        return
    unchanged, detail = host_core_baseline_status(core_root, baseline)
    if not unchanged:
        raise CheckError(f"Host 공개 인터페이스 실행 중 {detail}")


def cmd_verify(core_root: Path, consumer_root: Path | None = None) -> int:
    """소비자: Core 자체 또는 Core와 소비 계약의 구조 위반을 확인한다."""
    baseline = _host_core_baseline(core_root, consumer_root, require_clean=False)
    try:
        report = run_all(core_root)
        scope = "core"
        if consumer_root is not None:
            report = _merge(report, run_consumer(core_root, consumer_root))
            scope = "core+consumer"
    finally:
        _require_host_core_unchanged(core_root, baseline)
    payload = report.as_dict()
    payload.update({"contract_version": _version(core_root), "scope": scope})
    _emit(payload)
    return EXIT_OK if report.ok else EXIT_FINDINGS


def cmd_context(core_root: Path, consumer_root: Path, matched: list[str]) -> int:
    """소비자: scope가 있는 시작 문맥을 구성하고 재현성 지문을 반환한다."""
    baseline = _host_core_baseline(core_root, consumer_root, require_clean=True)
    try:
        package = build_context(core_root, consumer_root, matched)
    finally:
        _require_host_core_unchanged(core_root, baseline)
    payload = package.as_dict()
    payload["contract_version"] = _version(core_root)
    _emit(payload)
    return EXIT_OK


def cmd_gate(core_root: Path, consumer_root: Path | None = None) -> int:
    """소비자: Core 변경 또는 소비 연결의 통합 검증 관문을 실행한다."""
    result = run_gate(core_root, consumer_root)
    _emit(result.as_dict())
    return EXIT_OK if result.ok else EXIT_FINDINGS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="core-check", description="Agent Core 계약 검사")
    parser.add_argument("--core-root", help="검사할 Core 저장소 뿌리")
    parser.add_argument("--consumer-root", help="Maintainer 또는 Host 저장소 뿌리")
    parser.add_argument("--root", dest="legacy_root", help="deprecated: --core-root의 v2 별칭")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify", help="지정된 범위의 무결성을 검사한다")
    sub.add_parser("gate", help="통합 검증 게이트를 실행한다")
    context = sub.add_parser("context", help="소비 저장소 시작 컨텍스트를 구성한다")
    context.add_argument(
        "--rule", action="append", default=[], help="core: 또는 consumer: scope가 있는 규칙 ID"
    )
    return parser


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.core_root and args.legacy_root:
        _emit({"ok": False, "error": "--core-root와 deprecated --root를 함께 쓸 수 없다"})
        return EXIT_UNUSABLE

    core_root = Path(args.core_root or args.legacy_root).resolve() if (args.core_root or args.legacy_root) else _package_root()
    consumer_root = Path(args.consumer_root).resolve() if args.consumer_root else None
    if not core_root.is_dir():
        _emit({"ok": False, "error": f"Core 뿌리가 없다: {args.core_root or args.legacy_root}"})
        return EXIT_UNUSABLE
    if consumer_root is not None and not consumer_root.is_dir():
        _emit({"ok": False, "error": f"소비 저장소 뿌리가 없다: {args.consumer_root}"})
        return EXIT_UNUSABLE

    try:
        if args.command == "verify":
            return cmd_verify(core_root, consumer_root)
        if args.command == "gate":
            return cmd_gate(core_root, consumer_root)
        if args.command == "context":
            if consumer_root is None:
                raise CheckError("context 명령에는 --consumer-root가 필요하다")
            return cmd_context(core_root, consumer_root, args.rule)
    except CheckError as exc:
        _emit({"ok": False, "error": str(exc), "kind": type(exc).__name__})
        return EXIT_UNUSABLE
    except Exception as exc:  # noqa: BLE001
        _emit({"ok": False, "error": str(exc), "kind": type(exc).__name__, "unexpected": True})
        return EXIT_UNUSABLE
    _emit({"ok": False, "error": f"알 수 없는 명령: {args.command}"})
    return EXIT_UNUSABLE


if __name__ == "__main__":
    raise SystemExit(main())
