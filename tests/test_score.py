"""Scoring: severity weights, per-tool capping, and the manifest average."""

from __future__ import annotations

import unittest

from toolsmell.finding import Finding, Severity
from toolsmell.score import overall_score, tool_score


def _f(sev):
    return Finding("TS-000", sev, "t", "", "title", "detail", "fix")


class ToolScore(unittest.TestCase):
    def test_no_findings_is_zero(self):
        self.assertEqual(tool_score([]), 0)

    def test_single_medium(self):
        self.assertEqual(tool_score([_f(Severity.MEDIUM)]), 25)

    def test_mixed_severities_sum(self):
        score = tool_score([_f(Severity.MEDIUM), _f(Severity.LOW), _f(Severity.INFO)])
        self.assertEqual(score, 25 + 10 + 3)

    def test_score_caps_at_100(self):
        score = tool_score([_f(Severity.MEDIUM) for _ in range(10)])
        self.assertEqual(score, 100)


class OverallScore(unittest.TestCase):
    def test_no_tools_is_zero(self):
        self.assertEqual(overall_score([]), 0)

    def test_single_tool_passthrough(self):
        self.assertEqual(overall_score([42]), 42)

    def test_averages_across_tools(self):
        self.assertEqual(overall_score([0, 100]), 50)

    def test_one_bad_tool_still_moves_the_average(self):
        # A single very smelly tool among clean ones should not be buried.
        self.assertGreater(overall_score([0, 0, 0, 100]), 0)

    def test_result_capped_at_100(self):
        self.assertEqual(overall_score([100, 100]), 100)


if __name__ == "__main__":
    unittest.main()
