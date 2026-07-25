"""Turn findings into a 0-100 smell score. Higher means smellier.

A tool's score is the sum of its findings' severity weights, capped at 100.
The manifest's overall score is the mean of its tools' scores. A mean does
dilute a single bad tool across its clean siblings, so the overall number
answers "how smelly is this manifest on average", not "is any one tool
bad". To catch a single badly documented tool that the mean would bury,
gate on the per-tool scores too -- see --max-tool-score in the CLI.
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
