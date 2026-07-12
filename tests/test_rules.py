"""Per-rule unit tests. Each rule module is exercised directly so a test
failure points straight at the rule, not at the whole pipeline."""

from __future__ import annotations

import unittest

from toolsmell.rules import description, examples, naming, schema
from tests._helpers import mk_tool


def _ids(findings):
    return [f.rule_id for f in findings]


class MissingDescription(unittest.TestCase):
    def test_missing_key_fires(self):
        t = mk_tool("t")
        self.assertIn("TS-001", _ids(description.check(t, [t])))

    def test_empty_string_fires(self):
        t = mk_tool("t", description="")
        self.assertIn("TS-001", _ids(description.check(t, [t])))

    def test_whitespace_only_fires(self):
        t = mk_tool("t", description="   \n  ")
        self.assertIn("TS-001", _ids(description.check(t, [t])))

    def test_present_description_does_not_fire(self):
        t = mk_tool("t", description="Fetches a thing and returns it as JSON.")
        self.assertNotIn("TS-001", _ids(description.check(t, [t])))

    def test_empty_description_skips_other_description_rules(self):
        # No point piling on TS-002/003/004/008 when there is no text at all.
        t = mk_tool("t")
        ids = _ids(description.check(t, [t]))
        self.assertEqual(ids, ["TS-001"])


class TooShort(unittest.TestCase):
    def test_short_description_fires(self):
        t = mk_tool("t", description="Gets stuff.")
        self.assertIn("TS-002", _ids(description.check(t, [t])))

    def test_long_description_does_not_fire(self):
        t = mk_tool("t", description="Fetches the requested record and returns its full contents as JSON.")
        self.assertNotIn("TS-002", _ids(description.check(t, [t])))


class NoReturnMention(unittest.TestCase):
    def test_no_return_word_fires(self):
        t = mk_tool("t", description="Fetches the requested record from the primary datastore for lookups.")
        self.assertIn("TS-003", _ids(description.check(t, [t])))

    def test_return_word_present_does_not_fire(self):
        t = mk_tool("t", description="Fetches the requested record and returns its full contents as JSON.")
        self.assertNotIn("TS-003", _ids(description.check(t, [t])))

    def test_output_synonym_counts(self):
        t = mk_tool("t", description="Fetches the requested record; the output is the full JSON body.")
        self.assertNotIn("TS-003", _ids(description.check(t, [t])))


class VagueVerbOnly(unittest.TestCase):
    def test_bare_process_fires(self):
        t = mk_tool("t", description="Process the data.")
        self.assertIn("TS-004", _ids(description.check(t, [t])))

    def test_bare_handle_requests_fires(self):
        t = mk_tool("t", description="Handles requests.")
        self.assertIn("TS-004", _ids(description.check(t, [t])))

    def test_vague_verb_with_specifics_does_not_fire(self):
        t = mk_tool("t", description="Processes incoming webhook payloads from Stripe and returns a receipt id.")
        self.assertNotIn("TS-004", _ids(description.check(t, [t])))

    def test_non_vague_verb_does_not_fire(self):
        t = mk_tool("t", description="Deletes the specified record and returns nothing.")
        self.assertNotIn("TS-004", _ids(description.check(t, [t])))


class UndocumentedParam(unittest.TestCase):
    def test_param_not_mentioned_fires(self):
        t = mk_tool(
            "get_item", description="Fetches an item and returns its full record as JSON.",
            schema={"type": "object", "properties": {"item_id": {"type": "string"}}})
        self.assertIn("TS-005", _ids(schema.check(t, [t])))

    def test_param_mentioned_by_split_words_does_not_fire(self):
        t = mk_tool(
            "get_item",
            description="Fetches the item with the given item id and returns its full record.",
            schema={"type": "object", "properties": {"item_id": {"type": "string"}}})
        self.assertNotIn("TS-005", _ids(schema.check(t, [t])))

    def test_param_mentioned_literally_does_not_fire(self):
        t = mk_tool(
            "get_item",
            description="Fetches the item; pass item_id to select which one and get its record back.",
            schema={"type": "object", "properties": {"item_id": {"type": "string"}}})
        self.assertNotIn("TS-005", _ids(schema.check(t, [t])))

    def test_no_description_does_not_pile_on(self):
        t = mk_tool("get_item", schema={"type": "object",
                                         "properties": {"item_id": {"type": "string"}}})
        self.assertNotIn("TS-005", _ids(schema.check(t, [t])))


class ParamNoDescription(unittest.TestCase):
    def test_missing_param_description_fires(self):
        t = mk_tool("t", description="x", schema={"type": "object",
                                                    "properties": {"x": {"type": "string"}}})
        self.assertIn("TS-006", _ids(schema.check(t, [t])))

    def test_present_param_description_does_not_fire(self):
        t = mk_tool("t", description="x", schema={
            "type": "object",
            "properties": {"x": {"type": "string", "description": "The x value."}}})
        self.assertNotIn("TS-006", _ids(schema.check(t, [t])))


class RequiredMissing(unittest.TestCase):
    def test_no_required_key_with_properties_fires(self):
        t = mk_tool("t", description="d", schema={"type": "object",
                                                    "properties": {"x": {"type": "string"}}})
        self.assertIn("TS-007", _ids(schema.check(t, [t])))

    def test_empty_required_list_does_not_fire(self):
        t = mk_tool("t", description="d", schema={
            "type": "object", "properties": {"x": {"type": "string"}}, "required": []})
        self.assertNotIn("TS-007", _ids(schema.check(t, [t])))

    def test_no_properties_does_not_fire(self):
        t = mk_tool("t", description="d", schema={"type": "object", "properties": {}})
        self.assertNotIn("TS-007", _ids(schema.check(t, [t])))


class NoErrorGuidance(unittest.TestCase):
    def test_no_error_words_fires(self):
        t = mk_tool("t", description="Fetches the record and returns its full contents as JSON.")
        self.assertIn("TS-008", _ids(description.check(t, [t])))

    def test_error_word_present_does_not_fire(self):
        t = mk_tool("t", description="Fetches the record and returns it, raising an error if missing.")
        self.assertNotIn("TS-008", _ids(description.check(t, [t])))


class NameCollision(unittest.TestCase):
    def test_exact_duplicate_name_fires(self):
        a = mk_tool("dup_tool", description="d")
        b = mk_tool("dup_tool", description="d", index=1)
        self.assertIn("TS-009", _ids(naming.check(a, [a, b])))

    def test_near_prefix_fires(self):
        a = mk_tool("search_items", description="d")
        b = mk_tool("search_items_v2", description="d", index=1)
        self.assertIn("TS-009", _ids(naming.check(a, [a, b])))

    def test_small_edit_distance_fires(self):
        a = mk_tool("get_invoice", description="d")
        b = mk_tool("get_invoicee", description="d", index=1)
        self.assertIn("TS-009", _ids(naming.check(a, [a, b])))

    def test_distinct_names_do_not_fire(self):
        a = mk_tool("get_weather", description="d")
        b = mk_tool("convert_currency", description="d", index=1)
        self.assertNotIn("TS-009", _ids(naming.check(a, [a, b])))

    def test_short_common_prefix_does_not_fire(self):
        a = mk_tool("get", description="d")
        b = mk_tool("get_users", description="d", index=1)
        self.assertNotIn("TS-009", _ids(naming.check(a, [a, b])))


class MissingExample(unittest.TestCase):
    def test_three_params_no_example_fires(self):
        t = mk_tool("t", description="Does a thing with three inputs and returns a result.", schema={
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": "string"}},
        })
        self.assertTrue(examples.check(t, [t]))

    def test_three_params_with_example_does_not_fire(self):
        t = mk_tool("t", description="Does a thing, for example t(a=1, b=2, c=3) returns 6.", schema={
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": "string"}},
        })
        self.assertEqual(examples.check(t, [t]), [])

    def test_two_params_does_not_fire(self):
        t = mk_tool("t", description="Does a thing with two inputs.", schema={
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        })
        self.assertEqual(examples.check(t, [t]), [])

    def test_code_fence_counts_as_example(self):
        t = mk_tool("t", description="Does a thing. ```t(a=1, b=2, c=3)```", schema={
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": "string"}},
        })
        self.assertEqual(examples.check(t, [t]), [])


class OverloadedTool(unittest.TestCase):
    def test_many_distinct_verbs_fires(self):
        t = mk_tool("t", description="Creates, updates, deletes, and lists records in the store.")
        self.assertIn("TS-011", _ids(description.check(t, [t])))

    def test_two_verbs_with_two_joiners_fires(self):
        t = mk_tool("t", description="Fetches a record and sends a notification, or removes it entirely.")
        self.assertIn("TS-011", _ids(description.check(t, [t])))

    def test_single_verb_with_and_does_not_fire(self):
        t = mk_tool("t", description="Fetches a user's name and email address and returns them as JSON.")
        self.assertNotIn("TS-011", _ids(description.check(t, [t])))


class EnumWorthyFreeText(unittest.TestCase):
    def test_three_quoted_tokens_fires(self):
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"order": {
                "type": "string",
                "description": "Sort order: 'asc', 'desc', or 'relevance'.",
            }}})
        self.assertIn("TS-012", _ids(schema.check(t, [t])))

    def test_phrase_with_one_quoted_token_fires(self):
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"mode": {
                "type": "string",
                "description": "Must be one of 'fast' or a slower fallback.",
            }}})
        self.assertIn("TS-012", _ids(schema.check(t, [t])))

    def test_enum_defined_does_not_fire(self):
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"order": {
                "type": "string",
                "description": "Sort order: 'asc', 'desc', or 'relevance'.",
                "enum": ["asc", "desc", "relevance"],
            }}})
        self.assertNotIn("TS-012", _ids(schema.check(t, [t])))

    def test_non_string_type_does_not_fire(self):
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"count": {
                "type": "integer",
                "description": "One of '1', '2', or '3', loosely.",
            }}})
        self.assertNotIn("TS-012", _ids(schema.check(t, [t])))

    def test_plain_prose_does_not_fire(self):
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"note": {
                "type": "string",
                "description": "Freeform note attached to the record.",
            }}})
        self.assertNotIn("TS-012", _ids(schema.check(t, [t])))


if __name__ == "__main__":
    unittest.main()
