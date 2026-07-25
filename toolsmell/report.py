"""Render a LintResult as human text or JSON."""

from __future__ import annotations

import json
import unicodedata

from . import __version__
from .finding import Severity

_COLOR = {
    Severity.MEDIUM: "\033[31m",
    Severity.LOW: "\033[33m",
    Severity.INFO: "\033[90m",
}
_RESET = "\033[0m"


def _clean(s: str) -> str:
    """Neutralize text that ultimately comes from the manifest before it
    reaches a terminal. A manifest is untrusted input, and a tool name or
    description crafted to smuggle escape sequences into whoever's terminal
    is linting it is exactly the kind of thing this tool exists to be fed.

    Control characters (Cc, e.g. a raw ANSI escape) are dropped. Format and
    line/paragraph separators (Cf/Zl/Zp -- right-to-left overrides,
    zero-width joiners, and the like) are escaped to \\uXXXX rather than
    dropped, so a name spoofed with bidi or invisible characters shows up as
    visibly weird instead of being silently normalized into something that
    renders as an innocent string. Tab and newline are kept as-is."""
    out = []
    for ch in s:
        if ch in ("\t", "\n"):
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat == "Cc":
            continue
        if cat in ("Cf", "Zl", "Zp"):
            out.append(f"\\u{ord(ch):04x}")
            continue
        out.append(ch)
    return "".join(out)


def render_human(result, color: bool = True) -> str:
    def c(code, s):
        return f"{code}{s}{_RESET}" if color else s

    source = _clean(result.source)
    lines = ["", f"  toolsmell  {source}", f"  {len(result.tools)} tool(s) checked", ""]

    for t in result.tools:
        name = _clean(t.name)
        header = f"  {name}  (smell {t.score}/100)"
        lines.append(c("\033[1m", header) if color else header)
        if not t.findings:
            lines.append(c("\033[32m", "    no smells found"))
        for f in t.findings:
            tag = c(_COLOR[f.severity], f" {f.severity.label.upper():^6} ")
            param = _clean(f.param)
            loc = f" | {param}" if param else ""
            lines.append(f"   {tag} {_clean(f.title)}  [{f.rule_id}{loc}]")
            lines.append(f"          {_clean(f.detail)}")
            lines.append(c("\033[90m", f"          fix: {_clean(f.fix)}"))
        lines.append("")

    counts = result.counts()
    parts = []
    for sev in (Severity.MEDIUM, Severity.LOW, Severity.INFO):
        if counts[sev]:
            parts.append(c(_COLOR[sev], f"{counts[sev]} {sev.label}"))
    total = sum(counts.values())
    summary = "  " + (", ".join(parts) if parts else "0 smells")
    lines.append(summary + f"   ({total} total)")
    lines.append(f"  Overall smell score: {result.score}/100")
    lines.append("")
    return "\n".join(lines)


def _json_payload(result) -> dict:
    counts = result.counts()
    return {
        "tool": "toolsmell",
        "version": __version__,
        "source": result.source,
        "score": result.score,
        "counts": {s.label: counts[s] for s in Severity},
        "tools": [
            {
                "name": t.name,
                "score": t.score,
                "findings": [
                    {
                        "rule_id": f.rule_id,
                        "severity": f.severity.label,
                        "param": f.param,
                        "title": f.title,
                        "detail": f.detail,
                        "fix": f.fix,
                    }
                    for f in t.findings
                ],
            }
            for t in result.tools
        ],
    }


def render_json(result) -> str:
    return json.dumps(_json_payload(result), indent=2)


def render_json_multi(results) -> str:
    """One JSON array covering several linted files. Printing one
    render_json document per file would emit concatenated objects that
    json.load / JSON.parse reject; an array is a single valid document."""
    return json.dumps([_json_payload(r) for r in results], indent=2)
