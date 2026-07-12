# Rules reference

Every smell toolsmell checks for, what it looks for, and what to do about a
hit. Severities are info, low, or medium -- these are hygiene smells, not
security bugs, so there is no high/critical tier. A test keeps this file in
sync with `toolsmell/catalog.py`, so a rule cannot exist without being
documented here.

## TS-001

Missing or empty description. Severity medium.

The tool has no `description` key, or it is blank/whitespace. An agent
choosing between tools has nothing but the name to go on.

```json
{"name": "do_thing", "inputSchema": {"type": "object"}}
```

Fix: write a description that says what the tool does, what it returns, and
when to use it instead of a similarly named tool.

## TS-002

Description too short to disambiguate. Severity low.

The description is present but under 20 characters or 4 words -- not enough
to tell the tool apart from others with a similar name or purpose.

```json
{"description": "Gets stuff."}
```

Fix: expand it to at least a full sentence: what it does, on what input,
with what result.

## TS-003

Description doesn't say what the tool returns. Severity low.

The description explains what the tool does but never uses a return-shaped
word (returns, output, response, result, and similar), so an agent can't
predict how to use the result.

```json
{"description": "Fetches the requested record from the primary datastore."}
```

Fix: add a sentence describing the return value: its shape, type, or what it
contains.

## TS-004

Vague action verb with no specifics. Severity medium.

The description is one of the ambiguous verbs from the original finding
("process", "handle", "manage", "do") followed by nothing but filler words
("the data", "requests", "this"). Anything with a real object or detail
after the verb does not trigger this.

```json
{"description": "Handles requests."}
```

Fix: replace the vague verb with a specific one and name the input and
output it acts on.

## TS-005

Parameter undocumented in the description. Severity medium.

`inputSchema.properties` defines a parameter that the description never
mentions -- not by its literal name, and not by its words split out of
snake_case or camelCase. An agent has to guess its purpose from the name
alone.

```json
{
  "description": "Converts an amount between currencies.",
  "inputSchema": {"properties": {"rounding_mode": {"type": "string"}}}
}
```

Fix: mention every parameter in the description, or at least the ones whose
purpose isn't obvious from the name.

## TS-006

Parameter has no description field. Severity low.

A parameter's own schema entry has no `description`, so its purpose rests
entirely on its name and type.

```json
{"properties": {"limit": {"type": "integer"}}}
```

Fix: add a `description` to the parameter's schema entry.

## TS-007

Required parameters not distinguishable. Severity medium.

`inputSchema.properties` is non-empty but there is no `required` key at all
(an explicit empty array is fine -- that means every parameter is
optional). An agent cannot tell which parameters are mandatory.

```json
{"properties": {"id": {"type": "string"}}}
```

Fix: add a `required` array listing the mandatory parameter names.

## TS-008

No error guidance. Severity info.

The description never uses a failure-shaped word (error, fails, invalid,
raises, exception, and similar), so an agent has no way to anticipate or
recover from a bad call.

```json
{"description": "Fetches the record and returns its contents."}
```

Fix: add a sentence about failure behavior -- what happens on invalid input,
and what the error looks like.

## TS-009

Name collides with another tool. Severity medium.

This tool's name is a near-duplicate of another tool's name in the same
manifest: an exact duplicate, a short prefix relationship ("search_items"
vs. "search_items_v2"), or a small edit distance between similar-length
names ("get_invoice" vs. "get_invoicee"). An agent can easily call the
wrong one.

```json
{"tools": [{"name": "get_user"}, {"name": "get_users"}]}
```

Fix: rename one of the two tools so the names are clearly distinct, or merge
them if they do the same thing.

## TS-010

Missing example for a multi-parameter tool. Severity info.

The tool takes three or more parameters but the description has no example
call (no "example", "e.g.", or fenced code), so an agent has to infer the
right argument shape.

```json
{
  "description": "Books a flight.",
  "inputSchema": {"properties": {"from": {}, "to": {}, "date": {}}}
}
```

Fix: add a short example showing typical argument values.

## TS-011

Overloaded tool description. Severity medium.

The description names four or more distinct action verbs, or two or more
action verbs joined by "and"/"or" at least twice. Either shape usually means
the tool does too much for an agent to reliably pick the right mode.

```json
{"description": "Creates, updates, deletes, and lists records, or sends a summary email."}
```

Fix: split the tool into one tool per action, or narrow the description to
the single thing it actually does.

## TS-012

Enum-worthy free text. Severity low.

A string parameter with no `enum` in its schema has a description that
spells out the allowed values in prose: three or more quoted/backtick
tokens, or an enumeration phrase ("one of", "either", "must be", "allowed
values") next to at least one quoted token.

```json
{"description": "Sort order to use, either 'asc', 'desc', or 'relevance'."}
```

Fix: add an `enum` listing the allowed values to the parameter's schema
instead of describing them in prose.
