"""Isolated package deployment and failure tests, never real personal-skill roots."""

from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/install-common-skills/current/scripts/manage_common_skills.py"
API = runpy.run_path(str(TOOL))
plan = API["make_plan"]
apply = API["apply_plan"]
NAME = "review-chat-session"


class CommonSkillInstallationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="common-skills-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.core = self.base / "core source"
        shutil.copytree(ROOT / "skills", self.core / "skills")
        self.target = self.base / "personal skills"

    def catalog(self, mutate):
        path = self.core / "skills/INSTALLATION.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_bytes(API["encoded"](data))

    def install(self, agent="codex"):
        value, _ = plan(self.core, self.target, agent)
        return apply(self.core, self.target, agent, value["plan_id"])

    def bytes_at(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def test_catalog_classification_and_standalone_packages(self):
        from test_skills import entries
        data = json.loads((ROOT / "skills/INSTALLATION.json").read_text(encoding="utf-8"))
        public = {row[0] for row in entries(ROOT)}
        self.assertEqual(set(data["skills"]), public)
        self.assertEqual({name for name, spec in data["skills"].items() if spec["scope"] == "common"}, {NAME})
        for name in public - {NAME}:
            self.assertEqual(data["skills"][name], {"scope": "project"})
        for agent in ("codex", "claude"):
            target = self.base / agent
            before = self.bytes_at(self.core)
            value, _ = plan(self.core, target, agent)
            self.assertFalse(target.exists())
            self.assertEqual([row["name"] for row in value["skills"]], [NAME])
            result = apply(self.core, target, agent, value["plan_id"])
            self.assertFalse(result["blocked"])
            installed = target / NAME
            # All runtime references remain available after removing the input Core.
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "references/report.md").is_file())
            self.assertEqual((installed / "agents/openai.yaml").exists(), agent == "codex")
            self.assertEqual(before, self.bytes_at(self.core))
            from test_skills import LINK
            for document in installed.rglob("*.md"):
                for link in LINK.findall(document.read_text(encoding="utf-8")):
                    self.assertFalse(link.startswith(("http:", "https:")))
                    resolved = (document.parent / link).resolve()
                    resolved.relative_to(installed.resolve())
                    self.assertTrue(resolved.is_file())
        shutil.rmtree(self.core)
        self.assertTrue((self.base / "codex" / NAME / "references/report.md").is_file())

    def test_authored_entrypoints_and_invocation_metadata(self):
        from test_skills import frontmatter, openai_fields
        for name in (NAME, "install-common-skills"):
            fields, body = frontmatter((ROOT / f"skills/{name}/current/SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(set(fields), {"name", "description"})
            self.assertEqual(fields["name"], name)
            self.assertIsInstance(fields["description"], str)
            self.assertTrue(1 <= len(fields["description"]) <= 1024)
            self.assertNotIn("[TODO:", body)
            metadata = openai_fields((ROOT / f"skills/{name}/codex/agents/openai.yaml").read_text(encoding="utf-8"))
            self.assertTrue(metadata["policy"]["allow_implicit_invocation"])
            self.assertIn(f"${name}", metadata["interface"]["default_prompt"])

    def test_repeated_install_is_noop(self):
        self.install()
        before = self.bytes_at(self.target)
        stamps = {str(path): path.stat().st_mtime_ns for path in self.target.rglob("*") if path.is_file()}
        result = self.install()
        self.assertEqual(result["results"], [{"name": NAME, "result": "current"}])
        self.assertEqual(before, self.bytes_at(self.target))
        self.assertEqual(stamps, {str(path): path.stat().st_mtime_ns for path in self.target.rglob("*") if path.is_file()})

    def test_update_removes_stale_managed_files_and_keeps_unrelated_skills(self):
        self.catalog(lambda data: data["skills"][NAME].update(version="0.9.0"))
        old = self.core / f"skills/{NAME}/current/obsolete.txt"
        old.write_bytes(b"old managed content")
        self.catalog(lambda data: data["skills"][NAME]["files"].update({"obsolete.txt": f"skills/{NAME}/current/obsolete.txt"}))
        self.install()
        unrelated = self.target / "handoff-manager"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_bytes(b"user customized project skill")
        self.catalog(lambda data: data["skills"][NAME].update(version="1.0.0"))
        self.catalog(lambda data: data["skills"][NAME]["files"].pop("obsolete.txt"))
        result = self.install()
        self.assertEqual(result["results"][0]["result"], "updated")
        self.assertTrue(result["results"][0]["old_package_removed"])
        self.assertFalse((self.target / NAME / "obsolete.txt").exists())
        self.assertEqual((unrelated / "SKILL.md").read_bytes(), b"user customized project skill")
        self.assertEqual(sorted(path.name for path in self.target.iterdir()), ["handoff-manager", NAME])

    def test_newer_is_preserved_and_downgrade_not_applied(self):
        self.catalog(lambda data: data["skills"][NAME].update(version="9.0.0"))
        self.install()
        before = self.bytes_at(self.target)
        self.catalog(lambda data: data["skills"][NAME].update(version="1.0.0"))
        result = self.install()
        self.assertEqual(result["results"][0]["result"], "newer")
        self.assertEqual(before, self.bytes_at(self.target))

    def test_user_changes_foreign_receipts_and_extras_are_preserved(self):
        for case in ("edit", "extra", "empty-dir", "foreign", "no-receipt", "same-version-drift"):
            with self.subTest(case=case):
                self.target = self.base / case
                self.install()
                folder = self.target / NAME
                if case == "edit":
                    (folder / "SKILL.md").write_bytes(b"user change")
                elif case == "extra":
                    (folder / "user.txt").write_bytes(b"unique")
                elif case == "empty-dir":
                    (folder / "personal").mkdir()
                elif case == "foreign":
                    receipt = json.loads((folder / API["RECEIPT"]).read_text(encoding="utf-8"))
                    receipt["provider"] = "other"
                    (folder / API["RECEIPT"]).write_bytes(API["encoded"](receipt))
                elif case == "no-receipt":
                    (folder / API["RECEIPT"]).unlink()
                else:
                    source = self.core / f"skills/{NAME}/current/SKILL.md"
                    source.write_bytes(source.read_bytes() + b"\nchanged without version bump\n")
                before = self.bytes_at(self.target)
                result = self.install()
                self.assertTrue(result["blocked"])
                self.assertEqual(result["results"][0]["result"], "conflict")
                self.assertEqual(before, self.bytes_at(self.target))

    def test_unclassified_internal_and_project_entries_are_not_installed(self):
        self.catalog(lambda data: data["skills"].update({"private-helper": {"scope": "internal"}}))
        value, _ = plan(self.core, self.target, "codex")
        self.assertEqual([row["name"] for row in value["skills"]], [NAME])
        self.catalog(lambda data: data["skills"]["private-helper"].pop("scope"))
        with self.assertRaises(ValueError):
            plan(self.core, self.target, "codex")
        self.assertFalse(self.target.exists())

    def test_bad_paths_and_versions_fail_without_writes(self):
        original = (self.core / "skills/INSTALLATION.json").read_bytes()
        for key, value in (("version", "1.0"), ("version", "01.0.0"),
                           ("files", {"SKILL.md": "../outside"}),
                           ("files", {"../escape": f"skills/{NAME}/current/SKILL.md", "SKILL.md": f"skills/{NAME}/current/SKILL.md"}),
                           ("files", {"SKILL.md": "skills/session-close/current/SKILL.md"})):
            with self.subTest(value=value):
                (self.core / "skills/INSTALLATION.json").write_bytes(original)
                self.catalog(lambda data: data["skills"][NAME].update({key: value}))
                with self.assertRaises(ValueError):
                    plan(self.core, self.target, "codex")
                self.assertFalse(self.target.exists())
        with self.assertRaises(ValueError):
            plan(self.core, self.core / "personal", "codex")

    def test_plan_change_and_busy_lock_do_not_modify_installed_files(self):
        value, _ = plan(self.core, self.target, "codex")
        self.catalog(lambda data: data["skills"][NAME].update(version="1.1.0"))
        with self.assertRaisesRegex(ValueError, "stale plan"):
            apply(self.core, self.target, "codex", value["plan_id"])
        self.assertFalse(self.target.exists())
        self.install()
        value, _ = plan(self.core, self.target, "codex")
        lock = self.target / ".agent-core-install.lock"
        lock.write_bytes(b"other invocation")
        before = self.bytes_at(self.target)
        with self.assertRaises(FileExistsError):
            apply(self.core, self.target, "codex", value["plan_id"])
        self.assertEqual(before, self.bytes_at(self.target))

    def test_installation_failure_restores_previous_package(self):
        self.install()
        before = self.bytes_at(self.target)
        self.catalog(lambda data: data["skills"][NAME].update(version="1.1.0"))
        value, _ = plan(self.core, self.target, "codex")
        rename = Path.rename
        def fail_stage(path, destination):
            if path.name.startswith(".agent-core-") and not path.name.endswith("-previous"):
                raise OSError("injected new package activation failure")
            return rename(path, destination)
        with patch.object(Path, "rename", fail_stage):
            with self.assertRaisesRegex(OSError, "activation failure"):
                apply(self.core, self.target, "codex", value["plan_id"])
        self.assertEqual(before, self.bytes_at(self.target))
        self.assertEqual([path.name for path in self.target.iterdir()], [NAME])

    def test_post_activation_failure_restores_previous_verified_package(self):
        self.install()
        before = self.bytes_at(self.target)
        self.catalog(lambda data: data["skills"][NAME].update(version="1.1.0"))
        value, _ = plan(self.core, self.target, "codex")
        namespace = apply.__globals__
        original = namespace["package_snapshot"]
        injected = False
        def fail_once(path, expected):
            nonlocal injected
            if path == self.target / NAME and json.loads((path / API["RECEIPT"]).read_text(encoding="utf-8"))["version"] == "1.1.0" and not injected:
                injected = True
                raise OSError("injected post-activation verification failure")
            return original(path, expected)
        with patch.dict(namespace, {"package_snapshot": fail_once}):
            with self.assertRaises(API["DeploymentFailure"]) as caught:
                apply(self.core, self.target, "codex", value["plan_id"])
        self.assertEqual(caught.exception.recovery["rollback_result"], "restored")
        self.assertEqual(before, self.bytes_at(self.target))

    def test_partial_write_and_old_cleanup_errors_report_recovery_and_block_retry(self):
        for case in ("partial-write", "old-cleanup"):
            with self.subTest(case=case):
                self.target = self.base / case
                self.install()
                old_content = (self.target / NAME / "SKILL.md").read_bytes()
                self.catalog(lambda data: data["skills"][NAME].update(version="1.1.0" if case == "partial-write" else "1.2.0"))
                value, _ = plan(self.core, self.target, "codex")
                if case == "partial-write":
                    write = Path.write_bytes
                    def fail_write(path, data):
                        if path.name == "SKILL.md" and path.parent.name.startswith(".agent-core-"):
                            write(path, data[:10])
                            raise OSError("injected disk full")
                        return write(path, data)
                    context = patch.object(Path, "write_bytes", fail_write)
                else:
                    remove = shutil.rmtree
                    def fail_cleanup(path, *args, **kwargs):
                        if Path(path).name.endswith("-previous"):
                            raise OSError("injected old cleanup failure")
                        return remove(path, *args, **kwargs)
                    context = patch.object(shutil, "rmtree", fail_cleanup)
                with context:
                    with self.assertRaises(API["DeploymentFailure"]) as caught:
                        apply(self.core, self.target, "codex", value["plan_id"])
                recovery = caught.exception.recovery
                self.assertTrue(Path(recovery["recovery_path"]).is_file())
                if case == "partial-write":
                    self.assertEqual((self.target / NAME / "SKILL.md").read_bytes(), old_content)
                    self.assertTrue(Path(recovery["stage_path"]).exists())
                else:
                    self.assertEqual(recovery["active_state"], "new_verified")
                    self.assertTrue(Path(recovery["previous_path"]).exists())
                next_plan, _ = plan(self.core, self.target, "codex")
                self.assertEqual(next_plan["skills"][0]["action"], "conflict")
                self.assertIn("recovery_path", next_plan["skills"][0])

    def test_cli_plan_apply_and_errors(self):
        command = [sys.executable, "-B", str(TOOL), "--core-root", str(self.core),
                   "--target-root", str(self.target), "--agent", "claude"]
        planned = subprocess.run(command, capture_output=True, check=True, encoding="utf-8")
        value = json.loads(planned.stdout)
        self.assertFalse(self.target.exists())
        applied = subprocess.run(command + ["--apply", "--plan-id", value["plan_id"]],
                                 capture_output=True, check=True, encoding="utf-8")
        self.assertEqual(json.loads(applied.stdout)["results"][0]["result"], "installed")
        stale = subprocess.run(command + ["--apply", "--plan-id", value["plan_id"]],
                               capture_output=True, encoding="utf-8")
        self.assertEqual(stale.returncode, 2)
        self.assertEqual(json.loads(stale.stdout)["status"], "error")

    @unittest.skipUnless(os.name == "nt", "Windows reparse point fixture")
    def test_windows_junction_is_rejected(self):
        outside = self.base / "outside junction target"
        outside.mkdir()
        sentinel = outside / "user.txt"
        sentinel.write_bytes(b"preserve")
        created = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(self.target), str(outside)],
                                 capture_output=True)
        if created.returncode:
            self.skipTest("OS did not allow creation of junction fixture")
        with self.assertRaises(ValueError):
            plan(self.core, self.target, "codex")
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_linked_paths_are_rejected_without_touching_target(self):
        outside = self.base / "outside"
        outside.mkdir()
        try:
            self.target.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("OS did not allow creation of this symlink fixture")
        with self.assertRaises(ValueError):
            plan(self.core, self.target, "codex")
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
