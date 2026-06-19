# ADR-0006: Hosted Public-Read Deployment Architecture

- **Status:** Proposed — becomes Accepted when a maintainer accepts the deployment
  baseline and merges this ADR. **No production infrastructure is provisioned, no
  provider is accepted, no DNS/TLS is configured, no production secret exists, and
  no hosted OpenVA endpoint is live.** This ADR records *how* the already-accepted
  hosted posture should be deployed; it does not itself deploy anything.
- **Date:** 2026-06-19 (proposed)
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

A single deployable composed of: a public read API (FastAPI), an asynchronous
worker for `verify`-mode jobs, a queue between them, a small durable job/result
store (operational metadata only, TTL-deleted), the static/cached fallback layer
(GitHub Pages exports + static MCP, which remain canonical and keep working when
the hosted service is down), the existing PR-bound candidate-ingress boundary,
health/readiness endpoints, and an administrative kill-switch. See
[`docs/operations/hosted-deployment-architecture.md`](../../operations/hosted-deployment-architecture.md).

### Recommended baseline (recommendation only)

**Google Cloud Run** (+ Cloud Tasks for dispatch, Firestore Native TTL for the
tiny job store, Secret Manager, and Workload Identity), because it runs the
existing container unchanged (low lock-in), scales to zero with no idle charge,
offers instant revision rollback, and gives keyless access to cloud APIs.
**Alternatives:** AWS Lambda (container) — strongest hard abuse throttles
(reserved concurrency + gateway quotas) and true `$0` idle, at the cost of a
handler adapter and a 15-minute job ceiling; **Azure Container Apps** — same
scale-to-zero/portable-container profile plus Key Vault remote JWT signing, the
strongest secret posture (the GitHub App key never enters the app). Rejected:
AWS App Runner (closed to new customers in 2026), ECS Fargate and Render (no
scale-to-zero / high idle floor).

### Deployment-specific acceptance gates (in addition to ADR-0001's six)

1. **Engineered cost ceiling.** No major platform offers a hard spend cap. The
   deployment MUST bound cost with an instance/concurrency cap **plus** edge rate
   limiting **plus** a budget-alert-driven kill-switch — not a vendor checkbox.
2. **GitHub App key is a stored secret everywhere.** GitHub Apps do not support
   OIDC token exchange, so the private key remains a stored secret on every
   platform. It MUST live in a managed secret store, never in the repo, browser,
   artifacts, or logs; remote signing (KMS / Key Vault) is preferred where the
   chosen provider supports it.
3. **Transient, minimised job records.** The durable store holds operational
   metadata only — a request digest, a row count, lifecycle state, timestamps,
   and a TTL — never uploaded inventory, vendor identity, or request bodies
   (`schemas/openva/hosted-job-record.schema.json`, `additionalProperties: false`).
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
3. **Serverless functions (AWS Lambda) as the baseline.** Strong on cost caps and
   `$0` idle, but the ASGI→handler adapter raises lock-in and the 15-minute limit
   constrains verify batches. Kept as the first alternative, not the baseline.
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

- [ ] Maintainer accepts the deployment architecture and the recommended baseline,
      and the external decisions in the decision table, by merging this ADR
      (flips Status to Accepted and the README row to Accepted).

Until then this ADR is **Proposed** and authorises no provisioning.
