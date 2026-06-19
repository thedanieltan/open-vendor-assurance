# Hosted deployment threat model

Threat model for the bounded hosted resolver ([ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md),
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)).
It **extends, and does not restate,** the existing boundaries:
- inbound transport surface — [`remote-mcp-threat-model.md`](remote-mcp-threat-model.md);
- outbound fetch surface — [`ssrf-fetch-boundary.md`](ssrf-fetch-boundary.md).

**Decision-only.** No infrastructure is provisioned and no hosted endpoint is
live. Output stays non-advisory and public-source-only.

## Trust boundaries

1. **Public client → public API.** Untrusted input (vendor identities, batch
   rows). Validated, bounded, rate-limited; bodies never logged.
2. **API → worker (queue).** Internal; messages carry `job_id` only, no submitted
   content.
3. **Worker → vendor websites (egress).** Untrusted third parties. All egress via
   `build_safe_verify_fetcher` bound to vendor authority (see ssrf-fetch-boundary).
4. **Service → GitHub (candidate write-back).** Privileged but discovery-only:
   opens candidate-intake PRs; no merge, no `data/**` write.
5. **Service → secret store / cloud APIs.** Workload identity for cloud APIs; the
   GitHub App key is a stored secret (GitHub Apps cannot use OIDC).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Arbitrary-URL fetch / SSRF | No endpoint accepts a caller URL; all egress through `build_safe_verify_fetcher`, DNS-pinned, private/loopback rejected, same-authority redirects, bounded bytes + deadline. SSRF-negative tests gate the transport slice. |
| Portal / CAPTCHA / WAF / paywall bypass | Never attempted; gated pages recorded as access-state facts only (public-sources-only policy). |
| Submitted-content leakage (logs/traces/metric labels) | `prohibited_telemetry_fields` (request bodies, vendor identity, inventory rows, uploaded inventory, tool arguments, candidate URLs) are never emitted; job records are minimised (`additionalProperties: false`); errors are generic with a `job_id` correlation id only. |
| Inventory persistence beyond the request | Uploaded inventory is processed in memory only; only the minimised job record + aggregate metrics persist; job + result TTL-deleted (default 24h). |
| Oversized / abusive request | Body cap, row cap, max-active-jobs, per-job timeout, edge + app rate limiting; rejected before work. |
| Denial of service / cost blowout | Instance/concurrency cap + rate limit + budget-alert kill-switch (no vendor hard cap exists); queue saturation sheds verify load, never grows unbounded. |
| Catalogue mutation via the hosted path | The service only *proposes* candidates via the existing ingress; no `data/**` or `main` write; discovery ≠ decision ≠ merge. |
| Stale-as-live result | Live results labelled and distinct; degradation serves cached/static labelled `from_cache`; reproducible catalogue unchanged. |
| GitHub App key compromise | Key in a managed secret store (never repo/browser/artifacts/logs); least-privilege App (contents + pull-requests only, no merge); remote signing where supported; break-glass: revoke token, disable ingress, rotate, roll back image. |
| Production credential in browser/repo/artifacts | Browser holds no service or GitHub credential; CI holds no production secret in the repo; secrets only in the managed store. |
| Advisory / prompt injection via vendor strings | Inputs treated as data only, never executed/interpolated; output carries `not_advice: true` + `X-OpenVA-Advisory-Boundary: non_advisory`; prohibited-claims vocabulary enforced on output. |
| Snapshot substitution / integrity | `/readyz` 200 only after pack loaded + integrity verified; content digests SHA-256; static layer reproducible. |
| Supply-chain / dependency drift | Pinned dependencies + pinned base image; dependency + image scanning in CI; immutable digest-pinned deploys. |
| Region/data exfiltration | Single primary region; no inventory/job/result/log/backup crosses regions in the baseline. |

## Fail-closed posture

On any integrity, credential, leakage, or egress-safety failure the service
returns a controlled generic error and degrades to the static/cached layer; it
never weakens a boundary to keep serving. The kill-switch disables verify +
ingress independently of the read path; the static layer is the always-on safe
floor. These mirror the fail-closed posture in `remote-mcp-threat-model.md`.

## Out of scope

Provisioning, provider/credential acceptance, DNS/TLS, and the transport
implementation are out of scope for this decision package; each follow-on slice
carries its own acceptance tests (SSRF-negative, leakage, rate-limit, kill-switch)
in [`../operations/hosted-deployment-implementation-plan.md`](../operations/hosted-deployment-implementation-plan.md).
