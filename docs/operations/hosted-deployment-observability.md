# Hosted deployment observability and service-level specification

Observability and service-level specification for OpenVA's **bounded hosted
resolver**. It expands §9 (Observability) and §10 (Availability) of the
[hosted-deployment decision](hosted-deployment-decision.md) into signal-level
detail, SLIs/SLOs, alert routing, and the cost/abuse monitoring that feeds the
kill-switch.

**This is a decision/specification only.** Nothing here is deployed, provisioned,
live, or monitored today. There is no hosted endpoint, no dashboard, no alert
channel, and no telemetry pipeline. Every statement is **future framing** of how
observability *would* be wired once a maintainer accepts
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)
and provisions the workload. Product posture is governed by
[ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md);
the machine-readable contract is
[`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Non-advisory posture.** `not_advice: true`. OpenVA is a public-source-only,
metadata-first registry of vendor-published assurance references. Observability
signals never carry submitted content and never alter that posture: OpenVA does
not provide legal, compliance, or vendor-risk advice, and telemetry exists only to
keep the bounded read service honest, available, and within its cost envelope.

## 1. Signals

Four signal classes. Each row states what a signal **MAY** carry (operational
metadata) and what it **MUST NOT** carry (anything in
`prohibited_telemetry_fields`, §3). The only correlation identifier permitted
across any signal is the opaque `job_id`.

| Signal | MAY carry | MUST NOT carry |
| --- | --- | --- |
| **Structured logs** | `job_id`, `state`, `freshness_mode`, `error_code`, `attempt`, `row_count` (aggregate count only), latency/duration in ms, HTTP status, route template (e.g. `/v1/resolve`), region, revision/digest | Request bodies, vendor identity, inventory rows, uploaded inventory, tool arguments, candidate URLs, free-text vendor names, raw query strings |
| **Metrics** | Counters/histograms keyed on **bounded low-cardinality labels**: route template, HTTP status class, `error_code`, `state`, `freshness_mode`, queue name | Any high-cardinality or content-derived label — no `job_id` as a label, no vendor identity, no candidate URL, no per-request bodies |
| **Traces** | Span names from a fixed allow-list (`api.read`, `verify.enqueue`, `verify.execute`, `fetch.safe`), `job_id` as the single correlation attribute, timing, span status | Span attributes derived from request bodies, inventory rows, vendor identity, tool arguments, or fetched/candidate URLs (record only that a safe fetch occurred, not its target) |
| **Alerts** | Alert name, firing SLI, threshold, current value, route template, region, `job_id` count (aggregate) | Any payload sample, vendor identity, candidate URL, or inventory excerpt in the alert body |

`job_id` may appear in logs and as a trace correlation attribute, but **never as a
metric label** (it is unbounded cardinality). Logs are structured JSON; sampling
of verbose spans is allowed but never lowers the integrity of the prohibited-field
rule.

**Log residency.** Keeping logs in the primary region is **explicitly configured**,
not automatic: on GCP this means provisioning **regional log buckets and routing the
`_Default` sink** to them (and disabling the global default where required). This is
an infrastructure-slice task (WP-02G) with acceptance evidence, not an assumed
default — consistent with the "no inventory/job/result/log/backup crosses regions"
boundary in the decision report §2.

## 2. Prohibited telemetry fields

These fields **MUST NEVER** appear in any log line, metric label, or trace
attribute. This is the verbatim `prohibited_telemetry_fields` list from the
contract and inherits the ADR-0001 transient-input / minimal-leakage boundary:

- `request_body`
- `vendor_identity`
- `inventory_row`
- `uploaded_inventory`
- `tool_arguments`
- `candidate_url`

**Generic-error rule.** External error responses are **stable and generic**: a
fixed `error_code` plus a safe message, with **`job_id` as the only correlation
id**. No internal detail, stack frame, payload echo, vendor name, or candidate URL
crosses the boundary. A maintainer triaging an incident correlates by `job_id`
alone; the linkage from `job_id` to anything submitted is never persisted in
telemetry (the job record itself is minimised and TTL-deleted — see decision §7).
Because the job-record schema is `additionalProperties: false`, a leaked field
fails validation rather than being silently logged.

## 3. Service-level indicators (SLIs)

| SLI | Definition | Source signal |
| --- | --- | --- |
| **Read API availability** | Successful `/healthz` + `/readyz` probes / total probes | Synthetic probe + LB health metric |
| **Cached `/v1` p95 latency** | 95th-percentile server latency for cached-mode `/v1` reads (pinned pack, no egress) | Request-latency histogram, `freshness_mode=cached` |
| **Verify-job completion rate** | `completed` jobs / (`completed` + `failed`), excluding upstream-vendor-outage failures | `state` transition counters |
| **Verify-job p95 duration** | 95th-percentile wall time from `received` → terminal state | Job-duration histogram |
| **Error rate** | 5xx + internal `error_code` responses / total responses | HTTP status-class counter |
| **Queue depth** | Jobs currently `queued` (not yet `executing`) | Queue/backlog gauge |
| **Queue age** | Oldest `queued` job age in seconds | Queue oldest-age gauge |

Availability is measured against the read API; the **static GitHub Pages layer is
the always-on floor** (decision §10) and is outside these SLIs by design — it must
keep serving even when every hosted SLI is breached.

## 4. Service-level objectives (SLOs)

> **PROPOSED and maintainer-tunable.** These are starting targets, not commitments.
> A maintainer adjusts them once real traffic and provider behaviour are observed;
> they are deliberately conservative for a solo-operated, low/bursty workload.

| Objective | Proposed target | Window | Notes |
| --- | --- | --- | --- |
| Read API availability | **99.5%** | monthly | Static layer is the floor below this |
| Cached `/v1` p95 latency | **< 800 ms** | rolling 30d | Cached path only; verify is async, not latency-bound |
| Verify-job success rate | **≥ 99%** | monthly | **Excludes upstream vendor outages** (counted as `source_unavailable`, not failure) |
| Error rate | **< 1%** of responses | rolling 24h | Generic errors only; informs the latency/error alert |

Upstream vendor-site outages are reported honestly as `source_unavailable` /
`verification_inconclusive` (decision §10) and **do not count against** the
verify-job SLO — OpenVA never fabricates a verdict to protect a number.

## 5. Alert thresholds and routing

All alerts route to a single **maintainer notification path** (e.g. email + chat
webhook); there is no on-call rotation for a solo operator. Thresholds below are
**concrete examples** and are tunable alongside the SLOs.

| Alert | Example threshold | Severity | Routes to |
| --- | --- | --- | --- |
| **Error-rate** | Error rate > 5% over 5 min, or any sustained 5xx burst | High | Maintainer path |
| **Latency** | Cached `/v1` p95 > 1500 ms over 10 min (SLO 800 ms breached with margin) | Medium | Maintainer path |
| **Availability** | 2 consecutive failed `/readyz` probes, or < 99.5% over rolling 1h | High | Maintainer path |
| **Queue saturation** | Queue depth > `OPENVA_MAX_ACTIVE_JOBS`, or oldest `queued` age > 120 s | Medium | Maintainer path → load-shed (return cached + `queued`/`rate_limited`) |
| **Cost / budget** | Spend ≥ 50% (warn) / ≥ 80% (page) of the maintainer-set monthly ceiling | High | Maintainer path → arm kill-switch |
| **Abuse** | Per-client request rate exceeds the rate-limit ceiling for > 5 min, or sudden request-volume spike vs baseline | High | Maintainer path → consider kill-switch |

Alert bodies carry only the firing SLI, threshold, current value, and aggregate
`job_id` counts — never a payload sample, vendor identity, or candidate URL (§2).

## 6. Cost and abuse monitoring

**No platform offers a hard spend cap** (decision §11). The engineered ceiling is a
deliberate low instance/concurrency cap **+** edge rate limiting **+** a
**budget-alert → automation → kill-switch** chain:

- **Budget alerts** fire at maintainer-set fractions of the monthly ceiling (e.g.
  50% warn, 80% page). The 80% (or a hard 100%) alert is the trigger that **arms /
  invokes the kill-switch** — disabling `verify` and candidate-ingress while the
  static read layer keeps serving.
- **Per-client rate-limit metrics**: counters for accepted vs rejected requests
  per client key, and a gauge of clients currently throttled. These detect abuse
  (a single client hammering `verify`) before it consumes the budget. Labels stay
  low-cardinality — client identity is reduced to an opaque key class, never a raw
  identifier, and never a prohibited field.
- **Scale-bounded by design**: instance/concurrency caps and the per-job execution
  timeout bound the *rate* of worst-case spend even before an alert fires; the alert
  chain is the backstop, not the only control.
- **Budget-alert lag is real**: provider budget alerts can lag (often hours) and the
  Cloud Run instance cap is soft (briefly exceedable on spikes), so the kill-switch
  is not instantaneous. The accepted worst-case overrun window
  (`instance_cap × cost-rate × (alert lag + kill-switch exec time)`) is quantified
  in [`hosted-deployment-cost-envelope.md`](hosted-deployment-cost-envelope.md); the
  instance cap + edge rate limit are what actually bound it.

## 7. Dashboards and SLO-breach → kill-switch

A single maintainer dashboard (future) would surface:

| Panel | Shows |
| --- | --- |
| **Availability & probes** | `/healthz` + `/readyz` success rate, current SLO burn |
| **Cached read latency** | `/v1` cached p50/p95/p99 vs the 800 ms line |
| **Verify pipeline** | Completion rate, p95 duration, state distribution (`received`/`queued`/`executing`/`completed`/`failed`); expiry is time-based (`410` after `expires_at`), not a state |
| **Queue health** | Depth + oldest-age gauges with the saturation threshold marked |
| **Error budget** | Rolling error rate vs the 1% line and remaining monthly budget |
| **Cost & abuse** | Spend vs ceiling, budget-alert state, throttled-client count |

**Breach → response.** A sustained SLO breach (availability, error budget) or a
cost-ceiling breach is a **rollback / kill-switch trigger**: redeploy the prior
immutable image, or disable `verify` + candidate-ingress so the static layer
becomes the terminal safe state ("hosted disabled, static layer serving"). The
exact decision tree, credential-revocation sequence, and recovery steps live in
the operations runbook: [`hosted-deployment-runbook.md`](hosted-deployment-runbook.md)
(authored in the staging/observability slice, `WP-02H`). No dashboard, alert, or
kill-switch exists until that slice executes against provisioned infrastructure.
