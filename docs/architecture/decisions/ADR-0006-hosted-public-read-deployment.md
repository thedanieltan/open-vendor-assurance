# ADR-0006: Hosted Public-Read Deployment Architecture

- **Status:** Accepted — authoritative as of this **status-change PR's** merge (see
  the ADR lifecycle in [`README.md`](README.md)). A maintainer accepts the deployment
  **architecture** (topology, async/TTL job model, honest-degradation static fallback)
  recorded here. **Google Cloud Run remains the recommended baseline — a recommendation,
  not an accepted provider commitment.** **Acceptance authorises the architecture, not
  provisioning, and accepts no external deployment choice:** the provider, region,
  domain, DNS/TLS, production secrets, and spend ceiling are **not** accepted or created
  here and remain maintainer-gated in the WP-02 implementation slices (staging WP-02F,
  production WP-02G) — consistent with the contract's `provider_accepted_by_maintainer:
  false`.
  **No production infrastructure is provisioned, no provider account is created, no
  DNS/TLS is configured, no production secret exists, and no hosted OpenVA endpoint
  is live.**
  This ADR records *how* ADR-0001's accepted hosted posture should be deployed; the
  architecture is now authoritative, but it deploys nothing by itself.
- **Date:** 2026-06-19 (proposed); 2026-06-21 (accepted)
- **Decision owners:** OpenVA maintainers. Provider, region, domain, credentials,
  spend, production permissions, and public positioning remain human authority
  (`GOVERNANCE.md`).
- **Programme:** WP-OPENVA-AI-NATIVE-DISTRIBUTION-02. Governed by ADR-0001.

## Context

[ADR-0001](ADR-0001-hosted-resolver-and-live-verification.md) **accepted** the
bounded hosted transport and live-verification deployment of the already-merged
resolver, under six hard boundaries. It deliberately left the *deployment* —
provider, topology, persistence, secrets, abuse controls, observability, cost,
and rollback — to a later decision. This ADR is that decision.

The hosted artifact already exists as a self-hosted wrapper: a Python FastAPI /
Uvicorn service at `services/openva_match_service/` with `/healthz`, `/readyz`,
`/v1/catalog/meta`, `/v1/vendors/*`, `/v1/match`, and `/v1/enrich`, a public-read
mode, a Dockerfile, and *scaffolding* limits for active jobs and a job TTL that
are **not yet enforced** because the async transport does not exist. The async
job/result store and verify-mode egress that ADR-0001 permits are unbuilt.

This ADR does **not** revise the match-service contract or the positioning files;
those change *in lockstep with the first hosted-transport merge* per ADR-0001, not
in a decision-only package.

## Decision

**Adopt the following deployment architecture and recommend a baseline provider,
subject to maintainer acceptance of the external choices.** The detailed analysis
and decision table are in [`docs/operations/hosted-deployment-decision.md`](../../operations/hosted-deployment-decision.md);
the machine-readable contract is [`docs/operations/contracts/hosted-deployment.yaml`](../../operations/contracts/hosted-deployment.yaml).

### Topology

A single OCI deployable composed of: a rate-limiting edge (HTTPS LB + Cloud Armor),
a public read API (FastAPI), an asynchronous `verify`-mode **worker realized as a
Cloud Run service handler invoked by Cloud Tasks** (a concrete, bounded surface —
the **grounded** live-verify limit of `max_verify_rows 20` at the resolver's real
`SAFE_TIMEOUT_SECONDS` = 20 s per fetch, worst case ~12 min, fits the Cloud Tasks
30-min dispatch deadline with ~2× headroom; a larger verify limit is a separate
future WP requiring parent/child decomposition, not assumed here), a queue, a
transient request envelope + a small durable
job store (operational metadata only, TTL-deleted) + a transient result store, the
static/cached fallback layer (GitHub Pages exports + static MCP, which remain
canonical and keep working when the hosted service is down), the existing PR-bound
candidate-ingress boundary (the **only** holder of the GitHub App key — the API and
worker hold no GitHub credential), health/readiness endpoints, and an administrative
kill-switch. See
[`docs/operations/hosted-deployment-architecture.md`](../../operations/hosted-deployment-architecture.md).

### Recommended baseline (recommendation only — reassessed across review rounds)

**Google Cloud Run** — a container API **and a long-running container worker**
(+ external HTTPS LB & Cloud Armor for the rate-limiting edge, Cloud Tasks,
Firestore TTL, Secret Manager, Workload Identity). The reassessment converged here
after review #402 corrected the cost facts: the mandatory edge gives Cloud Run a
**~$24/mo fixed floor**, AWS Lambda's **API Gateway throttling is best-effort, not a
hard cost cap**, and **no provider offers a hard spend cap** — so cost is roughly a
wash and **not** decisive. The decisive factors for a solo maintainer are
**portability** (Cloud Run runs the existing container unchanged for both API and
worker) and **execution headroom**: the **grounded** live-verify worst case (~12 min
for `max_verify_rows 20` at `SAFE_TIMEOUT_SECONDS` = 20 s) fits Cloud Run's 30-min
dispatch deadline with ~2× headroom, where AWS Lambda's **15-min** ceiling is
tighter for the same work. (The earlier "verify is a 500-row batch that can't fit
Lambda" framing is **withdrawn**: 500 rows is the *cached* batch, which does no live
fetch; the hosted verify limit is 20 rows.) **Alternative — Azure Container Apps**
(container worker; Key Vault remote JWT signing — strongest secret posture).
**Alternative — AWS Lambda**, a viable `$0`-idle option with tighter execution
headroom and best-effort gateway throttling. Rejected: AWS App Runner
(closed to new customers in 2026), ECS Fargate and Render (no scale-to-zero / high
idle floor). The deployable stays a portable OCI image; the provider is a
reversible maintainer choice.

### Deployment-specific acceptance gates (in addition to ADR-0001's six)

1. **Engineered bounded spend rate (no hard cap).** No major platform offers a hard
   spend cap; Cloud Run's `max-instances` is a **soft** cap and AWS API Gateway
   throttling is **best-effort** (only Lambda reserved concurrency / ACA
   `maxReplicas` are hard, and only at the compute boundary). The deployment MUST
   bound the *rate* of spend with an instance/concurrency cap **plus** edge rate
   limiting **plus** a budget-alert-driven kill-switch, and accept a bounded
   worst-case overrun window (budget alerts lag) — not a vendor checkbox.
2. **GitHub App key is a stored secret everywhere, isolated to candidate-ingress.**
   GitHub Apps do not support OIDC token exchange, so the private key remains a
   stored secret on every platform. It MUST live in a managed secret store, never in
   the repo, browser, artifacts, or logs; remote signing (KMS / Key Vault) is
   preferred where supported. It is held/used by **only the candidate-ingress
   component** — the internet-facing API and the verify worker hold no GitHub
   credential (least-privilege `access_matrix`).
3. **Transient, minimised job records.** The durable store holds operational
   metadata only — a `request_ref` pointer, a row count, lifecycle state,
   timestamps, and a TTL — never uploaded inventory, vendor identity, request
   bodies, or a content-derived dedup key. The schema enforces this with
   `additionalProperties: false` **and** `if`/`then`/`allOf` state invariants
   (`schemas/openva/hosted-job-record.schema.json`).
4. **Honest degradation.** When the job store, queue, or worker is unavailable the
   service degrades to cached/static results, clearly labelled, and never presents
   a stale result as live. The static layer remains independently functional.
5. **Reversible, decision-only.** Nothing here provisions infrastructure. The
   external choices (gate by `provider_accepted_by_maintainer` etc.) are recorded
   as maintainer decisions and remain unmade until accepted.

A deployment PR that cannot satisfy ADR-0001's six boundaries **and** these five
is out of scope and needs a new decision.

## Alternatives considered

1. **Defer the deployment decision (status quo).** Rejected: leaves every
   follow-on slice blocked on architecture invention. A decision-ready package
   unblocks parallel implementation without provisioning anything.
2. **Always-on fixed-instance hosting (ECS Fargate / Render).** Rejected as the
   baseline: naturally bounded cost but a permanent idle floor for a low-traffic
   service, and no scale-to-zero. Retained as a fallback if scale-to-zero cold
   starts prove unacceptable.
3. **Serverless functions (AWS Lambda) as the baseline.** `$0` idle, but its API
   Gateway throttling is best-effort (not a hard cost cap), its 15-minute invocation
   ceiling gives tighter headroom than Cloud Run's 30-min dispatch deadline for the
   grounded ~12-min verify worst case (and a *larger* future verify limit would force
   per-row fan-out + aggregation sooner), and the ASGI→handler adapter raises lock-in.
   Kept as an alternative for the `$0`-idle case, not the baseline.
4. **Browser/edge-only execution.** Rejected for the same reasons as ADR-0001
   alternative 2: the SSRF-safe boundary and credential custody cannot run there.

## Consequences

**Positive**
- Follow-on implementation (the slices in the implementation plan) needs no
  architecture invention; each slice has inputs, outputs, allowed paths, tests,
  and rollback.
- The recommendation fits ADR-0001's boundaries: portable container, scale-to-zero,
  credential isolation, honest static fallback, egress control as defence-in-depth
  over the in-app SSRF boundary.

**Negative / new obligations**
- A new operational surface (secrets, monitoring, abuse controls, a GitHub App,
  custom domain/TLS) that is **maintainer-provisioned and outside this package**.
- The match-service contract and the seven positioning files must be revised **in
  lockstep with the first hosted-transport merge** (ADR-0001), not here.
- Cost is usage-metered with no vendor hard cap; the engineered ceiling above is a
  standing obligation.

## Compliance / security notes

| Invariant | How it is preserved |
| --- | --- |
| Non-advisory (ADR-0001, `config/bot-constitution.yaml`) | Every hosted response keeps `not_advice: true` + `X-OpenVA-Advisory-Boundary: non_advisory`; job records carry `not_advice: true` and no verdict. |
| Public-source-only + SSRF-safe (`docs/security/ssrf-fetch-boundary.md`) | All verify-mode egress routes through `build_safe_verify_fetcher` bound to vendor authority; no arbitrary-URL endpoint; platform egress controls are defence-in-depth. |
| PR-only mutation, separation of duties (`AGENTS.md`) | The hosted service only *proposes* candidates via the existing durable ingress; no `data/**` or `main` write; discovery ≠ decision ≠ merge. |
| Retention / leakage (`docs/retention-policy.md`, ADR-0001) | Inputs transient + TTL-deleted; job records minimised; `prohibited_telemetry_fields` never logged (`docs/operations/hosted-deployment-observability.md`). |
| Credential isolation (`GOVERNANCE.md`) | GitHub App key in a managed secret store, never in browser/repo/artifacts/logs; workload identity for cloud APIs; documented in the runbook. |
| Determinism + honest degradation (ADR-0001) | Static exports + static MCP remain canonical and independently functional; live results labelled and distinct. |

## Rollout

0. **This ADR (decision-only):** records the architecture + recommendation; nothing
   provisioned. The follow-on slices (`docs/operations/hosted-deployment-implementation-plan.md`)
   become buildable on acceptance.
1. **Hosted transport + async job persistence + worker/queue + candidate-ingress
   integration** (slices WP-02A–D). *Gated by ADR-0001 and this ADR.*
2. **Artifact/supply-chain + staging** (WP-02E–F).
3. **Production infrastructure + observability/abuse controls** (WP-02G–H) — needs
   the maintainer-accepted external decisions.
4. **Remote MCP resolver activation + live `/check`** (WP-02I–J).
5. **Production smokes + launch evidence**, then **positioning reconciliation**
   in lockstep (WP-02K–L).

**Rollback:** disable the hosted transport / kill-switch → the in-process resolver
CLI, cached browser matching, static exports, and static MCP remain available;
security incident → revoke the GitHub App token, disable ingress, rotate secrets,
roll back to the prior immutable image, keep the read-only catalogue available.

## Sign-off

- [x] Maintainer accepted the deployment **architecture** via this **status-change
      PR**, which flips this ADR's Status and the README index row to Accepted (and
      updates the acceptance-count test). The recommended provider baseline and the
      other external deployment choices remain separate, unaccepted maintainer
      decisions made at provisioning.

Merging the ADR's introducing PR recorded it as a **non-authoritative proposal**;
this **status-change PR** makes ADR-0006 **Accepted** and authoritative. Acceptance
authorises the architecture only; it provisions nothing, creates no provider account,
and the concrete external decisions (provider account, region, domain, DNS/TLS,
secrets, spend ceiling) remain maintainer-gated in the WP-02 implementation slices.
