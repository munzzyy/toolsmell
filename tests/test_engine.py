"""Engine tests: lint aggregation, report rendering, and the CLI."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
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

    def test_bidi_and_zero_width_chars_are_escaped_not_passed_through(self):
        # A right-to-left override or zero-width char in a name can make
        # 'delete‮gpj.report' render as an innocent 'deletetroper.jpg'
        # in the terminal. Those must be escaped to visible \\uXXXX, not
        # emitted raw (Cc stripping alone misses the Cf category).
        rlo, zwsp = "‮", "​"
        r = lint({"name": "delete" + rlo + "gpj.report"},
                 {"name": "fetch_data" + zwsp})
        text = render_human(r, color=False)
        self.assertNotIn(rlo, text)
        self.assertNotIn(zwsp, text)
        self.assertIn("\\u202e", text)
        self.assertIn("\\u200b", text)

    def test_a_tool_name_cannot_forge_extra_report_lines(self):
        # A newline in a tool name used to break out of its line, so a name
        # could paint a convincing clean report under the real one. The
        # manifest is untrusted input; a name is one line, always.
        forged = ("safe_tool  (smell 0/100)\n    no smells found\n\n"
                  "  0 smells   (0 total)\n  Overall smell score: 0/100\n\n"
                  "  second_tool")
        lines = render_human(lint({"name": forged}), color=False).splitlines()
        self.assertEqual(
            [ln for ln in lines if ln.startswith("  Overall smell score")],
            ["  Overall smell score: 25/100"])
        self.assertFalse([ln for ln in lines if ln.strip() == "no smells found"])
        self.assertTrue(any("\\n" in ln for ln in lines))

    def test_a_tab_in_a_name_cannot_fake_report_indentation(self):
        text = render_human(lint({"name": "a\tb"}), color=False)
        self.assertNotIn("\t", text)
        self.assertIn("a\\tb", text)

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

    def test_multi_file_json_is_a_single_parseable_array(self):
        # Two files with --json used to print concatenated objects that
        # json.load rejects; it must be one array now.
        p1 = self._write({"tools": [{"name": "a", "description": "d"}]})
        p2 = self._write(self._smelly_manifest())
        code, out = self._run([p1, p2, "--json"])
        payload = json.loads(out)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)

    def test_single_file_json_stays_a_bare_object(self):
        p = self._write({"tools": [{"name": "a", "description": "d"}]})
        code, out = self._run([p, "--json"])
        self.assertIsInstance(json.loads(out), dict)

    def _mostly_clean_manifest(self, extra=None):
        # A dozen clean tools; the mean stays near zero. Append `extra` to add
        # one bad tool without dragging the average past the default gate.
        tools = [{"name": f"tool_{c*3}",
                  "description": "Fetches record and returns it as JSON, error if missing."}
                 for c in "abcdefghijkl"]
        if extra is not None:
            tools.append(extra)
        return {"tools": tools}

    def test_max_tool_score_catches_a_tool_buried_by_the_mean(self):
        # Many clean tools plus one with no description: the mean stays low
        # and passes --max-score, but --max-tool-score must fail the run and
        # name the offending tool.
        p = self._write(self._mostly_clean_manifest(
            extra={"name": "worst_tool_ever", "description": ""}))
        code, _ = self._run([p, "--no-color"])
        self.assertEqual(code, 0)  # mean buries it under the default gate
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self._run([p, "--no-color", "--max-tool-score", "25"])
        self.assertEqual(code, 1)
        self.assertIn("worst_tool_ever", err.getvalue())

    def test_max_tool_score_passes_when_every_tool_is_under(self):
        # Same flag and threshold, but every tool is clean: the per-tool gate
        # must not fire, and nothing should be named as tripping it.
        p = self._write(self._mostly_clean_manifest())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self._run([p, "--no-color", "--max-tool-score", "25"])
        self.assertEqual(code, 0)
        self.assertNotIn("--max-tool-score", err.getvalue())

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


class RedirectedOutputEncoding(unittest.TestCase):
    """A non-ASCII manifest piped to a file used to die with a
    UnicodeEncodeError under a narrow locale encoding -- and exit 1, the same
    code as a tripped gate, so CI blamed the manifest. Run the real CLI in a
    subprocess with PYTHONIOENCODING forced to cp1252, which is what Windows
    hands a redirected stdout."""

    def test_cjk_manifest_survives_a_cp1252_stdout(self):
        tmp = Path(tempfile.mkdtemp()) / "cjk.json"
        tmp.write_text(json.dumps({"tools": [{
            "name": "天气查询",
            "description": "查询指定城市的天气预报。",
        }]}, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        proc = subprocess.run(
            [sys.executable, "-m", "toolsmell", str(tmp), "--no-color"],
            capture_output=True, env=env, cwd=str(Path(__file__).parent.parent))
        self.assertIn(proc.returncode, (0, 1), proc.stderr.decode("utf-8", "replace"))
        self.assertNotIn(b"Traceback", proc.stderr)
        self.assertNotIn(b"UnicodeEncodeError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
