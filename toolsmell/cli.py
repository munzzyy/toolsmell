"""Command-line interface for toolsmell."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .catalog import all_rules
from .lint import lint_path
from .manifest import ManifestError
from .report import render_human, render_json


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="toolsmell",
        description="Lint an MCP server's tool descriptions and JSON schemas "
                     "for smells that make agents use the tools worse.",
    )
    p.add_argument(
        "target", nargs="?",
        help="path to a tools/list JSON file (a {\"tools\": [...]} manifest)")
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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_rules:
        _print_rules()
        return 0

    if not args.target:
        print("toolsmell: a target JSON file is required (or use --list-rules)",
              file=sys.stderr)
        return 2

    if not os.path.exists(args.target):
        print(f"toolsmell: no such file: {args.target}", file=sys.stderr)
        return 2

    try:
        result = lint_path(args.target)
    except ManifestError as e:
        print(f"toolsmell: {e}", file=sys.stderr)
        return 2

    color = not args.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    if args.json:
        print(render_json(result))
    else:
        print(render_human(result, color=color))

    if result.score >= args.max_score:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
