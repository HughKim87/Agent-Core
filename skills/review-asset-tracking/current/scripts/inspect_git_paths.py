"""Report metadata and Git evidence for individual, pre-screened project files."""

import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import stat
import subprocess


def git(root, *args, stdin=None):
    env = os.environ.copy()
    # Use the specified worktree and its real index, including in linked worktrees.
    for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS",
                "GIT_ICASE_PATHSPECS", "GIT_CEILING_DIRECTORIES"):
        env.pop(key, None)
    env.update(LC_ALL="C", GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1")
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args], cwd=root, env=env,
        input=stdin, capture_output=True, check=False,
    )


def checked(result, name, allowed=(0,)):
    if result.returncode not in allowed or result.stderr:
        detail = os.fsdecode(result.stderr).strip() or f"exit {result.returncode}"
        raise ValueError(f"git {name}: {detail}")
    return result.stdout


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def entry_info(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def is_repository_dir(directory):
    if entry_info(directory / ".git"):
        return True
    # A bare repo keeps its metadata directly under its root.
    return all(entry_info(directory / name) for name in ("HEAD", "objects", "refs"))


def repository(root):
    if ".." in root.parts:
        raise ValueError("Use a root path without parent traversal")
    for directory in (*reversed(root.parents), root):
        if directory.name.casefold() == ".git" or is_link(directory.lstat()):
            raise ValueError("The root crosses a link or Git metadata")
    if os.name == "nt" and root.resolve(strict=True) != root:
        raise ValueError("Use the canonical project root")
    if not root.is_dir():
        raise ValueError("Root must be a directory")
    marker = entry_info(root / ".git")
    if marker and is_link(marker):
        raise ValueError("Linked .git metadata")
    result = git(root, "rev-parse", "--show-toplevel")
    if result.returncode == 128 and result.stderr.startswith(b"fatal: not a git repository"):
        if not any(is_repository_dir(parent) for parent in (root, *root.parents)):
            return "pre_init"
    top = checked(result, "rev-parse").removesuffix(b"\n").removesuffix(b"\r")
    if not root.samefile(os.fsdecode(top)):
        raise ValueError("Root must be the top of the intended worktree")
    return "git"


def file_metadata(root, name):
    path = Path(name)
    if not path.parts or path.anchor or PureWindowsPath(name).anchor or ".." in path.parts:
        raise ValueError("Expected a project-relative file path without parent traversal")
    current = root
    for index, part in enumerate(path.parts):
        if part.casefold() == ".git" or (os.name == "nt" and (
            ":" in part or part.endswith((" ", ".")) or Path(part).is_reserved()
        )):
            raise ValueError("Git metadata or reserved path")
        current = current / part
        info = current.lstat()
        if is_link(info):
            raise ValueError("Refusing to follow a symlink or reparse point")
        if os.name == "nt" and current.resolve(strict=True) != current:
            raise ValueError("Use the canonical file or directory name")
        if index < len(path.parts) - 1:
            if not stat.S_ISDIR(info.st_mode) or is_repository_dir(current):
                raise ValueError("Path crosses a non-directory or nested repository")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Only existing regular files can be inspected")
    if os.name == "nt":
        # NTFS can open the right file even when the supplied casing is different.
        path = current.resolve(strict=True).relative_to(root)
    return path.as_posix(), info.st_size


def is_listed(root, name, *options):
    magic = ":(literal,icase)" if os.name == "nt" else ":(literal)"
    result = git(root, "ls-files", "-z", *options, "--", magic + name)
    names = set(checked(result, "ls-files").split(b"\0")) - {b""}
    if names - {os.fsencode(name)}:
        raise ValueError("Git lists a different spelling or file structure for this path")
    return bool(names)


def matching_rule(root, name):
    # check-ignore rejects Git's literal pathspec mode. ./ disables leading colon
    # magic, and the NUL protocol keeps spaces, wildcards and newlines intact.
    supplied = os.fsencode("./" + name)
    result = git(root, "check-ignore", "-v", "-z", "--no-index", "--stdin",
                 stdin=supplied + b"\0")
    output = checked(result, "check-ignore", (0, 1))
    if not output:
        return None
    source, line, pattern, matched, end = output.split(b"\0")
    if matched != supplied or end:
        raise ValueError("Unexpected path from git check-ignore")
    return {"source": os.fsdecode(source), "line": int(line), "pattern": os.fsdecode(pattern)}


def inspect_file(root, name, repo):
    name, size = file_metadata(root, name)
    row = dict(path=name, size_bytes=size, indexed=None, untracked_candidate=None,
               ignored=None, ignore_rule=None)
    if repo == "git":
        indexed = is_listed(root, name, "--cached")
        candidate = is_listed(root, name, "--others", "--exclude-standard")
        rule = matching_rule(root, name)
        ignored = False
        if not indexed and not candidate and rule and not rule["pattern"].startswith("!"):
            ignored = is_listed(root, name, "--others", "--ignored", "--exclude-standard")
        if sum((indexed, candidate, ignored)) != 1:
            raise ValueError("Git results do not establish one state for this exact path")
        row.update(indexed=indexed, untracked_candidate=candidate, ignored=ignored, ignore_rule=rule)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    root = args.root.absolute()
    report = {"repository": "error", "files": []}
    try:
        report["repository"] = repository(root)
    except (ValueError, OSError) as exc:
        report["error"] = str(exc)
    else:
        for name in args.files:
            try:
                row = inspect_file(root, name, report["repository"])
            except (ValueError, OSError) as exc:
                row = {"path": name, "error": str(exc)}
            report["files"].append(row)
    print(json.dumps(report, ensure_ascii=True))
    return int("error" in report or any("error" in row for row in report["files"]))


if __name__ == "__main__":
    raise SystemExit(main())
