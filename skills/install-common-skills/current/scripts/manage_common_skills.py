"""Explicit common-skill deployment helper; no network, Core writes or implicit roots.

Plan by default. Apply requires the exact plan ID and an authorized target root.
Receipts track local ownership, not authenticity or filesystem isolation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile

RECEIPT = ".agent-core-install.json"
PROVIDER = "agent-core"
NAME = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


class DeploymentFailure(OSError):
    def __init__(self, cause, recovery):
        super().__init__(str(cause))
        self.recovery = recovery


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("invalid relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).is_absolute():
        raise ValueError("unsafe relative path")
    return value


def plain(path):
    """Reject links/reparse points in existing ancestors, including Windows junctions."""
    path = Path(os.path.abspath(path))
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symlink/reparse path is not supported")
    return path


def version(value):
    if not isinstance(value, str) or VERSION.fullmatch(value) is None:
        raise ValueError("expected stable MAJOR.MINOR.PATCH version")
    return tuple(int(item) for item in value.split("."))


def files_at(root):
    plain(root)
    if not root.is_dir():
        raise ValueError("expected package directory")
    files = {}
    directories = set()
    for parent, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = plain(Path(parent) / name)
            info = path.lstat()
            rel = path.relative_to(root).as_posix()
            if stat.S_ISREG(info.st_mode):
                files[rel] = path
            elif stat.S_ISDIR(info.st_mode):
                directories.add(rel)
            else:
                raise ValueError("non-regular package entry")
    return files, directories


def hashes(payload):
    return {key: digest(value) for key, value in sorted(payload.items())}


def package_snapshot(root, expected):
    files, directories = files_at(root)
    allowed_dirs = {parent.as_posix() for key in expected for parent in PurePosixPath(key).parents
                    if parent.as_posix() != "."}
    if set(files) != set(expected) or directories != allowed_dirs:
        raise ValueError("unmanaged, missing or extra package entries")
    actual = {key: digest(path.read_bytes()) for key, path in sorted(files.items())}
    if actual != expected:
        raise ValueError("managed files were modified")
    return digest(encoded(actual))


def load_packages(core, agent):
    core = plain(core)
    data = read_json(plain(core / "skills/INSTALLATION.json"))
    if (set(data) != {"format_version", "provider", "skills"}
            or type(data["format_version"]) is not int or data["format_version"] != 1
            or data["provider"] != PROVIDER or not isinstance(data["skills"], dict)):
        raise ValueError("invalid installation catalog")
    packages = {}
    for name, spec in data["skills"].items():
        if NAME.fullmatch(name) is None or not isinstance(spec, dict):
            raise ValueError("invalid skill declaration")
        scope = spec.get("scope")
        if scope not in {"common", "project", "internal"}:
            raise ValueError("missing or invalid installation scope")
        if scope != "common":
            if set(spec) != {"scope"}:
                raise ValueError("non-common entry must not contain install payload")
            continue
        if set(spec) != {"scope", "version", "files", "agent_files"}:
            raise ValueError("invalid common entry")
        version(spec["version"])
        if (not isinstance(spec["files"], dict) or "SKILL.md" not in spec["files"]
                or not isinstance(spec["agent_files"], dict)
                or set(spec["agent_files"]) != {"codex", "claude"}):
            raise ValueError("missing common package entrypoint or agent map")
        extra = spec["agent_files"][agent]
        if not isinstance(extra, dict) or set(extra) & set(spec["files"]):
            raise ValueError("duplicate package destinations")
        payload = {}
        for destination, source in {**spec["files"], **extra}.items():
            relative(destination)
            relative(source)
            if destination == RECEIPT or not source.startswith(f"skills/{name}/"):
                raise ValueError("foreign source owner or reserved destination")
            path = plain(core / source)
            path.relative_to(core)
            if not path.is_file():
                raise ValueError("missing package file")
            payload[destination] = path.read_bytes()
        # Explicit map only: never recursively ship source trees or a whole Core.
        for key in payload:
            if any(parent.as_posix() in payload for parent in PurePosixPath(key).parents):
                raise ValueError("file/directory collision")
        receipt = {"format_version": 1, "provider": PROVIDER, "name": name, "agent": agent,
                   "version": spec["version"], "files": hashes(payload)}
        payload[RECEIPT] = encoded(receipt)
        packages[name] = (spec["version"], payload)
    return packages


def inspect_package(path, name, agent, desired_version, payload):
    result = {"name": name, "target": str(path), "desired_version": desired_version,
              "payload_hash": digest(encoded(hashes(payload)))}
    try:
        recovery = path.parent / f".agent-core-{name}.recovery.json"
        if recovery.exists() or recovery.is_symlink():
            return {**result, "action": "conflict", "reason": "previous deployment needs recovery",
                    "recovery_path": str(recovery)}
        plain(path)
        if not path.exists():
            return {**result, "action": "install", "snapshot": None}
        receipt = read_json(plain(path / RECEIPT))
        if (set(receipt) != {"format_version", "provider", "name", "agent", "version", "files"}
                or type(receipt["format_version"]) is not int or receipt["format_version"] != 1
                or receipt["provider"] != PROVIDER or receipt["name"] != name or receipt["agent"] != agent
                or not isinstance(receipt["files"], dict) or "SKILL.md" not in receipt["files"]):
            raise ValueError("foreign or invalid receipt")
        for key, value in receipt["files"].items():
            relative(key)
            if key == RECEIPT or not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
                raise ValueError("invalid receipt file map")
        expected = {**receipt["files"], RECEIPT: digest((path / RECEIPT).read_bytes())}
        snapshot = package_snapshot(path, expected)
        installed = version(receipt["version"])
        desired = version(desired_version)
        action = "update" if installed < desired else "newer" if installed > desired else "current"
        if action == "current" and expected != hashes(payload):
            raise ValueError("same version has different content")
        return {**result, "action": action, "installed_version": receipt["version"], "snapshot": snapshot}
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return {**result, "action": "conflict", "reason": str(exc)}


def make_plan(core, target, agent):
    core, target = plain(core), plain(target)
    if (core == target or core in target.parents or target in core.parents
            or target == Path(target.anchor)):
        raise ValueError("target must be a separate personal skill root")
    packages = load_packages(core, agent)
    rows = [inspect_package(target / name, name, agent, ver, payload)
            for name, (ver, payload) in sorted(packages.items())]
    value = {"core_root": str(core), "target_root": str(target), "agent": agent, "skills": rows}
    return {**value, "plan_id": digest(encoded(value))}, packages


def remove_exact(root, path, expected):
    """Delete only an invocation-created direct child with revalidated contents."""
    root, path = plain(root), plain(path)
    if path.parent != root or path == root:
        raise ValueError("cleanup escaped target root")
    package_snapshot(path, expected)
    shutil.rmtree(path)


def deploy(target, row, payload):
    name = row["name"]
    dest = target / name
    expected_new = hashes(payload)
    stage = Path(tempfile.mkdtemp(prefix=f".agent-core-{name}-", dir=target))
    old = None
    phase = "prepare"
    previous_expected = None
    try:
        for key, content in payload.items():
            path = stage / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        package_snapshot(stage, expected_new)
        if row["action"] == "update":
            old_files, _ = files_at(dest)
            expected_old = {key: digest(path.read_bytes()) for key, path in old_files.items()}
            previous_expected = expected_old
            if digest(encoded(expected_old)) != row["snapshot"]:
                raise ValueError("installed package changed before replacement")
            old = stage.with_name(stage.name + "-previous")
            if old.exists():
                raise ValueError("recovery path already exists")
            dest.rename(old)
        elif dest.exists():
            raise ValueError("destination appeared before installation")
        phase = "activate"
        stage.rename(dest)
        package_snapshot(dest, expected_new)
        phase = "cleanup"
        if old is not None:
            remove_exact(target, old, expected_old)
        return {"name": name, "result": "installed" if old is None else "updated",
                "old_package_removed": old is not None}
    except BaseException as cause:
        recovery = {"name": name, "phase": phase, "active_path": str(dest),
                    "stage_path": str(stage), "previous_path": str(old) if old else None,
                    "active_state": "unverified", "rollback_result": "not_attempted",
                    "cleanup_result": "not_attempted"}
        try:
            if old is not None and old.exists() and phase != "cleanup":
                if dest.exists():
                    # Restore only if the new directory still contains exactly our own payload.
                    # Concurrent user changes remain in place with an explicit recovery record.
                    package_snapshot(dest, expected_new)
                    if stage.exists():
                        raise ValueError("stage path occupied during rollback")
                    dest.rename(stage)
                old.rename(dest)
                package_snapshot(dest, previous_expected)
                recovery.update(active_state="previous_verified", rollback_result="restored")
            elif phase == "cleanup":
                package_snapshot(dest, expected_new)
                recovery["active_state"] = "new_verified"
            elif row["action"] == "install" and not dest.exists():
                recovery["active_state"] = "absent"
            elif phase == "prepare" and previous_expected is None and row["action"] == "update":
                recovery["active_state"] = "previous_untouched"
        except (OSError, ValueError) as exc:
            recovery["rollback_result"] = f"blocked: {exc}"
        try:
            if stage.exists():
                # Preserve corrupt/partial files rather than guessing they are safe to remove.
                remove_exact(target, stage, expected_new)
            recovery["cleanup_result"] = "stage_absent"
        except (OSError, ValueError) as exc:
            recovery["cleanup_result"] = f"retained: {exc}"
        residual = stage.exists() or (old is not None and old.exists()) or recovery["active_state"] == "unverified"
        if residual:
            marker = target / f".agent-core-{name}.recovery.json"
            recovery["recovery_path"] = str(marker)
            try:
                with marker.open("xb") as stream:
                    stream.write(encoded(recovery))
            except OSError as exc:
                recovery["record_error"] = str(exc)
        raise DeploymentFailure(cause, recovery) from cause


def apply_plan(core, target, agent, plan_id):
    initial, _ = make_plan(core, target, agent)
    if initial["plan_id"] != plan_id:
        raise ValueError("stale plan; inspect a new plan before applying")
    target = plain(target)
    target.mkdir(parents=True, exist_ok=True)
    lock = target / ".agent-core-install.lock"
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        plan, packages = make_plan(core, target, agent)
        if plan["plan_id"] != plan_id:
            raise ValueError("plan changed while acquiring installation lock")
        results = []
        for row in plan["skills"]:
            if row["action"] in {"install", "update"}:
                current, _ = make_plan(core, target, agent)
                fresh = next(item for item in current["skills"] if item["name"] == row["name"])
                if fresh != row:
                    raise ValueError("package inputs changed before deployment")
                results.append(deploy(target, row, packages[row["name"]][1]))
            else:
                results.append({"name": row["name"], "result": row["action"]})
        final, _ = make_plan(core, target, agent)
        if any(row["action"] in {"install", "update"} for row in final["skills"]):
            raise ValueError("installation did not reach the expected package state")
        return {"results": results, "state": final, "blocked": any(
            row["action"] == "conflict" for row in final["skills"])}
    finally:
        owned = os.fstat(descriptor)
        os.close(descriptor)
        try:
            current = lock.lstat()
            if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                raise ValueError("installation lock was replaced; preserving current lock")
            lock.unlink()
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-root", required=True, type=Path)
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--agent", required=True, choices=("codex", "claude"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-id")
    args = parser.parse_args()
    if not args.core_root.is_absolute() or not args.target_root.is_absolute():
        parser.error("root paths must be absolute")
    try:
        if args.apply:
            if not args.plan_id:
                parser.error("--apply requires --plan-id from a reviewed plan")
            result = apply_plan(args.core_root, args.target_root, args.agent, args.plan_id)
            status = 1 if result["blocked"] else 0
        else:
            result, _ = make_plan(args.core_root, args.target_root, args.agent)
            status = 0
        print(encoded(result).decode("utf-8"), end="")
        return status
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result = {"status": "error", "error": str(exc)}
        if isinstance(exc, DeploymentFailure):
            result["recovery"] = exc.recovery
        print(encoded(result).decode("utf-8"), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
