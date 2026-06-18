# Architecture Decision Records

This log records OpenVA's architecture decisions and their boundaries. Each ADR is
the authoritative record of one decision; the narrative docs (`README.md`,
`docs/**`) describe the resulting behaviour and must not contradict an accepted
ADR. This index is a pointer only — it is not a second source of decision content.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-0001](ADR-0001-hosted-resolver-and-live-verification.md) | Hosted OpenVA Resolver Service and Live Source Verification | Accepted |
| [ADR-0002](ADR-0002-agent-composed-workspace-integration.md) | Agent-Composed Workspace Integration as the Primary Distribution Model | Proposed |
| [ADR-0003](ADR-0003-remote-mcp-product-surface.md) | Remote Read-Only MCP as a First-Class Agent Transport | Proposed |
| [ADR-0004](ADR-0004-workspace-credential-and-action-boundary.md) | Workspace Credentials and Workspace Actions Remain Outside OpenVA | Proposed |
| [ADR-0005](ADR-0005-native-clients-as-secondary-compatibility-surfaces.md) | Native Workspace Clients Are Secondary Compatibility Surfaces | Proposed |

A *Proposed* ADR becomes *Accepted* when the PR containing it merges. ADR-0001
remains authoritative for the hosted live-verification transport; ADR-0002–0005
govern agent-composed distribution and the remote read-only MCP surface, and do not
themselves claim a production hosted deployment.
