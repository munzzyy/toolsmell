"""Smells about the tool-level description text: TS-001, 002, 003, 004,
008, 011. Everything here reads tool.description in isolation; parameter
cross-checks live in schema.py."""

from __future__ import annotations

import re

from .. import catalog
from ._util import first_word, mentions, word_count

MIN_CHARS = 20
MIN_WORDS = 4

# Spec's own examples of an ambiguous action verb, plus close variants.
_VAGUE_VERBS = {
    "process", "processes", "handle", "handles", "manage", "manages",
    "do", "does", "perform", "performs", "execute", "executes",
}

# Words a vague verb can be immediately followed by without adding any real
# specificity ("handle the data", "process requests").
_FILLER_WORDS = {
    "the", "a", "an", "this", "that", "it", "them", "data", "input",
    "request", "requests", "item", "items", "thing", "things", "stuff",
    "info", "information",
}

_RETURN_WORDS = (
    "return", "returns", "returned", "output", "outputs", "response",
    "responds", "result", "results", "yield", "yields", "produce",
    "produces", "provide", "provides",
)

_ERROR_WORDS = (
    "error", "errors", "fail", "fails", "failure", "failures", "invalid",
    "raise", "raises", "raised", "exception", "exceptions", "throw",
    "throws", "thrown", "reject", "rejects",
)

# Verbs that name an action the tool actually performs. "returns"/"raises"
# are deliberately excluded -- they describe the outcome, not a mode of
# operation, and counting them would make TS-011 fire on any well-described
# tool.
_ACTION_VERBS = {
    "create", "creates", "delete", "deletes", "update", "updates", "fetch",
    "fetches", "list", "lists", "search", "searches", "send", "sends",
    "remove", "removes", "modify", "modifies", "get", "gets", "set",
    "sets", "generate", "generates", "convert", "converts", "upload",
    "uploads", "download", "downloads", "sync", "syncs", "merge",
    "merges", "validate", "validates", "parse", "parses", "publish",
    "publishes", "cancel", "cancels", "schedule", "schedules",
}

_JOINER = re.compile(r"\band\b|\bor\b", re.IGNORECASE)


def _is_vague_only(desc: str) -> bool:
    fw = first_word(desc)
    if fw not in _VAGUE_VERBS:
        return False
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", desc)]
    remainder = [w for w in words[1:] if w not in _FILLER_WORDS]
    return len(remainder) == 0


def check(tool, all_tools) -> list:
    findings = []
    desc = tool.description.strip()

    if not desc:
        findings.append(catalog.build(
            "TS-001", tool=tool.name,
            detail=f"'{tool.name}' has no description."))
        return findings  # nothing else worth checking without any text

    n_chars = len(desc)
    n_words = word_count(desc)
    if n_chars < MIN_CHARS or n_words < MIN_WORDS:
        findings.append(catalog.build(
            "TS-002", tool=tool.name,
            detail=f"'{tool.name}' description is {n_chars} chars / {n_words} "
                   f"words (want at least {MIN_CHARS} chars and {MIN_WORDS} "
                   "words to disambiguate it from similar tools)."))

    if not any(mentions(desc, w) for w in _RETURN_WORDS):
        findings.append(catalog.build(
            "TS-003", tool=tool.name,
            detail=f"'{tool.name}' description never says what the tool returns."))

    if _is_vague_only(desc):
        findings.append(catalog.build(
            "TS-004", tool=tool.name,
            detail=f"'{tool.name}' description is just '{desc}' -- a vague "
                   "verb with nothing about what it acts on."))

    if not any(mentions(desc, w) for w in _ERROR_WORDS):
        findings.append(catalog.build(
            "TS-008", tool=tool.name,
            detail=f"'{tool.name}' description never says what happens on "
                   "bad input or failure."))

    lowered = desc.lower()
    verb_hits = {v for v in _ACTION_VERBS if re.search(rf"\b{re.escape(v)}\b", lowered)}
    joiners = len(_JOINER.findall(desc))
    if len(verb_hits) >= 4 or (len(verb_hits) >= 2 and joiners >= 2):
        findings.append(catalog.build(
            "TS-011", tool=tool.name,
            detail=f"'{tool.name}' description names multiple actions "
                   f"({', '.join(sorted(verb_hits))}) -- looks like it does "
                   "more than one job."))

    return findings
