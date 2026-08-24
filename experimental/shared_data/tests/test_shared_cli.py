"""공개 ``shared_data`` v1 CLI·schema·격리 경계 회귀."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
SOURCE_ID = "123e4567-e89b-42d3-a456-426614174031"
WORK_ID = "123e4567-e89b-42d3-a456-426614174032"
STORAGE_ROOT = "runtime/public-shared-data"
PROTECTED_PATH = "sealed-material"


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


class PublicSharedDataCliTests(unittest.TestCase):
    def run_cli(
        self,
        root: Path | None,
        *,
        request: dict | None = None,
        raw: str | None = None,
        write: bool = False,
        info: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-B", "-m", "experimental.shared_data"]
        if info:
            command.append("info")
        else:
            command.extend(
                [
                    "--consumer-root", str(root),
                    "--storage-root", STORAGE_ROOT,
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
            cwd=ROOT,
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
        completed = self.run_cli(None, info=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        info = json.loads(completed.stdout)
        from core_check.declarations import declared_compatibility

        capability = declared_compatibility(ROOT)["optional_capabilities"]["shared_data"]
        self.assertEqual(info["capability_version"], capability["version"])
        self.assertEqual(info["commands"], capability["commands"])
        self.assertEqual(info["request_schema"], capability["request_schema"])
        request_schema = json.loads((ROOT / capability["request_schema"]).read_text(encoding="utf-8"))
        self.assertEqual(info["operations"], request_schema["properties"]["operation"]["enum"])

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
