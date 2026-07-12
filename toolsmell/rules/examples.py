"""TS-010: a tool with three or more parameters but no example call in its
description leaves an agent to guess the right argument shape."""

from __future__ import annotations

from .. import catalog

_MARKERS = ("example", "e.g.", "eg.", "for instance", "```")


def check(tool, all_tools) -> list:
    params = tool.params
    if len(params) < 3:
        return []
    lowered = tool.description.lower()
    if any(m in lowered for m in _MARKERS):
        return []
    return [catalog.build(
        "TS-010", tool=tool.name,
        detail=f"'{tool.name}' takes {len(params)} parameters but the "
               "description has no example call.")]
