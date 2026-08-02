"""Rule selection: which rule ids a run is allowed to report.

Two ways in, in this order of precedence: `--ignore` / `--select` on the
command line, then a `[tool.toolsmell]` table in the nearest pyproject.toml
above the manifest being linted. A rule that is not selected is dropped
before scoring, so turning off a rule you disagree with also takes its
weight out of the smell score -- otherwise the flag would silence the text
and leave the number lying.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .catalog import BY_ID

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.9 / 3.10: no stdlib TOML parser
    tomllib = None

CONFIG_TABLE = "tool.toolsmell"


class ConfigError(Exception):
    """Raised when rule selection cannot be resolved: an unknown rule id, or
    a pyproject.toml that exists but cannot be read."""


def _parse_ids(raw, where: str) -> set:
    """Turn a comma-separated string or a list of strings into a set of rule
    ids, rejecting anything the catalog does not know about. An unknown id
    is a typo the user wants to hear about, not a silent no-op that leaves
    the rule running."""
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ConfigError(f"{where} must be a list of rule ids")
    ids = set()
    for item in items:
        if not isinstance(item, str):
            raise ConfigError(f"{where} must be a list of rule ids")
        rule_id = item.strip().upper()
        if not rule_id:
            continue
        if rule_id not in BY_ID:
            known = ", ".join(sorted(BY_ID))
            raise ConfigError(
                f"{where}: unknown rule id {rule_id!r}. Known ids: {known}")
        ids.add(rule_id)
    return ids


def find_pyproject(start) -> "Path | None":
    """Nearest pyproject.toml at or above `start`. Stops at the filesystem
    root; returns None if there isn't one."""
    directory = Path(start).resolve()
    if directory.is_file():
        directory = directory.parent
    for candidate in [directory, *directory.parents]:
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            return pyproject
    return None


def _warn(message: str) -> None:
    """Say out loud that rule selection did not get applied.

    Dropping a selection only ever makes a run stricter -- every rule stays
    on -- so this never hides a smell. It does mean rules the user switched
    off are about to fire, and being told why beats staring at findings you
    thought you had disabled.
    """
    print(f"toolsmell: {message}", file=sys.stderr)


def _read_pyproject(pyproject: Path) -> dict:
    if tomllib is None:
        # No stdlib TOML parser before 3.11 and toolsmell ships zero runtime
        # dependencies, so the table cannot be honored here. Say so instead
        # of pretending the file was empty -- an unread `ignore` list means
        # rules the user switched off are about to fire.
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}
        if f"[{CONFIG_TABLE}]" in text:
            _warn(f"{pyproject} has a [{CONFIG_TABLE}] table, but reading it "
                  f"needs Python 3.11+ (running {sys.version_info[0]}."
                  f"{sys.version_info[1]}). Continuing with every rule enabled; "
                  "pass --ignore or --select to override.")
        return {}
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as e:
        _warn(f"cannot read {pyproject} ({e}). Continuing with every rule "
              "enabled; pass --ignore or --select to override.")
        return {}
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}
    section = tool.get("toolsmell")
    return section if isinstance(section, dict) else {}


def from_pyproject(start) -> "tuple[set, set]":
    """Read `ignore` and `select` out of the nearest pyproject.toml. Returns
    two sets, either of which may be empty."""
    pyproject = find_pyproject(start)
    if pyproject is None:
        return set(), set()
    section = _read_pyproject(pyproject)
    where = f"{pyproject} [{CONFIG_TABLE}]"
    ignore = _parse_ids(section["ignore"], f"{where} ignore") if "ignore" in section else set()
    select = _parse_ids(section["select"], f"{where} select") if "select" in section else set()
    if ignore and select:
        raise ConfigError(f"{where}: set either 'ignore' or 'select', not both")
    return ignore, select


def resolve(ignore=None, select=None, config_start=None) -> "frozenset | None":
    """The set of rule ids a run may report, or None for 'every rule'.

    Command-line values win outright: passing either flag skips the
    pyproject.toml lookup entirely, so a one-off run is never quietly
    reshaped by a config file the user forgot about.
    """
    if ignore is not None and select is not None:
        raise ConfigError("pass either --ignore or --select, not both")
    if ignore is not None:
        return frozenset(set(BY_ID) - _parse_ids(ignore, "--ignore"))
    if select is not None:
        return frozenset(_parse_ids(select, "--select"))
    if config_start is None:
        return None
    file_ignore, file_select = from_pyproject(config_start)
    if file_select:
        return frozenset(file_select)
    if file_ignore:
        return frozenset(set(BY_ID) - file_ignore)
    return None
