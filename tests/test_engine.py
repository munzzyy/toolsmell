"""Engine tests: lint aggregation, report rendering, and the CLI."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from toolsmell import cli
from toolsmell.lint import lint_data
from toolsmell.report import render_human, render_json
from tests._helpers import lint


class LintAggregation(unittest.TestCase):
    def test_clean_manifest_scores_zero(self):
        r = lint({"name": "get_weather",
                  "description": "Fetches the weather for a place and returns the forecast; "
                                  "raises an error if the place is unknown."})
        self.assertEqual(r.score, 0)
        self.assertEqual(r.findings, [])

    def test_multiple_tools_get_their_own_reports(self):
        r = lint({"name": "a"}, {"name": "b"})
        self.assertEqual(len(r.tools), 2)
        self.assertEqual({t.name for t in r.tools}, {"a", "b"})

    def test_findings_are_sorted_worst_first(self):
        r = lint({"name": "a", "inputSchema": {
            "type": "object",
            "properties": {"x": {"type": "string"}, "y": {"type": "string"}},
        }})
        severities = [f.severity for f in r.findings]
        self.assertEqual(severities, sorted(severities, reverse=True))

    def test_counts_match_findings(self):
        r = lint({"name": "a"})
        counts = r.counts()
        self.assertEqual(sum(counts.values()), len(r.findings))

    def test_lint_data_matches_lint_tools(self):
        r = lint_data({"tools": [{"name": "a"}]}, source="x")
        self.assertEqual(r.source, "x")
        self.assertEqual(len(r.tools), 1)


class Reporting(unittest.TestCase):
    def test_json_is_valid_and_complete(self):
        r = lint({"name": "a"})
        payload = json.loads(render_json(r))
        self.assertEqual(payload["tool"], "toolsmell")
        self.assertIn("score", payload)
        self.assertTrue(payload["tools"][0]["findings"])
        self.assertIn("severity", payload["tools"][0]["findings"][0])

    def test_human_report_mentions_every_tool(self):
        r = lint({"name": "alpha"}, {"name": "beta"})
        text = render_human(r, color=False)
        self.assertIn("alpha", text)
        self.assertIn("beta", text)

    def test_human_report_has_no_ansi_when_color_false(self):
        r = lint({"name": "a"})
        text = render_human(r, color=False)
        self.assertNotIn("\033[", text)

    def test_clean_tool_says_no_smells_found(self):
        r = lint({"name": "get_weather",
                  "description": "Fetches the weather for a place and returns the forecast; "
                                  "raises an error if the place is unknown."})
        text = render_human(r, color=False)
        self.assertIn("no smells found", text)

    def test_escape_sequence_in_tool_name_is_stripped(self):
        # A manifest is untrusted input; a name crafted to smuggle a raw
        # ANSI escape shouldn't get to run in whoever's terminal is linting
        # it. This is toolsmell's own SECURITY.md threat model, not a new
        # requirement --stdio introduces.
        r = lint({"name": "a\033[31mRED\033[0mtool"})
        text = render_human(r, color=False)
        self.assertNotIn("\033", text)

    def test_escape_sequence_in_param_name_is_stripped(self):
        r = lint({"name": "a", "inputSchema": {
            "type": "object",
            "properties": {"x\033[31m": {"type": "string"}},
        }})
        text = render_human(r, color=False)
        self.assertNotIn("\033", text)

    def test_json_output_already_escapes_control_characters(self):
        # render_json goes through json.dumps, which escapes control
        # characters per the JSON spec -- no separate stripping needed
        # there. This test pins that assumption down.
        r = lint({"name": "a\033[31m"})
        payload = json.loads(render_json(r))
        self.assertNotIn("\033", render_json(r))
        self.assertEqual(payload["tools"][0]["name"], "a\033[31m")


class CLI(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def _write(self, data) -> str:
        tmp = Path(tempfile.mkdtemp()) / "manifest.json"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        return str(tmp)

    def test_clean_manifest_exit_zero(self):
        p = self._write({"tools": [{
            "name": "get_weather",
            "description": "Fetches the weather for a place and returns the forecast; "
                            "raises an error if the place is unknown.",
        }]})
        code, _ = self._run([p, "--no-color"])
        self.assertEqual(code, 0)

    def _smelly_manifest(self):
        return {"tools": [{"name": "do_thing", "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"},
                            "c": {"type": "string"}},
        }}]}

    def test_smelly_manifest_fails_default_threshold(self):
        p = self._write(self._smelly_manifest())
        code, _ = self._run([p, "--no-color"])
        self.assertEqual(code, 1)

    def test_max_score_can_be_relaxed(self):
        p = self._write(self._smelly_manifest())
        code, _ = self._run([p, "--no-color", "--max-score", "1000"])
        self.assertEqual(code, 0)

    def test_json_flag_produces_parseable_json(self):
        p = self._write({"tools": [{"name": "a", "description": "d"}]})
        code, out = self._run([p, "--json"])
        json.loads(out)

    def test_missing_path_exit_two(self):
        code, _ = self._run(["/no/such/path.json"])
        self.assertEqual(code, 2)

    def test_no_target_and_no_list_rules_exit_two(self):
        code, _ = self._run([])
        self.assertEqual(code, 2)

    def test_malformed_manifest_exit_two(self):
        tmp = Path(tempfile.mkdtemp()) / "bad.json"
        tmp.write_text("{not json", encoding="utf-8")
        code, _ = self._run([str(tmp)])
        self.assertEqual(code, 2)

    def test_list_rules_exits_zero_and_prints_every_id(self):
        code, out = self._run(["--list-rules"])
        self.assertEqual(code, 0)
        for i in range(1, 13):
            self.assertIn(f"TS-{i:03d}", out)

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as cm:
            self._run(["--version"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
