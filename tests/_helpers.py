"""Shared test helpers."""

from __future__ import annotations

import dataclasses

from toolsmell.lint import lint_tools
from toolsmell.manifest import parse_tools


def mk_tool(name: str, description: str = "", schema=None, index: int = 0,
            icons=None):
    """Build a single Tool without going through JSON, for rule unit tests.
    `index` is overridden after parsing so callers can build two distinct
    tools (e.g. for the name-collision rule) with different identities."""
    entry = {
        "name": name,
        "description": description,
        "inputSchema": schema or {},
    }
    if icons is not None:
        entry["icons"] = icons
    tools = parse_tools({"tools": [entry]})
    return dataclasses.replace(tools[0], index=index)


def lint(*tool_dicts, enabled=None):
    """Parse and lint one or more raw tool dicts as if they were one manifest.
    `enabled` restricts which rule ids may report, the same way --ignore and
    --select do."""
    tools = parse_tools({"tools": list(tool_dicts)})
    return lint_tools(tools, source="<test>", enabled=enabled)


def by_rule(result, rule_id: str):
    return [f for f in result.findings if f.rule_id == rule_id]
