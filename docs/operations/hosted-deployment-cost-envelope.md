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

Three load regimes, all marked `[confirm]` because rates and free grants change.

| Regime | Cloud Run (baseline) | AWS Lambda (container) | Azure Container Apps |
| --- | --- | --- | --- |
| **IDLE** (~0 traffic) | Scale-to-zero → ≈ `$0` compute; cents for secret store + tiny TTL job store + registry storage. Perpetual free tier likely covers idle entirely. `~$0–low cents/mo` `[confirm]` | True `$0` idle (no warm instance billed); ECR image storage only. `~$0–low cents/mo` `[confirm]` | Scale-to-zero → ≈ `$0` within monthly free grant; companions in cents. `~$0–low cents/mo` `[confirm]` |
| **NORMAL** (light, bursty public read; occasional verify job) | Free tier likely absorbs idle + light; spillover variable. `~$0–single-digit $/mo` `[confirm]` | On-demand request + GB-s billing; low at this volume. `~$0–low single-digit $/mo` `[confirm]` | Free grant covers light use; companions (Cosmos/Service Bus) tend to dominate. `~$0–a few $/mo` `[confirm]` |
| **ABUSIVE** (sustained hammering / scripted flood) | **Highest unbounded risk**: per-request autoscaling can fan out instances and bill linearly with traffic *unless* `max-instances` caps it. Bounded only by the engineered ceiling (§4–§5). | **Strongest hard throttle**: reserved/maximum concurrency + API Gateway usage-plan quota reject excess *before* compute, flattening the worst case. | Bounded by `maxReplicas`; excess sheds rather than scaling without limit. Worst case is `maxReplicas` running continuously. |

Read across: at IDLE and NORMAL all three sit near zero. They diverge under
ABUSIVE — and that divergence is the entire reason for §4.

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

Net shape: the baseline is **almost entirely variable** (scale-to-zero), with a
thin near-fixed floor of cents for companions. There is no always-on instance
floor to pay for — which is exactly why the bill is bounded by *controls*, not by
a contract.

## 3. The engineered cost ceiling

**No major cloud offers a hard spend cap on a normal paid account.** GCP, AWS,
and Azure budgets are **alerts and notifications, not enforcement** — they tell
you that you have spent money; they do not stop spending. Fly offers neither a
hard cap nor a native scale-to-zero story for this shape. So "set a $X limit and
walk away" is **not available** on any candidate provider.

The real ceiling is therefore **engineered**, not purchased — a deliberate
combination of three independent layers, each of which alone is insufficient:

1. **Instance / concurrency cap** — bound the maximum compute that *can* run
   (`max-instances` on Cloud Run; reserved/maximum concurrency on Lambda;
   `maxReplicas` on ACA). This converts an unbounded autoscale into a *known
   worst-case running cost*: at most N instances × the regime rate.
2. **Edge rate limiting** — reject abusive traffic at the gateway/edge *before*
   it reaches compute (decision §8), so the cap above is rarely approached and
   floods cost a rejection, not a request.
3. **Budget alert → automation kill-switch** — a budget threshold that, on
   breach, triggers automation to fire the existing `admin_kill_switch`
   (disable verify + candidate-ingress; the static layer keeps serving, decision
   §10). This is the only layer that turns "money spent" into "spending stopped."

Together these form the ceiling: layer 1 caps the *rate* of spend to a known
worst case, layer 2 keeps normal operation far below it, and layer 3 converts an
alert into an actual stop. Remove any one and the bill is no longer bounded.

## 4. Controls preventing an unbounded bill

Concrete, low, deliberately conservative starting values — all `[confirm]`
against the chosen provider/region and tunable after staging observation:

| Control | Mechanism | Proposed starting value `[confirm]` | Effect |
| --- | --- | --- | --- |
| Instance / concurrency cap | `max-instances` (Cloud Run) / reserved+max concurrency (Lambda) / `maxReplicas` (ACA) | Deliberately low, e.g. **`max-instances = 3`** (Lambda max concurrency comparable) | Hard ceiling on worst-case running compute. |
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
| 4 | Instance/concurrency cap value | Sets the hard worst-case running cost (§3 layer 1) | Maintainer decision + provider limits |
| 5 | Spend-ceiling value (`$/mo`) | The number the kill-switch defends (§4) | Maintainer risk tolerance |
| 6 | Budget-alert threshold(s) | Early-warning point under the ceiling (§3 layer 3) | Maintainer decision |
| 7 | Egress pricing for verify-mode fetch | Confirms egress is non-material at expected volume | Provider egress pricing |

Until items 1–7 are confirmed and the §4 controls are configured, the hosted
resolver remains decision-only and unprovisioned per ADR-0006.
