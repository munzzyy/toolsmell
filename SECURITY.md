# Security

toolsmell reads an MCP server's `tools/list` output - a JSON manifest - and
lints the descriptions and schemas in it. Parsing is `json.loads` plus plain
text analysis. By default (a JSON file on disk) it never connects to a
server, never calls a tool, and never executes anything.

`--stdio` is the one opt-in exception: it runs the command you give it as a
subprocess so it can speak the MCP handshake to a real server over stdio.
That command is split with `shlex` and exec'd as a real argv list - never a
shell - so there's no shell-injection surface in the command string, but the
process genuinely runs. It's your responsibility to only point `--stdio` at
a server you already trust to execute; toolsmell has no way to vet that for
you. The server's `tools/list` response itself is still just data, handled
by the same parser and the same threat model as a manifest file below - the
subprocess only ever gets *started*, its output is never executed. A hard
timeout bounds the whole exchange and each read, and a size cap bounds the
response, so a hung or unbounded-output server can't wedge or exhaust a run;
the process is killed either way once it's over.

A manifest - whether read from a file or from a live `--stdio` server - is
untrusted input, and manifests from third-party MCP servers are exactly the
ones worth linting. A manifest crafted to crash toolsmell, to hang it, or to
smuggle terminal escape sequences into the report so they run in your
terminal is a vulnerability here. A smell the linter should reasonably catch
but doesn't is a regular issue - attach the manifest.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's private
reporting instead:

https://github.com/munzzyy/toolsmell/security/advisories/new

Include what you found, how to reproduce it, and the impact you'd expect.

## Supported versions

Fixes land on the latest tagged version; there's no backport policy.
