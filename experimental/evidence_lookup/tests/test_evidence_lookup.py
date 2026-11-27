import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experimental.evidence_lookup import __main__ as cli
from experimental.evidence_lookup import backends
from core_check import runtime_boundary


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

    def test_protected_sources_are_checked_again_before_read(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(cli, "CORE", root / "core"), patch.object(cli, "tracked", return_value=[
                "docs/private/note.md", "docs/target.md",
            ]) as tracked, patch.object(backends, "safe_read", return_value=(b"data", ())) as read:
                boundary = SimpleNamespace(consumer_root=root, protected_paths=("core", "docs/./PrIvAtE/"),
                                           host_baseline=object())
                data, partial = cli.document_sources(boundary, ["docs"], ".md")
                self.assertFalse(partial)
                self.assertEqual(set(data), {"docs/target.md"})
                tracked.assert_called_once_with(root, ["docs"], excluded=("docs/PrIvAtE", "core"))
                read.assert_called_once_with(root / "docs/target.md")
                with self.assertRaisesRegex(backends.Rejected, "CORE_SOURCE_SCOPE_REJECTED"):
                    cli.document_sources(boundary, ["core/docs"], ".md")
                with self.assertRaisesRegex(backends.Rejected, "PROTECTED_SOURCE"):
                    cli.document_sources(boundary, ["docs"], ".md", target="docs/private/note.md")
                tracked.assert_called_once()

    @unittest.skipUnless(shutil.which("git"), "Git is required for the tracked source boundary")
    def test_git_excludes_protected_names_before_returning_candidates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "--quiet"], cwd=root, check=True, capture_output=True)
            for relative in ("notes/subfolder/example.md", "notes/subfolder-nearby/public.md", "notes/public.md",
                             "notes/Équipe/Été/example.md", "notes/Équipage/public.md"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Synthetic fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "--", "notes"], cwd=root, check=True, capture_output=True)
            with patch.dict(os.environ, {"GIT_LITERAL_PATHSPECS": "1"}):
                result = cli.tracked(root, ["notes"], excluded=("Notes/Subfolder", "notes/éQUIPE/éTÉ"))
            self.assertEqual(result, ["notes/public.md", "notes/subfolder-nearby/public.md", "notes/Équipage/public.md"])

    def test_invoke_checks_boundary_input_and_cache_before_obsidian_registration(self):
        root = Path.cwd().resolve()
        request = {"tool": "obsidian", "target": "notes/public.md", "source_roots": ["notes"],
                   "executable": str(root / "Obsidian.exe"), "cache": ".evidence"}
        boundary = SimpleNamespace(write_paths=(".evidence",))
        failure = backends.Rejected("TEST_REJECTED")
        with patch.object(cli, "prepare_consumer_runtime_boundary") as prepare, \
                patch.object(cli, "document_sources") as sources, \
                patch.object(cli, "cache_directory") as cache, \
                patch.object(cli.obsidian_session, "Request") as register, \
                patch.object(cli, "require_consumer_runtime_boundary_unchanged") as verify:
            prepare.side_effect = cli.RuntimeBoundaryError("No valid Consumer boundary")
            with self.assertRaises(cli.RuntimeBoundaryError):
                cli.invoke(root, request)
            sources.assert_not_called()
            cache.assert_not_called()
            register.assert_not_called()
            verify.assert_not_called()

            prepare.side_effect = None
            prepare.return_value = boundary
            sources.side_effect = failure
            with self.assertRaisesRegex(backends.Rejected, "TEST_REJECTED"):
                cli.invoke(root, request)
            cache.assert_not_called()
            register.assert_not_called()
            verify.assert_called_once_with(boundary)

            sources.side_effect = None
            sources.return_value = {request["target"]: (b"# Example", ())}, False
            cache.side_effect = failure
            with self.assertRaisesRegex(backends.Rejected, "TEST_REJECTED"):
                cli.invoke(root, request)
            register.assert_not_called()
            self.assertEqual(verify.call_count, 2)

    def test_shared_boundary_checks_only_invoked_capability_and_not_protected_targets(self):
        root = Path.cwd().resolve()
        core = root / "core"
        contract = {"contract_version": 2, "consumer_role": "maintainer",
                    "required_core_capabilities": {"evidence_lookup": 1},
                    "protected_paths": [f"{root.drive}equivalent/./path/"]}
        selected = {"version": 1}
        compatibility = {"contract_version": 2, "optional_capabilities":
                         {"evidence_lookup": selected, "shared_data": {"version": 1}}}
        with patch.object(runtime_boundary, "capture_host_consumer_observation", side_effect=OSError), \
                patch.object(runtime_boundary, "consumer_contract", return_value=contract), \
                patch.object(runtime_boundary, "declared_compatibility", return_value=compatibility), \
                patch.object(runtime_boundary, "optional_capability_installation_state", return_value="installed") as installed, \
                patch.object(runtime_boundary, "resolve_inside") as resolve:
            with self.assertRaisesRegex(cli.RuntimeBoundaryError, "보호 경로"):
                runtime_boundary.prepare_consumer_runtime_boundary(core, root, capability_id="evidence_lookup",
                                                                    write_paths=("equivalent/path/cache",))
            installed.assert_called_once_with(core, "evidence_lookup", selected)
            resolve.assert_not_called()
            installed.return_value = "absent"
            with self.assertRaisesRegex(cli.RuntimeBoundaryError, "설치되지 않았다"):
                runtime_boundary.prepare_consumer_runtime_boundary(core, root, capability_id="evidence_lookup",
                                                                    write_paths=(".evidence",))
            resolve.assert_not_called()

            installed.return_value = "installed"
            install_failure = runtime_boundary.CheckError("선택 기능이 부분 설치 상태다")
            installed.side_effect = install_failure
            with self.assertRaisesRegex(cli.RuntimeBoundaryError, "부분 설치"):
                runtime_boundary.prepare_consumer_runtime_boundary(core, root, capability_id="evidence_lookup",
                                                                    write_paths=(".evidence",))
            resolve.assert_not_called()

            installed.side_effect = None
            resolve.side_effect = lambda _, path: root / "runtime" / "cache" if path == "storage-alias" else path
            aliased = runtime_boundary.prepare_consumer_runtime_boundary(core, root, capability_id="evidence_lookup",
                                                                         write_paths=("storage-alias",))
            self.assertEqual(aliased.write_paths, ("runtime/cache",))
            self.assertEqual(aliased.protected_paths, ("core", "equivalent/path"))

    def test_obsidian_cleanup_precedes_final_consumer_check_and_fallback_survives(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            note = root / "example.md"
            note.write_text("# Example\n", encoding="utf-8")
            snapshot = {note.name: backends.safe_read(note)}
            request = {"tool": "obsidian", "target": note.name, "source_roots": [note.name],
                       "executable": str(root / "Obsidian.exe"), "cache": ".evidence"}
            boundary = SimpleNamespace(consumer_root=root, write_paths=(".evidence",))
            order = []
            with patch.object(cli, "prepare_consumer_runtime_boundary", return_value=boundary), \
                    patch.object(cli, "document_sources", return_value=(snapshot, False)), \
                    patch.object(cli, "cache_directory", return_value=root), \
                    patch.object(cli.obsidian_session, "Request") as register, \
                    patch.object(cli, "require_consumer_runtime_boundary_unchanged",
                                 side_effect=lambda _: order.append("check")):
                register.return_value.lookup.return_value = []
                register.return_value.close.side_effect = lambda: order.append("close")
                native = cli.invoke(root, request)
                self.assertEqual(native["backend"], "obsidian")
                self.assertEqual(order, ["close", "check"])

                register.side_effect = backends.Rejected("MOCK_TOOL_FAILURE")
                fallback = cli.invoke(root, request)
                self.assertEqual(fallback["backend"], "markdown")
                self.assertEqual(fallback["fallback_reason"], "MOCK_TOOL_FAILURE")
                self.assertEqual(order, ["close", "check", "check"])
