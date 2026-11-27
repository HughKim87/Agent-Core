"""Public v1 entry for opt-in evidence lookup."""

import argparse
from collections import defaultdict
from functools import cache
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

CORE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE / "src"))

from core_check.runtime_boundary import (  # noqa: E402
    RuntimeBoundaryError, capture_static_discovery_baseline,
    prepare_consumer_runtime_boundary, require_consumer_runtime_boundary_unchanged,
    require_static_discovery_unchanged,
)
from . import backends, obsidian_session  # noqa: E402

CAPABILITY = "evidence_lookup"
SCHEMAS = "experimental/evidence_lookup/schemas/"


def relative_checked(value):
    backends.require(
        isinstance(value, str) and value and not any(char in value for char in "\\:\x00")
        and all(part.rstrip(" .").casefold() not in {"", ".git"}
                and (os.name != "nt" or part == part.rstrip(" .")) for part in value.split("/")),
        "INVALID_RELATIVE_PATH",
    )
    return value


def inside_path(parent, path):
    parent, path = parent.casefold(), path.casefold()
    return path == parent or path.startswith(parent + "/")


def git(root, *args, literal=True):
    pathspec = ["--literal-pathspecs"] if literal and args[0] != "check-ignore" else []
    env = os.environ.copy()
    for name in ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS"):
        env.pop(name, None)
    return subprocess.run(["git", *pathspec, "-C", str(root), *args], env=env,
                          capture_output=True, timeout=20, check=False)


@cache
def unicode_case_spellings():
    # Git pathspec icase handles ASCII; match the same Unicode case folding as the read guard.
    spellings = defaultdict(list)
    for value in range(128, sys.maxunicode + 1):
        character = chr(value)
        folded = character.casefold()
        if character != folded:
            spellings[folded].append(character)
    return spellings, max(map(len, spellings))


def protected_pathspecs(path):
    normalized = path.casefold()
    alternates, longest = unicode_case_spellings()
    prefixes = [{""}, *(set() for _ in normalized)]
    for offset, character in enumerate(normalized):
        prefixes[offset + 1].update(prefix + character for prefix in prefixes[offset])
        for end in range(offset + 1, min(offset + longest, len(normalized)) + 1):
            variants = alternates.get(normalized[offset:end], ())
            prefixes[end].update(prefix + variant for prefix in prefixes[offset] for variant in variants)
            backends.require(len(prefixes[end]) <= 128, "PROTECTED_PATHSPEC_LIMIT")
    return [f":(top,exclude,literal,icase){value}" for value in sorted(prefixes[-1])]


def tracked(root, roots, *, excluded=()):
    includes = [f":(top,literal){path}" for path in roots]
    excludes = [spec for path in excluded if any(inside_path(root, path) for root in roots)
                for spec in protected_pathspecs(path)]
    result = git(root, "ls-files", "-z", "--", *includes, *excludes, literal=False)
    backends.require(result.returncode == 0, "TRACKED_SOURCE_LIST_UNAVAILABLE")
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def document_sources(boundary, roots, suffix, *, target=None):
    core_rel = CORE.relative_to(boundary.consumer_root).as_posix()
    protected = tuple(Path(path).as_posix() for path in boundary.protected_paths
                      if Path(path) != Path(core_rel))
    requested_paths = roots if target is None else [*roots, target]
    backends.require(not any(inside_path(path, requested) for requested in requested_paths for path in protected),
                     "PROTECTED_SOURCE")
    core_inputs = [path[len(core_rel) + 1:] for path in roots if inside_path(core_rel, path)]
    allowed_core = {"PROJECT_RULES.md", "README.md", "docs", "rules", "src"}
    boundary_clients = {"experimental/evidence_lookup/__main__.py", "experimental/shared_data/cli.py"} if suffix == ".py" else set()
    if core_inputs:
        backends.require(boundary.host_baseline is None and all(
            path.split("/", 1)[0] in allowed_core or path in boundary_clients for path in core_inputs
        ), "CORE_SOURCE_SCOPE_REJECTED")
    local_roots = [path for path in roots if not inside_path(core_rel, path)]
    excluded = (*protected, core_rel)
    paths = [path for path in tracked(boundary.consumer_root, local_roots, excluded=excluded)
             if not inside_path(core_rel, path)] if local_roots else []
    partial = False
    if core_inputs:
        try:
            paths.extend(core_rel + "/" + path for path in tracked(CORE, core_inputs))
        except backends.Rejected as exc:
            if exc.code != "TRACKED_SOURCE_LIST_UNAVAILABLE":
                raise
            partial = True
            paths.extend(core_rel + "/" + path for path in core_inputs if path.endswith(".md"))
    files = {}
    total = 0
    for path in sorted(set(paths)):
        relative_checked(path)
        if not path.endswith(suffix) or any(inside_path(item, path) for item in protected):
            continue
        if any(word in path.casefold() for word in ("credentials", "cookie", "private-key", "auth.json")):
            continue
        source = boundary.consumer_root / path
        data, signature = backends.safe_read(source)
        total += len(data)
        backends.require(total <= 4 * backends.MAX_FILE, "SOURCE_LIMIT")
        files[path] = (data, signature)
    return files, partial


def cache_directory(boundary):
    root = boundary.consumer_root
    location, = boundary.write_paths
    ignored = git(root, "check-ignore", "-q", "--", location + "/")
    staged = git(root, "ls-files", "-z", "--", location)
    backends.require(ignored.returncode == 0 and staged.returncode == 0 and not staged.stdout,
                     "CACHE_MUST_BE_GIT_IGNORED")
    path = root
    for part in PurePosixPath(location).parts:
        path /= part
        path.mkdir(exist_ok=True)
        backends.no_links(path)
    return path


def invoke(consumer_root, request):
    required = {"tool", "target", "source_roots", "executable", "cache"}
    backends.require(isinstance(request, dict) and required <= request.keys()
                     and request.keys() <= required | {"include_call_sites"}, "REQUEST_FIELDS")
    tool, target, roots, executable = (request[k] for k in ("tool", "target", "source_roots", "executable"))
    backends.require(tool in ("obsidian", "graphify") and isinstance(roots, list) and 0 < len(roots) <= 40,
                     "REQUEST_VALUES")
    include_call_sites = request.get("include_call_sites", False)
    backends.require(type(include_call_sites) is bool and (not include_call_sites or tool == "graphify"),
                     "REQUEST_VALUES")
    roots = [relative_checked(path) for path in roots]
    cache = relative_checked(request["cache"])
    if tool == "obsidian":
        relative_checked(target)
        backends.require(target.endswith(".md"), "MARKDOWN_NOTE_REQUIRED")
    else:
        backends.require(isinstance(target, str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", target)
                         and len(target) <= 128, "INVALID_SYMBOL")
    backends.require(executable is None or (isinstance(executable, str) and Path(executable).is_absolute()),
                     "ABSOLUTE_EXECUTABLE_REQUIRED")
    backends.no_links(consumer_root)
    return lookup_with_boundary(consumer_root, cache, tool, target, roots, executable, include_call_sites)


def lookup_with_boundary(consumer_root, cache, tool, target, roots, executable, include_call_sites):
    boundary = prepare_consumer_runtime_boundary(CORE, consumer_root, capability_id=CAPABILITY,
                                                 write_paths=(cache,), reject_write_path_links=True)
    try:
        backends.require(boundary.write_paths == (cache,), "CACHE_PATH_ALIAS_REJECTED")
        snapshots, partial = document_sources(boundary, roots, ".md" if tool == "obsidian" else ".py",
                                              target=target if tool == "obsidian" else None)
        data = {path: snapshot[0] for path, snapshot in snapshots.items()}
        if tool == "obsidian":
            backends.require(target in data, "NOTE_NOT_IN_SCOPE")
        reason = "CORE_FILE_LIST_UNAVAILABLE" if partial else "TOOL_NOT_CONFIGURED"
        result = None
        mode = None
        if executable is not None and not partial:
            local_cache = cache_directory(boundary)
            obsidian_request = None
            try:
                if tool == "obsidian":
                    obsidian_request = obsidian_session.Request(executable)
                    with TemporaryDirectory(dir=local_cache, prefix=f"{tool}-") as temp:
                        result = obsidian_request.lookup(data, target, Path(temp))
                    mode = "cold_obsidian"
                else:
                    with TemporaryDirectory(dir=local_cache, prefix=f"{tool}-") as temp:
                        result, mode = backends.graphify(data, target, executable, Path(temp), local_cache)
            except (backends.Rejected, OSError, subprocess.SubprocessError, ValueError, SyntaxError) as exc:
                reason = getattr(exc, "code", type(exc).__name__)
            finally:
                if obsidian_request is not None:
                    obsidian_request.close()
        backend = tool
        if result is None:
            backend = "markdown" if tool == "obsidian" else "python"
            mode = f"{backend}_fallback"
            result = (backends.markdown_backlinks(data, target) if tool == "obsidian"
                      else backends.python_definitions(data, target))
        for path, (_, signature) in snapshots.items():
            source = boundary.consumer_root / path
            backends.no_links(source)
            backends.require(backends.path_signature(source.stat()) == signature, "SOURCE_CHANGED")
        truncated = len(result) > (16000 if isinstance(result, str) else 100)
        response = {"ok": True, "backend": backend, "execution_mode": mode,
                    "fallback_reason": reason if backend != tool else None,
                    "partial": partial, "truncated": truncated,
                    "result": result[:16000] if isinstance(result, str) else result[:100]}
        if include_call_sites:
            matches, incomplete = backends.python_call_sites(data, target)
            response["call_sites"] = {"matches": matches, "incomplete": partial or incomplete}
        return response
    finally:
        require_consumer_runtime_boundary_unchanged(boundary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info")
    invoke_args = commands.add_parser("invoke")
    invoke_args.add_argument("--consumer-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "info":
            baseline = capture_static_discovery_baseline(CORE)
            try:
                output = {"ok": True, "capability": CAPABILITY, "capability_version": 1,
                          "commands": ["info", "invoke"],
                          "request_schema": SCHEMAS + "request-v1.schema.json",
                          "result_schema": SCHEMAS + "result-v1.schema.json"}
            finally:
                require_static_discovery_unchanged(CORE, baseline)
        else:
            raw = sys.stdin.buffer.read(65537)
            backends.require(len(raw) <= 65536, "REQUEST_LIMIT")
            root = Path(os.path.abspath(args.consumer_root))
            output = invoke(root, json.loads(raw.decode("utf-8")))
    except (RuntimeBoundaryError, backends.Rejected, OSError, ValueError, subprocess.SubprocessError) as exc:
        output = {"ok": False, "error": getattr(exc, "code", str(exc))}
    print(json.dumps(output, ensure_ascii=True))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
