"""Central registry of every smell rule: id, severity, title, explanation, fix.

Rule modules build findings through `build()` instead of repeating these
strings inline, so --list-rules, docs/rules.md, and every finding stay in
sync with one source of truth. A test asserts docs/rules.md documents
exactly this set of ids and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

from .finding import Finding, Severity


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    title: str
    explanation: str
    fix: str


_RULES = [
    Rule(
        "TS-001", Severity.MEDIUM,
        "Missing or empty description",
        "The tool has no description, or the description is blank. An agent "
        "choosing between tools has nothing but the name to go on.",
        "Write a description that says what the tool does, what it returns, "
        "and when to use it instead of a similarly named tool.",
    ),
    Rule(
        "TS-002", Severity.LOW,
        "Description too short to disambiguate",
        "The description is present but too short to tell the tool apart "
        "from others with a similar name or purpose.",
        "Expand the description to at least a full sentence: what it does, "
        "on what input, with what result.",
    ),
    Rule(
        "TS-003", Severity.LOW,
        "Description doesn't say what the tool returns",
        "The description explains what the tool does but never says what "
        "comes back, so an agent can't predict how to use the result.",
        "Add a sentence describing the return value: its shape, type, or "
        "what it contains.",
    ),
    Rule(
        "TS-004", Severity.MEDIUM,
        "Vague action verb with no specifics",
        "The description is a single vague verb ('process', 'handle', "
        "'manage', 'do') with nothing about what it acts on.",
        "Replace the vague verb with a specific one and name the input and "
        "output it acts on.",
    ),
    Rule(
        "TS-005", Severity.MEDIUM,
        "Parameter undocumented in the description",
        "The schema defines a parameter that the description never "
        "mentions, so an agent has to guess its purpose from the name "
        "alone.",
        "Mention every parameter in the description, or at least the ones "
        "whose purpose isn't obvious from the name.",
    ),
    Rule(
        "TS-006", Severity.LOW,
        "Parameter has no description field",
        "A parameter in the schema has no 'description', so its purpose "
        "rests entirely on its name and type.",
        "Add a 'description' to the parameter's schema entry.",
    ),
    Rule(
        "TS-007", Severity.MEDIUM,
        "Required parameters not distinguishable",
        "The schema defines parameters but has no 'required' list, so an "
        "agent cannot tell which parameters are mandatory.",
        "Add a 'required' array listing the mandatory parameter names (an "
        "empty array is fine if every parameter is optional).",
    ),
    Rule(
        "TS-008", Severity.INFO,
        "No error guidance",
        "The description never says what happens on bad input or failure, "
        "so an agent has no way to anticipate or recover from an error.",
        "Add a sentence about failure behavior: what happens on invalid "
        "input, and what the error looks like.",
    ),
    Rule(
        "TS-009", Severity.MEDIUM,
        "Name collides with another tool",
        "This tool's name is a near-duplicate of another tool's name, which "
        "makes it easy for an agent to call the wrong one.",
        "Rename one of the two tools so the names are clearly distinct, or "
        "merge them if they do the same thing.",
    ),
    Rule(
        "TS-010", Severity.INFO,
        "Missing example for a multi-parameter tool",
        "The tool takes three or more parameters but the description gives "
        "no example call, so an agent has to infer the right argument "
        "shape.",
        "Add a short example showing typical argument values.",
    ),
    Rule(
        "TS-011", Severity.MEDIUM,
        "Overloaded tool description",
        "The description lists several unrelated actions, which usually "
        "means the tool does too much for an agent to reliably pick the "
        "right mode.",
        "Split the tool into one tool per action, or narrow the "
        "description to the single thing it actually does.",
    ),
    Rule(
        "TS-012", Severity.LOW,
        "Enum-worthy free text",
        "A string parameter's description spells out the allowed values in "
        "prose instead of the schema constraining them.",
        "Add an 'enum' listing the allowed values to the parameter's "
        "schema instead of describing them in prose.",
    ),
    Rule(
        "TS-013", Severity.MEDIUM,
        "Tool name breaks the MCP name rules",
        "The name is longer than 128 characters or uses characters outside "
        "A-Z a-z 0-9 _ . - , which the spec does not allow. A client that "
        "enforces the rule drops the tool, so it never reaches the agent.",
        "Rename the tool to at most 128 characters of letters, digits, "
        "underscore, dot, or hyphen.",
    ),
    Rule(
        "TS-014", Severity.MEDIUM,
        "x-mcp-header is not a usable header name",
        "A parameter's 'x-mcp-header' is empty, is not a string, or contains "
        "characters an HTTP field name cannot hold. A line break is the "
        "worst case: it splits the request headers instead of naming one.",
        "Set 'x-mcp-header' to a single HTTP token: letters, digits, and "
        "!#$%&'*+-.^_`|~ with no spaces or line breaks.",
    ),
    Rule(
        "TS-015", Severity.MEDIUM,
        "Two parameters claim the same header",
        "Two parameters in the same inputSchema map to header names that "
        "differ only in case. HTTP field names are case-insensitive, so "
        "they are one header and one of the values is lost.",
        "Give each parameter its own header name, compared without regard "
        "to case.",
    ),
    Rule(
        "TS-016", Severity.MEDIUM,
        "x-mcp-header on a type that cannot be sent as one",
        "A parameter carrying 'x-mcp-header' is typed object, array, or "
        "number. Only string, integer and boolean have an agreed spelling "
        "in a header value.",
        "Send the parameter in the request body instead, or narrow it to a "
        "string, integer, or boolean.",
    ),
    Rule(
        "TS-017", Severity.MEDIUM,
        "Icon src uses a scheme consumers reject",
        "A tool icon's 'src' is not an https: or data: URI. Every other "
        "scheme, javascript: and file: included, is one a consumer is "
        "required to refuse, so the icon simply never loads.",
        "Serve the icon over https:, or inline it as a data: URI.",
    ),
]

BY_ID = {r.id: r for r in _RULES}


def all_rules() -> list:
    return list(_RULES)


def build(rule_id: str, *, tool: str = "", param: str = "", detail: str = "",
          fix: str = "") -> Finding:
    """Construct a Finding from a catalog entry, overriding the generic
    explanation/fix with an instance-specific one when the caller has it."""
    r = BY_ID[rule_id]
    return Finding(
        rule_id=r.id,
        severity=r.severity,
        tool=tool,
        param=param,
        title=r.title,
        detail=detail or r.explanation,
        fix=fix or r.fix,
    )
