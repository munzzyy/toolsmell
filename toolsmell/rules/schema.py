"""Smells about inputSchema parameters and how they relate to the
description: TS-005, 006, 007, 012."""

from __future__ import annotations

import re

from .. import catalog
from ._util import mentions, split_name_words

_ENUM_PHRASE = re.compile(
    r"\b(one of|either|allowed values?|options? (?:are|include)|must be)\b",
    re.IGNORECASE,
)
# A quoted or backtick-quoted bare token, e.g. 'asc', "desc", `relevance`.
_QUOTED_TOKEN = re.compile(r"""(['"`])([A-Za-z0-9_\-]+)\1""")


# Below this length a prefix match stops carrying information: 'id' would be
# "mentioned" by 'identity', 'idle' or 'ideal'. Four characters is where a
# shared prefix starts meaning the description is genuinely talking about
# the parameter.
MIN_STEM_CHARS = 4


def _stem_mentioned(desc: str, name: str) -> bool:
    """Whether the description has a word that starts with `name`.

    'repo' is documented by "in a GitHub repository", 'config' by
    'configuration', 'auth' by 'authentication'. The whole-token rule in
    mentions() calls all of those undocumented, and TS-005 is the heaviest
    rule in the score, so that false positive costs a well-written tool 25
    points on its own. The length floor keeps the strict behaviour for the
    short names the whole-token rule exists to protect.
    """
    if len(name) < MIN_STEM_CHARS:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(name)}[A-Za-z0-9]*(?![A-Za-z0-9])"
    return re.search(pattern, desc, re.IGNORECASE) is not None


def _mentioned(desc: str, term: str) -> bool:
    return mentions(desc, term) or _stem_mentioned(desc, term)


def _param_mentioned(desc: str, name: str) -> bool:
    if _mentioned(desc, name):
        return True
    words = split_name_words(name)
    if not words:
        return False
    return all(_mentioned(desc, w) for w in words)


def _looks_enum_worthy(desc: str) -> bool:
    if not desc:
        return False
    tokens = _QUOTED_TOKEN.findall(desc)
    if len(tokens) >= 3:
        return True
    return bool(tokens) and bool(_ENUM_PHRASE.search(desc))


def check(tool, all_tools) -> list:
    findings = []
    params = tool.params
    desc = tool.description.strip()

    # Undocumented params pile on when there is no description at all --
    # TS-001 already covers that case, so only check here once there is
    # some text a parameter could plausibly be mentioned in.
    if desc:
        for p in params:
            if not _param_mentioned(desc, p.name):
                findings.append(catalog.build(
                    "TS-005", tool=tool.name, param=p.name,
                    detail=f"'{tool.name}' parameter '{p.name}' is never "
                           "mentioned in the description."))

    for p in params:
        if not p.description.strip():
            findings.append(catalog.build(
                "TS-006", tool=tool.name, param=p.name,
                detail=f"'{tool.name}' parameter '{p.name}' has no "
                       "'description' in its schema."))

    if params and not tool.has_required_field:
        findings.append(catalog.build(
            "TS-007", tool=tool.name,
            detail=f"'{tool.name}' defines parameters but the schema has no "
                   "'required' list, so an agent can't tell which are "
                   "mandatory."))

    for p in params:
        if "string" in p.type_set and not p.has_enum and _looks_enum_worthy(p.description):
            findings.append(catalog.build(
                "TS-012", tool=tool.name, param=p.name,
                detail=f"'{tool.name}' parameter '{p.name}' spells out "
                       f"allowed values in prose ({p.description!r}) instead "
                       "of using a schema enum."))

    return findings
