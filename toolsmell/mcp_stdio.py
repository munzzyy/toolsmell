"""Speak the minimal MCP JSON-RPC handshake over a subprocess's stdio.

This is the only place in toolsmell that runs another program. It exists
for the opt-in `--stdio` flag only -- the default target-file mode never
imports the function that spawns anything. The child is treated as a
hostile peer throughout: the command is split with shlex and exec'd as a
real argv list (never a shell), every read is bounded in both size and
time, and the process gets killed on any error, timeout, or exit.

The handshake itself is deliberately small: `initialize`, the
`notifications/initialized` notice that has to follow it, then
`tools/list`. That's every call the protocol requires to get a tool
listing, so there's no reason to depend on a full MCP client library for
it.
"""

from __future__ import annotations

import json
import queue
import shlex
import subprocess
import threading
import time

from . import __version__
from .manifest import MAX_FILE_BYTES

# A tools/list response describing a real server has no business being any
# bigger than a manifest file would be -- a malicious or just-broken server
# streaming unbounded output shouldn't be able to run the caller out of
# memory. Same ceiling as manifest.py's static-file path.
MAX_RESPONSE_BYTES = MAX_FILE_BYTES

# Wall-clock budget for the whole exchange: spawning the process, both
# requests, and both responses. A slow-but-honest server fits easily; a
# hung one gets killed instead of wedging the caller indefinitely.
PROCESS_TIMEOUT = 20.0

# Ceiling on waiting for any single response line. This is combined with
# PROCESS_TIMEOUT below rather than used on its own, so a server that
# trickles a few bytes just under this ceiling, over and over, still can't
# stall the whole call past the overall budget.
READ_TIMEOUT = 10.0

MCP_PROTOCOL_VERSION = "2024-11-05"


class StdioError(Exception):
    """Raised when a --stdio server can't be launched, times out, or sends
    something that isn't a usable JSON-RPC response."""


class _LineReader:
    """Reads newline-delimited bytes off a pipe on a background thread and
    hands complete lines to the caller through a queue, so the caller can
    wait for one with a real deadline instead of blocking on read().

    A thread is used rather than select() because select() can't watch a
    plain pipe on Windows -- only sockets. A background thread doing a
    blocking read works the same on every platform toolsmell's CI covers.
    """

    def __init__(self, stream):
        self._stream = stream
        self._queue: "queue.Queue" = queue.Queue()
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        buf = bytearray()
        total = 0
        try:
            while True:
                chunk = self._stream.read1(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    self._queue.put(("oversized", None))
                    return
                buf += chunk
                while b"\n" in buf:
                    line, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)
                    self._queue.put(("line", bytes(line)))
        except (OSError, ValueError):
            pass  # the pipe went away, e.g. the process was killed
        self._queue.put(("eof", None))

    def readline(self, deadline: float) -> bytes:
        """Return the next complete line, waiting at most until `deadline`
        (an absolute time.monotonic() value) and at most READ_TIMEOUT for
        this one call, whichever is sooner."""
        remaining = deadline - time.monotonic()
        wait = max(0.0, min(remaining, READ_TIMEOUT))
        try:
            kind, payload = self._queue.get(timeout=wait)
        except queue.Empty:
            raise StdioError(f"server did not respond within {READ_TIMEOUT:.0f}s")
        if kind == "oversized":
            raise StdioError(f"server response exceeded {MAX_RESPONSE_BYTES} bytes")
        if kind == "eof":
            raise StdioError("server closed its output before responding")
        return payload


def _send(proc: "subprocess.Popen", message: dict) -> None:
    try:
        proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as e:
        raise StdioError(f"could not write to the server's stdin: {e}")


def _recv_response(reader: _LineReader, deadline: float, expected_id: int) -> dict:
    """Read lines until one carries `expected_id`. A compliant server can
    interleave notifications (log messages, progress) with no "id" before
    the actual response; those are skipped rather than treated as the
    answer. Still bounded by the same overall deadline either way, so a
    server that never stops chattering can't stall this past PROCESS_TIMEOUT."""
    while True:
        line = reader.readline(deadline)
        try:
            message = json.loads(line.decode("utf-8"))
        except UnicodeDecodeError as e:
            raise StdioError(f"server response is not valid UTF-8: {e}")
        except json.JSONDecodeError as e:
            raise StdioError(f"server response is not valid JSON: {e}")
        if isinstance(message, dict) and message.get("id") == expected_id:
            return message


def _check_error(message: dict, step: str) -> None:
    err = message.get("error")
    if err is not None:
        detail = err.get("message") if isinstance(err, dict) else err
        raise StdioError(f"server rejected {step}: {detail}")


def _kill(proc: "subprocess.Popen") -> None:
    """Make sure the child is gone, whether the handshake finished, timed
    out, or blew up partway through."""
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
    for stream in (proc.stdin, proc.stdout):
        try:
            stream.close()
        except OSError:
            pass


def fetch_tools_via_stdio(command: str) -> dict:
    """Spawn `command`, speak the minimal MCP handshake over its stdio, and
    return the parsed tools/list result. The result is still untrusted --
    it's handed to the same parse_tools() a manifest file goes through, so
    a hostile server gets exactly the same treatment as a hostile file.

    `command` is split with shlex and run as a real argv list. There is no
    shell involved in launching it, ever.
    """
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise StdioError(f"cannot parse --stdio command: {e}")
    if not argv:
        raise StdioError("--stdio command is empty")

    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
    except OSError as e:
        raise StdioError(f"cannot run {argv[0]!r}: {e}")

    deadline = time.monotonic() + PROCESS_TIMEOUT
    reader = _LineReader(proc.stdout)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "toolsmell", "version": __version__},
            },
        })
        init_response = _recv_response(reader, deadline, 1)
        _check_error(init_response, "initialize")

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        list_response = _recv_response(reader, deadline, 2)
        _check_error(list_response, "tools/list")
    finally:
        _kill(proc)

    result = list_response.get("result")
    if not isinstance(result, dict):
        raise StdioError("tools/list response has no 'result' object")
    return result
