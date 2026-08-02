"""Command-line interface for toolsmell."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .catalog import all_rules
from .lint import lint_data, lint_path
from .manifest import ManifestError
from .mcp_stdio import StdioError, fetch_tools_via_stdio
from .report import _clean, render_human, render_json, render_json_multi


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="toolsmell",
        description="Lint an MCP server's tool descriptions and JSON schemas "
                     "for smells that make agents use the tools worse.",
    )
    p.add_argument(
        "target", nargs="*",
        help="path to a tools/list JSON file (a {\"tools\": [...]} manifest)")
    p.add_argument(
        "--stdio", metavar="CMD",
        help="run CMD as a live MCP server and lint its real tools/list response, "
             "instead of reading a file. This is the one thing in toolsmell that "
             "executes a subprocess -- only point it at a server you already trust")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument(
        "--max-score", type=int, default=50, metavar="N",
        help="exit non-zero if the overall smell score is at or above N (default: 50)")
    p.add_argument(
        "--max-tool-score", type=int, default=None, metavar="N",
        help="also exit non-zero if any single tool scores at or above N. The "
             "overall score is a mean, so one bad tool among many clean ones "
             "can pass --max-score; this gate catches it (default: off)")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p.add_argument("--list-rules", action="store_true", help="print every rule id and exit")
    p.add_argument("--version", action="version", version=f"toolsmell {__version__}")
    return p


def _print_rules() -> None:
    for r in all_rules():
        print(f"{r.id}  [{r.severity.label:>6}]  {r.title}")


def _tools_over_limit(result, args):
    """Tools whose own score is at or above --max-tool-score, or an empty list
    when the flag is off. The overall score is a mean, so one bad tool can hide
    under a passing --max-score -- this is what the per-tool gate catches."""
    if args.max_tool_score is None:
        return []
    return [t for t in result.tools if t.score >= args.max_tool_score]


def _should_fail(result, args) -> bool:
    """Whether a lint result trips a configured gate: the overall mean score,
    or (when set) any single tool's score."""
    if result.score >= args.max_score:
        return True
    return bool(_tools_over_limit(result, args))


def _print_gate_trip(result, args) -> None:
    """Name the tool(s) whose own score tripped --max-tool-score, so a failing
    CI run points at the tool to fix instead of just exiting 1. Goes to stderr
    so it never lands in the --json document or the report piped on stdout.
    Tool names are run through _clean first -- a manifest is untrusted input."""
    over = _tools_over_limit(result, args)
    if not over:
        return
    names = ", ".join(f"{_clean(t.name)} (smell {t.score})" for t in over)
    print(f"toolsmell: {len(over)} tool(s) at or above --max-tool-score "
          f"{args.max_tool_score}: {names}", file=sys.stderr)


def _report(result, args, color: bool) -> bool:
    """Print one lint result and say whether it should fail the run."""
    if args.json:
        print(render_json(result))
    else:
        print(render_human(result, color=color))
    _print_gate_trip(result, args)
    return _should_fail(result, args)


def _force_utf8_output() -> None:
    """Make stdout and stderr accept any character a manifest can contain.

    Python picks the locale encoding for a redirected stream, which on
    Windows is cp1252. A tool name with a CJK or Cyrillic character then
    kills `toolsmell tools.json > out.txt` with a UnicodeEncodeError, and
    the traceback exits 1 -- the same code as a tripped gate, so CI reads a
    crash as a lint failure. Reconfiguring to UTF-8 with errors='replace'
    means a character the terminal genuinely can't show comes out mangled
    instead of taking the whole run down.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _force_utf8_output()

    if args.list_rules:
        _print_rules()
        return 0

    if args.stdio and args.target:
        print("toolsmell: pass either a target file or --stdio, not both",
              file=sys.stderr)
        return 2

    if not args.target and not args.stdio:
        print("toolsmell: a target JSON file is required (or --stdio, or --list-rules)",
              file=sys.stderr)
        return 2

    color = not args.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    if args.stdio:
        try:
            data = fetch_tools_via_stdio(args.stdio)
            result = lint_data(data, source=f"stdio:{args.stdio}")
        except (StdioError, ManifestError) as e:
            print(f"toolsmell: {e}", file=sys.stderr)
            return 2
        return 1 if _report(result, args, color) else 0

    exit_code = 0
    results = []
    for target_path in args.target:
        if not os.path.exists(target_path):
            print(f"toolsmell: no such file: {target_path}", file=sys.stderr)
            return 2

        try:
            result = lint_path(target_path)
        except ManifestError as e:
            print(f"toolsmell: {e}", file=sys.stderr)
            return 2

        results.append(result)
        if _should_fail(result, args):
            exit_code = 1

    # With --json, several files become one JSON array rather than a run of
    # concatenated objects no JSON parser would accept. A single file keeps
    # emitting a bare object, so existing consumers are unaffected.
    if args.json and len(results) > 1:
        print(render_json_multi(results))
        for result in results:
            _print_gate_trip(result, args)
    else:
        for result in results:
            _report(result, args, color)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
