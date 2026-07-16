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


TOOLS_RESULT = {
    "tools": [{
        "name": "get_weather",
        "description": "Handles requests.",
        "inputSchema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
        },
    }],
}


def run_ok() -> None:
    init = _read_request()
    _write({"jsonrpc": "2.0", "id": init["id"], "result": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "serverInfo": {"name": "fake-mcp-server", "version": "0"},
    }})
    sys.stdin.readline()  # notifications/initialized -- no response expected
    list_request = _read_request()
    _write({"jsonrpc": "2.0", "id": list_request["id"], "result": TOOLS_RESULT})


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


_MODES = {
    "ok": run_ok,
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
