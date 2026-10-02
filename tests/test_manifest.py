"""Manifest parsing and loading: shape validation, size caps, and the
malformed-input paths that must raise ManifestError instead of crashing."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from toolsmell import cli
from toolsmell.lint import lint_path
from toolsmell.manifest import MAX_JSON_DEPTH, ManifestError, load_manifest, parse_tools


class ParseTools(unittest.TestCase):
    def test_valid_manifest(self):
        tools = parse_tools({"tools": [{"name": "a", "description": "d",
                                         "inputSchema": {"type": "object"}}]})
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "a")
        self.assertEqual(tools[0].index, 0)

    def test_missing_description_defaults_to_empty(self):
        tools = parse_tools({"tools": [{"name": "a"}]})
        self.assertEqual(tools[0].description, "")

    def test_missing_schema_defaults_to_empty_dict(self):
        tools = parse_tools({"tools": [{"name": "a", "description": "d"}]})
        self.assertEqual(tools[0].input_schema, {})

    def test_top_level_not_object_raises(self):
        with self.assertRaises(ManifestError):
            parse_tools([1, 2, 3])

    def test_missing_tools_key_raises(self):
        with self.assertRaises(ManifestError):
            parse_tools({"not_tools": []})

    def test_tools_not_a_list_raises(self):
        with self.assertRaises(ManifestError):
            parse_tools({"tools": "nope"})

    def test_tool_entry_not_object_raises(self):
        with self.assertRaises(ManifestError):
            parse_tools({"tools": ["nope"]})

    def test_tool_missing_name_raises(self):
        with self.assertRaises(ManifestError):
            parse_tools({"tools": [{"description": "d"}]})

    def test_tool_blank_name_raises(self):
        with self.assertRaises(ManifestError):
            parse_tools({"tools": [{"name": "   "}]})

    def test_non_string_description_becomes_empty(self):
        tools = parse_tools({"tools": [{"name": "a", "description": 123}]})
        self.assertEqual(tools[0].description, "")

    def test_index_follows_array_order(self):
        tools = parse_tools({"tools": [{"name": "a"}, {"name": "b"}, {"name": "c"}]})
        self.assertEqual([t.index for t in tools], [0, 1, 2])


class ToolParams(unittest.TestCase):
    def test_params_from_properties(self):
        tools = parse_tools({"tools": [{
            "name": "a",
            "inputSchema": {"type": "object", "properties": {
                "x": {"type": "string"}, "y": {"type": "number"}}},
        }]})
        names = {p.name for p in tools[0].params}
        self.assertEqual(names, {"x", "y"})

    def test_required_flag_set_from_required_list(self):
        tools = parse_tools({"tools": [{
            "name": "a",
            "inputSchema": {
                "type": "object",
                "properties": {"x": {"type": "string"}, "y": {"type": "string"}},
                "required": ["x"],
            },
        }]})
        by_name = {p.name: p for p in tools[0].params}
        self.assertTrue(by_name["x"].required)
        self.assertFalse(by_name["y"].required)

    def test_no_properties_gives_empty_params(self):
        tools = parse_tools({"tools": [{"name": "a", "inputSchema": {"type": "object"}}]})
        self.assertEqual(tools[0].params, [])

    def test_non_dict_property_schema_normalizes_to_empty(self):
        tools = parse_tools({"tools": [{
            "name": "a",
            "inputSchema": {"type": "object", "properties": {"x": "not-a-schema"}},
        }]})
        self.assertEqual(tools[0].params[0].schema, {})

    def test_has_required_field_reflects_key_presence(self):
        with_key = parse_tools({"tools": [{
            "name": "a", "inputSchema": {"type": "object", "properties": {}, "required": []}}]})
        without_key = parse_tools({"tools": [{
            "name": "a", "inputSchema": {"type": "object", "properties": {}}}]})
        self.assertTrue(with_key[0].has_required_field)
        self.assertFalse(without_key[0].has_required_field)


def _args(required=None):
    schema = {"type": "object", "properties": {
        "origin": {"type": "string"}, "dest": {"type": "string"}}}
    if required is not None:
        schema["required"] = required
    return schema


class RefOnTheSchemaRoot(unittest.TestCase):
    """A schema that is only a pointer into $defs, or composed from
    pointers, has to show the same params as the flat one. Seeing none
    gives the tool a perfect score it did nothing to earn."""

    def _tool(self, schema):
        return parse_tools({"tools": [{"name": "t", "inputSchema": schema}]})[0]

    def test_root_ref_into_definitions(self):
        tool = self._tool({"$ref": "#/definitions/Args", "definitions": {"Args": _args()}})
        self.assertEqual({p.name for p in tool.params}, {"origin", "dest"})
        self.assertFalse(tool.has_required_field)

    def test_ref_inside_allof_branch(self):
        tool = self._tool({"type": "object", "allOf": [{"$ref": "#/$defs/Args"}],
                           "$defs": {"Args": _args()}})
        self.assertEqual({p.name for p in tool.params}, {"origin", "dest"})

    def test_required_list_arrives_through_a_ref(self):
        tool = self._tool({"type": "object", "anyOf": [{"$ref": "#/$defs/Args"}],
                           "$defs": {"Args": _args(required=["origin"])}})
        self.assertTrue(tool.has_required_field)
        by_name = {p.name: p for p in tool.params}
        self.assertTrue(by_name["origin"].required)
        self.assertFalse(by_name["dest"].required)

    def test_param_refs_still_resolve_against_the_original_root(self):
        tool = self._tool({"$ref": "#/$defs/Args", "$defs": {
            "Args": {"type": "object", "properties": {"where": {"$ref": "#/$defs/Where"}}},
            "Where": {"type": "string", "description": "City name."}}})
        self.assertEqual(tool.params[0].description, "City name.")

    def test_ref_cycle_on_the_root_terminates(self):
        tool = self._tool({"$ref": "#/$defs/A", "$defs": {"A": {"$ref": "#/$defs/A"}}})
        self.assertEqual(tool.params, [])

    def test_ref_wrapped_tool_scores_like_the_flat_one(self):
        desc = "Books a flight and returns a booking id; raises an error on invalid input."
        flat = lint_path(self._file({"name": "t", "description": desc, "inputSchema": _args()}))
        wrapped = lint_path(self._file({"name": "t", "description": desc, "inputSchema": {
            "$ref": "#/definitions/Args", "definitions": {"Args": _args()}}}))
        self.assertGreater(flat.score, 0)
        self.assertEqual(wrapped.score, flat.score)
        self.assertEqual(sorted(f.rule_id for f in wrapped.findings),
                         sorted(f.rule_id for f in flat.findings))

    def _file(self, tool) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "tools.json"
        tmp.write_text(json.dumps({"tools": [tool]}), encoding="utf-8")
        return tmp


class LoadManifestFromDisk(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "manifest.json"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def test_loads_a_real_file(self):
        p = self._write(json.dumps({"tools": [{"name": "a", "description": "d"}]}))
        tools = load_manifest(p)
        self.assertEqual(len(tools), 1)

    def test_missing_file_raises(self):
        with self.assertRaises(ManifestError):
            load_manifest("/no/such/path/manifest.json")

    def test_malformed_json_raises(self):
        p = self._write("{not valid json")
        with self.assertRaises(ManifestError):
            load_manifest(p)

    def test_oversized_file_raises(self):
        import toolsmell.manifest as m
        p = self._write(json.dumps({"tools": []}))
        original = m.MAX_FILE_BYTES
        m.MAX_FILE_BYTES = 1
        try:
            with self.assertRaises(ManifestError):
                load_manifest(p)
        finally:
            m.MAX_FILE_BYTES = original

    def test_non_utf8_file_raises(self):
        tmp = Path(tempfile.mkdtemp()) / "bad.json"
        tmp.write_bytes(b"\x80\x81\x82\x83")
        with self.assertRaises(ManifestError):
            load_manifest(tmp)


class FileEncodings(unittest.TestCase):
    """A manifest saved by a Windows editor is still a manifest. A BOM must
    load, and a wide encoding must say what is actually wrong."""

    def _write_bytes(self, raw: bytes) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "manifest.json"
        tmp.write_bytes(raw)
        return tmp

    def test_utf8_bom_file_loads(self):
        body = json.dumps({"tools": [{"name": "a", "description": "d"}]})
        p = self._write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        tools = load_manifest(p)
        self.assertEqual(tools[0].name, "a")

    def test_utf16le_file_names_the_encoding(self):
        body = json.dumps({"tools": [{"name": "a"}]})
        p = self._write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(p)
        message = str(ctx.exception)
        self.assertIn("UTF-16LE", message)
        self.assertNotIn("not valid JSON", message)

    def test_utf16be_file_names_the_encoding(self):
        body = json.dumps({"tools": [{"name": "a"}]})
        p = self._write_bytes(b"\xfe\xff" + body.encode("utf-16-be"))
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(p)
        self.assertIn("UTF-16BE", str(ctx.exception))

    def test_utf32le_is_not_mistaken_for_utf16(self):
        body = json.dumps({"tools": [{"name": "a"}]})
        p = self._write_bytes(b"\xff\xfe\x00\x00" + body.encode("utf-32-le"))
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(p)
        self.assertIn("UTF-32LE", str(ctx.exception))


def _nest(depth: int) -> str:
    return "[" * depth + "]" * depth


class HostileJson(unittest.TestCase):
    """A manifest built to crash the parser has to come back as a usage
    error. A traceback exits 1, the same code as a tripped smell gate."""

    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "tools.json"
        tmp.write_text(text, encoding="utf-8")
        return tmp

    def _cli(self, path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([str(path)])
        return code, out.getvalue(), err.getvalue()

    def test_nesting_past_the_parser_stack_is_a_manifest_error(self):
        p = self._write('{"tools": ' + _nest(200_000) + "}")
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(p)
        self.assertIn("levels deep", str(ctx.exception))

    def test_nesting_the_parser_accepts_is_still_capped(self):
        # 3.12+ parses this, then overflows the stack in the TS-014 repr().
        tool = ('{"name": "t", "inputSchema": {"properties": {"a": '
                '{"type": "string", "x-mcp-header": ' + _nest(MAX_JSON_DEPTH) + "}}}}")
        p = self._write('{"tools": [' + tool + "]}")
        with self.assertRaises(ManifestError):
            load_manifest(p)

    def test_nesting_under_the_cap_loads(self):
        p = self._write('{"tools": [{"name": "t", "x": ' + _nest(MAX_JSON_DEPTH - 4) + "}]}")
        self.assertEqual(load_manifest(p)[0].name, "t")

    def test_integer_over_the_digit_limit_is_a_manifest_error(self):
        p = self._write('{"tools": [{"name": "t", "inputSchema": {"properties": '
                        '{"a": {"maxLength": ' + "9" * 5000 + "}}}}]}")
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(p)
        self.assertIn("4300", str(ctx.exception))

    def test_cli_exits_two_with_one_line_and_no_traceback(self):
        for text in ('{"tools": ' + _nest(200_000) + "}",
                     '{"tools": [{"name": "t", "x": ' + "9" * 5000 + "}]}"):
            with self.subTest(text=text[:20]):
                code, out, err = self._cli(self._write(text))
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertEqual(len(err.splitlines()), 1)
                self.assertTrue(err.startswith("toolsmell: "))

    def test_non_string_required_entries_are_ignored(self):
        props = {"a": {"type": "string"}}
        tools = parse_tools({"tools": [
            {"name": "t1", "inputSchema": {"properties": props, "required": [{"x": 1}, "a"]}},
            {"name": "t2", "inputSchema": {"properties": props, "required": [["a"]]}},
            {"name": "t3", "inputSchema": {"allOf": [{"properties": props, "required": [{}]}]}},
        ]})
        self.assertTrue(tools[0].params[0].required)
        for tool in tools[1:]:
            with self.subTest(tool=tool.name):
                self.assertFalse(tool.params[0].required)
                self.assertTrue(tool.has_required_field)

    def test_non_string_required_entries_lint_without_ts007(self):
        desc = "Fetches a record and returns it, or an error if missing."
        p = self._write(json.dumps({"tools": [{"name": "t1", "description": desc, "inputSchema": {
            "type": "object", "properties": {"a": {"type": "string"}}, "required": [{}]}}]}))
        result = lint_path(p)
        self.assertNotIn("TS-007", [f.rule_id for f in result.findings])


if __name__ == "__main__":
    unittest.main()
