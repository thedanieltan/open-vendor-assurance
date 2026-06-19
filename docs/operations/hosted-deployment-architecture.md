# Hosted public-read deployment architecture

The deployable-system architecture for the bounded hosted resolver permitted by
[ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)
and decided by [ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md).
Decision rationale: [`hosted-deployment-decision.md`](hosted-deployment-decision.md).
Contract: [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Decision-only.** Nothing here is provisioned and no hosted endpoint is live.
OpenVA stays public-source-only and metadata-first; it does not provide legal or
vendor-risk advice, never handles private or gated source material, and stores no
raw vendor documents. The hosted service **transiently processes the
customer-specific vendor identities a caller submits** but never publishes, logs,
retains, reuses, or incorporates that input into canonical catalogue records.

## Components

| Component | Responsibility | Hosted boundary |
| --- | --- | --- |
| `edge_gateway` | HTTPS load balancer + rate limiting (e.g. Cloud Armor) in front of the API | Origin ingress restricted to the edge so direct ingress cannot bypass rate limits; CORS allow-list |
| `public_api` | FastAPI `/v1` read + enrich + `/healthz` + `/readyz`; cached mode answers from the pinned pack with no egress | Non-advisory headers on every response; reachable only via the edge |
| `resolver_app` | The already-merged `vendor_resolution` core wrapped by the transport; no second resolver | Writes nothing to `data/**` or `main` |
| `async_worker` | Executes `verify`-mode jobs: re-reads the request envelope, then bounded SSRF-safe fetch + discovery | Egress only via `build_safe_verify_fetcher` bound to vendor authority |
| `queue` | Dispatches jobs API→worker with retry/backoff | Carries `job_id` only — **no submitted content, no envelope** |
| `transient_request_store` | Holds the submitted-input envelope between API receipt and worker execution, keyed by `job_id` | Encrypted at rest; workload-identity least privilege (API writes, worker reads); deleted on terminal + TTL backstop |
| `durable_job_store` | Operational job metadata, TTL-deleted | `hosted-job-record.schema.json`; minimised; never uploaded content |
| `transient_result_store` | Holds the result blob (`result_ref`), retrieved only with the `job_token` capability | Transient; TTL/expiry-deleted; never indexed by submitted content |
| `static_cached_fallback` | GitHub Pages exports + static MCP + pinned pack | Canonical, reproducible, **independent of the host**; always-on floor |
| `candidate_ingress_boundary` | Proposes discovered candidates into the existing PR-bound lifecycle | Discovery only; no decision/merge authority |
| `health_readiness` | `/healthz` (liveness), `/readyz` (200 only when pack loaded + integrity verified) | Unauthenticated; no content |
| `admin_kill_switch` | Disables verify + ingress; static read keeps serving | Maintainer-operated; independent of read path |

## Request flows

**Cached read (`freshness_mode: cached`)** — synchronous, no egress:
`client → public_api → resolver_app (pinned pack) → response (not_advice, from_cache labelled)`.

**Live verify (`freshness_mode: verify`)** — asynchronous:
1. `public_api` validates limits, writes the submitted input to
   `transient_request_store` (referenced by `request_ref`), creates a **new**
   `received` job (one per request — **no deduplication in v1**), enqueues **only
   the `job_id`** (task name = `job_id`), CAS `received → queued` after the enqueue
   ack, and returns the `job_id` plus a one-time `job_token` capability.
2. `async_worker` dequeues the `job_id` → `executing` → **re-reads the request
   envelope** (workload identity) → SSRF-safe fetch/discovery via the resolver →
   writes the transient result, sets `completed`/`failed`, and **deletes the
   request envelope**.
3. `client` polls with `job_id` + `job_token`; the API distinguishes `received`
   (accepted, not yet dispatched) from `queued` (dispatched). On `completed` it
   retrieves the result via `result_ref`. After `expires_at` the API returns
   `410 Gone`; the record, envelope, and result blob are deleted by TTL/lifecycle.
4. Discovered candidates are *proposed* through `candidate_ingress_boundary` →
   existing durable ingress → PR lifecycle. The hosted service never merges.

**Consistency and recovery.** The three durable steps (write envelope → create
`received` job → enqueue `job_id`) follow one exact CAS protocol: **the API owns
the normal `received → queued`** (after the enqueue ack; task name = `job_id` so
re-enqueue is a no-op); the **worker** does CAS `{received | queued} → executing`
(tolerating a record still in `received`, with duplicate deliveries acked-and-
dropped); the **reconciler is recovery-only** and merely re-enqueues jobs stuck in
`received` (it never owns the normal transition); an orphan envelope (job-create
failed) is invisible to clients and TTL-reaped while the API returns a generic
retryable `503`. Full per-crash-point rules: the lifecycle spec.

**Degraded** — request/result store, queue, or worker unavailable → `public_api`
serves cached/static labelled results; verify returns `queued`/`rate_limited`/cached,
never stale-as-live.

## Separation of duties

Discovery (resolver/worker) ≠ decision (independent quorum/controller) ≠ merge
(`pr_safety`). The hosted service occupies the **discovery** role only. There is
exactly one catalogue mutation path (the PR lifecycle), and it is not the resolver.

## Statelessness and the static floor

The API and worker are stateless; all durable state is the TTL job store plus the
git catalogue. The static layer (Pages exports, static MCP, pinned pack) is the
canonical reproducible layer and keeps working when the hosted service is down —
the terminal safe state is "hosted disabled, static layer serving."

## Portability

The deployable is a standard OCI image; the only provider-specific surface is a
thin adapter at the `edge_gateway`, `queue`, and store boundary. **Baseline (Google
Cloud Run):** a container API **and a long-running container worker** (no
invocation ceiling — bounded by the per-job execution timeout + row cap), behind an
external HTTPS LB + Cloud Armor (the rate-limiting edge; ~$24/mo fixed floor), with
Cloud Tasks + Firestore TTL + Secret Manager + Workload Identity. The worker is a
**container** precisely because verify is long-running batch work (up to 500 rows
of live fetch) that a 15-minute function model could not bound without per-row
fan-out. **Alternatives:** Azure Container Apps (container worker; Key Vault remote
signing); or AWS Lambda, which is `$0`-idle but **requires per-row fan-out +
aggregation** to fit the 15-min ceiling and whose API Gateway throttling is
best-effort (not a hard cost cap). Lock-in stays bounded to the adapter; rollback
to a prior image is clean on all three. No provider offers a hard spend cap, so the
bounded-spend-rate controls apply regardless of provider.

## Topology diagram

See the diagram in [`hosted-deployment-decision.md` §3](hosted-deployment-decision.md).
