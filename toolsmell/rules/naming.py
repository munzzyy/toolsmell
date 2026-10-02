"""TS-009: tool names that collide closely enough for an agent to pick the
wrong one -- names equal once case and separators are ignored, one name as
a near-prefix of another, or a short edit distance between otherwise
similar-length names. An exact duplicate is TS-018's finding, not this one:
a client keeps only one of the two, so there is no wrong one to call."""

from __future__ import annotations

import re

from .. import catalog
from ._util import manifest_index, note, spend

_SEP = re.compile(r"[_\-\s]+")

PREFIX_MIN = 4
PREFIX_MAX_EXTRA = 4
EDIT_MIN = 6
EDIT_MAX = 2

# Four medium findings already reach the 100-point cap; more only grow the report.
MAX_FINDINGS = 4

# Checks before the edit-distance search gives up; long pairs cost more than one.
EDIT_BUDGET = 2_000_000


def _normalized(name: str) -> str:
    return _SEP.sub("", name.lower())


def _levenshtein(a: str, b: str, max_distance: int | None = None) -> int:
    """Edit distance between a and b. When max_distance is given, abandon as
    soon as a whole row exceeds it and return max_distance + 1 -- the caller
    only cares whether the distance clears a small threshold, and bailing
    early keeps a pair of long, dissimilar names from paying the full O(n*m)
    fill."""
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
        if max_distance is not None and min(cur) > max_distance:
            return max_distance + 1
        prev = cur
    return prev[-1]


def _common_prefix(a: str, b: str) -> int:
    if a[:1] != b[:1]:
        return 0
    lo, hi = 1, min(len(a), len(b))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if a[:mid] == b[:mid]:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _within(a: str, b: str, k: int) -> bool:
    """Whether a and b are at most k edits apart. Slices off the equal ends,
    then branches on the first differing character. One edit leaves at most
    one character per side once the ends are gone, so k == 1 needs no branch."""
    if abs(len(a) - len(b)) > k:
        return False
    i = _common_prefix(a, b)
    a, b = a[i:], b[i:]
    j = _common_prefix(a[::-1], b[::-1])
    a, b = a[:len(a) - j], b[:len(b) - j]
    if max(len(a), len(b)) <= k:
        return True
    if k <= 1:
        return False
    return (_within(a[1:], b[1:], k - 1) or _within(a[1:], b, k - 1)
            or _within(a, b[1:], k - 1))


def _collides(a: str, b: str) -> bool:
    na, nb = _normalized(a), _normalized(b)
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if (len(shorter) >= PREFIX_MIN and longer.startswith(shorter)
            and len(longer) - len(shorter) <= PREFIX_MAX_EXTRA):
        return True
    return (min(len(na), len(nb)) >= EDIT_MIN and abs(len(na) - len(nb)) <= EDIT_MAX
            and _within(na, nb, EDIT_MAX))


def _segments(length: int) -> list:
    """EDIT_MAX + 1 (start, size) chunks of a name this long. Two edits touch
    at most two, so a near name shares one of them nearly in place."""
    parts = EDIT_MAX + 1
    short, extra = divmod(length, parts)
    out, start = [], 0
    for i in range(parts):
        size = short + (1 if i >= parts - extra else 0)
        out.append((start, size))
        start += size
    return out


def _edit_pairs(norms: list, all_tools) -> set:
    """Pairs of distinct normalized names within EDIT_MAX edits, both at
    least EDIT_MIN long, by Pass-Join (Li et al., VLDB 2011) chunk lookup."""
    pairs = set()
    index = {}
    for s in sorted((n for n in norms if len(n) >= EDIT_MIN), key=lambda n: (len(n), n)):
        seen = set()
        for length in range(max(EDIT_MIN, len(s) - EDIT_MAX), len(s) + 1):
            delta = len(s) - length
            for i, (start, size) in enumerate(_segments(length), 1):
                lo = max(-(i - 1), delta - (EDIT_MAX + 1 - i))
                hi = min(i - 1, delta + (EDIT_MAX + 1 - i))
                for shift in range(lo, hi + 1):
                    at = start + shift
                    if at < 0 or at + size > len(s):
                        continue
                    for r in index.get((length, i, s[at:at + size]), ()):
                        if r in seen:
                            continue
                        seen.add(r)
                        cost = 1 + (len(r) + len(s)) // 1000
                        if not spend(all_tools, "TS-009", EDIT_BUDGET, cost):
                            note(all_tools, "TS-009",
                                 "TS-009 stopped looking for names a couple of "
                                 f"edits apart after {EDIT_BUDGET:,} comparisons. "
                                 "Case, separator and prefix collisions were "
                                 "all still checked.")
                            return pairs
                        if _within(r, s, EDIT_MAX):
                            pairs.add((r, s))
        for i, (start, size) in enumerate(_segments(len(s)), 1):
            index.setdefault((len(s), i, s[start:start + size]), []).append(s)
    return pairs


def _prefix_pairs(norms: list) -> set:
    present = set(norms)
    pairs = set()
    for n in norms:
        for extra in range(1, PREFIX_MAX_EXTRA + 1):
            head = n[:-extra]
            if len(head) < PREFIX_MIN:
                break
            if head in present:
                pairs.add((head, n))
    return pairs


def _collision_index(all_tools) -> dict:
    """tool index -> (first MAX_FINDINGS colliding tools by index, total)."""
    groups = {}
    for t in all_tools:
        groups.setdefault(_normalized(t.name), []).append(t)
    norms = list(groups)
    partners = {}
    for a, b in _prefix_pairs(norms) | _edit_pairs(norms, all_tools):
        partners.setdefault(a, set()).add(b)
        partners.setdefault(b, set()).add(a)

    out = {}
    for norm, members in groups.items():
        members.sort(key=lambda t: t.index)
        outside_first, outside_count = [], 0
        for other in partners.get(norm, ()):
            outside_first.extend(groups[other][:MAX_FINDINGS])
            outside_count += len(groups[other])
        outside_first = sorted(outside_first, key=lambda o: o.index)[:MAX_FINDINGS]
        by_name = {}
        for t in members:
            by_name.setdefault(t.name, []).append(t)
        for t in members:
            # The first few of each other spelling hold the lowest indices.
            inside_first = []
            taken = 0
            for name, same in by_name.items():
                if name == t.name:
                    continue
                inside_first.extend(same[:MAX_FINDINGS])
                taken += 1
                if taken == MAX_FINDINGS:
                    break
            others = sorted(inside_first + outside_first, key=lambda o: o.index)
            count = len(members) - len(by_name[t.name]) + outside_count
            if count:
                out[t.index] = (others[:MAX_FINDINGS], count)
    return out


def check(tool, all_tools) -> list:
    others, count = manifest_index(all_tools, _collision_index).get(tool.index, ([], 0))
    findings = []
    for n, other in enumerate(others, 1):
        more = count - len(others) if n == len(others) else 0
        also = f", and of {more} more tool(s) not listed" if more else ""
        findings.append(catalog.build(
            "TS-009", tool=tool.name,
            detail=f"'{tool.name}' is a near-duplicate of '{other.name}'{also} "
                   "-- an agent could easily call the wrong one."))
    return findings
