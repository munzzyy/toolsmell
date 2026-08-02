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
import time
import unittest
from pathlib import Path
from unittest import mock

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

    def test_paging_server_returns_every_page(self):
        # A spec-compliant server splits its tools across pages with
        # nextCursor. The client must follow the cursor, not lint only the
        # first page and silently drop the rest.
        result = fetch_tools_via_stdio(_cmd("paging"))
        names = [t["name"] for t in result["tools"]]
        self.assertEqual(names, ["alpha_tool", "beta_tool", "gamma_tool"])

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
            # StdioLimitError specifically: the version probe swallows
            # protocol errors to fall back to the legacy handshake, and it
            # must never swallow a size cap the same way.
            with self.assertRaises(mcp_stdio.StdioLimitError):
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


class _FastDiscover:
    """Shrink the probe budget so a fixture that deliberately ignores
    server/discover doesn't cost the suite five seconds."""

    def __init__(self, seconds: float = 0.3):
        self._seconds = seconds

    def __enter__(self):
        self._original = mcp_stdio.DISCOVER_TIMEOUT
        mcp_stdio.DISCOVER_TIMEOUT = self._seconds
        return self

    def __exit__(self, *exc):
        mcp_stdio.DISCOVER_TIMEOUT = self._original


class ProtocolNegotiation(unittest.TestCase):
    """MCP 2026-07-28 replaced initialize with a server/discover probe.
    Servers on both revisions are in the wild, so toolsmell has to reach
    either one without being told which it is talking to."""

    def test_modern_server_is_reached_through_server_discover(self):
        # This fixture answers server/discover and nothing else, and it
        # rejects any request missing the _meta fields the revision made
        # mandatory -- so getting tools back proves both.
        result = fetch_tools_via_stdio(_cmd("modern"))
        self.assertEqual(result["tools"][0]["name"], "modern_weather")

    def test_legacy_server_still_works_through_the_fallback(self):
        result = fetch_tools_via_stdio(_cmd("ok"))
        self.assertEqual(result["tools"][0]["name"], "get_weather")

    def test_probe_carries_the_required_meta_fields(self):
        request = mcp_stdio._request(1, mcp_stdio.DISCOVER_METHOD)
        meta = request["params"][mcp_stdio.META_KEY]
        self.assertEqual(meta[mcp_stdio.PROTOCOL_VERSION_META],
                          mcp_stdio.PROTOCOL_VERSION)
        self.assertIn(mcp_stdio.CLIENT_CAPABILITIES_META, meta)

    def test_legacy_requests_carry_no_meta(self):
        # _meta is a 2026-07-28 field. Sending it to a legacy server is not
        # harmless politeness, it is a request the server never agreed to.
        request = mcp_stdio._request(3, "tools/list", modern=False)
        self.assertNotIn(mcp_stdio.META_KEY, request["params"])

    def test_unsupported_version_does_not_fall_back(self):
        # The fixture answers -32022 and then offers a working legacy
        # handshake. A client that falls back gets tools; toolsmell must
        # stop and say the version was rejected.
        with self.assertRaises(StdioError) as ctx:
            fetch_tools_via_stdio(_cmd("unsupported-version"))
        message = str(ctx.exception)
        self.assertIn("rejected protocol version", message)
        self.assertIn("2099-01-01", message)

    def test_silent_probe_times_out_into_the_legacy_handshake(self):
        # A legacy server that ignores unknown methods entirely. The
        # fallback must be keyed to "no usable answer", not to one error
        # code, or this server is unreachable.
        with _FastDiscover():
            result = fetch_tools_via_stdio(_cmd("discover-silent"))
        self.assertEqual(result["tools"][0]["name"], "get_weather")

    def test_probe_budget_comes_out_of_the_overall_deadline(self):
        # A hung server must still die on PROCESS_TIMEOUT, not on
        # PROCESS_TIMEOUT plus a probe budget bolted on top.
        with _FastTimeouts(), _FastDiscover(5.0):
            started = time.monotonic()
            with self.assertRaises(StdioError):
                fetch_tools_via_stdio(_cmd("hang"))
            self.assertLess(time.monotonic() - started, 3.0)


class ServerStderr(unittest.TestCase):
    """A server that dies on startup used to produce one useless line. The
    real cause is on its stderr, so the error has to carry it."""

    def test_startup_failure_quotes_the_server_stderr(self):
        with self.assertRaises(StdioError) as ctx:
            fetch_tools_via_stdio(_cmd("startup-failure"))
        message = str(ctx.exception)
        self.assertIn("mcp_does_not_exist", message)
        self.assertIn("status 3", message)

    def test_stderr_tail_is_bounded(self):
        with self.assertRaises(StdioError) as ctx:
            fetch_tools_via_stdio(_cmd("stderr-flood"))
        message = str(ctx.exception)
        self.assertIn("flood-line-", message)
        self.assertLess(len(message), mcp_stdio.STDERR_TAIL_CHARS + 500,
                        "a chatty server must not paste its whole log into the error")

    def test_a_healthy_server_says_nothing_extra(self):
        # The stderr channel only shows up on a failure path; a good run must
        # not grow a "server stderr:" section out of nowhere.
        result = fetch_tools_via_stdio(_cmd("ok"))
        self.assertEqual(result["tools"][0]["name"], "get_weather")


class SplitCommand(unittest.TestCase):
    """_split_command must not eat the backslashes in a Windows path. shlex
    is pure Python, so forcing os.name exercises the real Windows behavior on
    any platform."""

    def test_windows_keeps_backslashes_in_a_path(self):
        with mock.patch.object(mcp_stdio.os, "name", "nt"):
            argv = mcp_stdio._split_command(r"python C:\Users\cole\mcp\server.py")
        self.assertEqual(argv, ["python", r"C:\Users\cole\mcp\server.py"])

    def test_windows_strips_wrapping_double_quotes(self):
        with mock.patch.object(mcp_stdio.os, "name", "nt"):
            argv = mcp_stdio._split_command(r'python "C:\Program Files\mcp\server.py"')
        self.assertEqual(argv, ["python", r"C:\Program Files\mcp\server.py"])

    def test_posix_split_is_unchanged(self):
        with mock.patch.object(mcp_stdio.os, "name", "posix"):
            argv = mcp_stdio._split_command("python /home/cole/server.py --flag x")
        self.assertEqual(argv, ["python", "/home/cole/server.py", "--flag", "x"])


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
