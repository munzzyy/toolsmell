# Security

toolsmell reads an MCP server's `tools/list` output - a JSON manifest - and
lints the descriptions and schemas in it. Parsing is `json.loads` plus plain
text analysis. It never connects to a server, never calls a tool, and never
executes anything from the manifest.

A manifest is untrusted input, and manifests from third-party MCP servers are
exactly the ones worth linting. A manifest crafted to crash toolsmell, to hang
it, or to smuggle terminal escape sequences into the report so they run in
your terminal is a vulnerability here. A smell the linter should reasonably
catch but doesn't is a regular issue - attach the manifest.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's private
reporting instead:

https://github.com/munzzyy/toolsmell/security/advisories/new

Include what you found, how to reproduce it, and the impact you'd expect.

## Supported versions

Fixes land on the latest tagged version; there's no backport policy.
