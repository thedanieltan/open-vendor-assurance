# Hosted public-read deployment architecture

The deployable-system architecture for the bounded hosted resolver permitted by
[ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)
and decided by [ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md).
Decision rationale: [`hosted-deployment-decision.md`](hosted-deployment-decision.md).
Contract: [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Decision-only.** Nothing here is provisioned and no hosted endpoint is live.
OpenVA stays public-source-only and metadata-first; it does not provide legal or
vendor-risk advice, handles no private or gated or customer-specific material, and
stores no raw vendor documents.

## Components

| Component | Responsibility | Hosted boundary |
| --- | --- | --- |
| `public_api` | FastAPI `/v1` read + enrich + `/healthz` + `/readyz`; cached mode answers from the pinned pack with no egress | Non-advisory headers on every response; CORS allow-list; rate limited |
| `resolver_app` | The already-merged `vendor_resolution` core wrapped by the transport; no second resolver | Writes nothing to `data/**` or `main` |
| `async_worker` | Executes `verify`-mode jobs: bounded SSRF-safe fetch + discovery | Egress only via `build_safe_verify_fetcher` bound to vendor authority |
| `queue` | Dispatches jobs API→worker with retry/backoff | Bounded concurrency; no submitted content in messages (carries `job_id`) |
| `durable_job_store` | Operational job/result metadata, TTL-deleted | `hosted-job-record.schema.json`; minimised; never uploaded content |
| `static_cached_fallback` | GitHub Pages exports + static MCP + pinned pack | Canonical, reproducible, **independent of the host**; always-on floor |
| `candidate_ingress_boundary` | Proposes discovered candidates into the existing PR-bound lifecycle | Discovery only; no decision/merge authority |
| `health_readiness` | `/healthz` (liveness), `/readyz` (200 only when pack loaded + integrity verified) | Unauthenticated; no content |
| `admin_kill_switch` | Disables verify + ingress; static read keeps serving | Maintainer-operated; independent of read path |

## Request flows

**Cached read (`freshness_mode: cached`)** — synchronous, no egress:
`client → public_api → resolver_app (pinned pack) → response (not_advice, from_cache labelled)`.

**Live verify (`freshness_mode: verify`)** — asynchronous:
1. `public_api` validates limits, computes `request_digest`, creates a `received`
   job (idempotent on digest), enqueues it, returns the `job_id`.
2. `async_worker` dequeues → `executing` → SSRF-safe fetch/discovery via the
   resolver → writes the transient result, sets `completed`/`failed`.
3. `client` polls `job_id`; on `completed`, reads the result via `result_ref`.
4. Discovered candidates are *proposed* through `candidate_ingress_boundary` →
   existing durable ingress → PR lifecycle. The hosted service never merges.

**Degraded** — store/queue/worker unavailable → `public_api` serves cached/static
labelled results; verify returns `queued`/`rate_limited`/cached, never stale-as-live.

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
thin adapter at the `queue` and `durable_job_store` boundary (Cloud Tasks +
Firestore for the baseline; SQS + DynamoDB or Service Bus + Cosmos for the
alternatives). This keeps lock-in low and rollback to a prior image clean.

## Topology diagram

See the diagram in [`hosted-deployment-decision.md` §3](hosted-deployment-decision.md).
