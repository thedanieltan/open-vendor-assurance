# ADR-0005: Native Workspace Clients Are Secondary Compatibility Surfaces

- **Status:** Accepted — recorded by merging PR #398.
- **Date:** 2026-06-18 (proposed), 2026-06-18 (accepted)
- **Decision owners:** OpenVA maintainers (human authority required for boundary,
  policy, and positioning changes per `AGENTS.md`).
- **Programme:** WP-OPENVA-AI-NATIVE-DISTRIBUTION-01.

## Context

OpenVA has a manually installed Google Apps Script reference client (PR #397).
Earlier roadmap language anticipated Google Sheets, Excel and Word clients as a
principal distribution sequence. Building those as the default path creates
repeated packaging, UI, authentication and marketplace work. Some users and
organisations will nevertheless lack capable agents or prohibit agent access to
internal workspaces.

## Decision

Native workspace clients are permitted, but they are **secondary compatibility
surfaces**. They must not become separate product authorities. The default
implementation priority is:

```text
stable OpenVA contracts
→ HTTP and MCP
→ agent-composed workspace workflows
→ native compatibility clients only where demonstrated demand or policy
  constraints justify them
```

PR #397's Google Sheets implementation remains a reference client, a tested example
of safe row mapping and write-back, a fallback manual client, and a source of
integration fixtures. It is **not** the strategic centre of OpenVA distribution.

## Requirements for any future native client

Every native client must:

1. remain thin;
2. reuse the shared resolver/enrichment contract;
3. avoid duplicating matching or source-ranking logic;
4. request the minimum host permissions;
5. avoid embedding service credentials;
6. preserve ambiguous and no-match states;
7. preserve non-advisory output;
8. avoid storing private workspace content;
9. have an independent adoption or policy justification;
10. be removable without affecting the OpenVA core.

## Consequences

**Positive**

- Native clients remain available when needed; prior Google Sheets work remains
  useful.
- Platform-specific code cannot redefine OpenVA semantics.
- Engineering effort follows demonstrated demand.

**Negative**

- Some non-agent users may not receive first-class native integration immediately.
- Reference clients still require maintenance while supported.
- The roadmap must clearly distinguish primary and fallback distribution.
