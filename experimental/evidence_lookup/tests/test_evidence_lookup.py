from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experimental.evidence_lookup import __main__ as cli
from experimental.evidence_lookup import backends


class EvidenceLookupTests(unittest.TestCase):
    def test_direct_markdown_excludes_nonlinks_and_self(self):
        files = {"docs/policy.md": b"[self](policy.md)",
                 "docs/ref.md": b"[ref](policy.md#example)",
                 "docs/code.md": b"\x60[ref](policy.md)\x60"}
        self.assertEqual(backends.markdown_backlinks(files, "docs/policy.md"), ["docs/ref.md"])

    def test_graph_matches_actual_definition_and_rejects_rationale(self):
        files = {"src/example.py": b"def target(): pass\n"}
        output = "Node: target()\n  ID: target\n  Source: src/example.py L1\n  Type: code\n"
        self.assertTrue(backends.matches_graph_symbol("src.example.target", output, files))
        self.assertFalse(backends.matches_graph_symbol("other.example.target", output, files))
        self.assertFalse(backends.matches_graph_symbol("target", output.replace("code", "rationale"), files))

    def test_protected_sources_are_not_opened_and_cache_is_not_in_core(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(cli, "CORE", root / "core"), patch.object(cli, "tracked", return_value=[
                "docs/private/note.md", "docs/target.md",
            ]), patch.object(backends, "safe_read", return_value=(b"data", ())) as read:
                boundary = SimpleNamespace(consumer_root=root, protected_paths=("core", "docs/private"),
                                           host_baseline=object())
                data, partial = cli.document_sources(boundary, ["docs"], ".md")
                self.assertFalse(partial)
                self.assertEqual(set(data), {"docs/target.md"})
                read.assert_called_once_with(root / "docs/target.md")
                with self.assertRaisesRegex(backends.Rejected, "CORE_SOURCE_SCOPE_REJECTED"):
                    cli.document_sources(boundary, ["core/docs"], ".md")
