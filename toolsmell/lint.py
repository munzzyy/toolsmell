"""Lint orchestration: parse tools, run every rule per tool, score, aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field

from .finding import Severity
from .manifest import load_manifest, parse_tools
from .rules import run_all
from .score import overall_score, tool_score


@dataclass
class ToolReport:
    name: str
    findings: list = field(default_factory=list)
    score: int = 0


@dataclass
class LintResult:
    source: str
    tools: list = field(default_factory=list)  # list[ToolReport]
    score: int = 0

    @property
    def findings(self) -> list:
        out = []
        for t in self.tools:
            out.extend(t.findings)
        return out

    def counts(self) -> dict:
        out = {s: 0 for s in Severity}
        for f in self.findings:
            out[f.severity] += 1
        return out


def lint_tools(tools, source: str = "<data>") -> LintResult:
    result = LintResult(source=source)
    for tool in tools:
        findings = run_all(tool, tools)
        findings.sort(key=lambda f: f.sort_key())
        result.tools.append(ToolReport(name=tool.name, findings=findings,
                                        score=tool_score(findings)))
    result.score = overall_score([t.score for t in result.tools])
    return result


def lint_data(data, source: str = "<data>") -> LintResult:
    return lint_tools(parse_tools(data, source=source), source=source)


def lint_path(path) -> LintResult:
    tools = load_manifest(path)
    return lint_tools(tools, source=str(path))
