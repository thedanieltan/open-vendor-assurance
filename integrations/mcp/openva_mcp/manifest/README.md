# Publication metadata (draft, not yet submitted)

These files are prepared for distribution but have **not** been published:

- `server.json` — MCP Registry server metadata
  (schema `2025-12-11`). Not submitted to the MCP Registry.
- `mcp-manifest.json` — local MCP host manifest describing the stdio command and
  tool surface.

The package is not on PyPI and no OCI image has been pushed. Treat the
`pypi` package reference in `server.json` and the `openva-mcp` console command as
the intended identifiers once publication actually succeeds, not as a claim that
they resolve today.

Ownership verification markers used by the MCP Registry are in place for when
submission happens:

- PyPI: the `<!-- mcp-name: io.github.thedanieltan/openva -->` marker in the
  package `README.md`.
- OCI: the `io.modelcontextprotocol.server.name` label in the `Dockerfile`.
