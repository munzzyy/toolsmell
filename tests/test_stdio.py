"""--stdio: the subprocess client itself, and the CLI flag wired to it.

tests/fixtures/fake_mcp_server.py stands in for a real MCP server -- it's
spawned for real, over a real pipe, exactly the way `toolsmell --stdio`
spawns one. Nothing here is mocked at the subprocess boundary."""

from __future__ import annotations

import contextlib
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import toolsmell.mcp_stdio as mcp_stdio
from toolsmell import cli
from toolsmell.manifest import parse_tools
from toolsmell.mcp_stdio import StdioError, _kill, fetch_tools_via_stdio

FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def _cmd(mode: str) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(FIXTURE))} {mode}"


class _FastTimeouts:
    """Swap the module's wall-clock constants for small ones for the
    duration of a test, so a deliberately hung fixture doesn't make the
    suite slow. Mirrors the MAX_FILE_BYTES monkeypatch test_manifest.py
    already uses for the same reason."""

    def __enter__(self):
        self._process, self._read = mcp_stdio.PROCESS_TIMEOUT, mcp_stdio.READ_TIMEOUT
        mcp_stdio.PROCESS_TIMEOUT, mcp_stdio.READ_TIMEOUT = 0.5, 0.5
        return self

    def __exit__(self, *exc):
        mcp_stdio.PROCESS_TIMEOUT, mcp_stdio.READ_TIMEOUT = self._process, self._read


class FetchToolsViaStdio(unittest.TestCase):
    def test_ok_server_returns_the_tools_result(self):
        result = fetch_tools_via_stdio(_cmd("ok"))
        self.assertEqual(result["tools"][0]["name"], "get_weather")

    def test_result_feeds_the_same_parser_a_file_would(self):
        result = fetch_tools_via_stdio(_cmd("ok"))
        tools = parse_tools(result)
        self.assertEqual(tools[0].name, "get_weather")

    def test_hanging_server_times_out(self):
        with _FastTimeouts(), self.assertRaises(StdioError):
            fetch_tools_via_stdio(_cmd("hang"))

    def test_server_that_exits_immediately_raises(self):
        with self.assertRaises(StdioError):
            fetch_tools_via_stdio(_cmd("exit"))

    def test_malformed_json_raises(self):
        with self.assertRaises(StdioError):
            fetch_tools_via_stdio(_cmd("malformed"))

    def test_oversized_response_raises(self):
        original = mcp_stdio.MAX_RESPONSE_BYTES
        mcp_stdio.MAX_RESPONSE_BYTES = 1024
        try:
            with self.assertRaises(StdioError):
                fetch_tools_via_stdio(_cmd("oversized"))
        finally:
            mcp_stdio.MAX_RESPONSE_BYTES = original

    def test_empty_command_raises(self):
        with self.assertRaises(StdioError):
            fetch_tools_via_stdio("   ")

    def test_nonexistent_command_raises(self):
        with self.assertRaises(StdioError):
            fetch_tools_via_stdio("no-such-binary-anywhere-on-this-machine")

    def test_command_is_never_handed_to_a_shell(self):
        # A shell would run `touch` after the `;` and leave the marker file
        # behind. shlex.split plus a real argv list hands `echo` a literal
        # "hi;" argument instead -- nothing after it ever executes.
        marker = Path(tempfile.mkdtemp()) / "toolsmell-shell-test-marker"
        with self.assertRaises(StdioError):
            fetch_tools_via_stdio(f"echo hi; touch {shlex.quote(str(marker))}")
        self.assertFalse(marker.exists(),
                          "a shell would have run `touch` here; shlex+argv must not")


class KillHelper(unittest.TestCase):
    def test_kill_terminates_a_live_child(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3600)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        _kill(proc)
        self.assertIsNotNone(proc.poll())


class CLIStdio(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_stdio_flag_lints_a_live_server(self):
        code, out = self._run(["--stdio", _cmd("ok"), "--no-color"])
        self.assertIn("get_weather", out)
        self.assertEqual(code, 1)  # the fixture tool is deliberately smelly

    def test_stdio_json_output(self):
        code, out = self._run(["--stdio", _cmd("ok"), "--json"])
        payload = json.loads(out)
        self.assertEqual(payload["tools"][0]["name"], "get_weather")

    def test_stdio_and_target_together_is_a_usage_error(self):
        code, _ = self._run(["some-file.json", "--stdio", _cmd("ok")])
        self.assertEqual(code, 2)

    def test_neither_target_nor_stdio_is_a_usage_error(self):
        code, _ = self._run([])
        self.assertEqual(code, 2)

    def test_connection_failure_is_a_usage_error_not_a_crash(self):
        code, _ = self._run(["--stdio", "no-such-binary-anywhere-on-this-machine"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
