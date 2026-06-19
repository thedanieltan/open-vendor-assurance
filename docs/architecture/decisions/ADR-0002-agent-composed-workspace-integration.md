# ADR-0002: Agent-Composed Workspace Integration as the Primary Distribution Model

- **Status:** Accepted — recorded by merging PR #398.
- **Date:** 2026-06-18 (proposed), 2026-06-18 (accepted)
- **Decision owners:** OpenVA maintainers (human authority required for boundary,
  policy, and positioning changes per `AGENTS.md`).
- **Programme:** WP-OPENVA-AI-NATIVE-DISTRIBUTION-01.

## Context

OpenVA users already keep vendor inventories and related work in existing
environments — spreadsheets, document systems, ticketing tools, procurement
systems and databases. A conventional integration strategy would require OpenVA
to build and maintain a separate add-on or plug-in for each environment, which
creates:

- duplicated user interfaces;
- duplicated OAuth and permission models;
- duplicated release and marketplace processes;
- duplicated mapping logic;
- a long-tail connector maintenance burden;
- pressure for OpenVA to become a workspace application rather than a specialist
  public metadata service.

Modern agent hosts already provide access to the user's workspace and can compose
multiple specialist tools in one workflow. OpenVA therefore does not need to
acquire direct workspace access merely to make its public catalogue useful inside
those workspaces. This keeps OpenVA consistent with its stated purpose in
`AGENTS.md` — it is **not** a workspace app, a private SaaS intelligence service,
or a vendor-risk scoring system.

## Decision

OpenVA adopts **agent-composed workspace integration as its primary distribution
model**. The composition is:

```text
workspace
  ↕
agent host's workspace connector
  ↕
agent orchestration
  ↕
OpenVA read-only API or MCP tools
```

OpenVA exposes specialist, host-neutral operations. The agent host reads the
user's existing workspace, identifies relevant fields, decides how to present or
write results, and enforces its own workspace authorization and approval model.
OpenVA does not build direct workspace access into its core service.

## Hard boundaries

1. OpenVA does not request or receive Google, Microsoft, Notion, Jira, Slack or
   equivalent workspace credentials.
2. OpenVA does not enumerate the user's files, sheets, databases, pages, tickets
   or channels.
3. OpenVA accepts only bounded, explicit vendor-identity inputs.
4. OpenVA returns public source metadata and provenance only.
5. OpenVA never claims to have modified a workspace.
6. Workspace write-back is performed by the agent host, not by OpenVA.
7. OpenVA tool semantics remain the same regardless of which workspace the agent
   is using.
8. Workspace-specific business logic must not enter the catalogue, resolver or MCP
   core.

## Alternatives considered

1. **Build a native connector for every platform.** Rejected as the primary
   strategy: it creates a conventional integration treadmill and duplicates
   workspace-access concerns already handled by agent hosts. Retained as a
   *secondary* compatibility surface — see ADR-0005.
2. **Require users to migrate vendor inventories into an OpenVA workspace.**
   Rejected. OpenVA is not a private workspace SaaS application and should not
   require data migration merely to resolve public references.
3. **Publish only files and require manual joins.** Retained as a deterministic
   fallback, but insufficient as the primary non-technical user experience.
4. **Agent-composed access (chosen).** Preserves OpenVA's specialist boundary
   while allowing use in any workspace the user's agent already supports.

## Consequences

**Positive**

- One durable OpenVA capability can serve many workspaces.
- No broad workspace OAuth burden and no separate UI per platform.
- Users keep working where their data already exists; private workspace data stays
  under the agent host's existing controls.
- OpenVA remains host-neutral.

**Negative / new obligations**

- OpenVA must provide precise tool schemas and workflow instructions
  (`docs/agent-workspace-composition.md`, `schemas/openva/agent-enrichment-*`).
- Agent hosts differ in workspace capability; compound-workflow testing becomes
  necessary.
- OpenVA cannot guarantee that an external agent writes results correctly, and must
  clearly distinguish its output from the agent's subsequent workspace actions
  (see ADR-0004).

## Relationship to ADR-0001

ADR-0001 permits the hosted resolver and live transport under strict public-source,
non-advisory and PR-only boundaries. ADR-0002 determines **how** users and agents
compose that capability with existing workspaces. It does not replace ADR-0001 and
does not itself ship a hosted production endpoint.
