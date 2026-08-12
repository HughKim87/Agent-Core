"""Core 최소 공개 인터페이스.

실제 소비자가 있는 명령만 공개한다. 소비자가 없는 명령은 만들지 않는다.

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
from .integrity import run_all
from .primitives import CheckError

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNUSABLE = 2


def _emit(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def cmd_verify(root: Path) -> int:
    """소비자: 변경 후 통합 검증 게이트."""
    report = run_all(root)
    _emit(report.as_dict())
    return EXIT_OK if report.ok else EXIT_FINDINGS


def cmd_context(root: Path, matched: list[str]) -> int:
    """소비자: 시작 문맥 예산 확인과 재현성 비교."""
    package = build_context(root, matched)
    _emit(package.as_dict())
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="core-check", description="Core 무결성 검사")
    parser.add_argument("--root", default=".", help="검사할 저장소 뿌리")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify", help="모든 필수 검사를 실행한다")
    context = sub.add_parser("context", help="시작 컨텍스트를 구성한다")
    context.add_argument("--rule", action="append", default=[], help="현재 행동에 일치한 규칙")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        _emit({"ok": False, "error": f"뿌리가 없다: {args.root}"})
        return EXIT_UNUSABLE
    try:
        if args.command == "verify":
            return cmd_verify(root)
        if args.command == "context":
            return cmd_context(root, args.rule)
    except CheckError as exc:
        _emit({"ok": False, "error": str(exc), "kind": type(exc).__name__})
        return EXIT_UNUSABLE
    except Exception as exc:  # noqa: BLE001
        # 예상하지 못한 오류도 구조화해서 돌려준다. 검사 도구가 traceback으로 죽으면
        # 호출자는 실패인지 수행 불가인지 구분할 수 없다.
        _emit({"ok": False, "error": str(exc), "kind": type(exc).__name__, "unexpected": True})
        return EXIT_UNUSABLE
    _emit({"ok": False, "error": f"알 수 없는 명령: {args.command}"})
    return EXIT_UNUSABLE


if __name__ == "__main__":
    raise SystemExit(main())
