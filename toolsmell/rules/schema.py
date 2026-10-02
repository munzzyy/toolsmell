"""Smells about inputSchema parameters and how they relate to the
description: TS-005, 006, 007, 012."""

from __future__ import annotations

import re

from .. import catalog
from ._util import (Tokens, is_one_token, mentions, note, spend,
                    split_name_words, token_pieces)

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


# Characters the regex fallback may read per manifest before TS-005 gives up.
SLOW_PATH_CHARS = 50_000_000


def _mentioned_fast(tokens: Tokens, term: str, all_tools, skipped: list) -> bool:
    """_mentioned(tokens.text, term), by lookup where that gives the same answer."""
    if is_one_token(term):
        return tokens.has(term) or (len(term) >= MIN_STEM_CHARS
                                    and tokens.has_prefix(term))
    pieces = token_pieces(term)
    # Each run must be a whole token; the stem rule lets the last one run on.
    if pieces and not (all(p in tokens.set for p in pieces[:-1])
                       and tokens.has_prefix(pieces[-1])):
        return False
    if not spend(all_tools, "TS-005", SLOW_PATH_CHARS, 2 * len(tokens.text)):
        skipped.append(term)
        return True
    return _mentioned(tokens.text, term)


def _param_mentioned_fast(tokens: Tokens, name: str, all_tools, skipped: list) -> bool:
    if _mentioned_fast(tokens, name, all_tools, skipped):
        return True
    words = split_name_words(name)
    if not words:
        return False
    return all(_mentioned_fast(tokens, w, all_tools, skipped) for w in words)


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
    if desc and params:
        tokens = Tokens(desc)
        skipped = []
        for p in params:
            if not _param_mentioned_fast(tokens, p.name, all_tools, skipped):
                findings.append(catalog.build(
                    "TS-005", tool=tool.name, param=p.name,
                    detail=f"'{tool.name}' parameter '{p.name}' is never "
                           "mentioned in the description."))
        if skipped:
            note(all_tools, "TS-005",
                 f"TS-005 did not check {len(skipped)} parameter name(s) of "
                 f"'{tool.name}' against its description: the manifest used "
                 f"up the {SLOW_PATH_CHARS:,}-character budget for "
                 "names with punctuation in them.")

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
