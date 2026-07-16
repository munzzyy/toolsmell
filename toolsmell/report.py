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
    """Strip control characters -- including a raw ANSI escape -- out of
    text that ultimately comes from the manifest before it reaches a
    terminal. A manifest is untrusted input, and a tool name or description
    crafted to smuggle escape sequences into whoever's terminal is linting
    it is exactly the kind of thing this tool exists to be fed."""
    return "".join(ch for ch in s if ch in ("\t", "\n") or unicodedata.category(ch) != "Cc")


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


def render_json(result) -> str:
    counts = result.counts()
    payload = {
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
    return json.dumps(payload, indent=2)
