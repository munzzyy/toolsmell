"""docs/rules.md drift check: every rule id in the catalog appears as a
heading in the doc, and the doc documents nothing that no longer exists."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from toolsmell.catalog import all_rules

ROOT = Path(__file__).parent.parent


def _rule_ids_in_doc():
    doc = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")
    return set(re.findall(r"^##\s+(TS-\d{3})", doc, re.MULTILINE))


class RulesDoc(unittest.TestCase):
    def test_every_rule_is_documented(self):
        code_ids = {r.id for r in all_rules()}
        undocumented = code_ids - _rule_ids_in_doc()
        self.assertFalse(undocumented, f"in catalog but not docs/rules.md: {sorted(undocumented)}")

    def test_doc_has_no_ghost_rules(self):
        code_ids = {r.id for r in all_rules()}
        ghosts = _rule_ids_in_doc() - code_ids
        self.assertFalse(ghosts, f"in docs/rules.md but not the catalog: {sorted(ghosts)}")

    def test_doc_covers_every_rule_count(self):
        self.assertEqual(len(_rule_ids_in_doc()), len(all_rules()))


if __name__ == "__main__":
    unittest.main()
