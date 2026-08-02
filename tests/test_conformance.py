"""TS-013 to TS-017: the rules that check the manifest against MCP
2026-07-28 rather than against taste.

A tool that breaks one of these is dropped by a conforming client, so the
failure mode is a tool that silently is not there. These tests pin both
sides of each rule: the violating shape fires, and the legal shape stays
quiet, because a conformance rule that over-fires is worse than none.
"""

from __future__ import annotations

import unittest

from toolsmell.rules import conformance
from tests._helpers import mk_tool


def _ids(findings):
    return [f.rule_id for f in findings]


def _check(tool):
    return _ids(conformance.check(tool, [tool]))


def _param(schema):
    return {"type": "object", "properties": {"trace": schema}}


class ToolName(unittest.TestCase):
    def test_a_normal_name_is_quiet(self):
        for name in ("get_weather", "search.orders", "list-items", "v2"):
            with self.subTest(name=name):
                self.assertNotIn("TS-013", _check(mk_tool(name)))

    def test_a_space_in_the_name_fires(self):
        self.assertIn("TS-013", _check(mk_tool("search orders")))

    def test_punctuation_outside_the_set_fires(self):
        self.assertIn("TS-013", _check(mk_tool("search_orders(v2)")))

    def test_the_offending_character_is_named(self):
        findings = conformance.check(mk_tool("a b"), [])
        detail = next(f.detail for f in findings if f.rule_id == "TS-013")
        self.assertIn("' '", detail)

    def test_a_name_at_the_limit_is_quiet(self):
        self.assertNotIn("TS-013", _check(mk_tool("a" * 128)))

    def test_a_name_over_the_limit_fires(self):
        findings = conformance.check(mk_tool("a" * 129), [])
        detail = next(f.detail for f in findings if f.rule_id == "TS-013")
        self.assertIn("129", detail)


class HeaderSyntax(unittest.TestCase):
    def test_a_plain_token_is_quiet(self):
        t = mk_tool("t", schema=_param({"type": "string", "x-mcp-header": "X-Trace"}))
        self.assertNotIn("TS-014", _check(t))

    def test_no_header_at_all_is_quiet(self):
        self.assertNotIn("TS-014", _check(mk_tool("t", schema=_param({"type": "string"}))))

    def test_an_empty_header_fires(self):
        t = mk_tool("t", schema=_param({"type": "string", "x-mcp-header": ""}))
        self.assertIn("TS-014", _check(t))

    def test_a_non_string_header_fires(self):
        t = mk_tool("t", schema=_param({"type": "string", "x-mcp-header": 7}))
        self.assertIn("TS-014", _check(t))

    def test_a_space_in_the_header_fires(self):
        t = mk_tool("t", schema=_param({"type": "string", "x-mcp-header": "X Trace"}))
        self.assertIn("TS-014", _check(t))

    def test_a_newline_in_the_header_fires_and_says_why(self):
        t = mk_tool("t", schema=_param(
            {"type": "string", "x-mcp-header": "X-Trace\r\nX-Admin: 1"}))
        findings = conformance.check(t, [t])
        detail = next(f.detail for f in findings if f.rule_id == "TS-014")
        self.assertIn("newline", detail)

    def test_the_full_token_charset_is_accepted(self):
        # The odd-looking characters really are legal in a field name. A
        # rule that rejected them would be a false positive on a valid tool.
        t = mk_tool("t", schema=_param(
            {"type": "string", "x-mcp-header": "a!#$%&'*+-.^_`|~0Z"}))
        self.assertNotIn("TS-014", _check(t))


class HeaderDuplicates(unittest.TestCase):
    def _two(self, first: str, second: str):
        return mk_tool("t", schema={"type": "object", "properties": {
            "a": {"type": "string", "x-mcp-header": first},
            "b": {"type": "string", "x-mcp-header": second},
        }})

    def test_distinct_headers_are_quiet(self):
        self.assertNotIn("TS-015", _check(self._two("X-One", "X-Two")))

    def test_an_exact_duplicate_fires(self):
        self.assertIn("TS-015", _check(self._two("X-Trace", "X-Trace")))

    def test_a_case_only_difference_still_fires(self):
        # HTTP field names are compared case-insensitively, so these are one
        # header and one of the two parameter values never arrives.
        self.assertIn("TS-015", _check(self._two("X-Trace", "x-trace")))

    def test_both_parameters_are_named(self):
        findings = conformance.check(self._two("X-Trace", "x-trace"), [])
        detail = next(f.detail for f in findings if f.rule_id == "TS-015")
        self.assertIn("'a'", detail)
        self.assertIn("'b'", detail)

    def test_an_invalid_header_is_not_also_reported_as_a_duplicate(self):
        # Two empty values are two TS-014s. Calling them a collision as well
        # would double-charge the same mistake.
        ids = _check(self._two("", ""))
        self.assertNotIn("TS-015", ids)
        self.assertEqual(ids.count("TS-014"), 2)


class HeaderTypes(unittest.TestCase):
    def _typed(self, type_value):
        return mk_tool("t", schema=_param(
            {"type": type_value, "x-mcp-header": "X-Trace"}))

    def test_string_integer_and_boolean_are_quiet(self):
        for type_value in ("string", "integer", "boolean"):
            with self.subTest(type=type_value):
                self.assertNotIn("TS-016", _check(self._typed(type_value)))

    def test_number_fires(self):
        # Excluded outright: a float has no agreed spelling in a header.
        self.assertIn("TS-016", _check(self._typed("number")))

    def test_object_fires(self):
        self.assertIn("TS-016", _check(self._typed("object")))

    def test_array_fires(self):
        self.assertIn("TS-016", _check(self._typed("array")))

    def test_a_nullable_string_is_judged_on_its_real_type(self):
        self.assertNotIn("TS-016", _check(self._typed(["string", "null"])))

    def test_an_untyped_parameter_is_left_alone(self):
        # The schema never said what it is, so there is nothing to be wrong
        # about and a finding here would not be actionable.
        t = mk_tool("t", schema=_param({"x-mcp-header": "X-Trace"}))
        self.assertNotIn("TS-016", _check(t))

    def test_a_bad_type_is_reported_even_when_the_name_is_also_bad(self):
        t = mk_tool("t", schema=_param({"type": "object", "x-mcp-header": "X Trace"}))
        ids = _check(t)
        self.assertIn("TS-014", ids)
        self.assertIn("TS-016", ids)


class Icons(unittest.TestCase):
    def test_no_icons_is_quiet(self):
        self.assertNotIn("TS-017", _check(mk_tool("t")))

    def test_https_is_quiet(self):
        t = mk_tool("t", icons=[{"src": "https://example.com/icon.png"}])
        self.assertNotIn("TS-017", _check(t))

    def test_data_uri_is_quiet(self):
        t = mk_tool("t", icons=[{"src": "data:image/png;base64,iVBORw0KGgo="}])
        self.assertNotIn("TS-017", _check(t))

    def test_scheme_matching_ignores_case(self):
        t = mk_tool("t", icons=[{"src": "HTTPS://example.com/icon.png"}])
        self.assertNotIn("TS-017", _check(t))

    def test_javascript_fires(self):
        t = mk_tool("t", icons=[{"src": "javascript:alert(1)"}])
        self.assertIn("TS-017", _check(t))

    def test_plain_http_fires(self):
        t = mk_tool("t", icons=[{"src": "http://example.com/icon.png"}])
        self.assertIn("TS-017", _check(t))

    def test_file_and_ftp_and_ws_fire(self):
        for src in ("file:///etc/passwd", "ftp://example.com/i.png",
                    "ws://example.com/i"):
            with self.subTest(src=src):
                self.assertIn("TS-017", _check(mk_tool("t", icons=[{"src": src}])))

    def test_a_schemeless_src_fires(self):
        t = mk_tool("t", icons=[{"src": "/assets/icon.png"}])
        self.assertIn("TS-017", _check(t))

    def test_a_malformed_icon_entry_fires_instead_of_crashing(self):
        t = mk_tool("t", icons=["https://example.com/icon.png", {}, {"src": 7}])
        self.assertEqual(_check(t).count("TS-017"), 3)

    def test_the_finding_points_at_the_icon_that_broke(self):
        t = mk_tool("t", icons=[{"src": "https://ok.example/i.png"},
                                {"src": "javascript:alert(1)"}])
        finding = next(f for f in conformance.check(t, [])
                       if f.rule_id == "TS-017")
        self.assertEqual(finding.param, "icons[1]")


class NoFalsePositivesOnOrdinaryTools(unittest.TestCase):
    def test_a_plain_tool_trips_none_of_these_rules(self):
        t = mk_tool(
            "get_weather",
            description="Returns the forecast for a place, error if unknown.",
            schema={"type": "object", "required": ["place"], "properties": {
                "place": {"type": "string", "description": "City name."}}})
        self.assertEqual(_check(t), [])


if __name__ == "__main__":
    unittest.main()
