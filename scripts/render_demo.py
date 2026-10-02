#!/usr/bin/env python3
"""Draw docs/media/demo.svg from a live run over examples/smelly-tools.json.

    python3 scripts/render_demo.py           # rewrite the SVG
    python3 scripts/render_demo.py --check   # exit 1 if the SVG is stale
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from toolsmell.lint import lint_path  # noqa: E402
from toolsmell.report import render_human  # noqa: E402

EXAMPLE = "examples/smelly-tools.json"
OUT = ROOT / "docs" / "media" / "demo.svg"

WIDTH = 840
COLUMNS = 96
CHAR_WIDTH = 8.42
LEFT = 16.0
TOP = 44
LINE_HEIGHT = 19

DEFAULT = "#abb2bf"
PROMPT = "#98c379"
ANSI = {"31": "#e06c75", "32": "#98c379", "33": "#e5c07b", "90": "#5c6370"}
_SGR = re.compile(r"(\x1b\[[0-9;]*m)")


def _spans(line: str) -> list:
    """(text, color, bold) runs of one line of colored report output."""
    out = []
    color, bold = DEFAULT, False
    for part in _SGR.split(line):
        code = part[2:-1] if _SGR.fullmatch(part) else None
        if code is None:
            if part:
                out.append((part, color, bold))
        elif code in ("", "0"):
            color, bold = DEFAULT, False
        elif code == "1":
            bold = True
        else:
            color = ANSI[code]
    return out


def _breaks(text: str) -> list:
    """(start, end, indent) rows for one line, broken only at spaces.
    Continuation rows hang under the first word, or under the text after
    'fix: ' on a fix line."""
    lead = len(text) - len(text.lstrip(" "))
    indent = lead + (5 if text.lstrip(" ").startswith("fix: ") else 0)
    rows, start, pad = [], 0, 0
    while pad + len(text) - start > COLUMNS:
        limit = start + COLUMNS - pad
        cut = text.rfind(" ", start + 1, limit + 1)
        if cut <= start:
            cut = limit
        rows.append((start, cut, pad))
        start = cut
        while start < len(text) and text[start] == " ":
            start += 1
        pad = indent
    rows.append((start, len(text), pad))
    return rows


def _text(x: float, y: int, color: str, bold: bool, body: str) -> str:
    weight = "bold" if bold else "normal"
    return (f'<text x="{x:.1f}" y="{y}" fill="{color}" font-weight="{weight}" '
            f'xml:space="preserve">{html.escape(body)}</text>')


def render() -> str:
    os.chdir(ROOT)
    report = render_human(lint_path(EXAMPLE), color=True)
    lines = [[("$", PROMPT, False), (f" toolsmell {EXAMPLE}", DEFAULT, False)]]
    lines += [_spans(line) for line in report.split("\n")]

    body, row = [], 0
    for spans in lines:
        text = "".join(t for t, _, _ in spans)
        for start, end, pad in _breaks(text):
            y = TOP + LINE_HEIGHT * row
            col, pos = pad, 0
            for piece, color, bold in spans:
                lo, hi = max(start, pos), min(end, pos + len(piece))
                if lo < hi:
                    body.append(_text(LEFT + CHAR_WIDTH * col, y, color, bold,
                                      piece[lo - pos:hi - pos]))
                    col += hi - lo
                pos += len(piece)
            row += 1
    height = TOP + LINE_HEIGHT * (row - 1) + 16

    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="14">',
        f'<rect width="{WIDTH}" height="{height}" rx="8" fill="#0d1117"/>',
        f'<rect width="{WIDTH}" height="30" rx="8" fill="#161b22"/>',
        f'<rect y="22" width="{WIDTH}" height="8" fill="#161b22"/>',
        '<circle cx="18" cy="15" r="5.5" fill="#ff5f57"/>',
        '<circle cx="38" cy="15" r="5.5" fill="#febc2e"/>',
        '<circle cx="58" cy="15" r="5.5" fill="#28c840"/>',
        f'<text x="{WIDTH // 2}" y="19" text-anchor="middle" fill="#8b949e" '
        f'font-size="12">toolsmell {EXAMPLE}</text>',
    ]
    return "\n".join(head + body + ["</svg>"]) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if docs/media/demo.svg is not what this would write")
    args = parser.parse_args(argv)
    svg = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != svg:
            print(f"{OUT.relative_to(ROOT)} is stale; run scripts/render_demo.py",
                  file=sys.stderr)
            return 1
        return 0
    OUT.write_text(svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
