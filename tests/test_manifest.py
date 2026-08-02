"""Manifest parsing and loading: shape validation, size caps, and the
malformed-input paths that must raise ManifestError instead of crashing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from toolsmell.manifest import ManifestError, load_manifest, parse_tools


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


if __name__ == "__main__":
    unittest.main()
