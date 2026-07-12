"""Core types: severity and a single smell finding."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.IntEnum):
    """Ordered so comparisons and sorting work (higher = smellier). toolsmell
    only needs three bands -- these are hygiene smells, not security bugs, so
    there is no high/critical tier."""

    INFO = 0
    LOW = 1
    MEDIUM = 2

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, name: str) -> "Severity":
        try:
            return cls[name.strip().upper()]
        except KeyError:
            raise ValueError(f"unknown severity: {name!r}")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    tool: str   # name of the tool this finding is about
    param: str  # parameter name, or "" if the finding is tool-level
    title: str
    detail: str
    fix: str

    def sort_key(self):
        # Worst first, then stable by rule and parameter.
        return (-int(self.severity), self.rule_id, self.param)
