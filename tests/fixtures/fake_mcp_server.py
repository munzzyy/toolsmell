"""A tiny stand-in MCP server for exercising toolsmell's --stdio client.

Not part of the toolsmell package -- only spawned as a subprocess by
tests/test_stdio.py, the same way `toolsmell --stdio "..."` spawns a real
one. The mode to misbehave in (or not) is picked with a single argv flag
so one small file covers the happy path and every failure mode the client
has to survive.
"""

from __future__ import annotations

import json
import sys
import time


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _read_request() -> dict:
    return json.loads(sys.stdin.readline())


DISCOVER_METHOD = "server/discover"
METHOD_NOT_FOUND = -32601
UNSUPPORTED_PROTOCOL_VERSION = -32022
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2024-11-05"
PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"


def _tool(name: str) -> dict:
    return {
        "name": name,
        "description": "Handles requests.",
        "inputSchema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
        },
    }


TOOLS_RESULT = {"tools": [_tool("get_weather")]}
MODERN_TOOLS_RESULT = {"tools": [_tool("modern_weather")]}


def _error(request_id, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}})


def _has_required_meta(request: dict) -> bool:
    """Whether a request carries the _meta fields 2026-07-28 makes mandatory.
    A modern server rejects one that doesn't, which is how the tests prove
    toolsmell actually sends them."""
    meta = (request.get("params") or {}).get("_meta") or {}
    return (meta.get(PROTOCOL_VERSION_META) == MODERN_VERSION
            and CLIENT_CAPABILITIES_META in meta)


def _legacy_open() -> None:
    """Open the way a pre-2026-07-28 server does. It has never heard of
    server/discover, so it answers that with method-not-found and waits for
    initialize, exactly as a real legacy server would."""
    request = _read_request()
    if request.get("method") == DISCOVER_METHOD:
        _error(request["id"], METHOD_NOT_FOUND, "Method not found")
        request = _read_request()
    _write({"jsonrpc": "2.0", "id": request["id"], "result": {
        "protocolVersion": LEGACY_VERSION, "capabilities": {},
        "serverInfo": {"name": "fake-mcp-server", "version": "0"},
    }})
    sys.stdin.readline()  # notifications/initialized -- no response expected


def run_ok() -> None:
    _legacy_open()
    list_request = _read_request()
    _write({"jsonrpc": "2.0", "id": list_request["id"], "result": TOOLS_RESULT})


def run_modern() -> None:
    """A 2026-07-28 server: server/discover is the entry point and there is
    no initialize at all."""
    request = _read_request()
    if request.get("method") != DISCOVER_METHOD:
        _error(request.get("id"), METHOD_NOT_FOUND,
               f"this server only speaks {MODERN_VERSION}")
        return
    if not _has_required_meta(request):
        _error(request["id"], -32602, "request _meta is missing required fields")
        return
    _write({"jsonrpc": "2.0", "id": request["id"], "result": {
        "protocolVersion": MODERN_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "fake-mcp-server", "version": "0"},
    }})
    list_request = _read_request()
    if not _has_required_meta(list_request):
        _error(list_request["id"], -32602,
               "tools/list _meta is missing required fields")
        return
    _write({"jsonrpc": "2.0", "id": list_request["id"],
            "result": MODERN_TOOLS_RESULT})


def run_unsupported_version() -> None:
    """A modern server on a version we can't talk. The client must stop here
    -- so this fixture goes on to offer a perfectly good legacy handshake,
    and a client that wrongly falls back gets tools it should never see."""
    request = _read_request()
    _error(request["id"], UNSUPPORTED_PROTOCOL_VERSION,
           "unsupported protocol version; this server requires 2099-01-01")
    _legacy_open()
    list_request = _read_request()
    _write({"jsonrpc": "2.0", "id": list_request["id"], "result": TOOLS_RESULT})


def run_discover_silent() -> None:
    """A legacy server that neither answers nor rejects an unknown method.
    The probe has to time out and fall back rather than hang or give up."""
    _read_request()  # server/discover, deliberately left unanswered
    init = _read_request()
    _write({"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": LEGACY_VERSION, "capabilities": {},
        "serverInfo": {"name": "fake-mcp-server", "version": "0"},
    }})
    sys.stdin.readline()  # notifications/initialized
    list_request = _read_request()
    _write({"jsonrpc": "2.0", "id": list_request["id"], "result": TOOLS_RESULT})


def _paging_tool(name: str) -> dict:
    return {"name": name, "description": "Handles requests.",
            "inputSchema": {"type": "object", "properties": {}}}


# Three tools spread across three pages, keyed by the cursor the client
# echoes back. The last page has no nextCursor, which ends the loop.
_PAGES = {
    None: {"tools": [_paging_tool("alpha_tool")], "nextCursor": "page2"},
    "page2": {"tools": [_paging_tool("beta_tool")], "nextCursor": "page3"},
    "page3": {"tools": [_paging_tool("gamma_tool")]},
}


def run_paging() -> None:
    _legacy_open()
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        request = json.loads(line)
        cursor = (request.get("params") or {}).get("cursor")
        _write({"jsonrpc": "2.0", "id": request["id"], "result": _PAGES[cursor]})


def run_hang() -> None:
    # Reads and writes nothing, ever. Proves the client's read timeout
    # fires instead of blocking forever.
    time.sleep(3600)


def run_exit() -> None:
    # Exits before answering anything. The client should see either a
    # closed stdin on write or a closed stdout on read, depending on
    # exactly how the race lands -- either is the correct outcome.
    sys.exit(0)


def run_malformed() -> None:
    # Rejects the probe properly, then answers initialize with garbage, so
    # this exercises JSON handling on the legacy path rather than the probe.
    request = _read_request()
    if request.get("method") == DISCOVER_METHOD:
        _error(request["id"], METHOD_NOT_FOUND, "Method not found")
        _read_request()
    sys.stdout.write("this is not json\n")
    sys.stdout.flush()


def run_oversized() -> None:
    _read_request()
    # One line, no trailing newline, well past any sane response size --
    # exercises the reader's bounded-size guard rather than its line
    # framing. Stays alive so the client's guard is what ends this, not
    # the fixture exiting on its own.
    sys.stdout.write("x" * 200_000)
    sys.stdout.flush()
    time.sleep(3600)


def run_startup_failure() -> None:
    # The shape of the most common --stdio failure: the server never gets
    # far enough to speak the protocol, and the only explanation goes to
    # stderr. Written without a trailing newline on purpose -- a real
    # traceback cut short still has to reach the user.
    sys.stderr.write("ModuleNotFoundError: No module named 'mcp_does_not_exist'")
    sys.stderr.flush()
    sys.exit(3)


def run_stderr_flood() -> None:
    # A server that logs relentlessly on its way down. The client must quote
    # a readable tail, not paste a megabyte of logging into one error.
    for i in range(5000):
        sys.stderr.write(f"flood-line-{i}\n")
    sys.stderr.flush()
    sys.exit(1)


_MODES = {
    "ok": run_ok,
    "modern": run_modern,
    "unsupported-version": run_unsupported_version,
    "discover-silent": run_discover_silent,
    "startup-failure": run_startup_failure,
    "stderr-flood": run_stderr_flood,
    "paging": run_paging,
    "hang": run_hang,
    "exit": run_exit,
    "malformed": run_malformed,
    "oversized": run_oversized,
}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    _MODES[mode]()


if __name__ == "__main__":
    main()
