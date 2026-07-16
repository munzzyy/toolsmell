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
from .report import render_human, render_json


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
    p.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p.add_argument("--list-rules", action="store_true", help="print every rule id and exit")
    p.add_argument("--version", action="version", version=f"toolsmell {__version__}")
    return p


def _print_rules() -> None:
    for r in all_rules():
        print(f"{r.id}  [{r.severity.label:>6}]  {r.title}")


def _report(result, args, color: bool) -> bool:
    """Print one lint result and say whether it should fail the run."""
    if args.json:
        print(render_json(result))
    else:
        print(render_human(result, color=color))
    return result.score >= args.max_score


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

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
    for target_path in args.target:
        if not os.path.exists(target_path):
            print(f"toolsmell: no such file: {target_path}", file=sys.stderr)
            return 2

        try:
            result = lint_path(target_path)
        except ManifestError as e:
            print(f"toolsmell: {e}", file=sys.stderr)
            return 2

        if _report(result, args, color):
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
