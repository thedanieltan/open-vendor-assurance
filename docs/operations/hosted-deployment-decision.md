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
source material, and stores no raw vendor documents. The hosted service
**transiently processes the customer-specific vendor identities a caller submits**
but never publishes, logs, retains, reuses, or incorporates that input into
canonical catalogue records — the input is held only in a transient, TTL-deleted
request envelope (§7). Those limits are unchanged by hosting.

The workload is a stateless FastAPI read API (`services/openva_match_service/`) plus
an asynchronous `verify`-mode worker doing bounded, SSRF-safe outbound fetches,
plus a small TTL-deleted job/result store and a queue between them, holding a
GitHub App key to *propose* candidates through the existing PR lifecycle. Traffic
is low and bursty.

## 1. Provider and execution platform

| Option | Execution | Edge (rate limit) | Queue + tiny store | Secrets | Idle floor | Cost-cap rigor | Ops | Lock-in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Google Cloud Run (baseline)** | container API **+ container worker (Cloud Run service handler invoked by Cloud Tasks)**; grounded **20-row** live-verify limit (~12-min worst case) fits the 30-min Cloud Tasks deadline with ~2× headroom | external HTTPS LB + Cloud Armor — configurable rate limit; **~$24/mo fixed floor** | Cloud Tasks + Firestore Native TTL | Secret Manager + Workload Identity | ~$24/mo | no hard cap (soft `max-instances` + Cloud Armor rate limit + budget kill-switch) | 2 | 2 |
| **Azure Container Apps (alternative)** | container + ACA Jobs worker (ACA Jobs run long; no 15-min function limit) | Front Door/APIM — fixed-ish floor | Service Bus + Cosmos serverless TTL | Key Vault + Managed Identity; **remote JWT signing** | low–mod | no hard cap (`maxReplicas` hard at compute) | 3 | 2 |
| **AWS Lambda (alternative — needs fan-out)** | functions, **≤15-min cap ⇒ per-row fan-out + aggregation** required | API Gateway throttling — **no fixed floor but best-effort, not a cost cap** | SQS + DynamoDB on-demand TTL | Secrets Manager + IAM; KMS remote signing | ≈ `$0` | reserved concurrency hard at **Lambda compute only**; gateway best-effort | 4 | 4 |
| AWS App Runner | **Rejected** — closed to new customers (2026) | — | — | — | — | — | — | — |
| AWS ECS Fargate | **Rejected** — no scale-to-zero; always-on idle | — | — | — | — | — | 4 | 2 |
| Render | **Rejected** — paid tiers do not scale to zero; ~fixed idle floor | — | — | — | — | — | 2 | 2 |

**Recommendation: Google Cloud Run (container API + long-running container worker).**
This is a reassessment after several review rounds that corrected the facts. (a) The
mandatory rate-limiting edge gives Cloud Run a **~$24/mo fixed floor** (LB + Cloud
Armor, §11) — modest and bounded. (b) Verify is **live-fetch batch work**: each row
drives serial 20-second (`SAFE_TIMEOUT_SECONDS`) SSRF-safe fetches, so the hosted
verify limit is **grounded and deliberately small — 20 rows, ~12-minute worst case**
(§7), distinct from the 500-row *cached* batch which does no fetch. That worst case
fits **Cloud Run's 30-minute Cloud Tasks dispatch deadline with ~2× headroom**;
AWS Lambda's **15-minute** function ceiling would be tighter for the same worst case
and grows fragile if source-type coverage widens, and its API Gateway throttling is
**best-effort, not a hard cost cap** (AWS documents not relying on usage plans for
cost control). For a solo maintainer prioritising simplicity, **running the existing
container unchanged for both API and worker, with ~2× time headroom**, is the
decisive advantage; Cloud Run scales to zero on compute and rolls back instantly.
**No provider offers a hard spend cap**, so the engineered bounded-spend-rate (soft
cap + edge rate limit + budget kill-switch, §8/§11) applies regardless. **Azure
Container Apps**
is the alternative when the GitHub App key must never enter the app (Key Vault
remote signing); **AWS Lambda** only if `$0` idle justifies building per-row
fan-out. The deployable stays a portable OCI image, so the provider remains the
maintainer's reversible choice.

> Reassessment note for the maintainer: the baseline moved Cloud Run → Lambda → back
> to Cloud Run across review rounds as the facts were corrected (edge floor, then
> Lambda's best-effort gateway + 15-min batch limit). The decisive factor is that
> verify is long-running batch work that fits a container worker without fan-out.
> The provider is your call; Lambda and ACA are documented as alternatives.

## 2. Region and data location

- **Recommend** a single primary region chosen by the maintainer for data
  residency and latency; the free-grant rates of Cloud Run/ACA apply to specific
  regions, so the region is a maintainer input (see decision table).
- Uploaded inventories and request payloads are **transient** and processed in the
  primary region only; job/result records (operational metadata) and any backups
  stay in that region. **No inventory, job, result, log, or backup crosses
  regions** in the baseline; cross-region is out of scope and would need a new
  decision.
- Logs and metrics carry no submitted content (§8, §9). Keeping them in the primary
  region is **not automatic on GCP** — it requires explicit regional log buckets +
  `_Default` sink configuration; this is an infrastructure-slice task with
  acceptance evidence (§12, implementation plan), not an assumed default.

## 3. Service topology

```
            ┌─────────────── static/cached fallback (canonical, always-on) ───────────────┐
            │  GitHub Pages exports + static MCP + pinned pack — independent of the host    │
            └──────────────────────────────────────────────────────────────────────────────┘
 client ─▶ edge gateway (HTTPS LB + rate limiting; origin reachable only via edge)
              ▼
           public API (FastAPI /v1, /healthz, /readyz)
              │  cached mode: answer from pinned pack (no egress)
              │  verify mode: write input ─▶ transient request store (envelope, encrypted, TTL)
              │               create job (job_id + one-time job_token) ─▶ queue (job_id only) ─▶ async worker
              │                                          │  re-read envelope ─▶ SSRF-safe fetch (vendor authority)
              │                                          ▼
              │   durable job store (TTL, minimised) + transient result store (result_ref, TTL)
              │  poll (job_id + job_token) ◀──────────── (state, result_ref); 410 while retained / 404 after deletion
              ▼
         candidate-ingress boundary ──▶ existing PR-bound candidate lifecycle (discovery only)
         admin/kill-switch ──▶ disable verify + ingress; static layer keeps serving
```

Components (`topology_components` in the contract): `edge_gateway`, `public_api`,
`resolver_app`, `async_worker`, `queue`, `transient_request_store`,
`durable_job_store`, `transient_result_store`, `static_cached_fallback`,
`candidate_ingress_boundary`, `health_readiness`, `admin_kill_switch`. The worker
reconstructs the request from the transient envelope by `job_id`; the queue and the
durable record never carry submitted input. Result access requires the `job_token`
capability (`job_id` is a loggable correlation id, not a credential), sent **header-only
as `Authorization: Bearer`** (never in a URL/query/path). **Execution surface
(concrete):** the worker is a Cloud Run service handler invoked by Cloud Tasks; the
**grounded 20-row** live-verify limit (worst case ~12 min, derived from the
resolver's `SAFE_TIMEOUT_SECONDS`) fits the Cloud Tasks 30-min dispatch deadline with
~2× headroom. A larger verify limit is a separate future WP requiring a full
parent/child decomposition (not a hand-waved scale-up). Detail in
[`hosted-deployment-architecture.md`](hosted-deployment-architecture.md).

## 4. Domain, DNS, and TLS

- **Hostname structure (proposed):** a maintainer-owned OpenVA host, e.g.
  `api.<openva-domain>` for `/v1` and `mcp.<openva-domain>` for the remote MCP,
  with staging under a `staging.` prefix. Names are illustrative; the actual
  domain is maintainer-owned.
- **Change boundary:** DNS and the domain are **maintainer-controlled**. This
  package configures nothing.
- **Edge + TLS:** a public **HTTPS Application Load Balancer with rate limiting**
  (e.g. Cloud Armor) terminates TLS on the maintainer host and is the only path to
  the origin — the container service's ingress is restricted to the edge
  (`internal-and-cloud-load-balancing` on Cloud Run) so **direct origin ingress
  cannot bypass** the rate limits. Provider-managed certificate (auto-renew); no
  private key in the repo. This edge adds a fixed monthly cost floor (§11).
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
- **Least privilege + credential isolation:** the GitHub App key is held and used
  by **only the candidate-ingress component** (the one that proposes PRs). The
  **internet-facing API and the verify worker hold no GitHub credential** — they
  have read-only catalogue access only (contract `access_matrix`). The App itself is
  narrowly scoped (contents + pull-requests on the OpenVA repo only) with **no**
  catalogue-merge authority.
- **Break-glass:** documented revocation (revoke installation token, rotate key,
  disable ingress) in the runbook.
- **Staging vs production:** separate apps, secrets, and identities. **No secret is
  created in this WP.**

## 7. Persistence and retention

Three stores, two of them transient. Full lifecycle:
[`hosted-deployment-job-lifecycle.md`](hosted-deployment-job-lifecycle.md).

- **Transient request envelope (`transient_request_store`):** the submitted input
  the worker must process. It is **not** carried in the queue (which holds `job_id`
  only) and **not** in the durable record. Written by the API at `received`, keyed
  by `job_id` (`request_ref`), encrypted at rest, read by the worker via workload
  identity (least privilege), and **deleted on the terminal transition** with an
  object-lifecycle TTL as a backstop. Bounded by the existing upload/row caps.
- **Durable job record (`durable_job_store`):** operational metadata only —
  `job_id`, `job_token_digest`, `state`, `freshness_mode` (always `verify`),
  `request_ref`, `row_count`, `result_ref`, `error_code`, timestamps, `expires_at`,
  `not_advice`. No request content, content fingerprint, or dedup key is stored.
  Schema:
  [`schemas/openva/hosted-job-record.schema.json`](../../schemas/openva/hosted-job-record.schema.json)
  — `additionalProperties: false` **and** `if`/`then`/`allOf` state invariants, so a
  leaked field or an inconsistent state (e.g. `completed` with no `result_ref`)
  fails validation.
- **Transient result blob (`transient_result_store`):** the resolver result,
  referenced by `result_ref`, deleted on TTL/expiry; never indexed by submitted
  content.
- **Result-access authorization:** `job_id` is a loggable correlation id and is
  **not** a credential. A one-time high-entropy `job_token` capability (returned at
  creation, never logged, stored only as `job_token_digest`) is required to poll/
  retrieve the result.
- **Idempotency (none in v1):** every request creates a **new job**. There is **no
  deduplication and no content-derived dedup key** — a digest of low-entropy vendor
  names is dictionary-testable and must not gate access. An optional idempotency key
  is deferred and, if ever added, must be a server-keyed HMAC scoped to an
  authenticated caller with defined replay/conflict/expiry — never a plain content
  digest.
- **Consistency/recovery:** the write-envelope → create-`received`-job → enqueue
  handoff follows one actor-scoped CAS protocol — **the API owns the normal
  `received → queued`** (after the enqueue ack; task name = `job_id`); the **worker**
  recovers via `received → queued` then `queued → executing` (no direct
  `received → executing`), takes an **execution lease**, and acks-and-drops duplicate
  deliveries; a **watchdog** recovers a stale lease (`executing → queued` re-dispatch,
  else `executing → failed`); the reconciler recovers un-dispatched `received` jobs.
  Orphan envelopes are TTL-reaped; job-create failure returns a generic retryable
  `503`. Polling distinguishes `received` (accepted, not dispatched) from `queued`
  (dispatched). Full rules:
  [`hosted-deployment-job-lifecycle.md`](hosted-deployment-job-lifecycle.md).
- **Expiry/deletion:** **time-based on `expires_at`, not a persisted state**, with
  explicit **three-phase** HTTP semantics (the record holds `expires_at` and
  `job_token_digest`, both gone once deleted): pre-expiry → status/result (`job_token`
  required); expired-but-retained → content-free **`410 Gone`**; after physical
  deletion → content-free **`404 Not Found`** (a 404 leaks nothing — `job_id` is not
  a credential). The record, request envelope, and result blob are each deleted by
  their own native TTL + object-lifecycle backstop; the result blob is not
  auto-deleted by the record TTL. Only the minimised record + aggregate metrics
  persist; uploaded content never persists beyond the transient envelope.
- **Limits + error codes:** two distinct caps — the cached/batch enrich limit
  `max_rows_cached: 500` (no live fetch) and the hosted **live-verify** limit
  `max_verify_rows: 20` (the schema's `row_count` maximum matches *this*, grounded in
  the resolver fetch model, §7/§11). Over-limit requests are **rejected by the API
  before a job exists**, so `input_too_large` / `row_limit_exceeded` are API rejection
  responses, **not** durable job error codes (those are `execution_timeout`,
  `upstream_unavailable`, `rate_limited`, `internal_error`).
- **Backup:** none required for transient data; the catalogue itself is the git
  repo (already durable).
- **Concurrency + recovery:** bounded concurrent jobs; a crashed/abandoned job
  times out to `failed` (`execution_timeout`) or expires to `410` after
  `expires_at`; retries are bounded (`attempt`) and re-read the same envelope.

## 8. Abuse and application security

- **Limits:** request body cap (existing `OPENVA_MAX_UPLOAD_BYTES`), row cap
  (`OPENVA_MAX_ROWS`), max active jobs (`OPENVA_MAX_ACTIVE_JOBS` — enforced in the
  transport slice), per-job execution timeout, and bounded outbound fetch
  (size/deadline) via the SSRF boundary.
- **Rate limiting + edge:** a concrete edge (HTTPS load balancer + rate limiting,
  e.g. Cloud Armor) plus app-level per-client limits; abusive traffic is rejected
  before doing work. The origin's ingress is restricted to the edge so **direct
  ingress cannot bypass** the limits (§4).
- **CORS:** explicit allow-list; an empty allow-list is never treated as wildcard
  (mirrors the MCP transport posture).
- **Result-access authorization + token transport:** results are retrieved with the
  one-time `job_token` capability, not the `job_id`. The token is sent **header-only
  (`Authorization: Bearer`)** — never in a URL, query string, path, or redirect;
  verified with a **constant-time** digest comparison; redacted by the API and the
  edge proxy; never logged/traced/metered/echoed/persisted (only `job_token_digest`
  persists; `authorization_header` + `job_token` are in `prohibited_telemetry_fields`).
  Failed/absent token → generic content-free response. No rotation in v1.
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
- **Log residency:** keeping logs in the primary region is **explicitly configured**
  (regional log buckets + `_Default` sink on GCP), not assumed automatic — an
  infrastructure-slice task with acceptance evidence.
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
| Idle (~0 traffic) | **~$24/mo** edge floor (HTTPS LB ~$18/mo + Cloud Armor ~$5–6/mo) + ≈ `$0` compute `[confirm]` | **≈ `$0`** (API Gateway has no fixed floor; ECR storage cents) | edge floor (Front Door/APIM) + ≈ `$0` compute within grant |
| Normal (light/bursty) | `$0`–single-digit `$` (free tier likely covers) | `$0`–low `$` | `$0`–a few `$` (companions dominate) |
| Abusive (hammered) | soft `max-instances` + Cloud Armor rate limit + budget kill-switch (no hard cap) | reserved concurrency caps **Lambda compute** (hard); API Gateway throttling is **best-effort**, not a cost cap | bounded by `maxReplicas` (hard at compute) |

- **Fixed vs variable:** compute is variable (scale-to-zero) on all three. The
  **Cloud Run baseline's main fixed cost is the rate-limiting edge** — an external
  HTTPS LB + Cloud Armor at ≈ **$24/mo** before traffic — which is modest and
  bounded. (AWS Lambda would avoid this fixed floor since API Gateway has no fixed
  monthly cost, but its gateway throttling is **best-effort, not a cost cap**, and
  it needs per-row fan-out to fit the 15-min limit — so it is an alternative, not
  the baseline; §1.) Companions (secret store, tiny stores, registry storage) are
  cents.
- **Bounded spend rate, not a hard cap:** **no platform offers a hard spend cap,
  and on Cloud Run `max-instances` is a soft cap that may be briefly exceeded
  during traffic spikes** (and is complicated by traffic split across revisions).
  So the design bounds the *rate* of spend, it does not purchase a ceiling: a
  deliberately low instance/concurrency cap **+** the edge rate limit **+** a
  budget-alert → automation kill-switch. Because budget alerts lag (often hours),
  the **worst-case overrun** before the kill-switch fires is roughly
  `instance_cap × per-instance cost-rate × (budget-alert lag + kill-switch exec
  time)` — a bounded but non-zero window the maintainer must accept. (Lambda's
  reserved concurrency and ACA's `maxReplicas` are harder ceilings **at the compute
  boundary only**; Lambda's API Gateway throttling is best-effort, not a hard cost
  cap; Cloud Run's `max-instances` is softer. None is a hard spend cap.) Detail +
  numbers to confirm:
  [`hosted-deployment-cost-envelope.md`](hosted-deployment-cost-envelope.md).
- **Maintainer-confirm before provisioning:** the spend ceiling value, the budget
  alert threshold, the edge/LB fixed cost, and the exact free-tier/region rates
  (these shift; verify in the provider calculator).

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
| Provider | Google Cloud Run | Azure ACA; AWS Lambda (needs fan-out) | Container API + long-running container worker (no 15-min ceiling) fits long batch verify; modest bounded edge floor; runs the container unchanged | High (portable OCI image) | Low | ~$24/mo edge floor + per-use | Accept provider (ACA/Lambda are documented alternatives) |
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
