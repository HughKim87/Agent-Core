"""공개 ``shared_data`` v1 CLI·schema·격리 경계 회귀."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
SOURCE_ID = "123e4567-e89b-42d3-a456-426614174031"
WORK_ID = "123e4567-e89b-42d3-a456-426614174032"
STORAGE_ROOT = "runtime/public-shared-data"
PROTECTED_PATH = "sealed-material"


def make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise OSError(completed.stderr or completed.stdout)
        return
    link.symlink_to(target, target_is_directory=True)


def remove_directory_link(link: Path) -> None:
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def request_payload() -> dict:
    return {
        "desired_outcome": "공개 CLI 흐름을 검증한다.",
        "authorized_actions": ["임시 소비 데이터 쓰기"],
        "excluded_scope": ["외부 전송"],
        "input_refs": ["fixture://public-cli"],
        "protection_boundaries": ["선언된 보호 경로"],
        "required_decisions": [],
        "verification_levels": ["unit"],
    }


def configure_consumer(
    root: Path,
    *,
    contract_version: int = 2,
    required_capabilities: dict[str, int] | None = None,
    consumer_role: str = "maintainer",
) -> None:
    core_link = root / "core"
    if not core_link.exists():
        # 현재 worktree의 공개 CLI를 검증하는 합성 packaging fixture다. Host 배포·Runtime
        # 의존이나 실제 Consumer 검증 근거로 사용하지 않는다.
        shutil.copytree(
            ROOT,
            core_link,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
    (root / "rules").mkdir(exist_ok=True)
    (root / "rules" / "project.md").write_text("# fixture\n", encoding="utf-8")
    (root / "CURRENT.md").write_text("# fixture state\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# fixture entry\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# fixture entry\n", encoding="utf-8")
    contract = {
        "contract_version": contract_version,
        "consumer_role": consumer_role,
        "core_path": "core",
        "state": "CURRENT.md",
        "entry_pointers": {"codex": "AGENTS.md", "claude": "CLAUDE.md"},
        "rule_roots": ["rules"],
        "protected_paths": [PROTECTED_PATH],
        "required_core_capabilities": (
            {"shared_data": 1}
            if required_capabilities is None
            else required_capabilities
        ),
    }
    (root / "PROJECT_RULES.md").write_text(
        "# fixture policy\n\n<!-- agent-core-consumer:v1 -->\n```json\n"
        + json.dumps(contract, ensure_ascii=False, indent=2)
        + "\n```\n<!-- /agent-core-consumer:v1 -->\n",
        encoding="utf-8",
    )
    if consumer_role == "host" and not (core_link / ".git").exists():
        commands = (
            ["git", "init", "--quiet"],
            ["git", "add", "-A"],
            [
                "git",
                "-c", "user.name=Core Test",
                "-c", "user.email=core-test@example.invalid",
                "-c", "commit.gpgsign=false",
                "commit", "--quiet", "-m", "fixture",
            ],
        )
        for command in commands:
            subprocess.run(command, cwd=core_link, capture_output=True, check=True)


class PublicSharedDataCliTests(unittest.TestCase):
    def run_cli(
        self,
        root: Path | None,
        *,
        request: dict | None = None,
        raw: str | None = None,
        write: bool = False,
        info: bool = False,
        storage_root: str = STORAGE_ROOT,
        contract_version: int = 2,
        required_capabilities: dict[str, int] | None = None,
        consumer_role: str = "maintainer",
    ) -> subprocess.CompletedProcess[str]:
        if root is not None:
            configure_consumer(
                root,
                contract_version=contract_version,
                required_capabilities=required_capabilities,
                consumer_role=consumer_role,
            )
        runtime_core = root / "core" if root is not None else ROOT
        environment = os.environ.copy()
        bootstrap = (
            "import runpy,sys;"
            f"sys.path[:0]=[{str(runtime_core)!r},{str(runtime_core / 'src')!r}];"
            "runpy.run_module('experimental.shared_data',run_name='__main__',alter_sys=True)"
        )
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-B", "-I", "-c", bootstrap]
        if info:
            command.append("info")
        else:
            command.extend(
                [
                    "--consumer-root", str(root),
                    "--storage-root", storage_root,
                    "--protected-path", PROTECTED_PATH,
                ]
            )
            if write:
                command.append("--write")
            command.append("invoke")
        input_text = raw if raw is not None else (
            json.dumps(request, ensure_ascii=False) if request is not None else None
        )
        return subprocess.run(
            command,
            cwd=root if root is not None else ROOT,
            env=environment,
            input=input_text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def invoke(self, root: Path, operation: str, arguments: dict, *, write: bool = False) -> dict:
        completed = self.run_cli(
            root,
            request={"operation": operation, "arguments": arguments},
            write=write,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["operation"], operation)
        return payload["result"]

    def test_info_matches_declaration_and_request_schema(self) -> None:
        from core_check.gate import capture_host_core_baseline

        before = capture_host_core_baseline(ROOT, require_clean=False)
        completed = self.run_cli(None, info=True)
        after = capture_host_core_baseline(ROOT, require_clean=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(before, after)
        info = json.loads(completed.stdout)
        from core_check.declarations import declared_compatibility

        capability = declared_compatibility(ROOT)["optional_capabilities"]["shared_data"]
        self.assertEqual(info["capability_version"], capability["version"])
        self.assertEqual(info["commands"], capability["commands"])
        self.assertEqual(info["request_schema"], capability["request_schema"])
        request_schema = json.loads((ROOT / capability["request_schema"]).read_text(encoding="utf-8"))
        self.assertEqual(info["operations"], request_schema["properties"]["operation"]["enum"])

    def test_info_fails_when_git_baseline_cannot_be_proved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-info-no-git-") as raw_root:
            completed = self.run_cli(Path(raw_root), info=True)
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1, payload)
            self.assertIn("기준선을 증명할 수 없다", payload["error"])

    def test_info_exception_still_runs_post_boundary_check(self) -> None:
        from experimental.shared_data import cli as shared_cli

        class BoundaryFailure(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix="shared-cli-info-exception-") as raw_root:
            core_root = Path(raw_root) / "core"
            fake_cli = core_root / "experimental" / "shared_data" / "cli.py"
            state = core_root / "state.txt"
            state.parent.mkdir(parents=True)
            state.write_text("before", encoding="utf-8")
            post_checked: list[bool] = []

            class BoundaryApi:
                RuntimeBoundaryError = BoundaryFailure

                @staticmethod
                def capture_static_discovery_baseline(root: Path) -> str:
                    self.assertEqual(root, core_root.resolve())
                    return state.read_text(encoding="utf-8")

                @staticmethod
                def require_static_discovery_unchanged(root: Path, baseline: str) -> None:
                    post_checked.append(True)
                    if state.read_text(encoding="utf-8") != baseline:
                        raise BoundaryFailure("mutated")

            def mutate_then_raise() -> dict:
                state.write_text("after", encoding="utf-8")
                raise RuntimeError("boom")

            with (
                patch.object(shared_cli, "__file__", str(fake_cli)),
                patch.object(shared_cli, "_runtime_boundary_api", return_value=BoundaryApi),
                patch.object(shared_cli, "_info", side_effect=mutate_then_raise),
            ):
                with self.assertRaisesRegex(shared_cli.SharedDataCliError, "mutated"):
                    shared_cli._static_discovery()
            self.assertEqual(post_checked, [True])

    def test_write_is_explicit_and_errors_are_structured(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-write-") as raw_root:
            root = Path(raw_root)
            denied = self.run_cli(
                root,
                request={"operation": "initialize", "arguments": {}},
                write=False,
            )
            payload = json.loads(denied.stdout)
            self.assertEqual(denied.returncode, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["kind"], "write_not_enabled")
            self.assertFalse((root / STORAGE_ROOT).exists())
            initialized = self.invoke(root, "initialize", {}, write=True)
            self.assertEqual(initialized["records"], f"{STORAGE_ROOT}/records")

    def test_core_storage_is_rejected_before_runtime_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-boundary-") as raw_root:
            root = Path(raw_root)
            completed = self.run_cli(
                root,
                request={"operation": "initialize", "arguments": {}},
                write=True,
                storage_root="core/forbidden-cache",
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1, payload)
            self.assertFalse(payload["ok"])
            self.assertIn("core_path", payload["error"])
            self.assertFalse((root / "core" / "forbidden-cache").exists())

    def test_runtime_boundary_canonicalizes_storage_and_protects_core(self) -> None:
        from core_check.runtime_boundary import prepare_consumer_runtime_boundary

        with tempfile.TemporaryDirectory(prefix="shared-cli-canonical-") as raw_root:
            root = Path(raw_root)
            configure_consumer(root)
            safe = root / "runtime" / "safe"
            link = root / "storage-link"
            safe.mkdir(parents=True)
            try:
                make_directory_link(link, safe)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory link를 만들 수 없다: {exc}")
            try:
                boundary = prepare_consumer_runtime_boundary(
                    root / "core",
                    root,
                    capability_id="shared_data",
                    write_paths=("storage-link",),
                )
                self.assertEqual(boundary.write_paths, ("runtime/safe",))
                self.assertIn("core", boundary.protected_paths)
            finally:
                remove_directory_link(link)

    def test_runtime_boundary_rejects_storage_under_protected_path(self) -> None:
        from core_check.runtime_boundary import (
            RuntimeBoundaryError,
            prepare_consumer_runtime_boundary,
        )

        with tempfile.TemporaryDirectory(prefix="shared-cli-protected-") as raw_root:
            root = Path(raw_root)
            configure_consumer(root)
            with self.assertRaisesRegex(RuntimeBoundaryError, "보호 경로"):
                prepare_consumer_runtime_boundary(
                    root / "core",
                    root,
                    capability_id="shared_data",
                    write_paths=(f"{PROTECTED_PATH}/runtime",),
                )

    def test_contract_version_mismatch_is_rejected_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-contract-") as raw_root:
            root = Path(raw_root)
            completed = self.run_cli(
                root,
                request={"operation": "initialize", "arguments": {}},
                write=True,
                contract_version=99,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1, payload)
            self.assertIn("contract_version", payload["error"])
            self.assertFalse((root / STORAGE_ROOT).exists())

    def test_undeclared_or_unavailable_capability_is_rejected_before_dispatch(self) -> None:
        for requirements in ({}, {"shared_data": 2}):
            with self.subTest(requirements=requirements), tempfile.TemporaryDirectory(
                prefix="shared-cli-capability-"
            ) as raw_root:
                root = Path(raw_root)
                completed = self.run_cli(
                    root,
                    request={"operation": "initialize", "arguments": {}},
                    write=True,
                    required_capabilities=requirements,
                )
                payload = json.loads(completed.stdout)
                self.assertEqual(completed.returncode, 1, payload)
                self.assertFalse((root / STORAGE_ROOT).exists())

    def test_consumer_core_check_package_cannot_shadow_runtime_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-shadow-") as raw_root:
            root = Path(raw_root)
            fake_package = root / "core_check"
            fake_package.mkdir()
            marker = root / "shadow-imported.txt"
            (fake_package / "__init__.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
                encoding="utf-8",
            )
            completed = self.run_cli(
                root,
                request={"operation": "initialize", "arguments": {}},
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1, payload)
            self.assertEqual(payload["kind"], "write_not_enabled")
            self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("git"), "Git 실행기가 없어 Host public boundary를 건너뛴다")
    def test_host_dirty_core_is_rejected_before_public_dispatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-host-") as raw_root:
            root = Path(raw_root)
            clean = self.run_cli(
                root,
                request={"operation": "initialize", "arguments": {}},
                write=True,
                storage_root="runtime/clean",
                consumer_role="host",
            )
            self.assertEqual(clean.returncode, 0, clean.stdout)

            (root / "core" / "unexpected-empty-cache").mkdir()
            blocked = self.run_cli(
                root,
                request={"operation": "initialize", "arguments": {}},
                write=True,
                storage_root="runtime/blocked",
                consumer_role="host",
            )
            payload = json.loads(blocked.stdout)
            self.assertEqual(blocked.returncode, 1, payload)
            self.assertIn("Host Core 읽기 전용 사전 검사 실패", payload["error"])
            self.assertFalse((root / "runtime" / "blocked").exists())

    def test_invoke_exception_still_runs_host_post_boundary_check(self) -> None:
        from experimental.shared_data import cli as shared_cli

        with tempfile.TemporaryDirectory(prefix="shared-cli-host-post-") as raw_root:
            root = Path(raw_root)
            marker = root / "core-mutated.txt"
            post_checked: list[bool] = []
            boundary = type(
                "HostBoundary",
                (),
                {
                    "write_paths": ("runtime/data",),
                    "protected_paths": (),
                    "host_baseline": ("tree", "git", True),
                },
            )()

            class MutatingDispatcher:
                def __init__(self, **_: object) -> None:
                    pass

                def dispatch(self, operation: str, arguments: dict) -> None:
                    marker.write_text("mutated", encoding="utf-8")
                    raise RuntimeError("dispatch failed")

            def reject_mutation(candidate: object) -> None:
                self.assertIs(candidate, boundary)
                post_checked.append(True)
                if marker.exists():
                    raise shared_cli.SharedDataCliError("Host Core 사후 불변 검사 실패")

            emitted: list[dict] = []
            with (
                patch.object(shared_cli, "_read_request", return_value=("initialize", {})),
                patch.object(shared_cli, "_prepare_runtime_boundary", return_value=boundary),
                patch.object(shared_cli, "Dispatcher", MutatingDispatcher),
                patch.object(
                    shared_cli,
                    "_require_runtime_boundary_unchanged",
                    side_effect=reject_mutation,
                ),
                patch.object(shared_cli, "_emit", side_effect=lambda payload: emitted.append(dict(payload))),
            ):
                code = shared_cli.main(
                    [
                        "--consumer-root", str(root),
                        "--storage-root", "runtime/data",
                        "invoke",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertEqual(post_checked, [True])
            self.assertIn("사후 불변", emitted[0]["error"])

    def test_source_lifecycle_context_and_work_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-flow-") as raw_root:
            root = Path(raw_root)
            self.invoke(root, "initialize", {}, write=True)
            source = self.invoke(
                root,
                "source.create",
                {
                    "source_kind": "user_statement",
                    "locator": "request://public-cli",
                    "evidence_role": "primary",
                    "verification_status": "verified",
                    "record_id": SOURCE_ID,
                    "timestamp": "2026-08-20T01:00:00Z",
                },
                write=True,
            )
            state = self.invoke(
                root,
                "lifecycle.register",
                {
                    "target_id": SOURCE_ID,
                    "initial_state": "current",
                    "actor": "agent:test",
                    "approval_kind": "standing_policy",
                    "reason": "공개 CLI 검증",
                    "timestamp": "2026-08-20T01:01:00Z",
                },
                write=True,
            )
            package = self.invoke(
                root,
                "context.build",
                {"purpose": "공개 current source", "record_ids": [SOURCE_ID]},
            )
            repeated = self.invoke(
                root,
                "context.build",
                {"purpose": "공개 current source", "record_ids": [SOURCE_ID]},
            )
            self.assertEqual(package, repeated)
            self.assertEqual(package["selected"][0]["record_id"], source["id"])
            self.assertEqual(state["payload"]["state"], "current")
            work = self.invoke(
                root,
                "work.create",
                {
                    "request": request_payload(),
                    "actor": "user:test",
                    "next_action": "검증 시작",
                    "work_id": WORK_ID,
                    "timestamp": "2026-08-20T01:02:00Z",
                },
                write=True,
            )
            shown = self.invoke(root, "work.get", {"work_id": WORK_ID})
            self.assertEqual(shown, work)

    def test_strict_request_and_protected_design_fail_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shared-cli-invalid-") as raw_root:
            root = Path(raw_root)
            duplicate = self.run_cli(
                root,
                raw='{"operation":"initialize","operation":"source.list","arguments":{}}',
            )
            payload = json.loads(duplicate.stdout)
            self.assertEqual(duplicate.returncode, 1)
            self.assertEqual(payload["kind"], "shared_data_cli_error")
            self.assertNotIn("Traceback", duplicate.stderr)
            protected = self.run_cli(
                root,
                request={
                    "operation": "execution.fingerprint",
                    "arguments": {"design_ref": f"{PROTECTED_PATH}/phase.md"},
                },
            )
            protected_payload = json.loads(protected.stdout)
            self.assertEqual(protected.returncode, 1)
            self.assertFalse(protected_payload["ok"])
            self.assertNotIn("Traceback", protected.stderr)


if __name__ == "__main__":
    unittest.main()
