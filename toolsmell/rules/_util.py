"""Shared text helpers for rule modules."""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9]+")


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def first_word(text: str) -> str:
    m = _WORD.search(text)
    return m.group(0).lower() if m else ""


def mentions(text: str, term: str) -> bool:
    """Case-insensitive substring check."""
    return term.lower() in text.lower()


def split_name_words(name: str) -> list:
    """Split a snake_case / camelCase / kebab-case identifier into lowercase
    words, e.g. 'fromCurrency' or 'from_currency' -> ['from', 'currency']."""
    spaced = re.sub(r"[_\-]+", " ", name)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return [w.lower() for w in _WORD.findall(spaced)]
