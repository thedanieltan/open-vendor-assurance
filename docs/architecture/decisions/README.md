# Architecture Decision Records

This log records OpenVA's architecture decisions and their boundaries. Each ADR is
the authoritative record of one decision; the narrative docs (`README.md`,
`docs/**`) describe the resulting behaviour and must not contradict an accepted
ADR. This index is a pointer only — it is not a second source of decision content.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-0001](ADR-0001-hosted-resolver-and-live-verification.md) | Hosted OpenVA Resolver Service and Live Source Verification | Accepted |
| [ADR-0002](ADR-0002-agent-composed-workspace-integration.md) | Agent-Composed Workspace Integration as the Primary Distribution Model | Accepted |
| [ADR-0003](ADR-0003-remote-mcp-product-surface.md) | Remote Read-Only MCP as a First-Class Agent Transport | Accepted |
| [ADR-0004](ADR-0004-workspace-credential-and-action-boundary.md) | Workspace Credentials and Workspace Actions Remain Outside OpenVA | Accepted |
| [ADR-0005](ADR-0005-native-clients-as-secondary-compatibility-surfaces.md) | Native Workspace Clients Are Secondary Compatibility Surfaces | Accepted |
| [ADR-0006](ADR-0006-hosted-public-read-deployment.md) | Hosted Public-Read Deployment Architecture | Proposed |

**ADR lifecycle.** An ADR whose authoring PR records a decision already taken is
authored *Accepted* and becomes authoritative on that PR's merge (ADR-0001 on its
merge; ADR-0002–0005 on the merge of PR #398). An ADR may instead be authored
*Proposed* and merge to `main` as a **recorded, non-authoritative proposal**: it
documents a recommendation but authorises and provisions nothing. A *Proposed* ADR
becomes *Accepted* only through a **subsequent status-change PR** in which a
maintainer accepts it; that PR flips the ADR's Status and this index row to
Accepted (and updates any acceptance-count assertion). Merging a *Proposed* ADR
never makes it authoritative on its own.

ADR-0001 remains authoritative for the hosted live-verification transport;
ADR-0002–0005 govern agent-composed distribution and the remote read-only MCP
surface, and do not themselves claim a production hosted deployment. **ADR-0006 is
a *Proposed*, non-authoritative proposal**: it records *how* ADR-0001's accepted
hosted posture should be deployed (topology + a provider recommendation),
provisions no infrastructure, and claims no live endpoint. It becomes Accepted
only via a maintainer status-change PR that accepts the external deployment choices
(provider, region, domain, credentials, spend, positioning).
