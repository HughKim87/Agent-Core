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

    def test_direct_python_call_candidates_include_attribute_calls_only_in_syntax(self):
        files = {"src/example.py": b"def target(): pass\ntarget()\napi.target()\n# target()\n'api.target()'\n",
                 "src/broken.py": b"def broken(\n"}
        matches, incomplete = backends.python_call_sites(files, "module.target")
        self.assertEqual(matches, [{"path": "src/example.py", "line": 2}, {"path": "src/example.py", "line": 3}])
        self.assertTrue(incomplete)

    def test_direct_python_call_candidates_include_renamed_imports(self):
        files = {
            "src/caller.py": b"from .context import build as build_context\n"
                             b"from .other import setup as prepare\n"
                             b"build_context()\n"
                             b"api.build_context()\n"
                             b"prepare()\n",
            "src/unrelated.py": b"build_context()\n",
        }
        matches, incomplete = backends.python_call_sites(files, "core_check.context.build")
        self.assertEqual(matches, [{"path": "src/caller.py", "line": 3}])
        self.assertFalse(incomplete)

    def test_new_core_scope_is_limited_to_explicit_maintainer_python_files(self):
        root = Path("workspace").resolve()
        target = "experimental/shared_data/cli.py"
        with patch.object(cli, "CORE", root / "core"), patch.object(cli, "tracked", return_value=[target]), \
                patch.object(backends, "safe_read", return_value=(b"target()", ())):
            boundary = SimpleNamespace(consumer_root=root, protected_paths=(), host_baseline=None)
            data, _ = cli.document_sources(boundary, ["core/" + target], ".py")
            self.assertEqual(set(data), {"core/" + target})
            with self.assertRaisesRegex(backends.Rejected, "CORE_SOURCE_SCOPE_REJECTED"):
                cli.document_sources(boundary, ["core/experimental/shared_data"], ".py")
            boundary.host_baseline = object()
            with self.assertRaisesRegex(backends.Rejected, "CORE_SOURCE_SCOPE_REJECTED"):
                cli.document_sources(boundary, ["core/" + target], ".py")

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
