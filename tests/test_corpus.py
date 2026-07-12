"""Labeled-corpus gate. Every smelly fixture must score above the floor
(recall) and every clean fixture must stay under it (precision). These are
the numbers CI enforces -- a rule change that starts missing real smells or
flagging well-written tools fails here."""

from __future__ import annotations

import unittest
from pathlib import Path

from toolsmell.lint import lint_path

CORPUS = Path(__file__).parent / "corpus"
FLOOR = 40  # smelly fixtures must clear this; clean fixtures must stay under it


class SmellyRecall(unittest.TestCase):
    def test_every_smelly_manifest_scores_high(self):
        files = sorted((CORPUS / "smelly").glob("*.json"))
        self.assertTrue(files, "no smelly fixtures found")
        for f in files:
            with self.subTest(manifest=f.name):
                result = lint_path(f)
                self.assertTrue(result.findings, f"{f.name}: nothing flagged")
                self.assertGreaterEqual(
                    result.score, FLOOR,
                    f"{f.name}: score {result.score} too low for a smelly fixture")


class CleanPrecision(unittest.TestCase):
    def test_every_clean_manifest_stays_low(self):
        files = sorted((CORPUS / "clean").glob("*.json"))
        self.assertTrue(files, "no clean fixtures found")
        for f in files:
            with self.subTest(manifest=f.name):
                result = lint_path(f)
                self.assertLess(
                    result.score, FLOOR,
                    f"{f.name}: score {result.score} too high for a clean fixture; "
                    f"findings: {[fi.title for fi in result.findings]}")


if __name__ == "__main__":
    unittest.main()
