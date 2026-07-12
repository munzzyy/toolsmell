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


def run_all(tool, all_tools) -> list:
    findings = []
    for rule in ALL_RULES:
        findings.extend(rule(tool, all_tools))
    return findings
