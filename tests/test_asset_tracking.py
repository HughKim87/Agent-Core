"""Exercise the installed helper's CLI against isolated worktrees and ordinary folders."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


CORE = Path(__file__).resolve().parents[1]
HELPER = CORE / "skills/review-asset-tracking/current/scripts/inspect_git_paths.py"


@unittest.skipUnless(shutil.which("git"), "Requires the Git CLI")
class AssetTrackingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="asset-tracking-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "example project"
        self.root.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, PYTHONUTF8="1")

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments], env=self.env,
            check=True, capture_output=True,
        ).stdout

    def inspect(self, *paths, root=None):
        return subprocess.run(
            [sys.executable, "-B", str(HELPER), "--root", str(root or self.root), "--", *paths],
            env=self.env, capture_output=True, encoding="utf-8",
        )

    def test_distinguishes_index_rule_and_candidates_without_writes(self):
        self.git("init", "--quiet")
        names = ("model.bin", "원본 [1].bin", "local.bin", "keep.bin", "keepXbin", "-notes")
        for name in names:
            (self.root / name).write_bytes(b"sample")
        self.git("--literal-pathspecs", "add", "--", "원본 [1].bin")
        (self.root / ".gitignore").write_text("*.bin\n!keep.bin\n", encoding="utf-8")
        (self.root / ".git/info/exclude").write_text("-notes\n", encoding="utf-8")
        index = self.root / ".git/index"
        before = (index.read_bytes(), index.stat().st_mtime_ns, self.git("ls-files", "-z"))
        result = self.inspect(*names)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        document = json.loads(result.stdout)
        self.assertEqual(document["repository"], "git")
        rows = {row["path"]: row for row in document["files"]}
        self.assertEqual(set(rows), set(names))
        expected = {
            "model.bin": (False, False, True),
            "원본 [1].bin": (True, False, False),
            "local.bin": (False, False, True),
            "keep.bin": (False, True, False),
            "keepXbin": (False, True, False),
            "-notes": (False, False, True),
        }
        for name, values in expected.items():
            row = rows[name]
            with self.subTest(name=name):
                self.assertEqual(row["size_bytes"], 6)
                self.assertEqual((row["indexed"], row["untracked_candidate"], row["ignored"]), values)
        self.assertEqual(rows["원본 [1].bin"]["ignore_rule"]["pattern"], "*.bin")
        self.assertEqual(rows["keep.bin"]["ignore_rule"]["pattern"], "!keep.bin")
        self.assertIn("info/exclude", rows["-notes"]["ignore_rule"]["source"].replace("\\", "/"))
        self.assertEqual(before, (index.read_bytes(), index.stat().st_mtime_ns, self.git("ls-files", "-z")))

    def test_handles_existing_folder_before_init_and_broken_repository(self):
        (self.root / "model.bin").write_bytes(b"data")
        result = self.inspect("model.bin")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        document = json.loads(result.stdout)
        self.assertEqual(document["repository"], "pre_init")
        row, = document["files"]
        self.assertEqual(row["size_bytes"], 4)
        for key in ("indexed", "untracked_candidate", "ignored"):
            self.assertIsNone(row[key])
        self.assertFalse((self.root / ".git").exists())
        (self.root / ".git").write_text("gitdir: non-existent\n", encoding="utf-8")
        broken = self.inspect("model.bin")
        self.assertNotEqual(broken.returncode, 0)

    def test_case_variants_cannot_hide_an_indexed_file(self):
        original = self.root / "original.bin"
        alternate = self.root / "ORIGINAL.bin"
        original.write_bytes(b"source")
        if not alternate.exists():
            self.skipTest("Requires a case-insensitive filesystem")
        self.git("init", "--quiet")
        self.git("add", "--", original.name)
        (self.root / ".gitignore").write_text("*.bin\n", encoding="utf-8")
        for rename in (False, True):
            with self.subTest(case_only_rename=rename):
                if rename:
                    original.rename(alternate)
                result = self.inspect(alternate.name)
                row, = json.loads(result.stdout)["files"]
                if result.returncode:
                    self.assertIn("error", row)
                else:
                    self.assertTrue(row["indexed"])
                    self.assertFalse(row["ignored"])

    def test_checks_only_files_in_selected_worktree(self):
        self.git("init", "--quiet")
        child = self.root / "another"
        child.mkdir()
        self.git("init", "--quiet", str(child))
        (child / "inner.bin").write_bytes(b"x")
        (self.root.parent / "outside.bin").write_bytes(b"x")
        for path in ("another/inner.bin", "another", ".git/config", "../outside.bin", str(child / "inner.bin")):
            with self.subTest(path=path):
                self.assertNotEqual(self.inspect(path).returncode, 0)


if __name__ == "__main__":
    unittest.main()
