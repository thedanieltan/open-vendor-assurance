# Hosted deployment threat model

Threat model for the bounded hosted resolver ([ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md),
[ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md)).
It **extends, and does not restate,** the existing boundaries:
- inbound transport surface — [`remote-mcp-threat-model.md`](remote-mcp-threat-model.md);
- outbound fetch surface — [`ssrf-fetch-boundary.md`](ssrf-fetch-boundary.md).

**Decision-only.** No infrastructure is provisioned and no hosted endpoint is
live. Output stays non-advisory and public-source-only.

## Trust boundaries

1. **Public client → edge → public API.** Untrusted input (vendor identities,
   batch rows) arrives only through the rate-limiting edge; the origin's ingress is
   restricted to the edge so direct ingress cannot bypass it. Validated, bounded;
   bodies never logged.
2. **API → worker (queue).** Internal; messages carry `job_id` only — **no
   submitted content and no request envelope**.
3. **API/worker → transient request & result stores.** The submitted input lives
   in a transient request envelope (keyed by `job_id`) and the result in a
   transient result blob; both are encrypted at rest, access-controlled by workload
   identity (API writes, worker reads), and TTL-deleted.
4. **Worker → vendor websites (egress).** Untrusted third parties. All egress via
   `build_safe_verify_fetcher` bound to vendor authority (see ssrf-fetch-boundary).
5. **Service → GitHub (candidate write-back).** Privileged but discovery-only:
   opens candidate-intake PRs; no merge, no `data/**` write.
6. **Service → secret store / cloud APIs.** Workload identity for cloud APIs; the
   GitHub App key is a stored secret (GitHub Apps cannot use OIDC).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Arbitrary-URL fetch / SSRF | No endpoint accepts a caller URL; all egress through `build_safe_verify_fetcher`, DNS-pinned, private/loopback rejected, same-authority redirects, bounded bytes + deadline. SSRF-negative tests gate the transport slice. |
| Portal / CAPTCHA / WAF / paywall bypass | Never attempted; gated pages recorded as access-state facts only (public-sources-only policy). |
| Submitted-content leakage (logs/traces/metric labels) | `prohibited_telemetry_fields` (request bodies, vendor identity, inventory rows, uploaded inventory, tool arguments, candidate URLs, **`authorization_header`**, **`job_token`**) are never emitted; job records are minimised (`additionalProperties: false`); errors are generic with a `job_id` correlation id only. |
| Submitted input lost / unavailable to the worker | The worker reconstructs the request from the **transient request envelope** keyed by `job_id` (the queue carries no content). The envelope is the single transient home for submitted input. |
| Transient request/result store exposure | Envelope + result blob encrypted at rest; access-controlled by workload identity (API writes, worker reads); deleted on the terminal transition with an object-lifecycle TTL backstop; never published, never in canonical records. |
| Inventory persistence beyond the request | Uploaded inventory lives only in the transient envelope, deleted on completion/failure/abandonment (+ TTL backstop); only the minimised job record + aggregate metrics persist. |
| Result-access abuse / IDOR via `job_id` | `job_id` is a loggable correlation id, **not** an access credential. Result polling/retrieval requires the one-time high-entropy `job_token` capability, never logged and stored only as `job_token_digest`. Guessing `job_id` does not grant access. |
| `job_token` capture in transit / at the edge | The capability is transported **header-only** as `Authorization: Bearer <job_token>` — **forbidden** in the URL, query string, path, or redirect target, so it never lands in an access log, the edge proxy's request line, a referrer header, or browser history. The API and edge proxy **redact** the `Authorization` header in all telemetry (`authorization_header` + `job_token` are `prohibited_telemetry_fields`); the server verifies it by **constant-time** comparison against `job_token_digest`; an auth failure returns a **generic** code that never echoes the presented value; the CORS allow-list constrains which origins may send it. The token is **not rotated in v1** (single-use, short TTL bounded by `expires_at`). |
| Cross-caller capability leak via content dedup | **No deduplication in v1** — every request creates a new job, and there is no content-derived dedup key (a SHA-256 of low-entropy vendor names is dictionary-testable and would let one caller reproduce another's request to obtain a capability to their job/result). Any future idempotency option must bind the key with a server-keyed HMAC scoped to an authenticated caller, with replay/conflict/expiry defined — never a plain content digest. |
| Rate-limit / edge bypass | The origin's ingress is restricted to the edge (e.g. `internal-and-cloud-load-balancing`); direct origin requests are refused, so the edge rate limit cannot be bypassed. |
| Expired-job access | Three-phase semantics: pre-expiry needs the `job_token`; once `now >= expires_at` and the record is still retained → content-free `410 Gone`; after the record (with `expires_at` + `job_token_digest`) is physically deleted → content-free `404 Not Found`. A 404 leaks nothing — `job_id` is not a credential and is indistinguishable from an unknown id. No stale result is served. |
| Oversized / abusive request | Body cap, row cap, max-active-jobs, per-job timeout, edge + app rate limiting; rejected before work. |
| Denial of service / cost blowout | Instance/concurrency cap + rate limit + budget-alert kill-switch (no vendor hard cap exists); queue saturation sheds verify load, never grows unbounded. |
| Catalogue mutation via the hosted path | The service only *proposes* candidates via the existing ingress; no `data/**` or `main` write; discovery ≠ decision ≠ merge. |
| Stale-as-live result | Live results labelled and distinct; degradation serves cached/static labelled `from_cache`; reproducible catalogue unchanged. |
| Stranded `executing` job / lost worker | The worker holds a heartbeated **execution lease** (`lease_owner` + `lease_expires_at`) while `executing`; a **watchdog** recovers a stale lease (CAS `executing → queued` re-dispatch, else `executing → failed` `execution_timeout`). A live lease is never preempted; a duplicate delivery to a live-leased job is acked-and-dropped. A crashed worker never strands a job past the lease window. |
| GitHub App key compromise / over-broad access | Key in a managed secret store (never repo/browser/artifacts/logs); **held and used ONLY by the candidate-ingress component** — the internet-facing API and the verify worker hold no GitHub credential (least-privilege `access_matrix`); least-privilege App (contents + pull-requests only, no merge); remote signing where supported; break-glass: revoke token, disable ingress, rotate, roll back image. |
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
