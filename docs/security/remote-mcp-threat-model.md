# Remote MCP Threat Model

This records the threat analysis for the remote (Streamable HTTP) MCP surface added
under [ADR-0003](../architecture/decisions/ADR-0003-remote-mcp-product-surface.md).
The surface is **read-only**: it serves the cached snapshot tools only, holds no
GitHub or workspace token, and exposes no mutation, arbitrary-fetch, or live-verify
tool. Caller-provided vendor strings are **data, never instructions** — they are
never interpolated into prompts or shell commands.

The companion fetch boundary for catalogue/source collection is
[`ssrf-fetch-boundary.md`](ssrf-fetch-boundary.md); this document covers the inbound
request surface.

| Threat | Mitigation |
| --- | --- |
| DNS rebinding | DNS-rebinding protection is on by default; Host and Origin headers are validated by the MCP transport security layer. |
| Origin validation | A present Origin not in the allow-list is rejected (403). An empty allow-list is never treated as a wildcard. Absent Origin is permitted only for non-browser MCP clients, per documented policy. |
| Host validation | The Host header must be in the allow-list. A non-loopback bind requires an explicit Host allow-list (`OPENVA_MCP_ALLOWED_HOSTS`); the loopback default derives a loopback-only list. |
| Oversized JSON-RPC body | The body is bounded before parsing: a declared Content-Length over the cap is rejected up front (413); a chunked body is buffered up to the cap and replayed. |
| Malformed JSON-RPC | Returned as a controlled transport error (HTTP 400), not an uncaught exception. |
| Excessive batch size | `enrich_inventory` bounds `rows` (maxItems) in its declared input schema; over-limit calls are a controlled tool error. |
| Excessive field length | Each identity field is bounded (maxLength) in the declared input schema. |
| Tool-name probing | An unknown tool returns a controlled tool error; the tool list is the fixed read-only set. |
| Exception leakage | Errors return stable, generic messages; tool arguments and request bodies are never emitted in traces or access logs. |
| Dependency version drift | The MCP SDK is pinned `>=1.27,<2`; transport deps are declared explicitly. |
| Snapshot substitution | Every export's content digest must match the agent index and the bound root snapshot identity; a mismatch fails closed before any tool serves. |
| Stale cached fallback disclosure | A remote read may fall back to cache only when the exact cached snapshot identity is disclosed on every result (`from_cache`). |
| Request / argument logging | Default access logging is disabled; the MCP route carries no vendor identity in its path, and bodies/arguments are never logged. |
| Arbitrary URL injection | No tool accepts a caller-supplied URL. The only network path is the hosted-static snapshot read, bound to the configured export tree. |
| Workspace token injection | No tool accepts a workspace credential; the request schema rejects unknown fields. |
| GitHub token injection | The server accepts no GitHub token and has no write path. |
| Catalogue write attempts | There is no mutation tool and no `data/**` write path; the candidate-intake lane stays inert (`execution_wired: false`). |
| Advisory prompt injection via vendor strings | Caller-provided vendor strings are treated as data only; they are matched, never executed or interpolated into prompts/shell. Output carries `not_advice: true` and no compliance/suitability/risk conclusion. |

## Fail-closed posture

- Readiness (`/readyz`) returns 503 until the snapshot has loaded **and** integrity
  verification has passed. `/mcp` returns 503 in the same window. A verification
  failure keeps the surface closed rather than serving unverified data.
- A non-loopback bind is refused unless `OPENVA_MCP_PUBLIC_READ_ENABLED=true` is set
  explicitly; the default binding is loopback-only.

## Operational controls required before public activation

Deployment-level rate limiting and abuse controls are mandatory before any public
activation. Hosting, DNS, TLS, production rate limiting, monitoring, and redacted
observability are out of scope for this work package and are tracked under
successor work (WP-OPENVA-AI-NATIVE-DISTRIBUTION-02).
