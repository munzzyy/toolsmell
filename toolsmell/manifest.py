"""Load and validate an MCP tools/list-shaped manifest.

Accepts a JSON file with a top-level "tools" array, each entry shaped like
{"name": ..., "description": ..., "inputSchema": {...}} -- the shape an MCP
server's tools/list response returns. Nothing here is ever executed or
evaluated; malformed input raises ManifestError with a plain message instead
of a traceback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# A tools/list response describing a real server has no business being
# bigger than this. Reject oversized input up front instead of reading an
# arbitrarily large file into memory.
MAX_FILE_BYTES = 5_000_000


class ManifestError(Exception):
    """Raised when the input cannot be read as a tools manifest."""


@dataclass(frozen=True)
class Param:
    name: str
    schema: dict
    required: bool

    @property
    def description(self) -> str:
        d = self.schema.get("description")
        return d if isinstance(d, str) else ""

    @property
    def type(self) -> str:
        t = self.schema.get("type")
        return t if isinstance(t, str) else ""

    @property
    def has_enum(self) -> bool:
        return isinstance(self.schema.get("enum"), list)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    index: int  # position in the tools array; used for stable identity

    @property
    def params(self) -> list:
        props = self.input_schema.get("properties")
        if not isinstance(props, dict):
            return []
        required = self.input_schema.get("required")
        required_names = set(required) if isinstance(required, list) else set()
        out = []
        for name, schema in props.items():
            if not isinstance(name, str):
                continue
            out.append(Param(
                name=name,
                schema=schema if isinstance(schema, dict) else {},
                required=name in required_names,
            ))
        return out

    @property
    def has_required_field(self) -> bool:
        return "required" in self.input_schema


def load_manifest(path) -> list:
    """Read a tools manifest JSON file and return a list[Tool]."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError as e:
        raise ManifestError(f"cannot read {p}: {e}")
    if size > MAX_FILE_BYTES:
        raise ManifestError(
            f"{p} is {size} bytes, over the {MAX_FILE_BYTES}-byte limit for a "
            "tools manifest")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(f"cannot read {p}: {e}")
    except UnicodeDecodeError as e:
        raise ManifestError(f"{p} is not valid UTF-8: {e}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ManifestError(f"{p} is not valid JSON: {e}")
    return parse_tools(data, source=str(p))


def parse_tools(data, source: str = "<data>") -> list:
    """Validate already-parsed JSON data into a list[Tool]. Never raises on
    malformed shape -- it raises ManifestError with a message instead."""
    if not isinstance(data, dict):
        raise ManifestError(f"{source}: expected a JSON object with a 'tools' array")
    tools = data.get("tools")
    if not isinstance(tools, list):
        raise ManifestError(f"{source}: 'tools' is missing or is not an array")
    out = []
    for i, entry in enumerate(tools):
        if not isinstance(entry, dict):
            raise ManifestError(f"{source}: tools[{i}] is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ManifestError(f"{source}: tools[{i}] has no valid 'name'")
        description = entry.get("description")
        description = description if isinstance(description, str) else ""
        schema = entry.get("inputSchema")
        schema = schema if isinstance(schema, dict) else {}
        out.append(Tool(name=name, description=description, input_schema=schema, index=i))
    return out
