"""Speak the minimal MCP JSON-RPC handshake over a subprocess's stdio.

This is the only place in toolsmell that runs another program. It exists
for the opt-in `--stdio` flag only -- the default target-file mode never
imports the function that spawns anything. The child is treated as a
hostile peer throughout: the command is split with shlex and exec'd as a
real argv list (never a shell), every read is bounded in both size and
time, and the process gets killed on any error, timeout, or exit.

The handshake is deliberately small, and there are two of them because the
protocol changed. MCP 2026-07-28 dropped `initialize` in favour of a
`server/discover` probe and made every request carry its protocol version
in `_meta`. Servers written against either revision are still out there, so
toolsmell probes with `server/discover` first and falls back to
`initialize` + `notifications/initialized` on anything that says the server
has not heard of it. Either way it ends at `tools/list`, which is the only
call it actually wants, so there's no reason to depend on a full MCP client
library for this.
"""

from __future__ import annotations

import json
import os
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

# The revision toolsmell asks for, and the one it drops back to. 2026-07-28
# replaced the initialize handshake with a server/discover probe; anything
# older still expects initialize.
PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2024-11-05"

# 2026-07-28 made the protocol stateless: the version and the client's
# capabilities ride along in _meta on every request rather than being agreed
# once at startup.
META_KEY = "_meta"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"

DISCOVER_METHOD = "server/discover"

# UnsupportedProtocolVersionError. This is the one probe outcome that must
# NOT fall back: it means the server does speak the modern protocol and has
# rejected our version, so retrying with an older handshake is just noise.
# Every other error, and a timeout, means "probably a legacy server" -- the
# fallback is deliberately not keyed to any single other code, because a
# legacy server can reject an unknown method however it likes.
UNSUPPORTED_PROTOCOL_VERSION = -32022

# How long to wait for the probe before assuming the server is legacy. A
# server that answers server/discover at all answers it immediately; this is
# only the budget for one that ignores unknown methods entirely, and it is
# carved out of PROCESS_TIMEOUT rather than added to it.
DISCOVER_TIMEOUT = 5.0

# A real server lists its tools in a handful of pages at most. Cap the
# follow-the-cursor loop so a hostile server that always returns a fresh
# nextCursor can't keep the client paging forever.
MAX_LIST_PAGES = 50

# The child's stderr is captured so a server that dies on startup can say
# why, but it gets the same bounded treatment as its stdout -- a chatty
# server must not be able to fill memory through the diagnostic channel.
MAX_STDERR_BYTES = 65_536
STDERR_TAIL_LINES = 20
STDERR_TAIL_CHARS = 4_000

# How long to wait for the stderr reader to catch up once the exchange has
# already failed. A server that dies during startup usually writes its
# traceback microseconds before the client notices, so a short grace period
# is the difference between quoting the real cause and quoting nothing.
STDERR_GRACE = 0.5


class StdioError(Exception):
    """Raised when a --stdio server can't be launched, times out, or sends
    something that isn't a usable JSON-RPC response."""


class StdioLimitError(StdioError):
    """Raised when the server blew past a hard size cap.

    Kept distinct from StdioError so the version probe can treat a protocol
    error as "probably a legacy server, try the old handshake" without ever
    treating a size-cap breach the same way. A cap a retry path quietly
    steps over is not a cap.
    """


class _LineReader:
    """Reads newline-delimited bytes off a pipe on a background thread and
    hands complete lines to the caller through a queue, so the caller can
    wait for one with a real deadline instead of blocking on read().

    A thread is used rather than select() because select() can't watch a
    plain pipe on Windows -- only sockets. A background thread doing a
    blocking read works the same on every platform toolsmell's CI covers.
    """

    def __init__(self, stream, limit=None, flush_partial: bool = False):
        self._stream = stream
        self._limit = limit
        self._flush_partial = flush_partial
        self._queue: "queue.Queue" = queue.Queue()
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        limit = MAX_RESPONSE_BYTES if self._limit is None else self._limit
        buf = bytearray()
        total = 0
        try:
            while True:
                chunk = self._stream.read1(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    self._queue.put(("oversized", None))
                    return
                buf += chunk
                while b"\n" in buf:
                    line, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)
                    self._queue.put(("line", bytes(line)))
        except (OSError, ValueError):
            pass  # the pipe went away, e.g. the process was killed
        # A traceback cut off before its final newline is still the thing the
        # user needs to read, so the diagnostic reader keeps the tail. The
        # protocol reader does not: a half-written JSON line is not a message.
        if self._flush_partial and buf:
            self._queue.put(("line", bytes(buf)))
        self._queue.put(("eof", None))

    def drain(self, grace: float = 0.0) -> list:
        """Every line queued so far, waiting up to `grace` seconds for the
        stream to close first. Never raises -- this is the path that runs
        while an error is already being reported, and losing the diagnostic
        is better than replacing the real error with a second one."""
        out = []
        deadline = time.monotonic() + grace
        while True:
            wait = max(0.0, deadline - time.monotonic())
            try:
                if wait > 0:
                    kind, payload = self._queue.get(timeout=wait)
                else:
                    kind, payload = self._queue.get_nowait()
            except queue.Empty:
                return out
            if kind != "line":
                return out  # eof, or the reader hit its size cap
            out.append(payload)

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
            raise StdioLimitError(
                f"server response exceeded {MAX_RESPONSE_BYTES} bytes")
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
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _stderr_tail(reader: _LineReader) -> str:
    """The last few lines the server wrote to stderr, indented for the error
    message. Bounded in lines and characters on top of the reader's own byte
    cap, so a server that logs a megabyte before dying still produces a
    readable error."""
    lines = [line.decode("utf-8", "replace").rstrip("\r")
             for line in reader.drain(STDERR_GRACE)]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ""
    text = "\n".join("  " + line for line in lines[-STDERR_TAIL_LINES:])
    if len(text) > STDERR_TAIL_CHARS:
        text = "  ...\n" + text[-STDERR_TAIL_CHARS:]
    return text


def _with_server_output(message: str, reader: _LineReader,
                        proc: "subprocess.Popen") -> str:
    """Attach whatever the server said on its way down.

    Without this, a server that fails to start produces one line -- 'server
    closed its output before responding' -- and the ModuleNotFoundError or
    missing env var that actually caused it goes in the bin. Startup failure
    is the most common --stdio outcome for a new user, so it is the one that
    most needs the real message.
    """
    parts = [message]
    # Wait rather than poll. A server that dies on startup usually loses the
    # race with the client noticing, and poll() on a process that is dead but
    # not yet reaped returns None, which would drop the exit status from the
    # error at exactly the moment it is worth the most.
    try:
        status = proc.wait(timeout=STDERR_GRACE)
    except subprocess.TimeoutExpired:
        status = None
    if status is not None and status != 0:
        parts.append(f"the server exited with status {status}")
    tail = _stderr_tail(reader)
    if tail:
        parts.append("server stderr:\n" + tail)
    return "\n".join(parts)


def _request(request_id: int, method: str, params=None, modern: bool = True) -> dict:
    """One JSON-RPC request. On the 2026-07-28 path every request carries the
    protocol version and the client's capabilities in `_meta`; on the legacy
    path both were settled once by `initialize`, so sending them would be
    wrong."""
    body = dict(params or {})
    if modern:
        body[META_KEY] = {
            PROTOCOL_VERSION_META: PROTOCOL_VERSION,
            # toolsmell reads a tool list and calls nothing, so it claims
            # nothing. An empty object is the honest answer, not a stub.
            CLIENT_CAPABILITIES_META: {},
        }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": body}


def _probe_discover(proc, reader: _LineReader, deadline: float) -> bool:
    """Ask the server whether it speaks 2026-07-28. True means it does.

    Three outcomes, per the stdio transport spec. A result means modern. An
    UnsupportedProtocolVersionError means modern but on a version we can't
    talk, and falling back would only hide that, so it raises. Anything else
    (any other error code, a timeout, junk on the wire) means the server has
    never heard of the method, which is what a legacy server looks like.
    """
    probe_deadline = min(deadline, time.monotonic() + DISCOVER_TIMEOUT)
    _send(proc, _request(1, DISCOVER_METHOD))
    try:
        response = _recv_response(reader, probe_deadline, 1)
    except StdioLimitError:
        raise  # a size cap is never a reason to retry
    except StdioError:
        return False
    error = response.get("error")
    if error is None:
        return True
    code = error.get("code") if isinstance(error, dict) else None
    if code == UNSUPPORTED_PROTOCOL_VERSION:
        detail = error.get("message") if isinstance(error, dict) else error
        raise StdioError(
            f"the server rejected protocol version {PROTOCOL_VERSION}: {detail}. "
            "It speaks the modern protocol on a version toolsmell does not, so "
            "the legacy handshake would not help either.")
    return False


def _legacy_handshake(proc, reader: _LineReader, deadline: float,
                      request_id: int) -> None:
    """The pre-2026-07-28 opening: `initialize`, then the
    `notifications/initialized` notice the spec requires before any other
    call."""
    _send(proc, {
        "jsonrpc": "2.0", "id": request_id, "method": "initialize",
        "params": {
            "protocolVersion": LEGACY_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "toolsmell", "version": __version__},
        },
    })
    response = _recv_response(reader, deadline, request_id)
    _check_error(response, "initialize")
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def _list_tools(proc, reader: _LineReader, deadline: float, request_id: int,
                modern: bool) -> list:
    """Follow tools/list to the end of its pagination and return every tool."""
    tools = []
    cursor = None
    seen_cursors = set()
    for _ in range(MAX_LIST_PAGES):
        params = {} if cursor is None else {"cursor": cursor}
        _send(proc, _request(request_id, "tools/list", params, modern=modern))
        response = _recv_response(reader, deadline, request_id)
        _check_error(response, "tools/list")
        result = response.get("result")
        if not isinstance(result, dict):
            raise StdioError("tools/list response has no 'result' object")
        page = result.get("tools")
        if isinstance(page, list):
            tools.extend(page)
        # tools/list is paginated: a string nextCursor means fetch the next
        # page with it. Stop on anything else, and refuse to loop on a
        # repeated cursor (a server stuck or lying about progress).
        next_cursor = result.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            return tools
        if next_cursor in seen_cursors:
            raise StdioError("server repeated a tools/list cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        request_id += 1
    raise StdioError(f"server paginated tools/list past {MAX_LIST_PAGES} pages")


def _split_command(command: str) -> list:
    """Split a --stdio command string into an argv list. Split posix
    everywhere except Windows, where posix mode eats the backslashes in a
    path like `python C:\\mcp\\server.py`; there, split non-posix and strip
    the surrounding double quotes non-posix leaves attached to a token."""
    argv = shlex.split(command, posix=(os.name != "nt"))
    if os.name == "nt":
        argv = [
            tok[1:-1] if len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0] else tok
            for tok in argv
        ]
    return argv


def fetch_tools_via_stdio(command: str) -> dict:
    """Spawn `command`, speak the minimal MCP handshake over its stdio, and
    return the parsed tools/list result. The result is still untrusted --
    it's handed to the same parse_tools() a manifest file goes through, so
    a hostile server gets exactly the same treatment as a hostile file.

    `command` is split with shlex and run as a real argv list. There is no
    shell involved in launching it, ever.
    """
    try:
        argv = _split_command(command)
    except ValueError as e:
        raise StdioError(f"cannot parse --stdio command: {e}")
    if not argv:
        raise StdioError("--stdio command is empty")

    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
    except OSError as e:
        raise StdioError(f"cannot run {argv[0]!r}: {e}")

    deadline = time.monotonic() + PROCESS_TIMEOUT
    reader = _LineReader(proc.stdout)
    err_reader = _LineReader(proc.stderr, limit=MAX_STDERR_BYTES,
                             flush_partial=True)
    try:
        modern = _probe_discover(proc, reader, deadline)
        if not modern:
            _legacy_handshake(proc, reader, deadline, request_id=2)
        tools = _list_tools(proc, reader, deadline, request_id=3, modern=modern)
    except StdioError as e:
        # Re-raise as the same class: StdioLimitError has to stay a limit
        # error after the stderr tail is bolted on.
        raise type(e)(_with_server_output(str(e), err_reader, proc)) from None
    finally:
        _kill(proc)

    return {"tools": tools}
