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
