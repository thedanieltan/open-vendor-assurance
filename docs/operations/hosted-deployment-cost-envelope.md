# Hosted public-read cost envelope

Cost analysis for **WP-OPENVA-AI-NATIVE-DISTRIBUTION-02**, expanding §11 of the
[hosted-deployment decision](hosted-deployment-decision.md) and the `spend_ceiling`
maintainer decision in [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).
It records the *engineered* cost ceiling for the bounded hosted resolver accepted
in posture by [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)
and decided architecturally in [ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md).

**This is analysis and architecture only.** No production infrastructure is
provisioned, no provider is accepted, no budget or alert is configured, and no
hosted OpenVA endpoint is live. The figures here are envelopes and ranges, not
quotes. OpenVA is a public-source-only, metadata-first registry; **this document
is operational planning, not financial, procurement, or advisory guidance**, and
nothing here is a non-advisory exception to the ADR-0001 posture.

Every per-unit price and free-tier quota below shifts by region and over time.
Exact dollar figures are deliberately marked `[confirm]` and MUST be re-derived
in the provider's own pricing calculator before any provisioning (§6).

## 1. Cost envelopes (qualitative + rough ranges)

> **Baseline rationale, reassessed across review #402.** The mandatory rate-limiting edge gives Cloud Run a
> **~$24/mo fixed floor** (external HTTPS LB ~$18/mo + Cloud Armor ~$5–6/mo); AWS
> API Gateway throttling is **best-effort, not a hard cost cap**, and **no provider
> offers a hard spend cap**, so cost is roughly a wash and **not** the deciding
> factor. The baseline is **Google Cloud Run** with a **long-running container
> worker** chosen primarily for **portability** (it runs the existing container
> unchanged) and **execution headroom**: the hosted **live-verify** limit is grounded
> in the resolver's real fetch model — `max_verify_rows 20`, each row up to 4 serial
> fetches per source type at `SAFE_TIMEOUT_SECONDS` = 20 s, worst case **~12 min** —
> which fits Cloud Run's 30-min Cloud Tasks dispatch deadline with ~2× headroom. AWS
> Lambda's **15-min** ceiling gives less headroom for the same worst case (it is
> **not** claimed impossible — the earlier "500-row batch can't fit Lambda" framing
> is withdrawn; the 500-row figure is the *cached* batch, which does no live fetch).
> A larger verify limit is a **separate future WP** (parent/child decomposition),
> not assumed here. Lambda stays a `$0`-idle alternative; ACA is the container
> alternative. All figures `[confirm]` — rates and free grants change.

| Regime | Google Cloud Run (baseline) | Azure Container Apps (alternative) | AWS Lambda (alt — tighter 15-min headroom) |
| --- | --- | --- | --- |
| **IDLE** (~0 traffic) | Scale-to-zero ≈ `$0` *compute* **plus the external HTTPS LB + Cloud Armor fixed floor** (decision §4/§8) — idle is **~$24/mo** + cents, not ≈ `$0`. `~$24/mo + cents` `[confirm]` | Scale-to-zero ≈ `$0` compute within free grant + an always-on ingress/gateway (Front Door/APIM) cost. `~low single-digit $/mo` `[confirm]` | True `$0` idle (no warm instance); **API Gateway has no fixed monthly floor**; ECR image storage cents. `~$0–low cents/mo` `[confirm]` |
| **NORMAL** (light, bursty public read; occasional verify job) | Free tier likely absorbs light compute, but the **~$24/mo edge floor dominates** at this volume. `~$24/mo + spillover` `[confirm]` | Free grant covers light use; companions (Cosmos/Service Bus) + edge dominate. `~$0–a few $/mo + edge` `[confirm]` | On-demand request + GB-s billing; low at this volume; API Gateway per-request. `~$0–low single-digit $/mo` `[confirm]` |
| **ABUSIVE** (sustained hammering / scripted flood) | **Soft-cap risk**: per-request autoscaling can fan out; `max-instances` is a *soft* cap, so bounded by the engineered spend-rate controls (§3–§4) + Cloud Armor rate limit, not a hard ceiling. | Bounded by `maxReplicas` (hard at compute); excess sheds rather than scaling without limit. | Reserved concurrency caps **Lambda compute** (hard), but **API Gateway throttling/quotas are best-effort** (AWS: do not rely on usage plans for cost control), so the public edge is **not** a hard cost cap. |

Read across: under ABUSIVE, every provider relies on the engineered bounded-spend-
rate (§3) — none gives a hard spend cap.

## 2. Fixed vs variable cost breakdown

| Component | Cost shape | Notes |
| --- | --- | --- |
| Compute (API + async worker) | **Variable** | Scale-to-zero on all three baselines → no idle compute charge; cost tracks actual request volume / GB-s. |
| Secret store (GitHub App key) | Near-fixed, **cents** | A handful of secret versions; flat low monthly cost. |
| TTL job/result store | **Variable**, cents at low volume | Minimised job records, default 24h TTL (decision §7); on-demand/serverless tiers bill on tiny usage. |
| Queue (worker dispatch) | **Variable**, cents | Low message volume at OpenVA traffic levels. |
| Registry storage (OCI image) | Near-fixed, **cents** | One immutable digest-pinned image plus a short tail of prior digests for rollback. |
| Egress (verify-mode fetch) | **Variable** | Small, bounded by the SSRF fetch size/deadline limits (decision §8); not a material driver at expected volume. |
| Domain / TLS | Fixed, external | Maintainer-owned domain renewal; provider-managed certificate is included (decision §4). |
| **Edge HTTPS load balancer + rate limiting** | **Fixed monthly floor** | Required to enforce edge rate limiting and restrict origin ingress (decision §4/§8). On GCP this is an external Application Load Balancer + Cloud Armor — an always-on hourly/rule charge, so the baseline is **not** a pure scale-to-zero ≈`$0` idle. `[confirm]` |

Net shape: compute is **variable** (scale-to-zero), but the **edge load balancer is
an always-on fixed floor** — so the realistic baseline is "LB floor + ≈`$0`
compute," not ≈`$0`. The bill is bounded by *controls* (the engineered spend-rate
bound, §3), not by a vendor contract.

## 3. The engineered bounded spend rate (not a hard cap)

**No major cloud offers a hard spend cap on a normal paid account.** GCP, AWS,
and Azure budgets are **alerts and notifications, not enforcement** — they tell
you that you have spent money; they do not stop spending, and they **lag (often
hours)**. Fly offers neither a hard cap nor a native scale-to-zero story for this
shape. So "set a $X limit and walk away" is **not available** on any candidate
provider. Worse, on Cloud Run `max-instances` is a **soft** cap that may be
**briefly exceeded during traffic spikes** (and is complicated by traffic split
across revisions) — so even the instance cap is not an absolute guarantee.

The design therefore bounds the **rate** of spend; it does not purchase a ceiling.
Three independent layers, each insufficient alone:

1. **Instance / concurrency cap** — bound the compute that can run (`max-instances`
   on Cloud Run — soft; reserved/maximum concurrency on Lambda — hard;
   `maxReplicas` on ACA — hard). This converts unbounded autoscale into a *known
   worst-case running rate*: ~N instances × the regime rate.
2. **Edge rate limiting** — reject abusive traffic at the HTTPS-LB edge *before* it
   reaches compute (decision §8), with origin ingress restricted to the edge so it
   cannot be bypassed. Floods cost a rejection, not a request.
3. **Budget alert → automation kill-switch** — a budget threshold that, on breach,
   triggers automation to fire `admin_kill_switch` (disable verify + ingress; the
   static layer keeps serving, decision §10). The only layer that turns "money
   spent" into "spending stopped."

**Worst-case overrun window.** Because alerts lag and the cap is soft, spend is not
stopped instantly. The bounded worst case before the kill-switch executes is
roughly:

```
overrun ≈ instance_cap × per-instance cost-rate × (budget-alert lag + kill-switch exec time)
```

Layer 1 bounds the rate, layer 2 keeps normal load far below it, and layer 3 stops
spend after a bounded, non-zero delay. This is a **bounded spend rate with a known
overrun window**, not an absolute ceiling — a trade-off the maintainer accepts
(Lambda's hard reserved-concurrency throttle is the alternative if the soft Cloud
Run cap is unacceptable).

## 4. Controls preventing an unbounded bill

Concrete, low, deliberately conservative starting values — all `[confirm]`
against the chosen provider/region and tunable after staging observation:

| Control | Mechanism | Proposed starting value `[confirm]` | Effect |
| --- | --- | --- | --- |
| Instance / concurrency cap | `max-instances` (Cloud Run — **soft**, briefly exceedable) / reserved+max concurrency (Lambda — **hard**) / `maxReplicas` (ACA — **hard**) | Deliberately low, e.g. **`max-instances = 3`** (Lambda max concurrency comparable) | Bounds the *rate* of worst-case compute; on Cloud Run it is a soft bound, not an absolute ceiling. |
| Edge rate limit | Gateway/edge per-client + global rate limit (decision §8) | e.g. **60 req/min per client**, low global ceiling | Floods rejected before doing work. |
| App-level active-job cap | `OPENVA_MAX_ACTIVE_JOBS` (transport slice) | Low bounded value | Caps concurrent verify work regardless of edge. |
| Budget alert threshold | Provider budget (alert only) | e.g. **first alert at a low single-digit-$ monthly figure** | Early warning well under any tolerable spend. |
| Kill-switch trigger | Budget-alert → automation → `admin_kill_switch` | Fire on **budget breach of the ceiling value** | Disables verify + ingress; static layer serves on. |
| Spend-ceiling value | Maintainer-chosen monthly tolerance | e.g. **a low, explicit `$/mo` ceiling** | The number the kill-switch defends. |

The kill-switch terminal state is "hosted disabled, static layer serving"
(decision §10/§12), which is always reachable — so the worst case is degraded
service, never an unbounded bill.

## 5. Numbers a maintainer MUST confirm before provisioning

These shift by region and over time; **do not treat any figure in this document
as authoritative**. Re-derive each in the provider's own calculator at
provisioning time:

| # | Number to confirm | Why it matters | Source of truth |
| --- | --- | --- | --- |
| 1 | Region compute + request rates (per-request, GB-s, per-vCPU/GiB) | Drives the NORMAL/ABUSIVE envelope and the worst-case cap math | Provider pricing calculator, chosen region |
| 2 | Free-tier / free-grant quotas (and whether perpetual) | Determines whether IDLE + light truly land at `$0` | Provider free-tier page, chosen region |
| 3 | Companion rates (secret store, TTL store, queue, registry storage, egress) | The thin near-fixed floor; can dominate at very low volume | Provider pricing per service |
| 4 | Instance/concurrency cap value | Bounds the worst-case running-cost rate (§3 layer 1; soft on Cloud Run, hard on Lambda/ACA) | Maintainer decision + provider limits |
| 4b | Edge HTTPS load balancer fixed monthly cost | The always-on floor that makes idle ≠ ≈`$0` (§2) | Provider LB pricing, chosen region |
| 5 | Spend-ceiling value (`$/mo`) | The number the kill-switch defends (§4) | Maintainer risk tolerance |
| 6 | Budget-alert threshold(s) | Early-warning point under the ceiling (§3 layer 3) | Maintainer decision |
| 7 | Egress pricing for verify-mode fetch | Confirms egress is non-material at expected volume | Provider egress pricing |

Until items 1–7 are confirmed and the §4 controls are configured, the hosted
resolver remains decision-only and unprovisioned per ADR-0006.
