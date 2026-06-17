# ADR-0001: Hosted OpenVA Resolver Service and Live Source Verification

- **Status:** Accepted. The in-process resolver core has **already merged** (the
  catalogue-first, live-refresh-on-use Python/CLI path — `tools/openva/vendor_resolution.py`,
  the unified candidate model, the durable lifecycle ingress, the result schema,
  the SSRF-safe fetch, and `freshness_mode` `cached`/`verify`; see
  `docs/vendor-resolution.md`). This decision therefore governs only the
  **remaining hosted-transport and live-deployment** capability: an HTTP `/v1`
  surface with an async job/result store, a live public `/check` integration, live
  MCP resolver tools, deployment, and production smokes — **none of which has
  merged.** Those become buildable under the boundaries below; deployment also
  needs external infrastructure (GitHub App, secrets, hosting, DNS, registries).
- **Date:** 2026-06-16 (proposed), 2026-06-17 (accepted)
- **Decision owners:** OpenVA maintainers (human authority required for boundary,
  policy, and positioning changes per `AGENTS.md`).
- **Programme:** WP-OPENVA-PUBLIC-ACTIVATION-01.

This is the first record in the OpenVA architecture decisions log
(`docs/architecture/decisions/`). It records the decision and its boundaries;
`docs/vendor-resolution.md` describes the merged implementation.

## Context

OpenVA is evolving from a **public, pinned-export registry** into a product where
a practitioner or agent submits a vendor name / domain / inventory and receives
current public assurance-source references, with discoveries feeding the existing
autonomous candidate lifecycle.

The **in-process resolver already exists on `main`** (merged via the unified
vendor-resolution work): `vendor_resolution.py` resolves cached + live-refresh
sources, builds unified `candidate_record`s, evaluates eligibility, and hands them
to a durable, concurrency-safe lifecycle ingress (`CatalogQueueIngress` /
`GitHubIntakeIngress` / `RecordingIngress`) that writes
`maintenance/candidates/<id>.json` and tracks an honest durability ladder
(`pending_ingress` → `workflow_visible` → `candidate_processing`). It reuses the
SSRF-safe boundary (`safe_fetch` / `safe_verify`) and the result schema.

What does **not** yet exist, and what this ADR gates, is the **hosted transport
and live deployment** layer: an HTTP `/v1` surface with asynchronous job
execution and a durable job/result store, the live public `/check` integration,
live MCP resolver tools, and the deployed service itself. Those cross three
positions that are **currently canonical** in the repository — and under the
`AGENTS.md` *Documentation conflict order* those statements outrank a narrative
brief, so a recorded decision is required **before** any hosted-transport or
live-deployment capability merges:

1. **"OpenVA does not operate a central hosted service."** Stated in several
   places (see *Positioning reconciliation*); the match-service contract
   additionally promises *no persistence, no tenant state, and no request-path
   network egress* for that self-hosted wrapper.
2. **`AGENTS.md` repository purpose:** OpenVA "is **not** an upload-driven
   crawler, a private SaaS intelligence service, a workspace app, a stateless
   retrieval engine, or a vendor-risk scoring system."
3. **The non-advisory / no-hosted-decisioning invariant** (`docs/non-advisory-policy.md`,
   machine-enforced via `config/bot-constitution.yaml`): OpenVA records
   source-bound factual metadata only and never decides pass/fail.

## Decision

**Permit the hosted transport and live-verification deployment of the
already-merged resolver, bounded by the hard constraints below.** The constraints
are not advisory; they are the acceptance gates for every hosted-transport / live
/ deployment PR, and CI must enforce the ones that are machine-checkable.

### Hard boundaries (acceptance gates)

1. **Non-advisory, unchanged.** The resolver returns only source-bound public
   metadata and observed source state. It never emits a verdict, score, risk
   level, approval, suitability, or advice. Every resolver and MCP response
   carries `not_advice: true` and the `X-OpenVA-Advisory-Boundary: non_advisory`
   boundary. The prohibited-claims vocabulary (`config/prohibited-claims.yaml`)
   applies to resolver output. LLMs may assist drafting; they never decide a
   result status.
2. **SSRF-safe, public-source-only retrieval.** All live retrieval goes through
   the existing safe boundary (`safe_fetch` / `build_safe_verify_fetcher`) bound
   to the vendor's own authority: DNS-pinned IPs, private/loopback/mixed-answer
   rejection, same-authority per-hop redirects, bounded bytes, whole-request
   deadline, no cookies/credentials, no anti-bot / CAPTCHA / WAF bypass, no
   gated or authenticated content. **No endpoint fetches an arbitrary URL
   without vendor-authority resolution.**
3. **Not a catalogue mutation path.** The resolver writes nothing to `data/**`
   and never to `main`. Its only write-back is *proposing* candidate records into
   the existing PR-only lifecycle via the durable ingress (branch → PR →
   authority/path/validation → release gate → controlled merge). **Separation of
   duties is preserved:** the resolver discovers; independent existing components
   decide and merge. There is exactly one catalogue mutation path, and it is not
   the resolver.
4. **Transient, unpublished inputs.** Uploaded inventories are transient: never
   published, never placed in catalogue records, never written to logs or metric
   labels, deleted on a TTL. Only bounded aggregate operational metrics persist.
   This is consistent with `docs/retention-policy.md` and the public-source-only
   posture.
5. **Credential isolation and honest degradation.** The hosted service is a
   separate deployable under an OpenVA-controlled HTTPS host. The browser never
   holds a GitHub App or service credential. The static GitHub Pages site, pinned
   exports, and **static MCP mode remain the canonical reproducible layer** and
   keep working when the resolver is unavailable. A resolver failure degrades
   honestly (cached/static, clearly labelled) and never silently presents a stale
   result as a live one.
6. **Catalogue determinism preserved.** Live results are clearly labelled and
   visually/semantically distinct from canonical catalogue records. Live
   verification *supplements* the deterministic export; it never overwrites it.
   Reproducibility of the catalogue given inputs + versioned rules is unchanged.

A hosted-transport / live / deployment PR that cannot satisfy all six is out of
scope for this ADR and needs a new decision.

## Alternatives considered

1. **Status quo — no hosted transport.** Rejected as the launch posture: it fails
   the core outcome (a non-technical practitioner cannot use OpenVA without
   Python/GitHub/CLI). *Retained as the rollback posture* — disabling the hosted
   transport returns OpenVA to the pinned-export registry plus the in-process
   resolver CLI.
2. **Browser-only live verification (no central service).** Rejected: the
   SSRF-safe boundary (DNS pinning, IP allow/deny, same-authority redirects)
   cannot run in a browser; CORS and the absence of DNS control make it both
   unsafe and unreliable; and a browser cannot safely hold a credential for
   write-back.
3. **Hosted resolver that also scores / decides / approves.** Rejected outright:
   violates the non-advisory invariant and `AGENTS.md` ("not a vendor-risk
   scoring system"). This is the line the bounded design must not cross.
4. **Bounded hosted transport over the merged resolver (chosen):** metadata-only,
   SSRF-safe, PR-only write-back via the existing ingress, transient inputs,
   honest degradation.

## Consequences

**Positive**
- A usable public product for privacy practitioners and agents over the resolver
  that already exists in-process.
- A real catalogue-maintenance signal: user/agent demand drives discovery through
  the existing ingress and autonomous lifecycle.
- No second resolver, candidate model, or mutation path is introduced — the hosted
  transport wraps the merged core.

**Negative / new obligations**
- A new operational surface: secrets, hosting, custom domain/TLS, abuse controls,
  monitoring, and a GitHub App. These are largely **external/maintainer-provisioned**.
- **The match-service contract must be revised** when the hosted `/v1` transport
  lands — the self-hosted wrapper currently forbids persistence and request-path
  egress, which the async job store and live verify introduce (bounded); so
  `docs/openva-match-service-contract.md` / `-deployment.md` change in lockstep.
- A new request-path attack surface requiring the ACT-06 controls (SSRF boundary
  on every fetch, body/row limits, rate limits, CORS allow-list, CSV-formula-safe
  exports, generic errors).

## Compliance / security notes

| Invariant | How it is preserved |
| --- | --- |
| Non-advisory (`config/bot-constitution.yaml`, `docs/non-advisory-policy.md`) | Resolver returns source-bound metadata + observed state only; `not_advice: true`; prohibited-claims vocabulary enforced on output. |
| Public-source-only (`docs/public-sources-only.md`) | Safe fetch bound to vendor authority; gated/auth/anti-bot never bypassed; gated pages recorded as access-state facts only. |
| PR-only mutation, reversibility, separation of duties (`AGENTS.md`) | Resolver only proposes candidate records via the existing durable ingress + PR lifecycle; no direct `data/**` or `main` writes; discovery ≠ decision ≠ merge. |
| Retention / minimal leakage (`docs/retention-policy.md`) | Inventories transient and TTL-deleted; not published; not in logs or metric labels. |
| Release-smoke limitation phrases (`tools/openva/release_smoke.py`) | The 7 required phrases — *public-source-only, metadata-first, does not provide legal, vendor-risk advice, private or gated, customer-specific, raw vendor documents* — are preserved verbatim in any positioning rewrite. ("central hosted" is **not** a required phrase, so revising it does not break the gate.) |

## Positioning reconciliation

The following statements become inaccurate once the hosted transport ships and are
revised **in lockstep with the first hosted-transport / live capability merge —
not before** (so narrative never contradicts shipped behaviour). Each rewrite
keeps the 7 required limitation phrases and reframes the service as *hosted,
non-advisory, public-source, transient-input*. Anchors are quoted phrases (not
line numbers) so they survive future edits:

| File | Phrase to revise |
| --- | --- |
| `README.md` | "does not operate a public upload service or central hosted matching service"; "OpenVA does not operate a central hosted service." |
| `docs/openva-match-service-contract.md` | "OpenVA does not operate a central hosted service." |
| `docs/openva-match-service-deployment.md` | "OpenVA does not operate a central hosted service." |
| `docs/public-launch-checklist.md` | "does not operate a hosted private inventory upload service or central hosted matching service" |
| `docs/release-downloads.md` | "does not operate a public upload service or central hosted matching" |
| `docs/v0.1.0-public-launch-readiness.md` | "does not operate a public upload service or central hosted matching" |
| `docs/agent-export-contract.md` | "No hosted API and no MCP server — these are static files." |

Until that lockstep merge, all of these remain true and unchanged.

## Rollout

0. **Already merged (in-process core):** the unified resolver, candidate model,
   durable lifecycle ingress, result schema, SSRF-safe fetch, and `freshness_mode`
   landed via the unified vendor-resolution work. The governance-clean additions
   in flight alongside this ADR are scoped and non-hosted: SSRF hardening of the
   remaining non-resolver verify/discovery/intake lanes (ACT-06), contract-
   preserving match-service health/limits/bounded-upload scaffolding (ACT-01), and
   an (inert, `execution_wired: false`) `automerge:candidate-intake` lane plus a
   freshness push trigger for the existing candidate store (ACT-02). None claims a
   hosted capability.
1. **Hosted transport** — an asynchronous job-execution engine, a durable
   job/result store, and the HTTP `/v1` verify surface over the merged resolver.
   *Gated by this ADR.*
2. **Positioning reconciliation** (the files above) lands **with** the hosted
   transport.
3. **Live MCP resolver tools and the public `/check` live mode** (build on the
   `/v1` surface). *Gated by this ADR.*
4. **Production smokes A/B/C** and the launch-evidence record. *Gated by this ADR.*

**Rollback:** disable the hosted transport / live mode → the in-process resolver
CLI, cached browser matching, static exports, and static MCP remain available;
candidate-intake failure → keep returning source results, mark catalogue update
pending; security incident → revoke the GitHub App token, disable resolver
ingress, rotate secrets, keep the read-only catalogue available.

## Sign-off

- [x] Maintainer accepts the bounded posture and the six hard boundaries (recorded
      by merging this ADR).

On acceptance, the gated **hosted-transport, live, and deployment** steps (1, 3, 4
above) become buildable under the six boundaries. The in-process resolver core is
already merged and is not gated by this ADR.
