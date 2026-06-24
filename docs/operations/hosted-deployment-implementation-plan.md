# Hosted deployment implementation plan

The dependency-ordered follow-on slices for the accepted
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)
deployment architecture (governed by [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)).
Each slice is independently reviewable. The machine-readable slice list +
dependencies (and the per-slice `status`) live in
[`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Decision-only for the un-provisioned infrastructure.** No infrastructure is
provisioned by this plan; no production endpoint is live. The completed in-repo
slices below shipped only provider-neutral, off-by-default application code. OpenVA
stays non-advisory (`not_advice: true`), public-source-only, and metadata-first; it
does not provide legal or vendor-risk advice and stores no raw vendor documents.

Authority levels follow `docs/operations/contracts/bot-authority.yaml` (0 report-only,
1 evidence-authorship/PR, 4 merge). The hosted service operates in the **discovery**
role only; decision and merge stay with the existing independent components.

## Programme state

The decision package (issue #401, WP-OPENVA-AI-NATIVE-DISTRIBUTION-02) is complete and
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md) is
**Accepted**. The entire provider-neutral application path is now **complete and
merged**: **WP-02A** (hosted transport) and **WP-02L** (positioning, in lockstep —
PR #408), **WP-02B** (async persistence — PR #410), **WP-02C** (worker + queue —
PR #415), **WP-02D** (candidate ingress — PR #416), **WP-02H** (application hardening —
PR #417), **WP-02I** (remote MCP — PR #418), **WP-02J** (live `/check` — PR #419), and
**WP-02E** (deployment artifact + supply-chain — PR #422). **No provider-neutral slice
remains startable.** What remains is the maintainer-gated infrastructure chain
(**WP-02F** staging → **WP-02G** production → **WP-02K** launch evidence + programme
closeout), which additionally requires the single maintainer external-decision block
(provider/region/domain/credentials/spend) requested once before WP-02F, plus real
provisioning.

## Slice summary

| Slice | Depends on | Authority | Provisions infra? | Status |
| --- | --- | --- | --- | --- |
| WP-02A hosted transport + API contract | — | 1 | No (code) | completed |
| WP-02L positioning reconciliation | 02A | 1 (human-reviewed) | No (docs) | completed |
| WP-02B async job/result persistence | 02A | 1 | No (code) | completed |
| WP-02C worker + queue execution | 02B | 1 | No (code) | completed |
| WP-02E deployment artifact + supply-chain | 02A | 1 | No (CI/artifact) | completed |
| WP-02D candidate-ingress integration | 02C | 1 | No (code) | completed |
| WP-02H application hardening (provider-neutral) | 02C | 1 | No (code) | completed |
| WP-02I remote MCP resolver activation | 02D, 02H | 1 | No (code) | completed |
| WP-02J live `/check` integration | 02I | 1 | No (code) | completed |
| WP-02F staging environment | 02E, 02J | maintainer | **Yes (staging)** | infra-gated |
| WP-02G production infrastructure | 02F | maintainer | **Yes (prod)** | infra-gated |
| WP-02K production smokes + launch evidence + closeout | 02G | maintainer | evidence | infra-gated |

Slices WP-02F, WP-02G, and the infra parts of WP-02K **require the
maintainer-accepted external decisions** (provider, region, domain, credentials,
spend ceiling, permissions), requested **once** before staging (WP-02F). They fail
closed until those are made. WP-02H is now **provider-neutral application hardening**
that lands before staging — its provider-specific edge enforcement, alert routing,
dashboards, and cloud configuration moved to WP-02F/WP-02G acceptance.

## Cross-cutting execution constraints

These hold across every remaining slice (they are properties of *how* the work is
built, not a separate work package or operating mode; the machine-readable form is
`cross_cutting_execution_constraints` in the contract):

- **Provider-neutral code before infrastructure.** All WP-02C..02J application code
  lands and is reviewed before any external provisioning (WP-02F onward).
- **Hosted capabilities disabled by default.** The verify/worker/transport paths ship
  behind an off-by-default flag; the default build changes no runtime behaviour.
- **Deterministic local test paths.** Local/in-memory/SQLite implementations let every
  test run with no cloud provider, account, or network egress.
- **Queue, store, and telemetry behind provider interfaces** — one in-memory
  implementation plus a provider implementation, selected by configuration.
- **No external provisioning before WP-02F:** no provider account, DNS, TLS, production
  secrets, paid registry publication, or public endpoint before staging.
- **The static layer is unaffected** — the static catalogue, static MCP, and cached
  operation keep working throughout, including when the hosted service is absent.
- **External decisions stay maintainer-controlled** — provider, region, domain,
  credentials, and spend are a single maintainer decision block requested once,
  immediately before WP-02F.

## Per-slice specification

### WP-02A — Hosted transport + API contract
- **Inputs:** the merged resolver core; ADR-0001/0006; the match-service contract.
- **Outputs:** the `/v1` verify transport over the existing FastAPI service (job
  create returns `job_id` + a one-time `job_token`; poll retrieves the result with
  the `job_token` sent **header-only** as `Authorization: Bearer <job_token>` —
  never in the URL/query/path/redirect — verified by **constant-time** digest
  comparison and redacted in logs), the revised match-service contract acknowledging
  persistence + egress (in lockstep, per ADR-0001), and the API contract doc.
- **Allowed paths:** `services/openva_match_service/**`, `docs/openva-match-service-contract.md`, `docs/resolver-api.md`, `tests/**`.
- **Non-goals:** persistence backend, worker, deployment.
- **Tests:** contract tests for job-create/poll shapes; **`job_token` accepted only via the `Authorization: Bearer` header** (query-string/path/redirect rejected); constant-time digest comparison; generic auth-failure with no token echo; non-advisory headers on every response; CORS allow-list; body/row limits; **SSRF-negative**.
- **Rollback:** transport behind a flag; off → cached-only synchronous service.
- **Acceptance evidence:** CI green; ADR-0001 six gates demonstrably preserved.

### WP-02B — Async job/result persistence
- **Inputs:** WP-02A; `schemas/openva/hosted-job-record.schema.json`; the job-lifecycle spec.
- **Outputs:** the transient request-envelope store, the durable job store, and the transient result store behind interfaces (in-memory + one provider impl); TTL enforcement + three-phase `410`/`404` expiry; the schema-enforced state machine **incl. the execution-lease invariants** (executing requires `lease_owner` + `lease_expires_at`); the **actor-scoped handoff protocol** (API owns normal `received→queued`; CAS transitions per the `access_matrix`; **recovery-only reconciler** for stuck `received`; the **watchdog** stale-lease recovery `executing→queued|failed`; orphan-envelope cleanup); **no deduplication in v1**.
- **Allowed paths:** `services/openva_match_service/**`, `schemas/openva/**`, `tests/**`.
- **Non-goals:** the worker fetch logic; provider provisioning; any request deduplication.
- **Tests:** schema validation incl. **state-invariant negative cases** (`completed` w/o `result_ref`, `failed` w/o `error_code`, terminal retaining `request_ref`, non-terminal w/o envelope, `executing` w/o lease, lease set in a non-executing state, `cached` job — all rejected); illegal-transition + unauthorized-actor rejection; three-phase expiry (`410` retained → `404` deleted); **new-job-per-request**; handoff recovery at each crash point (envelope/job/enqueue, duplicate delivery acked-and-dropped); **watchdog stale-lease recovery** (worker dies → lease expires → exactly one component recovers/terminalizes); **minimisation**.
- **Rollback:** disable verify → store unused; cached mode unaffected.
- **Acceptance evidence:** CI green; records + negative cases validate as expected; recovery + minimisation tests pass.

### WP-02C — Worker + queue execution
- **Inputs:** WP-02B; the SSRF-safe fetch boundary.
- **Outputs:** the async worker as a **Cloud Run service handler invoked by Cloud Tasks** (concrete, bounded by the **grounded `verify_execution_budget`**: `max_verify_rows 20` × up to 4 serial fetches/source-type at `per_fetch_deadline_seconds 20` = `SAFE_TIMEOUT_SECONDS`, `verify_row_concurrency 10` → worst case ~12 min < the per-job timeout < the 30-min Cloud Tasks dispatch deadline) that re-reads the envelope by `job_id`, does the recovery CAS `received→queued` then `queued→executing`, **takes + heartbeats the execution lease**, then `executing→completed|failed`, and acks-and-drops duplicate deliveries; the **watchdog** (stale-lease recovery); plus a queue adapter behind an interface; `attempt` retries.
- **Allowed paths:** `services/openva_match_service/**`, `tools/openva/**` (read-only reuse), `tests/**`.
- **Non-goals:** candidate write-back; deployment. (A **larger verify limit** is a separate future WP needing a full parent/child decomposition — Cloud Run Jobs + a Cloud Tasks launcher is the likely vehicle for *that* WP — not a hand-waved scale-up here. The 500-row figure is the *cached* batch, which does no live fetch.)
- **Tests:** worker re-reads the envelope + executes via the resolver; **SSRF-negative**; **`verify_execution_budget` recomputed from the imported resolver constants** (`per_fetch_deadline_seconds == SAFE_TIMEOUT_SECONDS`; `network_ops_per_source_type_worst >= 1 + max len(_DISCOVERY_PATHS)`; worst case < per-job timeout < dispatch deadline); lease heartbeat extends; **watchdog recovers a stale lease** (`executing→queued` re-dispatch / `executing→failed` timeout); live lease not preempted; recovery CAS `received→queued→executing`; duplicate-delivery CAS dropped; no partial `completed`.
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
- **Inputs:** WP-02E, WP-02J (the full provider-neutral application path is complete
  and hardened before any host exists); **the single maintainer external-decision
  block** (provider, region, staging domain, staging secrets), requested once here.
- **Outputs:** a deployed staging service on a maintainer-owned staging host, plus the
  **provider-specific controls moved out of WP-02H**: edge/WAF rate-limit enforcement,
  alert routing, and SLO dashboards wired to the application's metrics/log interfaces,
  and the cloud configuration that realises them in staging.
- **Allowed paths:** infra config (maintainer-owned), `docs/operations/**`.
- **Authority:** maintainer (provisions infra, creates staging secrets).
- **Non-goals:** production; public traffic.
- **Tests:** staging smokes A/B/C; kill-switch; degradation; edge rate-limit enforced;
  alerts route; dashboards populated from the application signals.
- **Rollback:** tear down staging; static layer unaffected.
- **Acceptance evidence:** staging smoke evidence recorded; edge enforcement + alert
  routing + dashboards demonstrated in staging.

### WP-02G — Production infrastructure
- **Inputs:** WP-02F; **maintainer external decisions** (production provider/region/domain/secrets/permissions/spend ceiling).
- **Outputs:** production service (not yet public), separate prod secrets/identity with the GitHub App key **isolated to the candidate-ingress component** (API/worker hold none), explicit **regional log buckets + `_Default` sink** so logs stay in the primary region (not automatic on GCP), the engineered cost ceiling (instance cap + rate limit + budget-alert kill-switch), and the **production realisation of the provider-specific edge enforcement, alert routing, and SLO dashboards** (same controls proven in staging, now in production).
- **Authority:** maintainer.
- **Non-goals:** enabling public traffic (WP-02K).
- **Tests:** prod health/readiness; least-privilege + credential-isolation check (API/worker have no GitHub credential); log-residency check; cost-ceiling controls present; edge enforcement + alert routing + dashboards live in production.
- **Rollback:** disable transport; revoke credentials; static layer serving.
- **Acceptance evidence:** prod stood up, traffic disabled, credential isolation + regional logs + cost controls + edge/alert/dashboard controls verified.

### WP-02H — Application hardening (provider-neutral)
- **Inputs:** WP-02C; the observability spec. **Depends on WP-02C and may run in
  parallel with WP-02D.** Lands BEFORE staging.
- **Outputs:** the provider-neutral application controls, all behind interfaces so no
  cloud provider is required to build or test them:
  - telemetry field **prohibition + redaction** honouring `prohibited_telemetry_fields`
    (request body, vendor identity, inventory row, `Authorization` header, `job_token`, …);
  - **structured logging and metrics interfaces** (one in-memory/stdout implementation;
    a provider exporter is wired at WP-02F/02G);
  - **application request and concurrency limits** (body/row caps, in-process concurrency);
  - a **rate-limit / abuse-control policy** expressed at the application layer;
  - **cost-exhaustion protection behaviour** (bounded work per job/instance so a flood
    cannot run away before the edge/budget controls exist);
  - **kill-switch behaviour** (an application flag that fail-closes verify/worker to
    cached-only);
  - **leakage and negative tests**.
- **Allowed paths:** `services/openva_match_service/**`, `docs/operations/**`, `tests/**`.
- **Non-goals:** advisory analytics; content logging; **provider-specific edge
  enforcement, alert routing, SLO dashboards, and cloud configuration** — those are
  WP-02F/WP-02G acceptance criteria, not this slice.
- **Tests:** **leakage tests** (no prohibited field in any signal, deterministic/local);
  request + concurrency limits enforced; rate-limit policy unit tests; kill-switch
  fail-closes to cached-only; cost-exhaustion bound holds.
- **Rollback:** controls are additive and default-off where they change behaviour;
  disabling reverts to the prior caps; cached mode unaffected.
- **Acceptance evidence:** CI green; leakage tests green with no provider dependency.

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

### WP-02K — Production smokes + launch evidence + programme closeout
- **Inputs:** WP-02G (WP-02J — the live `/check` path — is already in WP-02G's
  dependency closure); **maintainer** enables public traffic.
- **Outputs:** the launch-evidence-then-go-live sequence AND the WP-02 programme
  closeout:
  - recorded **production smoke evidence** (A/B/C);
  - **rollback and kill-switch drills** performed and recorded;
  - **public-traffic enablement only after** the evidence exists (never before);
  - the **hosted-live positioning update** (the docs/READMEs may state the service is
    live only once smoke evidence exists — the inverse of today's "no production
    endpoint" wording);
  - **release/tag evidence** for the deployed build (digest-pinned);
  - the **roadmap final-state update** recording the hosted service as live; and
  - **closure of the hosted-deployment programme** (WP-OPENVA-AI-NATIVE-DISTRIBUTION-02).
- **Authority:** maintainer.
- **Non-goals:** any live claim before evidence exists.
- **Tests:** production smokes A/B/C; rollback drill; kill-switch drill.
- **Rollback:** disable public traffic; static layer serving.
- **Acceptance evidence:** smoke evidence record + drills; only then may docs state the
  service is live; release/tag + roadmap final-state recorded; programme closed.

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

The full provider-neutral application path is **complete and merged**: 02A (+02L in
lockstep), 02B, 02C, 02D, 02E (deployment artifact + supply-chain), 02H (application
hardening), 02I, and 02J (live `/check`). **No provider-neutral slice remains startable.**
Only the maintainer-gated infrastructure chain remains: staging 02F (after 02E + 02J) →
production 02G → 02K (production smokes, launch evidence, and programme closeout). The
single maintainer external-decision block is requested once, immediately before 02F, and
real provisioning happens there. No slice claims the service is live until WP-02K's
evidence exists.
