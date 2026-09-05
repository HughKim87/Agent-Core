"""Core 자체와 선언된 소비 표면의 무결성 검사."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from .declarations import (
    consumer_contract,
    consumer_policy_path,
    consumer_routed_rule_paths,
    core_policy_path,
    declared_compatibility,
    document_roles,
    module_layers,
    optional_capability_installation_state,
    routed_rule_paths,
)
from .primitives import CheckError, Finding, Report, resolve_inside
from .registry import REGISTRY, register

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
AT_REFERENCE = re.compile(r"(?m)^@([^\s]+\.md)\s*$")
DOC_HEADERS = ("- 목적:", "- 읽는 시점:", "- 책임:", "- 상태:", "- 관련 권위:")
STATE_SECTIONS = (
    "## 현재 단계",
    "## 직전 게이트",
    "## 승인 상태",
    "## 차단",
    "## 알려진 위험",
    "## 첫 다음 행동",
)
STATE_BUDGET_CHARS = 3_000
DYNAMIC_NUMBERS = re.compile(
    r"(추적 파일\s*\d+|untracked\s*\d+|ignored\s*\d+|커밋\s*\d+\s*개|"
    r"파일\s*\d+\s*개\s*추적|blob\s*\d+)"
)
STATE_NUMBER = r"(?:`?\d+`?|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)"
STATE_COUNT = rf"{STATE_NUMBER}\s*개"
STATE_FILE_BASE = r"(?<![0-9A-Za-z가-힣_])(?:파일|경로)"
STATE_FILE_TERM = rf"{STATE_FILE_BASE}(?:은|는|이|가|을|를|의|도)?(?![0-9A-Za-z가-힣_])"
STATE_FILE_COUNT_NOUN = rf"{STATE_FILE_BASE}\s*(?:개수|수)(?:은|는|이|가|을|를)?"
STATE_COUNT_END = rf"{STATE_COUNT}(?:다|임|이다|입니다|뿐)?(?=\s*$|\s*[.,;)])"
STATE_FILE_COUNTS = re.compile(
    rf"(?:{STATE_COUNT}(?:의)?\s*{STATE_FILE_BASE}(?:이다|입니다|임)?"
    rf"(?![0-9A-Za-z가-힣_])|{STATE_FILE_TERM}\s*:?\s*(?:총\s*)?{STATE_COUNT}"
    rf"(?:다|임|이다|입니다|뿐)?(?=\s*$|\s*[.,;)])|"
    rf"{STATE_FILE_COUNT_NOUN}\s*:?\s*(?:총\s*)?{STATE_COUNT_END})",
    re.MULTILINE,
)
EPHEMERAL_FAILURE_KOREAN_KEY = re.compile(
    r"(?:실패(?:횟수|건수|카운터|누적)|연속실패|재시도횟수|"
    r"시도(?:(?:한|했던)|해본)?방법|(?:방법(?:의)?|시도)순서|"
    r"중단(?:플래그|여부|상태|유무)|중단됨|"
    r"실패(?:사건)?이력|시도이력|실패시도기록)"
)
EPHEMERAL_FAILURE_ENGLISH_KEY = re.compile(
    r"(?:[a-z0-9]+_)*(?:"
    r"failure_(?:count|counter|total)|retry_(?:count|counter|total)|"
    r"consecutive_failures|(?:failed|failure|retry)_attempts?(?:_(?:count|counter|total))?|"
    r"attempted_(?:methods?|approaches?)|(?:method|approach|attempt)_order|"
    r"(?:stop|halt)_(?:flag|state|status)|(?:is_)?(?:stopped|halted)|"
    r"failure_(?:event_)?history|attempt_history|failure_attempt_log)"
)
ACTION_EXECUTABLE_END = re.compile(
    r"(?:한다|시킨다|기다린다|유지한다|남긴다|중단한다)\.?$"
)
VAGUE_ACTION_END = re.compile(r"(?:계속|진행|검토|확인)한다\.?$")
GENERIC_ACTION = re.compile(
    r"(?:(?:계속|다음|후속|현재|해당)(?:/후속)?\s*)?"
    r"(?:작업|단계|내용|상태)?(?:을|를)?\s*(?:계속|진행|검토|확인)?한다?\.?$"
)
ACTION_PATH = re.compile(
    r"(?:[A-Za-z0-9_.-]+[/\\])+[A-Za-z0-9_.-]+|"
    r"[A-Za-z0-9_.-]+\.(?:md|py|json|toml|ya?ml)"
)
ACTION_SPECIFIC_TERM = re.compile(
    r"(?:현재 단계|직전 게이트|승인 상태|승인 범위|차단|알려진 위험|"
    r"첫 다음 행동|필수 절|변경 경로|검증 결과|후보 commit|"
    r"통과하면|실패하면|없으면|있으면|지시하면|승인하면|판정)"
)
FORBIDDEN_STATE_SECTION = re.compile(
    r"(?:(?<!미)완료|이력|기록|과거\s*판정|구현.*상태|"
    r"작업.*(?:과정|내역)|변경.*내역)"
)
GATE_JUDGMENT = re.compile(
    r"(?:`(?:pass|fail|not_run|not_applicable)`|"
    r"(?<![A-Za-z0-9_.-])(?:pass|fail|not_run|not_applicable)"
    r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9_])|"
    r"[:：]\s*(?:통과|실패)(?![0-9A-Za-z가-힣_-]|\.[0-9A-Za-z가-힣_])|"
    r"^\s*-\s*(?:통과|실패)(?![0-9A-Za-z가-힣_-]|\.[0-9A-Za-z가-힣_]))",
    re.IGNORECASE | re.MULTILINE,
)
SKIP_DIRS = {".git", "tmp", "__pycache__", ".obsidian"}
CONSUMER_CHECKS = (
    "consumer-contract",
    "consumer-core-read-only",
    "consumer-capabilities",
    "consumer-entry",
    "consumer-state",
    "consumer-rule-routes",
    "consumer-document-headers",
    "consumer-markdown-links",
    "consumer-submodule",
)


def _host_git_context(core_root: Path) -> tuple[dict[str, str], list[str]]:
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("GIT_"):
            environment.pop(name, None)
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    git_prefix = [
        "git",
        "-c",
        f"safe.directory={core_root.resolve().as_posix()}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
    ]
    return environment, git_prefix


def _run_host_git(
    core_root: Path,
    *arguments: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment, git_prefix = _host_git_context(core_root)
    return subprocess.run(
        [*git_prefix, *arguments],
        cwd=core_root,
        env=environment,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _tracked_content_attributes(
    core_root: Path, relatives: Iterable[str]
) -> tuple[bool, str]:
    """tracked 일반 파일의 content 변환 attribute를 단일 Git 호출로 검사한다."""
    paths = tuple(relatives)
    if not paths:
        return True, "ok"
    attributes = ("filter", "working-tree-encoding", "ident")
    try:
        completed = _run_host_git(
            core_root,
            "check-attr",
            "-z",
            "--stdin",
            *attributes,
            input_text="\0".join(paths) + "\0",
        )
    except OSError as exc:
        return False, f"tracked 경로의 Git attribute를 읽을 수 없다: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Git attribute 확인 실패"
        return False, detail[-500:]
    fields = [field for field in completed.stdout.split("\0") if field]
    if len(fields) % 3 != 0:
        return False, "tracked 경로의 Git attribute를 판정할 수 없다"
    expected = {(relative, attribute) for relative in paths for attribute in attributes}
    observed: set[tuple[str, str]] = set()
    unsafe: list[str] = []
    for relative, attribute, value in zip(
        fields[0::3], fields[1::3], fields[2::3], strict=True
    ):
        key = (relative, attribute)
        if key not in expected or key in observed:
            return False, "tracked 경로의 Git attribute를 판정할 수 없다"
        observed.add(key)
        if value not in {"unspecified", "unset"}:
            unsafe.append(f"{relative}: {attribute}={value}")
    if observed != expected:
        return False, "tracked 경로의 Git attribute를 판정할 수 없다"
    if unsafe:
        return False, (
            "content 변환 가능성이 있는 attribute를 허용하지 않는다: "
            + "; ".join(unsafe[:5])
        )
    return True, "ok"


def _parse_index_entries(raw: str) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for record in (value for value in raw.split("\0") if value):
        header, separator, relative = record.partition("\t")
        fields = header.split()
        if not separator or len(fields) != 3 or fields[2] != "0" or relative in entries:
            raise ValueError("Git index 항목 형식을 판정할 수 없다")
        entries[relative] = (fields[0], fields[1])
    return entries


def _parse_head_entries(raw: str) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for record in (value for value in raw.split("\0") if value):
        header, separator, relative = record.partition("\t")
        fields = header.split()
        if not separator or len(fields) != 3 or relative in entries:
            raise ValueError("Git HEAD 항목 형식을 판정할 수 없다")
        entries[relative] = (fields[0], fields[2])
    return entries


def host_consumer_gitlink_fingerprint(
    core_root: Path,
    consumer_root: Path,
    core_relative: str,
) -> str:
    """Host 부모 gitlink 계약과 실행 Core HEAD를 검증하고 지문화한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    core_relative = Path(core_relative).as_posix().rstrip("/")
    gitmodules = consumer_root / ".gitmodules"
    if not gitmodules.is_file():
        raise CheckError("Core submodule 선언 파일이 없다")
    try:
        gitmodules_bytes = gitmodules.read_bytes()
        gitmodules_text = gitmodules_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise CheckError(f"Core submodule 선언 파일을 읽을 수 없다: {exc}") from exc
    paths = re.findall(
        r"(?m)^\s*path\s*=\s*(.+?)\s*$",
        gitmodules_text,
    )
    if core_relative not in {Path(value).as_posix() for value in paths}:
        raise CheckError("core_path와 일치하는 submodule path가 없다")

    try:
        toplevel = _run_host_git(consumer_root, "rev-parse", "--show-toplevel")
        staged = _run_host_git(
            consumer_root,
            "ls-files",
            "--stage",
            "-z",
            "--",
            core_relative,
        )
        head = _run_host_git(
            consumer_root,
            "ls-tree",
            "-z",
            "HEAD",
            "--",
            core_relative,
        )
        core_head = _run_host_git(core_root, "rev-parse", "--verify", "HEAD^{commit}")
    except OSError as exc:
        raise CheckError(f"Host 부모 gitlink 상태를 실행할 수 없다: {exc}") from exc
    for label, completed in (
        ("parent root", toplevel),
        ("parent index", staged),
        ("parent HEAD", head),
        ("Core HEAD", core_head),
    ):
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"{label} 확인 실패"
            raise CheckError(detail[-500:])
    try:
        same_root = Path(toplevel.stdout.strip()).resolve().samefile(consumer_root)
    except OSError as exc:
        raise CheckError(f"Host 부모 Git root를 대조할 수 없다: {exc}") from exc
    if not same_root:
        raise CheckError(
            "Host 부모 Git top-level이 consumer_root와 다르다: "
            f"{toplevel.stdout.strip()}"
        )
    try:
        index_entries = _parse_index_entries(staged.stdout)
        head_entries = _parse_head_entries(head.stdout)
    except ValueError as exc:
        raise CheckError(str(exc)) from exc
    expected_index = index_entries.get(core_relative)
    expected_head = head_entries.get(core_relative)
    if expected_index is None or expected_index[0] != "160000":
        raise CheckError(f"부모 index의 core_path가 gitlink가 아니다: {core_relative}")
    if expected_head is None or expected_head[0] != "160000":
        raise CheckError(f"부모 HEAD의 core_path가 gitlink가 아니다: {core_relative}")
    if expected_index != expected_head:
        raise CheckError(f"부모 HEAD와 index의 Core gitlink가 다르다: {core_relative}")
    if core_head.stdout.strip() != expected_head[1]:
        raise CheckError(
            "부모 gitlink와 실행 Core HEAD가 다르다: "
            f"{core_relative}"
        )

    digest = hashlib.sha256()
    for value in (
        core_relative.encode("utf-8"),
        gitmodules_bytes,
        str(consumer_root).encode("utf-8"),
        expected_index[0].encode("ascii"),
        expected_index[1].encode("ascii"),
        expected_head[0].encode("ascii"),
        expected_head[1].encode("ascii"),
        core_head.stdout.strip().encode("ascii"),
    ):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def host_consumer_gitlink_observation_fingerprint(
    core_root: Path,
    consumer_root: Path,
    core_relative: str,
) -> str:
    """유효성 판정 없이 부모 gitlink 관련 원시 상태를 진단 기준선으로 지문화한다."""
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    core_relative = Path(core_relative).as_posix().rstrip("/")
    gitmodules = consumer_root / ".gitmodules"
    try:
        gitmodules_bytes = gitmodules.read_bytes() if gitmodules.is_file() else b""
        commands = (
            (
                "parent-root",
                _run_host_git(consumer_root, "rev-parse", "--show-toplevel"),
            ),
            (
                "parent-index",
                _run_host_git(
                    consumer_root,
                    "ls-files",
                    "--stage",
                    "-z",
                    "--",
                    core_relative,
                ),
            ),
            (
                "parent-head",
                _run_host_git(
                    consumer_root,
                    "ls-tree",
                    "-z",
                    "HEAD",
                    "--",
                    core_relative,
                ),
            ),
            (
                "core-head",
                _run_host_git(
                    core_root,
                    "rev-parse",
                    "--verify",
                    "HEAD^{commit}",
                ),
            ),
        )
    except OSError as exc:
        raise CheckError(f"Host 부모 gitlink 관찰 상태를 읽을 수 없다: {exc}") from exc

    digest = hashlib.sha256()

    def frame(value: str | bytes) -> None:
        payload = value.encode("utf-8") if isinstance(value, str) else value
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)

    frame(str(core_root))
    frame(str(consumer_root))
    frame(core_relative)
    frame("gitmodules-present" if gitmodules.is_file() else "gitmodules-missing")
    frame(gitmodules_bytes)
    for label, completed in commands:
        frame(label)
        frame(str(completed.returncode))
        frame(completed.stdout)
        frame(completed.stderr)
    return digest.hexdigest()


def host_consumer_gitlink_status(
    core_root: Path,
    consumer_root: Path,
    core_relative: str,
) -> tuple[bool, str]:
    """Host 부모 HEAD·index gitlink와 실행 Core HEAD가 같은지 판정한다."""
    try:
        host_consumer_gitlink_fingerprint(core_root, consumer_root, core_relative)
    except (CheckError, OSError) as exc:
        return False, str(exc)
    return True, "부모 HEAD·index gitlink와 실행 Core HEAD가 일치한다"


def _blob_oid(content: bytes, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def host_core_git_fingerprint(core_root: Path) -> str:
    """Host 실행 전후의 HEAD와 index 의미 상태를 읽기 전용으로 지문화한다."""
    digest = hashlib.sha256()
    outputs: dict[tuple[str, ...], str] = {}
    for arguments in (
        ("rev-parse", "--verify", "HEAD^{commit}"),
        ("rev-parse", "--show-object-format"),
        ("ls-files", "--stage", "-z"),
        ("ls-files", "-v", "-z"),
        ("config", "--local", "--null", "--list"),
    ):
        try:
            completed = _run_host_git(core_root, *arguments)
        except OSError as exc:
            raise CheckError(f"Host Core Git 상태를 실행할 수 없다: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "Git 상태 확인 실패"
            raise CheckError(detail[-500:])
        payload = completed.stdout.encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        outputs[arguments] = completed.stdout
    try:
        index_entries = _parse_index_entries(outputs[("ls-files", "--stage", "-z")])
    except ValueError as exc:
        raise CheckError(str(exc)) from exc
    for relative, (mode, _) in sorted(index_entries.items()):
        if mode != "160000":
            continue
        nested_root = core_root.joinpath(*PurePosixPath(relative).parts)
        nested = host_core_git_fingerprint(nested_root).encode("ascii")
        relative_bytes = relative.encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(nested).to_bytes(8, "big"))
        digest.update(nested)
    return digest.hexdigest()


def host_core_cleanliness(core_root: Path) -> tuple[bool, str]:
    """Host Core가 HEAD와 byte 단위로 같은 checkout인지 판정한다."""
    try:
        toplevel = _run_host_git(core_root, "rev-parse", "--show-toplevel")
    except OSError as exc:
        return False, f"Git 상태를 실행할 수 없다: {exc}"
    if toplevel.returncode != 0:
        detail = toplevel.stderr.strip() or toplevel.stdout.strip() or "Git root 확인 실패"
        return False, detail[-500:]
    try:
        same_root = Path(toplevel.stdout.strip()).resolve().samefile(core_root.resolve())
    except OSError as exc:
        return False, f"Git root를 대조할 수 없다: {exc}"
    if not same_root:
        return False, f"Git top-level이 core_root와 다르다: {toplevel.stdout.strip()}"

    try:
        tracked = _run_host_git(core_root, "ls-files", "-v", "-z")
    except OSError as exc:
        return False, f"Git index를 실행할 수 없다: {exc}"
    if tracked.returncode != 0:
        detail = tracked.stderr.strip() or tracked.stdout.strip() or "Git index 확인 실패"
        return False, detail[-500:]
    records = [record for record in tracked.stdout.split("\0") if record]
    malformed = [record for record in records if len(record) < 3 or record[1] != " "]
    if malformed:
        return False, "Git index 항목 형식을 판정할 수 없다"
    flagged = [record for record in records if record[0] != "H"]
    if flagged:
        return False, f"Git index 우회 flag가 있다: {'; '.join(flagged[:5])}"

    try:
        staged = _run_host_git(core_root, "ls-files", "--stage", "-z")
        head = _run_host_git(core_root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
        object_format = _run_host_git(core_root, "rev-parse", "--show-object-format")
    except OSError as exc:
        return False, f"Git 객체 상태를 실행할 수 없다: {exc}"
    for label, completed_object in (
        ("index", staged),
        ("HEAD", head),
        ("object format", object_format),
    ):
        if completed_object.returncode != 0:
            detail = (
                completed_object.stderr.strip()
                or completed_object.stdout.strip()
                or f"Git {label} 확인 실패"
            )
            return False, detail[-500:]
    try:
        index_entries = _parse_index_entries(staged.stdout)
        head_entries = _parse_head_entries(head.stdout)
    except ValueError as exc:
        return False, str(exc)
    if index_entries != head_entries:
        differences = sorted(
            relative
            for relative in set(index_entries) | set(head_entries)
            if index_entries.get(relative) != head_entries.get(relative)
        )
        return False, f"HEAD와 index가 다르다: {'; '.join(differences[:5])}"
    algorithm = object_format.stdout.strip()
    if algorithm not in hashlib.algorithms_available:
        return False, f"지원하지 않는 Git object format이다: {algorithm}"

    regular_paths = sorted(
        relative for relative, (mode, _) in index_entries.items()
        if mode in {"100644", "100755"}
    )
    attributes_safe, attributes_detail = _tracked_content_attributes(core_root, regular_paths)
    if not attributes_safe:
        return False, attributes_detail

    try:
        completed = _run_host_git(
            core_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
        )
    except OSError as exc:
        return False, f"Git 상태를 실행할 수 없다: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Git 상태 확인 실패"
        return False, detail[-500:]
    entries = [line for line in completed.stdout.splitlines() if line]
    if entries:
        return False, "; ".join(entries[:5])

    submodule_directories: set[Path] = set()
    for relative, (mode, expected_oid) in index_entries.items():
        worktree_path = core_root.joinpath(*PurePosixPath(relative).parts)
        try:
            file_stat = worktree_path.lstat()
        except OSError as exc:
            return False, f"tracked 경로를 읽을 수 없다: {relative}: {exc}"
        if mode in {"100644", "100755"}:
            if not stat.S_ISREG(file_stat.st_mode):
                return False, f"tracked entry type이 다르다: {relative}"
            try:
                raw_content = worktree_path.read_bytes()
            except OSError as exc:
                return False, f"tracked 파일을 읽을 수 없다: {relative}: {exc}"
            if _blob_oid(raw_content, algorithm) != expected_oid:
                return False, f"tracked blob 내용이 HEAD와 다르다: {relative}"
            if os.name != "nt":
                executable = bool(file_stat.st_mode & 0o111)
                if executable != (mode == "100755"):
                    return False, f"tracked 실행 mode가 HEAD와 다르다: {relative}"
        elif mode == "120000":
            if not stat.S_ISLNK(file_stat.st_mode):
                return False, f"tracked symlink type이 다르다: {relative}"
            try:
                target = os.fsencode(os.readlink(worktree_path))
            except OSError as exc:
                return False, f"tracked symlink를 읽을 수 없다: {relative}: {exc}"
            if _blob_oid(target, algorithm) != expected_oid:
                return False, f"tracked symlink target이 HEAD와 다르다: {relative}"
        elif mode == "160000":
            if not stat.S_ISDIR(file_stat.st_mode):
                return False, f"tracked gitlink type이 다르다: {relative}"
            submodule_directories.add(worktree_path)
            try:
                nested_head = _run_host_git(worktree_path, "rev-parse", "--verify", "HEAD^{commit}")
            except OSError as exc:
                return False, f"tracked gitlink를 읽을 수 없다: {relative}: {exc}"
            if nested_head.returncode != 0 or nested_head.stdout.strip() != expected_oid:
                return False, f"tracked gitlink HEAD가 다르다: {relative}"
            nested_clean, nested_detail = host_core_cleanliness(worktree_path)
            if not nested_clean:
                return False, f"tracked gitlink가 clean하지 않다: {relative}: {nested_detail}"
        else:
            return False, f"지원하지 않는 tracked mode다: {mode} {relative}"

    allowed_directories: set[str] = set()
    for relative_text, (mode, _) in index_entries.items():
        relative = PurePosixPath(relative_text)
        for parent in relative.parents:
            if parent.as_posix() != ".":
                allowed_directories.add(parent.as_posix())
        if mode == "160000":
            allowed_directories.add(relative.as_posix())
    git_metadata = core_root / ".git"
    extra_directories: list[str] = []
    for path in sorted(core_root.rglob("*")):
        if not path.is_dir():
            continue
        if git_metadata.is_dir() and (path == git_metadata or git_metadata in path.parents):
            continue
        if any(path == root or root in path.parents for root in submodule_directories):
            continue
        relative = path.relative_to(core_root).as_posix()
        if relative not in allowed_directories:
            extra_directories.append(relative)
    if extra_directories:
        return False, f"Git이 소유하지 않는 directory가 있다: {'; '.join(extra_directories[:5])}"
    return True, "HEAD·index·tracked blob/type/mode, untracked·ignored, 우회 flag, 추가 directory 일치"


def _walk(root: Path, suffix: str) -> Iterator[Path]:
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


@register("declaration-contracts")
def check_declaration_contracts(root: Path) -> Iterable[Finding]:
    for label, loader in (
        ("Core 문서 역할", document_roles),
        ("모듈 계층", module_layers),
        ("Core 규칙 route", routed_rule_paths),
        ("호환성", declared_compatibility),
    ):
        try:
            loader(root)
        except CheckError as exc:
            yield Finding("declaration-contracts", "-", f"{label}: {exc}")


@register("text-encoding")
def check_text_encoding(root: Path) -> Iterable[Finding]:
    for suffix in (".md", ".py", ".json"):
        for path in _walk(root, suffix):
            raw = path.read_bytes()
            rel = _rel(root, path)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                yield Finding("text-encoding", rel, f"UTF-8 디코딩 실패: {exc}")
                continue
            if b"\x00" in raw:
                yield Finding("text-encoding", rel, "NUL 바이트가 있다")
            for number, line in enumerate(text.splitlines(), start=1):
                if line != line.rstrip(" \t"):
                    yield Finding("text-encoding", rel, f"{number}행에 후행 공백이 있다")


@register("markdown-links")
def check_markdown_links(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".md"):
        rel = _rel(root, path)
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                yield Finding("markdown-links", rel, f"깨진 링크: {target}")


@register("json-parse")
def check_json_parse(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            yield Finding("json-parse", _rel(root, path), f"JSON 파싱 실패: {exc}")


@register("python-ast")
def check_python_ast(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            yield Finding("python-ast", _rel(root, path), f"구문 오류: {exc}")


@register("document-headers")
def check_document_headers(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".md"):
        text = path.read_text(encoding="utf-8")
        missing = [header for header in DOC_HEADERS if header not in text]
        if missing:
            yield Finding(
                "document-headers", _rel(root, path), f"최소 설명 누락: {' '.join(missing)}"
            )


@register("rule-routes")
def check_rule_routes(root: Path) -> Iterable[Finding]:
    try:
        routes = routed_rule_paths(root)
    except CheckError as exc:
        yield Finding("rule-routes", "-", str(exc))
        return
    rules_dir = root / "rules"
    active = sorted(f"rules/{path.name}" for path in rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    for rule in active:
        count = routes.count(rule)
        if count != 1:
            yield Finding("rule-routes", rule, f"route 수가 {count}이다")
    for route in routes:
        if not (root / route).is_file():
            yield Finding("rule-routes", route, "고아 route")


@register("rule-cross-routing")
def check_rule_cross_routing(root: Path) -> Iterable[Finding]:
    rules_dir = root / "rules"
    if not rules_dir.is_dir():
        return
    for path in sorted(rules_dir.glob("*.md")):
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.endswith(".md") and "/" not in target and target != path.name:
                yield Finding(
                    "rule-cross-routing", _rel(root, path), f"다른 규칙을 직접 라우팅한다: {target}"
                )


@register("layer-boundaries")
def check_layer_boundaries(root: Path) -> Iterable[Finding]:
    graph: dict[str, set[str]] = {}
    package = root / "src" / "core_check"
    if not package.is_dir():
        return
    try:
        layers = module_layers(root)
    except CheckError as exc:
        yield Finding("layer-boundaries", "-", str(exc))
        return

    assignments: dict[str, list[str]] = {}
    absent_l7_paths: set[str] = set()
    l7_groups: dict[tuple[str, str], list[str]] = {}
    for declared in layers["L7"]:
        parts = Path(declared).parts
        if len(parts) >= 2 and parts[0] == "experimental":
            l7_groups.setdefault((parts[0], parts[1]), []).append(declared)
    for paths in l7_groups.values():
        if not any((root / declared).is_file() for declared in paths):
            absent_l7_paths.update(paths)
    for layer, paths in layers.items():
        for declared in paths:
            assignments.setdefault(declared, []).append(layer)
            if not (root / declared).is_file() and declared not in absent_l7_paths:
                yield Finding("layer-boundaries", declared, f"{layer} 배정 대상 파일이 없다")

    for path in sorted(package.glob("*.py")):
        rel = _rel(root, path)
        owners = assignments.get(rel, [])
        if len(owners) != 1:
            yield Finding("layer-boundaries", rel, f"계층 배정 수가 {len(owners)}이다: {owners}")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module:
                    deps.add(f"src/core_check/{node.module.split('.', 1)[0]}.py")
                else:
                    for alias in node.names:
                        deps.add(f"src/core_check/{alias.name.split('.', 1)[0]}.py")
        graph[rel] = deps
        layer = owners[0] if len(owners) == 1 else None
        if layer == "L6" and deps:
            yield Finding("layer-boundaries", rel, f"L6이 내부 모듈을 import한다: {sorted(deps)}")
        if layer == "L5":
            bad = [dep for dep in deps if "L7" in assignments.get(dep, [])]
            if bad:
                yield Finding("layer-boundaries", rel, f"L5가 L7을 import한다: {bad}")

    seen: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> Iterator[Finding]:
        if node in stack:
            yield Finding("layer-boundaries", node, f"순환 의존: {' -> '.join(stack + [node])}")
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            yield from visit(dep)
        stack.pop()

    for node in sorted(graph):
        yield from visit(node)


@register("no-hardcoded-doc-names")
def check_no_hardcoded_doc_names(root: Path) -> Iterable[Finding]:
    package = root / "src" / "core_check"
    if not package.is_dir():
        return
    try:
        roles = document_roles(root)
    except CheckError:
        return
    discovered = {Path(value).name for value in roles.values() if isinstance(value, str)}
    for path in sorted(package.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in sorted(discovered):
            if name in text:
                yield Finding(
                    "no-hardcoded-doc-names", _rel(root, path), f"문서 이름이 상수로 있다: {name}"
                )


@register("temporary-canonical-links")
def check_temporary_canonical_links(root: Path) -> Iterable[Finding]:
    for path in _walk(root, ".md"):
        rel = _rel(root, path)
        for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith("tmp/") or "/tmp/" in target:
                yield Finding("temporary-canonical-links", rel, f"한시 자료를 참조한다: {target}")


def _markdown_h2_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    heading: str | None = None
    body: list[str] = []
    fence: tuple[str, int] | None = None
    in_comment = False

    def flush() -> None:
        if heading is not None:
            sections.setdefault(heading, []).append("".join(body))

    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if fence is not None:
            closing_match = re.fullmatch(r" {0,3}(`{3,}|~{3,})[ \t]*", content)
            if (
                closing_match
                and closing_match.group(1)[0] == fence[0]
                and len(closing_match.group(1)) >= fence[1]
            ):
                fence = None
            continue
        # Indented examples cannot declare state or open HTML comments.
        if not in_comment and content.expandtabs(4).startswith("    "):
            continue
        visible: list[str] = []
        cursor = 0
        while cursor < len(content):
            if in_comment:
                end = content.find("-->", cursor)
                if end == -1:
                    break
                visible.append(" " * (end + 3 - cursor))
                cursor = end + 3
                in_comment = False
            else:
                start = content.find("<!--", cursor)
                if start == -1:
                    visible.append(content[cursor:])
                    break
                visible.append(content[cursor:start])
                cursor = start
                in_comment = True
        content = "".join(visible)
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", content)
        if fence_match:
            marker = fence_match.group(1)
            fence = (marker[0], len(marker))
            continue
        match = re.match(r"^ {0,3}##(?!#)\s+(.+?)\s*$", content)
        if match:
            flush()
            title = re.sub(r"\s+#+\s*$", "", match.group(1)).strip()
            heading = f"## {title}"
            body = []
            continue
        if heading is not None:
            body.append(content + "\n")
    flush()
    return sections


def _action_has_concrete_signal(action: str) -> bool:
    code_spans = [value.strip() for value in re.findall(r"`([^`]+)`", action)]
    if any(value.upper() not in {"TODO", "TBD"} for value in code_spans):
        return True
    return bool(ACTION_PATH.search(action) or ACTION_SPECIFIC_TERM.search(action))


def _state_field_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or not cells[0] or not cells[1]:
            return None
        key = cells[0]
    else:
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        match = re.match(r"^[`\"']?(.+?)[`\"']?\s*[:：=]\s*\S", stripped)
        if match is None:
            return None
        key = match.group(1)
    return key.strip(" `\"'")


def _has_ephemeral_failure_state(text: str) -> bool:
    for line in text.splitlines():
        key = _state_field_key(line)
        if key is None:
            continue
        korean_key = re.sub(r"\s+", "", key)
        if EPHEMERAL_FAILURE_KOREAN_KEY.fullmatch(korean_key):
            return True
        english_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
        english_key = re.sub(r"[^a-zA-Z0-9]+", "_", english_key).strip("_").lower()
        if EPHEMERAL_FAILURE_ENGLISH_KEY.fullmatch(english_key):
            return True
    return False


def _state_findings(consumer_root: Path, state: Path) -> Iterable[Finding]:
    text = state.read_text(encoding="utf-8")
    rel = _rel(consumer_root, state)
    sections = _markdown_h2_sections(text)
    for section in STATE_SECTIONS:
        if section not in sections:
            yield Finding("consumer-state", rel, f"필수 절이 없다: {section}")
        elif len(sections[section]) > 1:
            yield Finding("consumer-state", rel, f"필수 절이 중복됐다: {section}")
    for heading in sections:
        if FORBIDDEN_STATE_SECTION.search(heading.removeprefix("## ")):
            yield Finding("consumer-state", rel, f"완료 상세 절을 포함한다: {heading}")
    if len(text) > STATE_BUDGET_CHARS:
        yield Finding("consumer-state", rel, f"{len(text)}자가 예산 {STATE_BUDGET_CHARS}자를 넘었다")
    if DYNAMIC_NUMBERS.search(text):
        yield Finding("consumer-state", rel, "동적 Git 수치가 문서에 고정되어 있다")
    if STATE_FILE_COUNTS.search(text):
        yield Finding("consumer-state", rel, "파일 개수가 문서에 고정되어 있다")
    if _has_ephemeral_failure_state(text):
        yield Finding("consumer-state", rel, "임시 실패 상태가 문서에 고정되어 있다")
    if "## 첫 다음 행동" in sections:
        tail = sections["## 첫 다음 행동"][0]
        actions = [line.strip() for line in tail.splitlines() if re.match(r"^\d+\.", line.strip())]
        if not actions:
            yield Finding("consumer-state", rel, "번호가 매겨진 첫 다음 행동이 없다")
        for action in actions:
            content = re.sub(r"^\d+\.\s*", "", action)
            if (
                not ACTION_EXECUTABLE_END.search(content)
                or GENERIC_ACTION.fullmatch(content)
                or (VAGUE_ACTION_END.search(content) and not _action_has_concrete_signal(content))
            ):
                yield Finding("consumer-state", rel, f"첫 다음 행동이 모호하다: {action}")
    if "## 직전 게이트" in sections:
        gates = sections["## 직전 게이트"][0]
        judged = list(GATE_JUDGMENT.finditer(gates))
        if not judged:
            yield Finding("consumer-state", rel, "직전 게이트 절에 판정이 없다")
        elif len(judged) > 1:
            yield Finding("consumer-state", rel, "직전 게이트 절에 과거 판정이 누적되어 있다")


def state_contract_findings(consumer_root: Path, state: Path) -> list[Finding]:
    """상태 계약의 독립 결함 주입 테스트용 공개 helper."""
    return list(_state_findings(consumer_root.resolve(), state.resolve()))


def _entry_targets(text: str) -> list[str]:
    targets = MD_LINK.findall(text)
    targets.extend(AT_REFERENCE.findall(text))
    return [target.replace("\\", "/") for target in targets]


def _consumer_contract_files(core_root: Path, consumer_root: Path, contract: dict[str, object]) -> list[Path]:
    files = {
        consumer_policy_path(core_root, consumer_root),
        resolve_inside(consumer_root, contract["state"]),
    }
    for value in contract["entry_pointers"].values():
        files.add(resolve_inside(consumer_root, value))
    for value in contract["rule_roots"]:
        files.update(resolve_inside(consumer_root, value).rglob("*.md"))
    gitmodules = consumer_root / ".gitmodules"
    if gitmodules.is_file():
        files.add(gitmodules)
    return sorted(path for path in files if path.is_file())


def consumer_findings(
    core_root: Path, consumer_root: Path, *, report: Report | None = None
) -> Iterable[Finding]:
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()

    def started(name: str) -> None:
        if report is not None and name not in report.ran:
            report.ran.append(name)

    started("consumer-contract")
    try:
        contract = consumer_contract(core_root, consumer_root)
        compatibility = declared_compatibility(core_root)
    except CheckError as exc:
        yield Finding("consumer-contract", "-", str(exc))
        if report is not None:
            reason = "consumer-contract를 해석하지 못해 실행하지 않았다"
            report.skipped.update({name: reason for name in CONSUMER_CHECKS[1:]})
        return

    if contract["contract_version"] != compatibility.get("contract_version"):
        yield Finding("consumer-contract", "-", "Core와 소비 계약의 contract_version이 다르다")

    started("consumer-core-read-only")
    if contract["consumer_role"] == "host":
        clean, detail = host_core_cleanliness(core_root)
        if not clean:
            yield Finding(
                "consumer-core-read-only",
                Path(contract["core_path"]).as_posix(),
                f"Host Core가 읽기 전용 clean 상태가 아니다: {detail}",
            )

    started("consumer-capabilities")
    available = compatibility.get("optional_capabilities", {})
    for capability_id, required_version in contract["required_core_capabilities"].items():
        declaration = available.get(capability_id)
        if not isinstance(declaration, dict):
            yield Finding(
                "consumer-capabilities", capability_id, "Core 호환성 선언에 선택 기능이 없다"
            )
            continue
        try:
            state = optional_capability_installation_state(core_root, capability_id, declaration)
        except CheckError as exc:
            yield Finding("consumer-capabilities", capability_id, str(exc))
            continue
        if state != "installed":
            yield Finding("consumer-capabilities", capability_id, "요구 선택 기능이 설치되지 않았다")
        elif declaration["version"] < required_version:
            yield Finding(
                "consumer-capabilities",
                capability_id,
                f"요구 버전 {required_version}, 제공 버전 {declaration['version']}",
            )

    core_rel = Path(contract["core_path"]).as_posix().rstrip("/")
    core_policy = core_policy_path(core_root).relative_to(core_root).as_posix()
    policy = consumer_policy_path(core_root, consumer_root).relative_to(consumer_root).as_posix()
    expected = [f"{core_rel}/{core_policy}", policy, Path(contract["state"]).as_posix()]
    started("consumer-entry")
    for agent, value in contract["entry_pointers"].items():
        pointer = resolve_inside(consumer_root, value)
        actual = _entry_targets(pointer.read_text(encoding="utf-8"))
        if actual != expected:
            yield Finding(
                "consumer-entry", _rel(consumer_root, pointer), f"{agent} 진입 순서가 다르다: {actual}"
            )

    state = resolve_inside(consumer_root, contract["state"])
    started("consumer-state")
    yield from _state_findings(consumer_root, state)

    started("consumer-rule-routes")
    try:
        routes = consumer_routed_rule_paths(core_root, consumer_root)
    except CheckError as exc:
        yield Finding("consumer-rule-routes", policy, str(exc))
        routes = []
    active: list[str] = []
    for value in contract["rule_roots"]:
        root = resolve_inside(consumer_root, value)
        active.extend(_rel(consumer_root, path) for path in sorted(root.glob("*.md")))
    for rule in active:
        if routes.count(rule) != 1:
            yield Finding("consumer-rule-routes", rule, f"route 수가 {routes.count(rule)}이다")
    for route in routes:
        if not resolve_inside(consumer_root, route).is_file():
            yield Finding("consumer-rule-routes", route, "고아 route")

    pointers = {Path(value).as_posix() for value in contract["entry_pointers"].values()}
    started("consumer-document-headers")
    started("consumer-markdown-links")
    for path in _consumer_contract_files(core_root, consumer_root, contract):
        rel = _rel(consumer_root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            text = ""
        if path.suffix == ".md" and rel not in pointers:
            missing = [header for header in DOC_HEADERS if header not in text]
            if missing:
                yield Finding("consumer-document-headers", rel, f"최소 설명 누락: {' '.join(missing)}")
        if path.suffix == ".md":
            for target in MD_LINK.findall(text):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                if not resolved.exists():
                    yield Finding("consumer-markdown-links", rel, f"깨진 링크: {target}")

    gitmodules = consumer_root / ".gitmodules"
    started("consumer-submodule")
    if not gitmodules.is_file():
        yield Finding("consumer-submodule", ".gitmodules", "Core submodule 선언 파일이 없다")
    else:
        try:
            gitmodules_text = gitmodules.read_text(encoding="utf-8")
        except UnicodeError as exc:
            yield Finding(
                "consumer-submodule",
                ".gitmodules",
                f"UTF-8 submodule 선언을 읽을 수 없다: {exc}",
            )
            gitmodules_text = ""
        paths = re.findall(r"(?m)^\s*path\s*=\s*(.+?)\s*$", gitmodules_text)
        normalized = {Path(value).as_posix() for value in paths}
        if Path(contract["core_path"]).as_posix() not in normalized:
            yield Finding("consumer-submodule", ".gitmodules", "core_path와 일치하는 submodule path가 없다")
    if contract["consumer_role"] == "host":
        linked, detail = host_consumer_gitlink_status(
            core_root,
            consumer_root,
            str(contract["core_path"]),
        )
        if not linked:
            yield Finding("consumer-submodule", Path(contract["core_path"]).as_posix(), detail)


def run_consumer(core_root: Path, consumer_root: Path) -> Report:
    report = Report()
    report.findings.extend(consumer_findings(core_root, consumer_root, report=report))
    return report


def run_all(root: Path) -> Report:
    report = Report()
    for name, fn in sorted(REGISTRY.required.items()):
        report.ran.append(name)
        report.findings.extend(fn(root))
    for name, fn in sorted(REGISTRY.optional.items()):
        report.ran.append(name)
        report.findings.extend(fn(root))
    if not REGISTRY.optional:
        try:
            declared_optional = declared_compatibility(root).get("optional_capabilities", {})
        except CheckError:
            declared_optional = {}
        if not declared_optional:
            report.skipped["optional-checks"] = "선택 기능이 등록되지 않았다. 실패가 아니다."
    return report
