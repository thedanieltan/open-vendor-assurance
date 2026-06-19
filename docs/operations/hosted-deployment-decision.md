# Hosted public-read deployment decision

Decision report for **WP-OPENVA-AI-NATIVE-DISTRIBUTION-02**. It converts the
hosted posture accepted in [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)
into a decision-ready deployment package. The authoritative decision record is
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md);
the machine-readable contract is [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**This is analysis and architecture only.** No production infrastructure is
provisioned, no provider is accepted, no DNS/TLS is configured, no production
secret exists, and no hosted OpenVA endpoint is live. OpenVA is a public-source-only,
metadata-first registry of vendor-published assurance references; it does not
provide legal, compliance, or vendor-risk advice, never handles private or gated
or customer-specific material, and stores no raw vendor documents. Those limits
are unchanged by hosting.

The workload is a stateless FastAPI read API (`services/openva_match_service/`) plus
an asynchronous `verify`-mode worker doing bounded, SSRF-safe outbound fetches,
plus a small TTL-deleted job/result store and a queue between them, holding a
GitHub App key to *propose* candidates through the existing PR lifecycle. Traffic
is low and bursty.

## 1. Provider and execution platform

| Option | Execution | Queue + tiny store | Secrets + identity | Ops (1–5) | Lock-in (1–5) |
| --- | --- | --- | --- | --- | --- |
| **Google Cloud Run (baseline)** | OCI container, scale-to-zero, no idle charge, instant revision rollback | Cloud Tasks (HTTP dispatch + retry) + Firestore Native TTL | Secret Manager + Workload Identity (keyless cloud APIs) | 2 | 2 |
| **AWS Lambda (container)** | Container image, true `$0` idle, 15-min cap | SQS + DynamoDB on-demand TTL | SSM/Secrets Manager + IAM roles; KMS remote signing | 3 | 4 |
| **Azure Container Apps** | OCI on KEDA, scale-to-zero, ACA Jobs for the worker | Service Bus + Cosmos serverless TTL | Key Vault + Managed Identity; **remote JWT signing** | 3 | 2 |
| AWS App Runner | **Rejected** — closed to new customers (2026) | — | — | — | — |
| AWS ECS Fargate | **Rejected** — no scale-to-zero; always-on idle | — | — | 4 | 2 |
| Render | **Rejected** — paid tiers do not scale to zero; ~fixed idle floor | — | — | 2 | 2 |

**Recommendation: Google Cloud Run.** For a solo maintainer it best balances
simplicity, portability (runs the existing container unchanged — no handler
rewrite), scale-to-zero with no idle charge, a keyless cloud-API identity story,
and instant rollback. Operational complexity, scaling, and portability are all
favourable; the one honest gap (a soft instance cap and alert-only budgets) is
addressed by the engineered cost ceiling in §8 and §11. **AWS Lambda** is the
first alternative when hard abuse throttling and `$0` idle dominate; **Azure
Container Apps** when the GitHub App key must never enter the app (Key Vault
remote signing). The recommendation is provider-portable: the deployable is a
standard OCI container with a small adapter at the queue/store boundary.

## 2. Region and data location

- **Recommend** a single primary region chosen by the maintainer for data
  residency and latency; the free-grant rates of Cloud Run/ACA apply to specific
  regions, so the region is a maintainer input (see decision table).
- Uploaded inventories and request payloads are **transient** and processed in the
  primary region only; job/result records (operational metadata) and any backups
  stay in that region. **No inventory, job, result, log, or backup crosses
  regions** in the baseline; cross-region is out of scope and would need a new
  decision.
- Logs and metrics are regional and carry no submitted content (§8, §9).

## 3. Service topology

```
            ┌─────────────── static/cached fallback (canonical, always-on) ───────────────┐
            │  GitHub Pages exports + static MCP + pinned pack — independent of the host    │
            └──────────────────────────────────────────────────────────────────────────────┘
 client ─▶ public API (FastAPI /v1, /healthz, /readyz)
              │  cached mode: answer from pinned pack (no egress)
              │  verify mode: create job ──▶ queue ──▶ async worker
              │                                          │  SSRF-safe fetch (vendor authority)
              │                                          ▼
              │                              durable job/result store (TTL, minimised)
              │  poll job ◀───────────────────────────── (state, result_ref)
              ▼
         candidate-ingress boundary ──▶ existing PR-bound candidate lifecycle (discovery only)
         admin/kill-switch ──▶ disable verify + ingress; static layer keeps serving
```

Components (`topology_components` in the contract): `public_api`, `resolver_app`,
`async_worker`, `queue`, `durable_job_store`, `static_cached_fallback`,
`candidate_ingress_boundary`, `health_readiness`, `admin_kill_switch`. Detail in
[`hosted-deployment-architecture.md`](hosted-deployment-architecture.md).

## 4. Domain, DNS, and TLS

- **Hostname structure (proposed):** a maintainer-owned OpenVA host, e.g.
  `api.<openva-domain>` for `/v1` and `mcp.<openva-domain>` for the remote MCP,
  with staging under a `staging.` prefix. Names are illustrative; the actual
  domain is maintainer-owned.
- **Change boundary:** DNS and the domain are **maintainer-controlled**. This
  package configures nothing.
- **Certificates:** provider-managed certificates on the maintainer host
  (automatic renewal); no private key handling in the repo.
- **DNS rollback:** keep the static GitHub Pages site authoritative; a hosted
  failure is recovered by removing the API/MCP records and pointing users back to
  the static layer. **No DNS change is made in this WP.**

## 5. Artifact and registry strategy

- **Format:** a single immutable OCI image built from the existing
  `services/openva_match_service/Dockerfile`, pack mounted/baked per the existing
  deployment doc.
- **Registry:** the provider-native registry (e.g. Artifact Registry) with
  **immutable tags** and digest-pinned deploys; registry ownership is maintainer.
- **Provenance + supply chain:** build provenance (SLSA-style attestation), an
  SBOM, image + dependency scanning, and pinned base images. Releases are
  digest-addressed; rollback is "deploy the prior digest."
- **Build/release flow:** CI builds and scans on tag; promotion to staging then
  production is a maintainer-gated deploy (§12). No registry is created here.

## 6. Secrets and identity

- **GitHub App custody:** an installation token mints from a GitHub App private
  key. **GitHub Apps do not support OIDC**, so the key is a **stored secret on
  every platform**. It lives in a managed secret store (Secret Manager / Key Vault
  / SSM), never in the repo, browser, artifacts, or logs. Where the provider
  supports it (Azure Key Vault, AWS KMS), prefer **remote signing** so the raw key
  never enters the app.
- **Workload identity:** use the provider's workload identity for *cloud* API
  access (no static cloud keys). This does not remove the GitHub key.
- **Least privilege:** the serving process holds read-only catalogue access and a
  narrowly-scoped GitHub App (contents + pull-requests on the OpenVA repo only,
  for candidate-intake PRs); it has **no** catalogue-merge authority.
- **Break-glass:** documented revocation (revoke installation token, rotate key,
  disable ingress) in the runbook.
- **Staging vs production:** separate apps, secrets, and identities. **No secret is
  created in this WP.**

## 7. Persistence and retention

- **Job record:** operational metadata only — `job_id`, `state`, `freshness_mode`,
  `request_digest` (SHA-256, for idempotency; the request is never stored),
  `row_count`, `result_ref`, `error_code`, timestamps, `expires_at`, `not_advice`.
  Schema: [`schemas/openva/hosted-job-record.schema.json`](../../schemas/openva/hosted-job-record.schema.json)
  (`additionalProperties: false`, so a leaked inventory/identity field fails
  validation). States and transitions: [`hosted-deployment-job-lifecycle.md`](hosted-deployment-job-lifecycle.md).
- **Result blob:** the resolver result returned to the caller, also transient and
  TTL-deleted; referenced by `result_ref`, never indexed by submitted content.
- **Idempotency:** keyed on `job_id`; a repeated identical request (same
  `request_digest`) reuses the existing job rather than duplicating work.
- **Expiry/deletion:** native store TTL (default 24h) deletes job + result; failed
  jobs expire on the same TTL. **Operational records vs uploaded content:** only
  the minimised job record + aggregate metrics persist; uploaded inventory content
  is never persisted beyond in-memory processing.
- **Backup:** none required for transient data; the catalogue itself is the git
  repo (already durable). Optional short-retention store snapshots are operational
  only and carry no submitted content.
- **Concurrency + recovery:** bounded concurrent jobs; a crashed worker leaves the
  job in `queued`/`executing` and the TTL reaps it; retries are bounded
  (`attempt`).

## 8. Abuse and application security

- **Limits:** request body cap (existing `OPENVA_MAX_UPLOAD_BYTES`), row cap
  (`OPENVA_MAX_ROWS`), max active jobs (`OPENVA_MAX_ACTIVE_JOBS` — enforced in the
  transport slice), per-job execution timeout, and bounded outbound fetch
  (size/deadline) via the SSRF boundary.
- **Rate limiting:** edge/gateway rate limiting plus app-level per-client limits;
  abusive traffic is rejected before doing work.
- **CORS:** explicit allow-list; an empty allow-list is never treated as wildcard
  (mirrors the MCP transport posture).
- **Errors:** stable, generic external messages with an internal correlation id
  (`job_id`) that leaks no submitted content.
- **CSV-formula-safe exports:** the existing formula-injection-safe export handling
  is preserved for any spreadsheet-facing output.
- **Supply chain:** dependency + image scanning in CI; pinned dependencies.
- **SSRF:** all egress through `build_safe_verify_fetcher`; **SSRF-negative tests**
  are an acceptance requirement of the transport slice. No arbitrary-URL endpoint.
- **DoS:** instance/concurrency caps + rate limits + the kill-switch.

## 9. Observability

- **Signals:** structured logs, metrics, traces, and alerts — all carrying
  **none** of `prohibited_telemetry_fields` (request bodies, vendor identity,
  inventory rows, uploaded inventory, tool arguments, candidate URLs).
- **SLIs:** availability (successful `/healthz`/`/readyz`), `/v1` p95 latency
  (cached path), verify-job completion rate + p95 duration, error rate, queue
  depth/age.
- **Initial SLOs (proposed, tunable):** read API availability 99.5% monthly;
  cached `/v1` p95 < 800 ms; verify-job success ≥ 99% excluding upstream vendor
  outages. Full detail + thresholds: [`hosted-deployment-observability.md`](hosted-deployment-observability.md).
- **Alerting:** error-rate, latency, queue-saturation, and **cost/abuse** alerts to
  a maintainer notification path.

## 10. Availability and degradation

- **Target:** 99.5% monthly for the read API (proposed); the static layer is the
  always-on floor.
- **Degradation:** store/queue/worker unavailable → serve cached/static, clearly
  labelled `from_cache`; verify falls back to cached and never presents stale as
  live. Queue saturation → shed verify load (return cached + `queued`/`rate_limited`),
  never unbounded growth. Dependency (vendor site) failure → honest
  `source_unavailable` / `verification_inconclusive`, never a fabricated result.
- **Kill switch:** disable verify + candidate-ingress; the static read layer keeps
  serving. Ingress disablement is independent of read serving.

## 11. Cost

| Scenario | Cloud Run (baseline) | AWS Lambda | Azure ACA |
| --- | --- | --- | --- |
| Idle (~0 traffic) | ≈ `$0` compute (scale-to-zero) + cents storage | ≈ `$0` (ECR storage only) | ≈ `$0` within free grant |
| Normal (light/bursty) | `$0`–single-digit `$` (free tier likely covers) | `$0`–low `$` | `$0`–a few `$` (companions dominate) |
| Abusive (hammered) | per-request scaling = real risk | **hard throttle** (reserved concurrency + gateway quota) | bounded by `maxReplicas` |

- **Fixed vs variable:** baseline is almost entirely variable (scale-to-zero); the
  companions (secret store, tiny job store, registry storage) are cents.
- **Cost ceiling:** **no platform offers a hard spend cap.** The engineered ceiling
  is: a deliberate low instance/concurrency cap **+** edge rate limiting **+** a
  budget-alert → automation kill-switch. Detail + numbers to confirm:
  [`hosted-deployment-cost-envelope.md`](hosted-deployment-cost-envelope.md).
- **Maintainer-confirm before provisioning:** the spend ceiling value, the budget
  alert threshold, and the exact free-tier/region rates (these shift; verify in the
  provider calculator).

## 12. Delivery and rollback

- **Environments:** development (local container), staging (maintainer-owned
  staging host), production (maintainer-owned host). Separate secrets/identities.
- **CI/CD authority:** CI builds + scans + pushes an immutable image; promotion to
  staging then production is a **maintainer-gated** deploy. CI never holds
  production credentials in the repo.
- **Promotion:** image digest promoted staging → production after staging smokes.
- **Production smoke sequence:** A — `/healthz`/`/readyz` + cached `/v1` read; B —
  one verify job end-to-end with a known vendor (no write-back); C — a candidate
  intake dry-run proving the PR-bound boundary. Evidence recorded before any
  public-traffic enablement.
- **Rollback criteria + mechanics:** SLO breach, security incident, or cost-ceiling
  breach → redeploy the prior immutable image (instant on Cloud Run/ACA; alias
  repoint on Lambda). **Credential-revocation sequence:** revoke installation
  token → disable ingress → rotate key → confirm static layer serving.
- **Static-only recovery:** the terminal safe state is "hosted disabled, static
  layer serving," which is always reachable.

## 13. External decisions (maintainer-controlled)

| Decision | Recommended option | Alternatives | Rationale | Reversibility | Lock-in | Approx. cost | Maintainer action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Provider | Google Cloud Run | AWS Lambda; Azure ACA | Solo-simple, portable, scale-to-zero, keyless cloud, instant rollback | High (portable container) | Low | `$0`–single-digit/mo idle+light | Accept provider |
| Region | Maintainer-selected | — | Data residency + latency + free-grant rates | High | Low | region-dependent | Select region |
| Domain | Maintainer-owned OpenVA host | — | OpenVA-controlled HTTPS host (ADR-0001) | High | None | domain renewal | Provide domain |
| DNS / TLS | Managed cert on the host | — | Auto-renew, no key handling | High | None | included | Configure DNS/TLS |
| Container registry | Provider-native, immutable tags | GHCR | Provenance + digest-pinned rollback | High | Low | cents storage | Create registry |
| Secrets + identity | Workload identity + secret store; remote signing where available | KMS/Key Vault signing | GitHub key can't use OIDC; minimise exposure | High | Low | cents | Create secrets |
| Spend ceiling | Concurrency cap + rate limit + kill-switch | fixed-instance hosting | No vendor hard cap exists | High | None | engineering only | Set ceiling value |
| Production permissions | Least-privilege; staging≠prod | — | Separation of duties | High | None | — | Grant scoped perms |
| Public traffic | Enable after staging smokes | — | Honest launch posture | High (kill-switch) | None | — | Enable traffic |
| ADR-0006 acceptance | Accept + merge | — | Records the architecture decision | High (revert PR) | None | — | Accept ADR-0006 |

## Hard boundaries preserved (ADR-0001)

Non-advisory output (`not_advice: true` + the advisory-boundary header); SSRF-safe
public-source-only retrieval with no arbitrary-URL fetch and no portal/CAPTCHA/WAF
bypass; no direct catalogue mutation (PR-bound candidate write-back only);
resolver discovery / decision / merge stay separated; transient unpublished inputs
never in logs/metrics/traces; static exports + static MCP + cached operation keep
working when the hosted service is down; live observations stay distinguishable
from canonical truth; production credentials never enter the browser/repo/artifacts/
logs; complete rollback + kill-switch; no production-live claim before provisioning
and smoke evidence exist. Threat detail: [`../security/hosted-deployment-threat-model.md`](../security/hosted-deployment-threat-model.md).

## Non-goals (this work package)

No provisioning; no provider/region/domain/credential acceptance; no DNS/TLS; no
registry/secret creation; no staging/production deploy; no public traffic; not the
hosted-transport implementation; not the positioning-reconciliation rewrites
(those land in lockstep with the first transport merge per ADR-0001).

## Follow-on slices

The dependency-ordered implementation slices are specified in
[`hosted-deployment-implementation-plan.md`](hosted-deployment-implementation-plan.md)
and listed machine-readably in the contract. The first executable slice after
acceptance is **WP-02A — hosted transport + API contract**.
