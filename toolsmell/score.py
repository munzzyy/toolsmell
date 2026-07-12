"""Turn findings into a 0-100 smell score. Higher means smellier.

A tool's score is the sum of its findings' severity weights, capped at 100.
The manifest's overall score is the average of its tools' scores (also
capped), so one badly documented tool in an otherwise clean manifest isn't
buried by a dozen clean ones.
"""

from __future__ import annotations

from .finding import Severity

_WEIGHT = {
    Severity.MEDIUM: 25,
    Severity.LOW: 10,
    Severity.INFO: 3,
}


def tool_score(findings) -> int:
    total = sum(_WEIGHT.get(f.severity, 0) for f in findings)
    return min(100, total)


def overall_score(tool_scores) -> int:
    if not tool_scores:
        return 0
    return round(sum(tool_scores) / len(tool_scores))
