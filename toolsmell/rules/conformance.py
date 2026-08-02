"""Smells that are outright spec violations: TS-013 through TS-017.

Everything else in toolsmell is a judgment call about whether a description
reads well. These are not. MCP 2026-07-28 gives each of these rules a
MUST-level line, and a client that follows the spec drops a tool that
breaks one -- so the tool does not appear in `tools/list` at all, and the
agent never sees it. That failure is invisible from the server side, which
is exactly the kind of thing worth catching before deploy.

The rules stay medium severity like the rest. toolsmell is not a security
scanner and this file does not turn it into one; the CRLF and icon-scheme
checks land where they do because the spec forbids those shapes, and the
fact that both happen to be injection vectors is a bonus rather than the
point.
"""

from __future__ import annotations

import re

from .. import catalog

# MCP 2026-07-28: a tool name is 1 to 128 characters of [A-Za-z0-9_.-].
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")
NAME_MAX_CHARS = 128

# The JSON Schema extension that mirrors a parameter into an HTTP
# `Mcp-Param-{value}` request header.
HEADER_KEY = "x-mcp-header"

# RFC 9110 token: what an HTTP field name is allowed to contain.
HTTP_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

# The spec allows x-mcp-header only on primitives, and excludes `number`
# outright -- a float has no single obvious wire spelling in a header.
HEADER_TYPES = {"string", "integer", "boolean"}

# Icon sources a consumer is required to accept. Everything else, notably
# javascript:, file:, ftp: and ws:, MUST be rejected.
ICON_SCHEMES = {"https", "data"}
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")


def _check_name(tool) -> list:
    name = tool.name
    if len(name) > NAME_MAX_CHARS:
        return [catalog.build(
            "TS-013", tool=name,
            detail=f"tool name is {len(name)} characters, over the "
                   f"{NAME_MAX_CHARS}-character limit.")]
    bad = sorted({ch for ch in name if not NAME_PATTERN.match(ch)})
    if bad:
        return [catalog.build(
            "TS-013", tool=name,
            detail=f"tool name contains {', '.join(repr(ch) for ch in bad)}, "
                   "which is outside the allowed A-Z a-z 0-9 _ . - set.")]
    return []


def _header_value(param):
    """The raw x-mcp-header setting on a parameter, or None if it has none."""
    return param.schema.get(HEADER_KEY) if isinstance(param.schema, dict) else None


def _check_header_syntax(tool, param, value) -> list:
    if not isinstance(value, str):
        return [catalog.build(
            "TS-014", tool=tool.name, param=param.name,
            detail=f"'{param.name}' sets {HEADER_KEY} to {value!r}, which is "
                   "not a string.")]
    if not value:
        return [catalog.build(
            "TS-014", tool=tool.name, param=param.name,
            detail=f"'{param.name}' sets an empty {HEADER_KEY}.")]
    if "\r" in value or "\n" in value:
        return [catalog.build(
            "TS-014", tool=tool.name, param=param.name,
            detail=f"'{param.name}' sets {HEADER_KEY} to {value!r}, which "
                   "contains a carriage return or newline. That splits the "
                   "request headers rather than naming one.",
            fix="Remove the line break. A header name is a single token: "
                "letters, digits, and !#$%&'*+-.^_`|~")]
    if not HTTP_TOKEN.match(value):
        bad = sorted({ch for ch in value if not HTTP_TOKEN.match(ch)})
        return [catalog.build(
            "TS-014", tool=tool.name, param=param.name,
            detail=f"'{param.name}' sets {HEADER_KEY} to {value!r}, which "
                   f"contains {', '.join(repr(ch) for ch in bad)}. An HTTP "
                   "field name has to be a token.")]
    return []


def _check_header_type(tool, param) -> list:
    # A nullable parameter is still whatever it is when present, so drop
    # "null" before judging the type. Nothing left means the schema never
    # said, and guessing would only produce a finding nobody can act on.
    types = {t for t in param.type_set if t != "null"}
    if not types or types <= HEADER_TYPES:
        return []
    offending = ", ".join(sorted(types - HEADER_TYPES))
    return [catalog.build(
        "TS-016", tool=tool.name, param=param.name,
        detail=f"'{param.name}' is typed {offending} and carries "
               f"{HEADER_KEY}. Only string, integer and boolean may be sent "
               "as a header.")]


def _check_header_duplicates(tool, headers) -> list:
    """HTTP field names are case-insensitive, so two parameters mapped to
    'X-Trace' and 'x-trace' are one header with two claimants."""
    findings = []
    seen = {}
    for param_name, value in headers:
        key = value.lower()
        if key in seen:
            findings.append(catalog.build(
                "TS-015", tool=tool.name, param=param_name,
                detail=f"'{param_name}' and '{seen[key]}' both map to the "
                       f"{value!r} header. Field names are case-insensitive, "
                       "so one of the two values is lost."))
            continue
        seen[key] = param_name
    return findings


def _check_headers(tool) -> list:
    findings = []
    usable = []
    for param in tool.params:
        value = _header_value(param)
        if value is None:
            continue
        syntax = _check_header_syntax(tool, param, value)
        findings.extend(syntax)
        findings.extend(_check_header_type(tool, param))
        if not syntax:
            usable.append((param.name, value))
    findings.extend(_check_header_duplicates(tool, usable))
    return findings


def _check_icons(tool) -> list:
    findings = []
    for i, icon in enumerate(tool.icons):
        label = f"icons[{i}]"
        if not isinstance(icon, dict):
            findings.append(catalog.build(
                "TS-017", tool=tool.name, param=label,
                detail=f"{label} is not an object."))
            continue
        src = icon.get("src")
        if not isinstance(src, str) or not src:
            findings.append(catalog.build(
                "TS-017", tool=tool.name, param=label,
                detail=f"{label} has no usable 'src' string."))
            continue
        match = _SCHEME.match(src)
        if match is None:
            findings.append(catalog.build(
                "TS-017", tool=tool.name, param=label,
                detail=f"{label} src {src!r} has no URI scheme. A consumer "
                       "has no base to resolve it against."))
            continue
        scheme = match.group(1).lower()
        if scheme not in ICON_SCHEMES:
            findings.append(catalog.build(
                "TS-017", tool=tool.name, param=label,
                detail=f"{label} src uses the {scheme}: scheme. Only https: "
                       "and data: are allowed, and this one gets rejected."))
    return findings


def check(tool, all_tools) -> list:
    return _check_name(tool) + _check_headers(tool) + _check_icons(tool)
