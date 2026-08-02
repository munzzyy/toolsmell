"""Rule registry. Each rule module exposes check(tool, all_tools) -> list[Finding]."""

from __future__ import annotations

from . import description, examples, naming, schema

# Order is cosmetic; findings are sorted by severity at report time.
ALL_RULES = [
    description.check,
    schema.check,
    naming.check,
    examples.check,
]


def run_all(tool, all_tools, enabled=None) -> list:
    """Every finding for one tool. `enabled` is a set of rule ids to keep, or
    None for all of them. Filtering happens here rather than at report time
    so a suppressed rule drops out of the smell score too."""
    findings = []
    for rule in ALL_RULES:
        findings.extend(rule(tool, all_tools))
    if enabled is None:
        return findings
    return [f for f in findings if f.rule_id in enabled]
