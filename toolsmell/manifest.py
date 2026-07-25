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


def _lookup_ref(ref: str, root: dict):
    """Resolve a local '#/$defs/<name>' or '#/definitions/<name>' pointer
    against root. Only these single-level shapes are handled -- external or
    deeper pointers return None and the ref is left as-is."""
    if ref.startswith("#/$defs/"):
        section, key = "$defs", ref[len("#/$defs/"):]
    elif ref.startswith("#/definitions/"):
        section, key = "definitions", ref[len("#/definitions/"):]
    else:
        return None
    defs = root.get(section)
    if not isinstance(defs, dict):
        return None
    return defs.get(key)


def _resolve_ref(schema: dict, root: dict) -> dict:
    """Inline a local $ref so a param defined by reference is read the same
    as an inline one. Sibling keys on the referencing schema win over the
    referenced one (JSON Schema 2020-12). Follows a chain of refs with a
    cycle guard; anything unresolvable is returned untouched rather than
    crashing."""
    seen = set()
    while isinstance(schema.get("$ref"), str) and schema["$ref"] not in seen:
        ref = schema["$ref"]
        seen.add(ref)
        target = _lookup_ref(ref, root)
        if not isinstance(target, dict):
            break
        siblings = {k: v for k, v in schema.items() if k != "$ref"}
        schema = {**target, **siblings}
    return schema


def _collect_schema(schema: dict):
    """Gather (properties, required_names, has_required_list) from an object
    schema, merging one level of allOf/anyOf/oneOf composition into the top
    level. A tool that splits its params across composed subschemas -- the
    shape pydantic/FastMCP emit for nested and combined models -- is then
    linted the same as one that lists them flat, instead of the rules
    failing open on the composed form. Top-level properties win over branch
    ones; branch 'required' lists are merged in for reporting."""
    props = {}
    required = set()
    has_required_list = False
    top_props = schema.get("properties")
    if isinstance(top_props, dict):
        props.update(top_props)
    top_required = schema.get("required")
    if isinstance(top_required, list):
        required.update(top_required)
        has_required_list = True
    for key in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            b_props = branch.get("properties")
            if isinstance(b_props, dict):
                for name, sub in b_props.items():
                    props.setdefault(name, sub)
            b_required = branch.get("required")
            if isinstance(b_required, list):
                required.update(b_required)
                has_required_list = True
    return props, required, has_required_list


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
    def type_set(self) -> set:
        """Every type this param could take -- the plain 'type' string, each
        entry of a list-form 'type' like ["string","null"], and the type of
        each anyOf/oneOf branch (the Optional[str] shape FastMCP emits). Lets
        a rule see the underlying type through a nullable wrapper."""
        out = set()

        def add(t):
            if isinstance(t, str):
                out.add(t)
            elif isinstance(t, list):
                out.update(x for x in t if isinstance(x, str))

        add(self.schema.get("type"))
        for key in ("anyOf", "oneOf"):
            branches = self.schema.get(key)
            if isinstance(branches, list):
                for branch in branches:
                    if isinstance(branch, dict):
                        add(branch.get("type"))
        return out

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
        props, required_names, _ = _collect_schema(self.input_schema)
        out = []
        for name, schema in props.items():
            if not isinstance(name, str):
                continue
            schema = schema if isinstance(schema, dict) else {}
            schema = _resolve_ref(schema, self.input_schema)
            out.append(Param(
                name=name,
                schema=schema,
                required=name in required_names,
            ))
        return out

    @property
    def has_required_field(self) -> bool:
        # A usable 'required' must be an array (per the schema). A present
        # but non-list value ("required": true) is malformed, so TS-007 must
        # still fire; a required list inside a composed branch counts too.
        return _collect_schema(self.input_schema)[2]


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
