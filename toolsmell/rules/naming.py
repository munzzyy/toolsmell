"""TS-009: tool names that collide closely enough for an agent to pick the
wrong one -- exact duplicates, one name as a near-prefix of another, or a
short edit distance between otherwise similar-length names."""

from __future__ import annotations

import re

from .. import catalog

_SEP = re.compile(r"[_\-\s]+")


def _normalized(name: str) -> str:
    return _SEP.sub("", name.lower())


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _collides(a: str, b: str) -> bool:
    na, nb = _normalized(a), _normalized(b)
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 4 and longer.startswith(shorter) and len(longer) - len(shorter) <= 4:
        return True
    if min(len(na), len(nb)) >= 6 and _levenshtein(na, nb) <= 2:
        return True
    return False


def check(tool, all_tools) -> list:
    findings = []
    for other in all_tools:
        if other.index == tool.index:
            continue
        if _collides(tool.name, other.name):
            findings.append(catalog.build(
                "TS-009", tool=tool.name,
                detail=f"'{tool.name}' is a near-duplicate of '{other.name}' "
                       "-- an agent could easily call the wrong one."))
    return findings
