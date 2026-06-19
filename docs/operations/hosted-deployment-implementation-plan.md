# Hosted deployment implementation plan

The dependency-ordered follow-on slices that become executable after a maintainer
accepts [ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)
(governed by [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)).
Each slice is independently reviewable. The machine-readable slice list +
dependencies live in [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Decision-only.** Nothing here is built or provisioned. Each slice carries its
own acceptance tests and rollback. OpenVA stays non-advisory (`not_advice: true`),
public-source-only, and metadata-first; it does not provide legal or vendor-risk
advice and stores no raw vendor documents.

Authority levels follow `docs/operations/contracts/bot-authority.yaml` (0 report-only,
1 evidence-authorship/PR, 4 merge). The hosted service operates in the **discovery**
role only; decision and merge stay with the existing independent components.

## Slice summary

| Slice | Depends on | Authority | Provisions infra? |
| --- | --- | --- | --- |
| WP-02A hosted transport + API contract | — | 1 | No (code) |
| WP-02B async job/result persistence | 02A | 1 | No (code) |
| WP-02C worker + queue execution | 02B | 1 | No (code) |
| WP-02D candidate-ingress integration | 02C | 1 | No (code) |
| WP-02E deployment artifact + supply-chain | 02A | 1 | No (CI/artifact) |
| WP-02F staging environment | 02E, 02C | maintainer | **Yes (staging)** |
| WP-02G production infrastructure | 02F | maintainer | **Yes (prod)** |
| WP-02H observability + abuse controls | 02F | 1 / maintainer | partial |
| WP-02I remote MCP resolver activation | 02D, 02H | 1 | No (code) |
| WP-02J live `/check` integration | 02I | 1 | No (code) |
| WP-02K production smokes + launch evidence | 02G, 02J | maintainer | evidence |
| WP-02L positioning reconciliation | 02A | 1 (human-reviewed) | No (docs) |

Slices WP-02F, WP-02G, and the infra parts of WP-02H/WP-02K **require the
maintainer-accepted external decisions** (provider, region, domain, credentials,
spend ceiling, permissions). They fail closed until those are made.

## Per-slice specification

### WP-02A — Hosted transport + API contract
- **Inputs:** the merged resolver core; ADR-0001/0006; the match-service contract.
- **Outputs:** the `/v1` verify transport over the existing FastAPI service (job
  create + poll), the revised match-service contract acknowledging persistence +
  egress (in lockstep, per ADR-0001), and the API contract doc.
- **Allowed paths:** `services/openva_match_service/**`, `docs/openva-match-service-contract.md`, `docs/resolver-api.md`, `tests/**`.
- **Non-goals:** persistence backend, worker, deployment.
- **Tests:** contract tests for job-create/poll shapes; non-advisory headers on every response; CORS allow-list; body/row limits; **SSRF-negative**.
- **Rollback:** transport behind a flag; off → cached-only synchronous service.
- **Acceptance evidence:** CI green; ADR-0001 six gates demonstrably preserved.

### WP-02B — Async job/result persistence
- **Inputs:** WP-02A; `schemas/openva/hosted-job-record.schema.json`; the job-lifecycle spec.
- **Outputs:** the transient request-envelope store, the durable job store, and the transient result store behind interfaces (in-memory + one provider impl); TTL enforcement + `expires_at`→`410` expiry; the schema-enforced state machine; the **handoff protocol** (API owns normal `received→queued` after enqueue ack; idempotent task name; CAS transitions; **recovery-only reconciler** for stuck `received`; orphan-envelope cleanup); **no deduplication in v1** (new job per request).
- **Allowed paths:** `services/openva_match_service/**`, `schemas/openva/**`, `tests/**`.
- **Non-goals:** the worker; provider provisioning; any request deduplication.
- **Tests:** schema validation incl. **state-invariant negative cases** (`completed` w/o `result_ref`, `failed` w/o `error_code`, terminal retaining `request_ref`, non-terminal w/o envelope, `cached` job — all rejected); illegal-transition rejection; `410`/TTL expiry of record + envelope + result; **new-job-per-request** (no dedup key persisted); handoff recovery at each crash point (envelope/job/enqueue, duplicate delivery acked-and-dropped); **minimisation** (no submitted content persisted).
- **Rollback:** disable verify → store unused; cached mode unaffected.
- **Acceptance evidence:** CI green; records + negative cases validate as expected; recovery + minimisation tests pass.

### WP-02C — Worker + queue execution
- **Inputs:** WP-02B; the SSRF-safe fetch boundary.
- **Outputs:** the async worker as a **long-running container** (no invocation ceiling; one job processes the whole ≤500-row batch, bounded by a per-job execution timeout) that re-reads the request envelope by `job_id`, does CAS `{received|queued}→executing` then `executing→completed|failed`, and acks-and-drops duplicate deliveries; plus a queue adapter behind an interface; bounded concurrency + `attempt` retries.
- **Allowed paths:** `services/openva_match_service/**`, `tools/openva/**` (read-only reuse), `tests/**`.
- **Non-goals:** candidate write-back; deployment. (A serverless AWS-Lambda variant is out of scope for the baseline — it would need a separate per-row fan-out + aggregation sub-slice to fit the 15-min ceiling.)
- **Tests:** worker re-reads the envelope + executes via the resolver; **SSRF-negative**; concurrency cap; per-job execution timeout → `failed` (`execution_timeout`); duplicate-delivery CAS dropped; no partial `completed`.
- **Rollback:** disable worker → verify returns `queued`/cached; no stale-as-live.
- **Acceptance evidence:** CI green; degradation honest; CAS protocol exercised.

### WP-02D — Candidate-ingress integration
- **Inputs:** WP-02C; the existing durable ingress + PR-bound candidate lifecycle.
- **Outputs:** discovered candidates *proposed* via the existing ingress from the hosted path; **no** decision/merge authority.
- **Allowed paths:** `services/openva_match_service/**`, `tools/openva/**` (reuse), `tests/**`.
- **Non-goals:** any `data/**` or `main` write; deciding/merging.
- **Tests:** discovery-only boundary (no catalogue write); separation of duties; uses the existing ingress, not a second path.
- **Rollback:** disable ingress → return source results, mark catalogue update pending.
- **Acceptance evidence:** CI green; no catalogue mutation path introduced.

### WP-02E — Deployment artifact + supply-chain controls
- **Inputs:** the existing Dockerfile; WP-02A.
- **Outputs:** immutable OCI build, SBOM, build provenance, image + dependency scanning, digest-pinned release flow.
- **Allowed paths:** `services/openva_match_service/**`, `.github/workflows/**`, `docs/operations/**`.
- **Non-goals:** registry creation (maintainer); deployment.
- **Tests:** build reproducibility; scan gate; provenance present; pinned base.
- **Rollback:** deploy the prior immutable digest.
- **Acceptance evidence:** CI green; SBOM + provenance artifacts produced.

### WP-02F — Staging environment
- **Inputs:** WP-02E, WP-02C; **maintainer external decisions** (provider, region, staging domain, staging secrets).
- **Outputs:** a deployed staging service on a maintainer-owned staging host.
- **Allowed paths:** infra config (maintainer-owned), `docs/operations/**`.
- **Authority:** maintainer (provisions infra, creates staging secrets).
- **Non-goals:** production; public traffic.
- **Tests:** staging smokes A/B/C; kill-switch; degradation.
- **Rollback:** tear down staging; static layer unaffected.
- **Acceptance evidence:** staging smoke evidence recorded.

### WP-02G — Production infrastructure
- **Inputs:** WP-02F; **maintainer external decisions** (production provider/region/domain/secrets/permissions/spend ceiling).
- **Outputs:** production service (not yet public), separate prod secrets/identity, the engineered cost ceiling (instance cap + rate limit + budget-alert kill-switch).
- **Authority:** maintainer.
- **Non-goals:** enabling public traffic (WP-02K).
- **Tests:** prod health/readiness; least-privilege check; cost-ceiling controls present.
- **Rollback:** disable transport; revoke credentials; static layer serving.
- **Acceptance evidence:** prod stood up, traffic disabled, cost controls verified.

### WP-02H — Observability + abuse controls
- **Inputs:** WP-02F; the observability spec.
- **Outputs:** logs/metrics/traces/alerts honouring `prohibited_telemetry_fields`; rate limiting; SLO dashboards; cost/abuse alerts → kill-switch.
- **Allowed paths:** `services/openva_match_service/**`, infra config, `docs/operations/**`, `tests/**`.
- **Non-goals:** advisory analytics; content logging.
- **Tests:** **leakage tests** (no prohibited field in any signal); rate-limit; alert routing.
- **Rollback:** alerting/limits are additive; disabling reverts to prior caps.
- **Acceptance evidence:** leakage tests green; alerts fire in staging.

### WP-02I — Remote MCP resolver activation
- **Inputs:** WP-02D, WP-02H; ADR-0003 remote MCP surface.
- **Outputs:** live MCP `resolve_*` tools over the hosted transport (read-only, bounded), reusing the existing MCP registry.
- **Allowed paths:** `integrations/mcp/**`, `services/openva_match_service/**`, `tests/**`.
- **Non-goals:** workspace credentials; write tools.
- **Tests:** MCP hardening/threat-model tests; non-advisory; no arbitrary-URL tool.
- **Rollback:** disable live MCP → static MCP remains canonical.
- **Acceptance evidence:** CI green; static MCP unaffected.

### WP-02J — Live `/check` integration
- **Inputs:** WP-02I.
- **Outputs:** the public `/check` live verify mode over `/v1`.
- **Allowed paths:** `services/openva_match_service/**`, `docs/**`, `tests/**`.
- **Non-goals:** advisory output; persistence beyond the TTL store.
- **Tests:** cached-vs-verify labelling; honest degradation; SSRF-negative.
- **Rollback:** disable `/check` → cached read remains.
- **Acceptance evidence:** CI green; labelling explicit.

### WP-02K — Production smokes + launch evidence
- **Inputs:** WP-02G, WP-02J; **maintainer** enables public traffic.
- **Outputs:** recorded production smoke evidence (A/B/C), then public traffic enabled.
- **Authority:** maintainer.
- **Non-goals:** any live claim before evidence exists.
- **Tests:** production smokes A/B/C; rollback drill; kill-switch drill.
- **Rollback:** disable public traffic; static layer serving.
- **Acceptance evidence:** smoke evidence record; only then may docs state the service is live.

### WP-02L — Positioning reconciliation
- **Inputs:** WP-02A (first transport merge); ADR-0001 positioning table.
- **Outputs:** the seven positioning files revised in lockstep with the first
  transport merge, **preserving the seven required limitation phrases verbatim**
  (public-source-only, metadata-first, does not provide legal, vendor-risk advice,
  private or gated, customer-specific, raw vendor documents).
- **Allowed paths:** the seven files in ADR-0001's positioning table; `docs/**`.
- **Authority:** 1, human-reviewed (positioning is maintainer governance).
- **Non-goals:** revising positioning before the transport actually ships.
- **Tests:** release-smoke limitation-phrase gate; doc-drift tests.
- **Rollback:** revert the doc change with the transport revert.
- **Acceptance evidence:** release-smoke green; narrative matches shipped behaviour.

## Sequencing

02A→02B→02C→02D unlock the code path; 02E→02F→02G stand up infra (maintainer-gated);
02H hardens; 02I→02J light up MCP + live `/check`; 02K records launch evidence;
02L reconciles positioning in lockstep with 02A's merge. No slice claims the
service is live until WP-02K's evidence exists.
