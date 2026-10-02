"""Per-rule unit tests. Each rule module is exercised directly so a test
failure points straight at the rule, not at the whole pipeline."""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import random
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from toolsmell import cli
from toolsmell.lint import lint_tools
from toolsmell.manifest import parse_tools
from toolsmell.rules import description, examples, naming, schema
from toolsmell.rules._util import Tokens
from tests._helpers import by_rule, lint, mk_tool


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

    def test_short_name_inside_a_word_is_not_a_mention(self):
        # 'id' is a substring of 'Provide' but the param is never really
        # documented, so it must still be flagged.
        t = mk_tool(
            "get_user",
            description="Provide a user record and return its fields as JSON.",
            schema={"type": "object", "properties": {"id": {"type": "string"}}})
        self.assertIn("TS-005", _ids(schema.check(t, [t])))

    def test_short_name_as_a_whole_word_counts_as_mentioned(self):
        t = mk_tool(
            "get_user",
            description="Fetches the user with the given id and returns the record.",
            schema={"type": "object", "properties": {"id": {"type": "string"}}})
        self.assertNotIn("TS-005", _ids(schema.check(t, [t])))

    def test_a_longer_word_starting_with_the_param_counts_as_mentioned(self):
        # The exact false positive that cost a well-documented tool 25
        # points: 'repo' called undocumented by a description that says
        # "in a GitHub repository".
        t = mk_tool(
            "create_issue",
            description="Create a new issue in a GitHub repository with the "
                        "given title and body. Returns the issue number, or "
                        "an error if the repository does not exist.",
            schema={"type": "object", "properties": {"repo": {"type": "string"}}})
        self.assertNotIn("TS-005", _ids(schema.check(t, [t])))

    def test_the_same_allowance_covers_split_name_words(self):
        # 'auth_token' splits to auth/token, and 'authentication' documents
        # 'auth' the same way 'repository' documents 'repo'.
        t = mk_tool(
            "sign_in",
            description="Exchanges an authentication token for a session and "
                        "returns the session id, or an error if it is expired.",
            schema={"type": "object",
                    "properties": {"auth_token": {"type": "string"}}})
        self.assertNotIn("TS-005", _ids(schema.check(t, [t])))

    def test_the_allowance_does_not_pretend_to_be_a_stemmer(self):
        # It matches a token that STARTS WITH the param name, nothing more.
        # 'currencies' does not start with 'currency', so this still fires,
        # and the rule stays something a user can predict by reading it.
        t = mk_tool(
            "convert",
            description="Converts an amount between the supported currencies "
                        "and returns the converted value, error if unknown.",
            schema={"type": "object", "properties": {"currency": {"type": "string"}}})
        self.assertIn("TS-005", _ids(schema.check(t, [t])))

    def test_short_names_keep_the_strict_whole_token_rule(self):
        # Under four characters a shared prefix means nothing: 'idle' must
        # not document 'id'. This is what the length floor protects.
        t = mk_tool(
            "get_user",
            description="Returns the idle users on the account, with an error "
                        "if the account is unknown.",
            schema={"type": "object", "properties": {"id": {"type": "string"}}})
        self.assertIn("TS-005", _ids(schema.check(t, [t])))

    def test_a_prefix_match_still_needs_a_word_boundary(self):
        # 'user' must not be documented by 'superuser' -- the allowance
        # extends a token to the right, never to the left.
        t = mk_tool(
            "grant",
            description="Grants superuser rights on the account and returns "
                        "the result, or an error if it fails.",
            schema={"type": "object", "properties": {"user": {"type": "string"}}})
        self.assertIn("TS-005", _ids(schema.check(t, [t])))

    def test_param_in_a_composed_subschema_is_still_checked(self):
        # Params tucked under allOf must be linted like top-level ones, or
        # the rules fail open on the composed shape.
        t = mk_tool(
            "composed", description="Does a thing with several inputs and returns JSON.",
            schema={"type": "object", "allOf": [
                {"properties": {"undoc": {"type": "string"}}}]})
        self.assertIn("TS-005", _ids(schema.check(t, [t])))


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

    def test_ref_with_description_in_defs_does_not_fire(self):
        # A $ref param whose referenced $defs entry carries a description is
        # documented; resolving the ref must not report a bogus TS-006.
        t = mk_tool("t", description="x", schema={
            "type": "object",
            "properties": {"location": {"$ref": "#/$defs/Location"}},
            "$defs": {"Location": {"type": "string",
                                   "description": "The location to search for."}}})
        self.assertNotIn("TS-006", _ids(schema.check(t, [t])))

    def test_ref_without_description_still_fires(self):
        t = mk_tool("t", description="x", schema={
            "type": "object",
            "properties": {"location": {"$ref": "#/$defs/Location"}},
            "$defs": {"Location": {"type": "string"}}})
        self.assertIn("TS-006", _ids(schema.check(t, [t])))


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

    def test_non_list_required_still_fires(self):
        # "required": true is malformed -- it is not a usable required list,
        # so the rule must still fire instead of going silent.
        t = mk_tool("t", description="d", schema={
            "type": "object", "properties": {"x": {"type": "string"}},
            "required": True})
        self.assertIn("TS-007", _ids(schema.check(t, [t])))

    def test_required_list_in_composed_branch_does_not_fire(self):
        t = mk_tool("t", description="d", schema={
            "type": "object", "allOf": [
                {"properties": {"x": {"type": "string"}}, "required": ["x"]}]})
        self.assertNotIn("TS-007", _ids(schema.check(t, [t])))


class NoErrorGuidance(unittest.TestCase):
    def test_no_error_words_fires(self):
        t = mk_tool("t", description="Fetches the record and returns its full contents as JSON.")
        self.assertIn("TS-008", _ids(description.check(t, [t])))

    def test_error_word_present_does_not_fire(self):
        t = mk_tool("t", description="Fetches the record and returns it, raising an error if missing.")
        self.assertNotIn("TS-008", _ids(description.check(t, [t])))


class NameCollision(unittest.TestCase):
    def test_exact_duplicate_name_is_left_to_ts018(self):
        # A client keeps only one of the two, so TS-018 owns this case.
        a = mk_tool("dup_tool", description="d")
        b = mk_tool("dup_tool", description="d", index=1)
        self.assertNotIn("TS-009", _ids(naming.check(a, [a, b])))

    def test_names_equal_after_normalizing_still_fire(self):
        for x, y in (("get_user", "get-user"), ("Get_User", "get_user"),
                     ("get_user", "get_users")):
            with self.subTest(pair=(x, y)):
                a = mk_tool(x, description="d")
                b = mk_tool(y, description="d", index=1)
                self.assertIn("TS-009", _ids(naming.check(a, [a, b])))

    def test_exact_duplicate_still_collides_with_a_third_name(self):
        a = mk_tool("get_user", description="d")
        b = mk_tool("get_user", description="d", index=1)
        c = mk_tool("get_users", description="d", index=2)
        self.assertEqual(_ids(naming.check(a, [a, b, c])), ["TS-009"])

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

    def test_bounded_levenshtein_matches_unbounded_verdict(self):
        # The early-abandon in _levenshtein is a speedup, not a behavior
        # change: for the distances the rule cares about it must agree with
        # the full computation, at and over the threshold.
        pairs = [("get_invoice", "get_invoicee"), ("alpha", "omega"),
                 ("abcdefghij", "abcdefghij"), ("abcdefghij", "zyxwvutsrq")]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                full = naming._levenshtein(a, b)
                self.assertEqual((full <= 2), (naming._levenshtein(a, b, 2) <= 2))


# TS-009 before the index, pair by pair. _within stands in for the DP table,
# which test_within_agrees_with_the_full_table holds it to.
_REF_SEP = re.compile(r"[_\-\s]+")


def _ref_levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def _ref_collides(na, nb):
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 4 and longer.startswith(shorter) and len(longer) - len(shorter) <= 4:
        return True
    return (min(len(na), len(nb)) >= 6 and abs(len(na) - len(nb)) <= 2
            and naming._within(na, nb, 2))


def _name_corpus(seed=11, size=2500):
    """Real-looking tool names, plus the near misses TS-009 is about:
    prefixes, case and separator changes, and one or two random edits."""
    rng = random.Random(seed)
    verbs = ["get", "list", "create", "delete", "update", "search", "sync",
             "fetch", "bulk_import", "reconcile_all"]
    nouns = ["user", "order", "invoice", "record", "weather", "repo", "issue",
             "payment", "session", "report", "customer", "ticket",
             "billing_account", "webhook_endpoint", "customer_subscription",
             "pull_request_review_comment"]
    base = [f"{v}_{n}" for v in verbs for n in nouns]
    names = set(base)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789_-"

    def edit(name):
        i = rng.randrange(len(name) + 1)
        op = rng.choice("sid")
        if op == "s" and i < len(name):
            return name[:i] + rng.choice(alphabet) + name[i + 1:]
        if op == "d" and i < len(name):
            return name[:i] + name[i + 1:]
        return name[:i] + rng.choice(alphabet) + name[i:]

    while len(names) < size:
        name = rng.choice(base)
        kind = rng.randrange(7)
        if kind == 0:
            name += rng.choice(["s", "_v2", "_all", "es", "_by_id"])
        elif kind == 1:
            name = name.upper() if rng.random() < 0.5 else name.title()
        elif kind == 2:
            name = name.replace("_", rng.choice(["-", "", " ", "__"]))
        elif kind == 3:
            name = edit(name)
        elif kind == 4:
            name = edit(edit(name))
        elif kind == 5:
            name = name[:rng.randint(3, len(name))]
        else:
            name = "".join(rng.choice(alphabet) for _ in range(rng.randint(4, 40)))
        if name.strip():
            names.add(name)
    return sorted(names)


class CollisionIndexParity(unittest.TestCase):
    """The index replaced a pairwise loop that took minutes on a few
    thousand tools. It must not change a single verdict."""

    def test_index_finds_exactly_the_pairwise_collisions(self):
        names = _name_corpus()
        tools = parse_tools({"tools": [{"name": n} for n in names]})
        norms = [_REF_SEP.sub("", t.name.lower()) for t in tools]
        # No branch of the rule matches lengths more than four apart.
        order = sorted(range(len(tools)), key=lambda i: len(norms[i]))
        expected = {}
        for x, a in enumerate(order):
            for b in order[x + 1:]:
                if len(norms[b]) - len(norms[a]) > 4:
                    break
                if tools[a].name != tools[b].name and _ref_collides(norms[a], norms[b]):
                    expected.setdefault(a, []).append(b)
                    expected.setdefault(b, []).append(a)
        self.assertGreater(len(expected), 1000, "the corpus should collide a lot")

        index = naming._collision_index(tools)
        self.assertEqual(set(index), set(expected))
        for i, others in expected.items():
            listed, count = index[i]
            self.assertEqual(count, len(others), names[i])
            self.assertEqual([t.index for t in listed], sorted(others)[:naming.MAX_FINDINGS])

    def test_within_agrees_with_the_full_table(self):
        strings = ["".join(p) for n in range(6) for p in itertools.product("ab", repeat=n)]
        strings += ["abcabc", "bcabca", "aabbcc", "abcdef", "abdcef", "xabcdefy"]
        for a in strings:
            for b in strings:
                distance = _ref_levenshtein(a, b)
                for k in range(4):
                    self.assertEqual(naming._within(a, b, k), distance <= k, (a, b, k))
        rng = random.Random(3)
        for _ in range(3000):
            a = "".join(rng.choice("abc") for _ in range(rng.randint(0, 14)))
            b = "".join(rng.choice("abc") for _ in range(rng.randint(0, 14)))
            distance = _ref_levenshtein(a, b)
            for k in range(4):
                self.assertEqual(naming._within(a, b, k), distance <= k, (a, b, k))

    def test_bounded_levenshtein_still_agrees_with_within(self):
        names = _name_corpus(size=400)
        norms = [naming._normalized(n) for n in names]
        for a, b in itertools.combinations(norms, 2):
            if abs(len(a) - len(b)) <= 2:
                self.assertEqual(naming._within(a, b, 2),
                                 naming._levenshtein(a, b, 2) <= 2, (a, b))

    def test_two_long_names_one_edit_apart_are_fast(self):
        a = mk_tool("a" * 20000 + "b", description="d")
        b = mk_tool("a" * 20000 + "c", description="d", index=1)
        started = time.monotonic()
        self.assertEqual(_ids(naming.check(a, [a, b])), ["TS-009"])
        self.assertLess(time.monotonic() - started, 10.0)


class CollisionCaps(unittest.TestCase):
    def test_findings_stop_at_the_score_cap_and_count_the_rest(self):
        result = lint(*[{"name": n} for n in
                        ["get_user", "get_users", "get-user", "Get_User", "get_userx", "getuser"]])
        first = result.tools[0]
        ts009 = [f for f in first.findings if f.rule_id == "TS-009"]
        self.assertEqual(len(ts009), naming.MAX_FINDINGS)
        self.assertIn("and of 1 more tool(s) not listed", ts009[-1].detail)
        self.assertNotIn("more tool(s)", ts009[0].detail)

    def test_budget_stops_edit_matching_and_says_so(self):
        names = [{"name": f"tool_{c}bcdef"} for c in "pqrstuvw"]
        with mock.patch.object(naming, "EDIT_BUDGET", 3):
            result = lint(*names)
        self.assertEqual(len(result.notes), 1)
        self.assertIn("stopped looking", result.notes[0])
        with mock.patch.object(naming, "EDIT_BUDGET", 3):
            quiet = lint(*names, enabled=frozenset({"TS-001"}))
        self.assertEqual(quiet.notes, [])

    def test_cli_prints_notes_on_stderr_only(self):
        tmp = Path(tempfile.mkdtemp()) / "tools.json"
        tmp.write_text(json.dumps({"tools": [{"name": f"tool_{c}bcdef"} for c in "pqrstuvw"]}),
                       encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(naming, "EDIT_BUDGET", 3), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main([str(tmp), "--json", "--max-score", "1000"])
        json.loads(out.getvalue())
        self.assertIn("stopped looking", err.getvalue())


def _ref_param_mentioned(desc, name):
    return schema._param_mentioned(desc, name)


class MentionParity(unittest.TestCase):
    """TS-005 answers from a token set now instead of running regexes over
    the description once per parameter. Same verdicts either way."""

    DESCRIPTIONS = [
        "Fetches the item with the given item_id and returns its record, or an error.",
        "Looks up a user.name in the x-api-key header; returns JSON. Raises on a bad repo.",
        "Uses the repository config (configuration) and the auth-token; errors if unknown.",
        "The \u212aelvin scale and a lo\u017fe ID in \u0130stanbul, with an id.",
        "Returns the idle superuser; v2.1 of get-items. Sort order is asc.",
        "",
    ]
    NAMES = ["item_id", "item", "id", "user.name", "user", "name", "x-api-key",
             "api_key", "repo", "config", "auth_token", "auth-token", "kelvin",
             "lose", "istanbul", "Istanbul", "idle_user", "super", "user_id",
             "v2.1", "get-items", "getItems", "sortOrder", "asc", "ID", "Id",
             "repoUrl", "configuration", "s", "x", "_private", "trailing_",
             "a.b.c", "caf\u00e9", "\u212aelvin", "lo\u017fe", "-", "123"]

    def test_fast_path_matches_the_regexes(self):
        for desc in self.DESCRIPTIONS:
            tokens = Tokens(desc)
            for name in self.NAMES:
                with self.subTest(desc=desc[:30], name=name):
                    self.assertEqual(
                        schema._param_mentioned_fast(tokens, name, [], []),
                        _ref_param_mentioned(desc, name))

    def test_fast_path_matches_on_random_names(self):
        rng = random.Random(5)
        alphabet = "abcdeIKS_-. \u0130\u0131\u017f\u212a"
        for _ in range(120):
            desc = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            tokens = Tokens(desc)
            for _ in range(10):
                name = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
                self.assertEqual(schema._param_mentioned_fast(tokens, name, [], []),
                                 _ref_param_mentioned(desc, name), (desc, name))

    def test_many_params_against_a_long_description_are_fast(self):
        t = mk_tool("w", description="word " * 100000, schema={
            "type": "object", "properties": {f"p{i}": {} for i in range(1000)}})
        started = time.monotonic()
        self.assertEqual(len(schema.check(t, [t])), 1000 + 1000 + 1)
        self.assertLess(time.monotonic() - started, 15.0)

    def test_slow_path_budget_skips_and_says_so(self):
        desc = "Pass item_id and user_id; returns the record or an error."
        tool = {"name": "t", "description": desc, "inputSchema": {
            "type": "object", "properties": {"item_id": {}, "user_id": {}, "order_id": {}},
            "required": []}}
        with mock.patch.object(schema, "SLOW_PATH_CHARS", 2 * len(desc)):
            result = lint(tool)
        self.assertEqual(len(result.notes), 1)
        self.assertIn("TS-005 did not check 1 parameter", result.notes[0])
        full = lint(tool)
        self.assertEqual(full.notes, [])


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

    def test_single_purpose_descriptions_do_not_fire(self):
        # These read as (list, lists), (list, searches) and (fetches, upload).
        for desc in (
                "Lists open invoices for an account and returns them as a list, "
                "or an error if the account does not exist.",
                "Searches orders by customer email and returns a list of matching "
                "orders, or an empty list if none match. Raises an error on an "
                "invalid email.",
                "Fetches a file and returns its contents; raises an error if the "
                "path is invalid or the upload has not finished."):
            with self.subTest(desc=desc[:30]):
                t = mk_tool("t", description=desc)
                self.assertNotIn("TS-011", _ids(description.check(t, [t])))

    def test_forms_of_one_verb_count_once(self):
        self.assertEqual(description._actions("Lists users, or list them by team."), {"list"})
        self.assertEqual(description._actions("Searches and search, fetches and fetch."),
                         {"search", "fetch"})
        self.assertEqual(description._actions("Modifies or modify."), {"modify"})

    def test_a_verb_word_after_a_determiner_is_a_noun(self):
        self.assertEqual(description._actions("Returns a list."), set())
        self.assertEqual(description._actions("Waits for the upload."), set())
        self.assertEqual(description._actions("Returns an empty list."), set())
        self.assertEqual(description._actions("Synchronizes the order list."), set())

    def test_a_verb_after_a_subject_still_counts(self):
        # Only a base form two words after a determiner reads as a noun.
        self.assertEqual(description._actions("This tool searches orders."), {"search"})
        self.assertEqual(description._actions("Fields that get set."), {"get", "set"})
        self.assertEqual(description._actions("The tool lists files."), {"list"})

    def test_detail_lists_each_verb_once(self):
        t = mk_tool("t", description="Creates, updates, deletes, and lists records "
                                     "and then lists them again.")
        detail = next(f.detail for f in description.check(t, [t]) if f.rule_id == "TS-011")
        self.assertIn("(create, delete, list, update)", detail)


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

    def test_nullable_type_array_still_fires(self):
        # ["string", "null"] is a nullable string; the enum-worthy check must
        # see through the nullable wrapper.
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"order": {
                "type": ["string", "null"],
                "description": "Sort order: 'asc', 'desc', or 'random'.",
            }}})
        self.assertIn("TS-012", _ids(schema.check(t, [t])))

    def test_anyof_nullable_string_still_fires(self):
        # The Optional[str] shape FastMCP/pydantic emit.
        t = mk_tool("t", description="d", schema={
            "type": "object",
            "properties": {"order": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "Sort order: 'asc', 'desc', or 'random'.",
            }}})
        self.assertIn("TS-012", _ids(schema.check(t, [t])))

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
