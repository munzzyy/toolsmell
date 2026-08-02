"""Rule selection: --ignore, --select, and the [tool.toolsmell] table.

The load-bearing behavior is that a switched-off rule leaves the score as
well as the report -- a flag that silences text but keeps the points would
make the number a lie.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from toolsmell import cli, config
from toolsmell.catalog import BY_ID
from tests._helpers import by_rule, lint


def _smelly():
    return {"name": "do_thing", "description": "Handles requests.",
            "inputSchema": {"type": "object",
                            "properties": {"location": {"type": "string"}}}}


class Resolve(unittest.TestCase):
    def test_no_selection_means_every_rule(self):
        self.assertIsNone(config.resolve(None, None))

    def test_ignore_removes_only_the_named_rules(self):
        enabled = config.resolve("TS-003,TS-008", None)
        self.assertNotIn("TS-003", enabled)
        self.assertNotIn("TS-008", enabled)
        self.assertIn("TS-001", enabled)
        self.assertEqual(len(enabled), len(BY_ID) - 2)

    def test_select_keeps_only_the_named_rules(self):
        self.assertEqual(config.resolve(None, "TS-001"), frozenset({"TS-001"}))

    def test_ids_are_case_insensitive_and_whitespace_tolerant(self):
        self.assertEqual(config.resolve(None, " ts-001 , ts-002 "),
                         frozenset({"TS-001", "TS-002"}))

    def test_unknown_id_is_an_error_not_a_silent_no_op(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.resolve("TS-999", None)
        self.assertIn("TS-999", str(ctx.exception))

    def test_both_flags_together_is_an_error(self):
        with self.assertRaises(config.ConfigError):
            config.resolve("TS-001", "TS-002")


class Filtering(unittest.TestCase):
    def test_ignored_rule_leaves_the_findings(self):
        full = lint(_smelly())
        self.assertTrue(by_rule(full, "TS-004"))
        trimmed = lint(_smelly(), enabled=config.resolve("TS-004", None))
        self.assertFalse(by_rule(trimmed, "TS-004"))

    def test_ignored_rule_also_leaves_the_score(self):
        # A tool with no parameters, so the total stays under the 100-point
        # cap and the arithmetic is visible.
        mild = {"name": "do_thing", "description": "Handles requests."}
        full = lint(mild)
        trimmed = lint(mild, enabled=config.resolve("TS-004", None))
        # TS-004 is medium, worth 25 points. Silencing it has to take the
        # points with it, or --max-score would still gate on a rule the user
        # switched off.
        self.assertEqual(trimmed.score, full.score - 25)

    def test_select_narrows_to_one_rule(self):
        result = lint(_smelly(), enabled=config.resolve(None, "TS-002"))
        self.assertEqual({f.rule_id for f in result.findings}, {"TS-002"})


class PyprojectTable(unittest.TestCase):
    def _project(self, toml_text: str):
        root = Path(tempfile.mkdtemp())
        (root / "pyproject.toml").write_text(toml_text, encoding="utf-8")
        manifest = root / "tools.json"
        manifest.write_text(json.dumps({"tools": [_smelly()]}), encoding="utf-8")
        return root, manifest

    def test_ignore_list_is_read_from_the_nearest_pyproject(self):
        if config.tomllib is None:
            self.skipTest("no stdlib TOML parser before Python 3.11")
        root, manifest = self._project(
            '[tool.toolsmell]\nignore = ["TS-004", "TS-008"]\n')
        enabled = config.resolve(config_start=str(manifest))
        self.assertNotIn("TS-004", enabled)
        self.assertNotIn("TS-008", enabled)

    def test_search_walks_up_from_a_nested_manifest(self):
        if config.tomllib is None:
            self.skipTest("no stdlib TOML parser before Python 3.11")
        root, _ = self._project('[tool.toolsmell]\nselect = ["TS-002"]\n')
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        manifest = nested / "tools.json"
        manifest.write_text(json.dumps({"tools": [_smelly()]}), encoding="utf-8")
        self.assertEqual(config.resolve(config_start=str(manifest)),
                         frozenset({"TS-002"}))

    def test_pyproject_without_the_table_changes_nothing(self):
        root, manifest = self._project('[project]\nname = "someone-elses"\n')
        self.assertIsNone(config.resolve(config_start=str(manifest)))

    def test_command_line_wins_over_the_file(self):
        root, manifest = self._project('[tool.toolsmell]\nignore = ["TS-004"]\n')
        enabled = config.resolve(select="TS-004", config_start=str(manifest))
        self.assertEqual(enabled, frozenset({"TS-004"}))

    def test_unknown_id_in_the_table_names_the_file(self):
        if config.tomllib is None:
            self.skipTest("no stdlib TOML parser before Python 3.11")
        root, manifest = self._project('[tool.toolsmell]\nignore = ["TS-404"]\n')
        with self.assertRaises(config.ConfigError) as ctx:
            config.resolve(config_start=str(manifest))
        self.assertIn("pyproject.toml", str(ctx.exception))

    def test_unparseable_pyproject_warns_and_keeps_every_rule(self):
        # A broken pyproject.toml belongs to some other tool as often as not.
        # Dropping the selection leaves the run stricter, never laxer, so the
        # right move is to say so on stderr and carry on linting.
        root, manifest = self._project("this is not [ valid toml\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            enabled = config.resolve(config_start=str(manifest))
        self.assertIsNone(enabled)
        self.assertIn("pyproject.toml", err.getvalue())

    @unittest.skipIf(sys.version_info >= (3, 11), "3.11+ has tomllib")
    def test_old_python_says_the_table_was_not_applied(self):
        root, manifest = self._project('[tool.toolsmell]\nignore = ["TS-004"]\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            enabled = config.resolve(config_start=str(manifest))
        self.assertIsNone(enabled)
        self.assertIn("3.11", err.getvalue())


class CLIWiring(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def _manifest(self):
        tmp = Path(tempfile.mkdtemp()) / "tools.json"
        tmp.write_text(json.dumps({"tools": [_smelly()]}), encoding="utf-8")
        return str(tmp)

    def test_ignore_flag_drops_the_rule_from_the_report(self):
        p = self._manifest()
        _, full = self._run([p, "--no-color", "--max-score", "1000"])
        self.assertIn("TS-004", full)
        _, trimmed = self._run([p, "--no-color", "--max-score", "1000",
                                "--ignore", "TS-004"])
        self.assertNotIn("TS-004", trimmed)

    def test_ignoring_enough_rules_can_pass_the_gate(self):
        p = self._manifest()
        code, _ = self._run([p, "--no-color"])
        self.assertEqual(code, 1)
        code, _ = self._run([p, "--no-color", "--ignore",
                             "TS-002,TS-003,TS-004,TS-005,TS-006,TS-007,TS-008"])
        self.assertEqual(code, 0)

    def test_bad_rule_id_exits_two_and_names_it(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self._run([self._manifest(), "--ignore", "TS-999"])
        self.assertEqual(code, 2)
        self.assertIn("TS-999", err.getvalue())

    def test_ignore_and_select_together_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                cli.main([self._manifest(), "--ignore", "TS-001",
                          "--select", "TS-002"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
