# Changelog

Notable changes to toolsmell. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

These can change a result you already rely on.

- A manifest built to crash the parser now exits 2 with a one-line error.
  Arrays nested past 512 levels and integers over 4300 digits used to end in
  a traceback, which exited 1 like a tripped gate.
- Two tools with exactly the same name score 25 each (TS-018 only), not 50
  (TS-018 plus TS-009). Such a pair no longer trips the default
  `--max-score 50` on its own.
- An `inputSchema` that is a `$ref` into `$defs` or is built from `$ref`
  branches is now linted like the flat schema. Those tools used to score 0.
- TS-011 counts forms of one verb once and reads "a list" or "the upload" as
  a noun, so single-purpose descriptions it used to flag are now clean.
- In a run over several manifests, each one uses the `pyproject.toml`
  nearest to it. Before, the first file's table applied to all of them.
- Releases after v0.1.0 are licensed GPL-3.0-or-later. v0.1.0 and earlier
  stay under MIT.

### Added

- `--stdio CMD` runs a live MCP server and lints its real `tools/list`
  response. It speaks MCP 2026-07-28 (`server/discover`) and falls back to
  the older `initialize` handshake. It follows `nextCursor` pagination and
  quotes the server's exit status and stderr when it fails to start. Error
  text and stderr from the server get the same escaping as the report.
- `--timeout SECONDS` sets the time budget for a `--stdio` run (default 20).
- `--ignore` and `--select` switch rules off or on, from the command line or
  a `[tool.toolsmell]` table in `pyproject.toml`. An empty `--select` exits
  2, so an unset CI variable can't switch every rule off.
- `--max-tool-score N` fails the run when any single tool is that smelly.
- TS-013 to TS-018 check tool names, `x-mcp-header` values, icon sources and
  duplicate names against MCP 2026-07-28.
- A file can hold a whole saved JSON-RPC response or a bare array of tools,
  not only `{"tools": [...]}`. A file with a `nextCursor` is one page of a
  longer list, and stderr says the other pages are missing.
- `scripts/render_demo.py` redraws the README demo from a live run.

### Fixed

- A tool name with a newline in it could draw a fake clean report under the
  real one. Bidi and zero-width characters are escaped too.
- Lint time and output are bounded. 150,000 tools used to take hours. Two
  40,000-character names one letter apart took minutes, and 1000 tools
  sharing a name printed hundreds of megabytes.
- A `--stdio` server that sends its own ping before answering now works. So
  does a 2026-07-28 server that takes more than 5 seconds to start.
- Param rules no longer fail open or misfire on composed schemas
  (`allOf`/`anyOf`/`oneOf`), nullable strings, `$ref` parameters or a
  non-list `required`.
- An object or array inside `required` no longer ends the run in a
  traceback.
- TS-005 accepts a longer word that starts with the parameter name
  ("repository" for `repo`). It no longer counts `id` as mentioned inside
  "Provide".
- `--json` over several files prints one JSON array, not concatenated
  objects.
- Output with non-ASCII tool names no longer crashes when redirected on
  Windows. A UTF-8 BOM loads, and a UTF-16 or UTF-32 file says so.
- `--stdio` keeps backslashes and strips quotes in Windows paths.

## [0.1.0] - 2026-07-16

First tagged release. Lints a `tools/list` JSON file against twelve rules
(TS-001 to TS-012) and prints a 0-100 smell score that `--max-score` gates
in CI. Ships a pre-commit hook and `--json` output.

[Unreleased]: https://github.com/munzzyy/toolsmell/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/munzzyy/toolsmell/releases/tag/v0.1.0
