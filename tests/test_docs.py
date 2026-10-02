"""Drift checks between the code and the docs that quote it: the rule ids
in docs/rules.md, the sample runs in the README, and the demo SVG."""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
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


def _live(example: str) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("NO_COLOR", None)
    run = subprocess.run([sys.executable, "-m", "toolsmell", example, "--no-color"],
                         cwd=ROOT, env=env, capture_output=True, text=True,
                         encoding="utf-8")
    return run.stdout


def _readme_block(command: str) -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"```\n\$ " + re.escape(command) + r"\n(.*?)```", readme, re.S)
    if match is None:
        raise AssertionError(f"README has no sample block for {command!r}")
    return match.group(1)


class ReadmeSamples(unittest.TestCase):
    """The two sample runs in the README are pasted output. A rule message
    change has to show up there too."""

    def test_sample_blocks_match_a_live_run(self):
        for example in ("examples/weather-tool-smelly.json",
                        "examples/weather-tool-clean.json"):
            with self.subTest(example=example):
                block = _readme_block(f"toolsmell {example} --no-color")
                self.assertEqual(block.rstrip("\n"), _live(example).rstrip("\n"))


def _svg_rows():
    svg = (ROOT / "docs" / "media" / "demo.svg").read_text(encoding="utf-8")
    rows = {}
    for m in re.finditer(r'<text x="([\d.]+)" y="(\d+)"[^>]*xml:space="preserve">(.*?)</text>',
                         svg):
        rows.setdefault(int(m.group(2)), []).append((float(m.group(1)), html.unescape(m.group(3))))
    return ["".join(t for _, t in sorted(parts)) for _, parts in sorted(rows.items())]


class DemoSvg(unittest.TestCase):
    """docs/media/demo.svg is drawn by scripts/render_demo.py from a live run."""

    def setUp(self):
        self.live = "$ toolsmell examples/smelly-tools.json\n" + _live("examples/smelly-tools.json")
        self.rows = _svg_rows()

    def test_text_matches_a_live_run(self):
        self.assertEqual(re.sub(r"\s+", "", "".join(self.rows)),
                         re.sub(r"\s+", "", self.live))

    def test_rows_break_only_between_words(self):
        # A row cut mid-word splits one word in two, so the word lists differ.
        svg_words = [w for row in self.rows for w in row.split()]
        self.assertEqual(svg_words, self.live.split())

    def test_no_row_is_wider_than_the_frame(self):
        script = (ROOT / "scripts" / "render_demo.py").read_text(encoding="utf-8")
        columns = int(re.search(r"^COLUMNS = (\d+)$", script, re.M).group(1))
        self.assertLessEqual(max(len(row) for row in self.rows), columns)

    def test_readme_alt_text_has_the_live_score(self):
        score = re.search(r"Overall smell score: (\d+)/100", self.live).group(1)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"overall smell {score} of 100", readme)

    def test_render_script_check_passes(self):
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_demo.py"), "--check"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
