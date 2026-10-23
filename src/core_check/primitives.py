"""L6 기반 원시.

이 모듈은 내부의 어떤 모듈도 import하지 않는다. 순수해야 한다.
계층 검사 A2가 이 성질을 강제한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path


WARNING_REVIEW_GUIDANCE = (
    "경고의 원문을 요청 조건·승인·제약과 대조한다. 충분한 내용은 유지하고 진행하며, "
    "실제 결함은 기존 승인 안에서 보완한 뒤 영향받은 내용·검사를 재확인한다. "
    "경고 자체로 재승인·전체 중단을 요구하지 않고, 승인 경계나 중요한 불확실성이 "
    "남은 행동·완료 주장만 보류한다. 이 안내는 의미 검토의 실행·통과 증거가 아니다."
)


class CheckError(Exception):
    """검사 수행 자체가 불가능한 상태."""


class UnsafePathError(CheckError):
    """선언된 뿌리 밖을 가리키는 경로."""


@dataclass(frozen=True)
class Finding:
    """하나의 확정 오류 또는 검토 진단."""

    check: str
    path: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "check": self.check,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class Report:
    """한 번의 검사 실행 결과."""

    findings: list[Finding] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "ran": sorted(self.ran),
            "skipped": dict(sorted(self.skipped.items())),
            "findings": [f.as_dict() for f in self.findings],
            "error_count": sum(f.severity == "error" for f in self.findings),
            "warning_count": sum(f.severity == "warning" for f in self.findings),
            "assessment_scope": "structure-and-diagnostics",
            "semantic_review": "not_assessed",
            "review_guidance": WARNING_REVIEW_GUIDANCE if any(
                f.severity == "warning" for f in self.findings
            ) else None,
        }


def resolve_inside(root: Path, candidate: str | Path) -> Path:
    """`root` 안쪽으로만 해석되는 절대 경로를 돌려준다."""
    root = root.resolve()
    target = (root / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    if root != target and root not in target.parents:
        raise UnsafePathError(f"{candidate} 는 선언된 뿌리 밖이다")
    return target


def fingerprint(text: str) -> str:
    """같은 입력에 항상 같은 값을 주는 결정론적 지문."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
