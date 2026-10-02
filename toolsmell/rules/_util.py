"""Shared text helpers for rule modules, and the per-manifest state that
lets a cross-tool rule build one index instead of comparing every pair."""

from __future__ import annotations

import bisect
import re

_WORD = re.compile(r"[A-Za-z0-9]+")


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def first_word(text: str) -> str:
    m = _WORD.search(text)
    return m.group(0).lower() if m else ""


def mentions(text: str, term: str) -> bool:
    """Case-insensitive whole-token check. A bare substring test would count
    a short param name like 'id' or 'q' as mentioned by any word that merely
    contains it ('Provide', 'query'), so the most common short names could
    never be flagged. Match on alphanumeric boundaries instead."""
    if not term:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def split_name_words(name: str) -> list:
    """Split a snake_case / camelCase / kebab-case identifier into lowercase
    words, e.g. 'fromCurrency' or 'from_currency' -> ['from', 'currency']."""
    spaced = re.sub(r"[_\-]+", " ", name)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return [w.lower() for w in _WORD.findall(spaced)]


class ToolList(list):
    """The tools of one manifest, with room for a cross-tool rule to keep
    an index, a work budget and notes for stderr. A plain list works too;
    the helpers below then rebuild the index per call."""

    def __init__(self, tools=()):
        super().__init__(tools)
        self.indexes = {}
        self.budgets = {}
        self.notes = []


def manifest_index(all_tools, build):
    """build(all_tools), computed once per ToolList."""
    cache = getattr(all_tools, "indexes", None)
    if cache is None:
        return build(all_tools)
    if build not in cache:
        cache[build] = build(all_tools)
    return cache[build]


def spend(all_tools, key: str, start: int, amount: int) -> bool:
    """Take `amount` from the per-manifest budget `key`, which starts at
    `start`. False once it would go negative; a plain list never runs out."""
    budgets = getattr(all_tools, "budgets", None)
    if budgets is None:
        return True
    left = budgets.get(key, start)
    if left < amount:
        budgets[key] = -1
        return False
    budgets[key] = left - amount
    return True


def note(all_tools, rule_id: str, message: str) -> None:
    notes = getattr(all_tools, "notes", None)
    if notes is not None and (rule_id, message) not in notes:
        notes.append((rule_id, message))


# With IGNORECASE this class also takes the four letters below, as mentions() does.
_TOKEN = re.compile(r"[A-Za-z0-9]+", re.IGNORECASE)
_FOLD = str.maketrans({"\u0130": "i", "\u0131": "i", "\u017f": "s", "\u212a": "k"})


def _fold(token: str) -> str:
    return token.translate(_FOLD).lower()


def token_pieces(term: str) -> list:
    """The folded alphanumeric runs in `term`."""
    return [_fold(t) for t in _TOKEN.findall(term)]


def is_one_token(term: str) -> bool:
    return _TOKEN.fullmatch(term) is not None


class Tokens:
    """The folded alphanumeric runs of a text. For a one-run term, has()
    answers what mentions(text, term) does, without a pass over the text."""

    def __init__(self, text: str):
        self.text = text
        self.set = {_fold(t) for t in _TOKEN.findall(text)}
        self._sorted = None

    def has(self, term: str) -> bool:
        return _fold(term) in self.set

    def has_prefix(self, stem: str) -> bool:
        if self._sorted is None:
            self._sorted = sorted(self.set)
        stem = _fold(stem)
        i = bisect.bisect_left(self._sorted, stem)
        return i < len(self._sorted) and self._sorted[i].startswith(stem)
