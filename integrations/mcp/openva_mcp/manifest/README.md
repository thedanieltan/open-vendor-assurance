# Publication metadata (draft, not yet submitted)

`server.json` is the MCP Registry server metadata (schema `2025-12-11`). It has
**not** been submitted to the MCP Registry, the package is not on PyPI, and no
OCI image has been pushed.

Treat the `pypi` package reference in `server.json` and the `openva-mcp` console
command as the intended identifiers once publication actually succeeds, not as a
claim that they resolve today.

Ownership verification markers used by the MCP Registry are in place for when
submission happens:

- PyPI: the `<!-- mcp-name: io.github.thedanieltan/openva -->` marker in the
  package `README.md`.
- OCI: the `io.modelcontextprotocol.server.name` label in the `Dockerfile`.

## Pinned schema provenance

`server.schema.2025-12-11.json` is a committed copy of
`https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`
(SHA-256 `3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0`).
Tests validate `server.json` against this pinned copy so validation is
deterministic and offline; the digest above guards the pinned bytes.
