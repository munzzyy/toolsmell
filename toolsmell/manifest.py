"""Load and validate an MCP tools/list-shaped manifest.

Accepts three shapes of JSON file, each holding tool entries like
{"name": ..., "description": ..., "inputSchema": {...}}:

- the tools/list result object, {"tools": [...]}
- the whole JSON-RPC response saved as-is, {"jsonrpc": "2.0", "id": 1,
  "result": {"tools": [...]}}
- a bare array of tools pasted into a file, [...]

Nothing here is ever executed or evaluated; malformed input raises
ManifestError with a plain message instead of a traceback.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .report import _clean

# A tools/list response describing a real server has no business being
# bigger than this. Reject oversized input up front instead of reading an
# arbitrarily large file into memory.
MAX_FILE_BYTES = 5_000_000

# Deep enough for any real schema, shallow enough for 3.9 to parse and repr().
MAX_JSON_DEPTH = 512


class ManifestError(Exception):
    """Raised when the input cannot be read as a tools manifest."""


def _deeper_than(data, limit: int) -> bool:
    stack = [(data, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        if depth > limit:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


# The same ceiling int() applies on current interpreters; older 3.9 builds
# on some CI runners have none, so the check is ours.
MAX_INT_DIGITS = 4300


def _bounded_int(literal: str) -> int:
    if len(literal.lstrip("-+")) > MAX_INT_DIGITS:
        raise ValueError(f"integer literal has more than {MAX_INT_DIGITS} digits")
    return int(literal)


def parse_json(text: str):
    """json.loads for untrusted text: any parse failure is a ValueError whose
    message follows the source name ("tools.json is not valid JSON")."""
    try:
        data = json.loads(text, parse_int=_bounded_int)
    except json.JSONDecodeError as e:
        raise ValueError(f"is not valid JSON: {e}") from None
    except RecursionError:
        raise ValueError(f"is nested more than {MAX_JSON_DEPTH} levels deep") from None
    except ValueError as e:
        raise ValueError(f"could not be parsed: {str(e).split(';')[0]}") from None
    if _deeper_than(data, MAX_JSON_DEPTH):
        raise ValueError(f"is nested more than {MAX_JSON_DEPTH} levels deep")
    return data


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


def _collect_schema(root: dict):
    """Gather (properties, required_names, has_required_list) from an object
    schema, merging one level of allOf/anyOf/oneOf composition into the top
    level. A tool that splits its params across composed subschemas -- the
    shape pydantic/FastMCP emit for nested and combined models -- is then
    linted the same as one that lists them flat, instead of the rules
    failing open on the composed form. Top-level properties win over branch
    ones; branch 'required' lists are merged in for reporting. A local $ref
    on the root or on a branch is followed first, or a schema that is only
    a pointer into $defs would show no params and score a perfect 0."""
    schema = _resolve_ref(root, root)
    props = {}
    required = set()
    has_required_list = False
    top_props = schema.get("properties")
    if isinstance(top_props, dict):
        props.update(top_props)
    top_required = schema.get("required")
    if isinstance(top_required, list):
        required.update(r for r in top_required if isinstance(r, str))
        has_required_list = True
    for key in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            branch = _resolve_ref(branch, root)
            b_props = branch.get("properties")
            if isinstance(b_props, dict):
                for name, sub in b_props.items():
                    props.setdefault(name, sub)
            b_required = branch.get("required")
            if isinstance(b_required, list):
                required.update(r for r in b_required if isinstance(r, str))
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
    # MCP 2026-07-28 lets a tool ship display icons. Kept as a tuple so a
    # frozen Tool stays frozen; entries are whatever the manifest had, and
    # the rules treat them as untrusted like everything else here.
    icons: tuple = ()

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


# UTF-16 and UTF-32 byte-order marks. PowerShell 5.1's `>` and Out-File
# write UTF-16LE by default, which is exactly how a Windows user ends up
# with one of these after saving a tools/list response by hand.
_WIDE_BOMS = (
    (b"\xff\xfe\x00\x00", "UTF-32LE"),
    (b"\x00\x00\xfe\xff", "UTF-32BE"),
    (b"\xff\xfe", "UTF-16LE"),
    (b"\xfe\xff", "UTF-16BE"),
)


def _reject_wide_encoding(p, raw: bytes) -> None:
    """Name the real problem when a file is UTF-16 or UTF-32.

    The NUL bytes of UTF-16 decode as valid UTF-8, so without this check the
    file reaches json.loads and comes back as "Expecting property name
    enclosed in double quotes: line 1 column 2" -- which sends the user
    hunting for a syntax error in JSON that is perfectly well formed.
    """
    for bom, name in _WIDE_BOMS:
        if raw.startswith(bom):
            raise ManifestError(
                f"{p} looks like {name}, not UTF-8. Re-save it as UTF-8 "
                "(in PowerShell: Out-File -Encoding utf8).")


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
        raw = p.read_bytes()
    except OSError as e:
        raise ManifestError(f"cannot read {p}: {e}")
    _reject_wide_encoding(p, raw)
    try:
        # utf-8-sig reads BOM-ful and BOM-less UTF-8 alike. Editors and
        # PowerShell's Set-Content write the BOM by default, and a manifest
        # that is otherwise perfectly good JSON should not be rejected for it.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ManifestError(f"{p} is not valid UTF-8: {e}")
    try:
        data = parse_json(text)
    except ValueError as e:
        raise ManifestError(f"{p} {e}")
    container = _tools_container(data, str(p))
    tools = parse_tools(container, source=str(p))
    cursor = container.get("nextCursor") if isinstance(container, dict) else None
    if isinstance(cursor, str) and cursor:
        print(f"toolsmell: {p} is one page of a tools/list response "
              f"(nextCursor is set), so only the {len(tools)} tool(s) on it "
              "get linted. Put every page's tools in one file, or use --stdio "
              "to follow the cursor.", file=sys.stderr)
    return tools


def _tools_container(data, source: str):
    """The object that should hold the 'tools' array, given either that
    object, a saved JSON-RPC response wrapped around it, or a bare array."""
    if isinstance(data, list):
        return {"tools": data}
    if not isinstance(data, dict) or "tools" in data:
        return data
    result = data.get("result")
    if isinstance(result, dict):
        return result
    error = data.get("error")
    if error is not None:
        detail = error.get("message") if isinstance(error, dict) else error
        raise ManifestError(
            f"{source}: this is a JSON-RPC error response, not a tool list: "
            f"{_clean(str(detail))}")
    return data


def parse_tools(data, source: str = "<data>") -> list:
    """Validate already-parsed JSON data into a list[Tool]. Never raises on
    malformed shape -- it raises ManifestError with a message instead."""
    data = _tools_container(data, source)
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
        icons = entry.get("icons")
        icons = tuple(icons) if isinstance(icons, list) else ()
        out.append(Tool(name=name, description=description, input_schema=schema,
                        index=i, icons=icons))
    return out
